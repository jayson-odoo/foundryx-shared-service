"""Write-back service flow (plan 55 section 6b, AC-55-20..28).

company -> write connection -> db3 guard -> per-document busy check -> staged
DocDate -> fresh GET -> stale check -> derive outstanding / SPO reference ->
S2 builder -> PUT -> GET back -> verify -> stage the read-back and push once.

AC-55-27: no AutoCount call is made while the session holds a transaction; the
``in_flight`` action row is committed before the PUT, and every outcome is
committed as it is reached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modules.autocount.canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
)
from modules.autocount.models import (
    AcCompany,
    AcWriteAction,
)
from modules.autocount.provider import PROVIDER_KEY
from modules.autocount.repositories import CompanyRepository, ConnectionRepository
from modules.autocount.write_back import payloads
from modules.autocount.write_back.client import (
    AutoCountWriteClient,
    WriteTransportError,
)
from modules.autocount.write_back.constants import EDIT_PO_PATH
from modules.autocount.write_back.staging import DocStager
from modules.autocount.write_back.guard import WriteNotAllowed, assert_write_allowed
from modules.autocount.write_back.payloads import WriteRefusal
from modules.autocount.write_back.reader import AutoCountDocReader, DocReadError
from modules.autocount.write_back.repository import (
    OUTCOME_IN_FLIGHT,
    StagedDocRepository,
    WriteActionRepository,
)

logger = logging.getLogger("foundryx.autocount")

Doc = Dict[str, Any]

OUTCOME_DONE = "done"
OUTCOME_REFUSED = "refused"
OUTCOME_MISMATCH = "mismatch"
OUTCOME_PENDING = "pending_verification"
OUTCOME_VENDOR_ERROR = "vendor_error"

WRITE_DISABLED = "WRITE_DISABLED"
# An in_flight / pending_verification action blocks its document for this long;
# after it the document is free again (the old row is marked pending_verification).
BUSY_WINDOW_SECONDS = 600

INTERNAL_ERROR = "INTERNAL_ERROR"
DOC_KIND_MISMATCH = "DOC_KIND_MISMATCH"
DOC_BUSY = "DOC_BUSY"
DOC_UNKNOWN = "DOC_UNKNOWN"
DOC_STALE = "DOC_STALE"

ACTION_LINK = "link"
ACTION_UNLINK = "unlink"
ACTION_SPO_UNLINK = "spo_unlink"

# vendor kind -> (action-log doc_type, staged entity type)
_PO = ("PO", ENTITY_PURCHASE_ORDER)
_SPO = ("SPO", ENTITY_SHIPPING_ORDER)
_SO = ("SO", ENTITY_SALES_ORDER)

_VERIFY_FIELDS = ("ItemCode", "Location", "UOM", "Qty")
_UNTOUCHED_FIELDS = payloads.ROW_KEYS + ("FromSODtlKey",)
_MAX_TEXT = 2000


@dataclass
class WriteActionResult:
    """What a flow answered. ``document`` is the read-back document on ``done``."""

    action_id: Optional[str]
    outcome: str
    error_code: Optional[str] = None
    message: str = ""
    document: Optional[Doc] = None


class _Stop(Exception):
    """Internal early exit carrying a finished result."""

    def __init__(self, result: WriteActionResult) -> None:
        self.result = result


@dataclass
class _Plan:
    """What one flow needs: the action, the PO-side document and the builder."""

    action: str
    kind: tuple
    doc_key: int
    dtl_key: int
    so_doc_key: Optional[int] = None
    so_dtl_key: Optional[int] = None
    qty: Optional[Decimal] = None


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


def _expected_link(row: Doc, is_spo: bool) -> int:
    """The link key the row must read back with: on a PO row AutoCount moves an
    SO link into ``FromSODtlKey``; an SPO row keeps ``FromDocDtlKey``."""
    if is_spo:
        return int(row.get("FromDocDtlKey") or 0)
    return int(row.get("FromDocDtlKey") or 0) if row.get("FromDocType") == "SO" else 0


def _row_ok(sent: Doc, got: Doc, is_spo: bool) -> bool:
    if not all(_same(sent.get(k), got.get(k)) for k in _VERIFY_FIELDS):
        return False
    key = "FromDocDtlKey" if is_spo else "FromSODtlKey"
    return int(got.get(key) or 0) == _expected_link(sent, is_spo)


def verify_readback(before: Doc, after: Doc, body: Doc) -> bool:
    """AC-55-22: every sent row reads back as sent (a new row, ``DtlKey 0``,
    appears exactly once) and every untouched row reads back unchanged."""
    is_spo = before.get("ShippingPO") == "T"
    for key, value in body.items():  # every header field we sent reads back unchanged
        if key != "Details" and not _same(value, after.get(key)):
            return False
    before_rows = {r.get("DtlKey"): r for r in before.get("Details") or []}
    after_rows = {r.get("DtlKey"): r for r in after.get("Details") or []}
    sent = body.get("Details") or []
    sent_keys = {r["DtlKey"] for r in sent if r.get("DtlKey")}
    new_sent = [r for r in sent if not r.get("DtlKey")]
    added = [r for k, r in after_rows.items() if k not in before_rows]
    if len(added) != len(new_sent) or len(after_rows) != len(before_rows) + len(new_sent):
        return False
    for row in sent:
        if row.get("DtlKey") and not (
            row["DtlKey"] in after_rows and _row_ok(row, after_rows[row["DtlKey"]], is_spo)
        ):
            return False
    if not all(any(_row_ok(s, a, is_spo) for a in added) for s in new_sent):
        return False
    for key, row in before_rows.items():
        if key in sent_keys:
            continue
        got = after_rows.get(key)
        if got is None or not all(_same(row.get(f), got.get(f)) for f in _UNTOUCHED_FIELDS):
            return False
    return True


def _safe_body(body: Any) -> Doc:
    if isinstance(body, (dict, list)):
        return body  # type: ignore[return-value]
    return {"text": str(body)[:_MAX_TEXT]}


class WriteBackService:
    def __init__(
        self,
        db: Session,
        *,
        client_factory: Optional[Callable[[str], AutoCountWriteClient]] = None,
        reader_factory: Optional[Callable[[str], AutoCountDocReader]] = None,
        sink_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.db = db
        self.actions = WriteActionRepository(db)
        self.staged = StagedDocRepository(db)
        self.connections = ConnectionRepository(db)
        self._client_factory = client_factory or AutoCountWriteClient
        self._reader_factory = reader_factory or AutoCountDocReader
        self._sink_factory = sink_factory

    # ── public flows ─────────────────────────────────────────────────────────

    def link(
        self,
        *,
        tenant_id: str,
        company_id: str,
        po_doc_key: int,
        po_dtl_key: int,
        so_doc_key: int,
        so_dtl_key: int,
        qty: Decimal,
        expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> WriteActionResult:
        plan = _Plan(ACTION_LINK, _PO, po_doc_key, po_dtl_key, so_doc_key, so_dtl_key, qty)
        return self._run(plan, tenant_id, company_id, expected_last_modified, key_id)

    def unlink(
        self,
        *,
        tenant_id: str,
        company_id: str,
        po_doc_key: int,
        po_dtl_key: int,
        expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> WriteActionResult:
        plan = _Plan(ACTION_UNLINK, _PO, po_doc_key, po_dtl_key)
        return self._run(plan, tenant_id, company_id, expected_last_modified, key_id)

    def spo_unlink(
        self,
        *,
        tenant_id: str,
        company_id: str,
        spo_doc_key: int,
        spo_dtl_key: int,
        expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> WriteActionResult:
        plan = _Plan(ACTION_SPO_UNLINK, _SPO, spo_doc_key, spo_dtl_key)
        return self._run(plan, tenant_id, company_id, expected_last_modified, key_id)

    # ── flow ─────────────────────────────────────────────────────────────────

    def _run(
        self,
        plan: _Plan,
        tenant_id: str,
        company_id: str,
        expected_last_modified: Optional[str],
        key_id: Optional[str],
    ) -> WriteActionResult:
        company = CompanyRepository(self.db).get(tenant_id, company_id)
        if company is None:
            return WriteActionResult(None, OUTCOME_REFUSED, WRITE_DISABLED)
        row = self._new_row(plan, tenant_id, company.id, key_id)
        try:
            self._check_qty(plan, row)
            base_url = self._write_base_url(row, company)
            self._check_not_busy(row, tenant_id, company.id, plan.doc_key)
            row.outcome = OUTCOME_IN_FLIGHT
            try:
                self.db.commit()
            except IntegrityError:
                # lost the race to another in_flight action on this document
                self.db.rollback()
                return self._busy_after_race(plan, tenant_id, company.id, key_id)
        except _Stop as stop:
            return stop.result
        row_id = row.id
        try:
            return self._execute(plan, company, base_url, row, expected_last_modified)
        except _Stop as stop:
            return stop.result
        except Exception:  # noqa: BLE001 - the in_flight row must never be stranded
            logger.exception("autocount write-back flow failed (action %s)", row_id)
            self.db.rollback()
            return self._finish(row, OUTCOME_PENDING, INTERNAL_ERROR)
        finally:
            self.db.rollback()

    def _check_qty(self, plan: _Plan, row: AcWriteAction) -> None:
        """Quantity bounds before any document is read (H5)."""
        if plan.qty is None:
            return
        try:
            plan.qty = payloads.validate_qty(plan.qty)
        except WriteRefusal as exc:
            raise self._refuse(row, exc.code, str(exc)) from None

    def _check_not_busy(
        self, row: AcWriteAction, tenant_id: str, company_id: str, doc_key: int
    ) -> None:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=BUSY_WINDOW_SECONDS)
        if self.actions.expire_stale_in_flight(tenant_id, company_id, doc_key, window_start):
            self.db.commit()
        if self.actions.has_open(tenant_id, company_id, doc_key, window_start):
            raise self._refuse(row, DOC_BUSY)

    def _busy_after_race(
        self, plan: _Plan, tenant_id: str, company_id: str, key_id: Optional[str]
    ) -> WriteActionResult:
        row = self._new_row(plan, tenant_id, company_id, key_id)
        return self._finish(row, OUTCOME_REFUSED, DOC_BUSY)

    def _new_row(
        self, plan: _Plan, tenant_id: str, company_id: str, key_id: Optional[str]
    ) -> AcWriteAction:
        return self.actions.add(
            AcWriteAction(
                tenant_id=tenant_id,
                company_id=company_id,
                action=plan.action,
                doc_type=plan.kind[0],
                doc_key=plan.doc_key,
                dtl_key=plan.dtl_key,
                outcome=OUTCOME_REFUSED,
                key_id=key_id,
            )
        )

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

    def _write_base_url(self, row: AcWriteAction, company: AcCompany) -> str:
        """The company's write connection URL, resolved WITH tenant_id and the
        db3 guard applied; a ``_Stop`` (refused) otherwise."""
        conn = None
        if company.is_active and company.write_connection_id:
            conn = self.connections.get_for_provider(
                company.tenant_id, company.write_connection_id, PROVIDER_KEY
            )
        if conn is None or not conn.is_active:
            raise self._refuse(row, WRITE_DISABLED)
        base_url = str((conn.config_json or {}).get("baseUrl") or "")
        try:
            assert_write_allowed(base_url)
        except WriteNotAllowed as exc:
            raise self._refuse(row, exc.code, str(exc)) from None
        return base_url

    def _execute(
        self,
        plan: _Plan,
        company: AcCompany,
        base_url: str,
        row: AcWriteAction,
        expected_last_modified: Optional[str],
    ) -> WriteActionResult:
        reader = self._reader_factory(base_url)
        doc = self._read_fresh(plan.kind, plan.doc_key, company, row, reader)
        if expected_last_modified and doc.get("LastModified") != expected_last_modified:
            raise self._refuse(row, DOC_STALE)
        so_doc = None
        if plan.so_doc_key is not None:
            so_doc = self._read_fresh(_SO, plan.so_doc_key, company, row, reader)
        body = self._build(plan, company, row, doc, so_doc)
        row.before_json = doc
        row.request_json = body
        self.db.commit()  # in_flight + body committed before any PUT (AC-55-27)
        return self._put_and_verify(plan, company, base_url, row, reader, doc, body)

    def _read_fresh(
        self,
        kind: tuple,
        doc_key: int,
        company: AcCompany,
        row: AcWriteAction,
        reader: AutoCountDocReader,
    ) -> Doc:
        ref = f"{company.database_name}:{doc_key}"
        staged = self.staged.newest(company.tenant_id, company.id, kind[1], ref)
        doc_date = _doc_date(staged.raw_json if staged else None)
        if doc_date is None:
            raise self._refuse(row, self._missing_code(kind, company, ref))
        self.db.commit()  # no transaction open during the GET (AC-55-27)
        try:
            return reader.get_document(kind[0], doc_key, doc_date)
        except DocReadError as exc:
            raise self._refuse(row, exc.code) from None

    def _missing_code(self, kind: tuple, company: AcCompany, ref: str) -> str:
        """``DOC_KIND_MISMATCH`` when the DocKey is staged as the OTHER PO-family
        entity (a PO key sent as an SPO, or the reverse), else ``DOC_UNKNOWN``."""
        other = {_PO[1]: _SPO[1], _SPO[1]: _PO[1]}.get(kind[1])
        if other and self.staged.newest(company.tenant_id, company.id, other, ref):
            return DOC_KIND_MISMATCH
        return DOC_UNKNOWN

    def _build(
        self,
        plan: _Plan,
        company: AcCompany,
        row: AcWriteAction,
        doc: Doc,
        so_doc: Optional[Doc],
    ) -> Doc:
        tenant_id = company.tenant_id
        try:
            if plan.action == ACTION_SPO_UNLINK:
                return payloads.build_spo_unlink(doc, plan.dtl_key)
            spo_ref = self._spo_ref(tenant_id, company.id, plan.dtl_key)
            if plan.action == ACTION_UNLINK:
                return payloads.build_unlink(doc, plan.dtl_key, spo_ref=spo_ref)
            assert so_doc is not None and plan.so_dtl_key is not None and plan.qty is not None
            linked = self._so_linked_qty(company, doc, plan.so_dtl_key)
            return payloads.build_link(
                doc, plan.dtl_key, so_doc, plan.so_dtl_key, plan.qty,
                so_linked_qty=linked, spo_ref=spo_ref,
            )
        except WriteRefusal as exc:
            raise self._refuse(row, exc.code, str(exc)) from None

    def _so_linked_qty(self, company: AcCompany, fresh_po: Doc, so_dtl_key: int) -> Decimal:
        """Qty of the SO row already covered by PO rows: the fresh edited PO plus
        every OTHER staged, non-cancelled PO (db3 scale; AQ11)."""
        total = Decimal(0)
        own_ref = f"{company.database_name}:{fresh_po.get('DocKey')}"
        sources: List[List[Doc]] = [list(fresh_po.get("Details") or [])]
        for staged in self.staged.for_entity(company.tenant_id, company.id, ENTITY_PURCHASE_ORDER):
            raw = staged.raw_json or {}
            if staged.source_ref != own_ref and raw.get("Cancelled") != "T":
                sources.append(_lines(raw))
        for lines in sources:
            total += sum(
                (_dec(r.get("Qty")) for r in lines if r.get("FromSODtlKey") == so_dtl_key),
                Decimal(0),
            )
        return total

    def _spo_ref(self, tenant_id: str, company_id: str, po_dtl_key: int) -> Optional[str]:
        """DocNo of a staged, non-cancelled SPO with a row pointing at the PO row."""
        for staged in self.staged.for_entity(tenant_id, company_id, ENTITY_SHIPPING_ORDER):
            raw = staged.raw_json or {}
            if raw.get("Cancelled") == "T":
                continue
            if any(r.get("FromDocDtlKey") == po_dtl_key for r in _lines(raw)):
                return str(raw.get("DocNo") or staged.doc_no or staged.source_ref)
        return None

    def _put_and_verify(
        self,
        plan: _Plan,
        company: AcCompany,
        base_url: str,
        row: AcWriteAction,
        reader: AutoCountDocReader,
        before: Doc,
        body: Doc,
    ) -> WriteActionResult:
        client = self._client_factory(base_url)
        try:
            response = client.put(EDIT_PO_PATH, body)  # never retried
        except WriteTransportError as exc:
            return self._finish(row, OUTCOME_PENDING, exc.code)
        row.response_status = response.status_code
        row.response_json = _safe_body(response.body)
        if not response.ok:
            return self._finish(row, OUTCOME_VENDOR_ERROR, "VENDOR_ERROR")
        self.db.commit()
        doc_date = _doc_date(before)
        try:
            assert doc_date is not None
            after = reader.get_document(plan.kind[0], plan.doc_key, doc_date)
        except (DocReadError, AssertionError) as exc:
            return self._finish(
                row, OUTCOME_PENDING, getattr(exc, "code", "READ_FAILED")
            )
        row.after_json = after
        if not verify_readback(before, after, body):
            return self._finish(row, OUTCOME_MISMATCH, "READBACK_MISMATCH")
        result = self._finish(row, OUTCOME_DONE, document=after)
        self._stage(company, plan.kind[0], after)
        return result

    # ── staging + push ───────────────────────────────────────────────────────

    def _stage(self, company: AcCompany, kind: str, doc: Doc) -> None:
        """Stage the verified read-back and push it once (never changes the outcome)."""
        DocStager(self.db, self._sink_factory).stage_and_push(company, doc, kind)


class WriteConnectionError(Exception):
    """``set_write_connection`` refused; ``code`` is WRITE_NOT_ALLOWED or
    CONNECTION_NOT_FOUND and the company is left unchanged."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def set_write_connection(
    db: Session, *, tenant_id: str, company_id: str, connection_id: str
) -> AcCompany:
    """Point a company's writes at a connection: same-tenant ``autocount``
    connection whose base URL passes the write guard (db3 only), else a
    ``WriteConnectionError`` with the company unchanged."""
    company = CompanyRepository(db).get(tenant_id, company_id)
    conn = ConnectionRepository(db).get_for_provider(tenant_id, connection_id, PROVIDER_KEY)
    if company is None or conn is None:
        raise WriteConnectionError("CONNECTION_NOT_FOUND")
    try:
        assert_write_allowed(str((conn.config_json or {}).get("baseUrl") or ""))
    except WriteNotAllowed as exc:
        raise WriteConnectionError(exc.code) from None
    company.write_connection_id = conn.id
    db.commit()
    return company
