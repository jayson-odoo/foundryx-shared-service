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

from datetime import date, datetime
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

# AC-CANCEL-PULL - four LINKED documents (contract 2.8): each line points
# back at the document it cancels/returns via FromDocType + FromDocNo
# (+ FromDocDtlKey, empty since ~Oct-Nov 2024). Same fetch/mapping path as
# SO/PO/SPO; their own canonical shape (`CanonicalLinkedDocument` below).
ENTITY_CANCEL_SALES_ORDER = "cancel_sales_order"
ENTITY_CANCEL_PURCHASE_ORDER = "cancel_purchase_order"
ENTITY_CONSIGNMENT = "consignment"
ENTITY_CONSIGNMENT_RETURN = "consignment_return"

LINKED_DOCUMENT_ENTITY_TYPES: Tuple[str, ...] = (
    ENTITY_CANCEL_SALES_ORDER, ENTITY_CANCEL_PURCHASE_ORDER,
    ENTITY_CONSIGNMENT, ENTITY_CONSIGNMENT_RETURN,
)

# The order family (SO/PO/SPO) - kept named on its own: the PO/SPO
# filter-formula split is the only reason one document can be seen by two
# sibling tasks, so the overlap warning compares within this family only.
ORDER_DOCUMENT_ENTITY_TYPES: Tuple[str, ...] = (
    ENTITY_SALES_ORDER, ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER,
)

DOCUMENT_ENTITY_TYPES: Tuple[str, ...] = (
    ORDER_DOCUMENT_ENTITY_TYPES + LINKED_DOCUMENT_ENTITY_TYPES
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
        # CONSTRAINT (review round, sprint-5/07): `not payload.get(name)`
        # treats `0`/`False`/`[]` as empty too, which is exactly right for a
        # string/ref field (never send a blank as the value, only omit it)
        # but WRONG for a numeric/boolean field genuinely valued at zero or
        # false - never name one of those here.
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
    # sprint-5/07 (AC-07-02) - the HEADER-level twin of
    # `CanonicalDocumentLine.OMIT_WHEN_EMPTY_FIELDS` (sprint-5/06): a fallback
    # field named here is DROPPED from the payload (never sent as an explicit
    # `null`) when its value is empty. Absent means "leave Sorento's stored
    # value alone"; `null` means "clear it" - generalises the `container_number`
    # rule that used to be a one-off `sink_payload` override on
    # `CanonicalShippingOrder`. Empty on the shared base; SO/SPO populate it.
    OMIT_WHEN_EMPTY_FIELDS: ClassVar[Tuple[str, ...]] = ()
    # SS-SO-TRANSFERABLE - the boolean-safe sibling of the list above: a
    # field named here is dropped from the payload ONLY when it is `None`, so
    # a genuine `False` (or `0`) still reaches the wire. Use this, never
    # `OMIT_WHEN_EMPTY_FIELDS`, for a boolean/numeric field.
    OMIT_WHEN_NONE_FIELDS: ClassVar[Tuple[str, ...]] = ()

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
        # CONSTRAINT (review round, sprint-5/07): `not payload.get(name)`
        # treats `0`/`False`/`[]` as empty too, which is exactly right for a
        # string/ref field (never send a blank as the value, only omit it)
        # but WRONG for a numeric/boolean field genuinely valued at zero or
        # false - never name one of those here.
        for name in self.OMIT_WHEN_EMPTY_FIELDS:
            if not payload.get(name):
                payload.pop(name, None)
        for name in self.OMIT_WHEN_NONE_FIELDS:
            if payload.get(name) is None:
                payload.pop(name, None)
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
    # sprint-5/07 (AC-07-02) - AutoCount `SO.Ref`, sent VERBATIM (no cleaning
    # on the ESB side - Sorento's `label_from_ref` owns stripping the sales-
    # staff agent stamps to derive `project_label`). SO only: PO/SPO never
    # carry this field at all (`CanonicalPurchaseOrder`/`CanonicalShippingOrder`
    # declare no such attribute). v2+ only, same fallback gate as every other
    # field below; never sent as an explicit `null` (`OMIT_WHEN_EMPTY_FIELDS`).
    ref: Optional[str] = Field(None, max_length=255)
    # SS-SO-TRANSFERABLE (partner of sorento #1421) - AutoCount
    # `SO.Transferable` ('T'/'F' through the `bool` transform). SO only; v2+
    # only like `ref`; omitted when `None` (never an explicit `null`), but a
    # real `False` IS sent (`OMIT_WHEN_NONE_FIELDS`, not the EMPTY list).
    transferable: Optional[bool] = None
    # SS-PO-REF (partner of sorento #1528) - the customer's own PO number,
    # AutoCount `UDFNote` by default. Its own field: `ref` keeps feeding
    # Sorento's Project label. SO only; v2+ only like `ref`; max 255 matches
    # Sorento's `CanonicalSalesOrder.po_ref`; never sent blank
    # (`OMIT_WHEN_EMPTY_FIELDS`).
    po_ref: Optional[str] = Field(None, max_length=255)
    lines: List[CanonicalSalesOrderLine] = Field(default_factory=list)

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref", "so_number", "customer_ref", "sales_agent_ref",
        "doc_date", "requested_delivery_date", "status", "internal_note",
    )
    FALLBACK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "customer_code", "customer_name", "agent_code", "ref", "transferable",
        "po_ref",
    )
    OMIT_WHEN_EMPTY_FIELDS: ClassVar[Tuple[str, ...]] = ("ref", "po_ref")
    OMIT_WHEN_NONE_FIELDS: ClassVar[Tuple[str, ...]] = ("transferable",)


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
    # sprint-5/07 - generalised onto the base class's own
    # `OMIT_WHEN_EMPTY_FIELDS` mechanism (previously a one-off `sink_payload`
    # override here): addendum section 11, absent means "leave Sorento's
    # stored value alone", `null` means "clear it" - a document whose `Ref`
    # is unmapped or blank must never send the clear signal.
    OMIT_WHEN_EMPTY_FIELDS: ClassVar[Tuple[str, ...]] = ("container_number",)


