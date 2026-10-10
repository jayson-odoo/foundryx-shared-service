"""Connector product registry (plan sprint-4/19, section 9).

Products and settings come from the database (lane SETTINGS-IN-DB-SS, secrets
Fernet-encrypted) with the environment as the per-field fallback. A product
missing any required value is listed as ``misconfigured`` and resolves to
``None`` everywhere, so its endpoints answer a uniform 404 without saying
which part is missing. Nothing is cached: a saved change applies on the next
request.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DEFAULT_REDIRECT_ALLOWLIST = ["https://claude.ai/api/mcp/auth_callback"]
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_REQUIRED = ("TENANT_SLUG", "CONNECTION_ID", "CONSENT_URL", "API_BASE_URL",
             "SS_TO_PRODUCT_SECRET", "PRODUCT_TO_SS_SECRET")


@dataclass(frozen=True)
class Product:
    key: str
    display_name: str
    tenant_slug: str
    connection_id: str
    consent_url: str
    api_base_url: str
    ss_to_product_secret: str = ""
    product_to_ss_secret: str = ""
    issuer: str = ""
    consent_audience: str = ""
    call_audience: str = ""
    tenant_id: str = ""  # set for database-backed products (owner); env products resolve by slug

    def __repr__(self) -> str:  # never leak secrets through logs/tracebacks
        return f"Product(key={self.key!r})"


@dataclass(frozen=True)
class ProductStatus:
    key: str
    status: str  # "ok" | "misconfigured"
    product: Optional[Product] = None
    partial: Optional[Product] = None  # misconfigured: whatever was set (admin view only)
    sources: dict = field(default_factory=dict)  # FIELD -> database|environment|default|unset|unreadable


_env_override: Optional[Mapping[str, str]] = None


def set_env_for_tests(env: Optional[Mapping[str, str]]) -> None:
    global _env_override
    _env_override = env


_dotenv_cache: tuple[str, float, dict[str, str]] | None = None


def _dotenv_values() -> dict[str, str]:
    """CONNECTOR_* values from ``.env`` in the cwd (same file pydantic Settings
    reads), re-read only when the file changes."""
    global _dotenv_cache
    from pathlib import Path

    from dotenv import dotenv_values

    path = Path(".env").resolve()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _dotenv_cache = None
        return {}
    if _dotenv_cache is None or _dotenv_cache[0] != str(path) or _dotenv_cache[1] != mtime:
        vals = {k: v for k, v in dotenv_values(path).items()
                if k.startswith("CONNECTOR_") and v is not None}
        _dotenv_cache = (str(path), mtime, vals)
    return _dotenv_cache[2]


def _env() -> Mapping[str, str]:
    if _env_override is not None:
        return _env_override
    # real environment wins over the .env file
    return {**_dotenv_values(), **os.environ}


def _val(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


# Product fields, in the env-name spelling. Required ones decide ok/misconfigured.
FIELDS = ("DISPLAY_NAME", "TENANT_SLUG", "CONNECTION_ID", "CONSENT_URL", "API_BASE_URL",
          "SS_TO_PRODUCT_SECRET", "PRODUCT_TO_SS_SECRET", "ISSUER", "CONSENT_AUDIENCE",
          "CALL_AUDIENCE")


def defaults_for(key: str) -> dict[str, str]:
    return {"DISPLAY_NAME": key, "ISSUER": key, "CONSENT_AUDIENCE": f"{key}-connector-consent",
            "CALL_AUDIENCE": f"{key}-connector-api"}


def env_product_keys(env: Mapping[str, str]) -> list[str]:
    out: list[str] = []
    for raw in _val(env, "CONNECTOR_PRODUCTS").split(","):
        key = raw.strip().lower()
        if key and key not in out:
            out.append(key)
    return out


def env_fields(env: Mapping[str, str], key: str) -> dict[str, str]:
    prefix = f"CONNECTOR_{key.upper()}_"
    return {name: _val(env, prefix + name) for name in FIELDS}


def build_status(key: str, vals: Mapping[str, str], *, tenant_id: str = "",
                 sources: Optional[Mapping[str, str]] = None) -> ProductStatus:
    """``vals`` = the explicitly set values (blank = unset); defaults fill the rest."""
    if not _KEY_RE.match(key):
        return ProductStatus(key=key, status="misconfigured", sources=dict(sources or {}))
    d = defaults_for(key)
    v = {name: (vals.get(name) or "") for name in FIELDS}
    product = Product(
        key=key,
        display_name=v["DISPLAY_NAME"] or d["DISPLAY_NAME"],
        tenant_slug=v["TENANT_SLUG"],
        connection_id=v["CONNECTION_ID"],
        consent_url=v["CONSENT_URL"],
        api_base_url=v["API_BASE_URL"].rstrip("/"),
        ss_to_product_secret=v["SS_TO_PRODUCT_SECRET"],
        product_to_ss_secret=v["PRODUCT_TO_SS_SECRET"],
        issuer=v["ISSUER"] or d["ISSUER"],
        consent_audience=v["CONSENT_AUDIENCE"] or d["CONSENT_AUDIENCE"],
        call_audience=v["CALL_AUDIENCE"] or d["CALL_AUDIENCE"],
        tenant_id=tenant_id,
    )
    ok = (all(v[name] for name in _REQUIRED)
          and v["SS_TO_PRODUCT_SECRET"] != v["PRODUCT_TO_SS_SECRET"])
    return ProductStatus(key=key, status="ok" if ok else "misconfigured",
                         product=product if ok else None, partial=None if ok else product,
                         sources=dict(sources or {}))


def load_products(env: Mapping[str, str]) -> dict[str, ProductStatus]:
    """Environment-only view (the fallback layer)."""
    out: dict[str, ProductStatus] = {}
    for key in env_product_keys(env):
        vals = env_fields(env, key)
        sources = {n: ("environment" if vals[n] else "default" if n in defaults_for(key) else "unset")
                   for n in FIELDS}
        out[key] = build_status(key, vals, sources=sources)
    return out


def merge_row(env: Mapping[str, str], key: str, tenant_slug: str, tenant_id: str,
              db_vals: Mapping[str, str], unreadable: frozenset[str] = frozenset()) -> ProductStatus:
    """Per-field precedence: database (non-blank) > environment (only when the
    environment assigns ``key`` to this same tenant) > built-in default. A secret
    the database holds but cannot decrypt stays unset (fail closed)."""
    env_applies = (key in env_product_keys(env)
                   and _val(env, f"CONNECTOR_{key.upper()}_TENANT_SLUG") == tenant_slug)
    ev = env_fields(env, key) if env_applies else {n: "" for n in FIELDS}
    vals: dict[str, str] = {"TENANT_SLUG": tenant_slug}
    sources: dict[str, str] = {"TENANT_SLUG": "database"}
    for name in FIELDS:
        if name == "TENANT_SLUG":
            continue
        if name in unreadable:
            vals[name], sources[name] = "", "unreadable"
        elif (db_vals.get(name) or "").strip():
            vals[name], sources[name] = db_vals[name].strip(), "database"
        elif ev[name]:
            vals[name], sources[name] = ev[name], "environment"
        else:
            vals[name] = ""
            sources[name] = "default" if name in defaults_for(key) else "unset"
    return build_status(key, vals, tenant_id=tenant_id, sources=sources)


def resolve_products(db: "Session") -> dict[str, ProductStatus]:
    """Every product: environment products plus database rows (merged per field)."""
    from .repositories.settings_repository import SettingsRepository

    env = _env()
    out = load_products(env)
    for key, st in SettingsRepository(db).resolved_rows(env).items():
        out[key] = st
    return out


def resolve_product(db: "Session", key: str) -> Optional[ProductStatus]:
    from .repositories.settings_repository import SettingsRepository

    key = (key or "").lower()
    env = _env()
    st = SettingsRepository(db).resolved_row(env, key)
    return st if st is not None else load_products(env).get(key)


def all_products(db: Optional["Session"] = None) -> dict[str, ProductStatus]:
    return resolve_products(db) if db is not None else load_products(_env())


def get_product(key: str, db: Optional["Session"] = None) -> Optional[Product]:
    if db is not None:
        st = resolve_product(db, key)
    else:
        st = load_products(_env()).get((key or "").lower())
    return st.product if st and st.status == "ok" else None


def redirect_allowlist() -> list[str]:
    raw = _val(_env(), "CONNECTOR_REDIRECT_ALLOWLIST")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items or list(DEFAULT_REDIRECT_ALLOWLIST)


def _int(name: str, default: int) -> int:
    try:
        return int(_val(_env(), name) or default)
    except ValueError:
        return default


def call_log_retention_days() -> int:
    return _int("CONNECTOR_CALL_LOG_RETENTION_DAYS", 180)


def manifest_ttl_seconds() -> int:
    return _int("CONNECTOR_MANIFEST_TTL_SECONDS", 900)


def call_timeout_seconds() -> int:
    return _int("CONNECTOR_CALL_TIMEOUT_SECONDS", 15)


def public_base_url() -> str:
    """Base URL for everything the connector emits: CONNECTOR_PUBLIC_BASE_URL
    (tunnel/staging) else the platform setting. No trailing slash."""
    from app.config import settings

    return (_val(_env(), "CONNECTOR_PUBLIC_BASE_URL") or settings.public_base_url).rstrip("/")


def allowed_client_cidrs() -> Optional[str]:
    """Raw CONNECTOR_ALLOWED_CLIENT_CIDRS (None/blank = no allow-list)."""
    return _val(_env(), "CONNECTOR_ALLOWED_CLIENT_CIDRS") or None


# --- per-tenant settings (database > environment > default) ---------------------------

# setting name -> (env var, built-in default as text; "" = none)
TENANT_SETTINGS = {
    "public_base_url": ("CONNECTOR_PUBLIC_BASE_URL", ""),  # default = settings.public_base_url
    "allowed_client_cidrs": ("CONNECTOR_ALLOWED_CLIENT_CIDRS", ""),
    "redirect_allowlist": ("CONNECTOR_REDIRECT_ALLOWLIST", ",".join(DEFAULT_REDIRECT_ALLOWLIST)),
    "manifest_ttl_seconds": ("CONNECTOR_MANIFEST_TTL_SECONDS", "900"),
    "call_timeout_seconds": ("CONNECTOR_CALL_TIMEOUT_SECONDS", "15"),
    "call_log_retention_days": ("CONNECTOR_CALL_LOG_RETENTION_DAYS", "180"),
}
_INT_SETTINGS = ("manifest_ttl_seconds", "call_timeout_seconds", "call_log_retention_days")


@dataclass(frozen=True)
class TenantConfig:
    public_base_url: str
    allowed_client_cidrs: Optional[str]
    redirect_allowlist: list
    manifest_ttl_seconds: int
    call_timeout_seconds: int
    call_log_retention_days: int
    values: dict = field(default_factory=dict)   # name -> effective text ("" = none)
    sources: dict = field(default_factory=dict)  # name -> database|environment|default|unset


def merge_tenant_config(env: Mapping[str, str], db_vals: Mapping[str, object]) -> TenantConfig:
    from app.config import settings

    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    for name, (env_name, default) in TENANT_SETTINGS.items():
        if name == "public_base_url":
            default = settings.public_base_url
        dbv = db_vals.get(name)
        dbv = "" if dbv is None else str(dbv).strip()
        envv = _val(env, env_name)
        if name in _INT_SETTINGS and envv:
            try:
                envv = str(int(envv))
            except ValueError:
                envv = ""  # a malformed env value falls through to the default, as before
        if dbv:
            values[name], sources[name] = dbv, "database"
        elif envv:
            values[name], sources[name] = envv, "environment"
        elif default:
            values[name], sources[name] = default, "default"
        else:
            values[name], sources[name] = "", "unset"
    values["public_base_url"] = values["public_base_url"].rstrip("/")
    allow = [x.strip() for x in values["redirect_allowlist"].split(",") if x.strip()]
    return TenantConfig(
        public_base_url=values["public_base_url"],
        allowed_client_cidrs=values["allowed_client_cidrs"] or None,
        redirect_allowlist=allow or list(DEFAULT_REDIRECT_ALLOWLIST),
        manifest_ttl_seconds=int(values["manifest_ttl_seconds"]),
        call_timeout_seconds=int(values["call_timeout_seconds"]),
        call_log_retention_days=int(values["call_log_retention_days"]),
        values=values, sources=sources)


def tenant_config(db: Optional["Session"], tenant_id: Optional[str]) -> TenantConfig:
    """The effective settings for ``tenant_id`` (None = environment only, used
    where no product resolved, e.g. the allow-list on an unknown product)."""
    db_vals: dict[str, object] = {}
    if db is not None and tenant_id:
        from .repositories.settings_repository import SettingsRepository

        db_vals = SettingsRepository(db).tenant_values(tenant_id)
    return merge_tenant_config(_env(), db_vals)
