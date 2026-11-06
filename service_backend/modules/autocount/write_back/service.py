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
import time
import uuid
from datetime import date
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

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
from modules.autocount.write_back import capabilities, payloads
from modules.autocount.write_back.client import (
    AutoCountWriteClient,
    WriteTransportError,
)
from modules.autocount.write_back.constants import EDIT_PO_PATH
from modules.autocount.write_back.frame import (  # noqa: F401  (re-exported names)
    ACTION_DEADLINE_SECONDS,
    BUSY_WINDOW_SECONDS,  # noqa: F401
    DEADLINE_EXCEEDED,  # noqa: F401
    DOC_BUSY,
    DOC_KIND_MISMATCH,
    DOC_STALE,
    DOC_UNKNOWN,
    INTERNAL_ERROR,
    LOCATION_NOT_MOVED,
    OUTCOME_DONE,
    OUTCOME_MISMATCH,
    OUTCOME_PENDING,
    OUTCOME_REFUSED,
    OUTCOME_VENDOR_ERROR,
    ROW_ALREADY_AT_LOCATION,
    SO_LOCATION_AMBIGUOUS,
    VENDOR_UNSUPPORTED,
    WRITE_DISABLED,
    WriteActionResult,
    WriteFrame,
    _Stop,
    _dec,
    _doc_date,
    _lines,
    _safe_body,
    _same,
)
from modules.autocount.write_back import guard
from modules.autocount.write_back.guard import WriteConnectionError, WriteNotAllowed, assert_write_allowed
from modules.autocount.write_back.payloads import WriteRefusal
from modules.autocount.write_back.reader import AutoCountDocReader, DocReadError
from modules.autocount.write_back.primitives import vendor_message
from modules.autocount.write_back.repository import OUTCOME_IN_FLIGHT

if TYPE_CHECKING:  # operations imports this module
    from modules.autocount.write_back.operations import OperationService

logger = logging.getLogger("foundryx.autocount")

Doc = Dict[str, Any]


ACTION_LINK = "link"
ACTION_UNLINK = "unlink"
ACTION_SPO_UNLINK = "spo_unlink"
ACTION_RELOCATE = "relocate"

# vendor kind -> (action-log doc_type, staged entity type)
_PO = ("PO", ENTITY_PURCHASE_ORDER)
_SPO = ("SPO", ENTITY_SHIPPING_ORDER)
_SO = ("SO", ENTITY_SALES_ORDER)

_VERIFY_FIELDS = ("ItemCode", "Location", "UOM", "Qty")
_UNTOUCHED_FIELDS = payloads.ROW_KEYS + ("FromSODtlKey",)
_MAX_TEXT = 2000




class _SkipMove(Exception):
    """Internal: the location move is not attempted (deadline passed)."""




@dataclass
class _Plan:
    """What one flow needs: the action, the PO-side document and the builder."""

    action: str
    kind: Tuple[str, str]
    doc_key: int
    dtl_key: int
    so_doc_key: Optional[int] = None
    so_dtl_key: Optional[int] = None
    qty: Optional[Decimal] = None
    so_doc_date: Optional[date] = None  # AC-57-44: DocDate of an SO that is not staged
    doc_date: Optional[date] = None  # the caller's DocDate of the PO / SPO side when it is not staged










def _expected_link(row: Doc, is_spo: bool) -> int:
    """The link key the row must read back with: on a PO row AutoCount moves an
    SO link into ``FromSODtlKey``; an SPO row keeps ``FromDocDtlKey``."""
    if is_spo:
        return int(row.get("FromDocDtlKey") or 0)
    return int(row.get("FromDocDtlKey") or 0) if row.get("FromDocType") == "SO" else 0


_HEADER_FREE_PREFIXES = ("LastModified", "Created")
_HEADER_FREE_TOTALS = frozenset({
    "Total", "NetTotal", "LocalNetTotal", "Tax", "LocalTax", "ExTax", "LocalExTax",
    "TotalExTax", "TaxableAmt", "LocalTaxableAmt", "FinalTotal", "RoundAdj",
})


