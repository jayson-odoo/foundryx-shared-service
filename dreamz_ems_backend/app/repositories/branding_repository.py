"""Branding repository (plan sprint-2/03) — pure SQLAlchemy."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.tenant_branding import TenantBranding


class BrandingRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_tenant(self, tenant_id: str) -> Optional[TenantBranding]:
        return (
            self.db.query(TenantBranding)
            .filter(TenantBranding.tenant_id == tenant_id)
            .first()
        )

    def get_by_slug(self, slug: str) -> Optional[TenantBranding]:
        return (
            self.db.query(TenantBranding)
            .join(Tenant, Tenant.id == TenantBranding.tenant_id)
            .filter(Tenant.slug == slug)
            .first()
        )

    def get_or_create(self, tenant_id: str) -> TenantBranding:
        row = self.get_by_tenant(tenant_id)
        if row is None:
            row = TenantBranding(tenant_id=tenant_id, version=0)
            self.db.add(row)
            self.db.flush()
        return row
