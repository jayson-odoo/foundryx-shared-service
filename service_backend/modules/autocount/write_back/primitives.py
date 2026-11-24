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

import copy
from contextlib import contextmanager
import logging
import re
import time
import unicodedata
from urllib.parse import urlsplit
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from sqlalchemy.exc import IntegrityError

from modules.autocount.canonical.documents import ENTITY_PURCHASE_ORDER
from modules.autocount.models import AcCompany, AcWriteAction
from modules.autocount.repositories import CompanyRepository
from modules.autocount.write_back import capabilities, frame, guard, payloads
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
from modules.autocount.write_back.repository import OUTCOME_IN_FLIGHT, OperationRepository, PoSoLinkRepository

logger = logging.getLogger("foundryx.autocount")

Doc = Dict[str, Any]

DOC_DATE_REQUIRED = "DOC_DATE_REQUIRED"
DOC_KIND_UNKNOWN = "DOC_KIND_UNKNOWN"
VENDOR_ERROR = "VENDOR_ERROR"
VENDOR_REFUSED = "VENDOR_REFUSED"
# PO-LINK-STUCK-RECONCILE-B (prod 19/20 Nov): AutoCount's own SQL command timeout. The write may still commit
# AFTER hapi answered (it did on 20 Nov), so it is an UNKNOWN outcome, never a refusal, until a read shows it.
VENDOR_TIMEOUT = "VENDOR_TIMEOUT"
VENDOR_TIMEOUT_MESSAGE = ("AutoCount timed out while saving this change. It may still be saved: it is being "
                          "checked in AutoCount before anything is sent again.")
# A command timeout reads "Timeout expired" (SqlException -2) or "The wait operation timed out" (Win32 258). A
# lock wait ("Lock request time out period exceeded", SQL 1222) rolls the statement back: a real refusal (AC-69-11).
_TIMEOUT_TEXT = re.compile(r"timeout expired|wait operation timed out", re.IGNORECASE)
FIELD_IGNORED = "FIELD_IGNORED"
ANSWER_UNPARSEABLE = "ANSWER_UNPARSEABLE"
QTY_BELOW_TRANSFERRED = "QTY_BELOW_TRANSFERRED"
ROW_HAS_TRANSFERS = "ROW_HAS_TRANSFERS"
ROW_RECEIVED = "ROW_RECEIVED"
NOT_APPLIED = "OPERATION_NOT_APPLIED"  # = operations.NOT_APPLIED (operations imports this module)
LOOKUP_FAILED = "LOOKUP_FAILED"
LOOKUP_FAILED_MESSAGE = "AutoCount could not be reached to check this change. Please try again shortly."
NOT_YET_CONFIRMED_MESSAGE = "AutoCount has not confirmed this change yet. Please try again in a couple of minutes."
DOC_HAS_TRANSFERS = "DOC_HAS_TRANSFERS"
DOC_CANCELLED = "DOC_CANCELLED"
DOC_NOT_FOUND = "DOC_NOT_FOUND"
ROW_NEEDS_ATTENTION = "ROW_NEEDS_ATTENTION"  # plan 65 D6: an unresolved link operation covers the row

CREATE, EDIT, ADD_LINE = "create_doc", "edit_doc", "add_line"
DELETE_LINE, DELETE_DOC, CANCEL = "delete_line", "delete_doc", "cancel_doc"
# Plan 61: one PUT deleting a row ("D") and adding its replacement (DtlKey 0). Not a
# gateway primitive: the row operations use it; it needs delete_line AND add_line on.
REPLACE_LINE = "replace_line"
_REPLACE_NEEDS = (DELETE_LINE, ADD_LINE)
# Plan 62: ONE PUT linking one row to N source rows (the row "D" or kept with the rest, N new
# linked rows). Not a gateway primitive: the ``link_batch`` operation uses it.
BATCH_LINK = "batch_link"
# Plan 62 D7: ONE PUT unlinking a row into a free row (the row "D", the free row raised).
UNLINK_MERGE = "unlink_merge"
# F7: AutoCount refuses a "D" on a row transferred onward with this exception type.
_TRANSFERRED_ROW = re.compile(r"UnableToDelete\w*TransferredItemException")


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
    vendor_class: Optional[str] = None  # the vendor's exception class name (no message, no stack), on a vendor_error


