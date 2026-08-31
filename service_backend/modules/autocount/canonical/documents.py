"""Canonical documents - Sales Order and Purchase Order (plan 22 S5, AC-22-24).

    !!  THESE ARE A STRICT SUBSET OF SORENTO'S OWN SCHEMAS, READ FROM SOURCE.  !!
    !!  `app/schemas/canonical_documents.py` sets ``extra="forbid"``, so a     !!
    !!  field we invent is a hard PER-RECORD REJECTION, not a warning.        !!

Three things differ from a master (``canonical/masters.py``):

**A document owns its lines.** They arrive nested under the header - one push
is one atomic statement about the whole order, so a header can never land
without its lines (AC-13-06's rule, restated for documents).

**Refs are two-tier.** The header mints ``{DatabaseName}:{DocKey}`` (identical
to a master's ``company_qualified_identity`` - ``mapping.flat_source_ref``
with a single key column IS this scheme). A LINE mints
``{DatabaseName}:{DocKey}:{DtlKey}`` - the header's own ref, colon-joined with
the line's own key column value (``mapping.MappingEngine`` composes this via
``EntityProfile.line_ref_prefix``, never here - a canonical model never mints
its own identity, see ``canonical/base.py``).

**Master references are INTEGRATION REFS, not codes** (Appendix A6 item 3):
``customer_ref``/``sales_agent_ref``/``supplier_ref`` (header) and
``product_ref``/``warehouse_ref`` (line) carry the ``source_ref`` the
REFERENCED master was pushed under - ``{DatabaseName}:{code}`` for every
master except the shared ``sales_agent`` (``agent:{CODE}``). Minted by
``mapping.mint_master_ref`` (which calls the SAME ``flat_source_ref`` a
master task uses for its own identity), never invented here - the scheme must
never drift between "the ref a master mints for itself" and "the ref a
document mints to point at one".

**Status is a fixed, five-word vocabulary** (Appendix A6 item 2): Sorento maps
canonical `status` onto two DIFFERENT internal enums (SO vs PO) - what is
fixed on OUR side is the five words and that an unrecognised one is a NAMED
per-field rejection at MAPPING time (``mapped.errors``), never a silent pass
that only fails later as Sorento's per-record ``errors.status``.

Money and quantity are ``Decimal``, never float - the same house rule as every
other canonical shape.
"""
from __future__ import annotations

from datetime import date
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from .base import CanonicalLine, CanonicalRecord

ENTITY_SALES_ORDER = "sales_order"
ENTITY_PURCHASE_ORDER = "purchase_order"

DOCUMENT_ENTITY_TYPES: Tuple[str, ...] = (ENTITY_SALES_ORDER, ENTITY_PURCHASE_ORDER)


def is_document_entity(entity_type: str) -> bool:
    return entity_type in DOCUMENT_ENTITY_TYPES


# The raw-row key a document's fetched lines are nested under (plan 22 §2.5/S5).
# `SqlDbSource` fetches a header task's rows, then - for a DOCUMENT entity only -
# runs the task's `lineQuery` once per header (`:doc_key` bound) and nests the
# result here, so `MappingEngine`'s EXISTING `detail_key` mechanism (built for
# the API path's nested vendor envelope) reads it with zero engine changes.
SQL_DOC_LINES_KEY = "_lines"

# Appendix A6 item 2 - the FIXED five-word vocabulary. An unrecognised value is
# a per-field ``mapped.errors`` rejection (the `status` field_validator below),
# never a value we forward and let Sorento reject as `errors.status`.
DOCUMENT_STATUS_VALUES: Tuple[str, ...] = (
    "open", "partial", "fulfilled", "closed", "cancelled",
)


class CanonicalDocumentLine(CanonicalLine):
    """Shared line rules (mirrors Sorento's ``_CanonicalLine``).

    Not a ``CanonicalMaster`` - a line carries no ``source_doc_no`` (Sorento's
    schema agrees: ``_CanonicalLine`` extends bare ``BaseModel``, not
    ``_Canonical``).
    """

    # AutoCount's ``DtlKey`` value, PRE-prefix - `MappingEngine` composes the
    # full `{header_ref}:{DtlKey}` ref post-mapping (`line_ref_prefix`), so by
    # the time a line reaches the sink this already carries the composed ref.
    product_ref: Optional[str] = Field(None, max_length=255)
    warehouse_ref: Optional[str] = Field(None, max_length=255)
    qty_ordered: Optional[Decimal] = Field(None, ge=0)
    discount: Optional[Decimal] = None
    line_total: Optional[Decimal] = None
    uom: Optional[str] = Field(None, max_length=100)
    extras: Dict[str, Any] = Field(default_factory=dict)

    #     !!  THE ONLY KEYS THAT MAY CROSS THE WIRE TO SORENTO.  !!
    SINK_FIELDS: ClassVar[Tuple[str, ...]] = ()

    def sink_payload(self) -> Dict[str, Any]:
        data = self.model_dump(mode="json")
        return {key: data[key] for key in self.SINK_FIELDS if key in data}


