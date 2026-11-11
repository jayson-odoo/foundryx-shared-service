"""Queries for write-back (plan 55): the action log + staged-document lookups.

Pure SQLAlchemy, every query tenant-scoped.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.autocount.models import (
    AcEntityConfig,
    AcPoSoLink,
    AcStagedRecord,
    AcWriteAction,
    AcWriteOperation,
)

OUTCOME_IN_FLIGHT = "in_flight"
OUTCOME_PENDING = "pending_verification"


class WriteActionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, row: AcWriteAction) -> AcWriteAction:
        self.db.add(row)
        self.db.flush()
        return row

    def attach_to_operation(
        self, tenant_id: str, action_id: str, operation_id: str, step: str, method: str, path: str
    ) -> bool:
        """Mark an existing action as one step of an operation (the plan 55 split link
        that an operation wraps); tenant-scoped."""
        row = (
            self.db.query(AcWriteAction)
            .filter(AcWriteAction.id == action_id, AcWriteAction.tenant_id == tenant_id)
            .first()
        )
        if row is None:
            return False
        row.operation_id, row.step, row.request_method, row.request_path = operation_id, step, method, path
        return True

    def has_open(
        self, tenant_id: str, company_id: str, doc_key: int, since: datetime,
        *, standalone_only: bool = False,
    ) -> bool:
        """True when an ``in_flight`` or ``pending_verification`` action created
        at or after ``since`` exists for the document (the busy lock).
        ``standalone_only`` skips actions that belong to an operation: the operation
        row carries its own lock and age (AC-57-43)."""
        query = self.db.query(AcWriteAction.id).filter(
            AcWriteAction.tenant_id == tenant_id,
            AcWriteAction.company_id == company_id,
            AcWriteAction.doc_key == doc_key,
            AcWriteAction.outcome.in_((OUTCOME_IN_FLIGHT, OUTCOME_PENDING)),
            AcWriteAction.created_at >= since,
        )
        if standalone_only:
            query = query.filter(AcWriteAction.operation_id.is_(None))
        return query.first() is not None

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

    def rekey(self, row: AcWriteOperation, idempotency_key: str) -> None:
        row.idempotency_key = idempotency_key
        self.db.flush()

    def created_documents(self, tenant_id: str, company_id: str, exclude_id: str) -> "tuple[set, set]":
        """``(DocKeys, DocNos)`` already recorded as the result of a DONE create of this company, other than
        ``exclude_id``: a lookup never adopts a document another create owns."""
        keys: set = set()
        numbers: set = set()
        rows = self.db.query(AcWriteOperation.result_json).filter(
            AcWriteOperation.tenant_id == tenant_id,
            AcWriteOperation.company_id == company_id,
            AcWriteOperation.op.like("create_doc:%"),
            AcWriteOperation.status == "done",
            AcWriteOperation.id != exclude_id,
        )
        for (result,) in rows:
            if isinstance(result, dict):
                if result.get("docKey") is not None:
                    keys.add(result["docKey"])
                if result.get("docNo"):
                    numbers.add(result["docNo"])
        return keys, numbers

    def delete(self, row: AcWriteOperation) -> None:
        self.db.delete(row)
        self.db.flush()

    def expire_stale_in_progress(
        self, tenant_id: str, company_id: str, doc_type: str, doc_key: int, before: datetime
    ) -> int:
        """Flip ``in_progress`` operations on a document that have not moved since
        ``before`` to ``pending_verification`` (a crashed run must not hold the lock
        for ever); returns how many."""
        return (
            self.db.query(AcWriteOperation)
            .filter(
                AcWriteOperation.tenant_id == tenant_id,
                AcWriteOperation.company_id == company_id,
                AcWriteOperation.doc_type == doc_type,
                AcWriteOperation.doc_key == doc_key,
                AcWriteOperation.status == "in_progress",
                AcWriteOperation.updated_at < before,
            )
            # updated_at stays as it was: the flip must not make the row look young
            .update({"status": "pending_verification", "updated_at": AcWriteOperation.updated_at},
                    synchronize_session=False)
        )

    def has_recent_pending(
        self, tenant_id: str, company_id: str, doc_type: str, doc_key: int, since: datetime
    ) -> bool:
        """An operation on the document that ended ``pending_verification`` after ``since``."""
        return (
            self.db.query(AcWriteOperation.id)
            .filter(
                AcWriteOperation.tenant_id == tenant_id,
                AcWriteOperation.company_id == company_id,
                AcWriteOperation.doc_type == doc_type,
                AcWriteOperation.doc_key == doc_key,
                AcWriteOperation.status == "pending_verification",
                AcWriteOperation.updated_at >= since,
            )
            .first()
            is not None
        )

    def claim(self, tenant_id: str, company_id: str, operation_id: str, from_statuses: "tuple[str, ...]") -> bool:
        """Conditional update to ``in_progress``: True only for the one caller whose
        update matched a row still in ``from_statuses`` (resume claims, AC-57-47)."""
        updated = (
            self.db.query(AcWriteOperation)
            .filter(
                AcWriteOperation.tenant_id == tenant_id,
                AcWriteOperation.company_id == company_id,
                AcWriteOperation.id == operation_id,
                AcWriteOperation.status.in_(from_statuses),
            )
            .update({"status": "in_progress"}, synchronize_session=False)
        )
        return updated == 1


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


class CompanyDataRepository:
    """What a company already holds that a write connection must not meet (AC-57-22)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def has_sql_source(self, tenant_id: str, company_id: str) -> bool:
        return (
            self.db.query(AcEntityConfig.id)
            .filter(
                AcEntityConfig.tenant_id == tenant_id,
                AcEntityConfig.company_id == company_id,
                AcEntityConfig.source_impl == "sql_db",
            )
            .first()
            is not None
        )

    def has_foreign_document_rows(
        self, tenant_id: str, company_id: str, entity_types: "tuple[str, ...]", own_job_id: str
    ) -> bool:
        """A staged document row (PO / SPO / SO) of any job but ``own_job_id``."""
        return (
            self.db.query(AcStagedRecord.id)
            .filter(
                AcStagedRecord.tenant_id == tenant_id,
                AcStagedRecord.company_id == company_id,
                AcStagedRecord.entity_type.in_(entity_types),
                AcStagedRecord.job_id != own_job_id,
            )
            .first()
            is not None
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


class PoSoLinkRepository:
    """The over-link index ``ac_po_so_link`` (plan 62 D8); every call is tenant + company scoped."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def replace_for_po(
        self, tenant_id: str, company_id: str, po_source_ref: str, links: "List[tuple[Optional[int], int, Decimal]]"
    ) -> None:
        """Swap one PO's rows for ``links`` (``(po_dtl_key, so_dtl_key, qty)``)."""
        self.db.query(AcPoSoLink).filter(
            AcPoSoLink.tenant_id == tenant_id,
            AcPoSoLink.company_id == company_id,
            AcPoSoLink.po_source_ref == po_source_ref,
        ).delete(synchronize_session=False)
        for po_dtl_key, so_dtl_key, qty in links:
            self.db.add(AcPoSoLink(
                tenant_id=tenant_id, company_id=company_id, po_source_ref=po_source_ref,
                po_dtl_key=po_dtl_key, so_dtl_key=so_dtl_key, qty=qty,
            ))
        self.db.flush()

    def linked_qty(
        self, tenant_id: str, company_id: str, so_dtl_key: int, *, except_ref: Optional[str] = None
    ) -> Decimal:
        """Qty of one SO row covered by the indexed POs, leaving out ``except_ref``."""
        query = self.db.query(func.coalesce(func.sum(AcPoSoLink.qty), 0)).filter(
            AcPoSoLink.tenant_id == tenant_id,
            AcPoSoLink.company_id == company_id,
            AcPoSoLink.so_dtl_key == so_dtl_key,
        )
        if except_ref is not None:
            query = query.filter(AcPoSoLink.po_source_ref != except_ref)
        return Decimal(str(query.scalar() or 0))
