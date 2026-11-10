"""Pure PO link / split / unlink payload builders (plan 55 section 6b, AC-55-10..16).

Inputs are the vendor documents as read back from AutoCount (dicts); nothing is
mutated. Only whitelisted header and row fields are sent, and only the touched
rows appear in ``Details``. Quantities are computed in ``Decimal``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from modules.autocount.write_back import capabilities
from modules.autocount.write_back.doc_kinds import DocKind, kind_of

Doc = Dict[str, Any]

HEADER_KEYS = (
    "DocKey", "DocNo", "DocDate", "CreditorCode", "CreditorName", "Ref", "Description",
    "DisplayTerm", "PurchaseAgent", "InvAddr1", "InvAddr2", "InvAddr3", "InvAddr4",
    "Phone1", "Fax1", "Attention", "BranchCode", "DeliverAddr1", "DeliverAddr2",
    "DeliverAddr3", "DeliverAddr4", "DeliverPhone1", "DeliverFax1", "DeliverContact",
    "CurrencyCode", "CurrencyRate", "Remark1", "Remark2", "Remark3", "Remark4",
    "RefDocNo", "ShipVia", "ShipInfo", "InclusiveTax",
)
# The SO header fields a create may carry (YourPODate and every total/audit field excluded).
SO_HEADER_KEYS = (
    "DocNo", "DocDate", "DebtorCode", "DebtorName", "Ref", "Description", "DisplayTerm",
    "SalesAgent", "InvAddr1", "InvAddr2", "InvAddr3", "InvAddr4", "Phone1", "Fax1",
    "Attention", "BranchCode", "DeliverAddr1", "DeliverAddr2", "DeliverAddr3", "DeliverAddr4",
    "DeliverPhone1", "DeliverFax1", "DeliverContact", "CurrencyCode", "CurrencyRate",
    "Remark1", "Remark2", "Remark3", "Remark4", "RefDocNo", "ShipVia", "ShipInfo",
    "InclusiveTax",
)
ROW_KEYS = (
    "DtlKey", "ItemCode", "Location", "Description", "ProjNo", "UOM", "UserUOM", "Qty",
    "FOCQty", "UnitPrice", "Discount", "TaxCode", "DeliveryDate", "Desc2", "FromDocType",
    "FromDocNo", "FromDocDtlKey", "FullTransferOption", "FullTransferFromDocList",
)


class WriteRefusal(Exception):
    """A request the builders refuse; ``code`` is stable, the text is operator-safe."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _num(value: Decimal) -> float:
    return float(value)


def so_outstanding(so_row: Doc, linked_qty: Decimal) -> Decimal:
    """SO row qty not yet transferred to a PO row, never below zero."""
    return max(_dec(so_row.get("Qty")) - linked_qty, Decimal(0))


_DATE_PREFIX = re.compile(r"^(\d{4})-\d{2}-\d{2}(?:$|[T ])")
# The wrapper's SQL Server floor: it answers 500 (SqlDateTime overflow) to any
# date below it, and reads an empty date back as 0001-01-01T00:00:00.
MIN_VENDOR_YEAR = 1753


def _empty_date(value: Any) -> bool:
    match = _DATE_PREFIX.match(value) if isinstance(value, str) else None
    return bool(match) and int(match.group(1)) < MIN_VENDOR_YEAR


def _pick(source: Doc, keys: Sequence[str]) -> Doc:
    """Whitelisted fields of ``source``; a date the vendor cannot take back
    (year below 1753) is omitted, a missing one stays missing. The one place
    that rule lives."""
    return {k: source[k] for k in keys if k in source and not _empty_date(source[k])}


# Header fields that hold an AutoCount master-file code (agent, terms, branch,
# currency, ship-via, party). AutoCount reads a blank one back as "" but answers 500
# "The value of column X ... does not exist in its master file" when "" is sent back
# (db3 6 Nov, PO DocKey 12127). A blank one is omitted so the vendor keeps its own value.
MASTER_REF_HEADER_KEYS = frozenset((
    "PurchaseAgent", "SalesAgent", "DisplayTerm", "BranchCode", "CurrencyCode", "ShipVia",
    "CreditorCode", "DebtorCode",
))


