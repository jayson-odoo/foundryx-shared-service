"""Canonical master shapes - Supplier (Creditor) and Customer (Debtor).

    !!  THESE ARE A STRICT SUBSET OF SORENTO'S OWN SCHEMAS, READ FROM SOURCE.  !!
    !!  `app/schemas/canonical_masters.py` sets ``extra="forbid"``, so a field  !!
    !!  we invent is a hard PER-RECORD REJECTION - not a warning, not a drop.   !!

Two rules decided which fields exist here, and both are the opposite of the
obvious "map everything" instinct:

1. **Payment terms are absent on purpose** (AC-14-12). AutoCount supplies
   ``DisplayTerm`` as a CODE (``"C.O.D."``), not a number of days, and Sorento's
   ``_supplier_columns`` raises ``MissingReference`` on ``payment_terms_code``
   **unconditionally** - it performs no lookup at all until their Phase D. Any
   value we sent would make the record permanently ``retryable`` and build an
   undrainable queue. So no field, and no code→days mapping invented anywhere.

2. **Supplier address fields are absent on purpose** (AC-14-13). Sorento's
   ``CanonicalSupplier`` *accepts* ``contact_name``/``address_line1``/``city``/…
   but ``_supplier_columns`` writes none of them. Sending them would have us
   report an operator that seven address fields synced when Sorento silently
   discarded all seven. That is the exact failure Sorento's canonical layer says
   it exists to prevent ("a field the ESB believed it sent and Sorento silently
   dropped is the worst kind of mapping bug") - we must not re-create it from
   the other side by reporting success.

``source_ref`` is **company-qualified** (AC-14-10): ``"{DatabaseName}:{AutoKey}"``.
``AutoKey`` is a per-company primary key, so ``AutoKey=1`` exists in EVERY
AutoCount company, while Sorento's uniqueness is
``(source_system, entity_type, source_ref)`` with **no company dimension**. An
unqualified ref therefore collides the moment a tenant connects a second company.
It is minted in the canonical shape (``mapping.company_qualified_identity``), not
at push time, so staging, the diff and the eventual push all key on one string.

Not ``Guid`` (Debtor rows carry one, Creditor rows do not) and not ``AccNo``
(a business code an operator can renumber - correlating on it would orphan the
Sorento row and duplicate the record on the next sync).
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from pydantic import Field

from .base import CanonicalRecord

ENTITY_SUPPLIER = "supplier"
ENTITY_CUSTOMER = "customer"

# Plan 22 S4 (AC-22-23) - masters fan-out. Every one of these is DB-source
# ONLY (no confirmed AutoCount API payload backs them, unlike GRN/supplier/
# customer - see ``services/company_service.py``'s ``SEEDED_ENTITIES`` guard),
# and all five live in THIS leaf module for the same reason ``ENTITY_SALES_AGENT``
# already did: it is the one place BOTH ``mapping.py`` (``ENTITY_PROFILES``,
# ``UNQUALIFIED_REF_ENTITIES``) and ``services/etl_service.py`` (the entity
# catalogue) import from without a cycle - ``mapping.py`` ->
# ``services/etl_service.py`` would cycle back through
# ``services/company_service.py`` -> ``mapping.py``.
ENTITY_PRODUCT_CATEGORY = "product_category"
ENTITY_UNIT_OF_MEASURE = "unit_of_measure"
ENTITY_WAREHOUSE = "warehouse"
ENTITY_PRODUCT = "product"
# Sales agent DID start as a plain flat DB-extract entity with no canonical
# dataclass (S2/S3); S4 gives it one (``CanonicalSalesAgent`` below) now that
# it actually pushes to Sorento (Appendix A6 §6/A8).
ENTITY_SALES_AGENT = "sales_agent"

# The vendor entity names in the URL grammar: POST /api/{Entity}/Get{Entity}.
VENDOR_ENTITY_SUPPLIER = "Creditor"
VENDOR_ENTITY_CUSTOMER = "Debtor"

# Where the real DB row hides. A master response nests it one level down, so a
# mapping row's path is ``Data.0.AutoKey`` - NOT ``AutoKey``.
#
# Deliberately NOT flattened into the parent: BOTH levels carry unique fields
# (top: ``EmailAddress``/``RegisterNo``/``TaxRegistrationNo``/``UDF``;
# ``Data[0]``: ``AutoKey``/``LastModified``/``Guid``) AND overlapping ones
# (``AccNo``/``CompanyName``/``IsActive``/``CreditLimit``). Flattening would need
# an invisible precedence rule for the overlaps; explicit paths keep the source
# visible to the operator, which is the entire point of data-driven mapping.
VENDOR_DATA_KEY = "Data"
VENDOR_AUTOKEY_PATH = "Data.0.AutoKey"
VENDOR_LAST_MODIFIED_PATH = "Data.0.LastModified"


class CanonicalMaster(CanonicalRecord):
    """Shared master provenance.

    ``last_modified`` is carried for staging, diffing and the watermark - it is
    NOT a Sorento field and is excluded from ``sink_payload`` below.
    """

    source_doc_no: Optional[str] = None
    code: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None

    last_modified: Optional[datetime] = None
    extras: Dict[str, Any] = Field(default_factory=dict)

    #     !!  THE ONLY KEYS THAT MAY CROSS THE WIRE TO SORENTO.  !!
    # Their models forbid extras, so an unknown key is a per-record rejection
    # costing a round-trip to discover (AC-14-14). Keeping the allow-list beside
    # the model - rather than in the sink - means a field added here without a
    # deliberate decision about the consumer cannot silently reach it.
    SINK_FIELDS: ClassVar[Tuple[str, ...]] = ()

    def sink_payload(self) -> Dict[str, Any]:
        """Exactly the keys Sorento defines - provenance and locally-useful
        fields (``source_system``, ``entity_type``, ``last_modified``,
        ``extras``) stripped."""
        data = self.model_dump(mode="json")
        return {key: data[key] for key in self.SINK_FIELDS if key in data}


class CanonicalSupplier(CanonicalMaster):
    """AutoCount ``Creditor`` → Sorento ``suppliers``.

    A synced supplier carries **code, name, email and the active flag only** -
    that is the honest list, and it is what an operator must be shown (AC-14-13).
    Creditor has no phone field at all, so ``phone_number`` (which Sorento *does*
    persist) has no source and is omitted rather than faked.
    """

    entity_type: str = ENTITY_SUPPLIER

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref",
        "source_doc_no",
        "code",
        "name",
        "email",
        "is_active",
    )


class CanonicalCustomer(CanonicalMaster):
    """AutoCount ``Debtor`` → Sorento ``customers``.

    No ``country`` source exists on Debtor, and ``registration_number`` exists on
    Creditor but not Debtor - both omitted rather than invented.
    """

    entity_type: str = ENTITY_CUSTOMER

    phone_number: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    tax_id: Optional[str] = None

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref",
        "source_doc_no",
        "code",
        "name",
        "email",
        "phone_number",
        "credit_limit",
        "tax_id",
        "is_active",
    )


class CanonicalProductCategory(CanonicalMaster):
    """AutoCount stock category → Sorento ``product_categories`` (Appendix A6).

    Products cannot be created without a category (``products.category_id`` is
    NOT NULL on the consumer), so this must land before products or every
    product reports ``retryable`` forever (AC-22-23's dependency order).
    """

    entity_type: str = ENTITY_PRODUCT_CATEGORY

    description: Optional[str] = None

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref",
        "source_doc_no",
        "code",
        "name",
        "description",
        "is_active",
    )


class CanonicalUnitOfMeasure(CanonicalMaster):
    """AutoCount UOM → Sorento ``units_of_measure``. Likewise a product
    dependency (``products.base_uom_id`` is NOT NULL)."""

    entity_type: str = ENTITY_UNIT_OF_MEASURE

    description: Optional[str] = None
    # Canonical divisibility, 0..4 (Sorento's own default is 0 - an upstream
    # master that never expressed precision counts in whole units).
    decimal_places: int = 0

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref",
        "source_doc_no",
        "code",
        "name",
        "decimal_places",
        "description",
        "is_active",
    )


class CanonicalWarehouse(CanonicalMaster):
    """AutoCount location/warehouse → Sorento ``warehouses``."""

    entity_type: str = ENTITY_WAREHOUSE

    location: Optional[str] = None

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref",
        "source_doc_no",
        "code",
        "name",
        "location",
        "is_active",
    )


class CanonicalProduct(CanonicalMaster):
    """AutoCount stock item → Sorento ``products`` (Appendix A6).

    ``category_code``/``uom_code`` are Sorento's OWN ``product_categories.
    category_code``/``units_of_measure.uom_code`` - resolved by CODE, never by
    ESB integration ref (unlike a document line's ``product_ref``/
    ``warehouse_ref``, which resolve by the pushed ``source_ref``). An
    unresolvable code is a per-record ``retryable`` on Sorento's side, not a
    422 here - the category/UOM may simply not have synced yet (AC-22-23), and
    it drains automatically once it does.
    """

    entity_type: str = ENTITY_PRODUCT

    description: Optional[str] = None
    category_code: Optional[str] = None
    uom_code: Optional[str] = None
    brand_code: Optional[str] = None
    list_price: Optional[Decimal] = None
    cost_price: Optional[Decimal] = None

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref",
        "source_doc_no",
        "code",
        "name",
        "description",
        "category_code",
        "uom_code",
        "brand_code",
        "list_price",
        "cost_price",
        "is_active",
    )


class CanonicalSalesAgent(CanonicalMaster):
    """AutoCount sales agent → Sorento ``sales_agents`` (Appendix A6 §6/A8).

    The only SHARED master (Sorento's row carries no ``company_id``): every
    company's task resolves to the ONE row, via the unqualified
    ``agent:{CODE}`` ref (``mapping.UNQUALIFIED_REF_ENTITIES``,
    ``flat_source_ref``) - minted upper-cased and trimmed there, matching how
    ``sales_agent_service`` stores and matches the code on Sorento's side.

    No ``email``/``credit_limit``/``phone_number`` - Sorento's own
    ``CanonicalSalesAgent`` carries none of those; only ``code``/
    ``description``/``is_active``/``person_label``. ``name`` is inherited from
    ``CanonicalMaster`` but is never sent (absent from ``SINK_FIELDS``) - the
    agent has no name field on Sorento's side, only ``person_label``.

    **A shared row is never deleted by one company's reconcile (plan 22 S4
    review B2, Appendix A6 item 6).** Because the ref carries no company
    qualifier, a company's extract missing a ref is not proof the agent is
    gone globally - a sibling company may still use it. ``sync._stage_deletes``
    therefore stages NO delete intent at all for this entity: it only drops
    the reporting company's own ``ac_row_hash`` row for the missing ref (so a
    later re-appearance stages as a fresh add, never a phantom update). An
    agent that is genuinely retired must be removed in Sorento directly, out
    of band - there is deliberately no path from a company's reconcile to a
    shared agent's deletion.
    """

    entity_type: str = ENTITY_SALES_AGENT

    description: Optional[str] = None
    person_label: Optional[str] = None

    SINK_FIELDS: ClassVar[Tuple[str, ...]] = (
        "source_ref",
        "source_doc_no",
        "code",
        "description",
        "is_active",
        "person_label",
    )


MASTER_ENTITIES: List[str] = [
    ENTITY_SUPPLIER,
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT_CATEGORY,
    ENTITY_UNIT_OF_MEASURE,
    ENTITY_WAREHOUSE,
    ENTITY_PRODUCT,
    ENTITY_SALES_AGENT,
]
