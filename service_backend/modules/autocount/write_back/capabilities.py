"""Vendor capability switches for write-back (plan 55 section 6a-2).

db3 4 Nov: AutoCount's wrapper does not apply these edits yet; flip after a db3
rerun proves them. Always read at call time (``capabilities.VENDOR_CAPABILITIES``),
never through a from-import, so a flip takes effect without a restart of the
reader's own copy.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

VENDOR_CAPABILITIES: Mapping[str, bool] = MappingProxyType(
    {
        "link_new_row": True,
        "link_existing_row": False,
        "unlink": False,
        "spo_unlink": False,
    }
)

# Whole-row link emulated as: original row to Qty 0 plus a new linked row, then
# the location move. Off until a db3 rerun shows the vendor accepts a zero qty.
ZERO_QTY_EMULATION = False

# Plan 57 section 5.1: per kind and primitive. Read at call time through
# ``capable`` (db3 probes 4 Nov: the wrapper ignores a header Cancelled and has no
# published delete door, so delete_line / delete_doc / cancel_doc stay off).
_PRIMITIVES = ("create_doc", "edit_doc", "add_line", "delete_line", "delete_doc", "cancel_doc")
_ON = {
    ("QT", "create_doc"), ("QT", "edit_doc"), ("QT", "add_line"),
    ("SO", "create_doc"), ("SO", "edit_doc"), ("SO", "add_line"),
    ("PO", "create_doc"), ("PO", "edit_doc"), ("PO", "add_line"),
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
