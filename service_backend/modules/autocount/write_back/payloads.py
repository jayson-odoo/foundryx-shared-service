"""Pure PO link / split / unlink payload builders (plan 55 section 6b, AC-55-10..16).

Inputs are the vendor documents as read back from AutoCount (dicts); nothing is
mutated. Only whitelisted header and row fields are sent, and only the touched
rows appear in ``Details``. Quantities are computed in ``Decimal``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from modules.autocount.write_back import capabilities
from modules.autocount.write_back.doc_kinds import DocKind, kind_of

Doc = Dict[str, Any]
logger = logging.getLogger("foundryx.autocount")

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
    "FurtherDescription",
)


class WriteRefusal(Exception):
    """A request the builders refuse; ``code`` is stable, the text is operator-safe."""

    def __init__(self, code: str, message: str = "", *, plain: bool = False) -> None:
        """``plain``: ``message`` is the user-facing reason as is (no code prefix)."""
        self.code = code
        super().__init__(message if plain and message else (f"{code}: {message}" if message else code))


def on_spo_message(spo_ref: Optional[str] = None) -> str:
    """The plain reason for ``ROW_ON_SPO`` (the CRM shows it as is): one text for the operations, the
    batch link and the single-line primitives."""
    where = f"shipping purchase order {spo_ref}" if spo_ref else "a shipping purchase order"
    that = "that shipping purchase order" if spo_ref else "the shipping purchase order"
    return (f"This purchase order line is on {where}, so the change was not made. "
            f"Remove it from {that} first, then try again.")


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


# Plan 73: the row's Further Description (RTF, may hold pictures). hapi never returns it on a PO GET, so the
# frame's NotesReader lays the AutoCount database's stored values on every PO / SPO it reads; a row without the key
# is unread.
FURTHER_DESC = "FurtherDescription"
AUTOCOUNT_DB_UNREAD = "AUTOCOUNT_DB_UNREAD"
AUTOCOUNT_DB_UNREAD_MESSAGE = (
    "The purchase order could not be read from AutoCount, so the change was not made. Try again."
)
_NOTES_KINDS = ("PO", "SPO")


DB_UNREAD_MARKER = "_dbUnread"  # set on a PO / SPO the AutoCount DB could not be read for; never in any key list, never sent


STORED_FIELDS_CHANGED = "STORED_FIELDS_CHANGED"


def public_doc(doc: Any) -> Any:
    """Plan 73: ``doc`` without the internal unread marker, for anything stored or returned (the document shape of
    contract 57 never carries it). Copies only when the marker is there; anything else is returned as is."""
    if isinstance(doc, dict) and DB_UNREAD_MARKER in doc:
        return {k: v for k, v in doc.items() if k != DB_UNREAD_MARKER}
    return doc


def require_db_read(doc: Mapping[str, Any]) -> None:
    """Plan 73 H1: a PO / SPO body (any of them, also a header-only one) is built from values read from the AutoCount
    DB; a document marked unread is refused before any write."""
    if doc.get(DB_UNREAD_MARKER):
        raise WriteRefusal(AUTOCOUNT_DB_UNREAD, AUTOCOUNT_DB_UNREAD_MESSAGE, plain=True)


def require_line_notes(*rows: Mapping[str, Any]) -> None:
    """Plan 73 D3: a row we re-send or copy must carry its Further Description (as read). Missing = unknown:
    refused before any write (resending it blank could erase the note and its pictures)."""
    if any(FURTHER_DESC not in row for row in rows):
        raise WriteRefusal(AUTOCOUNT_DB_UNREAD, AUTOCOUNT_DB_UNREAD_MESSAGE, plain=True)


def _resend(kind_name: str, row: Doc) -> Doc:
    """``_row_fields`` of a row that is sent again (not deleted): a PO / SPO row must carry its note."""
    if kind_name in _NOTES_KINDS:
        require_line_notes(row)
    return _row_fields(row)


def _inherit_note(new: Doc, old: Mapping[str, Any]) -> Doc:
    """A new row copied from ``old`` keeps ``old``'s Further Description unless the line brought its own."""
    if FURTHER_DESC not in new and FURTHER_DESC in old:
        new[FURTHER_DESC] = old[FURTHER_DESC]
    return new


def _is_spo(doc: Doc) -> bool:
    return doc.get("ShippingPO") == "T"


