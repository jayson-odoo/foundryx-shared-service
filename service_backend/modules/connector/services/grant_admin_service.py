"""Tenant-admin reads over connector grants (S5 extends: detail/activity/revoke)."""
from typing import Optional

from sqlalchemy.orm import Session

from ..repositories.connector_repository import ConnectorRepository
from ..schemas import GrantItem, GrantPage

STATUSES = ("active", "revoked", "expired")


class GrantAdminService:
    def __init__(self, db: Session, tenant_id: str):
        self.repo = ConnectorRepository(db, tenant_id)

    def list(self, *, status: Optional[str], product: Optional[str], search: Optional[str],
             page: int, page_size: int) -> GrantPage:
        if status not in STATUSES:
            status = None
        rows, total = self.repo.list_grants(status=status, product=product, search=search,
                                            page=page, page_size=page_size)
        return GrantPage(data=[GrantItem.model_validate(r) for r in rows], total=total,
                         page=page, page_size=page_size)
