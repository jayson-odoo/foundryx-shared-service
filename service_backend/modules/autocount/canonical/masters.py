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


MASTER_ENTITIES: List[str] = [ENTITY_SUPPLIER, ENTITY_CUSTOMER]
