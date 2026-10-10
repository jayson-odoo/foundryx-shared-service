"""Connector settings in the database (lane SETTINGS-IN-DB-SS).

Tenant-scoped: a tenant edits only the products it owns (database rows with its
``tenant_id``, or environment products whose TENANT_SLUG is its slug) and its own
tenant-level settings. Secrets are write-only and Fernet-encrypted; every change
writes an audit row with field NAMES only. Nothing is cached, so a save applies
on the next request.
"""

from __future__ import annotations
import ipaddress
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

from dataclasses import replace

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.url_guard import UrlGuardError, validate_public_https_url

from app.config import settings as app_settings

from .. import registry
from ..models import ProductSetting
from ..repositories.settings_repository import (
    COLUMNS,
    SECRET_SLOTS,
    SettingsRepository,
    decode_secrets,
    encode_secrets,
    row_values,
)
from ..schemas import (
    ProductSettings,
    ProductSettingsCreate,
    ProductSettingsUpdate,
    SecretValue,
    SettingsAuditItem,
    SettingValue,
    TenantSettings,
    TenantSettingsUpdate,
)

# wire name -> model column (plain product fields)
PRODUCT_WIRE = {
    "displayName": "display_name",
    "connectionId": "connection_id",
    "consentUrl": "consent_url",
    "apiBaseUrl": "api_base_url",
    "issuer": "issuer",
    "consentAudience": "consent_audience",
    "callAudience": "call_audience",
}
SECRET_WIRE = {"ssToProductSecret": "ssToProduct", "productToSsSecret": "productToSs"}
_URL_FIELDS = ("consentUrl", "apiBaseUrl")
MIN_SECRET_LEN = 16
RESERVED_KEYS = frozenset({"new"})  # /settings/claude-connector/products/new is the create page
_MAX_LEN = {"display_name": 120, "connection_id": 128, "issuer": 128, "consent_audience": 128,
            "call_audience": 128}

# wire name -> (TenantSetting column, kind, min, max)
TENANT_WIRE = {
    "publicBaseUrl": ("public_base_url", "url", None, None),
    "allowedClientCidrs": ("allowed_client_cidrs", "cidrs", None, None),
    "redirectAllowlist": ("redirect_allowlist", "urls", None, None),
    "manifestTtlSeconds": ("manifest_ttl_seconds", "int", 0, 86400),
    "callTimeoutSeconds": ("call_timeout_seconds", "int", 1, 120),
    "callLogRetentionDays": ("call_log_retention_days", "int", 1, 3650),
}


class NotFound(Exception):
    pass


