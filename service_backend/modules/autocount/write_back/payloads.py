"""Pure PO link / split / unlink payload builders (plan 55 section 6b, AC-55-10..16).

Inputs are the vendor documents as read back from AutoCount (dicts); nothing is
mutated. Only whitelisted header and row fields are sent, and only the touched
rows appear in ``Details``. Quantities are computed in ``Decimal``.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence

Doc = Dict[str, Any]

HEADER_KEYS = (
    "DocKey", "DocNo", "DocDate", "CreditorCode", "CreditorName", "Ref", "Description",
    "DisplayTerm", "PurchaseAgent", "InvAddr1", "InvAddr2", "InvAddr3", "InvAddr4",
    "Phone1", "Fax1", "Attention", "BranchCode", "DeliverAddr1", "DeliverAddr2",
    "DeliverAddr3", "DeliverAddr4", "DeliverPhone1", "DeliverFax1", "DeliverContact",
    "CurrencyCode", "CurrencyRate", "Remark1", "Remark2", "Remark3", "Remark4",
    "RefDocNo", "ShipVia", "ShipInfo", "InclusiveTax",
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


def _header(doc: Doc) -> Doc:
    return _pick(doc, HEADER_KEYS)


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
    return bool(row.get("FromSODtlKey")) or bool(row.get("FromDocDtlKey"))


def _unlinked(row: Doc) -> Doc:
    out = _row_fields(row)
    out.update(FromDocType="", FromDocNo="", FromDocDtlKey=0)
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
    whole_row_as_split: bool = False,
) -> Doc:
    """Link ``qty`` of a PO row to an SO row: in place when ``qty`` equals the
    row qty (the row also takes the SO row's location), else split off a new row.
    ``whole_row_as_split`` emulates a whole-row link as a split that leaves the
    original row at quantity 0."""
    _check_doc(po, want_spo=False)
    if so.get("Cancelled") == "T":
        raise WriteRefusal("DOC_CANCELLED", "sales order is cancelled")
    po_row = _find_row(po, po_dtl_key)
    so_row = _find_row(so, so_dtl_key)
    _refuse_on_spo(spo_ref)
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
    if qty == free and not whole_row_as_split:
        row = _row_fields(po_row)
        row.update(link)
        body["Details"] = [row]
        return body
    edited = _row_fields(po_row)
    edited["Qty"] = _num(free - qty)
    new = _row_fields(po_row)
    new.update(link, DtlKey=0, Qty=_num(qty), FOCQty=0)
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
    moved = _row_fields(row)
    moved["Location"] = location
    body = _header(po)
    body["Details"] = [moved]
    return body


def build_unlink(po: Doc, po_dtl_key: int, *, spo_ref: Optional[str] = None) -> Doc:
    """Clear the link of one PO row; the row keeps its own qty and location."""
    _check_doc(po, want_spo=False)
    row = _find_row(po, po_dtl_key)
    _refuse_on_spo(spo_ref)
    if not _row_linked(row):
        raise WriteRefusal("ROW_NOT_LINKED", "row is not linked")
    body = _header(po)
    body["Details"] = [_unlinked(row)]
    return body


def build_spo_unlink(spo: Doc, spo_dtl_key: int) -> Doc:
    """Clear the PO link of one SPO row (SPO = PO document with ShippingPO "T")."""
    _check_doc(spo, want_spo=True)
    row = _find_row(spo, spo_dtl_key)
    if not (row.get("FromDocDtlKey") or row.get("FromDocNo")):
        raise WriteRefusal("ROW_NOT_LINKED", "row is not linked")
    body = _header(spo)
    body["ShippingPO"] = "T"
    details: List[Doc] = [_unlinked(row)]
    body["Details"] = details
    return body