# ── AC-CANCEL-PULL - linked documents (contract 2.8) ──────────────────────────
#
#     !!  THE WIRE IS THE DO/GRN DOC-FEED SHAPE, NOT A CANONICAL ONE.  !!
# CRM #1623 ingests these four through the SAME door shape as the
# delivery-order / goods-receive-note feeds (`autocount-doc-feeds.md`
# section 1/3, contract 13): body `{companyCode, book, records}`, each record
# the AutoCount HEADER row with its own PascalCase column names and its lines
# under `Details`, deletions by `doc_keys`. The CRM derives `source_ref` as
# `{book}:{CODE}:{DocKey}` and answers verdicts under it, so that is this
# record's `source_ref` too (`linked_document_ref`).
#
# The typed fields below (`doc_no`, `status`, `customer_code`, lines'
# `product_code`/`qty`, ...) are the MAPPING layer only: the Mapping tab, the
# required-field gate and the mapping errors run on them exactly as for
# SO/PO. They never reach the wire. The wire is `source_record` - the row
# `SqlDbSource` fetched (header columns + the `_lines` it nested), filled by
# the mapping engine (`EntityProfile.raw_record_field`), never a mapping
# target - minus the ESB-internal join/fingerprint columns below.

# The CRM's doc-type code per entity: the second segment of the derived
# `source_ref`, verbatim from CRM #1623 (`autocount_cancel_ingest_service.py`
# `_PREFIX`, confirmed by the crew at CRM head 431a030d): `XS`/`XP` are
# AutoCount's own codes, consignments are `CSGN` and consignment returns
# `CSGR` - NOT the `CG`/`CR` AutoCount itself uses in `FromDocType`/
# `ToDocType`. A wrong code here makes every verdict miss its staged row and
# quarantines every delete as wrong-book; `test_the_ref_codes_match_the_crm`
# pins all four.
LINKED_DOCUMENT_REF_CODES: Dict[str, str] = {
    ENTITY_CANCEL_SALES_ORDER: "XS",
    ENTITY_CANCEL_PURCHASE_ORDER: "XP",
    ENTITY_CONSIGNMENT: "CSGN",
    ENTITY_CONSIGNMENT_RETURN: "CSGR",
}

