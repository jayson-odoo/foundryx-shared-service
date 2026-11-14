"""Vendor capability switches for write-back (plan 55 section 6a-2, plan 61 section 4.5).

db3 10 Nov 2026 (plan 61 facts F4..F12): one PUT deletes a row (``FullTransferOption
"D"``) and adds its replacement (``DtlKey 0``), so unlink, whole-row link, relink and
delete line are applied; cancel is ``DELETE /Cancel<Doc>bydocno``. Always read at call
time (``capabilities.VENDOR_CAPABILITIES``), never through a from-import, so a flip
takes effect without a restart of the reader's own copy.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

VENDOR_CAPABILITIES: Mapping[str, bool] = MappingProxyType(
    {
        "link_new_row": True,
        "link_existing_row": True,  # F5: one replace PUT [normal row "D", new linked row]
        "unlink": True,  # F4: one replace PUT [linked row "D", new normal row]
        "spo_unlink": False,  # F14: db3 cannot make an SPO, nothing probed
    }
)

# Plan 57 section 5.1: per kind and primitive, read at call time through ``capable``.
# Plan 61 (db3 10 Nov): delete_line (F6) and cancel_doc (F9) on for QT / SO / PO; SPO
# keeps only edit_doc (F14); delete_doc has no vendor door on any kind.
_PRIMITIVES = ("create_doc", "edit_doc", "add_line", "delete_line", "delete_doc", "cancel_doc")
_ON = {
    ("QT", "create_doc"), ("QT", "edit_doc"), ("QT", "add_line"), ("QT", "delete_line"), ("QT", "cancel_doc"),
    ("SO", "create_doc"), ("SO", "edit_doc"), ("SO", "add_line"), ("SO", "delete_line"), ("SO", "cancel_doc"),
    ("PO", "create_doc"), ("PO", "edit_doc"), ("PO", "add_line"), ("PO", "delete_line"), ("PO", "cancel_doc"),
    ("SPO", "edit_doc"),
}
CAPABILITIES: Mapping[tuple[str, str], bool] = MappingProxyType(
    {(k, p): (k, p) in _ON for k in ("QT", "SO", "PO", "SPO") for p in _PRIMITIVES}
)

# A create without a DocNo sends "<<New>>" and AutoCount numbers it (probe P-DOC2).
AUTO_DOCNO = True
# Owner ruling Q2: a partly received PO row is cut to the received qty and the open
# remainder added as a new row; False = refuse any receipt.
PARTIAL_RECEIPT_SPLIT = True


def capable(kind: str, primitive: str) -> bool:
    """Whether ``primitive`` is switched on for ``kind`` (unknown pair = False)."""
    return bool(CAPABILITIES.get((kind, primitive), False))
