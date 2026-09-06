"""Sorento contract 2.1 - masters (sprint-5/04).

Two live findings drive this file:

1. Sorento 2.1 REJECTS ``customers.credit_limit`` with a field-named 422
   (``extra="forbid"`` on its canonical model; proven live - 27/27 SIM
   customers failed). ``CanonicalCustomer.SINK_FIELDS`` must not carry it and
   a customer's ``sink_payload()`` must never emit the key, even when the
   model attribute is populated by a mapping row.

2. Sorento 2.1 treats ``null`` on a master as CLEAR and an ABSENT key as
   leave-alone. ``CanonicalMaster.sink_payload`` currently keeps every
   None-valued ``SINK_FIELDS`` key, so every product ships ``"list_price":
   null`` and every customer ``"credit_limit": null`` - a silent clear of
   whatever Sorento already holds. A None value must be OMITTED; a falsy
   non-None value (``0``, ``""``, ``False``) is a real value and must stay.

Both changes are safe unconditionally: under 1.x/2.0 Sorento ignores
``credit_limit`` and treats null and absent alike.

Documents are out of scope here - a document's ``sink_payload`` keeps sending
``status`` and friends untouched.
"""
from __future__ import annotations

import typing
from decimal import Decimal
from typing import Any, Dict, Type

import pytest

from modules.autocount.canonical.masters import (
    MASTER_ENTITIES,
    CanonicalCustomer,
    CanonicalMaster,
    CanonicalProduct,
)
from modules.autocount.services.sync_service import CANONICAL_MODELS

# Every canonical MASTER shape, straight from the production registry the sink
# rehydrates staged rows through - a shape registered there without this guard
# covering it is impossible.
MASTER_MODELS: Dict[str, Type[CanonicalMaster]] = {
    entity: model
    for entity, model in CANONICAL_MODELS.items()
    if isinstance(model, type) and issubclass(model, CanonicalMaster)
}


def _unwrap_optional(annotation: Any) -> Any:
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    return args[0] if args else annotation


def _falsy_value_for(model: Type[CanonicalMaster], field: str) -> Any:
    """A falsy but NOT-None value of the field's own type."""
    kind = _unwrap_optional(model.model_fields[field].annotation)
    if kind is bool:
        return False
    if kind is int:
        return 0
    if kind is Decimal:
        return Decimal("0")
    return ""


def test_registry_covers_every_master_entity():
    assert set(MASTER_MODELS) == set(MASTER_ENTITIES)


# ── (1) credit_limit leaves the customer wire ───────────────────────────────


def test_customer_sink_fields_do_not_carry_credit_limit():
    assert "credit_limit" not in CanonicalCustomer.SINK_FIELDS


def test_customer_sink_payload_has_no_credit_limit_key_even_when_set():
    """``credit_limit`` is no longer a model attribute (review round 3): a
    stale ``CreditLimit -> credit_limit`` mapping row can only land in
    ``extras``, and extras never cross the wire."""
    customer = CanonicalCustomer(
        source_ref="AED_VSOFT:3", source_doc_no="300-O002", code="300-O002",
        name="OW PIN BOON", phone_number="012-3456789", tax_id="TIN1",
        is_active=True, extras={"credit_limit": Decimal("25000")},
    )
    assert not hasattr(customer, "credit_limit")
    assert customer.extras["credit_limit"] == Decimal("25000")
    payload = customer.sink_payload()
    assert "credit_limit" not in payload
    assert payload["phone_number"] == "012-3456789"
    assert payload["tax_id"] == "TIN1"


# ── (2) None-valued keys are omitted; falsy non-None values are kept ───────


@pytest.mark.parametrize("entity_type", sorted(MASTER_MODELS), ids=sorted(MASTER_MODELS))
def test_master_sink_payload_omits_none_valued_keys(entity_type):
    model = MASTER_MODELS[entity_type]
    # Only the required provenance ref plus the two Sorento-required fields;
    # every other SINK_FIELD is left at its None default.
    record = model(source_ref="AED_VSOFT:1", code="C1", name="Name")
    payload = record.sink_payload()
    none_keys = sorted(key for key, value in payload.items() if value is None)
    assert none_keys == [], (
        f"{model.__name__}.sink_payload() must OMIT None-valued keys (Sorento "
        f"2.1: null = clear, absent = leave alone) - got None for {none_keys}"
    )
    # Nothing outside the allow-list, and the populated fields are all there.
    assert set(payload) <= set(model.SINK_FIELDS)
    assert payload["source_ref"] == "AED_VSOFT:1"
    for key in ("code", "name"):
        if key in model.SINK_FIELDS:
            assert key in payload