def _blank_text(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _pick_header(source: Doc, keys: Sequence[str]) -> Doc:
    """``_pick`` for a document header: also omits a blank master-reference code."""
    return {
        k: v for k, v in _pick(source, keys).items()
        if not (k in MASTER_REF_HEADER_KEYS and _blank_text(v))
    }


def _header(doc: Doc) -> Doc:
    return _pick_header(doc, HEADER_KEYS)


def so_header_of(doc: Doc) -> Doc:
    """The whitelisted header of an existing SO (a template for a new one); dates
    below 1753 are omitted like everywhere else."""
    return _pick_header(doc, SO_HEADER_KEYS)


def header_of(doc: Doc) -> Doc:
    """The whitelisted header of an existing document (a template for a new one)."""
    return _header(doc)


def _row_fields(row: Doc) -> Doc:
    return _pick(row, ROW_KEYS)


def _is_spo(doc: Doc) -> bool:
    return doc.get("ShippingPO") == "T"


def _check_doc(doc: Doc, want_spo: bool) -> None:
    if _is_spo(doc) != want_spo:
        raise WriteRefusal("DOC_KIND_MISMATCH", "wrong document kind")
    if doc.get("Cancelled") == "T":
        raise WriteRefusal("DOC_CANCELLED", "document is cancelled")


def _find_row(doc: Doc, dtl_key: int) -> Doc:
    for row in doc.get("Details") or []:
        if row.get("DtlKey") == dtl_key:
            return row
    raise WriteRefusal("ROW_NOT_FOUND", f"row {dtl_key} not found")


def _row_linked(row: Doc) -> bool:
    """Linked to an SO row (the only link a PO row write touches)."""
    return bool(row.get("FromSODtlKey"))


def _refuse_other_transfer(row: Doc) -> None:
    """A row transferred from some other document type (PO, QT, ...) is not ours to rewrite."""
    if row.get("FromDocType") not in ("", None, "SO"):
        raise WriteRefusal("ROW_HAS_OTHER_TRANSFER", "row comes from another document type")


# Plan 61 (db3 10 Nov, F3..F8): a row sent with ``FullTransferOption "D"`` is deleted, a
# row with ``DtlKey 0`` is added, both in ONE PUT that AutoCount applies all or nothing.
# Every other row SS sends is a normal row (AC-61-16).
DELETE_ROW = "D"
_NORMAL_ROW = {"FullTransferOption": " ", "FullTransferFromDocList": ""}
NORMAL_ROW_KEYS = tuple(_NORMAL_ROW)


def _normal(row: Doc) -> Doc:
    """``row`` as a normal (not deleted, not transferred-from-list) row (AC-61-16)."""
    row.update(_NORMAL_ROW)
    return row


def _deleted(row: Doc) -> Doc:
    """The row exactly as read, marked for deletion."""
    out = _row_fields(row)
    out["FullTransferOption"] = DELETE_ROW
    return out


def _refuse_on_spo(spo_ref: Optional[str]) -> None:
    if spo_ref:
        raise WriteRefusal("ROW_ON_SPO", f"row is referenced by {spo_ref}; unlink it there first")


MAX_QTY = Decimal(1_000_000_000)
_QTY_PLACES = Decimal("1E-8")


def validate_qty(qty: Decimal) -> Decimal:
    """The quantity at the vendor's 8 places, or ``QTY_INVALID``: not above zero,
    above 1e9, or changed by the rounding (never a silent rewrite)."""
    if not qty.is_finite() or qty <= 0 or qty > MAX_QTY:
        raise WriteRefusal("QTY_INVALID", "quantity out of range")
    try:
        quantized = qty.quantize(_QTY_PLACES)
    except InvalidOperation:
        raise WriteRefusal("QTY_INVALID", "quantity out of range") from None
    if quantized != qty:
        raise WriteRefusal("QTY_INVALID", "quantity has more than 8 decimal places")
    return quantized


def build_link(
    po: Doc,
    po_dtl_key: int,
    so: Doc,
    so_dtl_key: int,
    qty: Decimal,
    *,
    so_linked_qty: Decimal = Decimal(0),
    spo_ref: Optional[str] = None,
) -> Doc:
    """Link ``qty`` of a PO row to an SO row in ONE PUT. AutoCount never links an
    existing row, so the whole row is replaced (the row ``"D"`` plus a new linked row,
    plan 61 F5) and part of it is split (the row cut to the rest plus a new linked row).
    The new row asks for the SO row's location; AutoCount forces HQ and the caller
    moves it back in a second write."""
    _check_doc(po, want_spo=False)
    if so.get("Cancelled") == "T":
        raise WriteRefusal("DOC_CANCELLED", "sales order is cancelled")
    po_row = _find_row(po, po_dtl_key)
    so_row = _find_row(so, so_dtl_key)
    _refuse_on_spo(spo_ref)
    _refuse_other_transfer(po_row)
    if _row_linked(po_row):
        raise WriteRefusal("ROW_ALREADY_LINKED", "row is already linked")
    if po_row.get("ItemCode") != so_row.get("ItemCode"):
        raise WriteRefusal("ITEM_MISMATCH", "item differs")
    if po_row.get("UOM") != so_row.get("UOM"):
        raise WriteRefusal("UOM_MISMATCH", "unit of measure differs")
    qty = validate_qty(qty)
    free = _dec(po_row.get("Qty"))
    if qty > free:
        raise WriteRefusal("QTY_ABOVE_FREE", "quantity above the PO row quantity")
    if qty > so_outstanding(so_row, so_linked_qty):
        raise WriteRefusal("QTY_ABOVE_OUTSTANDING", "quantity above the SO row outstanding")
    link = {
        "FromDocType": "SO",
        "FromDocNo": so.get("DocNo"),
        "FromDocDtlKey": so_dtl_key,
        "Location": so_row.get("Location"),
    }
    body = _header(po)
    new = _normal(_row_fields(po_row))
    new.update(link, DtlKey=0, Qty=_num(qty), FOCQty=0)
    if qty == free:
        body["Details"] = [_deleted(po_row), new]
        return body
    edited = _normal(_row_fields(po_row))
    edited["Qty"] = _num(free - qty)
    body["Details"] = [edited, new]
    return body


def build_relocate(po: Doc, po_dtl_key: int, location: Optional[str], *, spo_ref: Optional[str] = None) -> Doc:
    """Move one LINKED PO row to ``location``: the row exactly as read, only its
    location changed (the vendor keeps the link of an edited existing row)."""
    _check_doc(po, want_spo=False)
    row = _find_row(po, po_dtl_key)
    _refuse_on_spo(spo_ref)
    if not _row_linked(row):
        raise WriteRefusal("ROW_NOT_LINKED", "row is not linked")
    if not location:
        raise WriteRefusal("DOC_UNKNOWN", "the linked sales order row is not in the synced copy")
    if row.get("Location") == location:
        raise WriteRefusal("ROW_ALREADY_AT_LOCATION", "row is already at that location")
    moved = _normal(_row_fields(row))
    moved["Location"] = location
    body = _header(po)
    body["Details"] = [moved]
    return body


# B4 (db3 6 Nov; test report 2026-11-04 P6/P10/C03): AutoCount stores a NEW row
# transferred from an SO with Location HQ, UnitPrice 0 and an empty DeliveryDate,
# whatever the split body sent. An edit of the EXISTING row afterwards keeps the link
# (probe P4), so the split flow restores these in its second write.
TRANSFER_RESET_FIELDS = ("Location", "UnitPrice", "DeliveryDate")


def _day(value: Any) -> Optional[str]:
    """A date as its ``YYYY-MM-DD`` day; empty and pre-1753 dates are None."""
    if not isinstance(value, str) or not value.strip() or _empty_date(value):
        return None
    return value[:10]


def day_of(value: Any) -> Optional[str]:
    """The ``YYYY-MM-DD`` day of a vendor date; None when empty or below 1753."""
    return _day(value)


def same_row_value(field_name: str, want: Any, got: Any) -> bool:
    """Row field equality for verify: dates by day (empty = empty), numbers by value."""
    if field_name == "DeliveryDate":
        return _day(want) == _day(got)
    return _same(want, got)


def transfer_restore(source: Mapping[str, Any], location: Optional[str]) -> Doc:
    """The ``TRANSFER_RESET_FIELDS`` values a new SO-linked PO row must get back after
    AutoCount reset them (F5): ``source``'s price and delivery date, at ``location``
    (when given). The one rule the split link and the row operations share."""
    wanted: Doc = {k: source[k] for k in TRANSFER_RESET_FIELDS if k in source}
    if location:
        wanted["Location"] = location
    else:
        wanted.pop("Location", None)
    return wanted


def transfer_row_drift(sent: Mapping[str, Any], got: Doc) -> Doc:
    """The ``TRANSFER_RESET_FIELDS`` the read-back row lost: ``{field: sent value}``.
    A field not sent (or an empty sent date) is never asked back."""
    out: Doc = {}
    for key in TRANSFER_RESET_FIELDS:
        if key not in sent or (key == "DeliveryDate" and _day(sent[key]) is None):
            continue
        if not same_row_value(key, sent[key], got.get(key)):
            out[key] = sent[key]
    return out


def build_restore_transfer_row(po: Doc, dtl_key: int, values: Mapping[str, Any]) -> Doc:
    """Second write of a split link: the new row exactly as read, with ``values``
    (location, unit price, delivery date) set back to what the split sent."""
    if not values:
        raise WriteRefusal("NO_CHANGE", "nothing to restore")
    row = _normal(_row_fields(_find_row(po, dtl_key)))
    row.update(values)
    body = _header(po)
    if _is_spo(po):
        body["ShippingPO"] = "T"
    body["Details"] = [row]
    return body


NO_LINK: Doc = {"FromDocType": "", "FromDocNo": "", "FromDocDtlKey": 0}


def build_unlink_row(po: Doc, po_dtl_key: int, *, spo_ref: Optional[str] = None) -> Doc:
    """Unlink one PO row in ONE PUT (plan 61 F4, AC-61-11): the linked row ``"D"`` plus
    a new normal row with the same item, qty, price, UOM, location and delivery date.
    AutoCount never clears a link in place (db3 4 Nov), so there is no blank-link PUT."""
    _check_doc(po, want_spo=False)
    row = _find_row(po, po_dtl_key)
    _refuse_on_spo(spo_ref)
    _refuse_other_transfer(row)
    if not _row_linked(row):
        raise WriteRefusal("ROW_NOT_LINKED", "row is not linked")
    new = {k: v for k, v in row.items() if k != "DtlKey"}
    new.update(NO_LINK)
    return build_row_replace("PO", po, row, new).body or {}


# ── plan 57 level-1 primitive builders (AC-57-10..18) ───────────────────────────

@dataclass(frozen=True)
class VendorRequest:
    method: str
    path: str
    body: Optional[Doc]
    params: Optional[Dict[str, str]] = None  # a query string, encoded by the client (cancel only)


@dataclass
class Verdict:
    """A verifier answer: ``outcome`` "done" | "mismatch"; ``code`` names why."""

    outcome: str
    code: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    message: str = ""


DONE = "done"
MISMATCH = "mismatch"

NEW_DOCNO = "<<New>>"
LINK_UNCONFIRMED = "QT_ROW_LINK_UNCONFIRMED"
# Header fields a create may carry, any kind (party and DocNo handled by the kind).
CREATE_HEADER_KEYS = tuple(
    dict.fromkeys(HEADER_KEYS + SO_HEADER_KEYS + ("YourPONo",))
)
CREATE_HEADER_KEYS = tuple(k for k in CREATE_HEADER_KEYS if k != "DocKey")
# Header fields an edit may change (AC-57-14).
EDIT_HEADER_KEYS = (
    "Ref", "Description", "Remark1", "Remark2", "Remark3", "Remark4", "DisplayTerm",
    "SalesAgent", "PurchaseAgent", "YourPONo", "InvAddr1", "InvAddr2", "InvAddr3", "InvAddr4",
    "DeliverAddr1", "DeliverAddr2", "DeliverAddr3", "DeliverAddr4",
)
# Line fields an edit may change, by DtlKey.
EDIT_LINE_KEYS = ("Qty", "UnitPrice", "Discount", "Location", "Description", "DeliveryDate")
LINE_KEYS = tuple(k for k in ROW_KEYS if k != "DtlKey") + ("YourPONo",)
REQUIRED_HEADER = ("DocDate", "DisplayTerm", "CurrencyCode", "CurrencyRate")
# SS-QTSO-DISPLAYTERM: kinds whose blank DisplayTerm is filled from the debtor's own
# AutoCount term (the caller - the CRM - has no debtor credit term).
TERM_FROM_DEBTOR_KINDS = ("QT", "SO")
DEBTOR_TERM_MISSING = "DEBTOR_TERM_MISSING"
_TERM_PLACEHOLDER = "<<debtor term>>"
REQUIRED_LINE = ("ItemCode", "UOM", "Qty", "UnitPrice", "Location")
# Compared before / after to prove an edit touched nothing else.
_COMPARE_HEADER = ("DocNo", "DocDate", "DebtorCode", "CreditorCode", "Cancelled") + EDIT_HEADER_KEYS
_COMPARE_LINE = ("ItemCode", "UOM", "Qty", "UnitPrice", "Discount", "Location", "Description", "DeliveryDate")


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _plain(value: Any) -> Any:
    """JSON-safe copy of a value (Decimal -> float)."""
    return float(value) if isinstance(value, Decimal) else value


def _num_of(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = Decimal(str(value))
    except InvalidOperation:
        return None
    return out if out.is_finite() else None


def _same(a: Any, b: Any) -> bool:
    na, nb = _num_of(a), _num_of(b)
    if na is not None and nb is not None and not isinstance(a, str) and not isinstance(b, str):
        return na == nb
    return a == b


def _check_kind_doc(kind: DocKind, doc: Doc, *, cancelled_ok: bool = False) -> None:
    if kind.name in ("PO", "SPO") and _is_spo(doc) != (kind.name == "SPO"):
        raise WriteRefusal("DOC_KIND_MISMATCH", "wrong document kind")
    if not cancelled_ok and doc.get("Cancelled") == "T":
        raise WriteRefusal("DOC_CANCELLED", "document is cancelled")


def _check_line(line: Mapping[str, Any]) -> None:
    for key in REQUIRED_LINE:
        if _blank(line.get(key)):
            raise WriteRefusal("FIELD_REQUIRED", key)
    qty, price = _num_of(line.get("Qty")), _num_of(line.get("UnitPrice"))
    if qty is None or qty <= 0:
        raise WriteRefusal("FIELD_REQUIRED", "Qty must be above zero")
    if price is None or price < 0:
        raise WriteRefusal("FIELD_REQUIRED", "UnitPrice must not be negative")


# AC-57-45: the vendor row shape a kind always gets (db3 answers 200 and DROPS a thin row,
# live run 4 Nov). The caller's values win; these only fill what is absent.
_ROW_DEFAULTS: Doc = {"ProjNo": "", "FOCQty": 0, "Discount": "", "TaxCode": "", "Desc2": ""}
_TRANSFER_DEFAULTS: Doc = {"YourPONo": "", "FromDocType": "", "FromDocNo": "", "FromDocDtlKey": 0}


def _vendor_line(line: Mapping[str, Any], dtl_key: Optional[int] = None, kind: str = "QT") -> Doc:
    out = {k: _plain(v) for k, v in _pick(dict(line), LINE_KEYS).items()}
    defaults = dict(_ROW_DEFAULTS)
    if kind != "QT":
        defaults.update(_TRANSFER_DEFAULTS)
    for key, value in defaults.items():
        out.setdefault(key, value)
    _normal(out)  # AC-61-16: every row SS sends is a normal row, QT too
    if dtl_key is not None:
        out["DtlKey"] = dtl_key
    return out


def _doc_header(kind: DocKind, doc: Doc) -> Doc:
    body = _pick_header(doc, ("DocKey",) + CREATE_HEADER_KEYS)
    if kind.name == "SPO":
        body["ShippingPO"] = "T"
    return body


def build_create(kind_name: str, header: Mapping[str, Any], lines: Optional[Sequence[Mapping[str, Any]]]) -> VendorRequest:
    kind = kind_of(kind_name)
    clean = _pick_header(dict(header), CREATE_HEADER_KEYS)
    for key in REQUIRED_HEADER + (kind.party_field,):
        if _blank(clean.get(key)):
            raise WriteRefusal("FIELD_REQUIRED", key)
    if not lines:
        raise WriteRefusal("FIELD_REQUIRED", "Details")
    for ln in lines:
        _check_line(ln)
    if _blank(clean.get("DocNo")):
        if not capabilities.AUTO_DOCNO:
            raise WriteRefusal("DOCNO_REQUIRED", "a document number is required")
        clean["DocNo"] = NEW_DOCNO
    body: Doc = {k: _plain(v) for k, v in clean.items()}
    if kind.name in ("PO", "SPO"):
        body["ShippingPO"] = "T" if kind.name == "SPO" else "F"
    body["Details"] = [_vendor_line(ln, None, kind.name) for ln in lines]
    return VendorRequest("POST", kind.new_path, body)


def create_needs_debtor_term(
    kind_name: str, header: Mapping[str, Any], lines: Optional[Sequence[Mapping[str, Any]]]
) -> bool:
    """True when a QT / SO create carries no DisplayTerm and is otherwise complete
    (every other refusal - FIELD_REQUIRED, DOCNO_REQUIRED - wins first, so a bad
    request never costs a debtor read)."""
    if kind_name not in TERM_FROM_DEBTOR_KINDS or not _blank(header.get("DisplayTerm")):
        return False
    build_create(kind_name, {**header, "DisplayTerm": _TERM_PLACEHOLDER}, lines)
    return True


def edit_needs_debtor_term(kind_name: str, doc: Doc, header_changes: Mapping[str, Any]) -> bool:
    """True when a QT / SO edit would send a blank DisplayTerm: the caller blanks it,
    or leaves it and the document has none."""
    if kind_name not in TERM_FROM_DEBTOR_KINDS:
        return False
    term = header_changes["DisplayTerm"] if "DisplayTerm" in header_changes else doc.get("DisplayTerm")
    return _blank(term)


_ANSWER = re.compile(r"DocNo=(.+?)\s*,DocKey=(\d+)")


def parse_create_answer(text: object) -> Optional[Tuple[str, int]]:
    """``(DocNo, DocKey)`` from the 2xx answer text, or None when it is not that shape."""
    if not isinstance(text, str):
        return None
    match = _ANSWER.search(text)
    if match is None or not match.group(1).strip():
        return None
    return match.group(1).strip(), int(match.group(2))


def check_edit_values(line_changes: Sequence[Mapping[str, Any]]) -> None:
    """``QTY_INVALID`` / ``PRICE_INVALID`` for a changed quantity or unit price, before
    any document is read."""
    for change in line_changes:
        if "Qty" in change:
            validate_qty(_dec(change["Qty"]))
        if "UnitPrice" in change:
            price = _num_of(change["UnitPrice"])
            if price is None or price < 0:
                raise WriteRefusal("PRICE_INVALID", "unit price must not be negative")


def build_edit(
    kind_name: str,
    doc: Doc,
    header_changes: Mapping[str, Any],
    line_changes: Sequence[Mapping[str, Any]],
) -> VendorRequest:
    kind = kind_of(kind_name)
    _check_kind_doc(kind, doc)
    for key in header_changes:
        if key not in EDIT_HEADER_KEYS:
            raise WriteRefusal("FIELD_NOT_EDITABLE", key)
    body = _doc_header(kind, doc)
    body.update({k: _plain(v) for k, v in header_changes.items()})
    details: List[Doc] = []
    for change in line_changes:
        row = _find_row(doc, change.get("DtlKey"))  # type: ignore[arg-type]
        edits = {k: v for k, v in change.items() if k != "DtlKey"}
        for key in edits:
            if key not in EDIT_LINE_KEYS:
                raise WriteRefusal("FIELD_NOT_EDITABLE", key)
        out = _normal(_row_fields(row))
        out.update({k: _plain(v) for k, v in edits.items()})
        price = _num_of(out.get("UnitPrice"))
        if "Qty" in edits:
            validate_qty(_dec(out.get("Qty")))  # QTY_INVALID: not above zero, over 1e9 or over 8 places
        if "UnitPrice" in edits and (price is None or price < 0):
            raise WriteRefusal("PRICE_INVALID", "unit price must not be negative")
        details.append(out)
    body["Details"] = details
    return VendorRequest("PUT", kind.edit_path, body)


def build_add_line(kind_name: str, doc: Doc, line: Mapping[str, Any]) -> VendorRequest:
    kind = kind_of(kind_name)
    _check_kind_doc(kind, doc)
    _check_line(line)
    body = _doc_header(kind, doc)
    body["Details"] = [_vendor_line(line, 0, kind.name)]
    return VendorRequest("PUT", kind.edit_path, body)


def check_row(kind_name: str, doc: Doc, dtl_key: int) -> Doc:
    """The row ``dtl_key`` of a writable ``kind_name`` document (kind, cancelled, row exists)."""
    _check_kind_doc(kind_of(kind_name), doc)
    return _find_row(doc, dtl_key)


def build_delete_line(kind_name: str, doc: Doc, dtl_key: int) -> VendorRequest:
    """Plan 61 F6: the row as read with ``FullTransferOption "D"``, alone, on the edit door."""
    kind = kind_of(kind_name)
    _check_kind_doc(kind, doc)
    body = _doc_header(kind, doc)
    body["Details"] = [_deleted(_find_row(doc, dtl_key))]
    return VendorRequest("PUT", kind.edit_path, body)


def build_row_replace(kind_name: str, doc: Doc, old_row: Mapping[str, Any], new_row: Mapping[str, Any]) -> VendorRequest:
    """Plan 61 section 4.1 (AC-61-10): ONE PUT on the edit door with ``Details [old row
    as read + "D", new row DtlKey 0]``. The new row is a full vendor row; it carries
    ``FromDocType / FromDocNo / FromDocDtlKey`` only when it is linked."""
    kind = kind_of(kind_name)
    _check_kind_doc(kind, doc)
    old = _find_row(doc, old_row.get("DtlKey"))  # type: ignore[arg-type]
    new = _vendor_line(new_row, 0, kind.name)
    if not new.get("FromDocType"):
        new.update(FromDocType="", FromDocNo="", FromDocDtlKey=0)
    body = _doc_header(kind, doc)
    body["Details"] = [_deleted(old), new]
    return VendorRequest("PUT", kind.edit_path, body)


def build_cancel(kind_name: str, doc: Doc) -> VendorRequest:
    """Plan 61 F9: ``DELETE /Cancel<Doc>bydocno?DocNo=<no>`` with no body."""
    kind = kind_of(kind_name)
    _check_kind_doc(kind, doc)
    if kind.name == "QT" and not _blank(doc.get("ToDocType")):
        raise WriteRefusal("DOC_HAS_TRANSFERS", "quotation has a target document")
    doc_no = doc.get("DocNo")
    if _blank(doc_no):
        raise WriteRefusal("DOC_NOT_FOUND", "document has no number")
    return VendorRequest("DELETE", kind.cancel_path, None, {"DocNo": str(doc_no)})


# ── verifiers (pure; compare the fresh read-back with what was sent) ─────────────

def _same_line(sent: Mapping[str, Any], got: Doc) -> bool:
    return all(_same(sent.get(k), got.get(k)) for k in REQUIRED_LINE)


QT_VALUES_INHERITED = "QT_ROW_VALUES_INHERITED"
_INHERITED_FIELDS = ("UnitPrice", "Location")


def _link_code(kind: str, sent: Mapping[str, Any], row: Doc) -> Optional[str]:
    """``LINK_MISMATCH`` when the link a sent row carried did not land (AC-57-41): a PO
    row carries it as ``FromSODtlKey``, an SPO row as ``FromDocDtlKey``, an SO row taken
    from a quotation as ``FromDocType`` + ``FromDocNo`` (AutoCount reads its row key as 0)."""
    ftype = sent.get("FromDocType")
    if not ftype:
        return None
    if kind == "PO" and ftype == "SO":
        ok = int(row.get("FromSODtlKey") or 0) == int(sent.get("FromDocDtlKey") or 0)
    elif kind == "SPO":
        ok = int(row.get("FromDocDtlKey") or 0) == int(sent.get("FromDocDtlKey") or 0)
    else:
        ok = row.get("FromDocType") == ftype and row.get("FromDocNo") == sent.get("FromDocNo")
    return None if ok else "LINK_MISMATCH"


def _line_same(sent: Mapping[str, Any], row: Doc, relax: Sequence[str]) -> bool:
    return all(_same(sent.get(k), row.get(k)) for k in REQUIRED_LINE if k not in relax)


def verify_create(kind_name: str, sent: Mapping[str, Any], after: Doc) -> Verdict:
    kind_of(kind_name)
    want: Sequence[Mapping[str, Any]] = sent.get("Details") or []
    got: List[Doc] = after.get("Details") or []
    if len(got) < len(want):
        return Verdict(MISMATCH, "ROWS_DROPPED")
    if len(got) > len(want):
        return Verdict(MISMATCH, "ROWS_UNEXPECTED")
    warnings: List[str] = []
    inherited: List[str] = []
    for line, row in zip(want, got):
        from_qt = kind_name == "SO" and line.get("FromDocType") == "QT"
        if not _line_same(line, row, _INHERITED_FIELDS if from_qt else ()):
            return Verdict(MISMATCH, "ROW_MISMATCH")
        if _link_code(kind_name, line, row):
            return Verdict(MISMATCH, "LINK_MISMATCH")
        if from_qt:  # AutoCount copies price and location from the quotation row (live db3)
            inherited += [k for k in _INHERITED_FIELDS if not _same(line.get(k), row.get(k)) and k not in inherited]
        if line.get("FromDocDtlKey") and kind_name == "SO" and not _same(
            row.get("FromDocDtlKey"), line.get("FromDocDtlKey")
        ):
            if LINK_UNCONFIRMED not in warnings:
                warnings.append(LINK_UNCONFIRMED)
    message = ""
    if inherited:
        warnings.append(QT_VALUES_INHERITED)
        message = "taken from the quotation row: " + ", ".join(inherited)
    return Verdict(DONE, None, warnings, message)


def _row_by_key(doc: Doc, dtl_key: Any) -> Optional[Doc]:
    for row in doc.get("Details") or []:
        if row.get("DtlKey") == dtl_key:
            return row
    return None


def _drifted(before: Doc, after: Doc, skip_header: Sequence[str], skip_rows: Sequence[Any]) -> List[str]:
    out: List[str] = []
    for key in _COMPARE_HEADER:
        if key in before and key not in skip_header and not _same(before.get(key), after.get(key)):
            out.append(key)
    for row in before.get("Details") or []:
        if row.get("DtlKey") in skip_rows:
            continue
        now = _row_by_key(after, row.get("DtlKey"))
        if now is None:
            out.append(f"Details[{row.get('DtlKey')}]")
            continue
        for key in _COMPARE_LINE:
            if key in row and not _same(row.get(key), now.get(key)):
                out.append(f"Details[{row.get('DtlKey')}].{key}")
    return out


def verify_edit(
    kind_name: str,
    before: Doc,
    header_changes: Mapping[str, Any],
    line_changes: Sequence[Mapping[str, Any]],
    after: Doc,
) -> List[str]:
    """Names of every field AutoCount ignored or altered unasked; empty = clean."""
    kind_of(kind_name)
    out: List[str] = [k for k, v in header_changes.items() if not _same(after.get(k), v)]
    touched: List[Any] = []
    for change in line_changes:
        dtl = change.get("DtlKey")
        touched.append(dtl)
        row = _row_by_key(after, dtl)
        if row is None:
            out.append(f"Details[{dtl}]")
            continue
        out.extend(f"Details[{dtl}].{k}" for k, v in change.items() if k != "DtlKey" and not _same(row.get(k), v))
        original = _row_by_key(before, dtl) or {}
        out.extend(
            f"Details[{dtl}].{k}"
            for k in _COMPARE_LINE
            if k in original and k not in change and not _same(original.get(k), row.get(k))
        )
    out.extend(k for k in _drifted(before, after, list(header_changes), touched) if not _remark_mirror(k, header_changes, after))
    return out


_MIRRORED_REMARKS = ("Remark2", "Remark3", "Remark4")


def _remark_mirror(key: str, header_changes: Mapping[str, Any], after: Doc) -> bool:
    """AutoCount's wrapper copies Remark1 into Remark2..4 on an edit (db3 6 Nov, QT
    DocKey 12147, F13). An untouched Remark2..4 that now reads back as the newly set
    Remark1 is that copy, not a field AutoCount ignored."""
    return (
        key in _MIRRORED_REMARKS
        and "Remark1" in header_changes
        and _same(after.get(key), header_changes["Remark1"])
    )


def verify_delete_line(kind_name: str, before: Doc, dtl_key: int, after: Doc) -> Verdict:
    kind_of(kind_name)
    if _row_by_key(after, dtl_key) is not None:
        return Verdict(MISMATCH, "LINE_NOT_DELETED")
    if _drifted(before, after, (), [dtl_key]):
        return Verdict(MISMATCH, "COLLATERAL_CHANGE")
    return Verdict(DONE)


def verify_cancel(kind_name: str, after: Doc) -> Verdict:
    kind_of(kind_name)
    if after.get("Cancelled") == "T":
        return Verdict(DONE)
    return Verdict(MISMATCH, "CANCEL_IGNORED")


def verify_add_line(kind_name: str, before: Doc, line: Mapping[str, Any], after: Doc) -> Verdict:
    """Exactly one new row reads back as sent and nothing else moved."""
    kind_of(kind_name)
    known = {r.get("DtlKey") for r in before.get("Details") or []}
    added = [r for r in after.get("Details") or [] if r.get("DtlKey") not in known]
    if len(added) != 1:
        return Verdict(MISMATCH, "ROWS_DROPPED" if not added else "ROWS_UNEXPECTED")
    # AutoCount resets a new row that carries a link (HQ, price 0, no date; db3, F5): a
    # later step puts them back, so they are not compared here.
    relaxed = _relax_transfer(line, added[0]) if line.get("FromDocDtlKey") else line
    if not _same_line(relaxed, added[0]):
        return Verdict(MISMATCH, "ROW_MISMATCH")
    if _link_code(kind_name, line, added[0]):
        return Verdict(MISMATCH, "LINK_MISMATCH")
    if _drifted(before, after, (), []):
        return Verdict(MISMATCH, "COLLATERAL_CHANGE")
    return Verdict(DONE)


def verify_row_replace(kind_name: str, before: Doc, old_key: int, line: Mapping[str, Any], after: Doc) -> Verdict:
    """AC-61-11..13: the old row is gone, exactly one new row reads back as sent (its
    location aside when it is linked: AutoCount forces HQ, F5) with its link, and no
    other row or header field moved."""
    kind_of(kind_name)
    if _row_by_key(after, old_key) is not None:
        return Verdict(MISMATCH, "LINE_NOT_DELETED")
    known = {r.get("DtlKey") for r in before.get("Details") or []}
    added = [r for r in after.get("Details") or [] if r.get("DtlKey") not in known]
    if len(added) != 1:
        return Verdict(MISMATCH, "ROWS_DROPPED" if not added else "ROWS_UNEXPECTED")
    relaxed = _relax_transfer(line, added[0]) if line.get("FromDocType") else line
    if not _same_line(relaxed, added[0]):
        return Verdict(MISMATCH, "ROW_MISMATCH")
    if _link_code(kind_name, line, added[0]) or (not line.get("FromDocType") and _link_of_row(kind_name, added[0])):
        return Verdict(MISMATCH, "LINK_MISMATCH")
    if _drifted(before, after, (), [old_key]):
        return Verdict(MISMATCH, "COLLATERAL_CHANGE")
    return Verdict(DONE)


def _relax_transfer(line: Mapping[str, Any], got: Doc) -> Doc:
    """``line`` with the ``TRANSFER_RESET_FIELDS`` taken from the read-back row: AutoCount
    resets them on a new linked row (F5) and the move step puts them back."""
    return dict(line, **{k: got.get(k) for k in TRANSFER_RESET_FIELDS})


def _link_of_row(kind_name: str, row: Doc) -> int:
    """The link a read-back row carries: ``FromSODtlKey`` on a PO row, ``FromDocDtlKey``
    on an SPO row; a QT / SO row is linked when it names a source document."""
    if kind_name == "PO":
        return int(row.get("FromSODtlKey") or 0)
    if kind_name == "SPO":
        return int(row.get("FromDocDtlKey") or 0)
    return 1 if row.get("FromDocType") else 0
