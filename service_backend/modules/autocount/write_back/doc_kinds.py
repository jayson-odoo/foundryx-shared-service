"""The document kinds the write layer addresses (plan 57 section 5.1, AC-57-01).

One frozen ``DocKind`` per kind. SPO is the PO door with header ``ShippingPO "T"``.
Plan 61 (db3 10 Nov 2026, F1 / F9): one document is read with
``GET /<Doc>bydocno?DocNo=`` and cancelled with ``DELETE /Cancel<Doc>bydocno?DocNo=``
(no body). A line is deleted by the edit door (a row with ``FullTransferOption "D"``);
AutoCount has no door that deletes a whole document.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class DocKind:
    name: str
    new_path: str
    edit_path: str
    by_date_path: str
    by_modified_path: str
    party_field: str
    by_doc_no_path: str
    cancel_path: str


_QT = DocKind(
    "QT", "/NewQuotation", "/EditQuotationbydockey", "/quotationbydocdate",
    "/quotationbyLastModified", "DebtorCode", "/Quotationbydocno", "/CancelQuotationbydocno",
)
_SO = DocKind(
    "SO", "/NewSalesOrder", "/EditSalesOrderbydockey", "/salesorderbydocdate",
    "/salesorderbyLastModified", "DebtorCode", "/SalesOrderbydocno", "/CancelSalesOrderbydocno",
)
_PO = DocKind(
    "PO", "/NewPurchaseOrder", "/EditPurchaseOrderbydockey", "/purchaseorderbydocdate",
    "/purchaseorderbyLastModified", "CreditorCode", "/PurchaseOrderbydocno", "/CancelPurchaseOrderbydocno",
)
_SPO = DocKind(
    "SPO", _PO.new_path, _PO.edit_path, _PO.by_date_path, _PO.by_modified_path, "CreditorCode",
    _PO.by_doc_no_path, _PO.cancel_path,
)

KINDS: Mapping[str, DocKind] = MappingProxyType({k.name: k for k in (_QT, _SO, _PO, _SPO)})


def kind_of(name: object) -> DocKind:
    """The kind named ``name``; anything else is a ``ValueError``."""
    if isinstance(name, str) and name in KINDS:
        return KINDS[name]
    raise ValueError("Unknown document kind.")


# The gateway's wire name of each kind (contract section 1).
WIRE_SLUGS: Mapping[str, str] = MappingProxyType({
    "QT": "quotations", "SO": "sales-orders", "PO": "purchase-orders", "SPO": "shipping-purchase-orders",
})
