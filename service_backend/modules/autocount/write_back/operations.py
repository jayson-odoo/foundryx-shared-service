"""Write-back operations (plan 57 section 5.3, AC-57-30..40).

The level-2 unit a caller asks for: link / unlink / relink of a PO row (to an SO
row) or an SPO row (to a PO row), and the plan 55 split link, each under an
idempotency key. AutoCount never changes a link in place, so a row operation is
snapshot -> delete -> add (with the new link or none) -> move the location,
every step one primitive (``PrimitiveService``, no second write frame). The
cross-step busy lock is the ``in_progress`` partial unique index of
``ac_write_operation``. A failed add after the delete is recovered from the
snapshot; when that fails too the operation is ``needs_attention``, one alert
mail goes out and nothing is retried automatically; ``resume`` re-reads
AutoCount and re-creates the line only when it is still absent.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modules.autocount.alerts import _safe_subject, alert_recipients
from modules.autocount.canonical.documents import ENTITY_SALES_ORDER, ENTITY_SHIPPING_ORDER
from modules.autocount.models import AcCompany, AcWriteAction, AcWriteOperation
from modules.autocount.repositories import CompanyRepository
from modules.autocount.write_back import capabilities, payloads
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
from modules.autocount.write_back.doc_kinds import KINDS
from modules.autocount.write_back.payloads import WriteRefusal
from modules.autocount.write_back.primitives import PrimitiveResult, PrimitiveService
from modules.autocount.write_back.reader import DocReadError
from modules.autocount.write_back.repository import OperationRepository
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
INVALID_PARAMS = "INVALID_PARAMS"
VENDOR_REFUSED = "VENDOR_REFUSED"
ROW_RECEIVED = "ROW_RECEIVED"
TRANSFER_STATE_UNKNOWN = "TRANSFER_STATE_UNKNOWN"
LOCATION_NOT_MOVED = "LOCATION_NOT_MOVED"
NOT_APPLIED = "OPERATION_NOT_APPLIED"
SPLIT_LINK = "split_link"
TEMPLATE_KEY = "autocount_write_needs_attention"

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


@dataclass
class _Spec:
    doc_key: int
    dtl_key: int
    target_doc_key: Optional[int] = None
    target_dtl_key: Optional[int] = None
    doc_date: Optional[date] = None
    expected_last_modified: Optional[str] = None


class _Done(Exception):
    """Internal early exit carrying a finished result."""

    def __init__(self, status: str, code: Optional[str] = None, message: str = "") -> None:
        self.status, self.code, self.message = status, code, message


def default_receipt_reader(kind: str, doc: Doc, row: Doc) -> Optional[Decimal]:
    """The row's AutoCount ``TransferedQty``; the hapi GET does not return it
    (AQ11), so a hapi document row reads as unknown (None)."""
    value = row.get("TransferedQty")
    return None if value is None else _dec(value)


def primitive_answer(res: PrimitiveResult, doc_key: Optional[int] = None) -> Dict[str, Any]:
    """The gateway answer of a primitive (contract section 4)."""
    return {
        "operationId": None, "actionId": res.action_id, "outcome": res.outcome, "errorCode": res.error_code,
        "message": res.message, "warnings": list(res.warnings), "docKey": res.doc_key or doc_key,
        "docNo": res.doc_no, "replacedLines": [], "document": res.document,
    }


def _doc_no(document: Optional[Doc], snapshot: Optional[Doc]) -> Optional[str]:
    number = (document or {}).get("DocNo") or (snapshot or {}).get("docNo")
    return str(number) if number else None


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _link_of(kind: str, row: Doc) -> int:
    """The link key a row reads back with: PO rows carry ``FromSODtlKey``, SPO
    rows ``FromDocDtlKey``."""
    return int((row.get("FromSODtlKey") if kind == "PO" else row.get("FromDocDtlKey")) or 0)


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
    ) -> None:
        self.db = db
        self.prims = PrimitiveService(
            db, client_factory=client_factory, reader_factory=reader_factory, sink_factory=sink_factory
        )
        self.ops = OperationRepository(db)
        self._receipt_reader = receipt_reader or default_receipt_reader
        self._notifier = notifier or self._mail
        self._steps: List[Dict[str, Any]] = []
        self._warnings: List[str] = []

    # ── public ───────────────────────────────────────────────────────────────

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
        if op != SPLIT_LINK and op not in OPS:
            return OperationResult(None, REFUSED, UNKNOWN_OPERATION)
        request_hash = hashlib.sha256(
            json.dumps({"op": op, "params": params}, sort_keys=True, default=str).encode()
        ).hexdigest()
        existing = self.ops.by_key(tenant_id, company.id, key_id, idempotency_key)
        if existing is not None:
            return self._replay(existing, op, request_hash)
        try:
            spec = self._spec(op, params)
        except (KeyError, TypeError, ValueError):
            return OperationResult(None, REFUSED, INVALID_PARAMS)
        kind = OPS[op].kind if op in OPS else "PO"
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
            return self._store_refusal(
                tenant_id, company.id, key_id, idempotency_key, request_hash, op, kind, spec, DOC_BUSY
            )
        self._steps, self._warnings = [], []
        return self._guarded(row, company, lambda: self._execute(row, company, op, spec, params))

    def resume(self, *, tenant_id: str, company_id: str, operation_id: str) -> OperationResult:
        row = self.ops.get(tenant_id, company_id, operation_id)
        if row is None:
            raise LookupError("operation not found")
        if row.status not in (NEEDS_ATTENTION, PENDING) or not row.snapshot_json:
            return self._from_row(row)
        company = CompanyRepository(self.db).get(tenant_id, company_id)
        if company is None:
            return OperationResult(row.id, REFUSED, WRITE_DISABLED)
        was = row.status
        row.status = IN_PROGRESS
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return OperationResult(row.id, REFUSED, DOC_BUSY)
        self._steps, self._warnings = list(row.steps_json or []), []
        return self._guarded(row, company, lambda: self._resume(row, company, was), restore=was)

    # ── frame ────────────────────────────────────────────────────────────────

    def _guarded(self, row: AcWriteOperation, company: AcCompany, body: Callable[[], OperationResult],
                 restore: Optional[str] = None) -> OperationResult:
        """Run ``body``; whatever happens the operation row leaves ``in_progress``."""
        try:
            return body()
        except _Done as done:
            return self._finish(row, done.status, done.code, message=done.message)
        except Exception:  # noqa: BLE001 - the in_progress lock must never be stranded
            logger.exception("autocount operation failed (%s)", row.id)
            self.db.rollback()
            return self._finish(row, restore or PENDING, INTERNAL_ERROR)
        finally:
            self.db.rollback()

    @staticmethod
    def _spec(op: str, params: Dict[str, Any]) -> _Spec:
        if op == SPLIT_LINK:
            return _Spec(
                int(params["po_doc_key"]), int(params["po_dtl_key"]),
                int(params["so_doc_key"]), int(params["so_dtl_key"]),
                params.get("doc_date"), params.get("expected_last_modified"),
            )
        names = _PARAM_NAMES[OPS[op].kind]
        target = OPS[op].target
        return _Spec(
            int(params[names[0]]), int(params[names[1]]),
            int(params[names[2]]) if target else None, int(params[names[3]]) if target else None,
            params.get("doc_date"), params.get("expected_last_modified"),
        )

    def _store_refusal(self, tenant_id: str, company_id: str, key_id: Optional[str], key: str,
                       request_hash: str, op: str, kind: str, spec: _Spec, code: str) -> OperationResult:
        row = AcWriteOperation(
            tenant_id=tenant_id, company_id=company_id, key_id=key_id, idempotency_key=key,
            request_hash=request_hash, op=op, doc_type=kind, doc_key=spec.doc_key, dtl_key=spec.dtl_key,
            status=REFUSED,
        )
        self.ops.add(row)
        return self._finish(row, REFUSED, code)

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
            row.doc_key, _doc_no(stored.get("document"), row.snapshot_json),
        )

    def _finish(self, row: AcWriteOperation, status: str, code: Optional[str] = None, *, message: str = "",
                replaced: Optional[List[Tuple[int, int]]] = None,
                document: Optional[Doc] = None) -> OperationResult:
        result = OperationResult(
            row.id, status, code, message, list(self._warnings), list(replaced or []), document,
            row.doc_key, _doc_no(document, row.snapshot_json),
        )
        row.status, row.error_code = status, code
        row.steps_json = _json_safe(self._steps)
        row.result_json = _json_safe({
            "outcome": status, "errorCode": code, "message": message, "warnings": result.warnings,
            "replacedLines": [list(p) for p in result.replaced_lines], "document": document,
        })
        self.db.commit()
        return result

    def _step(self, name: str, res: PrimitiveResult) -> None:
        self._steps.append({"step": name, "outcome": res.outcome, "code": res.error_code,
                            "actionId": res.action_id, "newDtlKey": res.new_dtl_key})

    # ── execute ──────────────────────────────────────────────────────────────

    def _execute(self, row: AcWriteOperation, company: AcCompany, op: str, spec: _Spec,
                 params: Dict[str, Any]) -> OperationResult:
        base_url, refusal = self.prims._resolve_write_base_url(company)
        if base_url is None:
            raise _Done(REFUSED, refusal[0] if refusal else WRITE_DISABLED)
        if op == SPLIT_LINK:
            return self._split_link(row, company, spec, params)
        defn = OPS[op]
        for primitive in ("delete_line", "add_line", "edit_doc"):
            if not capabilities.capable(defn.kind, primitive):
                raise _Done(REFUSED, VENDOR_UNSUPPORTED)
        self._check_not_busy(company, spec.doc_key)
        reader = self.prims._reader_factory(base_url)
        doc_date, doc = self._read(company, reader, defn.kind, spec.doc_key, spec.doc_date)
        if spec.expected_last_modified and doc.get("LastModified") != spec.expected_last_modified:
            raise _Done(REFUSED, DOC_STALE)
        plan = self._guards(company, reader, defn, spec, doc)
        snapshot = self._snapshot(company, defn, spec, doc, doc_date, plan)
        row.snapshot_json = snapshot
        self.db.commit()
        return self._steps_run(row, company, op, defn, spec, snapshot)

    def _check_not_busy(self, company: AcCompany, doc_key: int) -> None:
        window = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS)
        if self.prims.actions.expire_stale_in_flight(company.tenant_id, company.id, doc_key, window):
            self.db.commit()
        if self.prims.actions.has_open(company.tenant_id, company.id, doc_key, window):
            raise _Done(REFUSED, DOC_BUSY)

    def _read(self, company: AcCompany, reader: Any, kind: str, doc_key: int,
              doc_date: Optional[date]) -> Tuple[date, Doc]:
        """AC-57-20 date, then one fresh GET with no transaction open."""
        found, code = self.prims.find_date(company, kind, doc_key, doc_date)
        if found is None:
            raise _Done(REFUSED, code)
        self.db.commit()
        try:
            return found, reader.get_document(kind, doc_key, found)
        except DocReadError as exc:
            raise _Done(REFUSED, exc.code) from None

    # ── guards (AC-57-32, 33): every refusal before any write ────────────────

    def _guards(self, company: AcCompany, reader: Any, defn: _OpDef, spec: _Spec, doc: Doc) -> Dict[str, Any]:
        try:
            payloads.build_delete_line(defn.kind, doc, spec.dtl_key)  # kind, cancelled, row exists
        except WriteRefusal as exc:
            raise _Done(REFUSED, exc.code, str(exc)) from None
        row = next(r for r in doc.get("Details") or [] if r.get("DtlKey") == spec.dtl_key)
        if defn.kind == "PO" and self._spo_ref(company, spec.dtl_key):
            raise _Done(REFUSED, "ROW_ON_SPO")
        linked = _link_of(defn.kind, row)
        if defn.mode == "link" and linked:
            raise _Done(REFUSED, "ROW_ALREADY_LINKED")
        if defn.mode in ("unlink", "relink") and not linked:
            raise _Done(REFUSED, "ROW_NOT_LINKED")
        if defn.mode == "relink" and linked == spec.target_dtl_key:
            raise _Done(REFUSED, "NO_CHANGE")
        mode, received = self._receipt(defn, doc, row)
        qty = _dec(row.get("Qty"))
        link_qty = qty - received if mode == "partial" else qty
        target: Optional[Doc] = None
        if defn.target and spec.target_doc_key is not None:
            target = self._guard_target(company, reader, defn, spec, doc, row, link_qty)
        return {"mode": mode, "received": received, "target": target, "linkQty": link_qty}

    def _receipt(self, defn: _OpDef, doc: Doc, row: Doc) -> Tuple[str, Optional[Decimal]]:
        """``("delete" | "partial", received)``; an unknown received qty goes the
        delete way with a warning (owner ruling: the refusal comes from AutoCount)."""
        received = self._receipt_reader(defn.kind, doc, row)
        if received is None:
            self._warnings.append(TRANSFER_STATE_UNKNOWN)
            return "delete", None
        if received <= 0:
            return "delete", received
        if received >= _dec(row.get("Qty")) or not capabilities.PARTIAL_RECEIPT_SPLIT:
            raise _Done(REFUSED, ROW_RECEIVED)
        return "partial", received

    def _guard_target(self, company: AcCompany, reader: Any, defn: _OpDef, spec: _Spec, doc: Doc,
                      row: Doc, link_qty: Decimal) -> Doc:
        assert defn.target and spec.target_doc_key is not None
        _date, tdoc = self._read(company, reader, defn.target, spec.target_doc_key, None)
        if tdoc.get("Cancelled") == "T":
            raise _Done(REFUSED, "DOC_CANCELLED")
        trow = next((r for r in tdoc.get("Details") or [] if r.get("DtlKey") == spec.target_dtl_key), None)
        if trow is None:
            raise _Done(REFUSED, "ROW_NOT_FOUND")
        if row.get("ItemCode") != trow.get("ItemCode"):
            raise _Done(REFUSED, "ITEM_MISMATCH")
        if row.get("UOM") != trow.get("UOM"):
            raise _Done(REFUSED, "UOM_MISMATCH")
        if defn.target == "SO":  # AC-57-32 pins the outstanding rule for SO rows only
            used = self.prims._so_linked_qty(company, int(spec.target_dtl_key or 0), fresh_po=doc)
            if link_qty > payloads.so_outstanding(trow, used):
                raise _Done(REFUSED, "QTY_ABOVE_OUTSTANDING")
        return tdoc

    def _spo_ref(self, company: AcCompany, po_dtl_key: int) -> Optional[str]:
        """DocNo of a staged, non-cancelled SPO with a row pointing at the PO row."""
        for staged in self.prims.staged.for_entity(company.tenant_id, company.id, ENTITY_SHIPPING_ORDER):
            raw = staged.raw_json or {}
            if raw.get("Cancelled") != "T" and any(
                r.get("FromDocDtlKey") == po_dtl_key for r in _lines(raw)
            ):
                return str(raw.get("DocNo") or staged.doc_no or staged.source_ref)
        return None

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
        if target is not None and defn.target == "SO":
            trow = next((r for r in target.get("Details") or [] if r.get("DtlKey") == spec.target_dtl_key), {})
            move_to = trow.get("Location") or move_to  # owner ruling: a linked PO row sits at its SO row
        return _json_safe({
            "moveTo": move_to, "kind": defn.kind, "mode": plan["mode"], "docKey": spec.doc_key, "docNo": doc.get("DocNo"),
            "docDate": doc_date.isoformat(), "lastModified": doc.get("LastModified"),
            "knownKeys": [r.get("DtlKey") for r in doc.get("Details") or []],
            "row": row, "received": None if plan["received"] is None else str(plan["received"]),
            "newLink": new_link, "oldLink": self._old_link(company, defn, row),
            "location": row.get("Location"), "companyName": company.company_name or company.name,
        })

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
        partial = snap["mode"] == "partial"
        if partial:
            assert received is not None
            cut = self.prims.edit_doc(
                **self._call(row, company, snap, "cut"), header_changes={},
                line_changes=[{"DtlKey": old_key, "Qty": received}],
            )
            self._step("cut", cut)
            self._abort_unless_done(cut)
        else:
            gone = self.prims.delete_line(**self._call(row, company, snap, "delete"), dtl_key=old_key)
            self._step("delete", gone)
            if gone.outcome == OUTCOME_VENDOR_ERROR:  # AutoCount refused: the delete did not land
                raise _Done(VENDOR_ERROR, gone.error_code, gone.message)
            self._abort_unless_done(gone)
        add = self.prims.add_line(
            **self._call(row, company, snap, "add"),
            line=self._line_of(snap, snap["newLink"], (qty - received) if partial else None),
        )
        self._step("add", add)
        if add.outcome == OUTCOME_PENDING:
            raise _Done(PENDING, add.error_code)
        if add.outcome != OUTCOME_DONE or add.new_dtl_key is None:
            return self._recover(row, company, snap, add.error_code or INTERNAL_ERROR, partial)
        new_key = int(add.new_dtl_key)
        document = self._move(row, company, snap, new_key, add.document, snap.get("moveTo") or snap["location"])
        self.prims._stage(company, snap["kind"], document, None if partial else {new_key: old_key})
        return self._finish(row, DONE, None, replaced=[] if partial else [(old_key, new_key)], document=document)

    def _abort_unless_done(self, res: PrimitiveResult) -> None:
        """A first step that did not land cleanly: nothing to recover."""
        if res.outcome == OUTCOME_DONE:
            return
        if res.outcome == OUTCOME_REFUSED:
            raise _Done(REFUSED, res.error_code, res.message)
        if res.outcome == OUTCOME_VENDOR_ERROR:
            raise _Done(VENDOR_ERROR, res.error_code, res.message)
        raise _Done(PENDING, res.error_code, res.message)  # mismatch / pending: resume decides

    def _move(self, row: AcWriteOperation, company: AcCompany, snap: Doc, new_key: int,
              document: Optional[Doc], location: Optional[str]) -> Doc:
        """Move the new row to ``location`` when the read-back differs (db3 forces
        HQ on a new linked row); a failed move is a warning, never a failure."""
        document = document or {}
        landed = next((r for r in document.get("Details") or [] if r.get("DtlKey") == new_key), {})
        if not location or landed.get("Location") == location:
            return document
        moved = self.prims.edit_doc(
            **self._call(row, company, snap, "move"), header_changes={},
            line_changes=[{"DtlKey": new_key, "Location": location}],
        )
        self._step("move", moved)
        if moved.outcome == OUTCOME_DONE and moved.document:
            return moved.document
        if LOCATION_NOT_MOVED not in self._warnings:
            self._warnings.append(LOCATION_NOT_MOVED)
        return document

    def _recover(self, row: AcWriteOperation, company: AcCompany, snap: Doc, failed_code: str,
                 partial: bool) -> OperationResult:
        """The add failed after step 1 landed: put the line back as it was."""
        old_key = int(snap["row"]["DtlKey"])
        if partial:
            back = self.prims.edit_doc(
                **self._call(row, company, snap, "recover"), header_changes={},
                line_changes=[{"DtlKey": old_key, "Qty": _dec(snap["row"].get("Qty"))}],
            )
            self._step("recover", back)
            if back.outcome == OUTCOME_DONE:
                self.prims._stage(company, snap["kind"], back.document or {})
                return self._finish(row, RECOVERED, failed_code, document=back.document)
        else:
            res = self.prims.add_line(
                **self._call(row, company, snap, "recover"), line=self._line_of(snap, snap["oldLink"])
            )
            self._step("recover", res)
            if res.outcome == OUTCOME_PENDING:
                raise _Done(PENDING, res.error_code)
            if res.outcome == OUTCOME_DONE and res.new_dtl_key is not None:
                new_key = int(res.new_dtl_key)
                document = self._move(row, company, snap, new_key, res.document, snap["location"])
                self.prims._stage(company, snap["kind"], document, {new_key: old_key})
                return self._finish(row, RECOVERED, failed_code, replaced=[(old_key, new_key)], document=document)
        return self._needs_attention(row, company, snap, failed_code)

    def _needs_attention(self, row: AcWriteOperation, company: AcCompany, snap: Doc, code: str,
                         notify: bool = True) -> OperationResult:
        result = self._finish(row, NEEDS_ATTENTION, code)
        if notify:
            self._notify(company, row, snap)
        return result

    # ── resume (AC-57-36) ────────────────────────────────────────────────────

    def _resume(self, row: AcWriteOperation, company: AcCompany, was: str) -> OperationResult:
        snap = row.snapshot_json or {}
        base_url, refusal = self.prims._resolve_write_base_url(company)
        if base_url is None:
            raise _Done(was, refusal[0] if refusal else WRITE_DISABLED)
        kind, doc_date = snap["kind"], date.fromisoformat(snap["docDate"])
        reader = self.prims._reader_factory(base_url)
        self.db.commit()
        try:
            doc = reader.get_document(kind, int(snap["docKey"]), doc_date)
        except DocReadError as exc:
            raise _Done(was, exc.code) from None
        rows = doc.get("Details") or []
        old_key = int(snap["row"]["DtlKey"])
        original = next((r for r in rows if r.get("DtlKey") == old_key), None)
        partial = snap["mode"] == "partial"
        if original is not None and not partial:
            return self._finish(row, REFUSED, NOT_APPLIED, document=doc)  # the delete never landed
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
            document = self._resume_move(row, company, snap, int(intended["DtlKey"]), doc, snap.get("moveTo") or snap["location"])
            new_key = int(intended["DtlKey"])
            self.prims._stage(company, snap["kind"], document, None if partial else {new_key: old_key})
            return self._finish(row, DONE, None, replaced=[] if partial else [(old_key, new_key)],
                                document=document)
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

    def _resume_move(self, row: AcWriteOperation, company: AcCompany, snap: Doc, key: int, doc: Doc,
                     location: Optional[str]) -> Doc:
        return self._move(row, company, snap, key, doc, location)

    # ── split link (plan 55 wrapped, AC-57-40) ───────────────────────────────

    def _split_link(self, row: AcWriteOperation, company: AcCompany, spec: _Spec,
                    params: Dict[str, Any]) -> OperationResult:
        legacy = WriteBackService(
            self.db, client_factory=self.prims._client_factory, reader_factory=self.prims._reader_factory,
            sink_factory=self.prims._sink_factory,
        )
        qty = Decimal(str(params["qty"]))
        result: WriteActionResult = legacy.link(
            tenant_id=company.tenant_id, company_id=company.id, key_id=row.key_id,
            po_doc_key=spec.doc_key, po_dtl_key=spec.dtl_key, so_doc_key=int(spec.target_doc_key or 0),
            so_dtl_key=int(spec.target_dtl_key or 0), qty=qty,
            expected_last_modified=spec.expected_last_modified,
        )
        if result.action_id:
            action = self.db.query(AcWriteAction).filter(
                AcWriteAction.id == result.action_id, AcWriteAction.tenant_id == company.tenant_id
            ).first()
            if action is not None:
                action.operation_id, action.step = row.id, SPLIT_LINK
                action.request_method, action.request_path = "PUT", EDIT_PO_PATH
                self.db.commit()
        self._steps.append({"step": SPLIT_LINK, "outcome": result.outcome, "code": result.error_code,
                            "actionId": result.action_id})
        status = result.outcome if result.outcome in (DONE, REFUSED, PENDING, VENDOR_ERROR) else (
            PENDING if result.outcome == OUTCOME_MISMATCH else result.outcome)
        return self._finish(row, status, result.error_code, message=result.message, document=result.document)

    # ── gateway helpers (plan 57 S6) ─────────────────────────────────────────

    def capabilities(self, company: AcCompany) -> List[Dict[str, Any]]:
        """Every primitive per kind and every operation, enabled or not and why
        (reads the flags now; no AutoCount call). No usable write connection =
        every entry off with that reason."""
        base_url, refusal = self.prims._resolve_write_base_url(company)
        off = None if base_url is not None else (refusal[0] if refusal else WRITE_DISABLED)
        items: List[Dict[str, Any]] = []

        def entry(op: str, kind: str, enabled: bool) -> None:
            reason = off or (None if enabled else VENDOR_UNSUPPORTED)
            items.append({"op": op, "kind": kind, "enabled": reason is None, "reasonCode": reason})

        for kind in KINDS:
            for primitive in ("create_doc", "edit_doc", "add_line", "delete_line", "cancel_doc"):
                entry(primitive, kind, capabilities.capable(kind, primitive))
        for name, defn in OPS.items():
            entry(name, defn.kind, all(
                capabilities.capable(defn.kind, p) for p in ("delete_line", "add_line", "edit_doc")))
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
            return replay(existing)
        row = AcWriteOperation(
            tenant_id=tenant_id, company_id=company_id, key_id=key_id, idempotency_key=idempotency_key,
            request_hash=request_hash, op=label, doc_type=kind, doc_key=doc_key, status=IN_PROGRESS,
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
        status, code = PENDING, INTERNAL_ERROR
        answer = primitive_answer(PrimitiveResult(None, OUTCOME_PENDING, INTERNAL_ERROR), doc_key)
        try:
            result = call()
            answer = primitive_answer(result, doc_key)
            status, code = result.outcome, result.error_code
        except Exception:  # noqa: BLE001 - the in_progress lock must never be stranded
            logger.exception("autocount primitive call failed (%s)", row.id)
            self.db.rollback()
        finally:
            row = self.ops.get(tenant_id, company_id, row.id) or row
            row.status, row.error_code, row.result_json = status, code, _json_safe(answer)
            self.db.commit()
        return answer

    # ── needs_attention mail (AC-57-35) ──────────────────────────────────────

    def _notify(self, company: AcCompany, row: AcWriteOperation, snap: Doc) -> None:
        base = snap["row"]
        link = snap["oldLink"]
        text = ""
        if link.get("FromDocDtlKey"):
            text = f"{link.get('FromDocType')} {link.get('FromDocNo')} row {link.get('FromDocDtlKey')}"
        event = {
            "tenantId": company.tenant_id, "operationId": row.id, "company": snap["companyName"],
            "docType": snap["kind"], "docNo": snap["docNo"], "docKey": snap["docKey"],
            "item": base.get("ItemCode"), "uom": base.get("UOM"), "qty": str(base.get("Qty")),
            "location": base.get("Location"), "link": text or "none", "op": row.op,
        }
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
        text = "\n".join([lead, "", *[f"{k}: {v}" for k, v in rows]])
        cells = "".join(
            f'<tr><td style="padding:4px 16px 4px 0;color:#6b7280">{html.escape(str(k))}</td>'
            f'<td style="padding:4px 0">{html.escape(str(v))}</td></tr>' for k, v in rows
        )
        body = (f'<div style="font-family:Arial,sans-serif;font-size:14px;color:#111827">'
                f"<p>{html.escape(lead)}</p><table>{cells}</table></div>")
        subject = _safe_subject(f"AutoCount line needs re-keying: {event['company']} {event['docNo']}")
        for address, _zone in alert_recipients(self.db, event["tenantId"], []):
            email_service.enqueue_raw(
                self.db, event["tenantId"], address, subject, body, text,
                template_key=TEMPLATE_KEY, commit=False,
            )
        self.db.commit()
