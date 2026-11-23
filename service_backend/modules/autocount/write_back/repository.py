"""Queries for write-back (plan 55): the action log + staged-document lookups.

Pure SQLAlchemy, every query tenant-scoped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from modules.autocount.models import (
    AcEntityConfig,
    AcPoSoLink,
    AcSoRowIndex,
    AcSpoPoLink,
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

    def of_single_operation(
        self, tenant_id: str, company_id: str, operation_id: str, *, key_id: Optional[str], doc_type: str,
        doc_key: Optional[int], action: str, since: datetime, until: datetime, owned: bool = False,
    ) -> List[AcWriteAction]:
        """The write action(s) of one single-document operation (AUTOCOUNT-STRANDED-OPS-B): the newest action
        it carries; ``owned`` (its actions carry it) and none -> []; else (a row written before actions carried
        it) the unowned in-flight / pending actions of the same key, kind, document and primitive created inside
        the operation's window. Several, or none for an unowned row = cannot tell."""
        own = (
            self.db.query(AcWriteAction)
            .filter(AcWriteAction.tenant_id == tenant_id, AcWriteAction.company_id == company_id,
                    AcWriteAction.operation_id == operation_id)
            .order_by(AcWriteAction.created_at.desc(), AcWriteAction.id)
            .first()
        )
        if own is not None or owned:  # ``owned``: the row's actions carry it, so none = nothing was sent
            return [own] if own is not None else []
        query = self.db.query(AcWriteAction).filter(
            AcWriteAction.tenant_id == tenant_id,
            AcWriteAction.company_id == company_id,
            AcWriteAction.operation_id.is_(None),
            AcWriteAction.doc_type == doc_type,
            AcWriteAction.doc_key == doc_key,
            AcWriteAction.action == action,
            # only an unknown outcome is a candidate: a finished action belongs to a request that answered
            AcWriteAction.outcome.in_((OUTCOME_IN_FLIGHT, OUTCOME_PENDING)),
            AcWriteAction.created_at >= since,
            AcWriteAction.created_at <= until,
        )
        query = query.filter(AcWriteAction.key_id.is_(None) if key_id is None else AcWriteAction.key_id == key_id)
        return query.order_by(AcWriteAction.created_at, AcWriteAction.id).all()

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

    def newest_of_operation(self, tenant_id: str, company_id: str, operation_id: str) -> Optional[AcWriteAction]:
        """The newest write action of an operation (its last write: the settle clock of a timed-out PUT)."""
        return (
            self.db.query(AcWriteAction)
            .filter(
                AcWriteAction.tenant_id == tenant_id,
                AcWriteAction.company_id == company_id,
                AcWriteAction.operation_id == operation_id,
            )
            .order_by(AcWriteAction.created_at.desc(), AcWriteAction.id)
            .first()
        )

    def operation_step(self, tenant_id: str, company_id: str, operation_id: str, step: str) -> Optional[AcWriteAction]:
        """The newest action of one step of an operation (plan 65 D5: Resume re-judges the stored link PUT)."""
        return (
            self.db.query(AcWriteAction)
            .filter(
                AcWriteAction.tenant_id == tenant_id,
                AcWriteAction.company_id == company_id,
                AcWriteAction.operation_id == operation_id,
                AcWriteAction.step == step,
            )
            .order_by(AcWriteAction.created_at.desc(), AcWriteAction.id)
            .first()
        )

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

    def pending_link_qty(self, tenant_id: str, company_id: str, so_dtl_key: int, exclude_doc_key: Optional[int]) -> Decimal:
        """Quantity of one SO row that PENDING link operations (outcome unknown, they may have landed) of
        this company would cover, from their stored snapshot; the operations on ``exclude_doc_key`` (the PO
        being written, whose fresh rows already say) are left out."""
        total = Decimal(0)
        rows = self.db.query(AcWriteOperation).filter(
            AcWriteOperation.tenant_id == tenant_id,
            AcWriteOperation.company_id == company_id,
            or_(AcWriteOperation.status == OUTCOME_PENDING,
                # PO-LINK-STUCK-RECONCILE-B: a write AutoCount timed out on may still land, it counts too
                AcWriteOperation.error_code == "VENDOR_TIMEOUT"),
            AcWriteOperation.status.notin_(("done", "refused", "recovered", "in_progress")),
            AcWriteOperation.op.in_(("link_row", "relink_row", "link_batch", "split_link")),
        )
        for op in rows:
            snap = op.snapshot_json
            if not isinstance(snap, dict) or (exclude_doc_key is not None and op.doc_key == exclude_doc_key):
                continue
            if op.op in ("link_batch", "split_link"):
                for link in snap.get("links") or []:
                    if int(link.get("soDtlKey") or 0) == so_dtl_key:
                        total += Decimal(str(link.get("qty") or 0))
                continue
            target = int((snap.get("newLink") or {}).get("FromDocDtlKey") or 0)
            if target == so_dtl_key:
                qty = Decimal(str((snap.get("row") or {}).get("Qty") or 0))
                if snap.get("received") is not None:
                    qty -= Decimal(str(snap["received"]))
                total += qty
        return total

    def created_documents(self, tenant_id: str, company_id: str, exclude_id: str, since: datetime,
                          until: datetime) -> "tuple[set, set]":
        """``(DocKeys, DocNos)`` already recorded as the result of a DONE create of this company, other than
        ``exclude_id`` and started between ``since`` and ``until`` (the lookup window): a lookup never adopts a
        document another create owns, and never reads further back than the window."""
        keys: set = set()
        numbers: set = set()
        rows = self.db.query(AcWriteOperation.result_json).filter(
            AcWriteOperation.tenant_id == tenant_id,
            AcWriteOperation.company_id == company_id,
            AcWriteOperation.op.like("create_doc:%"),
            AcWriteOperation.status == "done",
            AcWriteOperation.id != exclude_id,
            AcWriteOperation.created_at >= since,
            AcWriteOperation.created_at <= until,
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

    def expire_stale_operation(self, tenant_id: str, company_id: str, operation_id: str, before: datetime) -> bool:
        """Flip ONE ``in_progress`` operation that has not moved since ``before`` to
        ``pending_verification`` (a same-key resend of a crashed run); updated_at kept."""
        return (
            self.db.query(AcWriteOperation)
            .filter(
                AcWriteOperation.tenant_id == tenant_id,
                AcWriteOperation.company_id == company_id,
                AcWriteOperation.id == operation_id,
                AcWriteOperation.status == "in_progress",
                AcWriteOperation.updated_at < before,
            )
            .update({"status": "pending_verification", "updated_at": AcWriteOperation.updated_at},
                    synchronize_session=False)
        ) == 1

    def store_snapshot(self, tenant_id: str, company_id: str, operation_id: str, snapshot: dict) -> bool:
        """Conditional first-snapshot write: only while the operation is still ``in_progress`` (a run whose row
        was expired and settled meanwhile must never go on to write); bumps updated_at (heartbeat)."""
        return (
            self.db.query(AcWriteOperation)
            .filter(
                AcWriteOperation.tenant_id == tenant_id,
                AcWriteOperation.company_id == company_id,
                AcWriteOperation.id == operation_id,
                AcWriteOperation.status == "in_progress",
            )
            # wall clock, not func.now() (Postgres: the transaction START, which can predate the guard reads)
            .update({"snapshot_json": snapshot, "updated_at": datetime.now(timezone.utc)}, synchronize_session=False)
        ) == 1

    def sweep_stale_in_progress(self, before: datetime) -> int:
        """API-start crash sweep (system context, every tenant): every ``in_progress`` operation
        that has not moved since ``before`` is a run whose process died -> ``pending_verification``
        (updated_at kept). A live run heartbeats, so it is never older than the busy window."""
        return (
            self.db.query(AcWriteOperation)
            .filter(AcWriteOperation.status == "in_progress", AcWriteOperation.updated_at < before)
            .update({"status": "pending_verification", "updated_at": AcWriteOperation.updated_at},
                    synchronize_session=False)
        )

    def settle_not_applied(
        self, tenant_id: str, company_id: str, operation_id: str, error_code: str, result: dict
    ) -> bool:
        """Conditional ``pending_verification`` -> ``recovered`` for an operation that never stored its
        snapshot (BL-SS-368): True only for the one caller whose update matched."""
        return (
            self.db.query(AcWriteOperation)
            .filter(
                AcWriteOperation.tenant_id == tenant_id,
                AcWriteOperation.company_id == company_id,
                AcWriteOperation.id == operation_id,
                AcWriteOperation.status == "pending_verification",
                AcWriteOperation.snapshot_json.is_(None),
            )
            .update({"status": "recovered", "error_code": error_code, "result_json": result},
                    synchronize_session=False)
        ) == 1

    def close_parked(
        self, tenant_id: str, company_id: str, operation_id: str, from_statuses: "tuple[str, ...]",
        error_code: str, result: dict,
    ) -> bool:
        """PO-LINK-STUCK-RECONCILE-B s2: conditional parked -> ``refused`` (an operator closed it as superseded,
        nothing written): True only for the one caller whose update matched a row still parked."""
        return (
            self.db.query(AcWriteOperation)
            .filter(
                AcWriteOperation.tenant_id == tenant_id,
                AcWriteOperation.company_id == company_id,
                AcWriteOperation.id == operation_id,
                AcWriteOperation.status.in_(from_statuses),
            )
            .update({"status": "refused", "error_code": error_code, "result_json": result},
                    synchronize_session=False)
        ) == 1

    def has_actions(self, tenant_id: str, operation_id: str) -> bool:
        """Any write action recorded under the operation (a step that may have reached AutoCount)."""
        return (
            self.db.query(AcWriteAction.id)
            .filter(AcWriteAction.tenant_id == tenant_id, AcWriteAction.operation_id == operation_id)
            .first()
            is not None
        )

    def pending_spo_move_qty(self, tenant_id: str, company_id: str, po_dtl_key: int,
                             exclude_doc_key: Optional[int]) -> Decimal:
        """Plan 71: quantity PENDING SPO moves (outcome unknown, they may have landed) would put on one PO row,
        from their stored snapshot's ``take``; moves on ``exclude_doc_key`` (the SPO being written, whose
        fresh rows already say) are left out."""
        total = Decimal(0)
        rows = self.db.query(AcWriteOperation).filter(
            AcWriteOperation.tenant_id == tenant_id,
            AcWriteOperation.company_id == company_id,
            AcWriteOperation.status == OUTCOME_PENDING,
            AcWriteOperation.op == "spo_move_row",
        )
        for op in rows:
            snap = op.snapshot_json
            if not isinstance(snap, dict) or (exclude_doc_key is not None and op.doc_key == exclude_doc_key):
                continue
            if int((snap.get("newLink") or {}).get("FromDocDtlKey") or 0) == po_dtl_key:
                total += Decimal(str(snap.get("take") or 0))
        return total

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

    def has_in_progress(
        self, tenant_id: str, company_id: str, doc_type: str, doc_key: int, since: datetime,
        *, exclude_id: Optional[str] = None,
    ) -> bool:
        """Another operation on the document is ``in_progress`` and moved after ``since`` (an older one is a
        crashed run, flipped to ``pending_verification`` by ``expire_stale_in_progress``)."""
        query = self.db.query(AcWriteOperation.id).filter(
            AcWriteOperation.tenant_id == tenant_id,
            AcWriteOperation.company_id == company_id,
            AcWriteOperation.doc_type == doc_type,
            AcWriteOperation.doc_key == doc_key,
            AcWriteOperation.status == "in_progress",
            AcWriteOperation.updated_at >= since,
        )
        if exclude_id is not None:
            query = query.filter(AcWriteOperation.id != exclude_id)
        return query.first() is not None

    def pending_po_row_links(
        self, tenant_id: str, company_id: str, doc_key: int, dtl_key: Optional[int], *,
        exclude_id: Optional[str] = None,
    ) -> List[AcWriteOperation]:
        """The unresolved link operations on one PO row (``dtl_key`` None = on any row of the PO):
        ``pending_verification`` (outcome unknown) and ``needs_attention`` (may have landed in part); both
        may already have taken some of the row."""
        query = self.db.query(AcWriteOperation).filter(
            AcWriteOperation.tenant_id == tenant_id,
            AcWriteOperation.company_id == company_id,
            AcWriteOperation.doc_type == "PO",
            AcWriteOperation.doc_key == doc_key,
            AcWriteOperation.status.in_((OUTCOME_PENDING, "needs_attention")),
            AcWriteOperation.op.in_(("link_row", "relink_row", "link_batch", "split_link", "link_doc_batch")),
        )
        if dtl_key is not None:  # a document batch (plan 69) covers several rows: its snapshot says which
            query = query.filter(or_(AcWriteOperation.dtl_key == dtl_key, AcWriteOperation.op == "link_doc_batch"))
        if exclude_id is not None:
            query = query.filter(AcWriteOperation.id != exclude_id)
        return query.all()

    def link_results_on_doc(
        self, tenant_id: str, company_id: str, doc_key: int, ops: "tuple[str, ...]" = ("link_batch", "link_doc_batch"),
    ) -> List[AcWriteOperation]:
        """Plan 69: the link operations of ``ops`` on one PO that linked something (``done`` / ``needs_attention``):
        their stored answers say which PO row each new linked row came from."""
        return self.db.query(AcWriteOperation).filter(
            AcWriteOperation.tenant_id == tenant_id,
            AcWriteOperation.company_id == company_id,
            AcWriteOperation.doc_type == "PO",
            AcWriteOperation.doc_key == doc_key,
            AcWriteOperation.status.in_(("done", "needs_attention")),
            AcWriteOperation.op.in_(ops),
        ).all()

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
        self, tenant_id: str, company_id: str, entity_type: str, source_ref: str, *, skip_failed: bool = False
    ) -> Optional[AcStagedRecord]:
        """The newest non-delete staged row of one document. ``skip_failed``: leave out copies whose mapping
        FAILED (their raw may be truncated; the SPO / SO indexes read the newest GOOD copy, C.d review)."""
        query = self.db.query(AcStagedRecord).filter(
            AcStagedRecord.tenant_id == tenant_id,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.entity_type == entity_type,
            AcStagedRecord.source_ref == source_ref,
            AcStagedRecord.op != "delete",
        )
        if skip_failed:
            query = query.filter(AcStagedRecord.status != "FAILED")
        return query.order_by(AcStagedRecord.created_at.desc(), AcStagedRecord.id).first()

    def copies_at(
        self, tenant_id: str, company_id: str, entity_type: str, source_ref: str, created_at: datetime
    ) -> List[AcStagedRecord]:
        """Every non-delete staged copy of one document staged at ``created_at`` (equally new copies). The
        instant is matched in Python over the document's (id, created_at) pairs (exact on every engine), and
        only the matching copies' payloads are loaded."""
        scope = (
            AcStagedRecord.tenant_id == tenant_id,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.entity_type == entity_type,
            AcStagedRecord.source_ref == source_ref,
            AcStagedRecord.op != "delete",
            AcStagedRecord.status != "FAILED",
        )
        ids = [rid for rid, at in self.db.query(AcStagedRecord.id, AcStagedRecord.created_at).filter(*scope)
               if at == created_at]
        if not ids:
            return []
        return self.db.query(AcStagedRecord).filter(*scope, AcStagedRecord.id.in_(ids)).order_by(AcStagedRecord.id).all()

    def newest_by_doc_nos(
        self, tenant_id: str, company_id: str, entity_type: str, doc_nos: "set[str]"
    ) -> List[AcStagedRecord]:
        """The newest non-delete staged copy of each document whose ``doc_no`` is in ``doc_nos`` (indexed on
        (tenant, company, entity_type, doc_no), 0048)."""
        if not doc_nos:
            return []
        rows = (
            self.db.query(AcStagedRecord)
            .filter(
                AcStagedRecord.tenant_id == tenant_id,
                AcStagedRecord.company_id == company_id,
                AcStagedRecord.entity_type == entity_type,
                AcStagedRecord.doc_no.in_(sorted(doc_nos)),
                AcStagedRecord.op != "delete",
            )
            .order_by(AcStagedRecord.created_at.desc(), AcStagedRecord.id)
            .all()
        )
        newest: Dict[str, AcStagedRecord] = {}
        for row in rows:
            newest.setdefault(row.source_ref, row)
        return list(newest.values())

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


