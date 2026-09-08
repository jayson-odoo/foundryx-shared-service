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

from pydantic import BaseModel, Field, field_validator, model_validator

from .base import CanonicalLine, CanonicalRecord

ENTITY_SALES_ORDER = "sales_order"
ENTITY_PURCHASE_ORDER = "purchase_order"
# sprint-5/02 S3 (addendum section 3) - a LINE-SET entity on Sorento's side
# (no header table, rows land in `spo_allocations`) but a normal document on
# OUR side: own header+line fetch, own mapping/status/filter formula. The
# ESB's "PO vs SPO" split is the documented `filterFormula` string on each
# sibling task (SPO: `startswith`, PO: `not(startswith(...))`), never a
# runtime branch here.
ENTITY_SHIPPING_ORDER = "shipping_order"

DOCUMENT_ENTITY_TYPES: Tuple[str, ...] = (
    ENTITY_SALES_ORDER, ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER,
)


def is_document_entity(entity_type: str) -> bool:
    return entity_type in DOCUMENT_ENTITY_TYPES


# The raw-row key a document's fetched lines are nested under (plan 22 §2.5/S5).
# `SqlDbSource` fetches a header task's rows, then - for a DOCUMENT entity only -
# runs the task's `lineQuery` once per header (`:doc_key` bound) and nests the
# result here, so `MappingEngine`'s EXISTING `detail_key` mechanism (built for
# the API path's nested vendor envelope) reads it with zero engine changes.
SQL_DOC_LINES_KEY = "_lines"

# The line query's bound-parameter name (plan 22 S5 review BLOCKER 1). Every
# document task's ``lineQuery`` MUST filter on exactly this bind - checked
# both at save time (``EtlService.validate_source_config``) and again at
# construction time (``SqlDbSource.__init__``) via ``guard.query_binds_param``.
# SQLAlchemy silently ignores a param passed to ``execute`` that the
# statement never references, so a ``lineQuery`` missing the bind would
# preview clean, save clean, then attach the WHOLE line table to every header
# at run time instead of just that header's own rows.
LINE_QUERY_DOC_KEY_PARAM = "doc_key"

# Appendix A6 item 2 - the FIXED five-word vocabulary. An unrecognised value is
# a per-field ``mapped.errors`` rejection (the `status` field_validator below),
# never a value we forward and let Sorento reject as `errors.status`.
DOCUMENT_STATUS_VALUES: Tuple[str, ...] = (
    "open", "partial", "fulfilled", "closed", "cancelled",
)

# sprint-5/06 (Definitions section of the UAC) - the eight operator-mappable
# line INPUT fields that feed engine minting and are NEVER sent on the wire
# (declared on `CanonicalPurchaseOrderLine`/`CanonicalShippingOrderLine`
# only - `CanonicalSalesOrderLine` gains none of them). Named once here so
# `mapping.py` (minting + save-time transform pairing) and
# `mapping_catalog.py` (the LINE picker) read the SAME set rather than a
# second hand-typed copy that could drift.
LINE_LINKAGE_INPUT_FIELDS: Tuple[str, ...] = (
    "from_so_doc_key", "from_so_line_key",
    "from_so_external_db", "from_so_external_doc_key",
    "from_so_external_doc_no", "from_so_external_line_key",
    "from_po_doc_key", "from_po_line_key",
)
# (sprint-5/06 review nit) - the five WIRE fields and the three ENGINE-MINTED
# ones among them (`from_so_line_ref`/`from_so_external`/`from_po_line_ref`)
# used to live here as two more module-level tuples; dropped as dead code -
# neither was ever imported anywhere (`mapping_catalog.py` builds its own
# `_LINE_LINKAGE_DIRECT_WIRE_FIELDS` + reads `FALLBACK_FIELDS` straight off
# the model instead, and `OMIT_WHEN_EMPTY_FIELDS` below is its own hand-typed
# tuple per subclass). If a THIRD hand-typed copy of either set ever shows up,
# promote one of these back as the single source rather than re-adding an
# unused constant.