class Conflict(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Invalid(Exception):
    """422 with a per-field map (the UI highlights the field)."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("invalid")
        self.errors = errors


MAX_URL_LEN = 2048
MAX_LIST_LEN = 4096


def _valid_url(value: str) -> bool:
    """http(s), a host, no credentials, no whitespace or control characters
    (``urlsplit`` silently drops tabs/newlines, so check the raw string)."""
    if len(value) > MAX_URL_LEN or any(ord(ch) < 33 or ord(ch) == 127 for ch in value):
        return False
    parts = urlsplit(value)
    return (parts.scheme in ("http", "https") and bool(parts.hostname)
            and parts.username is None and parts.password is None)


def _https_ok(value: str) -> bool:
    """Plain http is for local development only."""
    return (urlsplit(value).scheme == "https"
            or app_settings.environment in ("development", "test"))


def _cidr_error(raw: str) -> Optional[str]:
    items = [p.strip() for p in raw.split(",") if p.strip()]
    if not items:
        return "Enter at least one range, or leave blank for no allow-list."
    for item in items:
        try:
            ipaddress.ip_network(item, strict=False)
        except ValueError:
            return f"{item!r} is not an IP address or CIDR range."
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SettingsService:
    def __init__(self, db: Session, tenant_id: str, tenant_slug: str,
                 show_secret_hint: bool = False):
        self.db = db
        self.show_secret_hint = show_secret_hint
        self.tenant_id = tenant_id
        self.tenant_slug = tenant_slug
        self.repo = SettingsRepository(db)

    # --- products -----------------------------------------------------------------------
    def _owned_status(self, key: str) -> Optional[registry.ProductStatus]:
        """The product's merged status, only if this tenant owns it."""
        key = (key or "").lower()
        row = self.repo.get_any(key)
        if row is not None:
            if row.tenant_id != self.tenant_id:
                return None
            env = registry._env()
            st = self.repo.resolved_row(env, key)
            env_slug = registry.env_owner_slug(env, key)
            if st is not None and env_slug and env_slug != self.tenant_slug:
                # the operator assigned this key to another tenant: this row is inert
                return replace(st, status="misconfigured", product=None,
                               partial=st.product or st.partial)
            return st
        st = registry.load_products(registry._env()).get(key)
        p = (st.product or st.partial) if st else None
        return st if p is not None and p.tenant_slug == self.tenant_slug else None

    def _view(self, st: registry.ProductStatus, stored: bool) -> ProductSettings:
        p = st.product or st.partial
        assert p is not None
        src = st.sources
        values = {"displayName": p.display_name, "connectionId": p.connection_id,
                  "consentUrl": p.consent_url, "apiBaseUrl": p.api_base_url, "issuer": p.issuer,
                  "consentAudience": p.consent_audience, "callAudience": p.call_audience}
        fields = {wire: SettingValue(value=values[wire] or None,
                                     source=src.get(COLUMNS[col], "unset"))
                  for wire, col in PRODUCT_WIRE.items()}
        secret_vals = {"ssToProduct": p.ss_to_product_secret, "productToSs": p.product_to_ss_secret}
        secrets = {}
        for slot, field in SECRET_SLOTS.items():
            source = src.get(field, "unset")
            state = ("unreadable" if source == "unreadable"
                     else "set" if secret_vals[slot] else "missing")
            value = secret_vals[slot]
            hint = None
            if self.show_secret_hint and state == "set":
                hint = f"****{value[-4:]}" if len(value) >= MIN_SECRET_LEN else "****"
            secrets[slot] = SecretValue(state=state, source=source, hint=hint)
        return ProductSettings(key=p.key, stored=stored, status=st.status, fields=fields,
                               secrets=secrets)

    def get_product(self, key: str) -> ProductSettings:
        st = self._owned_status(key)
        if st is None:
            raise NotFound()
        return self._view(st, stored=self.repo.get(self.tenant_id, st.key) is not None)

    def _apply(self, row: ProductSetting, body: ProductSettingsUpdate, sent: set[str]) -> list[str]:
        """Validate + apply the sent fields onto ``row``; returns changed wire names."""
        errors: dict[str, str] = {}
        changed: list[str] = []
        for wire, col in PRODUCT_WIRE.items():
            if wire not in sent:
                continue
            value = (getattr(body, wire) or "").strip()
            if wire in _URL_FIELDS and value and not _valid_url(value):
                errors[wire] = "Enter an http(s) URL."
                continue
            if wire == "consentUrl" and value and not _https_ok(value):
                errors[wire] = "Use https:// (the consent request travels in this URL)."
                continue
            if wire == "apiBaseUrl" and value:
                # The server calls this URL: https and public addresses only. An
                # internal target stays possible through the operator's environment.
                try:
                    validate_public_https_url(value, subject="API base URL")
                except UrlGuardError as exc:
                    errors[wire] = str(exc)
                    continue
            if wire == "apiBaseUrl":
                value = value.rstrip("/")
            if col in _MAX_LEN and len(value) > _MAX_LEN[col]:
                errors[wire] = f"At most {_MAX_LEN[col]} characters."
                continue
            if (getattr(row, col) or "") != value:
                setattr(row, col, value or None)
                changed.append(wire)
        secrets, unreadable = decode_secrets(row)
        if unreadable:
            secrets = {}  # undecryptable = start over; the admin re-enters
        secrets_changed = False
        for slot in body.clearSecrets:
            if slot in secrets or unreadable:
                secrets.pop(slot, None)
                secrets_changed = True
                changed.append(next(w for w, s in SECRET_WIRE.items() if s == slot))
        for wire, slot in SECRET_WIRE.items():
            value = (getattr(body, wire) or "").strip() if wire in sent else ""
            if not value:
                continue  # blank = keep
            if len(value) < MIN_SECRET_LEN:
                errors[wire] = f"Use at least {MIN_SECRET_LEN} characters."
                continue
            if secrets.get(slot) != value:
                secrets[slot] = value
                secrets_changed = True
                changed.append(wire)
        if unreadable and secrets_changed:
            for wire, slot in SECRET_WIRE.items():
                if slot not in secrets and slot not in body.clearSecrets and wire not in errors:
                    errors[wire] = "The saved secrets can no longer be read: enter both again."
        if secrets_changed and not app_settings.fernet_key and \
                app_settings.environment not in ("development", "test"):
            errors.setdefault("ssToProductSecret",
                              "Secrets cannot be saved: the server has no FERNET_KEY.")
        if errors:
            raise Invalid(errors)
        if secrets_changed:
            row.secrets_encrypted = encode_secrets(secrets)
        return sorted(set(changed))

    def _check_resolved(self, row: ProductSetting, key: str,
                        edited: frozenset[str] = frozenset()) -> None:
        """Reject a save the registry would silently turn into a broken product:
        equal secrets, or a binding field saved here while a secret still comes
        from the environment (the environment's secrets never follow a
        tenant-set URL or claim - see ``registry.merge_row``)."""
        vals, _ = row_values(row)
        if any(vals.get(n) for n in registry.BINDING_FIELDS):
            missing = {wire: "Enter this secret too: it must be saved here when the URLs, "
                             "connection ID, issuer or audiences are."
                       for wire, slot in SECRET_WIRE.items()
                       if not vals.get(SECRET_SLOTS[slot])}
            if missing and registry.env_owner_slug(registry._env(), key) == self.tenant_slug:
                raise Invalid(missing)
        st = registry.resolve_product(self.db, key)
        p = (st.product or st.partial) if st else None
        if p and p.ss_to_product_secret and p.ss_to_product_secret == p.product_to_ss_secret:
            field = "ssToProductSecret" if edited == {"ssToProductSecret"} else "productToSsSecret"
            raise Invalid({field: "The two secrets must differ."})

    def create_product(self, body: ProductSettingsCreate, actor: Optional[str]) -> ProductSettings:
        key = (body.key or "").strip().lower()
        if not registry._KEY_RE.match(key) or key in RESERVED_KEYS:
            raise Invalid({"key": "Lowercase letters, digits and _, starting with a letter (max 32)."})
        if self.repo.get_any(key) is not None:
            raise Conflict("A product with this key already exists.")
        env_st = registry.load_products(registry._env()).get(key)
        env_p = (env_st.product or env_st.partial) if env_st else None
        if env_p is not None and env_p.tenant_slug != self.tenant_slug:
            raise Conflict("A product with this key already exists.")
        row = ProductSetting(tenant_id=self.tenant_id, key=key)
        changed = self._apply(row, body, set(body.model_fields_set) - {"key"})
        SettingsRepository.stamp(row, actor, _now())
        try:
            self.repo.add(row)
        except IntegrityError:  # a concurrent create won the unique key
            self.db.rollback()
            raise Conflict("A product with this key already exists.") from None
        self._check_resolved(row, key, frozenset(changed))
        self.repo.drop_manifest(self.tenant_id, key)
        self.repo.audit(self.tenant_id, actor, f"product:{key}", "created", changed)
        self.db.commit()
        return self.get_product(key)

    def update_product(self, key: str, body: ProductSettingsUpdate,
                       actor: Optional[str]) -> ProductSettings:
        st = self._owned_status(key)
        if st is None:
            raise NotFound()
        row = self.repo.get(self.tenant_id, st.key)
        created = row is None
        if row is None:  # first save of an environment product creates its row
            row = ProductSetting(tenant_id=self.tenant_id, key=st.key)
        changed = self._apply(row, body, set(body.model_fields_set))
        if created and not changed:
            return self.get_product(st.key)  # nothing to save: no empty row
        if created:
            self.repo.add(row)
        self.db.flush()
        self._check_resolved(row, st.key, frozenset(changed))
        if "apiBaseUrl" in changed:
            self.repo.drop_manifest(self.tenant_id, st.key)  # never reuse another host's tools
        if changed or created:
            SettingsRepository.stamp(row, actor, _now())
            self.repo.audit(self.tenant_id, actor, f"product:{st.key}",
                            "created" if created else "updated", changed)
        self.db.commit()
        return self.get_product(st.key)

    def delete_product(self, key: str, confirm_key: str, actor: Optional[str]) -> None:
        row = self.repo.get(self.tenant_id, (key or "").lower())
        if row is None:
            raise NotFound()
        if (confirm_key or "").strip() != row.key:
            raise Invalid({"confirmKey": "Type the product key to confirm."})
        if self.repo.active_grants(self.tenant_id, row.key):
            raise Conflict("Revoke this product's active grants first.")
        self.repo.delete(row)
        self.repo.drop_manifest(self.tenant_id, row.key)
        self.repo.audit(self.tenant_id, actor, f"product:{row.key}", "deleted", [])
        self.db.commit()

    # --- tenant-level ---------------------------------------------------------------------
    def get_tenant(self) -> TenantSettings:
        cfg = registry.tenant_config(self.db, self.tenant_id)
        out = {wire: SettingValue(value=cfg.values[col] or None, source=cfg.sources[col])
               for wire, (col, _k, _a, _b) in TENANT_WIRE.items()}
        col_to_wire = {v[0]: k for k, v in TENANT_WIRE.items()}
        limits = {col_to_wire[c]: v for c, v in registry.ceilings(registry._env()).items()}
        return TenantSettings(**out, ceilings=limits)

    def update_tenant(self, body: TenantSettingsUpdate, actor: Optional[str]) -> TenantSettings:
        errors: dict[str, str] = {}
        updates: dict[str, object] = {}
        for wire in body.model_fields_set:
            if wire not in TENANT_WIRE:
                continue
            col, kind, lo, hi = TENANT_WIRE[wire]
            raw = getattr(body, wire)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                updates[col] = None
                continue
            if kind == "int":
                if not (lo <= int(raw) <= hi):
                    errors[wire] = f"Between {lo} and {hi}."
                    continue
                updates[col] = int(raw)
                continue
            value = str(raw).strip()
            if len(value) > MAX_LIST_LEN:
                errors[wire] = f"At most {MAX_LIST_LEN} characters."
                continue
            if kind == "url":
                if not _valid_url(value):
                    errors[wire] = "Enter an http(s) URL."
                    continue
                if not _https_ok(value):
                    errors[wire] = "Use https://."
                    continue
                value = value.rstrip("/")
            elif kind == "urls":
                items = [x.strip() for x in value.split(",") if x.strip()]
                bad = next((x for x in items if not _valid_url(x)), None)
                if bad is not None:
                    errors[wire] = f"{bad!r} is not an http(s) URL."
                    continue
                value = ", ".join(items)
            elif kind == "cidrs":
                err = _cidr_error(value)
                if err:
                    errors[wire] = err
                    continue
                value = ", ".join(p.strip() for p in value.split(",") if p.strip())
            updates[col] = value
        env = registry._env()
        for wire, (col, _kind, _lo, _hi) in TENANT_WIRE.items():
            value = updates.get(col)
            if wire not in errors and value is not None:
                err = registry.ceiling_error(env, col, str(value))
                if err:
                    errors[wire] = err
        if errors:
            raise Invalid(errors)
        existing = self.repo.tenant_row(self.tenant_id)
        col_to_wire = {v[0]: k for k, v in TENANT_WIRE.items()}
        changed = [col_to_wire[c] for c, v in updates.items()
                   if (getattr(existing, c) if existing else None) != v]
        if not changed:
            return self.get_tenant()  # nothing to save: no empty row, no audit
        row = existing or self.repo.upsert_tenant(self.tenant_id)
        for col, value in updates.items():
            setattr(row, col, value)
        SettingsRepository.stamp(row, actor, _now())
        self.repo.audit(self.tenant_id, actor, "tenant", "updated", changed)
        self.db.commit()
        return self.get_tenant()

    def audit(self) -> list[SettingsAuditItem]:
        from app.models.user import User

        rows = self.repo.list_audit(self.tenant_id)
        ids = {r.actor_user_id for r in rows if r.actor_user_id}
        names = dict(self.db.query(User.id, User.name)
                     .filter(User.tenant_id == self.tenant_id, User.id.in_(ids)).all()) if ids else {}
        return [SettingsAuditItem(id=r.id, target=r.target, action=r.action,
                                  fields=list(r.fields or []), actorUserId=r.actor_user_id,
                                  actorName=names.get(r.actor_user_id), at=r.created_at)
                for r in rows]
