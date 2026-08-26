"""Terminology repository (sprint-3/08) - pure SQLAlchemy, tenant-scoped."""
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.terminology import TerminologyOverride


class TerminologyRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_tenant(self, tenant_id: str) -> Dict[str, TerminologyOverride]:
        rows = (
            self.db.query(TerminologyOverride)
            .filter(TerminologyOverride.tenant_id == tenant_id)
            .all()
        )
        return {row.entity_key: row for row in rows}

    def get(self, tenant_id: str, entity_key: str) -> Optional[TerminologyOverride]:
        return (
            self.db.query(TerminologyOverride)
            .filter(
                TerminologyOverride.tenant_id == tenant_id,
                TerminologyOverride.entity_key == entity_key,
            )
            .first()
        )

    def upsert(
        self,
        tenant_id: str,
        entity_key: str,
        singular: str,
        plural: str,
        updated_by: Optional[str],
    ) -> TerminologyOverride:
        row = self.get(tenant_id, entity_key)
        if row is None:
            row = TerminologyOverride(
                tenant_id=tenant_id, entity_key=entity_key
            )
            self.db.add(row)
        row.singular = singular
        row.plural = plural
        row.updated_by = updated_by
        self.db.flush()
        return row

    def delete(self, tenant_id: str, entity_key: str) -> bool:
        row = self.get(tenant_id, entity_key)
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True
