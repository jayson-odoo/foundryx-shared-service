"""Canonical Goods Received Note (AC-13-06).

Header with lines NESTED - AutoCount returns both in ONE response, and the
canonical shape preserves that: a GRN is one record, not a header record plus N
line records. No per-document fan-out anywhere in the pipeline.

Money and quantity are ``Decimal``, never float - an 8-dp vendor string
(``120.00000000``) through a float loses cents at scale, and these values end up
in a financial document.

Every field is OPTIONAL except ``source_ref``/``entity_type``. That is
deliberate: which fields exist is decided by **mapping rows** (D5), which vary
per customer. Making a field mandatory here would hardcode a mapping decision
into code and defeat the whole point - a required field is enforced by the
mapping row's ``is_required`` flag instead, where a customer's admin can see it.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import Field

from .base import CanonicalLine, CanonicalRecord

ENTITY_GOODS_RECEIVED_NOTE = "goods_received_note"

# The vendor entity name in the URL grammar: POST /api/{Entity}/Get{Entity}.
VENDOR_ENTITY = "GoodsReceivedNote"

# The nested detail array key for GRN is **GRDTL**, NOT "GRNDTL" (plan §4a
# hazard table - verified live). Per-entity, held in config, never guessed.
VENDOR_DETAIL_KEY = "GRDTL"


class CanonicalGrnLine(CanonicalLine):
    item_code: Optional[str] = None
    description: Optional[str] = None
    qty: Optional[Decimal] = None
    uom: Optional[str] = None
    unit_price: Optional[Decimal] = None
    sub_total: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    tax_rate: Optional[str] = None
    location: Optional[str] = None
    delivery_date: Optional[date] = None
    # Per-customer UDF values, extracted by mapping rows into named canonical
    # keys. A customer with no UDFs simply has no rows and this stays empty.
    extras: Dict[str, Any] = Field(default_factory=dict)


class CanonicalGrn(CanonicalRecord):
    entity_type: str = ENTITY_GOODS_RECEIVED_NOTE

    doc_no: Optional[str] = None  # DISPLAY only - mutable, never a correlation key
    supplier_code: Optional[str] = None
    supplier_name: Optional[str] = None
    doc_date: Optional[date] = None
    currency_code: Optional[str] = None
    currency_rate: Optional[Decimal] = None
    net_total: Optional[Decimal] = None
    tax_total: Optional[Decimal] = None
    total: Optional[Decimal] = None
    description: Optional[str] = None
    # From the vendor's "T"/"F" string - a real bool by the time it is here.
    cancelled: Optional[bool] = None
    # Drives the watermark. Aware-UTC (UTCDateTime discipline).
    last_modified: Optional[datetime] = None
    last_modified_user_id: Optional[str] = None
    created_at_source: Optional[datetime] = None
    created_user_id: Optional[str] = None

    lines: List[CanonicalGrnLine] = Field(default_factory=list)
    extras: Dict[str, Any] = Field(default_factory=dict)