class CanonicalSalesOrderLine(CanonicalDocumentLine):
    qty_delivered: Optional[Decimal] = Field(None, ge=0)
    unit_price: Optional[Decimal] = None
    # PER LINE, not per header - one order routinely carries several delivery
    # dates (Sorento's own ADR-0011 reasoning, mirrored here).
    required_date: Optional[date] = None

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref", "product_ref", "warehouse_ref", "qty_ordered",
        "qty_delivered", "unit_price", "discount", "line_total", "uom",
        "required_date",
    )


class CanonicalPurchaseOrderLine(CanonicalDocumentLine):
    qty_received: Optional[Decimal] = Field(None, ge=0)
    unit_cost: Optional[Decimal] = None
    currency: Optional[str] = Field(None, max_length=3)
    expected_date: Optional[date] = None

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref", "product_ref", "warehouse_ref", "qty_ordered",
        "qty_received", "unit_cost", "discount", "line_total", "uom",
        "currency", "expected_date",
    )


class CanonicalDocument(CanonicalRecord):
    """Shared header rules (mirrors Sorento's ``_CanonicalDocument``)."""

    status: Optional[str] = Field(None, max_length=50)
    source_doc_no: Optional[str] = None
    internal_note: Optional[str] = None
    lines: List[CanonicalDocumentLine] = Field(default_factory=list)
    extras: Dict[str, Any] = Field(default_factory=dict)

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = ()

    @field_validator("status")
    @classmethod
    def _status_in_the_fixed_vocabulary(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in DOCUMENT_STATUS_VALUES:
            raise ValueError(
                f"'{value}' is not a recognised document status - use one of "
                f"{', '.join(DOCUMENT_STATUS_VALUES)}"
            )
        return normalized

    @model_validator(mode="after")
    def _line_refs_are_unique(self) -> "CanonicalDocument":
        """One DtlKey, one line (mirrors Sorento's own guard). Two lines
        sharing a key cannot both be upserted onto it - last-one-wins would
        silently drop a quantity somebody ordered, so the whole document is
        quarantined instead (D13's all-or-nothing rule)."""
        seen: set = set()
        duplicates: set = set()
        for line in self.lines:
            if line.source_ref in seen:
                duplicates.add(line.source_ref)
            seen.add(line.source_ref)
        if duplicates:
            raise ValueError(
                f"duplicate line source_ref: {', '.join(sorted(duplicates))}"
            )
        return self

    def sink_payload(self) -> Dict[str, Any]:
        data = self.model_dump(mode="json")
        payload = {key: data[key] for key in self.SINK_FIELDS if key in data}
        payload["lines"] = [line.sink_payload() for line in self.lines]
        return payload


class CanonicalSalesOrder(CanonicalDocument):
    """AutoCount SO → Sorento ``sales_orders`` (Appendix A6 §3/A8).

    ``source_ref`` is the header's ``DocKey``; ``so_number`` is its ``DocNo`` -
    the field Sorento ADOPTS an existing row by on a first sync, mirroring the
    same DocKey-vs-DocNo distinction every other canonical shape makes.
    """

    entity_type: str = ENTITY_SALES_ORDER

    so_number: Optional[str] = Field(None, max_length=100)
    customer_ref: Optional[str] = Field(None, max_length=255)
    sales_agent_ref: Optional[str] = Field(None, max_length=255)
    doc_date: Optional[date] = None
    requested_delivery_date: Optional[date] = None
    lines: List[CanonicalSalesOrderLine] = Field(default_factory=list)

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref", "so_number", "customer_ref", "sales_agent_ref",
        "doc_date", "requested_delivery_date", "status", "internal_note",
    )


class CanonicalPurchaseOrder(CanonicalDocument):
    """AutoCount PO → Sorento ``purchase_orders`` (Appendix A6 §3/A8)."""

    entity_type: str = ENTITY_PURCHASE_ORDER

    po_number: Optional[str] = Field(None, max_length=100)
    supplier_ref: Optional[str] = Field(None, max_length=255)
    issue_date: Optional[date] = None
    expected_date: Optional[date] = None
    currency: Optional[str] = Field(None, max_length=3)
    lines: List[CanonicalPurchaseOrderLine] = Field(default_factory=list)

    #     !!  NO `internal_note` HERE - LIVE-VERIFY CAUGHT THIS (plan 22 S5).  !!
    # Sorento's `_CanonicalDocument` base carries no `internal_note` field at
    # all; only `CanonicalSalesOrder` declares its own. Sending it for a PO
    # trips their `extra="forbid"` guard - "Extra inputs are not permitted" -
    # and quarantines every purchase order. `internal_note` stays on OUR
    # shared `CanonicalDocument` (an operator may still map it locally) but is
    # excluded from the wire payload here.
    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref", "po_number", "supplier_ref", "issue_date",
        "expected_date", "currency", "status",
    )
