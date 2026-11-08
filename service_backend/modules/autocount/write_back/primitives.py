"""Write-back primitive service (plan 57 section 5.2, AC-57-03, 10..20).

One frame for every level-1 primitive over the kind table (QT | SO | PO | SPO):
company -> db3-guarded write connection -> capability -> busy -> document date
(AC-57-20) -> fresh GET -> stale -> pure builder + transfer guards -> commit the
``in_flight`` action row -> ONE vendor call (never retried) -> GET back -> verify
-> finish -> stage + push (SO / PO / SPO; QT is answered only).

AC-57-19: the action row records the exact call (method, path without host, body,
status, response, before / after). No AutoCount call is made while a transaction
is open (every outcome is committed as it is reached).
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.exc import IntegrityError

from modules.autocount.canonical.documents import ENTITY_PURCHASE_ORDER
from modules.autocount.models import AcCompany, AcWriteAction
from modules.autocount.repositories import CompanyRepository
from modules.autocount.write_back import capabilities, frame, payloads
from modules.autocount.write_back.client import WriteTransportError
from modules.autocount.write_back.doc_kinds import DocKind, kind_of
from modules.autocount.write_back.doc_mapping import ENTITY_BY_KIND
from modules.autocount.write_back.frame import (
    DOC_BUSY,
    DOC_KIND_MISMATCH,
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
    WriteFrame,
    _dec,
    _doc_date,
    _lines,
    _safe_body,
    _Stop,
)
from modules.autocount.write_back.payloads import (
    NEW_DOCNO,
    VendorRequest,
    WriteRefusal,
)
from modules.autocount.write_back.reader import DocReadError
from modules.autocount.write_back.repository import OUTCOME_IN_FLIGHT

logger = logging.getLogger("foundryx.autocount")

Doc = Dict[str, Any]

DOC_DATE_REQUIRED = "DOC_DATE_REQUIRED"
DOC_KIND_UNKNOWN = "DOC_KIND_UNKNOWN"
VENDOR_ERROR = "VENDOR_ERROR"
VENDOR_REFUSED = "VENDOR_REFUSED"
FIELD_IGNORED = "FIELD_IGNORED"
ANSWER_UNPARSEABLE = "ANSWER_UNPARSEABLE"
QTY_BELOW_TRANSFERRED = "QTY_BELOW_TRANSFERRED"
ROW_HAS_TRANSFERS = "ROW_HAS_TRANSFERS"
ROW_RECEIVED = "ROW_RECEIVED"
DOC_HAS_TRANSFERS = "DOC_HAS_TRANSFERS"
DOC_NOT_DELETED = "DOC_NOT_DELETED"
DOC_NOT_FOUND = "DOC_NOT_FOUND"

CREATE, EDIT, ADD_LINE = "create_doc", "edit_doc", "add_line"
DELETE_LINE, DELETE_DOC, CANCEL = "delete_line", "delete_doc", "cancel_doc"


@dataclass
class PrimitiveResult:
    """What a primitive answered; ``document`` is the read-back on ``done``."""

    action_id: Optional[str]
    outcome: str
    error_code: Optional[str] = None
    message: str = ""
    warnings: List[str] = field(default_factory=list)
    doc_key: Optional[int] = None
    doc_no: Optional[str] = None
    new_dtl_key: Optional[int] = None
    document: Optional[Doc] = None


@dataclass
class _Call:
    """What one primitive invocation carries through the frame."""

    primitive: str
    kind: str
    tenant_id: str
    doc_key: Optional[int] = None
    dtl_key: Optional[int] = None
    key_id: Optional[str] = None
    operation_id: Optional[str] = None
    step: Optional[str] = None
    doc_date: Optional[date] = None
    expected_last_modified: Optional[str] = None
    header: Optional[Dict[str, Any]] = None
    lines: Optional[Sequence[Dict[str, Any]]] = None
    header_changes: Dict[str, Any] = field(default_factory=dict)
    line_changes: Sequence[Dict[str, Any]] = ()
    line: Optional[Dict[str, Any]] = None
    stage: bool = True


# AC-57-47: what marks the start of an internal detail. The text is cut at the FIRST one:
# whatever follows is where hosts, accounts and secrets sit.
_CUT_PATTERNS = (
    re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE),  # any scheme://
    re.compile(
        r"""\b(?:addr|address|host|hostname|user\s*id|username|user|uid|password|pwd|server|"""
        r"""data\s*source|initial\s*catalog|database)\b["']?\s*[=:]""",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),  # IPv4
    re.compile(r"\b(?:token|secret|api[_-]?key)\b[\"']?\s*[=:]", re.IGNORECASE),
    re.compile(r"login failed for user|cannot open database", re.IGNORECASE),
    re.compile(r"\b[A-Za-z]:\\"),  # drive path
    re.compile(r"\\\\[A-Za-z0-9_.$-]"),  # UNC path
)
MESSAGE_CAP = 300