SHIPPING_PO = "ShippingPO"
SHIPPING_PO_CHANGED = "SHIPPING_PO_CHANGED"
SHIPPING_PO_CHANGED_MESSAGE = "AutoCount changed Shipping Order on this PO"
SHIPPING_PO_UNKNOWN = "SHIPPING_PO_UNKNOWN"
SHIPPING_PO_UNKNOWN_MESSAGE = (
    "Shipping Order on this PO is not set to yes or no in AutoCount, so the change was not made. "
    "Set Shipping Order on the PO in AutoCount, then try again."
)
_SHIPPING_FLAGS = ("T", "F")


def _require_known_shipping(doc: Doc) -> None:
    """SS-SHIPPINGPO-PRESERVE (prod proof, PO 202607-S0083): a read whose ``ShippingPO`` is
    not exactly "T" or "F" ("\u0000", "", null, missing) is unknown. SS never guesses it and
    never sends it back: the edit is refused before any write."""
    value = doc.get(SHIPPING_PO)
    if value not in _SHIPPING_FLAGS:
        logger.warning("autocount edit refused: ShippingPO reads %r (DocKey %s, DocNo %s)",
                       value, doc.get("DocKey"), doc.get("DocNo"))
        raise WriteRefusal(SHIPPING_PO_UNKNOWN, SHIPPING_PO_UNKNOWN_MESSAGE, plain=True)


def keep_shipping_po(body: Doc, doc: Doc) -> Doc:
    """SS-SHIPPINGPO-PRESERVE: a PO / SPO edit body carries ``ShippingPO`` exactly as SS just
    read it ("F" stays "F", "T" stays "T"); omitted, the vendor edit writes NUL, which
    AutoCount shows as ticked (prod 20 Nov). Copied, never computed; unknown is refused."""
    require_db_read(doc)
    _require_known_shipping(doc)
    body[SHIPPING_PO] = doc[SHIPPING_PO]
    return body


def shipping_po_changed(before: Doc, after: Doc) -> bool:
    """True when the read-back's ``ShippingPO`` is not exactly the pre-write value (a NUL,
    blank or missing read-back after "F" is a change)."""
    return before.get(SHIPPING_PO) != after.get(SHIPPING_PO)


def shipping_po_values(before: Doc, after: Doc) -> Tuple[str, str]:
    """``(before, after)`` as printable text for the log line of a ``SHIPPING_PO_CHANGED``."""
    return repr(before.get(SHIPPING_PO)), repr(after.get(SHIPPING_PO))


def _check_doc(doc: Doc, want_spo: bool) -> None:
    _require_known_shipping(doc)
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
        raise WriteRefusal("ROW_ON_SPO", on_spo_message(spo_ref), plain=True)


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
    note: Optional[str] = None,
    location: Optional[str] = None,
) -> Doc:
    """Link ``qty`` of a PO row to an SO row in ONE PUT. AutoCount never links an
    existing row, so the whole row is replaced (the row ``"D"`` plus a new linked row,
    plan 61 F5) and part of it is split (the row cut to the rest plus a new linked row).
    The new row asks for the SO row's location (plan 70: the caller's ``location`` when given);
    AutoCount forces HQ and the caller moves it back in a second write."""
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
        "Location": location or so_row.get("Location"),
    }
    body = keep_shipping_po(_header(po), po)
    new = _normal(_resend("PO", po_row))
    new.update(link, DtlKey=0, Qty=_num(qty), FOCQty=0)
    with_so_delivery_date(new, _day(so_row.get("DeliveryDate")))  # 16 Nov rule: the SO line's date, never the PO's
    with_link_note(new, {LINK_NOTE_KEY: note})  # plan 66: the note on the new row in the link PUT
    if qty == free:
        body["Details"] = [_deleted(po_row), new]
        return body
    edited = _normal(_row_fields(po_row))
    edited["Qty"] = _num(free - qty)
    body["Details"] = [edited, new]
    return body


def with_so_delivery_date(line: Dict[str, Any], so_day: Optional[str]) -> Dict[str, Any]:
    """PO-LINK-STUCK-RECONCILE-B (owner rule 16 Nov): a NEW tied PO row carries its SO line's delivery date,
    never the PO row's (that is the PO issue date, the CRM's ``docDate``). No SO line date = no date sent (the
    restore asks for none either, ``transfer_restore``). The one rule of the split link and the batches."""
    if so_day:
        line["DeliveryDate"] = f"{so_day}T00:00:00"
    else:
        line.pop("DeliveryDate", None)
    return line


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
    moved = _normal(_resend("PO", row))
    moved["Location"] = location
    body = keep_shipping_po(_header(po), po)
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