# Columns the presets select for the ESB's own use (master-ref joins and the
# change-detection fingerprint), never AutoCount table columns - stripped from
# the wire so the CRM only ever sees the vendor's own fields.
LINKED_HEADER_INTERNAL_COLUMNS = frozenset({
    "DebtorAutoKey", "CreditorAutoKey", "LineCount", "QtySum", "SubTotalSum",
    "MaxDtlKey", "LinkedLineCount", "FromDocKeySum",
})
LINKED_LINE_INTERNAL_COLUMNS = frozenset({"ItemAutoKey", "LocationAutoKey"})

# The cap on any one free-text cell of a linked document on the wire.
NOTE_MAX_CHARS = 4000

# The vendor feed's own datetime format (naive MYT, millisecond precision -
# e.g. `2026-09-28T10:00:00.000`); AutoCount stores local time, so a SQL
# `datetime` is already MYT and is only formatted, never shifted.
_VENDOR_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def linked_document_ref(entity_type: str, book: str, doc_key: Any) -> str:
    """``{book}:{CODE}:{DocKey}`` - the CRM's own derivation, verbatim."""
    return f"{book}:{LINKED_DOCUMENT_REF_CODES[entity_type]}:{doc_key}"


def vendor_json_value(value: Any) -> Any:
    """One SQL value as the vendor feed would send it: a ``Decimal`` as a JSON
    number (``int`` when integral, else ``float``), a ``datetime`` as the
    naive vendor string, a ``date`` as its midnight, bytes/GUIDs as text.
    Recursive over lists/dicts. Applied BEFORE the record is stored, so the
    staged ``canonical_json`` already holds the wire values."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).strftime(_VENDOR_DATETIME_FORMAT)[:-3]
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day).strftime(
            _VENDOR_DATETIME_FORMAT
        )[:-3]
    if isinstance(value, str):
        # Security review: one bound for EVERY free-text cell (Note,
        # Description, FurtherDescription, ...), never a size an ingest batch
        # cannot carry. Cut, never rejected.
        return value[:NOTE_MAX_CHARS] if len(value) > NOTE_MAX_CHARS else value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [vendor_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): vendor_json_value(v) for k, v in value.items()}
    # Bytes / GUIDs / times: the SAME rendering the SQL preview uses.
    from ..sql_source.preview import json_safe

    return json_safe(value)


class CanonicalLinkedDocumentLine(CanonicalDocumentLine):
    """The MAPPING-layer line of a cancel / consignment document (validation
    only - see the section comment). ``product_code`` + ``qty`` are required
    by the catalogue because the CRM matches a line to its source document by
    ``FromDocNo`` + item + location + qty (``FromDocDtlKey`` is often empty)."""

    qty: Optional[Decimal] = Field(None, ge=0)
    unit_price: Optional[Decimal] = None
    from_doc_type: Optional[str] = Field(None, max_length=20)
    # `FromDocNo` is nvarchar(max) on XSDTL/XPDTL/ConsignmentReturnDTL.
    from_doc_no: Optional[str] = Field(None, max_length=255)
    from_doc_line_key: Optional[int] = None

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref", "line_number", "product_ref", "product_code", "product_name",
        "warehouse_ref", "warehouse_code", "qty", "uom", "unit_price", "line_total",
        "from_doc_type", "from_doc_no", "from_doc_line_key",
    )
    FALLBACK_FIELDS: ClassVar[Tuple[str, ...]] = ()


class CanonicalLinkedDocument(CanonicalDocument):
    """Shared header of the four linked documents. ``sink_payload`` is the
    raw vendor-shaped record (see the section comment)."""

    doc_no: Optional[str] = Field(None, max_length=100)
    doc_date: Optional[date] = None
    agent_code: Optional[str] = Field(None, max_length=100)
    ref: Optional[str] = Field(None, max_length=255)
    note: Optional[str] = None
    lines: List[CanonicalLinkedDocumentLine] = Field(default_factory=list)
    source_record: Dict[str, Any] = Field(default_factory=dict)

    _COMMON_HEAD: ClassVar[Tuple[str, ...]] = ("source_ref", "doc_no", "doc_date", "status")
    _COMMON_TAIL: ClassVar[Tuple[str, ...]] = ("agent_code", "ref", "note")

    @field_validator("source_record", mode="before")
    @classmethod
    def _vendor_values(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        record = vendor_json_value(value)
        # Security review: AutoCount `Note` is nvarchar(max), often RTF with
        # embedded images - CUT (never rejected) so one huge note can never
        # bloat a staged row or sink a whole ingest batch.
        note = record.get("Note")
        if isinstance(note, str) and len(note) > NOTE_MAX_CHARS:
            record["Note"] = note[:NOTE_MAX_CHARS]
        return record

    def sink_payload(self, *, contract_version: int = 1) -> Dict[str, Any]:
        """The vendor record: header columns verbatim (minus the ESB-internal
        ones) and its lines under ``Details``. ``Details`` is always present
        (``[]`` for a header with no lines) - it is structure, not data."""
        raw = dict(self.source_record or {})
        lines = raw.pop(SQL_DOC_LINES_KEY, None) or []
        payload = {
            key: value for key, value in raw.items()
            if key not in LINKED_HEADER_INTERNAL_COLUMNS and not key.startswith("_")
        }
        payload["Details"] = [
            {key: value for key, value in line.items() if key not in LINKED_LINE_INTERNAL_COLUMNS}
            for line in lines if isinstance(line, dict)
        ]
        return payload


_CUSTOMER_FIELDS: Tuple[str, ...] = ("customer_ref", "customer_code", "customer_name")
_SUPPLIER_FIELDS: Tuple[str, ...] = ("supplier_ref", "supplier_code", "supplier_name")


class _CustomerSideDocument(CanonicalLinkedDocument):
    customer_ref: Optional[str] = Field(None, max_length=255)
    customer_code: Optional[str] = Field(None, max_length=50)
    customer_name: Optional[str] = None

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        CanonicalLinkedDocument._COMMON_HEAD + _CUSTOMER_FIELDS
        + CanonicalLinkedDocument._COMMON_TAIL
    )


class CanonicalCancelSalesOrder(_CustomerSideDocument):
    """AutoCount ``XS``/``XSDTL`` -> CRM ``cancel_sales_orders``."""

    entity_type: str = ENTITY_CANCEL_SALES_ORDER


class CanonicalConsignment(_CustomerSideDocument):
    """AutoCount ``Consignment``/``ConsignmentDTL`` (CG- numbers, entered by
    hand - no source document) -> CRM ``consignments``."""

    entity_type: str = ENTITY_CONSIGNMENT


class CanonicalConsignmentReturn(_CustomerSideDocument):
    """AutoCount ``ConsignmentReturn``/``ConsignmentReturnDTL`` (lines carry
    ``FromDocType 'CG'``) -> CRM ``consignment_returns``."""

    entity_type: str = ENTITY_CONSIGNMENT_RETURN


class CanonicalCancelPurchaseOrder(CanonicalLinkedDocument):
    """AutoCount ``XP``/``XPDTL`` -> CRM ``cancel_purchase_orders``."""

    entity_type: str = ENTITY_CANCEL_PURCHASE_ORDER

    supplier_ref: Optional[str] = Field(None, max_length=255)
    supplier_code: Optional[str] = Field(None, max_length=50)
    supplier_name: Optional[str] = None

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        CanonicalLinkedDocument._COMMON_HEAD + _SUPPLIER_FIELDS
        + CanonicalLinkedDocument._COMMON_TAIL
    )


LINKED_DOCUMENT_MODELS: Dict[str, type] = {
    ENTITY_CANCEL_SALES_ORDER: CanonicalCancelSalesOrder,
    ENTITY_CANCEL_PURCHASE_ORDER: CanonicalCancelPurchaseOrder,
    ENTITY_CONSIGNMENT: CanonicalConsignment,
    ENTITY_CONSIGNMENT_RETURN: CanonicalConsignmentReturn,
}
