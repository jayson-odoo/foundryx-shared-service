"""Sprint-5/10 S1 - the shipped product HTTP preset content and its wire
effects: AC-10-04 (pre-filled lookup), AC-10-59 (R5 negative-price clamp,
pinned on the DELIVERED wire value), AC-10-60 (the one trim rule - identity
side only, the enrich-join side is pinned in ``test_s10_http_lookups.py``),
AC-10-71 (code-wins product identity, R8), AC-10-73 (R10 description
parity), AC-10-74 (R10 ``uom_code`` withheld, seeded present-but-disabled),
and AC-10-07 (the general "falsy-but-not-None stays" sink rule, exercised
here through the SHIPPED preset's own formula rows rather than a hand-rolled
``CanonicalProduct``).

RED before the coder: ``PresetField``/``HttpPreset`` carry no ``lookups``/
``enabled`` fields yet and ``PRODUCT_HTTP_PRESET.rows`` still has the S1-era
shape (``Desc2 -> description``, no ``BaseUOMPrice -> list_price`` row, no
disabled ``uom_code`` row) - every content assertion below fails on a real,
named mismatch (never an ImportError, since ``presets.py`` already exists).

Runs the mapping engine over the ACTUAL preset rows (never a hand-copied
formula string) so a coder who "forgets" to update the shipped preset, while
the formula engine itself works fine in isolation, still gets a RED test.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

import pytest

from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.mapping import MappingEngine, MappingRow, flat_profile, flat_source_ref
from modules.autocount.presets import PRODUCT_HTTP_PRESET, HttpPreset, PresetField

DATABASE_NAME = "AED_SORENTO"


def _row_for(source_path: str, canonical_field: str) -> PresetField:
    for field in PRODUCT_HTTP_PRESET.rows:
        if field.source_path == source_path and field.canonical_field == canonical_field:
            return field
    raise AssertionError(
        f"no preset row {source_path!r} -> {canonical_field!r}; rows were "
        f"{[(f.source_path, f.canonical_field) for f in PRODUCT_HTTP_PRESET.rows]}"
    )


def _engine() -> MappingEngine:
    rows = [
        MappingRow(
            source_path=f.source_path,
            canonical_field=f.canonical_field,
            transform=f.transform,
            formula=f.formula,
            is_required=f.required,
            is_enabled=getattr(f, "enabled", True),
        )
        for f in PRODUCT_HTTP_PRESET.rows
    ]
    profile = flat_profile(ENTITY_PRODUCT, list(PRODUCT_HTTP_PRESET.key_fields))
    return MappingEngine(rows, entity_type=ENTITY_PRODUCT, profile=profile, database_name=DATABASE_NAME)


def _raw(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "ItemCode": "SRT-01",
        "Description": "WIDGET",
        "Desc2": None,
        "ItemGroup": "GRP1",
        "ItemBrand": "BR1",
        "BaseUOM": "UNIT",
        "IsActive": "T",
        "Discontinued": "F",
        "BaseUOMPrice": 10.0,
    }
    base.update(overrides)
    return base


# ── AC-10-04: the preset ships PRE-FILLED with the ItemUOM lookup ───────────


def test_product_preset_has_lookups_field_defaulting_to_empty_tuple_on_other_presets():
    """A non-product preset never gains a lookup by accident - the field
    exists on ``HttpPreset`` generally (any preset MAY carry lookups) but
    defaults empty."""
    from modules.autocount.presets import WAREHOUSE_HTTP_PRESET

    assert hasattr(WAREHOUSE_HTTP_PRESET, "lookups")
    assert tuple(WAREHOUSE_HTTP_PRESET.lookups) == ()


def test_product_preset_ships_the_pre_filled_item_uom_lookup():
    assert len(PRODUCT_HTTP_PRESET.lookups) == 1
    lookup = dict(PRODUCT_HTTP_PRESET.lookups[0])
    assert lookup["path"] == "/itemuombypage"
    assert lookup["as"] == "uom"
    assert lookup["on"] == [
        {"local": "ItemCode", "remote": "ItemCode"},
        {"local": "BaseUOM", "remote": "UOM", "match": "casefold_trim"},
    ]
    assert lookup["fields"] == [{"remote": "Price", "as": "BaseUOMPrice"}]


def _product_preset_lookup_aliases() -> set:
    return {
        field_spec["as"]
        for lookup in PRODUCT_HTTP_PRESET.lookups
        for field_spec in lookup.get("fields", [])
    }


def test_product_preset_lookup_validates_clean():
    """The shipped lookup must itself pass AC-10-01's own validator against
    the product preset's OWN source columns - a preset that fails its own
    save gate would be a foolproof-UI regression the moment the operator
    opens a fresh task.

    review round 1b (orchestrator-authorized fixture fix, assertion
    unchanged): under the raw-only rule, `source_columns` means the task's
    STORED, RAW main-endpoint columns - never a lookup's own alias (which
    is derived at read time, never stored). The old fixture modelled the
    pre-round-1b mixed `result_columns` by using every mapping row's
    `source_path` verbatim, which includes `BaseUOMPrice` only because the
    list_price mapping row's source_path equals the lookup's alias
    (AC-10-04) - not because it is ever a genuine raw column. Excluding the
    preset's own lookup aliases (derived from `PRODUCT_HTTP_PRESET.lookups`
    itself, never hardcoded) makes this fixture model a genuinely raw set.
    """
    from modules.autocount.http_source.lookups import validate_lookups

    lookup_aliases = _product_preset_lookup_aliases()
    source_columns = [
        f.source_path for f in PRODUCT_HTTP_PRESET.rows if f.source_path not in lookup_aliases
    ]
    errors = validate_lookups(list(PRODUCT_HTTP_PRESET.lookups), source_columns)
    assert errors == {}, errors


def test_product_preset_lookup_rejects_when_its_alias_is_a_raw_column():
    """The sibling of the test above: the SAME preset lookup, validated
    against a column set that DOES contain `BaseUOMPrice` as a genuine raw
    column, must be rejected - pinning that the collision check is exact
    (never vacuously empty because this fixture happens to exclude it),
    not just that the "clean" case above passes."""
    from modules.autocount.http_source.lookups import validate_lookups

    lookup_aliases = _product_preset_lookup_aliases()
    source_columns = [
        f.source_path for f in PRODUCT_HTTP_PRESET.rows if f.source_path not in lookup_aliases
    ] + sorted(lookup_aliases)
    errors = validate_lookups(list(PRODUCT_HTTP_PRESET.lookups), source_columns)
    assert "lookups[0].fields[0].as" in errors, errors


# ── AC-10-59: the clamp formula, on the DELIVERED wire value ─────────────────


def test_list_price_row_carries_the_clamp_formula():
    row = _row_for("BaseUOMPrice", "list_price")
    assert row.formula == "if(number(value) <= 0, 0, number(value))"
    assert row.required is False


@pytest.mark.parametrize(
    "source_price, expected_wire",
    [
        (-1.0, "0.0"),
        (-0.0, "0.0"),
        (0.0, "0.0"),
        (12.5, "12.5"),
    ],
)
def test_list_price_clamp_delivered_wire_values(source_price, expected_wire):
    mapped = _engine().map_document(_raw(BaseUOMPrice=source_price))
    assert mapped.ok, mapped.errors
    payload = mapped.record.sink_payload()
    assert payload.get("list_price") == expected_wire, payload


def test_list_price_absent_omits_the_key_entirely():
    raw = _raw()
    del raw["BaseUOMPrice"]
    mapped = _engine().map_document(raw)
    assert mapped.ok, mapped.errors
    payload = mapped.record.sink_payload()
    assert "list_price" not in payload


# ── AC-10-73: description parity with the manual Excel path ─────────────────


def test_description_row_replaces_desc2_row_and_carries_the_parity_formula():
    # The OLD `Desc2 -> description` row must be GONE (replaced, not kept
    # alongside the new one).
    for field in PRODUCT_HTTP_PRESET.rows:
        assert not (field.source_path == "Desc2" and field.canonical_field == "description"), (
            "the Desc2 -> description row must be REPLACED by Description -> "
            "description (AC-10-73), not kept alongside it"
        )
    row = _row_for("Description", "description")
    assert row.formula == (
        'trim(if(default(Desc2, "") != "", concat(Description, " ", Desc2), Description))'
    )


def test_description_no_desc2_is_just_description():
    mapped = _engine().map_document(_raw(Description="WIDGET", Desc2=None))
    assert mapped.ok, mapped.errors
    assert mapped.record.description == "WIDGET"
    assert mapped.record.name == "WIDGET"  # `name` is untouched, still Description -> name


def test_description_with_desc2_joins_with_one_space():
    mapped = _engine().map_document(_raw(Description="WIDGET", Desc2="BLUE"))
    assert mapped.ok, mapped.errors
    assert mapped.record.description == "WIDGET BLUE"


def test_description_raw_join_can_yield_a_double_space():
    """Live finding: 2,786 `SRT` descriptions hold a double space precisely
    because the Excel path joins RAW - never collapsed here either."""
    mapped = _engine().map_document(_raw(Description="WIDGET", Desc2=" BLUE"))
    assert mapped.ok, mapped.errors
    assert mapped.record.description == "WIDGET  BLUE"


def test_description_starting_with_stars_passes_through_unchanged():
    """2,882 live `SRT` descriptions start `****` - Sorento derives
    ``is_discontinued`` from the TEXT we send, so this side must never
    strip or alter the marker."""
    mapped = _engine().map_document(_raw(Description="**** OLD ITEM", Desc2=None))
    assert mapped.ok, mapped.errors
    assert mapped.record.description == "**** OLD ITEM"


def test_description_with_dimensions_passes_through_unchanged():
    mapped = _engine().map_document(_raw(Description="WIDGET 10x20x30MM", Desc2=None))
    assert mapped.ok, mapped.errors
    assert mapped.record.description == "WIDGET 10x20x30MM"


# ── AC-10-74: `uom_code` is seeded present but DISABLED ─────────────────────


def test_uom_code_row_is_seeded_disabled_by_default():
    row = _row_for("BaseUOM", "uom_code")
    assert row.enabled is False, (
        "the uom_code row must exist (operator can see and re-enable it) "
        "but ship disabled during the check period (R10/AC-10-74)"
    )


def test_other_preset_rows_default_enabled():
    row = _row_for("ItemCode", "code")
    assert row.enabled is True


def test_preset_field_enabled_defaults_true_for_a_bare_field():
    """A ``PresetField`` constructed with no ``enabled=`` kwarg (every OTHER
    preset in this module) must default enabled - the new flag must not
    silently disable every pre-existing row across the whole file."""
    field = PresetField("X", "y", "string")
    assert field.enabled is True


# ── AC-10-71: code wins - product identity is always <refPrefix>:<ItemCode> ──


def test_product_preset_keys_only_on_item_code():
    assert PRODUCT_HTTP_PRESET.key_fields == ("ItemCode",)


def test_no_product_preset_or_row_keys_on_autokey_or_dockey():
    assert "AutoKey" not in PRODUCT_HTTP_PRESET.key_fields
    assert "DocKey" not in PRODUCT_HTTP_PRESET.key_fields
    for field in PRODUCT_HTTP_PRESET.rows:
        assert field.source_path not in ("AutoKey", "DocKey")


def test_srt_and_mch_mint_parallel_refs_for_the_same_item_code():
    srt_ref = flat_source_ref(
        {"ItemCode": "BRACD7455C"}, database_name="AED_SORENTO",
        key_columns=PRODUCT_HTTP_PRESET.key_fields, entity_type=ENTITY_PRODUCT,
    )
    mch_ref = flat_source_ref(
        {"ItemCode": "BRACD7455C"}, database_name="MCH",
        key_columns=PRODUCT_HTTP_PRESET.key_fields, entity_type=ENTITY_PRODUCT,
    )
    assert srt_ref == "AED_SORENTO:BRACD7455C"
    assert mch_ref == "MCH:BRACD7455C"


# KILL TEST (for the reviewer): change the clamp formula's comparison from
# ``<=`` back to ``<`` (the plan's own earlier draft, superseded by AC-10-59)
# - only ``test_list_price_clamp_delivered_wire_values[source_price0-0.0]``
# (the ``-0.0`` case) and ``[source_price2-0.0]`` (the plain ``0.0`` case)
# flip red; the ``-1.0`` and ``12.5`` cases stay green either way, proving
# this test genuinely distinguishes ``<=`` from ``<`` rather than merely
# checking "negative becomes zero".
