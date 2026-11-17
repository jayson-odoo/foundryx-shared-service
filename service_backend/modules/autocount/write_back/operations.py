"""Write-back operations (plan 57 section 5.3, AC-57-30..40).

The level-2 unit a caller asks for: link / unlink / relink of a PO row (to an SO
row) or an SPO row (to a PO row), and the plan 55 split link, each under an
idempotency key. AutoCount never changes a link in place, so a row operation is
snapshot -> ONE replace PUT (the row ``"D"`` plus a new row with the new link or
none, plan 61 F4 / F5, all or nothing F8) -> move the new row's location and
delivery date back (AutoCount forces HQ and clears the date on a new linked row),
every step one primitive (``PrimitiveService``, no second write frame). A partly
received row is cut to its received qty and the remainder added. The cross-step
busy lock is the ``in_progress`` partial unique index of ``ac_write_operation``.
A replace that landed wrong (or a remainder add that failed) is recovered from the
snapshot; when that fails too the operation is ``needs_attention``, one alert mail
goes out and nothing is retried automatically; ``resume`` re-reads AutoCount and
re-creates the line only when it is still absent.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import html
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, ContextManager, Dict, Iterator, List, Optional, Tuple, Union

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modules.autocount.alerts import _safe_subject, alert_recipients
from modules.autocount.canonical.documents import ENTITY_SALES_ORDER
from modules.autocount.models import AcCompany, AcWriteOperation
from modules.autocount.repositories import CompanyRepository
from modules.autocount.write_back import call_log as cl, capabilities, frame, guard, payloads
from modules.autocount.write_back.guard import WriteConnectionError
from modules.autocount.write_back.constants import EDIT_PO_PATH
from modules.autocount.write_back.frame import (
    BUSY_WINDOW_SECONDS,
    DOC_BUSY,
    DOC_STALE,
    INTERNAL_ERROR,
    OUTCOME_DONE,
    OUTCOME_MISMATCH,
    OUTCOME_PENDING,
    OUTCOME_REFUSED,
    OUTCOME_VENDOR_ERROR,
    VENDOR_UNSUPPORTED,
    WRITE_DISABLED,
    WriteActionResult,
    _dec,
    _lines,
)
from modules.autocount.write_back.doc_kinds import KINDS, WIRE_SLUGS
from modules.autocount.write_back.link_index import refresh_po_links_from_doc
from modules.autocount.write_back.link_lock import SoRowBusy, link_locks, so_row_locks
from modules.autocount.write_back.payloads import WriteRefusal
from modules.autocount.write_back.primitives import (
    ROW_NEEDS_ATTENTION,
    VENDOR_REFUSED,
    PrimitiveResult,
    PrimitiveService,
)
from modules.autocount.write_back.reader import DocReadError
from modules.autocount.write_back.repository import OperationRepository, SpoPoLinkRepository
from modules.autocount.write_back.service import WriteBackService

logger = logging.getLogger("foundryx.autocount")

Doc = Dict[str, Any]

# operation statuses (= the answer's outcome)
IN_PROGRESS = "in_progress"
DONE = "done"
REFUSED = "refused"
RECOVERED = "recovered"
NEEDS_ATTENTION = "needs_attention"
PENDING = "pending_verification"
VENDOR_ERROR = "vendor_error"

IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
OPERATION_IN_PROGRESS = "OPERATION_IN_PROGRESS"
UNKNOWN_OPERATION = "UNKNOWN_OPERATION"
OPERATION_NOT_RESUMABLE = "OPERATION_NOT_RESUMABLE"
INVALID_PARAMS = "INVALID_PARAMS"
ROW_RECEIVED = "ROW_RECEIVED"
TRANSFER_STATE_UNKNOWN = "TRANSFER_STATE_UNKNOWN"
LOCATION_NOT_MOVED = "LOCATION_NOT_MOVED"
ROW_VALUES_NOT_KEPT = "ROW_VALUES_NOT_KEPT"
NOT_APPLIED = "OPERATION_NOT_APPLIED"
SPLIT_LINK = "split_link"
LINK_BATCH = "link_batch"  # plan 62: one PO row to N SO rows in one PUT
ALL_LINKS_SKIPPED = "ALL_LINKS_SKIPPED"
RESTORE_NOT_LANDED = "RESTORE_NOT_LANDED"  # plan 65 D3: the batch's restore PUT did not land (resumable)
FOC_ON_ROW = "FOC_ON_ROW"  # plan 65 D2a: the line would take the whole of a row carrying FOC (hapi cannot move it)
MAX_BATCH_LINKS = 20
TEMPLATE_KEY = "autocount_write_needs_attention"

# Plan 62 review: vendor exception classes proven to refuse BEFORE anything is saved (db3 probe, 11 Nov
# 2026): a create refused with one of these created no document, so its key is released at once.
PRE_SAVE_REFUSALS = frozenset({
    "ViolateCreditLimitNotAllowToSaveException", "NotExistItemCodeException", "DebtorRecordNotFoundException",
})
CREATE_AMBIGUOUS = "CREATE_AMBIGUOUS"
LOOKUP_WINDOW_SECONDS = 600  # AutoCount stamps with the customer server's clock, which may be minutes off ours
LOOKUP_MAX_DAYS = 7

ReceiptReader = Callable[[str, Doc, Doc], Optional[Decimal]]
Notifier = Callable[[Dict[str, Any]], None]


@dataclass(frozen=True)
class _OpDef:
    """``kind`` = the document the row lives on, ``target`` = what it links to."""

    kind: str
    target: Optional[str]
    mode: str  # link | unlink | relink


OPS: Dict[str, _OpDef] = {
    "link_row": _OpDef("PO", "SO", "link"),
    "unlink_row": _OpDef("PO", None, "unlink"),
    "relink_row": _OpDef("PO", "SO", "relink"),
    "spo_link_row": _OpDef("SPO", "PO", "link"),
    "spo_unlink_row": _OpDef("SPO", None, "unlink"),
    "spo_relink_row": _OpDef("SPO", "PO", "relink"),
}
_PARAM_NAMES = {
    "PO": ("doc_key", "dtl_key", "so_doc_key", "so_dtl_key"),
    "SPO": ("spo_doc_key", "spo_dtl_key", "po_doc_key", "po_dtl_key"),
}
_NO_LINK = {"FromDocType": "", "FromDocNo": "", "FromDocDtlKey": 0}
# The vendor switch an op needs on top of the primitives (plan 61 section 4.5).
_OP_FLAGS = {("PO", "link"): "link_existing_row", ("PO", "relink"): "link_existing_row", ("PO", "unlink"): "unlink"}
_OP_PRIMITIVES = ("delete_line", "add_line", "edit_doc")


def op_capable(defn: "_OpDef") -> bool:
    """A row op = one replace PUT (delete_line + add_line on the edit door) and the
    move edit; a PO op also needs its vendor switch."""
    if not all(capabilities.capable(defn.kind, p) for p in _OP_PRIMITIVES):
        return False
    flag = _OP_FLAGS.get((defn.kind, defn.mode))
    return flag is None or bool(capabilities.VENDOR_CAPABILITIES.get(flag))


@dataclass
class OperationResult:
    """The answer of ``run`` / ``resume`` / ``get`` (stored verbatim for replays)."""

    operation_id: Optional[str]
    outcome: str
    error_code: Optional[str] = None
    message: str = ""
    warnings: List[str] = field(default_factory=list)
    replaced_lines: List[Tuple[int, int]] = field(default_factory=list)
    document: Optional[Doc] = None
    doc_key: Optional[int] = None
    doc_no: Optional[str] = None
    batch: Optional[Dict[str, Any]] = None  # link_batch only: {"links": [...], "freeLine": {...} | None}
    detail: Optional[Doc] = None  # plan 64: link_row / split_link - the PO row the link landed on


@dataclass
class _Spec:
    doc_key: int
    dtl_key: int
    target_doc_key: Optional[int] = None
    target_dtl_key: Optional[int] = None
    doc_date: Optional[date] = None
    expected_last_modified: Optional[str] = None
    target_doc_date: Optional[date] = None  # AC-57-44: soDocDate / poDocDate for an unstaged target


class _Done(Exception):
    """Internal early exit carrying a finished result."""

    def __init__(self, status: str, code: Optional[str] = None, message: str = "",
                 batch: Optional[Dict[str, Any]] = None) -> None:
        self.status, self.code, self.message, self.batch = status, code, message, batch


def primitive_answer(res: PrimitiveResult, doc_key: Optional[int] = None) -> Dict[str, Any]:
    """The gateway answer of a primitive (contract section 4)."""
    return {
        "operationId": None, "actionId": res.action_id, "outcome": res.outcome, "errorCode": res.error_code,
        "message": res.message, "warnings": list(res.warnings), "docKey": res.doc_key or doc_key,
        "docNo": res.doc_no, "replacedLines": [], "document": res.document,
    }


def _as_date(value: Any) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _doc_no(document: Optional[Doc], snapshot: Optional[Doc]) -> Optional[str]:
    number = (document or {}).get("DocNo") or (snapshot or {}).get("docNo")
    return str(number) if number else None


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _row_in(document: Optional[Doc], dtl_key: int) -> Optional[Doc]:
    """Plan 64: row ``dtl_key`` of the read-back ``document`` (the ``detail`` answer)."""
    return next((r for r in (document or {}).get("Details") or [] if r.get("DtlKey") == dtl_key), None)


def received_message(kind: str, row: Doc) -> str:
    """Plan 64: the plain reason for ``ROW_RECEIVED`` (the CRM shows it as is)."""
    where = f" at {row['Location']}" if row.get("Location") else ""
    noun = "shipping purchase order" if kind == "SPO" else "purchase order"
    return (f"Goods have already been received on this {noun} line{where}, so the change was not made. "
            "Handle the received goods in AutoCount, then try again.")


def _link_of(kind: str, row: Doc) -> int:
    """The link key a row reads back with: PO rows carry ``FromSODtlKey``, SPO
    rows ``FromDocDtlKey``."""
    return int((row.get("FromSODtlKey") if kind == "PO" else row.get("FromDocDtlKey")) or 0)


class _AmbiguousCreate(Exception):
    """More than one document matches a create that may have landed."""


class _LookupFailed(Exception):
    """The document could not be looked up (no write connection, a failed read)."""


def _create_info(kind: str, params: Dict[str, Any], started: datetime) -> Dict[str, Any]:
    """What a later lookup needs to find the document this create may have saved."""
    header = params.get("header") if isinstance(params.get("header"), dict) else {}
    number = str(header.get("docNo") or "").strip()
    lines = []
    for line in params.get("lines") if isinstance(params.get("lines"), list) else []:
        if isinstance(line, dict):
            lines.append([line.get("itemCode"), str(line.get("qty")), line.get("uom")])
    return {
        "kind": kind, "docNo": None if number in ("", "<<New>>") else number,
        "party": header.get("debtorCode") or header.get("creditorCode"), "lines": lines,
        "start": started.isoformat(),
    }


def sweep_stranded_operations(db: Session) -> int:
    """API-start crash sweep: every ``in_progress`` operation older than the busy window was left by a
    process that died (gunicorn timeout, OOM kill, deploy) -> ``pending_verification``. A never-applied
    one is then settled ``recovered`` by its next resend / resume (BL-SS-368). Returns how many."""
    window = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS)
    swept = OperationRepository(db).sweep_stale_in_progress(window)
    db.commit()
    return swept


class OperationService:
    def __init__(
        self,
        db: Session,
        *,
        client_factory: Optional[Callable[[str], Any]] = None,
        reader_factory: Optional[Callable[[str], Any]] = None,
        sink_factory: Optional[Callable[..., Any]] = None,
        receipt_reader: Optional[ReceiptReader] = None,
        notifier: Optional[Notifier] = None,
        actor: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        self.db = db
        self.prims = PrimitiveService(
            db, client_factory=client_factory, reader_factory=reader_factory, sink_factory=sink_factory,
            actor=actor, request_id=request_id,
        )
        self.ops = OperationRepository(db)
        self._receipt_reader = receipt_reader  # None = the default source order (frame)
        self._notifier = notifier or self._mail
        self._steps: List[Dict[str, Any]] = []
        self._warnings: List[str] = []
        self._mail_allowed = True
        self._base_url = ""
        self._row: Optional[AcWriteOperation] = None
        self._op_deadline = 0.0
        # (kind, doc_key) -> (date, document | the read's exception): a side read made beside another
        # GET, consumed by the next ``_read`` of that document (SS-AUTOCOUNT-SPEEDUP).
        self._prefetched: Dict[Tuple[str, int], Tuple[date, Any]] = {}

    # ── public ───────────────────────────────────────────────────────────────

    def use_trace(
        self, request_id: Optional[str], person: "Tuple[Optional[str], Optional[str]]" = (None, None)
    ) -> None:
        """The caller's request id and acting person for every step (plan 61 section 4.8, plan 63)."""
        self.prims.use_trace(request_id, person)

    def _reader(self, company: AcCompany, base_url: str, kind: str, doc_key: Optional[int], doc_no: Optional[str]) -> Any:
        """A reader whose GETs are logged under this operation (plan 61 section 4.8)."""
        row = self._row
        log = self.prims.new_call_log(
            company, kind=kind, doc_key=doc_key, doc_no=doc_no, key_id=row.key_id if row else None,
            operation_id=row.id if row else None,
        )
        return self.prims._reader_for(base_url, log)

    def get(self, *, tenant_id: str, company_id: str, operation_id: str) -> OperationResult:
        row = self.ops.get(tenant_id, company_id, operation_id)
        if row is None:
            raise LookupError("operation not found")
        return self._from_row(row)

    def run(
        self, *, tenant_id: str, company_id: str, key_id: Optional[str], idempotency_key: str,
        op: str, params: Dict[str, Any],
    ) -> OperationResult:
        company = CompanyRepository(self.db).get(tenant_id, company_id)
        if company is None:
            return OperationResult(None, REFUSED, WRITE_DISABLED)
        if op not in (SPLIT_LINK, LINK_BATCH) and op not in OPS:
            return OperationResult(None, REFUSED, UNKNOWN_OPERATION)
        request_hash = hashlib.sha256(
            json.dumps({"op": op, "params": params}, sort_keys=True, default=str).encode()
        ).hexdigest()
        existing = self.ops.by_key(tenant_id, company.id, key_id, idempotency_key)
        if existing is not None and existing.status == IN_PROGRESS:
            # a same-key resend of a crashed run (its worker killed before ``_guarded``'s finally): past the busy
            # window it is reconciled like any stale op, then settled below, never OPERATION_IN_PROGRESS for ever
            window = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS)
            if self.ops.expire_stale_operation(tenant_id, company.id, existing.id, window):
                self.db.commit()
                self.db.refresh(existing)
        if existing is not None:
            settled = self._settle_existing(existing, tenant_id, company, op, request_hash)
            if settled is not None:
                return settled
        try:
            spec = self._spec(op, params)
        except (KeyError, TypeError, ValueError):
            return OperationResult(None, REFUSED, INVALID_PARAMS)
        kind = OPS[op].kind if op in OPS else "PO"
        window = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS)
        if self.ops.expire_stale_in_progress(tenant_id, company.id, kind, spec.doc_key, window):
            self.db.commit()  # a crashed run no longer holds the document (AC-57-43)
        row = AcWriteOperation(
            tenant_id=tenant_id, company_id=company.id, key_id=key_id, idempotency_key=idempotency_key,
            request_hash=request_hash, op=op, doc_type=kind, doc_key=spec.doc_key, dtl_key=spec.dtl_key,
            status=IN_PROGRESS,
        )
        try:
            self.ops.add(row)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raced = self.ops.by_key(tenant_id, company.id, key_id, idempotency_key)
            if raced is not None:
                return self._replay(raced, op, request_hash)
            return OperationResult(None, REFUSED, DOC_BUSY)  # not stored: the key stays usable
        self._steps, self._warnings = [], []
        self._mail_allowed = True
        self._row = row
        self._op_deadline = time.monotonic() + frame.ACTION_DEADLINE_SECONDS
        return self._guarded(row, company, lambda: self._execute(row, company, op, spec, params))

    def resume(self, *, tenant_id: str, company_id: str, operation_id: str) -> OperationResult:
        row = self.ops.get(tenant_id, company_id, operation_id)
        if row is None:
            raise LookupError("operation not found")
        if row.doc_key is not None:
            # plan 65 B2: a request that died mid-way never holds the document (or itself) for ever: the same
            # expiry as ``run`` (AC-57-43), updated_at kept; a young in_progress op is still respected
            window = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS)
            if self.ops.expire_stale_in_progress(tenant_id, row.company_id, row.doc_type, row.doc_key, window):
                self.db.commit()
                self.db.refresh(row)
        if row.status == IN_PROGRESS:
            return OperationResult(row.id, REFUSED, OPERATION_IN_PROGRESS)
        if row.op != SPLIT_LINK and row.op != LINK_BATCH and row.op not in OPS:
            return OperationResult(row.id, REFUSED, OPERATION_NOT_RESUMABLE)  # a document primitive (create): untouched
        if self._never_applied(row):
            return self._settle_not_applied(row)
        if row.status not in (NEEDS_ATTENTION, PENDING) or not row.snapshot_json or row.op == SPLIT_LINK:
            return self._from_row(row)
        company = CompanyRepository(self.db).get(tenant_id, company_id)
        if company is None:
            return OperationResult(row.id, REFUSED, WRITE_DISABLED)
        was = row.status
        # a resume re-reads and may PUT the PO: it holds the per-PO-document lock from before the claim to the
        # end; not won = DOC_BUSY with the row untouched (still resumable)
        locks = ExitStack()
        try:
            locks.enter_context(link_locks(self.db, company.id, po_doc_keys=[row.doc_key] if row.doc_type == "PO" else []))
        except SoRowBusy:
            return OperationResult(row.id, REFUSED, DOC_BUSY)
        with locks:
            try:
                claimed = self.ops.claim(tenant_id, company_id, row.id, (NEEDS_ATTENTION, PENDING))
                self.db.commit()
            except IntegrityError:  # another operation holds the document
                self.db.rollback()
                return OperationResult(row.id, REFUSED, DOC_BUSY)
            if not claimed:  # a concurrent resume won the conditional update
                return OperationResult(row.id, REFUSED, OPERATION_IN_PROGRESS)
            self.db.refresh(row)
            self._mail_allowed = was != NEEDS_ATTENTION  # a failed resume never mails again
            self._row = row
            self._op_deadline = time.monotonic() + frame.ACTION_DEADLINE_SECONDS
            self._steps, self._warnings = list(row.steps_json or []), []
            return self._guarded(row, company, lambda: self._resume(row, company, was), restore=was)

    # ── frame ────────────────────────────────────────────────────────────────

    def _guarded(self, row: AcWriteOperation, company: AcCompany, body: Callable[[], OperationResult],
                 restore: Optional[str] = None) -> OperationResult:
        """Run ``body``; whatever happens the operation row leaves ``in_progress``."""
        try:
            return body()
        except _Done as done:
            if done.code == DOC_BUSY and restore is None:  # never stored under the key
                self.ops.delete(row)
                self.db.commit()
                return OperationResult(None, REFUSED, DOC_BUSY)
            return self._finish(row, done.status, done.code, message=done.message, batch=done.batch)
        except Exception:  # noqa: BLE001 - the in_progress lock must never be stranded
            logger.exception("autocount operation failed (%s)", row.id)
            self.db.rollback()
            return self._finish(row, restore or PENDING, INTERNAL_ERROR)
        finally:
            self._prefetched = {}  # an unused side read never outlives its run
            self.db.rollback()

    @staticmethod
    def _spec(op: str, params: Dict[str, Any]) -> _Spec:
        if op == LINK_BATCH:
            if not isinstance(params["links"], list):
                raise TypeError("links")
            return _Spec(
                int(params["doc_key"]), int(params["dtl_key"]), None, None,
                params.get("doc_date"), params.get("expected_last_modified"), None,
            )
        if op == SPLIT_LINK:
            return _Spec(
                int(params["po_doc_key"]), int(params["po_dtl_key"]),
                int(params["so_doc_key"]), int(params["so_dtl_key"]),
                params.get("doc_date"), params.get("expected_last_modified"), params.get("target_doc_date"),
            )
        names = _PARAM_NAMES[OPS[op].kind]
        target = OPS[op].target
        return _Spec(
            int(params[names[0]]), int(params[names[1]]),
            int(params[names[2]]) if target else None, int(params[names[3]]) if target else None,
            params.get("doc_date"), params.get("expected_last_modified"), params.get("target_doc_date"),
        )

    @staticmethod
    def _nothing_landed(status: Optional[str], code: Optional[str]) -> bool:
        """Plan 62 D6: the stored outcome proves nothing reached AutoCount: a refusal, or AutoCount's
        own business refusal (``VENDOR_REFUSED``). A bare vendor failure (5xx, IIS page) may have landed.
        Plan 65 B3 (owner: only a confirmed success locks): every ``recovered`` answer, whatever its code,
        left the PO as it was; the next press runs fresh (re-read and re-guarded, so it cannot write twice)."""
        return (status == REFUSED or (status == VENDOR_ERROR and code == VENDOR_REFUSED)
                or status == RECOVERED)

    def _release_key(self, row: AcWriteOperation) -> None:
        """Free the idempotency key of a confirmed not-landed operation: the row is kept for history
        under a re-keyed value, so a resend runs fresh (any body)."""
        # \x1f is outside the printable range the Idempotency-Key header accepts, so no client can send this form
        self.ops.rekey(row, f"{row.idempotency_key}\x1freleased\x1f{row.id}")
        self.db.commit()

    def _settle_existing(self, row: AcWriteOperation, tenant_id: str, company: AcCompany, op: str,
                         request_hash: str) -> Optional[OperationResult]:
        """The answer for a key that already has a row, or None when the key was released and the
        operation must run fresh (plan 62 D6)."""
        if self._nothing_landed(row.status, row.error_code):
            self._release_key(row)
            return None
        if (row.status == PENDING and row.op == op and row.request_hash == request_hash
                and (row.snapshot_json or self._never_applied(row))):
            res = self.resume(tenant_id=tenant_id, company_id=company.id, operation_id=row.id)
            if res.error_code == NOT_APPLIED and res.outcome in (RECOVERED, REFUSED):
                fresh = self.ops.get(tenant_id, company.id, row.id)
                if fresh is not None:  # reconciled: the first request never changed AutoCount
                    self._release_key(fresh)
                    return None
            return res
        return self._replay(row, op, request_hash)

    def _never_applied(self, row: AcWriteOperation) -> bool:
        """BL-SS-368: a pending row operation that never stored its snapshot never wrote: every row
        operation commits its snapshot BEFORE its first AutoCount write (``_execute_unlocked``,
        ``_batch_locked``, ``_split_link``). Belt and braces: no step and no write action recorded."""
        return (row.status == PENDING and not row.snapshot_json and not row.steps_json
                and (row.op in OPS or row.op in (SPLIT_LINK, LINK_BATCH))
                and not self.ops.has_actions(row.tenant_id, row.id))

    def _settle_not_applied(self, row: AcWriteOperation) -> OperationResult:
        """End a never-applied pending operation ``recovered`` / ``OPERATION_NOT_APPLIED`` (conditional, so
        a concurrent settle or resume wins once); the next same-key press then runs fresh."""
        message = "Nothing was changed in AutoCount. Please try again."
        result = OperationResult(row.id, RECOVERED, NOT_APPLIED, message, doc_key=row.doc_key)
        stored = _json_safe({
            "outcome": RECOVERED, "errorCode": NOT_APPLIED, "message": message, "warnings": [],
            "replacedLines": [], "document": None, "batch": None, "detail": None,
        })
        settled = self.ops.settle_not_applied(row.tenant_id, row.company_id, row.id, NOT_APPLIED, stored)
        self.db.commit()
        self.db.refresh(row)
        if not settled:
            return self._from_row(row) if row.status != IN_PROGRESS else OperationResult(
                row.id, REFUSED, OPERATION_IN_PROGRESS)
        logger.warning("autocount operation %s ended before its snapshot: settled as not applied", row.id)
        return result

    def _replay(self, row: AcWriteOperation, op: str, request_hash: str) -> OperationResult:
        if row.op != op or row.request_hash != request_hash:
            return OperationResult(None, REFUSED, IDEMPOTENCY_CONFLICT)
        if row.status == IN_PROGRESS:
            return OperationResult(row.id, REFUSED, OPERATION_IN_PROGRESS)
        return self._from_row(row)

    @staticmethod
    def _from_row(row: AcWriteOperation) -> OperationResult:
        stored = row.result_json or {}
        return OperationResult(
            row.id, stored.get("outcome") or row.status, stored.get("errorCode", row.error_code),
            stored.get("message") or "", list(stored.get("warnings") or []),
            [(int(o), int(n)) for o, n in stored.get("replacedLines") or []], stored.get("document"),
            row.doc_key, _doc_no(stored.get("document"), row.snapshot_json), stored.get("batch"),
            stored.get("detail"),
        )

    def _finish(self, row: AcWriteOperation, status: str, code: Optional[str] = None, *, message: str = "",
                replaced: Optional[List[Tuple[int, int]]] = None,
                document: Optional[Doc] = None, batch: Optional[Dict[str, Any]] = None,
                detail: Optional[Doc] = None) -> OperationResult:
        result = OperationResult(
            row.id, status, code, message, list(self._warnings), list(replaced or []), document,
            row.doc_key, _doc_no(document, row.snapshot_json), batch, detail if status == DONE else None,
        )
        row.status, row.error_code = status, code
        row.steps_json = _json_safe(self._steps)
        row.result_json = _json_safe({
            "outcome": status, "errorCode": code, "message": message, "warnings": result.warnings,
            "replacedLines": [list(p) for p in result.replaced_lines], "document": document,
            "batch": batch, "detail": result.detail,
        })
        self.db.commit()
        return result

    def _step(self, name: str, res: PrimitiveResult) -> None:
        self._steps.append({"step": name, "outcome": res.outcome, "code": res.error_code,
                            "actionId": res.action_id, "newDtlKey": res.new_dtl_key})
        if self._row is not None:  # heartbeat: a live operation never looks stale (AC-57-43)
            self._row.updated_at = datetime.now(timezone.utc)
            self._row.steps_json = _json_safe(self._steps)
            self.db.commit()

    def _check_deadline(self) -> None:
        """No further step past the operation-wide deadline (below the busy window,
        read through ``time`` so a patched clock works): pending_verification, resumable."""
        if time.monotonic() > self._op_deadline:
            raise _Done(PENDING, "DEADLINE_EXCEEDED")

    # ── execute ──────────────────────────────────────────────────────────────

    def _execute(self, row: AcWriteOperation, company: AcCompany, op: str, spec: _Spec,
                 params: Dict[str, Any]) -> OperationResult:
        """Every row operation that writes a PO (the document primitives keep the action / operation indexes)
        runs under the per-PO-document lock, and a link-type operation
        also under its per-SO-row lock (``link_lock``, PO first): the read, the over-link guard and the write
        that follows must not interleave with another caller's on the same PO or the same SO row. A lock not
        won is ``DOC_BUSY`` (never stored under the key)."""
        po_keys = [spec.doc_key] if row.doc_type == "PO" else []
        so_keys = [spec.target_dtl_key] if op in (SPLIT_LINK, "link_row", "relink_row") and spec.target_dtl_key else []
        try:
            with link_locks(self.db, company.id, po_doc_keys=po_keys, so_dtl_keys=so_keys):
                return self._execute_unlocked(row, company, op, spec, params)
        except SoRowBusy:  # this lock, or a nested one (the batch's SO rows), was not won: nothing sent
            raise _Done(REFUSED, DOC_BUSY) from None

    def _execute_unlocked(self, row: AcWriteOperation, company: AcCompany, op: str, spec: _Spec,
                          params: Dict[str, Any]) -> OperationResult:
        base_url, refusal = self.prims._resolve_write_base_url(company)
        if base_url is None:
            if refusal:
                self.prims._log_refused_connection(company, refusal[0], doc_key=spec.doc_key)
            raise _Done(REFUSED, refusal[0] if refusal else WRITE_DISABLED)
        self._base_url = base_url
        self._prefetched = {}
        self._check_test_company(company)
        if op == LINK_BATCH:
            return self._batch_link(row, company, spec, params)
        if op == SPLIT_LINK or (
            op == "link_row" and not params.get("whole_row") and self._is_part_of_row(company, base_url, spec, params)
        ):
            return self._split_link(row, company, spec, params)
        defn = OPS[op]
        if not op_capable(defn):
            raise _Done(REFUSED, VENDOR_UNSUPPORTED)
        self._check_not_busy(company, spec.doc_key, defn.kind)
        doc_date, doc = self._read(company, defn.kind, spec.doc_key, spec.doc_date,
                                   beside=self._target_beside(company, defn, spec))
        if spec.expected_last_modified and doc.get("LastModified") != spec.expected_last_modified:
            raise _Done(REFUSED, DOC_STALE)
        if defn.kind == "PO" and defn.mode in ("unlink", "relink"):
            self._check_row_resolved(company, spec, doc)
        if defn.kind == "PO" and defn.mode in ("link", "relink"):
            self._log_remark_overwrite(doc)
        with self.prims.staged_memo():  # C.d: one staged read per document for the row AND every merge candidate
            plan = self._guards(company, defn, spec, doc)
        snapshot = self._snapshot(company, defn, spec, doc, doc_date, plan)
        row.snapshot_json = snapshot
        self.db.commit()
        return self._steps_run(row, company, op, defn, spec, snapshot)

    def _is_part_of_row(self, company: AcCompany, base_url: str, spec: _Spec, params: Dict[str, Any]) -> bool:
        """A ``link_row`` that names a qty below the FRESH row qty is the split link
        (no delete needed); anything else, or a row that cannot be read, is a whole row."""
        if params.get("qty") is None:
            return False
        found, _code = self.prims.find_date(company, "PO", spec.doc_key, spec.doc_date)
        if found is None:
            return False
        doc_no = self.prims.find_doc_no(company, "PO", spec.doc_key)
        reader = self._reader(company, base_url, "PO", spec.doc_key, doc_no)  # before the commit (row ids)
        self.db.commit()
        try:
            fresh = reader.get_document("PO", spec.doc_key, found, doc_no=doc_no)
        except DocReadError:
            return False
        row = next((r for r in fresh.get("Details") or [] if r.get("DtlKey") == spec.dtl_key), None)
        return row is not None and _dec(row.get("Qty")) != _dec(params["qty"])

    def _check_test_company(self, company: AcCompany, restore: Optional[str] = None) -> None:
        try:
            guard.assert_test_company(
                self.db, company.tenant_id, company.id, book=self.prims._company_book(company))
        except WriteConnectionError as exc:
            raise _Done(restore or REFUSED, exc.code) from None

    def _check_not_busy(self, company: AcCompany, doc_key: int, kind: str) -> None:
        """Standalone actions, young pending operations and other ``in_progress`` operations hold the
        document; an operation's own actions and its own row do not (the row carries its age, AC-57-43)."""
        window = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS)
        if self.prims.actions.expire_stale_in_flight(company.tenant_id, company.id, doc_key, window):
            self.db.commit()
        if self.prims.actions.has_open(
            company.tenant_id, company.id, doc_key, window, standalone_only=True
        ) or self.ops.has_recent_pending(company.tenant_id, company.id, kind, doc_key, window) or self.ops.has_in_progress(
            company.tenant_id, company.id, kind, doc_key, window, exclude_id=self._row.id if self._row else None,
        ):
            raise _Done(REFUSED, DOC_BUSY)

    def _check_row_resolved(self, company: AcCompany, spec: _Spec, doc: Doc) -> None:
        """Plan 65 D6: an unlink / relink of a PO row an unresolved link operation covers is refused
        ``ROW_NEEDS_ATTENTION`` before anything is sent (Resume is the repair). Same rule as the
        ``delete_line`` primitive (``PrimitiveService.row_needs_attention``); other rows stay writable."""
        row = next((r for r in doc.get("Details") or [] if r.get("DtlKey") == spec.dtl_key), None)
        if row is not None and self.prims.row_needs_attention(
                company, spec.doc_key, row, exclude_id=self._row.id if self._row else None):
            raise _Done(REFUSED, ROW_NEEDS_ATTENTION)

    def _log_remark_overwrite(self, doc: Doc) -> None:
        """Plan 65 D1b (owner ruling 16 Nov: no warning to users): AutoCount writes Remark1 over
        Remark2..4 on every PUT; a link on a PO whose remarks differ leaves one server-side line
        (operation id only, never the text; the old texts stay in the step's stored before-read)."""
        first = doc.get("Remark1")
        if any(not payloads._same(doc.get(k), first) for k in ("Remark2", "Remark3", "Remark4")):
            logger.info("autocount link on a PO whose Remark2..4 differ from Remark1 (operation %s)",
                        self._row.id if self._row else None)

    def _read(self, company: AcCompany, kind: str, doc_key: int,
              doc_date: Optional[date], *, beside: Optional[ContextManager[None]] = None) -> Tuple[date, Doc]:
        """AC-57-20 date, then one fresh GET with no transaction open. ``beside`` runs around the GET
        only (the independent target read, ``_target_beside``); a read it already made is used here."""
        held = self._prefetched.pop((kind, doc_key), None)
        if held is not None:
            found, outcome = held
            if isinstance(outcome, DocReadError):
                raise _Done(REFUSED, outcome.code) from None
            if isinstance(outcome, BaseException):
                raise outcome
            return found, outcome
        found, code = self.prims.find_date(company, kind, doc_key, _as_date(doc_date))
        if found is None:
            raise _Done(REFUSED, code)
        doc_no = self.prims.find_doc_no(company, kind, doc_key)
        reader = self._reader(company, self._base_url, kind, doc_key, doc_no)  # before the commit (row ids)
        self.db.commit()
        with beside or contextlib.nullcontext():
            try:
                return found, reader.get_document(kind, doc_key, found, doc_no=doc_no)
            except DocReadError as exc:
                raise _Done(REFUSED, exc.code) from None

    @contextlib.contextmanager
    def _target_beside(self, company: AcCompany, defn: _OpDef, spec: _Spec) -> Iterator[None]:
        """SS-AUTOCOUNT-SPEEDUP: the target document's first read (SO for a PO link, PO for an SPO
        link) does not depend on the document's own, so it runs on a second thread during it. Nothing
        else moves: the target is still checked in ``_guard_target`` after the document's own guards
        (same refusal order and codes), every call is still logged (``BufferedCallLog``, written here on
        this thread), and the live re-read before the write is untouched. No date for the target = no
        side read (``_guard_target`` refuses it as before)."""
        key = spec.target_doc_key
        if not defn.target or key is None:
            yield
            return
        found, _code = self.prims.find_date(company, defn.target, key, _as_date(spec.target_doc_date))
        if found is None:
            yield
            return
        doc_no = self.prims.find_doc_no(company, defn.target, key)
        row = self._row
        log = cl.BufferedCallLog(self.prims.new_call_log(
            company, kind=defn.target, doc_key=key, doc_no=doc_no, key_id=row.key_id if row else None,
            operation_id=row.id if row else None,
        ))
        reader = self.prims._reader_for(self._base_url, log)  # type: ignore[arg-type]
        self.db.commit()  # no transaction open during the GETs
        context = contextvars.copy_context()  # request id / logging / tracing context follow the read
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="ac-side-read") as pool:
            future = pool.submit(context.run, reader.get_document, defn.target, key, found, doc_no=doc_no)
            failed = True
            try:
                yield
                failed = False
            finally:
                # Waited for even when the document's own read failed: its calls are then logged
                # here, on this thread, like every other call (the log's session never crosses threads).
                try:
                    outcome: Any = future.result()
                except BaseException as exc:  # noqa: BLE001 - handed to the target's own _read
                    outcome = exc
                log.flush()
                if not failed:  # a refused run never leaves a read behind for a later one
                    self._prefetched[(defn.target, key)] = (found, outcome)

    # ── guards (AC-57-32, 33): every refusal before any write ────────────────

    def _guards(self, company: AcCompany, defn: _OpDef, spec: _Spec, doc: Doc) -> Dict[str, Any]:
        try:
            row = payloads.check_row(defn.kind, doc, spec.dtl_key)  # kind, cancelled, row exists
        except WriteRefusal as exc:
            raise _Done(REFUSED, exc.code, str(exc)) from None
        if defn.kind == "PO" and self._spo_ref(company, spec.dtl_key):
            raise _Done(REFUSED, "ROW_ON_SPO")
        linked = _link_of(defn.kind, row)
        if defn.mode == "link" and linked:
            raise _Done(REFUSED, "ROW_ALREADY_LINKED")
        if defn.mode in ("unlink", "relink") and not linked:
            raise _Done(REFUSED, "ROW_NOT_LINKED")
        if defn.mode == "relink" and linked == spec.target_dtl_key:
            raise _Done(REFUSED, "NO_CHANGE")
        mode, received = self._receipt(company, defn, doc, row)
        qty = _dec(row.get("Qty"))
        link_qty = qty - received if mode == "partial" else qty
        if defn.kind == "PO" and mode == "delete" and payloads.foc_on_row(row, link_qty):
            # plan 65 D2a / AC-65-28 / B1: a link, unlink (merge or replace) or relink that removes a row carrying
            # FOC would lose it (hapi cannot write FOCQty): the batch's skip rule, refused before any PUT
            raise _Done(REFUSED, FOC_ON_ROW)
        target: Optional[Doc] = None
        if defn.target and spec.target_doc_key is not None:
            target = self._guard_target(company, defn, spec, doc, row, link_qty)
        merge = self._merge_target(company, defn, doc, row) if mode == "delete" else None
        merge_qty = None
        if merge is not None:  # the free row's quantity now: a pending merge is judged against it
            merge_qty = str(_dec(next(r for r in doc.get("Details") or [] if r.get("DtlKey") == merge).get("Qty")))
        return {"mode": mode, "received": received, "target": target, "linkQty": link_qty, "merge": merge,
                "mergeQty": merge_qty}

    def _merge_target(self, company: AcCompany, defn: _OpDef, doc: Doc, row: Doc) -> Optional[int]:
        """Plan 62 D7: the DtlKey of the FIRST free row (row order) the unlinked quantity can join:
        same item, unit, location, price and delivery date, not linked, no SPO row pointing at it,
        no known receipt above zero. An UNKNOWN receipt (the vendor hides it) allows the merge, like the
        linked row's own receipt check. None = no merge (today's new free row)."""
        if defn.kind != "PO" or defn.mode != "unlink":
            return None
        for cand in doc.get("Details") or []:
            if cand.get("DtlKey") == row.get("DtlKey") or _link_of("PO", cand):
                continue
            if cand.get("FromDocType") not in ("", None):
                continue
            if any(cand.get(k) != row.get(k) for k in ("ItemCode", "UOM", "Location")):
                continue
            if not all(payloads.same_row_value(k, row.get(k), cand.get(k)) for k in ("UnitPrice", "DeliveryDate")):
                continue
            if self._spo_ref(company, int(cand["DtlKey"])):
                continue
            if self.prims.row_needs_attention(company, int(doc.get("DocKey") or 0), cand,
                                              exclude_id=self._row.id if self._row else None):
                continue  # plan 65 R1: growing a row an unresolved link covers breaks its Resume
            if self._receipt_reader is not None:
                received = self._receipt_reader("PO", doc, cand)
            else:
                received = self.prims._row_received(company, "PO", dict(cand, DocKey=doc.get("DocKey")))
            if received is not None and received > 0:  # unknown (the vendor hides it) joins the rule of _receipt
                continue
            return int(cand["DtlKey"])
        return None

    def _receipt(self, company: AcCompany, defn: _OpDef, doc: Doc, row: Doc) -> Tuple[str, Optional[Decimal]]:
        """``("delete" | "partial", received)``; an unknown received qty goes the
        delete way with a warning (owner ruling: the refusal comes from AutoCount)."""
        if self._receipt_reader is not None:
            received = self._receipt_reader(defn.kind, doc, row)
        else:
            received = self.prims._row_received(company, defn.kind, dict(row, DocKey=doc.get("DocKey")))
        if received is None:
            self._warnings.append(TRANSFER_STATE_UNKNOWN)
            return "delete", None
        if received <= 0:
            return "delete", received
        if received >= _dec(row.get("Qty")) or not capabilities.PARTIAL_RECEIPT_SPLIT:
            raise _Done(REFUSED, ROW_RECEIVED, received_message(defn.kind, row))
        return "partial", received

    def _guard_target(self, company: AcCompany, defn: _OpDef, spec: _Spec, doc: Doc,
                      row: Doc, link_qty: Decimal) -> Doc:
        assert defn.target and spec.target_doc_key is not None
        _date, tdoc = self._read(company, defn.target, spec.target_doc_key, spec.target_doc_date)
        if tdoc.get("Cancelled") == "T":
            raise _Done(REFUSED, "DOC_CANCELLED")
        trow = next((r for r in tdoc.get("Details") or [] if r.get("DtlKey") == spec.target_dtl_key), None)
        if trow is None:
            raise _Done(REFUSED, "ROW_NOT_FOUND")
        if row.get("ItemCode") != trow.get("ItemCode"):
            raise _Done(REFUSED, "ITEM_MISMATCH")
        if row.get("UOM") != trow.get("UOM"):
            raise _Done(REFUSED, "UOM_MISMATCH")
        if defn.target == "SO":
            used = self.prims._so_linked_qty(company, int(spec.target_dtl_key or 0), fresh_po=doc)
        else:
            used = self._spo_linked_qty(company, doc, int(spec.target_dtl_key or 0), spec.dtl_key)
        if link_qty > payloads.so_outstanding(trow, used):
            raise _Done(REFUSED, "QTY_ABOVE_OUTSTANDING")
        return tdoc

    def _spo_ref(self, company: AcCompany, po_dtl_key: int) -> Optional[str]:
        """DocNo of a staged, non-cancelled SPO with a row pointing at the PO row."""
        return self.prims._spo_ref(company.tenant_id, company.id, po_dtl_key)

    def _spo_linked_qty(self, company: AcCompany, fresh_spo: Doc, po_dtl_key: int, own_dtl: int) -> Decimal:
        """Qty of one PO row already taken by SPO rows: the fresh SPO (minus the row
        being moved) plus every other staged, non-cancelled SPO."""
        own_ref = f"{company.database_name}:{fresh_spo.get('DocKey')}"
        own = sum(
            (_dec(r.get("Qty")) for r in fresh_spo.get("Details") or []
             if r.get("DtlKey") != own_dtl and r.get("FromDocDtlKey") == po_dtl_key),
            Decimal(0),
        )
        # C.d: every OTHER SPO from the indexed newest copies (one query), never a load of every staged SPO
        return own + SpoPoLinkRepository(self.db).linked_qty(
            company.tenant_id, company.id, po_dtl_key, except_ref=own_ref)

    # ── snapshot ─────────────────────────────────────────────────────────────

    def _snapshot(self, company: AcCompany, defn: _OpDef, spec: _Spec, doc: Doc, doc_date: date,
                  plan: Dict[str, Any]) -> Doc:
        row = next(r for r in doc.get("Details") or [] if r.get("DtlKey") == spec.dtl_key)
        target = plan["target"]
        new_link = dict(_NO_LINK)
        if target is not None:
            new_link = {"FromDocType": defn.target, "FromDocNo": target.get("DocNo"),
                        "FromDocDtlKey": spec.target_dtl_key}
        move_to = row.get("Location")  # unlink / SPO: the line stays where it was
        so_link: Optional[Doc] = None
        if target is not None and defn.target == "SO":
            trow = next((r for r in target.get("Details") or [] if r.get("DtlKey") == spec.target_dtl_key), {})
            move_to = trow.get("Location") or move_to  # owner ruling: a linked PO row sits at its SO row
            so_link = self._so_link_values(target, trow)
        return _json_safe({
            "soLink": so_link,
            "moveTo": move_to, "kind": defn.kind, "mode": plan["mode"], "docKey": spec.doc_key, "docNo": doc.get("DocNo"),
            "docDate": doc_date.isoformat(), "lastModified": doc.get("LastModified"),
            "knownKeys": [r.get("DtlKey") for r in doc.get("Details") or []],
            "row": row, "received": None if plan["received"] is None else str(plan["received"]),
            "newLink": new_link, "oldLink": self._old_link(company, defn, row), "mergeInto": plan.get("merge"), "mergeBeforeQty": plan.get("mergeQty"),
            "location": row.get("Location"), "companyName": company.company_name or company.name,
        })

    @staticmethod
    def _so_link_values(so: Doc, so_row: Doc) -> Doc:
        """Plan 65 D2 / D4: what the restore of a row newly linked to ``so_row`` needs from the SO, kept
        in the snapshot at link time so Resume needs no guess: the SO row's day and the note text."""
        return payloads.so_link_values(so, so_row)

    def _old_link(self, company: AcCompany, defn: _OpDef, row: Doc) -> Doc:
        """The link fields the row has now, to restore it (a PO row linked to an SO
        row may read back without ``FromDocNo``: found on the staged SO)."""
        key = _link_of(defn.kind, row)
        if not key:
            return dict(_NO_LINK)
        if defn.kind == "SPO":
            return {"FromDocType": "PO", "FromDocNo": row.get("FromDocNo") or "", "FromDocDtlKey": key}
        number = row.get("FromDocNo") or ""
        if not number:
            for staged in self.prims.staged.for_entity(company.tenant_id, company.id, ENTITY_SALES_ORDER):
                if any(r.get("DtlKey") == key for r in _lines(staged.raw_json)):
                    number = str((staged.raw_json or {}).get("DocNo") or staged.doc_no or "")
                    break
        return {"FromDocType": "SO", "FromDocNo": number, "FromDocDtlKey": key}

    # ── steps (AC-57-30, 31, 33, 34, 35, 39) ─────────────────────────────────

    def _line_of(self, snap: Doc, link: Doc, qty: Optional[Decimal] = None) -> Doc:
        line = {k: v for k, v in snap["row"].items() if k != "DtlKey"}
        line.update(link)
        if qty is not None:
            line["Qty"] = float(qty)
        return line

    def _call(self, row: AcWriteOperation, company: AcCompany, snap: Doc, name: str) -> Dict[str, Any]:
        return dict(
            tenant_id=company.tenant_id, company_id=company.id, kind=snap["kind"], doc_key=snap["docKey"],
            doc_date=date.fromisoformat(snap["docDate"]), key_id=row.key_id, operation_id=row.id,
            step=name, stage=False,
        )

    def _steps_run(self, row: AcWriteOperation, company: AcCompany, op: str, defn: _OpDef, spec: _Spec,
                   snap: Doc) -> OperationResult:
        old_key = int(snap["row"]["DtlKey"])
        qty = _dec(snap["row"].get("Qty"))
        received = None if snap["received"] is None else Decimal(snap["received"])
        # The deadline may stop an operation only HERE, before its first write. After the
        # replace / cut has landed every further step runs (the heartbeat guards the lock).
        self._check_deadline()
        if snap.get("mergeInto"):
            return self._merge_run(row, company, snap, old_key, int(snap["mergeInto"]))
        if not snap["mode"] == "partial":
            return self._replace_run(row, company, snap, old_key)
        assert received is not None
        cut = self.prims.edit_doc(
            **self._call(row, company, snap, "cut"), header_changes={},
            line_changes=[{"DtlKey": old_key, "Qty": received}],
        )
        self._step("cut", cut)
        self._abort_unless_done(cut)
        add = self.prims.add_line(
            **self._call(row, company, snap, "add"), line=self._line_of(snap, snap["newLink"], qty - received),
        )
        self._step("add", add)
        if add.outcome == OUTCOME_PENDING:
            raise _Done(PENDING, add.error_code)
        if add.outcome != OUTCOME_DONE or add.new_dtl_key is None:
            return self._recover(row, company, snap, add.error_code or INTERNAL_ERROR, True)
        new_key = int(add.new_dtl_key)
        document, landed = self._link_move(row, company, snap, new_key, add.document, snap.get("soLink"))
        self.prims._stage(company, snap["kind"], document, None)
        if not landed:
            return self._needs_attention(row, company, snap, RESTORE_NOT_LANDED, document=document)
        return self._finish(row, DONE, None, replaced=[], document=document, detail=_row_in(document, new_key))

    def _merge_run(self, row: AcWriteOperation, company: AcCompany, snap: Doc, old_key: int,
                   free_key: int) -> OperationResult:
        """Plan 62 D7: ONE PUT [linked row "D", free row raised]. All or nothing: a refusal changed
        nothing; no move step (no new row, so nothing was reset)."""
        res = self.prims.unlink_merge(**self._call(row, company, snap, "merge"), dtl_key=old_key, merge_key=free_key)
        self._step("merge", res)
        if res.outcome == OUTCOME_VENDOR_ERROR:
            if res.error_code == VENDOR_REFUSED:  # AutoCount said no: nothing landed
                raise _Done(VENDOR_ERROR, res.error_code, res.message)
            raise _Done(PENDING, res.error_code, res.message)  # a bare 5xx or timeout: resume reads
        if res.outcome == OUTCOME_MISMATCH:  # the PUT landed but reads back wrong
            raise _Done(NEEDS_ATTENTION, res.error_code or INTERNAL_ERROR, res.message)
        if res.outcome != OUTCOME_DONE or res.document is None:
            self._abort_unless_done(res)
            raise _Done(PENDING, res.error_code or INTERNAL_ERROR)
        self.prims._stage(company, snap["kind"], res.document, None)
        return self._finish(row, DONE, None, replaced=[(old_key, free_key)], document=res.document)

    def _replace_run(self, row: AcWriteOperation, company: AcCompany, snap: Doc, old_key: int) -> OperationResult:
        """Plan 61: ONE PUT [row "D", new row with the new link or none], then the move.
        AutoCount applies the PUT all or nothing (F8): a refusal changed nothing."""
        res = self.prims.replace_line(
            **self._call(row, company, snap, "replace"), dtl_key=old_key, line=self._line_of(snap, snap["newLink"]),
        )
        self._step("replace", res)
        if res.outcome == OUTCOME_VENDOR_ERROR:
            if res.error_code == VENDOR_REFUSED:  # AutoCount said no: nothing landed
                raise _Done(VENDOR_ERROR, res.error_code, res.message)
            # a timeout or a bare 5xx: the replace may have landed; resume reads AutoCount (AC-57-42)
            raise _Done(PENDING, res.error_code, res.message)
        if res.outcome == OUTCOME_MISMATCH:  # the PUT landed but reads back wrong
            return self._recover(row, company, snap, res.error_code or INTERNAL_ERROR, False)
        if res.outcome != OUTCOME_DONE or res.new_dtl_key is None:
            self._abort_unless_done(res)
            raise _Done(PENDING, res.error_code or INTERNAL_ERROR)
        new_key = int(res.new_dtl_key)
        document, landed = self._link_move(row, company, snap, new_key, res.document, snap.get("soLink"))
        self.prims._stage(company, snap["kind"], document, {new_key: old_key})
        if not landed:
            return self._needs_attention(row, company, snap, RESTORE_NOT_LANDED, replaced=[(old_key, new_key)],
                                         document=document)
        return self._finish(row, DONE, None, replaced=[(old_key, new_key)], document=document,
                            detail=_row_in(document, new_key))

    def _abort_unless_done(self, res: PrimitiveResult) -> None:
        """A first step that did not land cleanly: nothing to recover."""
        if res.outcome == OUTCOME_DONE:
            return
        if res.outcome == OUTCOME_REFUSED:
            raise _Done(REFUSED, res.error_code, res.message)
        if res.outcome == OUTCOME_VENDOR_ERROR:
            if res.error_code == VENDOR_REFUSED:  # AutoCount said no: nothing landed
                raise _Done(VENDOR_ERROR, res.error_code, res.message)
            raise _Done(PENDING, res.error_code, res.message)  # a bare 5xx may have landed: resume reads
        raise _Done(PENDING, res.error_code, res.message)  # mismatch / pending: resume decides

    def _move(self, row: AcWriteOperation, company: AcCompany, snap: Doc, new_key: int,
              document: Optional[Doc], location: Optional[str], *, deadline: bool = True) -> Doc:
        """Put the new row back where and as the old row was when the read-back differs:
        ``location`` and the old row's unit price and delivery date (AutoCount resets all
        three on a new SO-linked row, F5; the split link's rule, ``payloads.transfer_restore``).
        A row newly linked to an SO row goes through ``_link_move`` instead (plan 65 D2, R2).
        One edit PUT, never retried; a failed move is a warning, never a failure (the link
        stays): ``LOCATION_NOT_MOVED``, plus ``ROW_VALUES_NOT_KEPT`` when price / date did
        not go back."""
        return self._move_rows(row, company, snap, [(new_key, location, None)], document, deadline=deadline)

    def _link_move(self, row: AcWriteOperation, company: AcCompany, snap: Doc, new_key: int,
                   document: Optional[Doc], so_link: Optional[Doc], *, deadline: bool = True) -> Tuple[Doc, bool]:
        """The move of a row op's new row, ``(document, landed)``. A row newly linked to an SO row
        (``so_link``) is restored by the batch's rule and a restore that did not land is not landed (plan 65
        R2: the op is resumable, never done with warnings); any other new row keeps ``_move``'s warnings."""
        location = snap.get("moveTo") or snap["location"]
        if so_link is None:
            return self._move(row, company, snap, new_key, document, location, deadline=deadline), True
        document, failed = self._restore_rows(row, company, snap, [(new_key, location, so_link)], document,
                                              deadline=deadline)
        return document, not failed

    def _move_rows(self, row: AcWriteOperation, company: AcCompany, snap: Doc,
                   moves: List[Tuple[int, Optional[str], Optional[Doc]]], document: Optional[Doc], *,
                   deadline: bool = True) -> Doc:
        """``_move`` for N new rows (plan 62 D4): every row whose read-back drifted goes back in
        ONE edit PUT; a failed PUT is the same warnings, never a failure."""
        document, failed = self._restore_rows(row, company, snap, moves, document, deadline=deadline)
        if failed:
            self._move_warnings({k: None for k in failed})
        return document

    def _restore_rows(self, row: AcWriteOperation, company: AcCompany, snap: Doc,
                      moves: List[Tuple[int, Optional[str], Optional[Doc]]], document: Optional[Doc], *,
                      deadline: bool = True) -> Tuple[Doc, Optional[set]]:
        """The restore PUT of ``_move_rows``: ``(document, None)`` when it landed (or nothing drifted),
        else ``(the last read, the fields that did not go back)``. Each move is ``(new row, location,
        so_link)``; the values are ``payloads.transfer_restore`` (one rule)."""
        document = document or {}
        changes_by_key: Dict[int, Dict[str, Any]] = {}
        for new_key, location, so_link in moves:
            landed = next((r for r in document.get("Details") or [] if r.get("DtlKey") == new_key), {})
            changes = payloads.transfer_row_drift(payloads.transfer_restore(snap["row"], location, so_link), landed)
            if changes:
                changes_by_key[new_key] = changes
        if not changes_by_key:
            return document, None
        fields = {k for changes in changes_by_key.values() for k in changes}
        if deadline and time.monotonic() > self._op_deadline:  # move due, deadline past: skip it
            return document, fields
        # ``document`` is the last read of this document (the step's read-back or resume's read), with
        # no vendor call since: the move is built on it, not on a second identical GET (SS-AUTOCOUNT-SPEEDUP).
        moved = self.prims.edit_doc(
            **self._call(row, company, snap, "move"), header_changes={},
            line_changes=[{"DtlKey": key, **changes} for key, changes in changes_by_key.items()],
            fresh_doc=document, restore=True,
        )
        self._step("move", moved)
        if moved.outcome == OUTCOME_DONE and moved.document:
            return moved.document, None
        return document, fields

    def _move_warnings(self, changes: Dict[str, Any]) -> None:
        codes = [LOCATION_NOT_MOVED] + ([ROW_VALUES_NOT_KEPT] if set(changes) - {"Location"} else [])
        self._warnings.extend(c for c in codes if c not in self._warnings)

    def _recover(self, row: AcWriteOperation, company: AcCompany, snap: Doc, failed_code: str,
                 partial: bool) -> OperationResult:
        """The add failed after step 1 landed: put the line back as it was."""
        old_key = int(snap["row"]["DtlKey"])
        if partial:
            remainder = _dec(snap["row"].get("Qty")) - Decimal(snap["received"])
            if self._remove_strays(row, company, snap, remainder) is None:
                return self._needs_attention(row, company, snap, failed_code)
            back = self.prims.edit_doc(
                **self._call(row, company, snap, "recover"), header_changes={},
                line_changes=[{"DtlKey": old_key, "Qty": _dec(snap["row"].get("Qty"))}],
            )
            self._step("recover", back)
            if back.outcome == OUTCOME_DONE:
                self.prims._stage(company, snap["kind"], back.document or {})
                return self._finish(row, RECOVERED, failed_code, document=back.document)
        else:
            doc = self._remove_strays(row, company, snap)
            if doc is None:
                return self._needs_attention(row, company, snap, failed_code)
            if any(r.get("DtlKey") == old_key for r in doc.get("Details") or []):
                # the "D" never landed: the line is as it was once the strays are gone
                self.prims._stage(company, snap["kind"], doc)
                return self._finish(row, RECOVERED, failed_code, document=doc)
            res = self.prims.add_line(
                **self._call(row, company, snap, "recover"), line=self._line_of(snap, snap["oldLink"])
            )
            self._step("recover", res)
            if res.outcome == OUTCOME_PENDING:
                raise _Done(PENDING, res.error_code)
            if res.outcome == OUTCOME_DONE and res.new_dtl_key is not None:
                new_key = int(res.new_dtl_key)
                document = self._move(row, company, snap, new_key, res.document, snap["location"], deadline=False)
                self.prims._stage(company, snap["kind"], document, {new_key: old_key})
                return self._finish(row, RECOVERED, failed_code, replaced=[(old_key, new_key)], document=document)
        return self._needs_attention(row, company, snap, failed_code)

    def _remove_strays(
        self, row: AcWriteOperation, company: AcCompany, snap: Doc, qty: Optional[Decimal] = None
    ) -> Optional[Doc]:
        """AC-57-41: a replace or add that read back wrong may still have left a copy
        (link lost). Delete any new row that looks like the line before the original
        is re-added, so recovery never doubles the quantity. Returns the document as
        read (strays then gone); None when AutoCount cannot be read or a stray cannot be
        removed (needs_attention). A partial operation looks for the remainder (``qty``)."""
        doc = self._read_snapshot_doc(company, snap)
        if doc is None:
            return None
        known, base = set(snap["knownKeys"]), snap["row"]
        strays = [
            r for r in doc.get("Details") or []
            if r.get("DtlKey") not in known and r.get("ItemCode") == base.get("ItemCode")
            and r.get("UOM") == base.get("UOM")
            and _dec(r.get("Qty")) == (qty if qty is not None else _dec(base.get("Qty")))
        ]
        for stray in strays:
            gone = self.prims.delete_line(**self._call(row, company, snap, "unstray"), dtl_key=int(stray["DtlKey"]))
            self._step("unstray", gone)
            if gone.outcome != OUTCOME_DONE:
                return None
            doc = gone.document or doc
        return doc

    def _read_snapshot_doc(self, company: AcCompany, snap: Doc) -> Optional[Doc]:
        """The snapshot's document as AutoCount holds it now (bydocno, day list as the
        fallback), or None when it cannot be read."""
        reader = self._reader(company, self._base_url, snap["kind"], int(snap["docKey"]), snap.get("docNo"))
        self.db.commit()
        try:
            return reader.get_document(snap["kind"], int(snap["docKey"]), date.fromisoformat(snap["docDate"]),
                                       doc_no=snap.get("docNo"))
        except DocReadError:
            return None

    def _needs_attention(self, row: AcWriteOperation, company: AcCompany, snap: Doc, code: str,
                         notify: bool = True, *, batch: Optional[Dict[str, Any]] = None,
                         replaced: Optional[List[Tuple[int, int]]] = None,
                         document: Optional[Doc] = None) -> OperationResult:
        result = self._finish(row, NEEDS_ATTENTION, code, batch=batch, replaced=replaced, document=document)
        if notify and self._mail_allowed:
            self._notify(company, row, snap)
        return result

    # ── resume (AC-57-36) ────────────────────────────────────────────────────

    def _resume(self, row: AcWriteOperation, company: AcCompany, was: str) -> OperationResult:
        snap = row.snapshot_json or {}
        base_url, refusal = self.prims._resolve_write_base_url(company)
        if base_url is None:
            if refusal:
                self.prims._log_refused_connection(company, refusal[0], doc_key=int(snap.get("docKey") or 0) or None)
            raise _Done(was, refusal[0] if refusal else WRITE_DISABLED)
        self._base_url = base_url
        self._check_test_company(company, restore=was)
        kind, doc_date = snap["kind"], date.fromisoformat(snap["docDate"])
        reader = self._reader(company, base_url, kind, int(snap["docKey"]), snap.get("docNo"))
        self.db.commit()
        try:
            doc = reader.get_document(kind, int(snap["docKey"]), doc_date, doc_no=snap.get("docNo"))
        except DocReadError as exc:
            raise _Done(was, exc.code) from None
        if snap.get("mode") == "batch":
            return self._resume_batch(row, company, snap, doc)
        rows = doc.get("Details") or []
        old_key = int(snap["row"]["DtlKey"])
        original = next((r for r in rows if r.get("DtlKey") == old_key), None)
        if snap.get("mergeInto"):
            return self._resume_merge(row, company, snap, doc, original, old_key)
        partial = snap["mode"] == "partial"
        if original is not None and not partial:
            # the replace never landed: the line is as it was (no write)
            return self._finish(row, RECOVERED, NOT_APPLIED, document=doc)
        known = set(snap["knownKeys"])
        fresh = [r for r in rows if r.get("DtlKey") not in known]
        base = snap["row"]
        qty = _dec(base.get("Qty"))
        want_qty = qty - Decimal(snap["received"]) if partial else qty

        def matching(link: Doc, wanted: Decimal) -> Optional[Doc]:
            return next((r for r in fresh if r.get("ItemCode") == base.get("ItemCode")
                         and r.get("UOM") == base.get("UOM") and _dec(r.get("Qty")) == wanted
                         and _link_of(kind, r) == int(link.get("FromDocDtlKey") or 0)), None)

        intended = matching(snap["newLink"], want_qty)
        if intended is not None:
            new_key = int(intended["DtlKey"])
            replaced = [] if partial else [(old_key, new_key)]
            so_link = self._row_so_link(row, company, snap)
            if so_link is False:  # an older snapshot whose SO cannot be read: no PUT
                return self._needs_attention(row, company, snap, RESTORE_NOT_LANDED, replaced=replaced, document=doc)
            document, landed = self._link_move(row, company, snap, new_key, doc, so_link or None, deadline=False)
            self.prims._stage(company, snap["kind"], document, None if partial else {new_key: old_key})
            if not landed:
                return self._needs_attention(row, company, snap, RESTORE_NOT_LANDED, replaced=replaced,
                                             document=document)
            return self._finish(row, DONE, None, replaced=replaced, document=document,
                                detail=_row_in(document, new_key))
        if partial:
            if _dec(original.get("Qty")) == qty if original else True:
                return self._finish(row, REFUSED, NOT_APPLIED, document=doc)
            return self._recover(row, company, snap, "RESUMED", True)
        old = matching(snap["oldLink"], qty)
        if old is not None:
            document = self._resume_move(row, company, snap, int(old["DtlKey"]), doc, snap["location"])
            self.prims._stage(company, snap["kind"], document, {int(old["DtlKey"]): old_key})
            return self._finish(row, RECOVERED, None, replaced=[(old_key, int(old["DtlKey"]))], document=document)
        res = self._recover(row, company, snap, "RESUMED", False)
        if res.outcome == NEEDS_ATTENTION and was == NEEDS_ATTENTION:
            return res
        return res

    def _resume_merge(self, row: AcWriteOperation, company: AcCompany, snap: Doc, doc: Doc,
                      original: Optional[Doc], old_key: int) -> OperationResult:
        """A pending merge. The linked row still there: it never landed. Gone and the free row holds
        exactly its quantity before plus the freed quantity: it landed. Anything else (the row deleted by
        hand, the free row changed since) needs a person; no PUT is sent."""
        if original is not None:
            return self._finish(row, RECOVERED, NOT_APPLIED, document=doc)
        free_key = int(snap["mergeInto"])
        free = next((r for r in doc.get("Details") or [] if r.get("DtlKey") == free_key), None)
        before = snap.get("mergeBeforeQty")
        landed = (free is not None and before is not None
                  and _dec(free.get("Qty")) == _dec(before) + _dec(snap["row"].get("Qty")))
        if not landed:
            return self._needs_attention(row, company, snap, "RESUMED")
        self.prims._stage(company, snap["kind"], doc, None)
        return self._finish(row, DONE, None, replaced=[(old_key, free_key)], document=doc)

    def _resume_move(self, row: AcWriteOperation, company: AcCompany, snap: Doc, key: int, doc: Doc,
                     location: Optional[str]) -> Doc:
        return self._move(row, company, snap, key, doc, location, deadline=False)

    def _row_so_link(self, row: AcWriteOperation, company: AcCompany, snap: Doc) -> "Union[Doc, None, bool]":
        """The SO values a row op's restore needs (plan 65 R3): the snapshot's, or for a snapshot stored
        before plan 65 the SO re-read through the logged reader (``_so_reread``, the batch's helper) and kept
        in the snapshot. None = the new row is not linked to an SO row; False = the SO could not be read."""
        if "soLink" in snap:
            return snap["soLink"]
        link = snap.get("newLink") or {}
        if link.get("FromDocType") != "SO":
            return None
        values = self._so_reread(company, link.get("FromDocNo"), None, int(link.get("FromDocDtlKey") or 0), {})
        if values is None:
            return False
        row.snapshot_json = _json_safe(dict(snap, soLink=values))
        self.db.commit()
        return values

    # ── link batch (plan 62 D1-D5): one PO row to N SO rows in ONE PUT ───────

    def _batch_params(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The batch's links, checked before anything is read: 1..20, no repeated SO row. A quantity that is
        not valid does not refuse the batch: that line is skipped (``QTY_INVALID``)."""
        raw = params["links"]
        if not 1 <= len(raw) <= MAX_BATCH_LINKS:
            raise _Done(REFUSED, INVALID_PARAMS, f"links must hold 1 to {MAX_BATCH_LINKS} entries")
        links: List[Dict[str, Any]] = []
        seen: set = set()
        for item in raw:
            try:
                so_doc, so_dtl = int(item["so_doc_key"]), int(item["so_dtl_key"])
                qty = Decimal(str(item["qty"]))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                raise _Done(REFUSED, INVALID_PARAMS) from None
            if so_dtl in seen:
                raise _Done(REFUSED, INVALID_PARAMS, f"SO row {so_dtl} is listed twice")
            seen.add(so_dtl)
            skip = None
            try:
                qty = payloads.validate_qty(qty)
            except WriteRefusal:
                skip = "QTY_INVALID"
            links.append({"so_doc_key": so_doc, "so_dtl_key": so_dtl, "qty": qty,
                          "so_doc_date": item.get("so_doc_date"), "skip": skip})
        return links

    def _batch_link(self, row: AcWriteOperation, company: AcCompany, spec: _Spec,
                    params: Dict[str, Any]) -> OperationResult:
        links = self._batch_params(params)
        # The guard and PUT 1 run under a per-SO-row lock (link_lock); the restore PUT runs after it is
        # released. All requested SO rows are locked, in sorted order (no deadlock): which lines are valid is
        # only known after reading, and a lock taken before the reads is the one that covers the guard.
        try:
            with so_row_locks(self.db, company.id, [link["so_dtl_key"] for link in links]):
                outcome = self._batch_locked(row, company, spec, links)
        except SoRowBusy:
            raise _Done(REFUSED, DOC_BUSY) from None
        if isinstance(outcome, OperationResult):
            return outcome
        snapshot, document = outcome
        return self._batch_done(row, company, snapshot, document)

    def _batch_locked(self, row: AcWriteOperation, company: AcCompany, spec: _Spec,
                      links: List[Dict[str, Any]]) -> "Union[OperationResult, Tuple[Doc, Doc]]":
        defn = OPS["link_row"]  # D9: the batch rides the link switch and the delete / add / edit primitives
        if not op_capable(defn):
            raise _Done(REFUSED, VENDOR_UNSUPPORTED)
        self._check_not_busy(company, spec.doc_key, "PO")
        doc_date, doc = self._read(company, "PO", spec.doc_key, spec.doc_date)
        if spec.expected_last_modified and doc.get("LastModified") != spec.expected_last_modified:
            raise _Done(REFUSED, DOC_STALE)
        try:
            old = payloads.check_row("PO", doc, spec.dtl_key)  # kind, cancelled, row exists
            payloads._refuse_other_transfer(old)
        except WriteRefusal as exc:
            raise _Done(REFUSED, exc.code, str(exc)) from None
        if self._spo_ref(company, spec.dtl_key):
            raise _Done(REFUSED, "ROW_ON_SPO")
        if _link_of("PO", old):
            raise _Done(REFUSED, "ROW_ALREADY_LINKED")
        mode, _received = self._receipt(company, defn, doc, old)
        if mode == "partial":
            raise _Done(REFUSED, ROW_RECEIVED, received_message("PO", old))
        # the PO row's qty that pending link operations on it may already have taken (outcome unknown) is not free
        free = _dec(old.get("Qty")) - self._po_row_pending_qty(company, spec, doc)
        # Owner rule (plan 62, 12 Nov): a bad line never fails the batch. Each line is checked on its own,
        # in request order; a failing line is skipped and named, the rest are linked.
        sources: Dict[int, Doc] = {}
        lines: List[Doc] = []
        applied: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        running = Decimal(0)
        for link in links:
            code = link["skip"] or self._line_skip(company, doc, old, link, sources, free, running)
            if code:
                skipped.append({"soDocKey": link["so_doc_key"], "soDtlKey": link["so_dtl_key"], "code": code})
                continue
            running += link["qty"]
            applied.append(link)
            lines.append(dict(
                {k: v for k, v in old.items() if k != "DtlKey"},
                FromDocType="SO", FromDocNo=link["so_no"], FromDocDtlKey=link["so_dtl_key"],
                Location=link["location"], Qty=float(link["qty"]), FOCQty=0,
                Discount=payloads.link_discount(old.get("Discount")),  # D2a: an amount stays on the kept row
            ))
        if not applied:  # nothing to link: refused, nothing sent, the key is released
            return self._finish(row, REFUSED, ALL_LINKS_SKIPPED, message="every link was skipped",
                                batch={"links": [], "skipped": skipped, "freeLine": None})
        snapshot = _json_safe({
            "kind": "PO", "mode": "batch", "docKey": spec.doc_key, "docNo": doc.get("DocNo"),
            "docDate": doc_date.isoformat(), "lastModified": doc.get("LastModified"),
            "knownKeys": [r.get("DtlKey") for r in doc.get("Details") or []], "row": old,
            "received": None, "location": old.get("Location"), "companyName": company.company_name or company.name,
            "links": [{"soDocKey": link["so_doc_key"], "soDtlKey": link["so_dtl_key"], "qty": str(link["qty"]),
                       "soNo": link["so_no"], "location": link["location"],
                       "soDeliveryDate": link["so_link"]["soDeliveryDate"], "note": link["so_link"]["note"]}
                      for link in applied],
            "skipped": skipped,
        })
        row.snapshot_json = snapshot
        self.db.commit()
        self._log_remark_overwrite(doc)
        none_linked = {"links": [], "skipped": skipped, "freeLine": None}
        try:
            self._check_deadline()
            res = self.prims.batch_link(
                **self._call(row, company, snapshot, "link"), dtl_key=spec.dtl_key, lines=lines,
            )
            self._step("link", res)
            if res.outcome == OUTCOME_VENDOR_ERROR:
                if res.error_code == VENDOR_REFUSED:  # AutoCount said no (all or nothing): nothing landed
                    raise _Done(VENDOR_ERROR, res.error_code, res.message)
                raise _Done(PENDING, res.error_code, res.message)  # a bare 5xx or timeout: resume reads
            if res.outcome == OUTCOME_MISMATCH:  # the PUT landed but reads back wrong
                raise _Done(NEEDS_ATTENTION, res.error_code or INTERNAL_ERROR, res.message)
            if res.outcome != OUTCOME_DONE or res.document is None:
                self._abort_unless_done(res)
                raise _Done(PENDING, res.error_code or INTERNAL_ERROR)
        except _Done as done:
            if done.batch is None:
                done.batch = none_linked  # the skipped lines are part of every answer
            raise
        refresh_po_links_from_doc(self.db, company.tenant_id, company.id,
                                  f"{company.database_name}:{spec.doc_key}", res.document)
        self.db.commit()  # the next guard sees these links before the lock is released
        return snapshot, res.document

    def _po_row_pending_qty(self, company: AcCompany, spec: _Spec, doc: Doc) -> Decimal:
        """Qty of the PO row that unresolved link operations on it (``pending_verification`` or
        ``needs_attention``: they may have landed) would cover and that the fresh read does not show yet (a
        landed link is already in the fresh rows: never counted twice, and one fresh row answers for one link
        only). A whole-row link that has not landed covers the whole row (less any received qty)."""
        total = Decimal(0)
        rows = doc.get("Details") or []
        pool = list(rows)
        for op in self.ops.pending_po_row_links(company.tenant_id, company.id, spec.doc_key, spec.dtl_key,
                                                exclude_id=self._row.id if self._row else None):
            snap = op.snapshot_json if isinstance(op.snapshot_json, dict) else {}
            if snap.get("mode") in ("batch", "split"):  # a part-row link_row runs as a split: its snapshot says
                known = set(snap.get("knownKeys") or [])
                for link in snap.get("links") or []:
                    want, qty = int(link.get("soDtlKey") or 0), _dec(link.get("qty"))
                    match = next((r for r in pool if r.get("DtlKey") not in known and _link_of("PO", r) == want
                                  and _dec(r.get("Qty")) == qty), None)
                    if match is None:
                        total += qty
                    else:
                        pool.remove(match)
                continue
            if op.status != PENDING or not any(r.get("DtlKey") == op.dtl_key for r in rows):
                # the row was replaced (the whole-row link landed), or a person is resolving an operation whose
                # row still stands (its replace never landed): nothing of the row is reserved
                continue
            qty = _dec((snap.get("row") or {}).get("Qty"))
            if snap.get("received") is not None:
                qty -= _dec(snap["received"])
            total += qty
        return total

    def _line_skip(self, company: AcCompany, doc: Doc, old: Doc, link: Dict[str, Any], sources: Dict[int, Doc],
                   free: Decimal, running: Decimal) -> Optional[str]:
        """The reason one line cannot be linked (None = it can); fills ``so_no`` and ``location``."""
        so = sources.get(link["so_doc_key"])
        if so is None:
            try:
                _d, so = self._read(company, "SO", link["so_doc_key"], _as_date(link["so_doc_date"]))
            except _Done as done:
                if done.status != REFUSED:
                    raise
                return done.code or "ROW_NOT_FOUND"
            sources[link["so_doc_key"]] = so
        if so.get("Cancelled") == "T":
            return "DOC_CANCELLED"
        so_row = next((r for r in so.get("Details") or [] if r.get("DtlKey") == link["so_dtl_key"]), None)
        if so_row is None:
            return "ROW_NOT_FOUND"
        if old.get("ItemCode") != so_row.get("ItemCode"):
            return "ITEM_MISMATCH"
        if old.get("UOM") != so_row.get("UOM"):
            return "UOM_MISMATCH"
        used = self.prims._so_linked_qty(company, link["so_dtl_key"], fresh_po=doc)
        if link["qty"] > payloads.so_outstanding(so_row, used):
            return "QTY_ABOVE_OUTSTANDING"
        if running + link["qty"] > free:
            return "QTY_ABOVE_FREE"
        if payloads.foc_on_row(old, running + link["qty"]):
            return FOC_ON_ROW  # the row would go with its FOC, which hapi cannot put on a new row (D2a)
        link["so_no"], link["location"] = so.get("DocNo"), so_row.get("Location")
        link["so_link"] = self._so_link_values(so, so_row)
        return None

    def _batch_done(self, row: AcWriteOperation, company: AcCompany, snap: Doc, document: Doc,
                    *, deadline: bool = True) -> OperationResult:
        """PUT 1 landed (or was found landed): match each link to its new row, run the ONE restore
        PUT when a read-back drifted, stage, answer with the new DtlKeys (plan 62 D4, D5). A restore
        that did not land (vendor error, read-back mismatch, deadline) leaves the operation
        ``needs_attention`` / ``RESTORE_NOT_LANDED`` with the landed links in its answer; Resume
        re-runs only the restore (plan 65 D3)."""
        known = set(snap["knownKeys"])
        fresh = [r for r in document.get("Details") or [] if r.get("DtlKey") not in known]
        answer: List[Dict[str, Any]] = []
        moves: List[Tuple[int, Optional[str], Optional[Doc]]] = []
        for link in snap["links"]:
            match = next((r for r in fresh if _link_of("PO", r) == int(link["soDtlKey"])
                          and _dec(r.get("Qty")) == _dec(link["qty"])), None)
            if match is None:  # cannot happen after a verified PUT; resume rejects it earlier
                raise _Done(NEEDS_ATTENTION, INTERNAL_ERROR)
            fresh.remove(match)
            answer.append({"soDocKey": link["soDocKey"], "soDtlKey": link["soDtlKey"], "qty": link["qty"],
                           "poDtlKey": int(match["DtlKey"])})
            moves.append((int(match["DtlKey"]), link.get("location"),
                          {"soDeliveryDate": link.get("soDeliveryDate"), "note": link.get("note")}))
        document, failed = self._restore_rows(row, company, snap, moves, document, deadline=deadline)
        self.prims._stage(company, snap["kind"], document, None)
        old_key = int(snap["row"]["DtlKey"])
        kept = next((r for r in document.get("Details") or [] if r.get("DtlKey") == old_key), None)
        batch = {"links": answer, "skipped": list(snap.get("skipped") or []),
                 "freeLine": None if kept is None else {"poDtlKey": old_key, "qty": str(_dec(kept.get("Qty")))}}
        if failed:
            return self._needs_attention(row, company, snap, RESTORE_NOT_LANDED, batch=batch)
        return self._finish(row, DONE, None, document=document, batch=batch)

    def _resume_batch(self, row: AcWriteOperation, company: AcCompany, snap: Doc, doc: Doc) -> OperationResult:
        """A pending batch. Everything landed (every expected (FromSODtlKey, qty) new row is on the PO)
        -> repair it (plan 65 D5): re-judge the stored link PUT, check the fresh PO's shape, then the ONE
        restore PUT (never the link PUT again). Nothing landed (no new row carries any batch SO row, and
        the old row reads back at its snapshot quantity) -> ``NOT_APPLIED``, the caller runs it fresh.
        Anything in between needs a person: no PUT is sent."""
        known = set(snap["knownKeys"])
        fresh = [r for r in doc.get("Details") or [] if r.get("DtlKey") not in known]
        batch_keys = {int(link["soDtlKey"]) for link in snap["links"]}
        pool = list(fresh)
        landed = True
        for link in snap["links"]:
            match = next((r for r in pool if _link_of("PO", r) == int(link["soDtlKey"])
                          and _dec(r.get("Qty")) == _dec(link["qty"])), None)
            if match is None:
                landed = False
                break
            pool.remove(match)
        if landed:
            code = self._link_step_verdict(row, company, snap, doc) or self._batch_shape(snap, doc)
            if code:
                return self._needs_attention(row, company, snap, code)
            snap = self._batch_so_values(row, company, snap)
            if snap is None:
                return self._needs_attention(row, company, row.snapshot_json or {}, "RESUMED")
            return self._batch_done(row, company, snap, doc, deadline=False)
        old_key = int(snap["row"]["DtlKey"])
        old = next((r for r in doc.get("Details") or [] if r.get("DtlKey") == old_key), None)
        any_batch_row = any(_link_of("PO", r) in batch_keys for r in fresh)
        if not any_batch_row and old is not None and _dec(old.get("Qty")) == _dec(snap["row"].get("Qty")):
            return self._finish(row, RECOVERED, NOT_APPLIED, document=doc)
        return self._needs_attention(row, company, snap, "RESUMED")

    def _batch_lines(self, snap: Doc) -> List[Doc]:
        """The new rows the link PUT asked for, as ``verify_link_batch`` compares them."""
        base = snap["row"]
        return [{"FromDocDtlKey": int(link["soDtlKey"]), "Qty": link["qty"], "ItemCode": base.get("ItemCode"),
                 "UOM": base.get("UOM")} for link in snap["links"]]

    def _link_step_verdict(self, row: AcWriteOperation, company: AcCompany, snap: Doc, doc: Doc) -> Optional[str]:
        """Plan 65 D5 (1), pure: the stored link PUT re-judged with today's verify (D1 tolerance): its
        before-read against its read-back, or against the fresh read when it has none (a timeout). None
        = it verifies; else the code (real collateral drift stays with a person)."""
        action = self.prims.actions.operation_step(company.tenant_id, company.id, row.id, "link")
        before = action.before_json if action is not None else None
        if not isinstance(before, dict):
            return "RESUMED"
        after = action.after_json if isinstance(action.after_json, dict) else doc
        verdict = payloads.verify_link_batch("PO", before, int(snap["row"]["DtlKey"]), self._batch_lines(snap), after)
        if verdict.outcome == payloads.DONE:
            return None
        return verdict.code or INTERNAL_ERROR

    @staticmethod
    def _batch_shape(snap: Doc, doc: Doc) -> Optional[str]:
        """Plan 65 D5 (2): the fresh PO as the batch left it: the kept row at its snapshot qty less the
        linked qty (or gone when all was taken), exactly one new row per link (FromSODtlKey + qty), and
        no other new row linked to a batch SO row. None = it is; else the code."""
        old_key = int(snap["row"]["DtlKey"])
        rest = _dec(snap["row"].get("Qty")) - sum((_dec(link["qty"]) for link in snap["links"]), Decimal(0))
        kept = next((r for r in doc.get("Details") or [] if r.get("DtlKey") == old_key), None)
        if rest == 0 and kept is not None:
            return "LINE_NOT_DELETED"
        if rest != 0 and (kept is None or _dec(kept.get("Qty")) != rest):
            return "ROW_MISMATCH"
        known = set(snap["knownKeys"])
        batch_keys = {int(link["soDtlKey"]) for link in snap["links"]}
        pool = [r for r in doc.get("Details") or [] if r.get("DtlKey") not in known and _link_of("PO", r) in batch_keys]
        for link in snap["links"]:
            match = next((r for r in pool if _link_of("PO", r) == int(link["soDtlKey"])
                          and _dec(r.get("Qty")) == _dec(link["qty"])), None)
            if match is None:
                return "LINK_MISMATCH"
            pool.remove(match)
        return "ROWS_UNEXPECTED" if pool else None

    def _so_reread(self, company: AcCompany, so_no: Optional[str], so_doc_key: Optional[int], so_dtl_key: int,
                   sources: Dict[Any, Doc]) -> Optional[Doc]:
        """Plan 65 D5 / R3: the SO values of one SO row for a snapshot stored without them, from a fresh read
        through the logged reader (bydocno by its number, else by its key and staged date; ``sources`` caches
        one read per SO). None = it cannot be read or the row is gone."""
        cache_key = so_no or so_doc_key
        so = sources.get(cache_key)
        if so is None:
            if so_no:
                reader = self._reader(company, self._base_url, "SO", so_doc_key, so_no)
                self.db.commit()
                try:
                    so = reader.get_by_doc_no("SO", str(so_no))
                except DocReadError:
                    return None
            elif so_doc_key is not None:
                try:
                    _d, so = self._read(company, "SO", so_doc_key, None)
                except _Done:
                    return None
            else:
                return None
            sources[cache_key] = so
        so_row = next((r for r in so.get("Details") or [] if r.get("DtlKey") == so_dtl_key), None)
        return None if so_row is None else self._so_link_values(so, so_row)

    def _batch_so_values(self, row: AcWriteOperation, company: AcCompany, snap: Doc) -> Optional[Doc]:
        """Plan 65 D5 (3): the snapshot with every link's SO row date and note. An older snapshot that has
        none re-reads its SO (the logged reader, once per SO) and keeps the values; None = an SO could
        not be read (no PUT)."""
        if all("note" in link for link in snap["links"]):
            return snap
        sources: Dict[Any, Doc] = {}
        links: List[Doc] = []
        for link in snap["links"]:
            link = dict(link)
            if "note" not in link:
                values = self._so_reread(company, link.get("soNo"), int(link["soDocKey"]), int(link["soDtlKey"]),
                                         sources)
                if values is None:
                    return None
                link.update(values)
            links.append(link)
        fresh = _json_safe(dict(snap, links=links))
        row.snapshot_json = fresh
        self.db.commit()
        return fresh

    # ── split link (plan 55 wrapped, AC-57-40) ───────────────────────────────

    def _split_link(self, row: AcWriteOperation, company: AcCompany, spec: _Spec,
                    params: Dict[str, Any]) -> OperationResult:
        legacy = WriteBackService(
            self.db, client_factory=self.prims._client_factory, reader_factory=self.prims._reader_factory,
            sink_factory=self.prims._sink_factory, actor=self.prims._actor, request_id=self.prims.request_id,
            operation_id=row.id,
        )
        legacy.use_trace(self.prims.request_id, (self.prims.acting_user_id, self.prims.acting_user_name))
        legacy.so_lock_held = True  # _execute holds the SO row lock around this call
        qty = Decimal(str(params["qty"]))
        # the over-link guard of other callers counts this link while its outcome is unknown (pending_link_qty)
        row.snapshot_json = {"mode": "split", "links": [{"soDtlKey": spec.target_dtl_key, "qty": str(qty)}]}
        self.db.commit()
        found, missing = self.prims.find_date(company, "PO", spec.doc_key, _as_date(spec.doc_date))
        if found is None and missing == frame.DOC_KIND_MISMATCH or found is None and missing:
            raise _Done(REFUSED, missing)
        result: WriteActionResult = legacy.link(
            tenant_id=company.tenant_id, company_id=company.id, key_id=row.key_id,
            po_doc_key=spec.doc_key, po_dtl_key=spec.dtl_key, so_doc_key=int(spec.target_doc_key or 0),
            so_dtl_key=int(spec.target_dtl_key or 0), qty=qty,
            expected_last_modified=spec.expected_last_modified, so_doc_date=_as_date(spec.target_doc_date), doc_date=found,
        )
        if result.action_id and self.prims.actions.attach_to_operation(
            company.tenant_id, result.action_id, row.id, SPLIT_LINK, "PUT", EDIT_PO_PATH
        ):
            self.db.commit()
        self._steps.append({"step": SPLIT_LINK, "outcome": result.outcome, "code": result.error_code,
                            "actionId": result.action_id})
        status = result.outcome if result.outcome in (DONE, REFUSED, PENDING, VENDOR_ERROR) else (
            PENDING if result.outcome == OUTCOME_MISMATCH else result.outcome)
        return self._finish(row, status, result.error_code, message=result.message, document=result.document,
                            detail=result.detail)

    # ── gateway helpers (plan 57 S6) ─────────────────────────────────────────

    def write_book(self, company: AcCompany) -> Optional[str]:
        """The AutoCount book (``/api/<book>``) SS writes to for this company, or
        None when writes are off or the connection names a book off the allowlist
        (a refused book is never named, AC-57-47). Lets a consumer refuse an edit of
        a document keyed to another book (SS-WRITECAP-BOOK)."""
        base_url, _ = self.prims._resolve_write_base_url(company)
        return None if base_url is None else guard.assert_write_allowed(base_url)

    def capabilities(self, company: AcCompany) -> List[Dict[str, Any]]:
        """Every primitive per kind and every operation, enabled or not and why
        (reads the flags now; no AutoCount call). No usable write connection =
        every entry off with that reason."""
        base_url, refusal = self.prims._resolve_write_base_url(company)
        off = None if base_url is not None else (refusal[0] if refusal else WRITE_DISABLED)
        items: List[Dict[str, Any]] = []

        def entry(op: str, kind: str, enabled: bool) -> None:
            reason = off or (None if enabled else VENDOR_UNSUPPORTED)
            items.append({"op": op, "kind": WIRE_SLUGS[kind], "enabled": reason is None, "reasonCode": reason})

        for kind in KINDS:
            for primitive in ("create_doc", "edit_doc", "add_line", "delete_line", "cancel_doc"):
                entry(primitive, kind, capabilities.capable(kind, primitive))
        entry(SPLIT_LINK, "PO", capabilities.capable("PO", "edit_doc") and capabilities.capable("PO", "add_line")
              and bool(capabilities.VENDOR_CAPABILITIES.get("link_new_row")))
        entry(LINK_BATCH, "PO", op_capable(OPS["link_row"]))
        for name, defn in OPS.items():
            entry(name, defn.kind, op_capable(defn))
        return items

    def run_primitive(
        self, *, tenant_id: str, company_id: str, key_id: Optional[str], idempotency_key: str,
        name: str, kind: str, doc_key: Optional[int], params: Dict[str, Any],
        call: Callable[[], PrimitiveResult],
    ) -> Dict[str, Any]:
        """One primitive under an idempotency key: the stored answer on a replay,
        ``IDEMPOTENCY_CONFLICT`` for another body, else run ``call`` and store the
        answer. Returns the answer dict (the gateway body)."""
        label = f"{name}:{kind}"
        if CompanyRepository(self.db).get(tenant_id, company_id) is None:
            return primitive_answer(PrimitiveResult(None, OUTCOME_REFUSED, WRITE_DISABLED), doc_key)
        request_hash = hashlib.sha256(
            json.dumps({"op": label, "docKey": doc_key, "params": params}, sort_keys=True, default=str).encode()
        ).hexdigest()

        def replay(row: AcWriteOperation) -> Dict[str, Any]:
            if row.op != label or row.request_hash != request_hash:
                return primitive_answer(PrimitiveResult(None, OUTCOME_REFUSED, IDEMPOTENCY_CONFLICT), doc_key)
            if row.status == IN_PROGRESS or not row.result_json:
                return primitive_answer(PrimitiveResult(None, OUTCOME_REFUSED, OPERATION_IN_PROGRESS), doc_key)
            return dict(row.result_json)

        existing = self.ops.by_key(tenant_id, company_id, key_id, idempotency_key)
        if existing is not None:
            looked_up = name == "create_doc" and existing.op == label and "start" in (existing.snapshot_json or {})
            if looked_up:
                early = self._create_resend(existing, tenant_id, company_id, replay)
                if early is not None:
                    return early
            elif (existing.status == OUTCOME_REFUSED if name == "create_doc"
                  else self._nothing_landed(existing.status, existing.error_code)):
                # plan 62 D6: run fresh. A create stored before its first attempt was recorded cannot be
                # looked up, so only SS's own refusal releases it; a vendor failure stays locked
                self._release_key(existing)
            else:
                return replay(existing)
        if doc_key is not None:  # a crashed run of ANY kind no longer holds the document (AC-57-43)
            window = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS)
            if self.ops.expire_stale_in_progress(tenant_id, company_id, kind, doc_key, window):
                self.db.commit()
        info = _create_info(kind, params, datetime.now(timezone.utc)) if name == "create_doc" else None
        row = AcWriteOperation(
            tenant_id=tenant_id, company_id=company_id, key_id=key_id, idempotency_key=idempotency_key,
            request_hash=request_hash, op=label, doc_type=kind, doc_key=doc_key, status=IN_PROGRESS,
            snapshot_json=info,
        )
        try:
            self.ops.add(row)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raced = self.ops.by_key(tenant_id, company_id, key_id, idempotency_key)
            if raced is not None:
                return replay(raced)
            return primitive_answer(PrimitiveResult(None, OUTCOME_REFUSED, DOC_BUSY), doc_key)
        vendor_class: Optional[str] = None
        status, code = PENDING, INTERNAL_ERROR
        answer = primitive_answer(PrimitiveResult(None, OUTCOME_PENDING, INTERNAL_ERROR), doc_key)
        try:
            result = call()
            answer = primitive_answer(result, doc_key)
            status, code = result.outcome, result.error_code
            vendor_class = result.vendor_class
        except Exception:  # noqa: BLE001 - the in_progress lock must never be stranded
            logger.exception("autocount primitive call failed (%s)", row.id)
            self.db.rollback()
        finally:
            row = self.ops.get(tenant_id, company_id, row.id) or row
            if code == DOC_BUSY and status == OUTCOME_REFUSED:  # never stored: the key stays usable
                self.ops.delete(row)
            else:
                row.status, row.error_code, row.result_json = status, code, _json_safe(answer)
                if info is not None:  # what a resend needs to look the document up (class name only)
                    row.snapshot_json = dict(info, end=datetime.now(timezone.utc).isoformat(),
                                             vendorClass=vendor_class)
            self.db.commit()
        return answer

    # ── create resend (plan 62 review): look the document up before re-running ──

    def _create_resend(self, existing: AcWriteOperation, tenant_id: str, company_id: str,
                       replay: Callable[[AcWriteOperation], Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """The answer for a resent create, or None when the key was released and the create must run.
        A stored refusal and a refusal AutoCount raised before saving release at once; any other
        stored failure or pending outcome looks the document up first: found -> done (locked),
        several -> needs attention (locked), none -> released."""
        info = existing.snapshot_json or {}
        if existing.status == OUTCOME_REFUSED or (
            existing.status == OUTCOME_VENDOR_ERROR and info.get("vendorClass") in PRE_SAVE_REFUSALS
        ):
            self._release_key(existing)
            return None
        if existing.status not in (OUTCOME_VENDOR_ERROR, OUTCOME_PENDING):
            return replay(existing)
        company = CompanyRepository(self.db).get(tenant_id, company_id)
        if company is None:
            return replay(existing)
        try:
            found = self.find_created_doc(company, existing.doc_type or "", info, key_id=existing.key_id,
                                          operation_id=existing.id)
        except _AmbiguousCreate:
            existing.status, existing.error_code = NEEDS_ATTENTION, CREATE_AMBIGUOUS
            existing.result_json = _json_safe(primitive_answer(PrimitiveResult(
                None, NEEDS_ATTENTION, CREATE_AMBIGUOUS,
                "More than one matching document exists in AutoCount; check it there."), None))
            self.db.commit()
            return replay(existing)
        except _LookupFailed:
            return replay(existing)  # cannot prove nothing was saved: the stored answer stands
        if found is None:
            self._release_key(existing)
            return None
        existing.status, existing.error_code = OUTCOME_DONE, None
        existing.result_json = _json_safe(primitive_answer(PrimitiveResult(
            None, OUTCOME_DONE, None, "The document was found in AutoCount.",
            doc_key=found.get("DocKey"), doc_no=found.get("DocNo")), None))
        self.db.commit()
        return replay(existing)

    def find_created_doc(self, company: AcCompany, kind: str, info: Dict[str, Any], *,
                         key_id: Optional[str] = None, operation_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The one document a create that may have landed produced, ``{"DocKey", "DocNo"}``, else None.
        A numbered body is read by DocNo; a ``<<New>>`` body is matched in the ``byLastModified`` day
        list(s) covering the first attempt (AutoCount local time, MYT): same party, ``CreatedTimeStamp``
        within a minute of the attempt, same line multiset (ItemCode, Qty, UOM). Several matches raise
        ``_AmbiguousCreate``. The day lists run from the first attempt's MYT day to today (a later edit moves a
        document to a later list), at most ``LOOKUP_MAX_DAYS`` back; an attempt older than that and not found
        stays locked. A document another done create of this company already owns is never adopted. Every GET
        is logged under the stored operation (``key_id``, ``operation_id``)."""
        from modules.autocount.doc_feed.clock import MYT

        base_url, _refusal = self.prims._resolve_write_base_url(company)
        if base_url is None or kind not in KINDS:
            raise _LookupFailed()
        reader = self.prims._reader_for(base_url, self.prims.new_call_log(
            company, kind=kind, key_id=key_id, operation_id=operation_id))
        start_at = datetime.fromisoformat(info["start"])
        end_at = datetime.fromisoformat(info["end"]) if info.get("end") else datetime.now(timezone.utc)
        owned_keys, owned_numbers = self.ops.created_documents(
            company.tenant_id, company.id, operation_id or "",
            start_at - timedelta(seconds=LOOKUP_WINDOW_SECONDS), end_at + timedelta(seconds=LOOKUP_WINDOW_SECONDS))
        party_field = KINDS[kind].party_field
        wanted = [(str(i), _dec(q), u) for i, q, u in info.get("lines") or []]
        use_uom = bool(wanted) and all(u for _i, _q, u in wanted)

        def shape(rows: List[Doc]) -> List[Tuple[Any, ...]]:
            out = [(str(r.get("ItemCode")), _dec(r.get("Qty"))) + ((r.get("UOM"),) if use_uom else ()) for r in rows]
            return sorted(out, key=str)

        want_shape = sorted([(i, q) + ((u,) if use_uom else ()) for i, q, u in wanted], key=str)

        def ours(doc: Doc) -> bool:
            if doc.get("DocKey") in owned_keys or doc.get("DocNo") in owned_numbers:
                return False
            if info.get("party") and doc.get(party_field) != info["party"]:
                return False
            if kind in ("PO", "SPO") and (kind == "SPO") != (doc.get("ShippingPO") == "T"):
                return False
            return not wanted or shape(doc.get("Details") or []) == want_shape

        self.db.commit()  # no transaction open during a GET
        try:
            if info.get("docNo"):
                try:
                    doc = reader.get_by_doc_no(kind, str(info["docNo"]))
                except DocReadError as exc:
                    if exc.code == "DOC_NOT_FOUND":
                        return None
                    if exc.code == "DOC_AMBIGUOUS":
                        raise _AmbiguousCreate() from None
                    raise _LookupFailed() from None
                return {"DocKey": doc.get("DocKey"), "DocNo": doc.get("DocNo")} if ours(doc) else None
            start, end = start_at, end_at
            low = (start - timedelta(seconds=LOOKUP_WINDOW_SECONDS)).astimezone(MYT)
            high = (end + timedelta(seconds=LOOKUP_WINDOW_SECONDS)).astimezone(MYT)
            matches: List[Doc] = []
            today = datetime.now(timezone.utc).astimezone(MYT).date()
            oldest = today - timedelta(days=LOOKUP_MAX_DAYS)
            day = max(low.date(), oldest)
            too_old = low.date() < oldest
            while day <= max(high.date(), today):
                for doc in reader.list_day(kind, day, by_last_modified=True):
                    try:
                        created = datetime.fromisoformat(str(doc.get("CreatedTimeStamp"))).replace(tzinfo=MYT)
                    except ValueError:
                        continue
                    if low <= created <= high and ours(doc) and doc.get("DocKey") not in {m.get("DocKey") for m in matches}:
                        matches.append(doc)
                day += timedelta(days=1)
        except DocReadError:
            raise _LookupFailed() from None
        if len(matches) > 1:
            raise _AmbiguousCreate()
        if not matches and too_old:
            raise _LookupFailed()  # past the scan reach: nothing proves it was not saved
        return {"DocKey": matches[0].get("DocKey"), "DocNo": matches[0].get("DocNo")} if matches else None

    # ── needs_attention mail (AC-57-35) ──────────────────────────────────────

    def _notify(self, company: AcCompany, row: AcWriteOperation, snap: Doc) -> None:
        base = snap["row"]
        link = snap.get("oldLink") or {}
        text = ""
        if link.get("FromDocDtlKey"):
            text = f"{link.get('FromDocType')} {link.get('FromDocNo')} row {link.get('FromDocDtlKey')}"
        event = {
            "tenantId": company.tenant_id, "operationId": row.id, "company": snap["companyName"],
            "docType": snap["kind"], "docNo": snap["docNo"], "docKey": snap["docKey"],
            "item": base.get("ItemCode"), "uom": base.get("UOM"), "qty": str(base.get("Qty")),
            "location": base.get("Location"), "link": text or "none", "op": row.op,
        }
        if snap.get("mode") == "partial" and snap.get("received") is not None:
            remainder = _dec(base.get("Qty")) - Decimal(snap["received"])
            event.update(
                mode="partial", cutQty=str(Decimal(snap["received"])), remainderQty=str(remainder),
                note=f"the line was cut to the received quantity {Decimal(snap['received'])} and its "
                     f"remainder {remainder} could not be added",
            )
        if snap.get("mode") == "batch" or snap.get("mergeInto"):  # a change whose outcome could not be confirmed
            event["mode"] = "check"
        try:
            self._notifier(event)
        except Exception:  # noqa: BLE001 - a mail fault never changes the outcome
            logger.exception("autocount needs-attention notice failed (%s)", row.id)

    def _mail(self, event: Dict[str, Any]) -> None:
        """One outbox mail per same-tenant alert recipient (no host, no key)."""
        from app.services.email_service import email_service

        rows = [
            ("Company", event["company"]), ("Document", f"{event['docType']} {event['docNo']}"),
            ("Item", event["item"]), ("Unit", event["uom"]), ("Quantity", event["qty"]),
            ("Location", event["location"]), ("Linked to", event["link"]),
        ]
        lead = "A line was deleted in AutoCount and could not be re-created. Re-key it:"
        if event.get("mode") == "check":
            lead = "A change to this line may or may not have reached AutoCount. Check the document there:"
        if event.get("mode") == "partial":
            rows[4] = ("Remainder quantity", event["remainderQty"])
            rows.insert(5, ("Cut to (received)", event["cutQty"]))
            lead = ("A line was cut in AutoCount to its received quantity and the remainder could not be "
                    "added. Add the remainder:")
        text = "\n".join([lead, "", *[f"{k}: {v}" for k, v in rows]])
        cells = "".join(
            f'<tr><td style="padding:4px 16px 4px 0;color:#6b7280">{html.escape(str(k))}</td>'
            f'<td style="padding:4px 0">{html.escape(str(v))}</td></tr>' for k, v in rows
        )
        body = (f'<div style="font-family:Arial,sans-serif;font-size:14px;color:#111827">'
                f"<p>{html.escape(lead)}</p><table>{cells}</table></div>")
        what = "AutoCount line to check" if event.get("mode") == "check" else "AutoCount line needs re-keying"
        subject = _safe_subject(f"{what}: {event['company']} {event['docNo']}")
        for address, _zone in alert_recipients(self.db, event["tenantId"], []):
            email_service.enqueue_raw(
                self.db, event["tenantId"], address, subject, body, text,
                template_key=TEMPLATE_KEY, commit=False,
            )
        self.db.commit()
