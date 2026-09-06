"""Field-mapping CATALOGS for the mapping editor (plan 15 §2, AC-15-40..43).

Two per-entity, code-side tables that the mapping editor reads:

* ``SORENTO_FIELDS`` - the Sorento fields an operator may target. This is the
  entity's canonical **sink** field set (``CanonicalSupplier/Customer.SINK_FIELDS``)
  MINUS ``source_ref``: ``source_ref`` is *identity*, minted by the profile's
  ``company_qualified_identity`` and never a mapping row (masters.py), so offering
  it as a mappable target would violate foolproof-UI (an option that cannot act).
  Each field carries a ``required`` flag - this is the set the guard admits
  (AC-15-42) and the picker offers, and nothing else.

* ``AC_SOURCE_FIELDS`` - the known AutoCount source paths for the entity, seeded
  from the entity's ``DEFAULT_MAPPINGS`` source paths plus the observed live
  top-level ``Creditor``/``Debtor`` keys and the ``Data.0.*`` nested keys
  (masters.py). Discoverability only: a free dotted path is still allowed on
  write (AC-15-43), so this is a starter list, not a whitelist.

    !!  REQUIRED SET - cited from SOURCE, not invented.  !!
Sorento's ``app/schemas/canonical_masters.py`` marks ``code`` and ``name`` as
required (``Field(...)`` with no default) on BOTH ``CanonicalSupplier`` and
``CanonicalCustomer``; ``is_active`` defaults to ``True`` there. We ADD
``is_active`` to the required set deliberately (masters.py): an unmapped active
flag falls through to the consumer's ``is_active: bool = True`` default and can
silently activate a blacklisted supplier or deactivate a live one - the exact
failure the module's default mapping makes ``is_required=True`` to prevent. So
"required" here = ``{code, name, is_active}`` ("code, name at least", plan §2).
``source_ref`` is required in Sorento too, but it is minted (see above) and is
therefore excluded from the mappable set entirely rather than shown as a
required-but-unmappable target.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .canonical.grn import ENTITY_GOODS_RECEIVED_NOTE
from .canonical.masters import (
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT,
    ENTITY_PRODUCT_CATEGORY,
    ENTITY_SALES_AGENT,
    ENTITY_SUPPLIER,
    ENTITY_UNIT_OF_MEASURE,
    ENTITY_WAREHOUSE,
    CanonicalCustomer,
    CanonicalProduct,
    CanonicalProductCategory,
    CanonicalSalesAgent,
    CanonicalSupplier,
    CanonicalUnitOfMeasure,
    CanonicalWarehouse,
)
from .canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    CanonicalPurchaseOrder,
    CanonicalPurchaseOrderLine,
    CanonicalSalesOrder,
    CanonicalSalesOrderLine,
    CanonicalShippingOrder,
    CanonicalShippingOrderLine,
)

# Identity is minted, never mapped (masters.py) - so it is not a mappable target.
_MINTED_FIELDS = ("source_ref",)

# From Sorento's canonical_masters.py (code, name) + masters.py (is_active).
_REQUIRED_MASTER_FIELDS = frozenset({"code", "name", "is_active"})

# Sorento's canonical_documents.py marks `so_number`/`po_number` and `status`
# required (plan 22 S5, Appendix A6 item 2/3) - the mapping editor's Sorento
# picker must say so for a document exactly like it already does for a master.
_REQUIRED_DOCUMENT_FIELDS: Dict[str, frozenset] = {
    ENTITY_SALES_ORDER: frozenset({"so_number", "status"}),
    ENTITY_PURCHASE_ORDER: frozenset({"po_number", "status"}),
    ENTITY_SHIPPING_ORDER: frozenset({"spo_number", "status"}),
}

# sprint-5/02 (addendum §1, AC-02-14) - the customer/supplier's CODE+NAME
# fallback fields, offered as mappable header targets alongside the ref
# fields so an operator can fill Sorento's back-create ladder even when the
# SQL login exposes only the document tables (no master task at all). Real
# `CanonicalSalesOrder`/`CanonicalPurchaseOrder`/`CanonicalShippingOrder`
# fields since slice S3 - `sink_payload(contract_version=)` gates whether
# they actually cross the wire (AC-02-27); this catalog only decides whether
# the mapping editor OFFERS the target.
_SO_FALLBACK_FIELDS: Tuple[str, ...] = ("customer_code", "customer_name", "agent_code")
_PO_FALLBACK_FIELDS: Tuple[str, ...] = ("supplier_code", "supplier_name", "agent_code")
_SPO_FALLBACK_FIELDS: Tuple[str, ...] = ("supplier_code", "supplier_name", "agent_code")

# The line-scope equivalent (addendum §1): a line's own product/warehouse
# code+name fallbacks + `line_number` (AutoCount `Seq`, addendum §9) - real
# `CanonicalDocumentLine` fields since S3, contract-version-2-gated at push.
_LINE_FALLBACK_FIELDS: Tuple[str, ...] = (
    "product_code", "product_name", "warehouse_code", "line_number",
)

# sprint-5/02 (AC-02-02/03) - a document's LINE fields are now first-class,
# operator-editable mapping rows (the fixed column-name convention is gone).
# `source_ref` is a mappable LINE target (unlike a header's, which is
# MINTED) - a line's bare key column IS what the operator maps.
_REQUIRED_LINE_FIELDS: Dict[str, frozenset] = {
    ENTITY_SALES_ORDER: frozenset({"source_ref", "product_ref", "qty_ordered"}),
    ENTITY_PURCHASE_ORDER: frozenset({"source_ref", "product_ref", "qty_ordered"}),
    ENTITY_SHIPPING_ORDER: frozenset({"source_ref", "product_ref", "qty_ordered"}),
}


@dataclass(frozen=True)
class SorentoFieldDef:
    """One accepted Sorento target: its canonical/Sorento name + required-ness.

    For masters/documents the canonical field name IS the Sorento-facing name,
    so this single value serves both the wire label and the storage key.
    """

    field: str
    required: bool


def _accepted(
    sink_fields: Tuple[str, ...], required: frozenset = _REQUIRED_MASTER_FIELDS
) -> Tuple[SorentoFieldDef, ...]:
    return tuple(
        SorentoFieldDef(field=name, required=name in required)
        for name in sink_fields
        if name not in _MINTED_FIELDS
    )


def _accepted_line(
    sink_fields: Tuple[str, ...], required: frozenset
) -> Tuple[SorentoFieldDef, ...]:
    """Like ``_accepted``, but WITHOUT the ``_MINTED_FIELDS`` filter - a
    line's ``source_ref`` (the bare DtlKey-equivalent) is a real, operator-
    mapped target (sprint-5/02, AC-02-02), unlike a header's, which is minted
    from identity and therefore excluded."""
    return tuple(
        SorentoFieldDef(field=name, required=name in required) for name in sink_fields
    )


# ── Sorento accepted-field catalogs (AC-15-42) ────────────────────────────────
SORENTO_FIELDS: Dict[str, Tuple[SorentoFieldDef, ...]] = {
    ENTITY_SUPPLIER: _accepted(CanonicalSupplier.SINK_FIELDS),
    ENTITY_CUSTOMER: _accepted(CanonicalCustomer.SINK_FIELDS),
    # GRN is a document (lines nested), not a master sink - it has no accepted
    # master-field set, so the mapping editor's Sorento picker is empty for it.
    ENTITY_GOODS_RECEIVED_NOTE: (),
    # Plan 22 S4 masters fan-out (AC-22-23) - without an entry here the PUT
    # mapping guard's `accepted_field_names` is empty and EVERY row a database
    # task's Mapping tab tries to save 422s "not a Sorento field accepted for
    # <entity>" (the accepted set is entity-agnostic code, DB-source or not).
    ENTITY_PRODUCT_CATEGORY: _accepted(CanonicalProductCategory.SINK_FIELDS),
    ENTITY_UNIT_OF_MEASURE: _accepted(CanonicalUnitOfMeasure.SINK_FIELDS),
    ENTITY_WAREHOUSE: _accepted(CanonicalWarehouse.SINK_FIELDS),
    ENTITY_PRODUCT: _accepted(CanonicalProduct.SINK_FIELDS),
    ENTITY_SALES_AGENT: _accepted(CanonicalSalesAgent.SINK_FIELDS),
    # Plan 22 S5 (AC-22-24) - HEADER fields. sprint-5/02 (AC-02-02) adds the
    # LINE catalog below (``SORENTO_LINE_FIELDS``) - a document's lines are
    # now first-class operator-editable rows, not a fixed column-name
    # convention. The fallback code/name fields (addendum §1, AC-02-14) are
    # appended here too.
    ENTITY_SALES_ORDER: _accepted(
        CanonicalSalesOrder.SINK_FIELDS + _SO_FALLBACK_FIELDS,
        _REQUIRED_DOCUMENT_FIELDS[ENTITY_SALES_ORDER],
    ),
    ENTITY_PURCHASE_ORDER: _accepted(
        CanonicalPurchaseOrder.SINK_FIELDS + _PO_FALLBACK_FIELDS,
        _REQUIRED_DOCUMENT_FIELDS[ENTITY_PURCHASE_ORDER],
    ),
    ENTITY_SHIPPING_ORDER: _accepted(
        CanonicalShippingOrder.SINK_FIELDS + _SPO_FALLBACK_FIELDS,
        _REQUIRED_DOCUMENT_FIELDS[ENTITY_SHIPPING_ORDER],
    ),
}

# ── LINE catalog (sprint-5/02, AC-02-02/03) ───────────────────────────────────
# A document's line fields, mirroring ``SORENTO_FIELDS`` above but for
# ``scope='line'`` rows. ``source_ref``/``product_ref``/``qty_ordered`` are
# required the moment ANY line row is saved (addendum §3's fixed line shape).
SORENTO_LINE_FIELDS: Dict[str, Tuple[SorentoFieldDef, ...]] = {
    ENTITY_SALES_ORDER: _accepted_line(
        CanonicalSalesOrderLine.SINK_FIELDS + _LINE_FALLBACK_FIELDS,
        _REQUIRED_LINE_FIELDS[ENTITY_SALES_ORDER],
    ),
    ENTITY_PURCHASE_ORDER: _accepted_line(
        CanonicalPurchaseOrderLine.SINK_FIELDS + _LINE_FALLBACK_FIELDS,
        _REQUIRED_LINE_FIELDS[ENTITY_PURCHASE_ORDER],
    ),
    ENTITY_SHIPPING_ORDER: _accepted_line(
        CanonicalShippingOrderLine.SINK_FIELDS + _LINE_FALLBACK_FIELDS,
        _REQUIRED_LINE_FIELDS[ENTITY_SHIPPING_ORDER],
    ),
}


# ── AutoCount source-field catalogs (AC-15-43) ────────────────────────────────
# Masters are flat but nest the real DB row under ``Data[0]`` (masters.py), so
# both levels are addressable. This is a discoverability starter list - a free
# dotted path is still accepted on write.
_MASTER_COMMON_SOURCES: Tuple[str, ...] = (
    "AccNo",
    "CompanyName",
    "EmailAddress",
    "IsActive",
    "RegisterNo",
    "TaxRegistrationNo",
    "Data.0.AutoKey",
    "Data.0.LastModified",
    "Data.0.Guid",
)

AC_SOURCE_FIELDS: Dict[str, Tuple[str, ...]] = {
    ENTITY_SUPPLIER: _MASTER_COMMON_SOURCES,
    ENTITY_CUSTOMER: _MASTER_COMMON_SOURCES + ("Mobile", "TIN"),
}


def accepted_fields(entity_type: str) -> Tuple[SorentoFieldDef, ...]:
    """The Sorento fields an operator may target for ``entity_type`` (may be
    empty for a non-master entity)."""
    return SORENTO_FIELDS.get(entity_type, ())


def accepted_field_names(entity_type: str) -> frozenset:
    """The accepted-field NAME set - what the PUT guard admits (AC-15-42)."""
    return frozenset(defn.field for defn in accepted_fields(entity_type))


def required_field_names(entity_type: str) -> frozenset:
    return frozenset(
        defn.field for defn in accepted_fields(entity_type) if defn.required
    )


def line_accepted_fields(entity_type: str) -> Tuple[SorentoFieldDef, ...]:
    """The Sorento LINE fields an operator may target (sprint-5/02, AC-02-02) -
    empty for a non-document entity (master/GRN have no line scope at all)."""
    return SORENTO_LINE_FIELDS.get(entity_type, ())


def line_accepted_field_names(entity_type: str) -> frozenset:
    return frozenset(defn.field for defn in line_accepted_fields(entity_type))


def line_required_field_names(entity_type: str) -> frozenset:
    return frozenset(
        defn.field for defn in line_accepted_fields(entity_type) if defn.required
    )


def ac_source_fields(entity_type: str) -> Tuple[str, ...]:
    """Known AutoCount source paths for ``entity_type`` - a discovery aid; a free
    dotted path is still allowed on write (AC-15-43)."""
    # Fall back to the entity's default-mapping source paths so a GRN (or any
    # entity absent from the master catalog) still offers its real source fields.
    if entity_type in AC_SOURCE_FIELDS:
        return AC_SOURCE_FIELDS[entity_type]
    from .mapping import DEFAULT_MAPPINGS

    seen: List[str] = []
    for row in DEFAULT_MAPPINGS.get(entity_type, ()):  # type: ignore[union-attr]
        if row.source_path not in seen:
            seen.append(row.source_path)
    return tuple(seen)


def sorento_field_for(
    entity_type: str, canonical_field: str, scope: str = "header"
) -> Optional[str]:
    """The Sorento-facing name for a stored ``canonical_field``, or ``None`` when
    the field is not delivered to Sorento (identity/provenance like
    ``last_modified``, or an ``extras`` key) - projected as non-delivered
    (plan §2).

    ``scope`` (sprint-5/02 S2 bugfix, caught in S3 live-verify) - a LINE row's
    canonical field (``source_ref``/``product_ref``/...) never appears in the
    HEADER accepted-field set, so a scope-blind lookup always returned
    ``None`` for every line mapping and the Mapping tab's "Line fields" table
    showed "No deliverable fields mapped yet" even when properly configured.
    Checks the matching scope's accepted-field set instead."""
    names = line_accepted_field_names(entity_type) if scope == "line" else accepted_field_names(
        entity_type
    )
    return canonical_field if canonical_field in names else None