def transfer_restore(source: Mapping[str, Any], location: Optional[str],
                     so_link: Optional[Mapping[str, Any]] = None) -> Doc:
    """The ``TRANSFER_RESET_FIELDS`` values a new SO-linked PO row must get back after
    AutoCount reset them (F5): ``source``'s price and delivery date, at ``location``
    (when given). The one rule the split link and the row operations share.

    ``so_link`` (plan 65 D2 / D4 / D2a, ``{"soDeliveryDate", "note"}`` as the snapshot keeps
    them): the row is a NEW row linked to that SO row, so the delivery date is the SO ROW's
    (omitted when it has none, never ``source``'s), a percentage discount of ``source`` goes
    back (``link_discount``) and the note goes on as ``FurtherDescription`` (AutoCount RTF)."""
    wanted: Doc = {k: source[k] for k in TRANSFER_RESET_FIELDS if k in source}
    if location:
        wanted["Location"] = location
    else:
        wanted.pop("Location", None)
    if so_link is None:
        return wanted
    wanted.pop("DeliveryDate", None)
    so_day = so_link.get("soDeliveryDate")
    if so_day:
        wanted["DeliveryDate"] = f"{so_day}T00:00:00"
    discount = link_discount(source.get("Discount"))
    if discount:
        wanted["Discount"] = discount
    note = so_link.get("note")
    if note:
        wanted[FURTHER_DESC] = append_note(source.get(FURTHER_DESC), str(note))
    return wanted


# Plan 65 D2a: AutoCount resets a new SO-linked row's discount too (probe P2); the restore
# sets it back when it is a percentage.
LINK_RESTORE_FIELDS = TRANSFER_RESET_FIELDS + ("Discount",)
# Plan 65 P3: accepted on an edit PUT, never returned by a read: always sent, never verified.
UNREADABLE_ROW_KEYS = ("FurtherDescription",)


def transfer_row_drift(sent: Mapping[str, Any], got: Doc) -> Doc:
    """The restore fields the read-back row lost: ``{field: sent value}``. A field not
    sent (or an empty sent date) is never asked back; a field no read returns
    (``UNREADABLE_ROW_KEYS``) is always sent."""
    out: Doc = {}
    for key in LINK_RESTORE_FIELDS:
        if key not in sent or (key == "DeliveryDate" and _day(sent[key]) is None):
            continue
        if not same_row_value(key, sent[key], got.get(key)):
            out[key] = sent[key]
    out.update({k: sent[k] for k in UNREADABLE_ROW_KEYS if sent.get(k)})
    return out


_NO_SO_PREFIX = re.compile(r"^SO", re.IGNORECASE)


def so_link_note(so: Mapping[str, Any], so_row: Mapping[str, Any]) -> str:
    """Plan 65 D4: the note on a PO row linked to an SO row, in the shape of the hand-made
    notes: ``**<DebtorName>[/<Ref>] S/O: <DocNo without a leading SO>[ DD: dd/mm/yyyy]``.
    The non-blank DebtorName and Ref are joined by "/"; the SO prefix strip ignores case;
    a missing SO row date is left out (plan 65 R5)."""
    parts = [str(so.get(k)).strip() for k in ("DebtorName", "Ref") if not _blank(so.get(k))]
    text = "**" + "/".join(parts) + " S/O: " + _NO_SO_PREFIX.sub("", str(so.get("DocNo") or "").strip())
    day = _day(so_row.get("DeliveryDate"))
    if day:
        year, month, dom = day.split("-")
        text += f" DD: {dom}/{month}/{year}"
    return text


_RTF_HEAD = (r"{\rtf1\ansi\ansicpg1252\deff0\deflang1033{\fonttbl{\f0\fswiss\fcharset0 Arial;}}"
             r"\viewkind4\uc1\pard\f0\fs20 ")
_RTF_TAIL = "\\par\r\n}"


def _rtf_char(ch: str) -> str:
    if ch in "\\{}":
        return "\\" + ch
    if ch == "\n":
        return "\\line "
    if ch == "\t":
        return "\\tab "
    code = ord(ch)
    if 0x20 <= code < 0x7F:
        return ch
    if code < 0x20 or code == 0x7F:
        return ""  # other control characters carry nothing printable
    try:
        raw = ch.encode("cp1252")
    except UnicodeEncodeError:
        units = ch.encode("utf-16-be")
        out = ""
        for i in range(0, len(units), 2):  # one \uN? per UTF-16 unit, signed as RTF wants
            unit = int.from_bytes(units[i:i + 2], "big")
            out += f"\\u{unit - 0x10000 if unit > 0x7FFF else unit}?"
        return out
    return "".join(f"\\'{b:02x}" for b in raw)