class FromSoExternal(BaseModel):
    """sprint-5/06 (AC-06-02/06) - a same-book ICB (inter-company) reference:
    ``db``/``doc_key``/``doc_no``/``dtl_key`` of a sales order the PO/SPO
    line was raised for, in a DIFFERENT AutoCount book than the one this
    line was fetched from (same-book linkage is ``from_so_line_ref``
    instead). All four fields are optional AT THE MODEL LEVEL - the "``db``
    is set whenever the object exists" invariant is upheld by the engine's
    minting step (``mapping.py``: the object is only ever constructed when
    the mapped ``from_so_external_db`` resolves), never by validation here.
    A key that does not resolve in this book never travels as a same-book
    ref (the Sorento owner's rule, grill D6).

    ``db`` is REQUIRED and non-blank here (codex round finding 2) - the
    engine only ever constructs this object when the mapped
    ``from_so_external_db`` resolved (``mapping.py``'s minting step), so a
    validated instance can never carry ``db=None``/``""``; ``sink_payload``
    can therefore never emit ``{"db": null}``. The other three fields stay
    optional at the model level (a resolved ``db`` does not guarantee the
    doc/dtl keys also resolved)."""

    db: str = Field(min_length=1, max_length=100)
    doc_key: Optional[int] = None
    doc_no: Optional[str] = Field(None, max_length=100)
    dtl_key: Optional[int] = None


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
    # sprint-5/02 S3 (addendum section 1) - code/name fallbacks for a
    # customer login that only exposes document tables (a master task never
    # ran, so no ref exists yet); `line_number` (AutoCount `Seq`) so
    # Sorento's cutover adoption can match a ref-less line by position
    # (addendum section 9). ALL of these are contract-version 2 ONLY - see
    # `sink_payload`.
    product_code: Optional[str] = Field(None, max_length=100)
    product_name: Optional[str] = None
    warehouse_code: Optional[str] = Field(None, max_length=100)
    line_number: Optional[int] = None
    extras: Dict[str, Any] = Field(default_factory=dict)

    #     !!  THE ONLY KEYS THAT MAY CROSS THE WIRE TO SORENTO.  !!
    SINK_FIELDS: ClassVar[Tuple[str, ...]] = ()
    # Fields gated behind `contract_version >= 2` (AC-02-14/27) - never sent
    # to a v1 (pre-addendum) Sorento, which has no columns for them.
    FALLBACK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "product_code", "product_name", "warehouse_code", "line_number",
    )
    # sprint-5/06 (AC-06-03) - the `container_number` rule, generalised: a
    # fallback field named here is DROPPED from the payload (never sent as
    # an explicit `null`/`[]`) when its value is empty. Absent means "leave
    # Sorento's stored value alone"; `null` means "clear it" - a linkage
    # field the engine could not resolve THIS run must never send the clear
    # signal. Empty on the shared base; PO/SPO lines populate it (Group A).
    OMIT_WHEN_EMPTY_FIELDS: ClassVar[Tuple[str, ...]] = ()

    def sink_payload(self, *, contract_version: int = 1) -> Dict[str, Any]:
        """The wire shape for ONE line. ``contract_version`` (default 1,
        AC-02-14) is the connection's own ``sorento_contract_version``
        setting - the AUTHORITATIVE gate. It is never inferred from what
        Sorento's `/contract` endpoint advertises (that is advisory only,
        see `sinks_sorento.py`)."""
        data = self.model_dump(mode="json")
        keys = list(self.SINK_FIELDS)
        if contract_version >= 2:
            keys = keys + list(self.FALLBACK_FIELDS)
        payload = {key: data[key] for key in keys if key in data}
        for name in self.OMIT_WHEN_EMPTY_FIELDS:
            if not payload.get(name):
                payload.pop(name, None)
        return payload


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
    # addendum section 4 - the AutoCount `FromSODocList` comma-separated cell,
    # split/stripped/blank-dropped by the ESB (never sent as a raw string -
    # Sorento's `order_link_service.claim_book_pairing` runs once per value).
    from_so_numbers: Optional[List[str]] = None

    #     !!  LINE LINKAGE (sprint-5/06, AC-06-02) - INPUT then WIRE.  !!
    # Input fields feed engine minting (`mapping.py`, right beside the
    # line's own `source_ref` composition) and are NEVER sent to Sorento -
    # they never appear in SINK_FIELDS/FALLBACK_FIELDS below. Wire fields
    # join FALLBACK_FIELDS (contract >= 2); the ref pair is minted, the
    # object is minted, `from_so_numbers`/`from_po_number` are mapped
    # directly (see `documents.py`'s own module docstring precedent and
    # plan 06 section 2.1's table).
    from_so_doc_key: Optional[int] = None
    from_so_line_key: Optional[int] = None
    from_so_external_db: Optional[str] = Field(None, max_length=100)
    from_so_external_doc_key: Optional[int] = None
    from_so_external_doc_no: Optional[str] = Field(None, max_length=100)
    from_so_external_line_key: Optional[int] = None
    from_po_doc_key: Optional[int] = None
    from_po_line_key: Optional[int] = None

    from_so_line_ref: Optional[str] = Field(None, max_length=255)
    from_so_external: Optional[FromSoExternal] = None
    from_po_line_ref: Optional[str] = Field(None, max_length=255)
    from_po_number: Optional[str] = Field(None, max_length=100)

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref", "product_ref", "warehouse_ref", "qty_ordered",
        "qty_received", "unit_cost", "discount", "line_total", "uom",
        "currency", "expected_date",
    )
    FALLBACK_FIELDS: ClassVar[Tuple[str, ...]] = (
        CanonicalDocumentLine.FALLBACK_FIELDS + (
            "from_so_numbers", "from_so_line_ref", "from_so_external",
            "from_po_line_ref", "from_po_number",
        )
    )
    OMIT_WHEN_EMPTY_FIELDS: ClassVar[Tuple[str, ...]] = (
        "from_so_numbers", "from_so_line_ref", "from_so_external",
        "from_po_line_ref", "from_po_number",
    )


