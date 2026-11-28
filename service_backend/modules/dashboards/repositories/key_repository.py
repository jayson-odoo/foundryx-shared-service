"""Gateway key + audit queries. Keys are looked up by prefix (they identify the tenant);
everything else is scoped by tenant."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from ..models import DashApiAudit, DashApiKey


class KeyRepository:
    def __init__(self, db: Session):
        self.db = db

    def by_prefix(self, prefix: str) -> List[DashApiKey]:
        return self.db.query(DashApiKey).filter(DashApiKey.key_prefix == prefix).all()

    def get(self, tenant_id: str, key_id: str) -> Optional[DashApiKey]:
        return self.db.query(DashApiKey).filter(DashApiKey.id == key_id, DashApiKey.tenant_id == tenant_id).first()

    def list(self, tenant_id: str) -> List[DashApiKey]:
        return (
            self.db.query(DashApiKey)
            .filter(DashApiKey.tenant_id == tenant_id)
            .order_by(DashApiKey.created_at.desc(), DashApiKey.id.asc())
            .all()
        )

    def add(self, row: DashApiKey) -> DashApiKey:
        self.db.add(row)
        self.db.flush()
        return row

    def add_audit(self, row: DashApiAudit) -> None:
        self.db.add(row)