def autocount_rtf(text: str) -> str:
    """Plan 65 D4: ``text`` in AutoCount's own default RTF wrapper (the shape its stored
    FurtherDescription carries): ``\\``, ``{``, ``}`` escaped, non-ASCII as ``\\'hh`` (cp1252)
    or ``\\uN?``."""
    return _RTF_HEAD + "".join(_rtf_char(ch) for ch in text) + _RTF_TAIL


_RTF_PAD = " \r\n\t\x00"  # bytes that may follow the closing brace of a stored FD


def _bare_note(value: Any) -> Optional[str]:
    """The escaped note text of a value that is exactly ``autocount_rtf(note)``, else None."""
    if isinstance(value, str) and value.startswith(_RTF_HEAD) and value.endswith(_RTF_TAIL):
        return value[len(_RTF_HEAD):len(value) - len(_RTF_TAIL)]
    return None


def _merge_bare_note(out: Doc, row: Mapping[str, Any], values: Mapping[str, Any]) -> None:
    """Plan 73 D4: a restore value that is only a note in AutoCount's wrapper is merged after the row's own
    FD (idempotent), never sent in place of it. A full FD value is sent as given."""
    escaped = _bare_note(values.get(FURTHER_DESC))
    if escaped is not None:
        out[FURTHER_DESC] = _append_escaped(row.get(FURTHER_DESC), escaped)


def _ends_with_note(fd: str, escaped: str) -> bool:
    """True when ``fd`` already ends with the note (its trailing ``\\par``, blanks and braces ignored)."""
    tail = fd.rstrip(_RTF_PAD)
    while True:
        if tail.endswith("}") or tail.endswith("\\par"):
            tail = tail[:-1] if tail.endswith("}") else tail[:-4]
            tail = tail.rstrip(_RTF_PAD)
            continue
        return tail.endswith(escaped)


def _append_escaped(fd: Any, escaped: str) -> str:
    text = fd if isinstance(fd, str) else ""
    if not escaped:
        return text
    if not text.strip():
        return _RTF_HEAD + escaped + _RTF_TAIL
    if text.lstrip().startswith("{\\rtf"):
        if _ends_with_note(text, escaped):
            return text
        close = text.rstrip(_RTF_PAD).rfind("}")  # the group's last brace; trailing CR LF / NUL / blanks stay after it
        if close < 0:
            return text + "\\par " + escaped
        return text[:close] + "\\par " + escaped + text[close:]
    return text


def append_note(fd: Any, note: str) -> str:
    """Plan 73 D4: ``note`` appended after the existing Further Description ``fd``. RTF: a paragraph before the
    final ``}`` (the rest byte for byte, pictures included); plain text: both in AutoCount's wrapper, the note on
    a new line; empty: the note in the wrapper. Idempotent: an FD that already ends with the note is unchanged."""
    escaped = "".join(_rtf_char(ch) for ch in str(note or ""))
    text = fd if isinstance(fd, str) else ""
    if text.strip() and not text.lstrip().startswith("{\\rtf"):
        if text.rstrip().endswith(str(note)):
            return text
        return autocount_rtf(text + "\n" + str(note))
    return _append_escaped(text, escaped)


def so_link_values(so: Mapping[str, Any], so_row: Mapping[str, Any]) -> Doc:
    """Plan 65 D2 / D4: the ``so_link`` of ``transfer_restore`` for a row newly linked to
    ``so_row``: the SO row's day (None when it has none) and the note text."""
    return {"soDeliveryDate": _day(so_row.get("DeliveryDate")), "note": so_link_note(so, so_row)}


# Plan 66: the plain note text a link flow puts on a line (operations / the split flow only). Never a vendor
# key and never in LINE_KEYS: a caller's own line cannot carry a note through the add / edit doors.
LINK_NOTE_KEY = "soNote"


def with_link_note(new: Doc, line: Mapping[str, Any]) -> Doc:
    """Plan 66: the NEW linked row ``new`` (built from ``line``) carries the note as ``FurtherDescription``
    in the PUT that creates it: AutoCount stores it on an added row, not on an edit of an existing one (live
    17 Nov). Only a row that carries a link and a note; anything else is left as built."""
    note = line.get(LINK_NOTE_KEY)
    if note and new.get("FromDocDtlKey"):
        new[FURTHER_DESC] = append_note(new.get(FURTHER_DESC), str(note))  # plan 73 D4: after the existing FD
    return new