class CanonicalShippingOrderLine(CanonicalDocumentLine):
    """addendum section 3 - a shipping order's lines land in Sorento's
    ``spo_allocations``, identified by ``source_ref`` (DtlKey) via
    ``integration_references`` (entity ``spo_allocations``), NOT the
    upload's ``(spo, item, location, occurrence)`` scheme."""

    qty_received: Optional[Decimal] = Field(None, ge=0)
    unit_cost: Optional[Decimal] = None
    expected_date: Optional[date] = None
    from_so_numbers: Optional[List[str]] = None

    # Line linkage (sprint-5/06, AC-06-02) - identical shape to the PO
    # line's own (see its comment above); a source PO line for an SPO
    # (`from_po_line_ref`/`from_po_number`) is the primary use of THIS
    # entity's linkage, an SO source (`from_so_*`) still possible when an
    # SPO was itself raised for a sales order.
    from_so_doc_key: Optional[int] = None
    from_so_line_key: Optional[int] = None
    from_so_external_db: Optional[str] = Field(None, max_length=100)
    from_so_external_doc_key: Optional[int] = None
    from_so_external_doc_no: Optional[str] = Field(None, max_length=100)
    from_so_external_line_key: Optional[int] = None
    from_po_doc_key: Optional[int] = None
    from_po_line_key: Optional[int] = None

    from_so_line_ref: Optional[str] = Field(None, max_length=255)
    from_so_external: Optional[FromSoExternal] = None
    from_po_line_ref: Optional[str] = Field(None, max_length=255)
    from_po_number: Optional[str] = Field(None, max_length=100)

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref", "product_ref", "warehouse_ref", "qty_ordered",
        "qty_received", "unit_cost", "uom", "expected_date",
    )
    FALLBACK_FIELDS: ClassVar[Tuple[str, ...]] = (
        CanonicalDocumentLine.FALLBACK_FIELDS + (
            "from_so_numbers", "from_so_line_ref", "from_so_external",
            "from_po_line_ref", "from_po_number",
        )
    )
    OMIT_WHEN_EMPTY_FIELDS: ClassVar[Tuple[str, ...]] = (
        "from_so_numbers", "from_so_line_ref", "from_so_external",
        "from_po_line_ref", "from_po_number",
    )


