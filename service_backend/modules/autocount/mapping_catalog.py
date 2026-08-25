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
    ENTITY_SUPPLIER,
    CanonicalCustomer,
    CanonicalSupplier,
)

# Identity is minted, never mapped (masters.py) - so it is not a mappable target.
_MINTED_FIELDS = ("source_ref",)

# From Sorento's canonical_masters.py (code, name) + masters.py (is_active).
_REQUIRED_MASTER_FIELDS = frozenset({"code", "name", "is_active"})


@dataclass(frozen=True)
class SorentoFieldDef:
    """One accepted Sorento target: its canonical/Sorento name + required-ness.

    For masters the canonical field name IS the Sorento-facing name (masters.py),
    so this single value serves both the wire label and the storage key.
    """

    field: str
    required: bool


def _accepted(sink_fields: Tuple[str, ...]) -> Tuple[SorentoFieldDef, ...]:
    return tuple(
        SorentoFieldDef(field=name, required=name in _REQUIRED_MASTER_FIELDS)
        for name in sink_fields
        if name not in _MINTED_FIELDS
    )


# ── Sorento accepted-field catalogs (AC-15-42) ────────────────────────────────
SORENTO_FIELDS: Dict[str, Tuple[SorentoFieldDef, ...]] = {
    ENTITY_SUPPLIER: _accepted(CanonicalSupplier.SINK_FIELDS),
    ENTITY_CUSTOMER: _accepted(CanonicalCustomer.SINK_FIELDS),
    # GRN is a document (lines nested), not a master sink - it has no accepted
    # master-field set, so the mapping editor's Sorento picker is empty for it.
    ENTITY_GOODS_RECEIVED_NOTE: (),
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
    "CreditLimit",
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


def sorento_field_for(entity_type: str, canonical_field: str) -> Optional[str]:
    """The Sorento-facing name for a stored ``canonical_field``, or ``None`` when
    the field is not delivered to Sorento (identity/provenance like
    ``last_modified``, or an ``extras`` key) - projected as non-delivered
    (plan §2)."""
    return canonical_field if canonical_field in accepted_field_names(entity_type) else None