class SpoPoLinkRepository:
    """The SPO -> PO-row index ``ac_spo_po_link`` (lane AUTOCOUNT-STRANDED-OPS, C.d); every call is tenant +
    company scoped."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def replace_for_spo(
        self, tenant_id: str, company_id: str, spo_source_ref: str, spo_doc_no: Optional[str],
        links: "List[tuple[Optional[int], int, Decimal]]",
    ) -> None:
        """Swap one SPO's rows for ``links`` (``(spo_dtl_key, po_dtl_key, qty)``)."""
        self.db.query(AcSpoPoLink).filter(
            AcSpoPoLink.tenant_id == tenant_id,
            AcSpoPoLink.company_id == company_id,
            AcSpoPoLink.spo_source_ref == spo_source_ref,
        ).delete(synchronize_session=False)
        for spo_dtl_key, po_dtl_key, qty in links:
            self.db.add(AcSpoPoLink(
                tenant_id=tenant_id, company_id=company_id, spo_source_ref=spo_source_ref, spo_doc_no=spo_doc_no,
                spo_dtl_key=spo_dtl_key, po_dtl_key=po_dtl_key, qty=qty,
            ))
        self.db.flush()

    def spo_doc_no(self, tenant_id: str, company_id: str, po_dtl_key: int) -> Optional[str]:
        """DocNo of an indexed SPO with a row pointing at the PO row (None = none)."""
        row = (
            self.db.query(AcSpoPoLink.spo_doc_no, AcSpoPoLink.spo_source_ref)
            .filter(
                AcSpoPoLink.tenant_id == tenant_id,
                AcSpoPoLink.company_id == company_id,
                AcSpoPoLink.po_dtl_key == po_dtl_key,
            )
            .first()  # any one SPO answers the guard; no ORDER BY, so the po_dtl_key index drives the plan
        )
        return None if row is None else str(row[0] or row[1])

    def linked_qty(
        self, tenant_id: str, company_id: str, po_dtl_key: int, *, except_ref: Optional[str] = None
    ) -> Decimal:
        """Qty of one PO row taken by the indexed SPO rows, leaving out ``except_ref``."""
        query = self.db.query(func.coalesce(func.sum(AcSpoPoLink.qty), 0)).filter(
            AcSpoPoLink.tenant_id == tenant_id,
            AcSpoPoLink.company_id == company_id,
            AcSpoPoLink.po_dtl_key == po_dtl_key,
        )
        if except_ref is not None:
            query = query.filter(AcSpoPoLink.spo_source_ref != except_ref)
        return Decimal(str(query.scalar() or 0))

    def rows_on_po_row(self, tenant_id: str, company_id: str, book: str, po_dtl_key: int) -> List[AcSpoPoLink]:
        """Every indexed SPO row of the company's book ``book`` (its ``<book>:`` source refs) pointing at the PO
        row (plan 71 slice 2: the rows a PO split may carry along), in a stable order. A row indexed under another
        book (a book switch) is never carried along: its keys mean nothing in this one (review round 2)."""
        return (
            self.db.query(AcSpoPoLink)
            .filter(
                AcSpoPoLink.tenant_id == tenant_id,
                AcSpoPoLink.company_id == company_id,
                AcSpoPoLink.po_dtl_key == po_dtl_key,
                AcSpoPoLink.spo_source_ref.startswith(f"{book}:", autoescape=True),
            )
            .order_by(AcSpoPoLink.spo_source_ref, AcSpoPoLink.spo_dtl_key)
            .all()
        )