def foc_on_row(row: Mapping[str, Any], taken: Decimal) -> bool:
    """Plan 65 D2a: a link taking ``taken`` of ``row`` would take all of it while it carries FOC,
    which hapi cannot put on the new row (``FOC_ON_ROW``: the batch skip and the single link refusal)."""
    return taken == _dec(row.get("Qty")) and _dec(row.get("FOCQty")) > 0


def link_discount(value: Any) -> str:
    """Plan 65 D2a: the discount a new linked row takes from its source row: the value when
    every ``+``-term is a percentage (``5%``, ``5%+2%``), else blank (an amount discount
    would change the PO total when the row is split)."""
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    terms = [t.strip() for t in text.split("+")]
    return text if all(t.endswith("%") and t[:-1].strip() for t in terms) else ""


def build_restore_transfer_row(po: Doc, dtl_key: int, values: Mapping[str, Any]) -> Doc:
    """Second write of a split link: the new row exactly as read, with ``values``
    (location, unit price, delivery date) set back to what the split sent."""
    if not values:
        raise WriteRefusal("NO_CHANGE", "nothing to restore")
    row = _normal(_resend("PO", _find_row(po, dtl_key)))
    row.update(values)
    _merge_bare_note(row, _find_row(po, dtl_key), values)
    body = keep_shipping_po(_header(po), po)
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
# Plan 65 D4: the restore of a new SO-linked row (an operation step, never the public edit
# door) may also send the note and the FOC quantity.
RESTORE_LINE_KEYS = EDIT_LINE_KEYS + ("FurtherDescription", "FOCQty")
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


def _check_kind_doc(kind: DocKind, doc: Doc, *, cancelled_ok: bool = False, write: bool = True) -> None:
    """``write`` False = a plain read (``get_doc``): an unknown ``ShippingPO`` is still readable."""
    if write and kind.name in ("PO", "SPO"):
        _require_known_shipping(doc)
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
    """The edit header: the document's own header fields; a PO / SPO also carries its
    ``ShippingPO`` as read (``_check_kind_doc`` already held it to the kind)."""
    body = _pick_header(doc, ("DocKey",) + CREATE_HEADER_KEYS)
    if kind.name in ("PO", "SPO"):
        keep_shipping_po(body, doc)
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
    *,
    restore: bool = False,
) -> VendorRequest:
    """``restore`` (operations only, plan 65 D4): the line whitelist is ``RESTORE_LINE_KEYS``."""
    kind = kind_of(kind_name)
    _check_kind_doc(kind, doc)
    line_keys = RESTORE_LINE_KEYS if restore else EDIT_LINE_KEYS
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
            if key not in line_keys:
                raise WriteRefusal("FIELD_NOT_EDITABLE", key)
        out = _normal(_resend(kind.name, row))
        out.update({k: _plain(v) for k, v in edits.items()})
        _merge_bare_note(out, row, edits)
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
    body["Details"] = [with_link_note(_vendor_line(line, 0, kind.name), line)]
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
    if kind.name in _NOTES_KINDS:
        require_line_notes(old)
    new = _inherit_note(_vendor_line(new_row, 0, kind.name), old)
    if not new.get("FromDocType"):
        new.update(FromDocType="", FromDocNo="", FromDocDtlKey=0)
    with_link_note(new, new_row)
    body = _doc_header(kind, doc)
    body["Details"] = [_deleted(old), new]
    return VendorRequest("PUT", kind.edit_path, body)


def build_link_batch(kind_name: str, doc: Doc, old_key: int, new_rows: Sequence[Mapping[str, Any]]) -> VendorRequest:
    """Plan 62 D3: ONE PUT on the edit door linking one row to N source rows (``build_link_doc`` with one
    row)."""
    return build_link_doc(kind_name, doc, [(old_key, new_rows)])