def vendor_class_of(body: Any) -> Optional[str]:
    """The short exception class AutoCount named in an error answer (``ViolateCreditLimit...``), else None."""
    if isinstance(body, dict):
        kind = str(body.get("ExceptionType") or "").strip()
        return kind.rsplit(".", 1)[-1][:120] or None if kind else None
    return None


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
    doc_no: Optional[str] = None
    merge_key: Optional[int] = None  # unlink_merge: the free row that takes the quantity
    # plan 69 D1: batch_link over several rows of ONE document: ((row DtlKey, [new rows]), ...)
    groups: Optional[Sequence[Tuple[int, Sequence[Dict[str, Any]]]]] = None
    # SS-AUTOCOUNT-SPEEDUP: the document as the previous step of the SAME operation just read
    # it back (no vendor call since). It stands in for the fresh GET; None = read it.
    fresh_doc: Optional[Dict[str, Any]] = None
    # plan 65 D4: an operation's restore of a new SO-linked row (``payloads.RESTORE_LINE_KEYS``)
    restore: bool = False


def _no_note(line: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Plan 66: a line from outside an operation never carries the link note; plan 73: nor a Further
    Description of its own (the builders copy that from the row as read)."""
    drop = (payloads.LINK_NOTE_KEY, payloads.FURTHER_DESC)
    if not line or not any(k in line for k in drop):
        return line
    return {k: v for k, v in line.items() if k not in drop}


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


def is_vendor_timeout(message: str, vendor_class: Optional[str] = None) -> bool:
    """AutoCount answered that its SQL command timed out (``CriticalSqlException`` / ``SqlException``
    "Timeout expired", "The wait operation timed out"): the save may have landed later. Judged on AutoCount's
    own (redacted) message, never on the HTTP status."""
    if vendor_class and "sql" not in vendor_class.lower():  # a business exception quoting the words is no timeout
        return False
    return bool(_TIMEOUT_TEXT.search(message or ""))


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


def _groups_of(call: "_Call") -> List[Tuple[int, Sequence[Dict[str, Any]]]]:
    """The rows a batch link changes: ``groups`` (plan 69), else the one row and its lines (plan 62)."""
    if call.groups is not None:
        return [(int(k), v) for k, v in call.groups]
    return [(int(call.dtl_key or 0), call.lines or [])]


def _unchanged(before: Doc, after: Doc) -> bool:
    """The document reads back exactly as before the PUT (its stamp and every row)."""
    return (before.get("LastModified") == after.get("LastModified")
            and _rows_as_read(before) == _rows_as_read(after))


def _rows_as_read(doc: Doc) -> List[Doc]:
    """The rows without the keys no read returns reliably (the Further Description comes from a second source that may
    answer on one read and not the next: plan 73 G1)."""
    return [{k: v for k, v in r.items() if k not in payloads.UNREADABLE_ROW_KEYS} for r in doc.get("Details") or []]


def _vendor_refusal(primitive: str, status: int, body: Any) -> Optional[str]:
    """Plan 61 answer mapping: a "D" AutoCount refuses because the row was transferred
    onward (F7) is ``ROW_HAS_TRANSFERS``; a cancel refused because the document was
    transferred (F11) is ``DOC_HAS_TRANSFERS``, because it is void already (F10)
    ``DOC_CANCELLED``. None = the general mapping."""
    if primitive in (DELETE_LINE, REPLACE_LINE) and isinstance(body, dict):
        if _TRANSFERRED_ROW.search(str(body.get("ExceptionType") or "")):
            return ROW_HAS_TRANSFERS
    if primitive == CANCEL and 400 <= status < 500:
        text = vendor_message(body)
        if "transfered" in text.lower() or "transferred" in text.lower():
            return DOC_HAS_TRANSFERS
        if "(void)" in text.lower():
            return DOC_CANCELLED
    return None


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
        stage: bool = True, fresh_doc: Optional[Doc] = None, restore: bool = False,
    ) -> PrimitiveResult:
        """``fresh_doc`` (operations only): the operation's own read-back of this document,
        taken with no vendor call since, used instead of a second identical GET. ``restore``
        (operations only, plan 65 D4): the restore of a new SO-linked row, which may also send
        the note; never set by the public edit door."""
        call = _Call(EDIT, kind, tenant_id, doc_key=doc_key, key_id=key_id, operation_id=operation_id,
                     step=step, doc_date=doc_date, expected_last_modified=expected_last_modified,
                     header_changes=header_changes, line_changes=line_changes, stage=stage,
                     fresh_doc=fresh_doc, restore=restore and operation_id is not None)
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

    def replace_line(
        self, *, tenant_id: str, company_id: str, kind: str, doc_key: int, dtl_key: int,
        line: Dict[str, Any], doc_date: Optional[date] = None, expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None, operation_id: Optional[str] = None, step: Optional[str] = None,
        stage: bool = True,
    ) -> PrimitiveResult:
        """Plan 61 section 4.1: ONE PUT ``[row dtl_key "D", line as a new row]``; done =
        the old row gone and exactly one new row read back (``new_dtl_key``)."""
        call = _Call(REPLACE_LINE, kind, tenant_id, doc_key=doc_key, dtl_key=dtl_key, key_id=key_id,
                     operation_id=operation_id, step=step, doc_date=doc_date,
                     expected_last_modified=expected_last_modified, line=line, stage=stage)
        return self._run(call, company_id)

    def batch_link(
        self, *, tenant_id: str, company_id: str, kind: str, doc_key: int, dtl_key: int,
        lines: Sequence[Dict[str, Any]], doc_date: Optional[date] = None,
        expected_last_modified: Optional[str] = None, key_id: Optional[str] = None,
        operation_id: Optional[str] = None, step: Optional[str] = None, stage: bool = True,
        groups: Optional[Sequence[Tuple[int, Sequence[Dict[str, Any]]]]] = None,
    ) -> PrimitiveResult:
        """Plan 62 D3: ONE PUT ``[row dtl_key "D" or cut to the rest, one new linked row per
        line]``; done = every new row read back with its link and quantity. Plan 69 D1: ``groups``
        = several rows of the same document in the same ONE PUT (``dtl_key`` / ``lines`` = the first)."""
        call = _Call(BATCH_LINK, kind, tenant_id, doc_key=doc_key, dtl_key=dtl_key, key_id=key_id,
                     operation_id=operation_id, step=step, doc_date=doc_date,
                     expected_last_modified=expected_last_modified, lines=lines, stage=stage,
                     groups=None if groups is None else [(int(k), list(v)) for k, v in groups])
        return self._run(call, company_id)

    def unlink_merge(
        self, *, tenant_id: str, company_id: str, kind: str, doc_key: int, dtl_key: int, merge_key: int,
        doc_date: Optional[date] = None, expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None, operation_id: Optional[str] = None, step: Optional[str] = None,
        stage: bool = True,
    ) -> PrimitiveResult:
        """Plan 62 D7: ONE PUT ``[row dtl_key "D", free row merge_key raised by its quantity]``."""
        call = _Call(UNLINK_MERGE, kind, tenant_id, doc_key=doc_key, dtl_key=dtl_key, key_id=key_id,
                     operation_id=operation_id, step=step, doc_date=doc_date,
                     expected_last_modified=expected_last_modified, stage=stage, merge_key=merge_key)
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
        if self._lookup_action is not None:  # a same-key resend of an unknown outcome: read, never write
            return self._look_up(call, company, self._lookup_action)
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
            if not self._capable(call):
                raise self._refuse(row, VENDOR_UNSUPPORTED)
            self._call_log = self.new_call_log(
                company, kind=call.kind, doc_key=call.doc_key, key_id=call.key_id,
                operation_id=call.operation_id, action_id=row.id,
            )
            reader = self._reader_for(base_url)
            doc, request, read_date = self._prepare(call, kind, company, row, reader)
            row.before_json = doc
            row.request_method, row.request_path = request.method, request.path
            row.request_json = request.body if request.params is None else {"query": dict(request.params)}
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

    @contextmanager
    def looking_up(self, action: AcWriteAction, operation_id: Optional[str], *, trust_absent: bool) -> Iterator[None]:
        """Inside: the next primitive call looks ``action``'s unknown outcome up (``_look_up``) instead of
        writing; its GET is logged under ``operation_id``. ``trust_absent``: the write is old enough that a
        change not found is not coming (else the answer stays pending: a timed-out PUT may still land)."""
        self._lookup_action, self._owner_operation_id, self._trust_absent = action, operation_id, trust_absent
        try:
            yield
        finally:
            self._lookup_action, self._owner_operation_id, self._trust_absent = None, None, False

    @contextmanager
    def under_operation(self, operation_id: Optional[str]) -> Iterator[None]:
        """Inside: action rows and GETs carry ``operation_id`` (the single-document operation row)."""
        self._owner_operation_id = operation_id
        try:
            yield
        finally:
            self._owner_operation_id = None

    def _look_up(self, call: _Call, company: AcCompany, action: AcWriteAction) -> PrimitiveResult:
        """AUTOCOUNT-STRANDED-OPS-B / owner rule: an unknown outcome is checked before a retry. ONE logged GET of
        the document, judged by ``payloads.change_landed`` against the action's stored before-image (only THIS
        change, never the rest of the document, which another person may have edited since):
        ``done`` (the change is in AutoCount: the action is settled done), ``refused`` / ``OPERATION_NOT_APPLIED``
        (it is not: the action is settled so it no longer holds the document, and the caller runs fresh) or
        ``pending_verification`` (the document could not be read: nothing is decided)."""
        unread = PrimitiveResult(action.id, OUTCOME_PENDING, LOOKUP_FAILED, LOOKUP_FAILED_MESSAGE,
                                 doc_key=call.doc_key)
        before = action.before_json if isinstance(action.before_json, dict) else None
        base_url, _refusal = self._resolve_write_base_url(company)
        if before is None or base_url is None:
            return unread
        self._call_log = self.new_call_log(
            company, kind=call.kind, doc_key=call.doc_key, doc_no=before.get("DocNo"), key_id=call.key_id,
            operation_id=action.operation_id, action_id=action.id,
        )
        read_date = _doc_date(before) or self.find_date(company, call.kind, int(call.doc_key or 0), call.doc_date)[0]
        if read_date is None:
            return unread
        self.db.commit()  # no transaction open during the GET
        try:
            after = self._reader_for(base_url).get_document(
                call.kind, int(call.doc_key or 0), read_date, doc_no=before.get("DocNo"))
        except DocReadError:
            return unread
        try:
            landed, new_key = payloads.change_landed(
                call.kind, call.primitive, before, after, header_changes=call.header_changes,
                line_changes=call.line_changes, line=_no_note(call.line), dtl_key=call.dtl_key)
        except Exception:  # noqa: BLE001 - a check that cannot judge decides nothing
            logger.exception("autocount look-up could not judge action %s", action.id)
            return unread
        if landed:
            action.outcome, action.error_code, action.after_json = OUTCOME_DONE, None, after
            self.db.commit()
            if call.kind != "QT" and call.stage:
                self._stage(company, call.kind, after)  # as the write's own done path does
            return PrimitiveResult(action.id, OUTCOME_DONE, None, "The change was found in AutoCount.",
                                   [], after.get("DocKey"), after.get("DocNo"), new_key, after)
        if not self._trust_absent:
            return PrimitiveResult(action.id, OUTCOME_PENDING, LOOKUP_FAILED, NOT_YET_CONFIRMED_MESSAGE,
                                   doc_key=call.doc_key)
        action.outcome, action.error_code = OUTCOME_REFUSED, NOT_APPLIED  # settled: no longer holds the document
        self.db.commit()
        return PrimitiveResult(action.id, OUTCOME_REFUSED, NOT_APPLIED,
                               "Nothing was changed in AutoCount. Please try again.", doc_key=call.doc_key)

    @staticmethod
    def _capable(call: _Call) -> bool:
        if call.primitive in (REPLACE_LINE, BATCH_LINK, UNLINK_MERGE):
            return all(capabilities.capable(call.kind, p) for p in _REPLACE_NEEDS)
        return capabilities.capable(call.kind, call.primitive)

    def read_doc(
        self, *, tenant_id: str, company_id: str, kind: str, doc_key: int, doc_date: Optional[date] = None,
    ) -> PrimitiveResult:
        """B6: the document as AutoCount holds it now (the read a CRM update needs for
        ``LastModified`` and the row keys). The same gates as a write (company of this
        tenant, write connection + db3 guard, test company, kind, date), no action row,
        no write, nothing staged. ``refused`` with a code when a gate or the GET fails."""
        company = CompanyRepository(self.db).get(tenant_id, company_id)
        if company is None:
            return PrimitiveResult(None, frame.OUTCOME_REFUSED, WRITE_DISABLED)
        try:
            kind_def = kind_of(kind)
        except ValueError:
            return PrimitiveResult(None, frame.OUTCOME_REFUSED, DOC_KIND_UNKNOWN)
        base_url, refusal = self._resolve_write_base_url(company)
        if base_url is None:
            return PrimitiveResult(None, frame.OUTCOME_REFUSED, refusal[0])  # type: ignore[index]
        try:
            guard.assert_test_company(self.db, company.tenant_id, company.id, book=guard.book_of(base_url))
        except guard.WriteConnectionError as exc:
            return PrimitiveResult(None, frame.OUTCOME_REFUSED, exc.code)
        found, code = self.find_date(company, kind_def.name, doc_key, doc_date)
        if found is None:
            return PrimitiveResult(None, frame.OUTCOME_REFUSED, code)
        doc_no = self.find_doc_no(company, kind_def.name, doc_key)
        log = self.new_call_log(company, kind=kind_def.name, doc_key=doc_key, doc_no=doc_no)
        self.db.commit()  # no transaction open during the GET
        try:
            doc = self._reader_for(base_url, log).get_document(kind_def.name, doc_key, found, doc_no=doc_no)
        except DocReadError as exc:
            return PrimitiveResult(None, frame.OUTCOME_REFUSED, exc.code)
        finally:
            self.db.rollback()
        try:
            payloads._check_kind_doc(kind_def, doc, cancelled_ok=True, write=False)
        except WriteRefusal as exc:
            return PrimitiveResult(None, frame.OUTCOME_REFUSED, exc.code)
        return PrimitiveResult(
            None, frame.OUTCOME_DONE, doc_key=doc.get("DocKey"), doc_no=doc.get("DocNo"), document=doc,
        )

    def _new_row(self, call: _Call, company_id: str) -> AcWriteAction:
        return self.actions.add(
            AcWriteAction(
                tenant_id=call.tenant_id, company_id=company_id, action=call.primitive,
                doc_type=str(call.kind)[:16], doc_key=call.doc_key, dtl_key=call.dtl_key,
                outcome=OUTCOME_REFUSED, key_id=call.key_id, operation_id=call.operation_id or self._owner_operation_id,
                step=call.step, created_at=datetime.now(timezone.utc),  # step order = time order
                **self._trace_columns(),
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
            sent_no = (request.body or {}).get("DocNo")
            self._log_doc(None if sent_no == NEW_DOCNO else sent_no)
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
        call.doc_no = call.doc_no or self.find_doc_no(company, kind.name, call.doc_key)
        self._log_doc(call.doc_no)
        self._check_deadline(row)
        self.db.commit()  # no transaction open during the GET
        if self._reusable(call):
            doc = copy.deepcopy(call.fresh_doc)
        else:
            try:
                doc = reader.get_document(call.kind, call.doc_key, doc_date, doc_no=call.doc_no)
            except DocReadError as exc:
                raise self._refuse(row, exc.code) from None
        self._log_doc(doc.get("DocNo"))
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

    @staticmethod
    def _reusable(call: _Call) -> bool:
        """The operation's own read-back may replace the fresh GET: only inside an operation
        (which holds the document, ``uq_ac_write_operation_one_in_progress``), only for an
        edit, and only for the very document asked for."""
        doc = call.fresh_doc
        return (call.operation_id is not None and call.primitive == EDIT and isinstance(doc, dict)
                and doc.get("DocKey") == call.doc_key and isinstance(doc.get("Details"), list))

    def _log_doc(self, doc_no: Any, doc_key: Optional[int] = None) -> None:
        """The document the next logged calls belong to (plan 61 section 4.8)."""
        if self._call_log is None:
            return
        if doc_no:
            self._call_log.context.doc_no = str(doc_no)
        if doc_key is not None:
            self._call_log.context.doc_key = doc_key

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
        if call.operation_id is not None and call.step == "recover" and doc.get(payloads.DB_UNREAD_MARKER):
            # plan 73 H1: the documented exception: a recover puts back a row an operation already deleted, so it is
            # never refused for an unread database (refusing would strand the deleted row)
            doc = {k: v for k, v in doc.items() if k != payloads.DB_UNREAD_MARKER}
        if call.operation_id is None:  # plan 66: only an operation's link step may carry the note
            call = replace(call, line=_no_note(call.line),
                           lines=None if call.lines is None else [_no_note(x) for x in call.lines],
                           groups=None if call.groups is None else [(k, [_no_note(x) for x in v])
                                                                    for k, v in call.groups])
        if call.primitive == EDIT:
            return payloads.build_edit(call.kind, doc, call.header_changes, call.line_changes,
                                       restore=call.restore)
        if call.primitive == ADD_LINE:
            return payloads.build_add_line(call.kind, doc, call.line or {})
        if call.primitive == DELETE_LINE:
            return payloads.build_delete_line(call.kind, doc, int(call.dtl_key or 0))
        if call.primitive == REPLACE_LINE:
            return payloads.build_row_replace(call.kind, doc, {"DtlKey": call.dtl_key}, call.line or {})
        if call.primitive == BATCH_LINK:
            return payloads.build_link_doc(call.kind, doc, _groups_of(call))
        if call.primitive == UNLINK_MERGE:
            return payloads.build_unlink_merge(call.kind, doc, int(call.dtl_key or 0), int(call.merge_key or 0))
        if call.primitive == CANCEL:
            return payloads.build_cancel(call.kind, doc)
        raise WriteRefusal(VENDOR_UNSUPPORTED, "AutoCount has no door that deletes a document")

    def find_doc_no(self, company: AcCompany, kind_name: str, doc_key: int) -> Optional[str]:
        """Plan 61 section 4.4: the DocNo the bydocno read uses, from the same sources as
        ``find_date`` (the staged copy, else our last confirmed read-back); None = unknown
        (the read falls back to the day list)."""
        ref = f"{company.database_name}:{doc_key}"
        entity = ENTITY_BY_KIND.get(kind_name)
        staged = self.staged.newest(company.tenant_id, company.id, entity, ref) if entity else None
        number = ((staged.raw_json or {}).get("DocNo") or staged.doc_no) if staged else None
        if not number:
            after = self.actions.last_confirmed_after(company.tenant_id, company.id, kind_name, doc_key)
            number = (after or {}).get("DocNo")
        return str(number) if number else None

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
        """Qty of one SO row already covered by non-cancelled PO rows: the indexed rows
        (``ac_po_so_link``, plan 62 D8), with ``fresh_po`` (when given) standing in for its own."""
        own_ref = f"{company.database_name}:{fresh_po.get('DocKey')}" if fresh_po else None
        total = sum(
            (_dec(r.get("Qty")) for r in (fresh_po or {}).get("Details") or [] if r.get("FromSODtlKey") == so_dtl_key),
            Decimal(0),
        )
        pending = OperationRepository(self.db).pending_link_qty(
            company.tenant_id, company.id, so_dtl_key, fresh_po.get("DocKey") if fresh_po else None)
        return total + pending + PoSoLinkRepository(self.db).linked_qty(
            company.tenant_id, company.id, so_dtl_key, except_ref=own_ref
        )

    def _guard_transfers(self, call: _Call, company: AcCompany, doc: Doc) -> None:
        if call.kind in ("PO", "SPO") and call.primitive == DELETE_LINE:
            self._guard_po_line(call, company, doc)
            return
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

    def row_needs_attention(self, company: AcCompany, doc_key: int, row: Doc,
                            *, exclude_id: Optional[str] = None) -> bool:
        """Plan 65 D6: the PO row (as freshly read) is covered by an unresolved (``needs_attention`` /
        ``pending_verification``) link operation on the same PO: it is that operation's source row, or a
        row the operation's read did not know (not in its snapshot ``knownKeys``) linked to one of its SO
        rows. ``exclude_id``: the operation asking (its own Resume is never blocked by it)."""
        dtl_key = row.get("DtlKey")
        linked = int(row.get("FromSODtlKey") or 0)
        for op in OperationRepository(self.db).pending_po_row_links(
                company.tenant_id, company.id, doc_key, None, exclude_id=exclude_id):
            whole = op.snapshot_json if isinstance(op.snapshot_json, dict) else {}
            if whole.get("mode") == "doc_batch":  # plan 69: each sent part is a one-row batch snapshot
                parts = [p for p in whole.get("parts") or [] if isinstance(p, dict) and p.get("sent")]
                if any(int((p.get("row") or {}).get("DtlKey") or 0) == dtl_key for p in parts):
                    return True
            else:
                if op.dtl_key == dtl_key:
                    return True
                parts = [whole]
            for snap in parts:
                if not linked or "knownKeys" not in snap or dtl_key in set(snap.get("knownKeys") or []):
                    continue
                so_rows = {int(link.get("soDtlKey") or 0) for link in snap.get("links") or []}
                new_link = snap.get("newLink") if isinstance(snap.get("newLink"), dict) else {}
                if new_link.get("FromDocType") == "SO":
                    so_rows.add(int(new_link.get("FromDocDtlKey") or 0))
                if linked in so_rows:
                    return True
        return False

    def _guard_po_line(self, call: _Call, company: AcCompany, doc: Doc) -> None:
        """AC-61-20 / F15: a PO row an SPO points at, or with a receipt, is never sent a
        "D" (AutoCount's own answer to a received row is unverified). Plan 65 D6: a row an
        unresolved link operation covers is never sent one either (Resume is its repair)."""
        row = next((r for r in doc.get("Details") or [] if r.get("DtlKey") == call.dtl_key), {})
        if (call.kind == "PO" and call.operation_id is None and call.doc_key is not None
                and self.row_needs_attention(company, call.doc_key, row)):
            raise WriteRefusal(ROW_NEEDS_ATTENTION, "a link on this row needs attention; resume it first")
        spo_ref = self._spo_ref(company.tenant_id, company.id, int(call.dtl_key or 0)) if call.kind == "PO" else None
        if spo_ref:
            raise WriteRefusal("ROW_ON_SPO", payloads.on_spo_message(spo_ref), plain=True)
        received = self._row_received(company, call.kind, dict(row, DocKey=doc.get("DocKey")))
        if received is not None and received > 0:  # unknown is left to AutoCount
            raise WriteRefusal(ROW_RECEIVED, "row has received quantity")

    # ── the call, read-back, verify ──────────────────────────────────────────

    def _send(
        self, call: _Call, kind: DocKind, company: AcCompany, base_url: str, row: AcWriteAction,
        reader: Any, before: Optional[Doc], request: VendorRequest, read_date: Optional[date],
        extra: Dict[str, Any],
    ) -> PrimitiveResult:
        client = self._client_for(base_url)
        self._check_deadline(row)
        self._put_sent = True
        try:  # never retried
            if request.method == "POST":
                response = client.post(request.path, request.body)
            elif request.method == "DELETE":  # plan 61 cancel: query string, no body
                response = client.delete_query(request.path, request.params or {})
            else:
                response = client.put(request.path, request.body)
        except WriteTransportError as exc:
            return self._wrap(self._finish(row, OUTCOME_PENDING, exc.code))
        row.response_status = response.status_code
        if response.ok:
            row.response_json = _safe_body(response.stored)
        if not response.ok:
            refusal = _vendor_refusal(call.primitive, response.status_code, response.body)
            if refusal is not None:  # AutoCount said why; nothing changed (F7, F10, F11)
                message = vendor_message(response.stored, base_url)
                row.response_json = {"message": message}
                return self._wrap(self._finish(row, OUTCOME_REFUSED, refusal, message=message))
            if is_business_refusal(response.status_code, response.body):
                message = vendor_message(response.stored, base_url)
                row.response_json = {"message": message}  # the same safe text, never the stack
                vendor_class = vendor_class_of(response.body)
                if request.method == "PUT":  # plan 69 Q1: the read decides, never the answer text
                    looked = self._look_after_refusal(call, company, row, reader, request, before, read_date,
                                                      extra, message, vendor_class)
                    if looked is not None:
                        return looked
                return self._wrap(self._finish(row, OUTCOME_VENDOR_ERROR, VENDOR_REFUSED, message=message),
                                  vendor_class=vendor_class)
            # a bare failure (an IIS page, a stack): the status and redacted text only (AC-57-47)
            text = vendor_message(response.stored, base_url)
            row.response_json = {"text": text}
            return self._wrap(self._finish(row, OUTCOME_VENDOR_ERROR, VENDOR_ERROR, message=text),
                              vendor_class=vendor_class_of(response.body))
        self.db.commit()
        self._check_deadline(row)
        try:
            after = self._read_back(call, reader, response.body, request, before, read_date, row)
        except DocReadError as exc:
            return self._wrap(self._finish(row, OUTCOME_PENDING, exc.code))
        return self._verified(call, company, row, request, before, after, extra)

    def _look_after_refusal(
        self, call: _Call, company: AcCompany, row: AcWriteAction, reader: Any, request: VendorRequest,
        before: Optional[Doc], read_date: Optional[date], extra: Dict[str, Any], message: str,
        vendor_class: Optional[str],
    ) -> Optional[PrimitiveResult]:
        """Plan 69 Q1 / D3: an edit PUT hapi answered with an AutoCount message (hapi's request is over:
        a refusal, or a command timeout that may have come after the save). ONE read decides: the document
        as it was = a real refusal (None: the caller answers ``VENDOR_REFUSED``); changed = it landed, judged
        like a 2xx answer; cannot be read = unknown (``pending_verification``, never refused)."""
        self.db.commit()  # the vendor answer is on the row before the read
        timeout = is_vendor_timeout(message, vendor_class)
        try:
            after = self._read_back(call, reader, None, request, before, read_date, row)
        except DocReadError:
            return self._wrap(self._finish(row, OUTCOME_PENDING, VENDOR_TIMEOUT if timeout else VENDOR_REFUSED,
                                           message=message), vendor_class=vendor_class)
        if before is not None and _unchanged(before, after):
            row.after_json = after
            if timeout:  # nothing YET: the save may still commit; the operation checks again (never released here)
                return self._wrap(self._finish(row, OUTCOME_VENDOR_ERROR, VENDOR_TIMEOUT, message=message),
                                  vendor_class=vendor_class)
            return None
        logger.warning("autocount PUT answered a refusal but the document changed (action %s): judged landed",
                       row.id)
        return self._verified(call, company, row, request, before, after, extra)

    def _verified(
        self, call: _Call, company: AcCompany, row: AcWriteAction, request: VendorRequest,
        before: Optional[Doc], after: Doc, extra: Dict[str, Any],
    ) -> PrimitiveResult:
        """A read-back in hand: verify it, finish the row, stage it."""
        row.after_json = after  # a read-back in hand is always verified
        verdict_code, message, warnings, new_key = self._verify(call, request, before, after)
        if (call.kind in ("PO", "SPO") and before is not None
                and payloads.shipping_po_changed(before, after)):  # SS-SHIPPINGPO-PRESERVE
            was, now = payloads.shipping_po_values(before, after)
            logger.error("autocount %s changed ShippingPO %s -> %s (action %s, DocKey %s)",
                         call.primitive, was, now, row.id, after.get("DocKey"))
            verdict_code, message = payloads.SHIPPING_PO_CHANGED, payloads.SHIPPING_PO_CHANGED_MESSAGE
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
            doc_no = (before or {}).get("DocNo") or call.doc_no
            return reader.get_document(call.kind, int(call.doc_key or 0), read_date, doc_no=doc_no)
        parsed = payloads.parse_create_answer(answer)
        if parsed is not None:
            self._log_doc(parsed[0], parsed[1])
            return reader.get_document(call.kind, parsed[1], read_date, doc_no=parsed[0])
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
        if call.primitive == REPLACE_LINE:
            v = payloads.verify_row_replace(call.kind, before, int(call.dtl_key or 0), call.line or {}, after)
            known = {r.get("DtlKey") for r in before.get("Details") or []}
            added = [r.get("DtlKey") for r in after.get("Details") or [] if r.get("DtlKey") not in known]
            ok = v.outcome == payloads.DONE
            return (None if ok else v.code), "", [], (added[0] if ok and added else None)
        if call.primitive == BATCH_LINK:
            v = payloads.verify_link_doc(call.kind, before, _groups_of(call), after)
            return (v.code if v.outcome == payloads.MISMATCH else None), "", [], None
        if call.primitive == UNLINK_MERGE:
            v = payloads.verify_unlink_merge(
                call.kind, before, int(call.dtl_key or 0), int(call.merge_key or 0), after)
            return (v.code if v.outcome == payloads.MISMATCH else None), "", [], None
        if call.primitive == DELETE_LINE:
            v = payloads.verify_delete_line(call.kind, before, int(call.dtl_key or 0), after)
        else:
            v = payloads.verify_cancel(call.kind, after)
        return (v.code if v.outcome != payloads.DONE else None), "", [], None