class CanonicalDocument(CanonicalRecord):
    """Shared header rules (mirrors Sorento's ``_CanonicalDocument``)."""

    status: Optional[str] = Field(None, max_length=50)
    source_doc_no: Optional[str] = None
    internal_note: Optional[str] = None
    lines: List[CanonicalDocumentLine] = Field(default_factory=list)
    extras: Dict[str, Any] = Field(default_factory=dict)

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = ()
    # Contract-version-2-only fields (AC-02-14/27) - empty on the shared base,
    # each subclass declares its OWN (the field names differ: customer_* vs
    # supplier_*).
    FALLBACK_FIELDS: ClassVar[Tuple[str, ...]] = ()

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

    def sink_payload(self, *, contract_version: int = 1) -> Dict[str, Any]:
        """The connection's ``sorento_contract_version`` (default 1) is the
        AUTHORITATIVE gate (AC-02-14) - never Sorento's own advertised
        `/contract` version, which is advisory only."""
        data = self.model_dump(mode="json")
        keys = list(self.SINK_FIELDS)
        if contract_version >= 2:
            keys = keys + list(self.FALLBACK_FIELDS)
        payload = {key: data[key] for key in keys if key in data}
        payload["lines"] = [
            line.sink_payload(contract_version=contract_version) for line in self.lines
        ]
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
    # addendum section 1 - code/name fallbacks (a customer login that only
    # exposes document tables) + back-create hints. v2-only.
    customer_code: Optional[str] = Field(None, max_length=50)
    customer_name: Optional[str] = None
    agent_code: Optional[str] = Field(None, max_length=100)
    lines: List[CanonicalSalesOrderLine] = Field(default_factory=list)

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref", "so_number", "customer_ref", "sales_agent_ref",
        "doc_date", "requested_delivery_date", "status", "internal_note",
    )
    FALLBACK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "customer_code", "customer_name", "agent_code",
    )


class CanonicalPurchaseOrder(CanonicalDocument):
    """AutoCount PO → Sorento ``purchase_orders`` (Appendix A6 §3/A8)."""

    entity_type: str = ENTITY_PURCHASE_ORDER

    po_number: Optional[str] = Field(None, max_length=100)
    supplier_ref: Optional[str] = Field(None, max_length=255)
    issue_date: Optional[date] = None
    expected_date: Optional[date] = None
    currency: Optional[str] = Field(None, max_length=3)
    supplier_code: Optional[str] = Field(None, max_length=50)
    supplier_name: Optional[str] = None
    agent_code: Optional[str] = Field(None, max_length=100)
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
    FALLBACK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "supplier_code", "supplier_name", "agent_code",
    )


class CanonicalShippingOrder(CanonicalDocument):
    """AutoCount SPO → Sorento ``shipping_orders`` (addendum section 3).

    A LINE-SET entity on Sorento's side (rows land in ``spo_allocations``,
    keyed ``(company_id, spo_number, spo_line_number)`` - no header table),
    reflected in the response contract only: push/read always returns header
    ``entity_id: null`` as a SUCCESS, never a failure (this ESB never branches
    on it). ``spo_number`` is the field Sorento adopts an xlsx-loaded row by,
    same DocKey-vs-DocNo split as SO/PO.
    """

    entity_type: str = ENTITY_SHIPPING_ORDER

    spo_number: Optional[str] = Field(None, max_length=50)
    supplier_ref: Optional[str] = Field(None, max_length=255)
    issue_date: Optional[date] = None
    expected_date: Optional[date] = None
    currency: Optional[str] = Field(None, max_length=3)
    supplier_code: Optional[str] = Field(None, max_length=50)
    supplier_name: Optional[str] = None
    agent_code: Optional[str] = Field(None, max_length=100)
    # feat/spo-container-number - AutoCount `PO.Ref`, sourced by the SPO
    # preset only (`presets.SPO_PRESET`). v2.1+ only, same fallback gate as
    # every other field below; a PO never carries this field at all
    # (`CanonicalPurchaseOrder` declares no such attribute).
    container_number: Optional[str] = Field(None, max_length=100)
    lines: List[CanonicalShippingOrderLine] = Field(default_factory=list)

    # No `internal_note` - same PO-shape rule above; Sorento's shipping-order
    # read/ingest schema carries no such field either.
    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref", "spo_number", "supplier_ref", "issue_date",
        "expected_date", "currency", "status",
    )
    FALLBACK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "supplier_code", "supplier_name", "agent_code", "container_number",
    )

    def sink_payload(self, *, contract_version: int = 1) -> Dict[str, Any]:
        """Same v2-gated shape as the base class, EXCEPT ``container_number``
        is dropped from the payload entirely when it is ``None`` (addendum
        section 11: absent means "leave Sorento's stored value alone", a
        ``null`` means "clear it" - a document whose ``Ref`` is unmapped or
        blank must never send the clear signal). Every other fallback field
        keeps the base class's "send the key even when null" behaviour
        unchanged."""
        payload = super().sink_payload(contract_version=contract_version)
        if payload.get("container_number") is None:
            payload.pop("container_number", None)
        return payload