def build_link_doc(kind_name: str, doc: Doc,
                   groups: Sequence[Tuple[int, Sequence[Mapping[str, Any]]]]) -> VendorRequest:
    """Plan 62 D3 / 69 D1: ONE PUT on the edit door linking every listed row of ONE document, each to its
    N source rows. Each row is marked ``"D"`` when its new rows take all of its quantity, else kept with the
    rest; every new row is a full vendor row, ``DtlKey 0``, with its own ``FromDocType / FromDocNo /
    FromDocDtlKey``. AutoCount applies the PUT all or nothing (plan 62 S0)."""
    kind = kind_of(kind_name)
    _check_kind_doc(kind, doc)
    if not groups or len({k for k, _ in groups}) != len(groups):
        raise WriteRefusal("INVALID_PARAMS", "each row is listed once")
    details: List[Doc] = []
    added: List[Doc] = []
    for old_key, new_rows in groups:
        old = _find_row(doc, old_key)
        if kind.name in _NOTES_KINDS:
            require_line_notes(old)
        taken = sum((_dec(r.get("Qty")) for r in new_rows), Decimal(0))
        rest = _dec(old.get("Qty")) - taken
        if rest < 0:
            raise WriteRefusal("QTY_ABOVE_FREE", "quantity above the PO row quantity")
        if rest == 0:
            details.append(_deleted(old))
        else:
            kept = _normal(_row_fields(old))
            kept["Qty"] = _num(rest)
            details.append(kept)
        added.extend(with_link_note(_inherit_note(_vendor_line(r, 0, kind.name), old), r) for r in new_rows)
    body = _doc_header(kind, doc)
    body["Details"] = details + added
    return VendorRequest("PUT", kind.edit_path, body)


def build_unlink_merge(kind_name: str, doc: Doc, linked_key: int, free_key: int) -> VendorRequest:
    """Plan 62 D7: ONE PUT unlinking a row by merging it into a free row: the linked row ``"D"``
    and the free row raised by the freed quantity (no new row, so no free row piles up)."""
    kind = kind_of(kind_name)
    _check_kind_doc(kind, doc)
    linked = _find_row(doc, linked_key)
    free = _find_row(doc, free_key)
    raised = _normal(_resend(kind.name, free))
    raised["Qty"] = _num(_dec(free.get("Qty")) + _dec(linked.get("Qty")))
    body = _doc_header(kind, doc)
    body["Details"] = [_deleted(linked), raised]
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


_MIRRORED_REMARKS = ("Remark2", "Remark3", "Remark4")


# R4: the kinds whose mirror is proven (PO / SPO db3 16 Nov, QT F13); an SO verify stays strict.
MIRROR_KINDS = ("PO", "SPO", "QT")


def _remark_mirror(key: str, after: Doc, kind_name: str, asked: Sequence[str] = ()) -> bool:
    """AutoCount's wrapper copies Remark1 into Remark2..4 on every edit PUT (db3 6 Nov, QT
    DocKey 12147, F13; plan 65 probe P1, PO, Remark1 changed or not). A Remark2..4 that reads
    back equal to the read-back Remark1 is that copy, not drift. Nothing broader: Remark1
    itself, a Remark2..4 that reads back as anything else, and every other field still count.
    Plan 65 R4: always for ``MIRROR_KINDS``; any other kind (SO) only when the edit set Remark1
    (``asked``, the F13 rule as it stood before plan 65)."""
    return (key in _MIRRORED_REMARKS and (kind_name in MIRROR_KINDS or "Remark1" in asked)
            and _same(after.get(key), after.get("Remark1")))


def _drifted(before: Doc, after: Doc, skip_header: Sequence[str], skip_rows: Sequence[Any],
             kind_name: str) -> List[str]:
    out: List[str] = []
    for key in _COMPARE_HEADER:
        if key in before and key not in skip_header and not _same(before.get(key), after.get(key)):
            if not _remark_mirror(key, after, kind_name, skip_header):
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
        out.extend(f"Details[{dtl}].{k}" for k, v in change.items()
                   if k != "DtlKey" and k not in UNREADABLE_ROW_KEYS and not _same(row.get(k), v))
        original = _row_by_key(before, dtl) or {}
        out.extend(
            f"Details[{dtl}].{k}"
            for k in _COMPARE_LINE
            if k in original and k not in change and not _same(original.get(k), row.get(k))
        )
    out.extend(_drifted(before, after, list(header_changes), touched, kind_name))
    return out


def verify_delete_line(kind_name: str, before: Doc, dtl_key: int, after: Doc) -> Verdict:
    kind_of(kind_name)
    if _row_by_key(after, dtl_key) is not None:
        return Verdict(MISMATCH, "LINE_NOT_DELETED")
    if _drifted(before, after, (), [dtl_key], kind_name):
        return Verdict(MISMATCH, "COLLATERAL_CHANGE")
    return Verdict(DONE)


def verify_cancel(kind_name: str, after: Doc) -> Verdict:
    kind_of(kind_name)
    if after.get("Cancelled") == "T":
        return Verdict(DONE)
    return Verdict(MISMATCH, "CANCEL_IGNORED")


