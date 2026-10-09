"""Connector product registry (plan sprint-4/19, section 9).

Products come from the environment only (secrets never live in the DB). A
product missing any required value is listed as ``misconfigured`` and resolves
to ``None`` everywhere, so its endpoints answer a uniform 404 without saying
which part is missing.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping, Optional

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

    def __repr__(self) -> str:  # never leak secrets through logs/tracebacks
        return f"Product(key={self.key!r})"


@dataclass(frozen=True)
class ProductStatus:
    key: str
    status: str  # "ok" | "misconfigured"
    product: Optional[Product] = None
    partial: Optional[Product] = None  # misconfigured: whatever was set (admin view only)


_env_override: Optional[Mapping[str, str]] = None


def set_env_for_tests(env: Optional[Mapping[str, str]]) -> None:
    global _env_override
    _env_override = env


def _env() -> Mapping[str, str]:
    return _env_override if _env_override is not None else os.environ


def _val(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def load_products(env: Mapping[str, str]) -> dict[str, ProductStatus]:
    out: dict[str, ProductStatus] = {}
    for raw in _val(env, "CONNECTOR_PRODUCTS").split(","):
        key = raw.strip().lower()
        if not key or key in out:
            continue
        if not _KEY_RE.match(key):
            out[key] = ProductStatus(key=key, status="misconfigured")
            continue
        prefix = f"CONNECTOR_{key.upper()}_"
        vals = {name: _val(env, prefix + name) for name in _REQUIRED}
        if not all(vals.values()):
            out[key] = ProductStatus(key=key, status="misconfigured", partial=Product(
                key=key, display_name=_val(env, prefix + "DISPLAY_NAME") or key,
                tenant_slug=vals["TENANT_SLUG"], connection_id=vals["CONNECTION_ID"],
                consent_url=vals["CONSENT_URL"], api_base_url=vals["API_BASE_URL"].rstrip("/"),
                ss_to_product_secret=vals["SS_TO_PRODUCT_SECRET"],
                product_to_ss_secret=vals["PRODUCT_TO_SS_SECRET"]))
            continue
        product = Product(
            key=key,
            display_name=_val(env, prefix + "DISPLAY_NAME") or key,
            tenant_slug=vals["TENANT_SLUG"],
            connection_id=vals["CONNECTION_ID"],
            consent_url=vals["CONSENT_URL"],
            api_base_url=vals["API_BASE_URL"].rstrip("/"),
            ss_to_product_secret=vals["SS_TO_PRODUCT_SECRET"],
            product_to_ss_secret=vals["PRODUCT_TO_SS_SECRET"],
            issuer=_val(env, prefix + "ISSUER") or key,
            consent_audience=_val(env, prefix + "CONSENT_AUDIENCE") or f"{key}-connector-consent",
            call_audience=_val(env, prefix + "CALL_AUDIENCE") or f"{key}-connector-api",
        )
        out[key] = ProductStatus(key=key, status="ok", product=product)
    return out


def all_products() -> dict[str, ProductStatus]:
    return load_products(_env())


def get_product(key: str) -> Optional[Product]:
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