def redact_text(text: str, base_url: str = "") -> str:
    """The first line of ``text``, control characters removed, cut at the first
    internal detail (the cut list above, or the company's own write host) and capped."""
    text = re.sub(r"<[^>]*>", " ", text)  # an HTML error page reads as its text
    text = next((line for line in text.splitlines() if line.strip()), "")
    text = "".join(" " if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c for c in text)
    cuts = [m.start() for m in (pattern.search(text) for pattern in _CUT_PATTERNS) if m]
    host = (urlsplit(base_url).hostname or "") if base_url else ""
    if host and host.lower() in text.lower():
        cuts.append(text.lower().index(host.lower()))
    if cuts:
        text = text[: min(cuts)].rstrip() + " [redacted]"
    return " ".join(text.split())[:MESSAGE_CAP]


def vendor_message(body: Any, base_url: str = "") -> str:
    """AutoCount's own refusal text, safe to show: ``ExceptionMessage`` (else a
    non-generic ``Message``), never the stack or exception type, redacted (``redact_text``)."""
    text = ""
    if isinstance(body, dict):
        text = str(body.get("ExceptionMessage") or "")
        if not text.strip() and body.get("Message") != _GENERIC:
            text = str(body.get("Message") or "")
    elif isinstance(body, str):
        text = body
    return redact_text(text, base_url)


_GENERIC = "An error has occurred."


def is_business_refusal(status: int, body: Any) -> bool:
    """AutoCount said no with a reason (a credit limit, a transferred quantity, a
    received line): a JSON error carrying ``ExceptionMessage`` / ``Message``, or a
    plain-text 4xx. A bare 5xx or an empty answer is a vendor fault instead."""
    if isinstance(body, dict):
        message = str(body.get("ExceptionMessage") or "")
        if not message:
            message = "" if body.get("Message") == _GENERIC else str(body.get("Message") or "")
        return bool(message.strip())
    return isinstance(body, str) and 400 <= status < 500 and bool(body.strip())