def change_landed(
    kind_name: str, primitive: str, before: Doc, after: Doc, *, header_changes: Mapping[str, Any] = {},
    line_changes: Sequence[Mapping[str, Any]] = (), line: Optional[Mapping[str, Any]] = None,
    dtl_key: Optional[int] = None,
) -> Tuple[bool, Optional[int]]:
    """AUTOCOUNT-STRANDED-OPS-B: did THIS write's own change reach AutoCount? ``(landed, new DtlKey)``. Unlike
    the verifiers it never judges the rest of the document (another person may have edited it since):
    an edit's asked values read back as asked, an added line reads back among the new rows, a deleted line is
    gone, a cancel reads cancelled. Unknown primitive -> not landed."""
    kind_of(kind_name)
    if primitive == "edit_doc":
        if any(not _same(after.get(k), v) for k, v in header_changes.items()):
            return False, None
        for change in line_changes:
            row = _row_by_key(after, change.get("DtlKey"))
            if row is None or any(not _same(row.get(k), v) for k, v in change.items()
                                  if k != "DtlKey" and k not in UNREADABLE_ROW_KEYS):
                return False, None
        return True, None
    if primitive == "add_line":
        sent = line or {}
        known = {r.get("DtlKey") for r in before.get("Details") or []}
        for row in after.get("Details") or []:
            if row.get("DtlKey") in known:
                continue
            relaxed = _relax_transfer(sent, row) if sent.get("FromDocDtlKey") else sent
            if _same_line(relaxed, row) and not _link_code(kind_name, sent, row):
                return True, row.get("DtlKey")
        return False, None
    if primitive == "delete_line":
        return _row_by_key(before, dtl_key) is not None and _row_by_key(after, dtl_key) is None, None
    if primitive == "cancel_doc":
        return after.get("Cancelled") == "T", None
    return False, None


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
    if _drifted(before, after, (), [], kind_name):
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
    if _drifted(before, after, (), [old_key], kind_name):
        return Verdict(MISMATCH, "COLLATERAL_CHANGE")
    return Verdict(DONE)


# The kept (cut) row of a link: only its quantity is sent changed; these must read back as before.
_KEPT_ROW_FIELDS = ("ItemCode", "UOM", "Location", "UnitPrice")

# PO-LINK-STUCK-RECONCILE-B s5 (prod 20 Nov, a qty move on a ~96-row PO): AutoCount recomputes the header's money
# and tax fields and its audit stamps on every save. Those are derived, never drift; every other header field we
# read must read back as it was.
_DERIVED_HEADER_KEYS = frozenset({
    "Total", "NetTotal", "LocalNetTotal", "Tax", "LocalTax", "ExTax", "LocalExTax", "TotalExTax", "TaxableAmt",
    "LocalTaxableAmt", "FinalTotal", "RoundAdj", "TaxEntityID",
})
_DERIVED_HEADER_PREFIXES = ("LastModified", "Created")
_DERIVED_HEADER_SUFFIXES = ("Total", "Tax", "ExTax", "TaxAmt", "Amt", "RoundAdj")


def vendor_derived_header(key: str) -> bool:
    """A header field AutoCount derives on a save (totals, tax, stamps): never judged as drift."""
    return (key in _DERIVED_HEADER_KEYS or key.startswith(_DERIVED_HEADER_PREFIXES)
            or key.endswith(_DERIVED_HEADER_SUFFIXES))


def header_moved(before: Doc, after: Doc, kind_name: str) -> List[str]:
    """Every header field read before a link that reads back otherwise (derived fields and the Remark mirror
    aside): the one header rule of the link comparator."""
    return [key for key in before if key != "Details" and not vendor_derived_header(key)
            and not _same(before.get(key), after.get(key)) and not _remark_mirror(key, after, kind_name)]


def verify_link_batch(
    kind_name: str, before: Doc, old_key: int, lines: Sequence[Mapping[str, Any]], after: Doc
) -> Verdict:
    """Plan 62: ``verify_link_doc`` for one row."""
    return verify_link_doc(kind_name, before, [(old_key, lines)], after)


