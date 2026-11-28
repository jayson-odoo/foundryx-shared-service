"""Builder usage log. One row per turn; scoped by tenant AND product on write."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import DashUsage


class UsageRepository:
    def __init__(self, db: Session, tenant_id: str, product: str):
        self.db = db
        self.tenant_id = tenant_id
        self.product = product

    def add(self, row: DashUsage) -> DashUsage:
        row.tenant_id, row.product = self.tenant_id, self.product
        self.db.add(row)
        self.db.commit()
        return row