class SoRowIndexRepository:
    """The SO-row index ``ac_so_row_index`` (lane AUTOCOUNT-STRANDED-OPS, C.d); every call is tenant + company
    scoped."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def replace_for_so(
        self, tenant_id: str, company_id: str, so_source_ref: str, so_doc_no: Optional[str],
        staged_at: Optional[datetime], rows: "List[tuple[int, Optional[str], bool]]", so_doc_key: Optional[str] = None,
    ) -> None:
        """Swap one SO's rows for ``rows`` (``(so_dtl_key, location, ambiguous)``)."""
        self.db.query(AcSoRowIndex).filter(
            AcSoRowIndex.tenant_id == tenant_id,
            AcSoRowIndex.company_id == company_id,
            AcSoRowIndex.so_source_ref == so_source_ref,
        ).delete(synchronize_session=False)
        for so_dtl_key, location, ambiguous in rows:
            self.db.add(AcSoRowIndex(
                tenant_id=tenant_id, company_id=company_id, so_source_ref=so_source_ref, so_doc_no=so_doc_no,
                so_dtl_key=so_dtl_key, location=location, ambiguous=ambiguous, staged_at=staged_at,
                so_doc_key=so_doc_key,
            ))
        self.db.flush()

    def rows_for_keys(self, tenant_id: str, company_id: str, so_dtl_keys: "List[int]") -> List[AcSoRowIndex]:
        """The indexed rows holding any of ``so_dtl_keys`` (chunked IN lists)."""
        keys = sorted(set(so_dtl_keys))
        out: List[AcSoRowIndex] = []
        for start in range(0, len(keys), 500):
            out.extend(self.db.query(AcSoRowIndex).filter(
                AcSoRowIndex.tenant_id == tenant_id,
                AcSoRowIndex.company_id == company_id,
                AcSoRowIndex.so_dtl_key.in_(keys[start:start + 500]),
            ).all())
        return out

    def rows_for(self, tenant_id: str, company_id: str, so_dtl_key: int) -> List[AcSoRowIndex]:
        """The indexed rows holding ``so_dtl_key`` (normally one SO), newest staged first."""
        return (
            self.db.query(AcSoRowIndex)
            .filter(
                AcSoRowIndex.tenant_id == tenant_id,
                AcSoRowIndex.company_id == company_id,
                AcSoRowIndex.so_dtl_key == so_dtl_key,
            )
            .all()
        )