@pytest.mark.parametrize("entity_type", sorted(MASTER_MODELS), ids=sorted(MASTER_MODELS))
def test_master_sink_payload_keeps_falsy_non_none_values(entity_type):
    model = MASTER_MODELS[entity_type]
    values = {field: _falsy_value_for(model, field) for field in model.SINK_FIELDS}
    values["source_ref"] = "AED_VSOFT:1"
    record = model(**values)
    payload = record.sink_payload()
    missing = sorted(set(model.SINK_FIELDS) - set(payload))
    assert missing == [], (
        f"{model.__name__}.sink_payload() dropped falsy NON-None values "
        f"{missing} - 0 / '' / False are real values, only None is omitted"
    )
    for field in model.SINK_FIELDS:
        if field == "source_ref":
            continue
        assert payload[field] is not None, field
        # Decimal leaves ``model_dump(mode="json")`` as a string ("0").
        assert payload[field] in (0, "", False, "0"), (
            f"{model.__name__}.{field} should round-trip as the falsy value we "
            f"set, got {payload[field]!r}"
        )


@pytest.mark.parametrize("entity_type", sorted(MASTER_MODELS), ids=sorted(MASTER_MODELS))
def test_master_sink_payload_keeps_every_populated_sink_field(entity_type):
    model = MASTER_MODELS[entity_type]
    populated = {field: _falsy_value_for(model, field) for field in model.SINK_FIELDS}
    populated["source_ref"] = "AED_VSOFT:1"
    for field in model.SINK_FIELDS:
        kind = _unwrap_optional(model.model_fields[field].annotation)
        if kind is str:
            populated[field] = f"v-{field}"
        elif kind is bool:
            populated[field] = True
        elif kind is int:
            populated[field] = 1
        elif kind is Decimal:
            populated[field] = Decimal("1.5")
    record = model(**populated)
    payload = record.sink_payload()
    assert set(payload) == set(model.SINK_FIELDS)


# ── (3) product list_price: None -> absent, 0 -> 0 ─────────────────────────


def _product(**overrides: Any) -> CanonicalProduct:
    base: Dict[str, Any] = dict(
        source_ref="AED_VSOFT:7", source_doc_no="ITEM-7", code="ITEM-7",
        name="Widget", category_code="CAT", uom_code="UNIT", is_active=True,
    )
    base.update(overrides)
    return CanonicalProduct(**base)


def test_product_with_no_list_price_sends_no_list_price_key():
    payload = _product(list_price=None).sink_payload()
    assert "list_price" not in payload
    # And the rest of the product still crosses the wire.
    assert payload["code"] == "ITEM-7"
    assert payload["category_code"] == "CAT"
    assert payload["uom_code"] == "UNIT"


def test_product_with_zero_list_price_sends_zero():
    payload = _product(list_price=Decimal("0")).sink_payload()
    assert "list_price" in payload
    assert Decimal(str(payload["list_price"])) == Decimal("0")


# ── (4) the inert-mapping-row sweep (BL: existing tenants) ─────────────────


def test_backfill_disables_saved_credit_limit_mapping_rows(session_factory):
    """A tenant that already saved a ``credit_limit`` mapping row before it
    left ``SINK_FIELDS`` must not be stuck with an ENABLED row targeting a
    field the entity no longer accepts - the next mapping save's PUT guard
    would reject it out of nowhere. The sweep disables it in place, is
    idempotent, and leaves an unrelated enabled row alone."""
    from modules.autocount.backfill import backfill_disable_credit_limit_mapping_rows
    from modules.autocount.mapping import SCOPE_HEADER
    from modules.autocount.models import AcFieldMapping

    db = session_factory()

    stale = AcFieldMapping(
        tenant_id="tenant-a", company_id="company-a", entity_type="customer",
        scope=SCOPE_HEADER, source_path="CreditLimit",
        canonical_field="credit_limit", transform="decimal",
        is_required=False, is_enabled=True, sort_order=5,
    )
    untouched = AcFieldMapping(
        tenant_id="tenant-a", company_id="company-a", entity_type="customer",
        scope=SCOPE_HEADER, source_path="Email",
        canonical_field="email", transform="string",
        is_required=False, is_enabled=True, sort_order=6,
    )
    db.add_all([stale, untouched])
    db.commit()

    touched = backfill_disable_credit_limit_mapping_rows(db, schema=None)
    db.expire_all()
    assert touched == 1

    assert db.get(AcFieldMapping, stale.id).is_enabled is False
    assert db.get(AcFieldMapping, untouched.id).is_enabled is True

    # Idempotent: a second pass finds nothing left to touch.
    again = backfill_disable_credit_limit_mapping_rows(db, schema=None)
    assert again == 0