def _header_unchanged(before: Doc, after: Doc, body: Doc) -> bool:
    """Every header field read before the write (and every one we sent) reads
    back unchanged, except the audit stamps and the vendor-computed totals."""
    keys = {k for k in list(before) + list(body) if k != "Details"}
    for key in keys:
        if key.startswith(_HEADER_FREE_PREFIXES) or key in _HEADER_FREE_TOTALS:
            continue
        expected = body[key] if key in body else before.get(key)
        if not _same(expected, after.get(key)):
            return False
    return True


def _row_ok(sent: Doc, got: Doc, is_spo: bool, check_location: bool = True) -> bool:
    fields = _VERIFY_FIELDS if check_location else tuple(f for f in _VERIFY_FIELDS if f != "Location")
    if not all(_same(sent.get(k), got.get(k)) for k in fields):
        return False
    key = "FromDocDtlKey" if is_spo else "FromSODtlKey"
    return int(got.get(key) or 0) == _expected_link(sent, is_spo)


def verify_readback(
    before: Doc, after: Doc, body: Doc, *, ignore_new_row_location: bool = False
) -> bool:
    """AC-55-22: every sent row reads back as sent (a new row, ``DtlKey 0``,
    appears exactly once) and every untouched row reads back unchanged.
    ``ignore_new_row_location``: the vendor may force a new linked row's
    location (db3 forces HQ); the split flow moves it in a second write."""
    is_spo = before.get("ShippingPO") == "T"
    if not _header_unchanged(before, after, body):
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
    if not all(
        any(_row_ok(s, a, is_spo, not ignore_new_row_location) for a in added) for s in new_sent
    ):
        return False
    for key, row in before_rows.items():
        if key in sent_keys:
            continue
        got = after_rows.get(key)
        if got is None or not all(_same(row.get(f), got.get(f)) for f in _UNTOUCHED_FIELDS):
            return False
    return True


def verify_relocate(before: Doc, after: Doc, dtl_key: int, location: str, body: Doc) -> bool:
    """The row is at ``location`` with everything else as before, and no other
    row or header field changed."""
    if not _header_unchanged(before, after, body):
        return False
    before_rows = {r.get("DtlKey"): r for r in before.get("Details") or []}
    after_rows = {r.get("DtlKey"): r for r in after.get("Details") or []}
    if set(before_rows) != set(after_rows):
        return False
    for key, row in before_rows.items():
        got = after_rows[key]
        for field in _UNTOUCHED_FIELDS:
            want = location if key == dtl_key and field == "Location" else row.get(field)
            if not _same(want, got.get(field)):
                return False
    return True




