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