class PrimitiveService(WriteFrame):
    # ── public primitives ────────────────────────────────────────────────────

    def create_doc(
        self, *, tenant_id: str, company_id: str, kind: str, header: Dict[str, Any],
        lines: Sequence[Dict[str, Any]], key_id: Optional[str] = None,
        operation_id: Optional[str] = None, step: Optional[str] = None,
    ) -> PrimitiveResult:
        call = _Call(CREATE, kind, tenant_id, key_id=key_id, operation_id=operation_id, step=step,
                     header=header, lines=lines)
        return self._run(call, company_id)

    def edit_doc(
        self, *, tenant_id: str, company_id: str, kind: str, doc_key: int,
        header_changes: Dict[str, Any], line_changes: Sequence[Dict[str, Any]],
        doc_date: Optional[date] = None, expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None, operation_id: Optional[str] = None, step: Optional[str] = None,
        stage: bool = True,
    ) -> PrimitiveResult:
        call = _Call(EDIT, kind, tenant_id, doc_key=doc_key, key_id=key_id, operation_id=operation_id,
                     step=step, doc_date=doc_date, expected_last_modified=expected_last_modified,
                     header_changes=header_changes, line_changes=line_changes, stage=stage)
        return self._run(call, company_id)

    def add_line(
        self, *, tenant_id: str, company_id: str, kind: str, doc_key: int, line: Dict[str, Any],
        doc_date: Optional[date] = None, expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None, operation_id: Optional[str] = None, step: Optional[str] = None,
        stage: bool = True,
    ) -> PrimitiveResult:
        call = _Call(ADD_LINE, kind, tenant_id, doc_key=doc_key, key_id=key_id, operation_id=operation_id,
                     step=step, doc_date=doc_date, expected_last_modified=expected_last_modified, line=line, stage=stage)
        return self._run(call, company_id)

    def delete_line(
        self, *, tenant_id: str, company_id: str, kind: str, doc_key: int, dtl_key: int,
        doc_date: Optional[date] = None, expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None, operation_id: Optional[str] = None, step: Optional[str] = None,
        stage: bool = True,
    ) -> PrimitiveResult:
        call = _Call(DELETE_LINE, kind, tenant_id, doc_key=doc_key, dtl_key=dtl_key, key_id=key_id,
                     operation_id=operation_id, step=step, doc_date=doc_date,
                     expected_last_modified=expected_last_modified, stage=stage)
        return self._run(call, company_id)

    def delete_doc(
        self, *, tenant_id: str, company_id: str, kind: str, doc_key: int,
        doc_date: Optional[date] = None, expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None, operation_id: Optional[str] = None, step: Optional[str] = None,
    ) -> PrimitiveResult:
        call = _Call(DELETE_DOC, kind, tenant_id, doc_key=doc_key, key_id=key_id,
                     operation_id=operation_id, step=step, doc_date=doc_date,
                     expected_last_modified=expected_last_modified)
        return self._run(call, company_id)

    def cancel_doc(
        self, *, tenant_id: str, company_id: str, kind: str, doc_key: int,
        doc_date: Optional[date] = None, expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None, operation_id: Optional[str] = None, step: Optional[str] = None,
    ) -> PrimitiveResult:
        call = _Call(CANCEL, kind, tenant_id, doc_key=doc_key, key_id=key_id,
                     operation_id=operation_id, step=step, doc_date=doc_date,
                     expected_last_modified=expected_last_modified)
        return self._run(call, company_id)

    # ── frame ────────────────────────────────────────────────────────────────

    def _run(self, call: _Call, company_id: str) -> PrimitiveResult:
        company = CompanyRepository(self.db).get(call.tenant_id, company_id)
        if company is None:
            return self._wrap(WriteActionResult(None, OUTCOME_REFUSED, WRITE_DISABLED))
        row = self._new_row(call, company.id)
        self._deadline = time.monotonic() + frame.ACTION_DEADLINE_SECONDS
        self._put_sent = False
        extra: Dict[str, Any] = {}
        try:
            try:
                kind = kind_of(call.kind)
            except ValueError:
                raise self._refuse(row, DOC_KIND_UNKNOWN) from None
            base_url = self._write_base_url(row, company)
            self._check_test_company(row, company)
            if not capabilities.capable(call.kind, call.primitive):
                raise self._refuse(row, VENDOR_UNSUPPORTED)
            reader = self._reader_factory(base_url)
            doc, request, read_date = self._prepare(call, kind, company, row, reader)
            row.before_json = doc
            row.request_method, row.request_path, row.request_json = request.method, request.path, request.body
            row.outcome = OUTCOME_IN_FLIGHT
            try:
                self.db.commit()  # in_flight + the exact body committed before the call
            except IntegrityError:
                self.db.rollback()
                busy = self._new_row(call, company.id)
                return self._wrap(self._finish(busy, OUTCOME_REFUSED, DOC_BUSY))
            return self._send(call, kind, company, base_url, row, reader, doc, request, read_date, extra)
        except _Stop as stop:
            return self._wrap(stop.result, **extra)
        except Exception:  # noqa: BLE001 - the in_flight row must never be stranded
            logger.exception("autocount primitive failed (action %s)", row.id)
            self.db.rollback()
            outcome = OUTCOME_PENDING if self._put_sent else OUTCOME_REFUSED
            return self._wrap(self._finish(row, outcome, INTERNAL_ERROR))
        finally:
            self.db.rollback()

    def _new_row(self, call: _Call, company_id: str) -> AcWriteAction:
        return self.actions.add(
            AcWriteAction(
                tenant_id=call.tenant_id, company_id=company_id, action=call.primitive,
                doc_type=str(call.kind)[:16], doc_key=call.doc_key, dtl_key=call.dtl_key,
                outcome=OUTCOME_REFUSED, key_id=call.key_id, operation_id=call.operation_id,
                step=call.step, created_at=datetime.now(timezone.utc),  # step order = time order
            )
        )

    @staticmethod
    def _wrap(result: WriteActionResult, **extra: Any) -> PrimitiveResult:
        return PrimitiveResult(
            result.action_id, result.outcome, result.error_code, result.message,
            document=result.document, **extra,
        )

    def _prepare(
        self, call: _Call, kind: DocKind, company: AcCompany, row: AcWriteAction, reader: Any
    ) -> "tuple[Optional[Doc], VendorRequest, Optional[date]]":
        """Everything before the vendor call: the pure build for a create, else
        busy -> date -> fresh GET -> stale -> build -> transfer guards."""
        if call.primitive == CREATE:
            header = dict(call.header or {})
            try:
                needs_term = payloads.create_needs_debtor_term(call.kind, header, call.lines)
            except WriteRefusal as exc:
                raise self._refuse(row, exc.code, str(exc)) from None
            if needs_term:
                header["DisplayTerm"] = self._debtor_term(row, reader, header.get("DebtorCode"))
                call.header = header
            try:
                request = payloads.build_create(call.kind, header, call.lines)
            except WriteRefusal as exc:
                raise self._refuse(row, exc.code, str(exc)) from None
            return None, request, _doc_date(request.body)
        assert call.doc_key is not None
        if call.primitive == EDIT:  # value checks need no document: no request on a bad number
            try:
                payloads.check_edit_values(call.line_changes)
            except WriteRefusal as exc:
                raise self._refuse(row, exc.code, str(exc)) from None
        if call.operation_id is None:  # an operation holds its own cross-step lock
            self._check_not_busy(row, call.tenant_id, company.id, call.doc_key)
        doc_date = self._resolve_date(call, kind, company, row)
        self._check_deadline(row)
        self.db.commit()  # no transaction open during the GET
        try:
            doc = reader.get_document(call.kind, call.doc_key, doc_date)
        except DocReadError as exc:
            raise self._refuse(row, exc.code) from None
        if call.expected_last_modified and doc.get("LastModified") != call.expected_last_modified:
            raise self._refuse(row, DOC_STALE)
        try:
            request = self._build(call, doc)
            self._guard_transfers(call, company, doc)  # every other refusal before a debtor read
        except WriteRefusal as exc:
            raise self._refuse(row, exc.code, str(exc)) from None
        if call.primitive == EDIT and payloads.edit_needs_debtor_term(call.kind, doc, call.header_changes):
            term = self._debtor_term(row, reader, doc.get("DebtorCode"))
            call.header_changes = {**call.header_changes, "DisplayTerm": term}
            try:
                request = self._build(call, doc)
            except WriteRefusal as exc:
                raise self._refuse(row, exc.code, str(exc)) from None
        return doc, request, doc_date  # type: ignore[return-value]

    def _debtor_term(self, row: AcWriteAction, reader: Any, debtor_code: Any) -> str:
        """SS-QTSO-DISPLAYTERM: the debtor's own AutoCount term code, read from the
        same book. ``DEBTOR_TERM_MISSING`` (naming the debtor) when the debtor has no
        term or is unknown to the book; ``READ_FAILED`` when the read fails. No write
        is ever sent on either refusal."""
        code = str(debtor_code or "").strip()
        if not code:
            raise self._refuse(row, payloads.DEBTOR_TERM_MISSING, "debtor has no code")
        self._check_deadline(row)
        self.db.commit()  # no transaction open during the GET
        try:
            found, term = reader.debtor_term(code, before_page=lambda: self._check_deadline(row))
        except DocReadError as exc:
            raise self._refuse(row, exc.code) from None
        if not found:
            raise self._refuse(row, payloads.DEBTOR_TERM_MISSING,
                               f"debtor {code} not found in AutoCount; send displayTerm")
        if term is None:
            raise self._refuse(row, payloads.DEBTOR_TERM_MISSING,
                               f"debtor {code} has no credit term in AutoCount; send displayTerm")
        return term

    @staticmethod
    def _build(call: _Call, doc: Doc) -> VendorRequest:
        if call.primitive == EDIT:
            return payloads.build_edit(call.kind, doc, call.header_changes, call.line_changes)
        if call.primitive == ADD_LINE:
            return payloads.build_add_line(call.kind, doc, call.line or {})
        if call.primitive == DELETE_LINE:
            return payloads.build_delete_line(call.kind, doc, int(call.dtl_key or 0))
        if call.primitive == DELETE_DOC:
            return payloads.build_delete_doc(call.kind, doc)
        return payloads.build_cancel(call.kind, doc)

    def find_date(
        self, company: AcCompany, kind_name: str, doc_key: int, doc_date: Optional[date] = None
    ) -> "tuple[Optional[date], str]":
        """AC-57-20: ``(date, "")`` from the caller, else the staged DocDate, else
        our last confirmed read-back's; ``(None, code)`` when none is known."""
        if doc_date is not None:
            return doc_date, ""
        ref = f"{company.database_name}:{doc_key}"
        entity = ENTITY_BY_KIND.get(kind_name)
        staged = self.staged.newest(company.tenant_id, company.id, entity, ref) if entity else None
        found = _doc_date(staged.raw_json if staged else None)
        if found is None:
            found = _doc_date(
                self.actions.last_confirmed_after(company.tenant_id, company.id, kind_name, doc_key)
            )
        if found is not None:
            return found, ""
        other = {"PO": "SPO", "SPO": "PO"}.get(kind_name)
        if other and self.staged.newest(company.tenant_id, company.id, ENTITY_BY_KIND[other], ref):
            return None, DOC_KIND_MISMATCH
        return None, DOC_DATE_REQUIRED

    def _resolve_date(
        self, call: _Call, kind: DocKind, company: AcCompany, row: AcWriteAction
    ) -> date:
        found, code = self.find_date(company, kind.name, int(call.doc_key or 0), call.doc_date)
        if found is None:
            raise self._refuse(row, code)
        return found

    # ── transfer guards (AC-57-18) ───────────────────────────────────────────

    def _so_linked_qty(
        self, company: AcCompany, so_dtl_key: int, fresh_po: Optional[Doc] = None
    ) -> Decimal:
        """Qty of one SO row already covered by non-cancelled PO rows: the staged
        copies, with ``fresh_po`` (when given) standing in for its own staged copy."""
        total = Decimal(0)
        own_ref = f"{company.database_name}:{fresh_po.get('DocKey')}" if fresh_po else None
        sources: List[List[Doc]] = [list(fresh_po.get("Details") or [])] if fresh_po else []
        for staged in self.staged.for_entity(company.tenant_id, company.id, ENTITY_PURCHASE_ORDER):
            raw = staged.raw_json or {}
            if raw.get("Cancelled") != "T" and staged.source_ref != own_ref:
                sources.append(_lines(raw))
        for lines in sources:
            total += sum(
                (_dec(r.get("Qty")) for r in lines if r.get("FromSODtlKey") == so_dtl_key), Decimal(0)
            )
        return total

    def _guard_transfers(self, call: _Call, company: AcCompany, doc: Doc) -> None:
        if call.kind != "SO":
            return
        if call.primitive == EDIT:
            for change in call.line_changes:
                if "Qty" in change and _dec(change["Qty"]) < self._so_linked_qty(company, change["DtlKey"]):
                    raise WriteRefusal(QTY_BELOW_TRANSFERRED, "quantity below the linked quantity")
        elif call.primitive == DELETE_LINE:
            if self._so_linked_qty(company, int(call.dtl_key or 0)) > 0:
                raise WriteRefusal(ROW_HAS_TRANSFERS, "row is linked by purchase order lines")
            row = next((r for r in doc.get("Details") or [] if r.get("DtlKey") == call.dtl_key), {})
            delivered = self._row_received(company, "SO", dict(row, DocKey=doc.get("DocKey")))
            if delivered is not None and delivered > 0:  # unknown is left to AutoCount
                raise WriteRefusal(ROW_RECEIVED, "row has delivered quantity")
        elif call.primitive == CANCEL:
            if any(self._so_linked_qty(company, r.get("DtlKey")) > 0 for r in doc.get("Details") or []):
                raise WriteRefusal(DOC_HAS_TRANSFERS, "lines are linked by purchase order lines")

    # ── the call, read-back, verify ──────────────────────────────────────────

    def _send(
        self, call: _Call, kind: DocKind, company: AcCompany, base_url: str, row: AcWriteAction,
        reader: Any, before: Optional[Doc], request: VendorRequest, read_date: Optional[date],
        extra: Dict[str, Any],
    ) -> PrimitiveResult:
        client = self._client_factory(base_url)
        self._check_deadline(row)
        self._put_sent = True
        try:  # never retried
            if request.method == "POST":
                response = client.post(request.path, request.body)
            elif request.method == "DELETE":
                response = client.delete(request.path, request.body)
            else:
                response = client.put(request.path, request.body)
        except WriteTransportError as exc:
            return self._wrap(self._finish(row, OUTCOME_PENDING, exc.code))
        row.response_status = response.status_code
        if response.ok:
            row.response_json = _safe_body(response.body)
        if not response.ok:
            if is_business_refusal(response.status_code, response.body):
                message = vendor_message(response.body, base_url)
                row.response_json = {"message": message}  # the same safe text, never the stack
                return self._wrap(self._finish(row, OUTCOME_VENDOR_ERROR, VENDOR_REFUSED, message=message))
            # a bare failure (an IIS page, a stack): the status and redacted text only (AC-57-47)
            row.response_json = {"text": vendor_message(response.body, base_url)}
            return self._wrap(self._finish(row, OUTCOME_VENDOR_ERROR, VENDOR_ERROR))
        self.db.commit()
        self._check_deadline(row)
        try:
            after = self._read_back(call, reader, response.body, request, before, read_date, row)
        except DocReadError as exc:
            if call.primitive == DELETE_DOC and exc.code == DOC_NOT_FOUND:
                return self._wrap(self._finish(row, OUTCOME_DONE))
            return self._wrap(self._finish(row, OUTCOME_PENDING, exc.code))
        row.after_json = after  # a read-back in hand is always verified
        verdict_code, message, warnings, new_key = self._verify(call, request, before, after)
        extra.update(doc_key=after.get("DocKey"), doc_no=after.get("DocNo"), new_dtl_key=new_key)
        if verdict_code:
            extra["warnings"] = warnings
            return self._wrap(self._finish(row, OUTCOME_MISMATCH, verdict_code, message=message), **extra)
        extra["warnings"] = warnings
        if call.primitive == CREATE:
            row.doc_key = after.get("DocKey")
        result = self._finish(row, OUTCOME_DONE, document=after, message=message)
        if call.kind != "QT" and call.stage:
            self._stage(company, call.kind, after)
        return self._wrap(result, **extra)

    def _read_back(
        self, call: _Call, reader: Any, answer: Any, request: VendorRequest,
        before: Optional[Doc], read_date: Optional[date], row: AcWriteAction,
    ) -> Doc:
        """The document as it reads now; a ``DocReadError`` (or a pending answer
        for an unparseable create) when it cannot be told."""
        if read_date is None:
            raise DocReadError("READ_FAILED")
        if call.primitive != CREATE:
            return reader.get_document(call.kind, int(call.doc_key or 0), read_date)
        parsed = payloads.parse_create_answer(answer)
        if parsed is not None:
            return reader.get_document(call.kind, parsed[1], read_date)
        sent_no = request.body.get("DocNo")
        if not sent_no or sent_no == NEW_DOCNO:
            raise DocReadError(ANSWER_UNPARSEABLE)
        return reader.find_by_doc_no(call.kind, str(sent_no), read_date)

    @staticmethod
    def _verify(call: _Call, request: VendorRequest, before: Optional[Doc], after: Doc):
        """``(mismatch code | None, message, warnings, new DtlKey | None)``."""
        if call.primitive == CREATE:
            v = payloads.verify_create(call.kind, {"Details": request.body.get("Details")}, after)
            return (v.code if v.outcome != payloads.DONE else None), v.message, list(v.warnings), None
        assert before is not None
        if call.primitive == EDIT:
            ignored = payloads.verify_edit(call.kind, before, call.header_changes, call.line_changes, after)
            if ignored:
                return FIELD_IGNORED, "ignored: " + ", ".join(ignored), ignored, None
            return None, "", [], None
        if call.primitive == ADD_LINE:
            v = payloads.verify_add_line(call.kind, before, call.line or {}, after)
            known = {r.get("DtlKey") for r in before.get("Details") or []}
            added = [r.get("DtlKey") for r in after.get("Details") or [] if r.get("DtlKey") not in known]
            ok = v.outcome == payloads.DONE
            return (None if ok else v.code), "", [], (added[0] if ok and added else None)
        if call.primitive == DELETE_LINE:
            v = payloads.verify_delete_line(call.kind, before, int(call.dtl_key or 0), after)
        elif call.primitive == DELETE_DOC:
            return DOC_NOT_DELETED, "", [], None  # the document still reads back
        else:
            v = payloads.verify_cancel(call.kind, after)
        return (v.code if v.outcome != payloads.DONE else None), "", [], None