class WriteBackService(WriteFrame):

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
        idempotency_key: Optional[str] = None,
        operations: Optional["OperationService"] = None,
        so_doc_date: Optional[date] = None,
        doc_date: Optional[date] = None,
    ) -> WriteActionResult:
        """Part of a row: the plan 55 split link (idempotent when a key is given).
        The whole row: the ``link_row`` operation (delete + add, plan 57). The gateway
        passes ``operations`` (the plan 57 service); without it the plan 55 flow runs."""
        if operations is not None:
            op = self._link_operation(operations, tenant_id, company_id, key_id, idempotency_key,
                                      po_doc_key, po_dtl_key, qty, doc_date)
            if op == "link_row":
                return self._operation(
                    operations, op, tenant_id, company_id, key_id, idempotency_key,
                    {"doc_key": po_doc_key, "dtl_key": po_dtl_key, "so_doc_key": so_doc_key,
                     "so_dtl_key": so_dtl_key, "qty": qty, "whole_row": True, "target_doc_date": so_doc_date,
                     "doc_date": doc_date,
                     "expected_last_modified": expected_last_modified},
                )
            if op == "split_link":
                return self._operation(
                    operations, op, tenant_id, company_id, key_id, idempotency_key,
                    {"po_doc_key": po_doc_key, "po_dtl_key": po_dtl_key, "so_doc_key": so_doc_key,
                     "so_dtl_key": so_dtl_key, "qty": qty, "target_doc_date": so_doc_date, "doc_date": doc_date,
                     "expected_last_modified": expected_last_modified},
                )
        plan = _Plan(ACTION_LINK, _PO, po_doc_key, po_dtl_key, so_doc_key, so_dtl_key, qty, so_doc_date, doc_date)
        return self._run(plan, tenant_id, company_id, expected_last_modified, key_id)

    def _link_operation(
        self, operations: "OperationService", tenant_id: str, company_id: str, key_id: Optional[str],
        idempotency_key: Optional[str], po_doc_key: int, po_dtl_key: int, qty: Decimal,
        doc_date: Optional[date] = None,
    ) -> Optional[str]:
        """Which operation a link request runs (AC-57-44). A stored key keeps its
        operation (a replay must not flip because the row changed since). Else the
        qty is compared with the FRESH row qty: equal = ``link_row`` (delete + add),
        anything else = the split link (an operation when a key is given, else the
        plan 55 flow). An invalid qty, or a row that cannot be read, takes the plan
        55 flow, which refuses it with its own recorded code and no further request."""
        if idempotency_key is not None:
            stored = operations.ops.by_key(tenant_id, company_id, key_id, idempotency_key)
            if stored is not None and stored.op in ("link_row", "split_link"):
                return stored.op
        fresh = self._fresh_row_qty(tenant_id, company_id, po_doc_key, po_dtl_key, qty, doc_date)
        if fresh is not None and fresh == qty:
            return "link_row"
        return "split_link" if idempotency_key is not None else None

    def _fresh_row_qty(
        self, tenant_id: str, company_id: str, po_doc_key: int, po_dtl_key: int, qty: Decimal,
        doc_date: Optional[date] = None,
    ) -> Optional[Decimal]:
        try:
            payloads.validate_qty(qty)
        except WriteRefusal:
            return None
        company = CompanyRepository(self.db).get(tenant_id, company_id)
        if company is None:
            return None
        base_url, _refusal = self._resolve_write_base_url(company)
        staged = self.staged.newest(tenant_id, company.id, _PO[1], f"{company.database_name}:{po_doc_key}")
        day = _doc_date(staged.raw_json if staged else None) or doc_date
        if base_url is None or day is None:
            return None
        self.db.commit()  # no transaction open during the GET
        try:
            fresh = self._reader_factory(base_url).get_document("PO", po_doc_key, day)
        except DocReadError:
            return None
        row = next((r for r in fresh.get("Details") or [] if r.get("DtlKey") == po_dtl_key), None)
        return None if row is None else _dec(row.get("Qty"))

    @staticmethod
    def _operation(
        operations: "OperationService", op: str, tenant_id: str, company_id: str, key_id: Optional[str],
        idempotency_key: Optional[str], params: Dict[str, Any],
    ) -> WriteActionResult:
        """Run a plan 57 operation and answer in the plan 55 shape (plus the
        operation fields); no key given = a fresh one (not idempotent, as before)."""
        result = operations.run(
            tenant_id=tenant_id, company_id=company_id, key_id=key_id,
            idempotency_key=idempotency_key or uuid.uuid4().hex, op=op, params=params,
        )
        return WriteActionResult(
            None, result.outcome, result.error_code, result.message, result.document,
            operation_id=result.operation_id, warnings=result.warnings,
            replaced_lines=result.replaced_lines, doc_key=result.doc_key, doc_no=result.doc_no,
        )

    def unlink(
        self,
        *,
        tenant_id: str,
        company_id: str,
        po_doc_key: int,
        po_dtl_key: int,
        expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        operations: Optional["OperationService"] = None,
        doc_date: Optional[date] = None,
    ) -> WriteActionResult:
        """With ``operations`` (the gateway): AutoCount never edits a link in place,
        so the ``unlink_row`` operation runs. Without it the plan 55 flow."""
        if operations is None:
            plan = _Plan(ACTION_UNLINK, _PO, po_doc_key, po_dtl_key)
            return self._run(plan, tenant_id, company_id, expected_last_modified, key_id)
        return self._operation(
            operations, "unlink_row", tenant_id, company_id, key_id, idempotency_key,
            {"doc_key": po_doc_key, "dtl_key": po_dtl_key, "doc_date": doc_date,
             "expected_last_modified": expected_last_modified},
        )

    def spo_unlink(
        self,
        *,
        tenant_id: str,
        company_id: str,
        spo_doc_key: int,
        spo_dtl_key: int,
        expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        operations: Optional["OperationService"] = None,
        doc_date: Optional[date] = None,
    ) -> WriteActionResult:
        """With ``operations``: the ``spo_unlink_row`` operation (delete + add unlinked)."""
        if operations is None:
            plan = _Plan(ACTION_SPO_UNLINK, _SPO, spo_doc_key, spo_dtl_key)
            return self._run(plan, tenant_id, company_id, expected_last_modified, key_id)
        return self._operation(
            operations, "spo_unlink_row", tenant_id, company_id, key_id, idempotency_key,
            {"spo_doc_key": spo_doc_key, "spo_dtl_key": spo_dtl_key, "doc_date": doc_date,
             "expected_last_modified": expected_last_modified},
        )

    def relocate(
        self,
        *,
        tenant_id: str,
        company_id: str,
        po_doc_key: int,
        po_dtl_key: int,
        expected_last_modified: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> WriteActionResult:
        """Move a linked PO row to its SO row's location (taken from staging)."""
        plan = _Plan(ACTION_RELOCATE, _PO, po_doc_key, po_dtl_key)
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
        self._deadline = time.monotonic() + ACTION_DEADLINE_SECONDS
        self._put_sent = False
        try:
            self._check_qty(plan, row)
            base_url = self._write_base_url(row, company)
            self._check_test_company(row, company)
            self._check_capability(plan, row)
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
            # nothing was written yet: a refusal that does not block the document
            outcome = OUTCOME_PENDING if self._put_sent else OUTCOME_REFUSED
            return self._finish(row, outcome, INTERNAL_ERROR)
        finally:
            self.db.rollback()



    def _check_capability(self, plan: _Plan, row: AcWriteAction) -> None:
        """Unlink and SPO unlink are refused outright while the vendor does not
        apply them (no request at all)."""
        flag = {ACTION_UNLINK: "unlink", ACTION_SPO_UNLINK: "spo_unlink"}.get(plan.action)
        if flag and not capabilities.VENDOR_CAPABILITIES[flag]:
            raise self._refuse(row, VENDOR_UNSUPPORTED)

    def _check_qty(self, plan: _Plan, row: AcWriteAction) -> None:
        """Quantity bounds before any document is read (H5)."""
        if plan.qty is None:
            return
        try:
            plan.qty = payloads.validate_qty(plan.qty)
        except WriteRefusal as exc:
            raise self._refuse(row, exc.code, str(exc)) from None


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




    def _execute(
        self,
        plan: _Plan,
        company: AcCompany,
        base_url: str,
        row: AcWriteAction,
        expected_last_modified: Optional[str],
    ) -> WriteActionResult:
        reader = self._reader_factory(base_url)
        doc = self._read_fresh(plan.kind, plan.doc_key, company, row, reader, plan.doc_date)
        if expected_last_modified and doc.get("LastModified") != expected_last_modified:
            raise self._refuse(row, DOC_STALE)
        if plan.action == ACTION_LINK:
            self._gate_whole_row(plan, company, doc, row)
        so_doc = None
        if plan.so_doc_key is not None:
            so_doc = self._read_fresh(_SO, plan.so_doc_key, company, row, reader, plan.so_doc_date)
        body = self._build(plan, company, row, doc, so_doc)
        row.before_json = doc
        row.request_json = body
        self.db.commit()  # in_flight + body committed before any PUT (AC-55-27)
        return self._put_and_verify(plan, company, base_url, row, reader, doc, body, so_doc)

    def _gate_whole_row(
        self, plan: _Plan, company: AcCompany, doc: Doc, row: AcWriteAction
    ) -> None:
        """A link of the whole PO row edits an existing row, which the vendor does
        not apply (unless flipped on or emulated): refused after the one PO read.
        A request the staged SO row already shows to be over its outstanding keeps
        its own refusal (``QTY_ABOVE_OUTSTANDING``) from the normal flow."""
        if not self._whole_row_unsupported(plan, doc):
            return
        if self._staged_over_outstanding(plan, company, doc):
            return
        raise self._refuse(row, VENDOR_UNSUPPORTED)

    def _whole_row_unsupported(self, plan: _Plan, doc: Doc) -> bool:
        """The link covers the whole PO row while neither the vendor capability
        nor the zero-qty emulation is on."""
        po_row = next(
            (r for r in doc.get("Details") or [] if r.get("DtlKey") == plan.dtl_key), None
        )
        if po_row is None or plan.qty is None or _dec(po_row.get("Qty")) != plan.qty:
            return False
        return not (
            capabilities.VENDOR_CAPABILITIES["link_existing_row"] or capabilities.ZERO_QTY_EMULATION
        )

    def _staged_over_outstanding(self, plan: _Plan, company: AcCompany, doc: Doc) -> bool:
        so_ref = f"{company.database_name}:{plan.so_doc_key}"
        staged = self.staged.newest(company.tenant_id, company.id, ENTITY_SALES_ORDER, so_ref)
        so_row = next((r for r in _lines(staged.raw_json if staged else None) if r.get("DtlKey") == plan.so_dtl_key), None)
        if so_row is None or plan.so_dtl_key is None or plan.qty is None:
            return False
        linked = self._so_linked_qty(company, doc, plan.so_dtl_key)
        return plan.qty > payloads.so_outstanding(so_row, linked)

    def _read_fresh(
        self,
        kind: Tuple[str, str],
        doc_key: int,
        company: AcCompany,
        row: AcWriteAction,
        reader: AutoCountDocReader,
        date_hint: Optional[date] = None,
    ) -> Doc:
        ref = f"{company.database_name}:{doc_key}"
        staged = self.staged.newest(company.tenant_id, company.id, kind[1], ref)
        doc_date = _doc_date(staged.raw_json if staged else None) or date_hint
        if doc_date is None:
            raise self._refuse(row, self._missing_code(kind, company, ref))
        self._check_deadline(row)
        self.db.commit()  # no transaction open during the GET (AC-55-27)
        try:
            return reader.get_document(kind[0], doc_key, doc_date)
        except DocReadError as exc:
            raise self._refuse(row, exc.code) from None

    def _missing_code(self, kind: Tuple[str, str], company: AcCompany, ref: str) -> str:
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
            if plan.action == ACTION_RELOCATE:
                return payloads.build_relocate(
                    doc, plan.dtl_key, self._so_location(company, doc, plan.dtl_key), spo_ref=spo_ref
                )
            if plan.action == ACTION_UNLINK:
                return payloads.build_unlink(doc, plan.dtl_key, spo_ref=spo_ref)
            assert so_doc is not None and plan.so_dtl_key is not None and plan.qty is not None
            linked = self._so_linked_qty(company, doc, plan.so_dtl_key)
            body = payloads.build_link(
                doc, plan.dtl_key, so_doc, plan.so_dtl_key, plan.qty,
                so_linked_qty=linked, spo_ref=spo_ref,
                whole_row_as_split=capabilities.ZERO_QTY_EMULATION
                and not capabilities.VENDOR_CAPABILITIES["link_existing_row"],
            )
            if self._whole_row_unsupported(plan, doc):
                raise WriteRefusal(VENDOR_UNSUPPORTED, "whole-row link not applied by the vendor")
            return body
        except WriteRefusal as exc:
            raise self._refuse(row, exc.code, str(exc)) from None

    def _so_location(self, company: AcCompany, po: Doc, dtl_key: int) -> str:
        """Location of the SO row the PO row links to, from the NEWEST staged SO
        record that holds that DtlKey; equally new records that disagree refuse
        ``SO_LOCATION_AMBIGUOUS``. Empty when the row is not linked or unstaged."""
        po_row = next((r for r in po.get("Details") or [] if r.get("DtlKey") == dtl_key), None)
        so_key = (po_row or {}).get("FromSODtlKey")
        if not so_key:
            return ""
        found = []
        for staged in self.staged.for_entity(company.tenant_id, company.id, ENTITY_SALES_ORDER):
            for line in _lines(staged.raw_json):
                if line.get("DtlKey") == so_key:
                    found.append((staged.created_at, str(line.get("Location") or "")))
        if not found:
            return ""
        newest = max(created for created, _loc in found)
        locations = {loc for created, loc in found if created == newest}
        if len(locations) > 1:
            raise WriteRefusal(SO_LOCATION_AMBIGUOUS, "staged sales order copies disagree")
        return locations.pop()

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
        so_doc: Optional[Doc] = None,
    ) -> WriteActionResult:
        client = self._client_factory(base_url)
        self._check_deadline(row)
        self._put_sent = True
        try:
            response = client.put(EDIT_PO_PATH, body)  # never retried
        except WriteTransportError as exc:
            return self._finish(row, OUTCOME_PENDING, exc.code)
        row.response_status = response.status_code
        # a failure keeps its status and the redacted text only (AC-57-47); a success as it came
        row.response_json = _safe_body(response.body) if response.ok else {"text": vendor_message(response.body, base_url)}
        if not response.ok:  # carry AutoCount's own (redacted, capped) text to the answer
            return self._finish(
                row, OUTCOME_VENDOR_ERROR, "VENDOR_ERROR", message=row.response_json["text"]
            )
        self.db.commit()
        self._check_deadline(row)
        after = self._read_back(plan, reader, before)
        if isinstance(after, WriteActionResult):
            return self._finish(row, OUTCOME_PENDING, after.error_code)
        row.after_json = after  # a read-back in hand is always verified, whatever the clock says
        is_split = plan.action == ACTION_LINK and any(
            not r.get("DtlKey") for r in body.get("Details") or []
        )
        if plan.action == ACTION_RELOCATE:
            ok = verify_relocate(
                before, after, plan.dtl_key, str(body["Details"][0].get("Location")), body
            )
        else:
            ok = verify_readback(before, after, body, ignore_new_row_location=is_split)
        if not ok:
            return self._finish(row, OUTCOME_MISMATCH, "READBACK_MISMATCH")
        if is_split and so_doc is not None and plan.so_dtl_key is not None:
            return self._finish_split(plan, company, client, row, reader, before, after, body, so_doc)
        result = self._finish(row, OUTCOME_DONE, document=after)
        self._stage(company, plan.kind[0], after)
        return result

    def _read_back(
        self, plan: _Plan, reader: AutoCountDocReader, before: Doc
    ) -> "Doc | WriteActionResult":
        """The document as it reads now, or a pending result naming why not."""
        doc_date = _doc_date(before)
        if doc_date is None:
            return WriteActionResult(None, OUTCOME_PENDING, "READ_FAILED")
        try:
            return reader.get_document(plan.kind[0], plan.doc_key, doc_date)
        except DocReadError as exc:
            return WriteActionResult(None, OUTCOME_PENDING, exc.code)

    def _finish_split(
        self,
        plan: _Plan,
        company: AcCompany,
        client: AutoCountWriteClient,
        row: AcWriteAction,
        reader: AutoCountDocReader,
        before: Doc,
        after1: Doc,
        body1: Doc,
        so_doc: Doc,
    ) -> WriteActionResult:
        """Second write of a split link: move the vendor-placed new row to the SO
        row's location. Any failure there is ``done`` with ``LOCATION_NOT_MOVED``
        (the link stands; the write is never retried)."""
        target = next(
            (r.get("Location") for r in so_doc.get("Details") or [] if r.get("DtlKey") == plan.so_dtl_key),
            None,
        )
        before_keys = {r.get("DtlKey") for r in before.get("Details") or []}
        new_row = next(
            (
                r for r in after1.get("Details") or []
                if r.get("DtlKey") not in before_keys and r.get("FromSODtlKey") == plan.so_dtl_key
            ),
            None,
        )
        if new_row is None or not target or new_row.get("Location") == target:
            result = self._finish(row, OUTCOME_DONE, document=after1)
            self._stage(company, plan.kind[0], after1)
            return result
        body2 = payloads.build_relocate(after1, int(new_row["DtlKey"]), str(target))
        first_status = row.response_status
        row.request_json = [body1, body2]
        row.response_json = [row.response_json, None]
        row.response_status = [first_status, None]
        row.after_json = [after1, None]
        self.db.commit()  # no transaction open during the second write
        final, code = after1, LOCATION_NOT_MOVED
        # The link is verified: past the deadline the move is simply not attempted
        # (no vendor call after it) and the action still ends done.
        try:
            if self._expired():
                raise _SkipMove()
            response = client.put(EDIT_PO_PATH, body2)  # never retried
        except _SkipMove:
            pass
        except WriteTransportError as exc:
            row.response_json = [row.response_json[0], {"error": exc.code}]
        else:
            row.response_json = [
                row.response_json[0],
                _safe_body(response.body) if response.ok
                else {"text": vendor_message(response.body, getattr(client, "base_url", ""))},
            ]
            row.response_status = [first_status, response.status_code]
            if response.ok and not self._expired():
                self.db.commit()
                after2 = self._read_back(plan, reader, before)
                if not isinstance(after2, WriteActionResult):
                    row.after_json = [after1, after2]
                    final = after2
                    if verify_relocate(after1, after2, int(new_row["DtlKey"]), str(target), body2):
                        code = None
                    elif next(
                        (r for r in after2.get("Details") or [] if r.get("DtlKey") == new_row["DtlKey"]), {}
                    ).get("Location") == target:
                        self.db.commit()
                        return self._finish(row, OUTCOME_MISMATCH, "READBACK_MISMATCH")
        result = self._finish(row, OUTCOME_DONE, code, document=final)
        self._stage(company, plan.kind[0], final)
        return result

    # ── staging + push ───────────────────────────────────────────────────────



def set_write_connection(
    db: Session, *, tenant_id: str, company_id: str, connection_id: str
) -> AcCompany:
    """Point a company's writes at a connection: same-tenant ``autocount``
    connection whose base URL passes the write guard (db3 only), else a
    ``WriteConnectionError`` with the company unchanged."""
    company = CompanyRepository(db).get(tenant_id, company_id)
    if company is None:
        raise WriteConnectionError("CONNECTION_NOT_FOUND")
    # AC-57-22: company-scoped data first. A company that reads SQL, or already holds
    # documents staged by another job, is a live book: it never gets a write connection.
    guard.assert_test_company(db, tenant_id, company.id)
    conn = ConnectionRepository(db).get_for_provider(tenant_id, connection_id, PROVIDER_KEY)
    if conn is None:
        raise WriteConnectionError("CONNECTION_NOT_FOUND")
    try:
        assert_write_allowed(str((conn.config_json or {}).get("baseUrl") or ""))
    except WriteNotAllowed as exc:
        raise WriteConnectionError(exc.code) from None
    company.write_connection_id = conn.id
    db.commit()
    return company
