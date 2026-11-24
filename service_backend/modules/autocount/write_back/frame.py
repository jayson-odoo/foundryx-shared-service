"""Shared frame of the write-back services (plan 55 / plan 57).

The pieces every write flow needs: outcome and refusal codes, the answer type,
the per-document busy check, the committed-outcome ``_finish``, the db3-guarded
write connection lookup, the deadline clock and the stage-and-push step. Moved
out of ``service.py`` unchanged so the plan 55 flows and the plan 57 primitive
service share one implementation.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.autocount.models import AcCompany, AcWriteAction
from modules.autocount.provider import PROVIDER_KEY
from modules.autocount.repositories import ConnectionRepository
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back import auth
from modules.autocount.write_back import call_log as cl
from modules.autocount.write_back import guard
from modules.autocount.write_back.line_notes import NotesReader, SqlDocDb
from modules.autocount.write_back.guard import WriteConnectionError, WriteNotAllowed, assert_write_allowed
from modules.autocount.write_back.reader import AutoCountDocReader
from modules.autocount.write_back.doc_mapping import ENTITY_BY_KIND
from modules.autocount.write_back.repository import (
    EntitySourceRepository,
    SoRowIndexRepository,
    SpoPoLinkRepository,
    StagedDocRepository,
    WriteActionRepository,
)
from modules.autocount.write_back.staging import DocStager

Doc = Dict[str, Any]
_MAX_TEXT = 2000

OUTCOME_DONE = "done"
OUTCOME_REFUSED = "refused"
OUTCOME_MISMATCH = "mismatch"
OUTCOME_PENDING = "pending_verification"
OUTCOME_VENDOR_ERROR = "vendor_error"

WRITE_DISABLED = "WRITE_DISABLED"
# An in_flight / pending_verification action blocks its document for this long;
# after it the document is free again (the old row is marked pending_verification).
BUSY_WINDOW_SECONDS = 600
# Overall budget of one action (all vendor calls together); at most half the busy window.
ACTION_DEADLINE_SECONDS = 270.0
DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
SO_LOCATION_AMBIGUOUS = "SO_LOCATION_AMBIGUOUS"

INTERNAL_ERROR = "INTERNAL_ERROR"
VENDOR_UNSUPPORTED = "VENDOR_UNSUPPORTED"
LOCATION_NOT_MOVED = "LOCATION_NOT_MOVED"
ROW_ALREADY_AT_LOCATION = "ROW_ALREADY_AT_LOCATION"
DOC_KIND_MISMATCH = "DOC_KIND_MISMATCH"
DOC_BUSY = "DOC_BUSY"
DOC_UNKNOWN = "DOC_UNKNOWN"
DOC_STALE = "DOC_STALE"
# Plan 70: a location the caller named is not in the book's Location master (refused before any write)
LOCATION_UNKNOWN = "LOCATION_UNKNOWN"


@dataclass
class WriteActionResult:
    """What a flow answered. ``document`` is the read-back document on ``done``."""

    action_id: Optional[str]
    outcome: str
    error_code: Optional[str] = None
    message: str = ""
    document: Optional[Doc] = None
    # plan 57: set only when an operation answered (the plan 55 routes then add them to the body)
    operation_id: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    replaced_lines: List[Tuple[int, int]] = field(default_factory=list)
    doc_key: Optional[int] = None
    doc_no: Optional[str] = None
    # plan 64: ``po-links`` only - the PO row the link landed on, as read back (None unless done)
    detail: Optional[Doc] = None
    # plan 71: ``po-links/unlink`` merged back into its source row (``returnedTo``; None otherwise)
    returned_to: Optional[Dict[str, Any]] = None


class _Stop(Exception):
    """Internal early exit carrying a finished result."""

    def __init__(self, result: WriteActionResult) -> None:
        self.result = result



def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))

def _doc_date(raw: Optional[Doc]) -> Optional[date]:
    text = str((raw or {}).get("DocDate") or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None

def _lines(raw: Optional[Doc]) -> List[Doc]:
    lines = (raw or {}).get("_lines")
    return [r for r in lines if isinstance(r, dict)] if isinstance(lines, list) else []

def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _dec(a) == _dec(b)
    return a == b

def clean_location(value: Any) -> Optional[str]:
    """Plan 70: a caller's optional ``location`` (an AutoCount Location code): trimmed text, else None
    (absent, null, blank or not text = none given, today's behaviour)."""
    return (value.strip() or None) if isinstance(value, str) else None


def unknown_location_message(code: str) -> str:
    """Plan 70: the plain reason for ``LOCATION_UNKNOWN`` (the CRM shows it as is)."""
    return f"Location {code} does not exist in AutoCount, so nothing was changed. Pick another location and try again."


def known_locations(reader: Any, codes: "Iterable[str]") -> Dict[str, str]:
    """Plan 70, the ONE location check of every link path: ``codes`` (trimmed) looked up in the book's
    Location master with one logged GET (``reader.location_codes``). Answers ``casefold(code) -> AutoCount's
    own code`` for the codes that exist; a missing key = unknown. A failed read raises ``DocReadError``."""
    wanted = {c.casefold() for c in codes if c}
    if not wanted:
        return {}
    master = reader.location_codes()
    return {key: master[key] for key in wanted if key in master}


def _safe_body(body: Any) -> Doc:
    if isinstance(body, (dict, list)):
        return body  # type: ignore[return-value]
    return {"text": str(body)[:_MAX_TEXT]}


class WriteFrame:
    def __init__(
        self,
        db: Session,
        *,
        client_factory: Optional[Callable[[str], AutoCountWriteClient]] = None,
        reader_factory: Optional[Callable[[str], AutoCountDocReader]] = None,
        sink_factory: Optional[Callable[..., Any]] = None,
        actor: Optional[str] = None,
        request_id: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> None:
        self.db = db
        self._actor = actor  # "runner" for the db3 runner; None = the API key id, else "system"
        self.request_id = request_id
        self.acting_user_id: Optional[str] = None
        self.acting_user_name: Optional[str] = None
        self._operation_id = operation_id  # set when an operation runs this flow (the split link)
        # AUTOCOUNT-STRANDED-OPS-B: the operation row a single-document primitive runs under (``run_primitive``):
        # its action rows and GETs carry it, so a same-key resend can look the outcome up. Never ``call.operation_id``
        # (that marks a step of a multi-step operation, which skips the busy check).
        self._owner_operation_id: Optional[str] = None
        # the action whose unknown outcome the next primitive call looks up instead of writing (``look_up``)
        self._lookup_action: Optional[Any] = None
        self._trust_absent = False
        self._call_log: Optional[cl.CallLog] = None
        self._refused_base_url: Optional[str] = None
        self._write_headers: Dict[str, str] = {}
        self._read_headers: Dict[str, str] = {}
        self._notes_extra: Optional[Any] = None  # plan 73: the company's AutoCount DB source (None = unread: every PO / SPO write refuses)
        self.actions = WriteActionRepository(db)
        self.staged = StagedDocRepository(db)
        self.connections = ConnectionRepository(db)
        self._client_factory = client_factory or AutoCountWriteClient
        self._reader_factory = reader_factory or AutoCountDocReader
        self._sink_factory = sink_factory
        self._deadline = 0.0
        self._put_sent = False
        self._staged_memo: Optional[Dict[Any, Any]] = None  # C.d: see ``staged_memo``

    def use_trace(
        self, request_id: Optional[str], person: "Tuple[Optional[str], Optional[str]]" = (None, None)
    ) -> None:
        """The caller's request id (``X-Request-ID`` else ``Idempotency-Key``) and acting person
        for the call log and the action rows."""
        self.request_id = request_id
        self.acting_user_id, self.acting_user_name = person

    def new_call_log(
        self, company: AcCompany, *, kind: Optional[str] = None, doc_key: Optional[int] = None,
        doc_no: Optional[str] = None, key_id: Optional[str] = None, operation_id: Optional[str] = None,
        action_id: Optional[str] = None,
    ) -> cl.CallLog:
        """A call log (plan 61 section 4.8) for the HTTP calls of one flow, on its own session."""
        context = cl.CallContext(
            tenant_id=company.tenant_id, company_id=company.id,
            actor=key_id or self._actor or cl.ACTOR_SYSTEM, request_id=self.request_id,
            operation_id=operation_id or self._operation_id or self._owner_operation_id, action_id=action_id, doc_type=kind,
            doc_no=doc_no, doc_key=doc_key, acting_user_id=self.acting_user_id,
            acting_user_name=self.acting_user_name,
        )
        return cl.CallLog(self.db.get_bind(), context)

    def _trace_columns(self) -> Dict[str, Optional[str]]:
        """The request id and acting person every action row of this request carries."""
        return {"request_id": self.request_id, "acting_user_id": self.acting_user_id,
                "acting_user_name": self.acting_user_name}

    def _reader_for(self, base_url: str, log: Optional[cl.CallLog] = None) -> Any:
        reader = auth.attach_headers(self._reader_factory(base_url), self._read_headers)
        reader = cl.attach_call_log(reader, log or self._call_log)
        # plan 73 D1: every PO / SPO read carries the values stored in the AutoCount DB (header + rows + FurtherDescription)
        return NotesReader(reader, self._notes_extra)

    def _client_for(self, base_url: str, log: Optional[cl.CallLog] = None) -> Any:
        client = auth.attach_headers(self._client_factory(base_url), self._write_headers)
        return cl.attach_call_log(client, log or self._call_log)

    def _expired(self) -> bool:
        return time.monotonic() > self._deadline

    def _check_deadline(self, row: AcWriteAction) -> None:
        """No vendor call after the action's overall deadline: refused before any
        write was sent, pending verification after."""
        if time.monotonic() <= self._deadline:
            return
        if self._put_sent:
            raise _Stop(self._finish(row, OUTCOME_PENDING, DEADLINE_EXCEEDED))
        raise self._refuse(row, DEADLINE_EXCEEDED)

    def _check_not_busy(
        self, row: AcWriteAction, tenant_id: str, company_id: str, doc_key: int
    ) -> None:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=BUSY_WINDOW_SECONDS)
        if self.actions.expire_stale_in_flight(tenant_id, company_id, doc_key, window_start):
            self.db.commit()
        if self.actions.has_open(tenant_id, company_id, doc_key, window_start):
            raise self._refuse(row, DOC_BUSY)

    def _finish(
        self,
        row: AcWriteAction,
        outcome: str,
        code: Optional[str] = None,
        *,
        document: Optional[Doc] = None,
        message: str = "",
    ) -> WriteActionResult:
        """Record the outcome (committed) and return the answer."""
        row.outcome = outcome
        row.error_code = code
        self.db.commit()
        return WriteActionResult(row.id, outcome, code, message, document)

    def _refuse(self, row: AcWriteAction, code: str, message: str = "") -> _Stop:
        return _Stop(self._finish(row, OUTCOME_REFUSED, code, message=message))

    def _write_connection(self, company: AcCompany) -> Any:
        """The company's active write connection resolved WITH tenant_id, or None."""
        conn = None
        if company.is_active and company.write_connection_id:
            conn = self.connections.get_for_provider(
                company.tenant_id, company.write_connection_id, PROVIDER_KEY
            )
        return conn if conn is not None and conn.is_active else None

    def _line_notes_source(self, company: AcCompany) -> Optional[Any]:
        """Plan 73 R1: the company's AutoCount DB source: its explicit ``line_notes_connection_id`` when set, else
        its own source connection (``company.connection_id``); either must resolve WITH tenant_id as an ACTIVE
        same-tenant ``sql_database`` connection, else None (unknown, every PO / SPO write refuses)."""
        from modules.autocount.sql_provider import SQL_DATABASE_PROVIDER_KEY

        connection_id = company.line_notes_connection_id or company.connection_id
        if not connection_id:
            return None
        conn = self.connections.get_for_provider(company.tenant_id, connection_id, SQL_DATABASE_PROVIDER_KEY)
        return SqlDocDb(conn) if conn is not None and conn.is_active else None

    def _resolve_write_base_url(self, company: AcCompany) -> "Tuple[Optional[str], Optional[Tuple[str, str]]]":
        """``(url, None)`` or ``(None, (code, message))``: the company's write
        connection URL resolved WITH tenant_id and the write guard applied."""
        self._refused_base_url = None
        self._notes_extra = self._line_notes_source(company)
        conn = self._write_connection(company)
        if conn is None:
            return None, (WRITE_DISABLED, "")
        base_url = str((conn.config_json or {}).get("baseUrl") or "")
        try:
            assert_write_allowed(base_url)
        except WriteNotAllowed as exc:
            self._refused_base_url = base_url  # kept for the guard_refused call-log row only
            return None, (exc.code, "")  # the code only: never the book name (AC-57-47)
        try:  # the optional API key, read fresh on every action (no cache: rotation = next action)
            self._write_headers, self._read_headers = auth.write_headers(conn), auth.read_headers(conn)
        except auth.AuthConfigInvalid as exc:
            self._refused_base_url = base_url
            return None, (exc.code, "")
        return base_url, None

    def _company_book(self, company: AcCompany) -> Optional[str]:
        """The book of the company's write connection URL (for the live-book check)."""
        conn = self._write_connection(company)
        return None if conn is None else guard.book_of(str((conn.config_json or {}).get("baseUrl") or ""))

    def _log_refused_connection(
        self, company: AcCompany, code: str, *, kind: Optional[str] = None, doc_key: Optional[int] = None,
        action_id: Optional[str] = None,
    ) -> None:
        """One ``guard_refused`` call-log row for a write refused before any client existed."""
        base_url = getattr(self, "_refused_base_url", None)
        if not base_url:
            return
        log = self._call_log or self.new_call_log(company, kind=kind, doc_key=doc_key, action_id=action_id)
        log.record(base_url=base_url, method="-", path="-", started=log.started(),
                   outcome=cl.GUARD_REFUSED, error_code=code)

    def _check_test_company(self, row: AcWriteAction, company: AcCompany) -> None:
        """AC-57-47: the write-time test-company check, through the guard module's one
        function, before any request (a company can gain SQL data after its connection
        was set)."""
        try:
            guard.assert_test_company(self.db, company.tenant_id, company.id, book=self._company_book(company))
        except WriteConnectionError as exc:
            raise self._refuse(row, exc.code) from None

    def _write_base_url(self, row: AcWriteAction, company: AcCompany) -> str:
        """The write URL, or a ``_Stop`` (refused) carrying why not."""
        base_url, refusal = self._resolve_write_base_url(company)
        if base_url is None:
            code, message = refusal  # type: ignore[misc]
            self._log_refused_connection(company, code, kind=row.doc_type, doc_key=row.doc_key, action_id=row.id)
            raise self._refuse(row, code, message)
        return base_url

    def _row_received(self, company: AcCompany, kind: str, row: Doc) -> Optional[Decimal]:
        """Qty of this row already received (PO / SPO) or delivered (SO), or None when
        unknown (AC-57-33 source order): the GET row's ``TransferedQty``; else, when the
        company's entity config for the document type is ``sql_db``, the staged canonical
        line's ``qty_received`` / ``qty_delivered`` of the newest staged row; else None."""
        if row.get("TransferedQty") is not None:
            return _dec(row.get("TransferedQty"))
        entity = ENTITY_BY_KIND[kind]
        memo = self._staged_memo  # C.d: one source / staged read per document per operation, not per row
        source_key = ("source", entity)
        if memo is None or source_key not in memo:
            impl = EntitySourceRepository(self.db).source_impl(company.tenant_id, company.id, entity)
            if memo is not None:
                memo[source_key] = impl
        else:
            impl = memo[source_key]
        if impl != "sql_db":
            return None
        ref = f"{company.database_name}:{row.get('DocKey')}"
        doc_key_memo = ("staged", entity, ref)
        if memo is not None and doc_key_memo in memo:
            staged = memo[doc_key_memo]
        else:
            staged = self.staged.newest(company.tenant_id, company.id, entity, ref)
            if memo is not None:
                memo[doc_key_memo] = staged
        wanted = f"{ref}:{row.get('DtlKey')}"
        field_name = "qty_delivered" if kind == "SO" else "qty_received"
        for line in ((staged.canonical_json or {}).get("lines") or []) if staged else []:
            if isinstance(line, dict) and line.get("source_ref") == wanted:
                value = line.get(field_name)
                return None if value is None else _dec(value)
        return None

    def _spo_ref(self, tenant_id: str, company_id: str, po_dtl_key: int) -> Optional[str]:
        """DocNo of a staged, non-cancelled SPO with a row pointing at the PO row: ONE indexed query on
        ``ac_spo_po_link`` (the newest copy of each SPO), never a load of every staged SPO (C.d)."""
        return SpoPoLinkRepository(self.db).spo_doc_no(tenant_id, company_id, po_dtl_key)

    def _so_row(self, tenant_id: str, company_id: str, so_dtl_key: int) -> Optional[Tuple[str, Optional[str], bool]]:
        """The SO row ``so_dtl_key`` from the NEWEST staged SO holding it: ``(so_doc_no, location, ambiguous)``,
        None when no staged SO holds it. ONE indexed query on ``ac_so_row_index``, never a load of every staged
        SO (C.d). ``ambiguous``: equally new copies disagree on its location (``SO_LOCATION_AMBIGUOUS``)."""
        rows = SoRowIndexRepository(self.db).rows_for(tenant_id, company_id, so_dtl_key)
        if not rows:
            return None
        floor = datetime.min.replace(tzinfo=timezone.utc)
        newest_at = max(r.staged_at or floor for r in rows)
        newest = sorted((r for r in rows if (r.staged_at or floor) == newest_at), key=lambda r: r.so_source_ref)
        locations = {r.location for r in newest}
        ambiguous = any(r.ambiguous for r in newest) or len(locations) > 1
        return str(newest[0].so_doc_no or ""), None if ambiguous else newest[0].location, ambiguous

    @contextlib.contextmanager
    def staged_memo(self) -> Iterator[None]:
        """Within the block, ``_row_received`` reads each document's source config and newest staged copy
        once (an operation's guards check the target row AND every merge candidate on the same PO)."""
        outer = self._staged_memo
        self._staged_memo = {} if outer is None else outer
        try:
            yield
        finally:
            self._staged_memo = outer

    def _stage(
        self, company: AcCompany, kind: str, doc: Doc, replaced: Optional[Dict[int, int]] = None
    ) -> None:
        """Stage the verified read-back and push it once (never changes the outcome)."""
        DocStager(self.db, self._sink_factory).stage_and_push(company, doc, kind, replaced=replaced)