def verify_link_doc(
    kind_name: str, before: Doc, groups: Sequence[Tuple[int, Sequence[Mapping[str, Any]]]], after: Doc
) -> Verdict:
    """Plan 62 / 69: every listed row is gone (all taken) or kept with its rest, exactly one new row per
    link reads back with its link and quantity (location, price and date aside: AutoCount resets them, the
    move step restores them), and no other row or header field moved."""
    kind_of(kind_name)
    total: List[Mapping[str, Any]] = []
    for old_key, lines in groups:
        old = _find_row(before, old_key)
        rest = _dec(old.get("Qty")) - sum((_dec(r.get("Qty")) for r in lines), Decimal(0))
        now = _row_by_key(after, old_key)
        if rest == 0:
            if now is not None:
                return Verdict(MISMATCH, "LINE_NOT_DELETED")
        elif now is None or _dec(now.get("Qty")) != rest or not all(
            _same(old.get(k), now.get(k)) for k in _KEPT_ROW_FIELDS if k in old
        ):  # PO-LINK-STUCK-RECONCILE-B: the kept row is as sent (its rest), never moved or repriced
            return Verdict(MISMATCH, "ROW_MISMATCH")
        total.extend(lines)
    known = {r.get("DtlKey") for r in before.get("Details") or []}
    added = [r for r in after.get("Details") or [] if r.get("DtlKey") not in known]
    if len(added) != len(total):
        return Verdict(MISMATCH, "ROWS_DROPPED" if len(added) < len(total) else "ROWS_UNEXPECTED")
    left = list(added)
    for line in total:
        match = next((r for r in left if _link_of_row(kind_name, r) == int(line.get("FromDocDtlKey") or 0)
                      and _dec(r.get("Qty")) == _dec(line.get("Qty"))
                      and r.get("ItemCode") == line.get("ItemCode") and r.get("UOM") == line.get("UOM")), None)
        if match is None:
            return Verdict(MISMATCH, "LINK_MISMATCH")
        left.remove(match)
    if _drifted(before, after, (), [k for k, _ in groups], kind_name) or header_moved(before, after, kind_name):
        return Verdict(MISMATCH, "COLLATERAL_CHANGE")
    return Verdict(DONE)


_NUMERIC_ROW_KEYS = ("UnitPrice",)


def _kept_value(field_name: str, before: Any, after: Any) -> bool:
    """Plan 71 review: the same value however a read spells it - dates by day (``same_row_value``), empty = empty
    (None / ""), a numeric field by value (``1.5`` == ``"1.50"``); text exactly."""
    if field_name == "DeliveryDate":
        return same_row_value(field_name, before, after)
    if before in (None, "") and after in (None, ""):
        return True
    if field_name in _NUMERIC_ROW_KEYS:
        nb, na = _num_of(before), _num_of(after)
        if nb is not None and na is not None:
            return nb == na
    return _same(before, after)


def merge_row_drift(kind_name: str, before_row: Mapping[str, Any], after_row: Mapping[str, Any]) -> List[str]:
    """Plan 71 (CRM SS contract read-back): the fields of the row a merge raised that moved, other than Qty,
    compared to THAT row's own before-image (never the tied row or the request). Location, DeliveryDate, price
    and the rest of ``_COMPARE_LINE``, plus the row's link (it stays untied). ``FurtherDescription`` (the note)
    is never returned by a read (``UNREADABLE_ROW_KEYS``); a merge sends it as read and never compares it."""
    out = [k for k in _COMPARE_LINE
           if k != "Qty" and k in before_row and not _kept_value(k, before_row.get(k), after_row.get(k))]
    if _link_of_row(kind_name, dict(after_row)) != _link_of_row(kind_name, dict(before_row)):
        out.append("FromSODtlKey" if kind_name == "PO" else "FromDocDtlKey")
    return out


def verify_unlink_merge(kind_name: str, before: Doc, linked_key: int, free_key: int, after: Doc) -> Verdict:
    """The linked row is gone, the free row holds the sum and nothing else of it moved, no new row, nothing
    else moved."""
    kind_of(kind_name)
    if _row_by_key(after, linked_key) is not None:
        return Verdict(MISMATCH, "LINE_NOT_DELETED")
    free = _row_by_key(after, free_key)
    want = _dec(_row_by_key(before, free_key).get("Qty")) + _dec(_row_by_key(before, linked_key).get("Qty"))  # type: ignore[union-attr]
    if free is None or _dec(free.get("Qty")) != want:
        return Verdict(MISMATCH, "ROW_MISMATCH")
    if merge_row_drift(kind_name, _row_by_key(before, free_key) or {}, free):
        return Verdict(MISMATCH, "ROW_MISMATCH")  # plan 71: only the free row's Qty may change
    known = {r.get("DtlKey") for r in before.get("Details") or []}
    if [r for r in after.get("Details") or [] if r.get("DtlKey") not in known]:
        return Verdict(MISMATCH, "ROWS_UNEXPECTED")
    if _drifted(before, after, (), [linked_key, free_key], kind_name):
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
