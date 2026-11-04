"""Queries for write-back (plan 55): the action log + staged-document lookups.

Pure SQLAlchemy, every query tenant-scoped.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from modules.autocount.models import AcStagedRecord, AcWriteAction

OUTCOME_IN_FLIGHT = "in_flight"


class WriteActionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, row: AcWriteAction) -> AcWriteAction:
        self.db.add(row)
        self.db.flush()
        return row

    def has_open(self, tenant_id: str, company_id: str, doc_key: int) -> bool:
        """True when an ``in_flight`` action exists for the document (the busy lock)."""
        return (
            self.db.query(AcWriteAction.id)
            .filter(
                AcWriteAction.tenant_id == tenant_id,
                AcWriteAction.company_id == company_id,
                AcWriteAction.doc_key == doc_key,
                AcWriteAction.outcome == OUTCOME_IN_FLIGHT,
            )
            .first()
            is not None
        )


class StagedDocRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def newest(
        self, tenant_id: str, company_id: str, entity_type: str, source_ref: str
    ) -> Optional[AcStagedRecord]:
        """The newest non-delete staged row of one document."""
        return (
            self.db.query(AcStagedRecord)
            .filter(
                AcStagedRecord.tenant_id == tenant_id,
                AcStagedRecord.company_id == company_id,
                AcStagedRecord.entity_type == entity_type,
                AcStagedRecord.source_ref == source_ref,
                AcStagedRecord.op != "delete",
            )
            .order_by(AcStagedRecord.created_at.desc(), AcStagedRecord.id)
            .first()
        )

    def for_entity(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> List[AcStagedRecord]:
        """Every non-delete staged row of one entity (db3 scale)."""
        return (
            self.db.query(AcStagedRecord)
            .filter(
                AcStagedRecord.tenant_id == tenant_id,
                AcStagedRecord.company_id == company_id,
                AcStagedRecord.entity_type == entity_type,
                AcStagedRecord.op != "delete",
            )
            .all()
        )
