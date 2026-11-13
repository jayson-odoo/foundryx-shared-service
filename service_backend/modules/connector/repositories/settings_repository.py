"""Connector settings persistence (lane SETTINGS-IN-DB-SS) - pure SQLAlchemy.

Two read shapes:
- ``resolved_row(s)`` - deployment-wide lookups by product key, used by the
  public endpoints to find a product (the key is the URL, so this cannot be
  tenant-scoped; the row's own ``tenant_id`` becomes the product's owner).
- everything else is tenant-scoped: the tenant is the caller's, a foreign
  product is indistinguishable from a missing one.
"""

from __future__ import annotations
from datetime import datetime
from typing import Mapping, Optional

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.secrets import decrypt_secret, encrypt_secret

from .. import registry
from ..models import Grant, ManifestCache, ProductSetting, SettingsAudit, TenantSetting

# product column <-> registry FIELD name
COLUMNS = {
    "display_name": "DISPLAY_NAME",
    "connection_id": "CONNECTION_ID",
    "consent_url": "CONSENT_URL",
    "api_base_url": "API_BASE_URL",
    "issuer": "ISSUER",
    "consent_audience": "CONSENT_AUDIENCE",
    "call_audience": "CALL_AUDIENCE",
}
# secret slot (stored dict key) <-> registry FIELD name
SECRET_SLOTS = {"ssToProduct": "SS_TO_PRODUCT_SECRET", "productToSs": "PRODUCT_TO_SS_SECRET"}


def decode_secrets(row: ProductSetting) -> tuple[dict[str, str], frozenset[str]]:
    """``({slot: secret}, unreadable FIELD names)``. A wrong FERNET_KEY or a
    tampered value never raises: both slots read as unreadable."""
    if not row.secrets_encrypted:
        return {}, frozenset()
    try:
        data = decrypt_secret(row.secrets_encrypted)
    except (InvalidToken, ValueError, TypeError):
        return {}, frozenset(SECRET_SLOTS.values())
    if not isinstance(data, dict):
        return {}, frozenset(SECRET_SLOTS.values())
    return {k: str(v) for k, v in data.items() if k in SECRET_SLOTS and v}, frozenset()


def encode_secrets(secrets: Mapping[str, str]) -> Optional[str]:
    kept = {k: v for k, v in secrets.items() if k in SECRET_SLOTS and v}
    return encrypt_secret(kept) if kept else None


def row_values(row: ProductSetting) -> tuple[dict[str, str], frozenset[str]]:
    vals = {field: (getattr(row, col) or "") for col, field in COLUMNS.items()}
    secrets, unreadable = decode_secrets(row)
    for slot, field in SECRET_SLOTS.items():
        vals[field] = secrets.get(slot, "")
    return vals, unreadable


class SettingsRepository:
    def __init__(self, db: Session):
        self.db = db

    # --- deployment-wide product lookups (public resolution) ----------------------------
    def _slugs(self, tenant_ids: set[str]) -> dict[str, str]:
        if not tenant_ids:
            return {}
        return dict(self.db.query(Tenant.id, Tenant.slug).filter(Tenant.id.in_(tenant_ids)).all())

    def _resolve(self, env: Mapping[str, str], row: ProductSetting,
                 slug: str) -> registry.ProductStatus:
        vals, unreadable = row_values(row)
        return registry.merge_row(env, row.key, slug, row.tenant_id, vals, unreadable)

    def resolved_rows(self, env: Mapping[str, str],
                      tenant_id: Optional[str] = None) -> dict[str, registry.ProductStatus]:
        q = self.db.query(ProductSetting)
        if tenant_id is not None:
            q = q.filter(ProductSetting.tenant_id == tenant_id)
        rows = q.all()
        slugs = self._slugs({r.tenant_id for r in rows})
        return {r.key: self._resolve(env, r, slugs.get(r.tenant_id, "")) for r in rows
                if r.tenant_id in slugs}

    def resolved_row(self, env: Mapping[str, str], key: str) -> Optional[registry.ProductStatus]:
        row = self.get_any(key)
        if row is None:
            return None
        slug = self._slugs({row.tenant_id}).get(row.tenant_id)
        return self._resolve(env, row, slug) if slug else None

    def get_any(self, key: str) -> Optional[ProductSetting]:
        return self.db.query(ProductSetting).filter(ProductSetting.key == key).first()

    # --- tenant-scoped ------------------------------------------------------------------
    def get(self, tenant_id: str, key: str) -> Optional[ProductSetting]:
        return (self.db.query(ProductSetting)
                .filter(ProductSetting.tenant_id == tenant_id, ProductSetting.key == key).first())

    def add(self, row: ProductSetting) -> None:
        self.db.add(row)
        self.db.flush()

    def delete(self, row: ProductSetting) -> None:
        self.db.delete(row)
        self.db.flush()

    def drop_manifest(self, tenant_id: str, key: str) -> None:
        self.db.query(ManifestCache).filter(ManifestCache.tenant_id == tenant_id,
                                            ManifestCache.product == key).delete(
            synchronize_session=False)

    def active_grants(self, tenant_id: str, key: str) -> int:
        return (self.db.query(Grant.id)
                .filter(Grant.tenant_id == tenant_id, Grant.product == key,
                        Grant.status == "active").count())

    def tenant_row(self, tenant_id: str) -> Optional[TenantSetting]:
        return self.db.get(TenantSetting, tenant_id)

    def tenant_values(self, tenant_id: str) -> dict[str, object]:
        row = self.tenant_row(tenant_id)
        if row is None:
            return {}
        return {name: getattr(row, name) for name in registry.TENANT_SETTINGS}

    def upsert_tenant(self, tenant_id: str) -> TenantSetting:
        row = self.tenant_row(tenant_id)
        if row is None:
            row = TenantSetting(tenant_id=tenant_id)
            self.db.add(row)
        return row

    def retention_overrides(self) -> dict[str, int]:
        """{tenant_id: days} for every tenant that set its own call-log retention."""
        return {tid: days for tid, days in
                self.db.query(TenantSetting.tenant_id, TenantSetting.call_log_retention_days)
                .filter(TenantSetting.call_log_retention_days.isnot(None)).all()}

    # --- audit --------------------------------------------------------------------------
    def audit(self, tenant_id: str, actor_user_id: Optional[str], target: str, action: str,
              fields: list[str]) -> None:
        self.db.add(SettingsAudit(tenant_id=tenant_id, actor_user_id=actor_user_id,
                                  target=target, action=action, fields=sorted(fields)))

    def list_audit(self, tenant_id: str, limit: int = 100) -> list[SettingsAudit]:
        return (self.db.query(SettingsAudit).filter(SettingsAudit.tenant_id == tenant_id)
                .order_by(SettingsAudit.created_at.desc(), SettingsAudit.id.desc())
                .limit(limit).all())

    @staticmethod
    def stamp(row: object, actor_user_id: Optional[str], now: datetime) -> None:
        setattr(row, "updated_by", actor_user_id)
        setattr(row, "updated_at", now)
