"""Queries for write-back (plan 55): the action log + staged-document lookups.

Pure SQLAlchemy, every query tenant-scoped.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from modules.autocount.models import AcEntityConfig, AcStagedRecord, AcWriteAction, AcWriteOperation

OUTCOME_IN_FLIGHT = "in_flight"
OUTCOME_PENDING = "pending_verification"


class WriteActionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, row: AcWriteAction) -> AcWriteAction:
        self.db.add(row)
        self.db.flush()
        return row

    def has_open(
        self, tenant_id: str, company_id: str, doc_key: int, since: datetime
    ) -> bool:
        """True when an ``in_flight`` or ``pending_verification`` action created
        at or after ``since`` exists for the document (the busy lock)."""
        return (
            self.db.query(AcWriteAction.id)
            .filter(
                AcWriteAction.tenant_id == tenant_id,
                AcWriteAction.company_id == company_id,
                AcWriteAction.doc_key == doc_key,
                AcWriteAction.outcome.in_((OUTCOME_IN_FLIGHT, OUTCOME_PENDING)),
                AcWriteAction.created_at >= since,
            )
            .first()
            is not None
        )

    def last_confirmed_after(
        self, tenant_id: str, company_id: str, doc_type: str, doc_key: int
    ) -> Optional[dict]:
        """The read-back document of the newest ``done`` action on the document
        (AC-57-20: its DocDate is a fallback for the by-date read)."""
        row = (
            self.db.query(AcWriteAction.after_json)
            .filter(
                AcWriteAction.tenant_id == tenant_id,
                AcWriteAction.company_id == company_id,
                AcWriteAction.doc_type == doc_type,
                AcWriteAction.doc_key == doc_key,
                AcWriteAction.outcome == "done",
                AcWriteAction.after_json.isnot(None),
            )
            .order_by(AcWriteAction.created_at.desc(), AcWriteAction.id)
            .first()
        )
        after = row[0] if row else None
        return after if isinstance(after, dict) else None

    def expire_stale_in_flight(
        self, tenant_id: str, company_id: str, doc_key: int, before: datetime
    ) -> int:
        """Mark ``in_flight`` rows older than ``before`` as ``pending_verification``
        (the lock must not outlive a crashed action); returns how many."""
        rows = (
            self.db.query(AcWriteAction)
            .filter(
                AcWriteAction.tenant_id == tenant_id,
                AcWriteAction.company_id == company_id,
                AcWriteAction.doc_key == doc_key,
                AcWriteAction.outcome == OUTCOME_IN_FLIGHT,
                AcWriteAction.created_at < before,
            )
            .all()
        )
        for row in rows:
            row.outcome = OUTCOME_PENDING
        return len(rows)


class OperationRepository:
    """The operation log (plan 57): every query tenant- and company-scoped."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def by_key(
        self, tenant_id: str, company_id: str, key_id: Optional[str], idempotency_key: str
    ) -> Optional[AcWriteOperation]:
        return (
            self.db.query(AcWriteOperation)
            .filter(
                AcWriteOperation.tenant_id == tenant_id,
                AcWriteOperation.company_id == company_id,
                AcWriteOperation.key_id == key_id,
                AcWriteOperation.idempotency_key == idempotency_key,
            )
            .first()
        )

    def get(self, tenant_id: str, company_id: str, operation_id: str) -> Optional[AcWriteOperation]:
        return (
            self.db.query(AcWriteOperation)
            .filter(
                AcWriteOperation.tenant_id == tenant_id,
                AcWriteOperation.company_id == company_id,
                AcWriteOperation.id == operation_id,
            )
            .first()
        )

    def add(self, row: AcWriteOperation) -> AcWriteOperation:
        self.db.add(row)
        self.db.flush()
        return row


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


class EntitySourceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def source_impl(self, tenant_id: str, company_id: str, entity_type: str) -> Optional[str]:
        """``source_impl`` of the company's entity config, or None when it has none."""
        return (
            self.db.query(AcEntityConfig.source_impl)
            .filter(
                AcEntityConfig.tenant_id == tenant_id,
                AcEntityConfig.company_id == company_id,
                AcEntityConfig.entity_type == entity_type,
            )
            .scalar()
        )
