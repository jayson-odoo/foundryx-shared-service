"""The document kinds the write layer addresses (plan 57 section 5.1, AC-57-01).

One frozen ``DocKind`` per kind. SPO is the PO door with header ``ShippingPO "T"``.
The delete shapes are ONE placeholder entry per kind, UNVERIFIED (AQ23): AutoCount
has not published the real delete door yet, so plugging it in = editing this table.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class VendorShape:
    method: str
    path: str


@dataclass(frozen=True)
class DocKind:
    name: str
    new_path: str
    edit_path: str
    by_date_path: str
    by_modified_path: str
    party_field: str
    delete_line: VendorShape
    delete_doc: VendorShape


def _shape(path: str) -> VendorShape:
    return VendorShape("DELETE", path)  # UNVERIFIED AQ23: placeholder, body {DocKey, DtlKey}


_QT = DocKind(
    "QT", "/NewQuotation", "/EditQuotationbydockey", "/quotationbydocdate",
    "/quotationbyLastModified", "DebtorCode",
    _shape("/DeleteQuotationDetailbydtlkey"), _shape("/DeleteQuotationbydockey"),
)
_SO = DocKind(
    "SO", "/NewSalesOrder", "/EditSalesOrderbydockey", "/salesorderbydocdate",
    "/salesorderbyLastModified", "DebtorCode",
    _shape("/DeleteSalesOrderDetailbydtlkey"), _shape("/DeleteSalesOrderbydockey"),
)
_PO = DocKind(
    "PO", "/NewPurchaseOrder", "/EditPurchaseOrderbydockey", "/purchaseorderbydocdate",
    "/purchaseorderbyLastModified", "CreditorCode",
    _shape("/DeletePurchaseOrderDetailbydtlkey"), _shape("/DeletePurchaseOrderbydockey"),
)
_SPO = DocKind(
    "SPO", _PO.new_path, _PO.edit_path, _PO.by_date_path, _PO.by_modified_path, "CreditorCode",
    _PO.delete_line, _PO.delete_doc,
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
