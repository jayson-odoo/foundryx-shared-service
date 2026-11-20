"""Sprint-5/10 S5b - the stock HTTP preset's shape: AC-10-40, AC-10-41,
AC-10-80 (key fields derived from group-by, checked against the PRESET's own
declared config, not a saved task).

RED before the coder: ``modules.autocount.presets`` has no
``STOCK_BALANCE_HTTP_PRESET`` today - every test below fails at collection
with a plain ``ImportError``.

ASSUMED NAME: ``modules.autocount.presets.STOCK_BALANCE_HTTP_PRESET``, an
``HttpPreset`` (the SAME dataclass ``PRODUCT_HTTP_PRESET`` already is),
registered in ``HTTP_PRESETS[ENTITY_STOCK_BALANCE]``. ``HttpPreset`` gains a
``combine: Optional[Dict[str, Any]] = None`` field (today it carries only
``lookups``) - accessing ``.combine`` on the EXISTING dataclass before that
field lands is an ``AttributeError``, not an ``ImportError``, which is fine
per the brief (a real "missing feature", not a name typo).

The combine block asserted here is the EXACT literal
``test_s10_s5a_preview_funnel.py``'s own ``STOCK_COMBINE`` already pins as
"the SAME deterministic set `test_s10_s5a_combine_apply.py` already pins" -
this file does not re-derive it, it holds the PRESET to that already-agreed,
already-GREEN shape so the two can never quietly drift apart.
"""
from __future__ import annotations

from typing import Any, Dict

# ── the agreed shape (byte-identical to test_s10_s5a_preview_funnel.py's own
# STOCK_COMBINE - AC-10-41 verbatim) ────────────────────────────────────────

STOCK_COMBINE: Dict[str, Any] = {
    "computed": [
        {"alias": "item_code", "formula": "trim(ItemCode)"},
        {"alias": "location_code", "formula": "trim(Location)"},
        {
            "alias": "base_qty",
            "formula": (
                "if(lower(trim(UOM)) == lower(trim(ItemBaseUOM)), "
                "number(BalQty), number(BalQty) * number(UomRate))"
            ),
        },
    ],
    "require": [
        {
            "name": "uom_rate",
            "formula": (
                "lower(trim(UOM)) == lower(trim(ItemBaseUOM)) or "
                "number(default(UomRate, 0)) > 0"
            ),
            "reason": "uom_rate_unresolved",
        }
    ],
    "measure": "base_qty",
    "groupBy": ["item_code", "location_code"],
    "measures": [{"source": "base_qty", "op": "sum", "alias": "qty"}],
    "carry": ["ItemDescription", "ItemBaseUOM"],
    "round": [{"measure": "qty", "mode": "half_up", "dp": 0}],
    "drop": [
        {"name": "zero", "formula": "qty == 0"},
        {"name": "negative", "formula": "qty < 0", "listRows": True},
    ],
}

SOURCE_COLUMNS = {"ItemCode", "UOM", "Location", "BatchNo", "BalQty"}


def test_preset_is_registered_under_the_agreed_key():
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.presets import HTTP_PRESETS, STOCK_BALANCE_HTTP_PRESET

    assert HTTP_PRESETS[ENTITY_STOCK_BALANCE] is STOCK_BALANCE_HTTP_PRESET


def test_preset_path_has_no_watermark_and_derives_no_typed_key_fields():
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET

    assert STOCK_BALANCE_HTTP_PRESET.path == "/itembatchbalqtybypage"
    assert STOCK_BALANCE_HTTP_PRESET.watermark_field is None
    # AC-10-40: "Key fields are DERIVED from the combine step's group-by...
    # not typed separately" - the preset itself carries no separate
    # key_fields opinion beyond whatever the dataclass default is; the real
    # key fields for a saved task come from `combine.groupBy` below.
    assert list(STOCK_BALANCE_HTTP_PRESET.combine["groupBy"]) == [
        "item_code", "location_code",
    ]


def test_preset_ships_the_two_lookups_in_the_agreed_order():
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET

    lookups = list(STOCK_BALANCE_HTTP_PRESET.lookups)
    assert len(lookups) == 2, lookups

    item_lookup, uom_lookup = lookups
    assert item_lookup["path"] == "/itembypage"
    assert item_lookup["on"] == [{"local": "ItemCode", "remote": "ItemCode"}]
    assert item_lookup["fields"] == [
        {"remote": "BaseUOM", "as": "ItemBaseUOM"},
        {"remote": "Description", "as": "ItemDescription"},
    ], item_lookup["fields"]

    assert uom_lookup["path"] == "/itemuombypage"
    assert uom_lookup["on"] == [
        {"local": "ItemCode", "remote": "ItemCode"},
        {"local": "UOM", "remote": "UOM", "match": "casefold_trim"},
    ], uom_lookup["on"]
    assert uom_lookup["fields"] == [{"remote": "Rate", "as": "UomRate"}]


def test_preset_lookups_validate_cleanly_against_the_source_columns():
    from modules.autocount.http_source.lookups import validate_lookups
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET

    errors = validate_lookups(list(STOCK_BALANCE_HTTP_PRESET.lookups), SOURCE_COLUMNS)
    assert errors == {}, errors


def test_preset_combine_block_matches_the_agreed_shape_exactly():
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET

    assert STOCK_BALANCE_HTTP_PRESET.combine == STOCK_COMBINE, STOCK_BALANCE_HTTP_PRESET.combine


def test_preset_combine_validates_cleanly_against_its_own_lookup_aliases():
    from modules.autocount.http_source.combine import validate_combine
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET

    lookup_aliases = ["ItemBaseUOM", "ItemDescription", "UomRate"]
    errors = validate_combine(
        STOCK_BALANCE_HTTP_PRESET.combine, SOURCE_COLUMNS, lookup_aliases
    )
    assert errors == {}, errors


def test_every_combine_formula_parses_through_the_hand_written_engine():
    """The house anti-SSTI line, checked directly (AC-10-41's own text:
    "Every formula parses through the EXISTING hand-written engine") - never
    eval, never a template language."""
    from modules.autocount.formula import parse_formula
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET

    combine = STOCK_BALANCE_HTTP_PRESET.combine
    lookup_aliases = {"ItemBaseUOM", "ItemDescription", "UomRate"}
    known = set(SOURCE_COLUMNS) | lookup_aliases

    computed_aliases: set = set()
    for spec in combine["computed"]:
        parse_formula(spec["formula"], frozenset(known | computed_aliases))
        computed_aliases.add(spec["alias"])

    for spec in combine["require"]:
        parse_formula(spec["formula"], frozenset(known | computed_aliases))

    post_group = (
        set(combine["groupBy"])
        | {m["alias"] for m in combine["measures"]}
        | set(combine["carry"])
    )
    for spec in combine["drop"]:
        parse_formula(spec["formula"], frozenset(post_group))


def test_preset_carry_and_measure_columns_are_the_probed_live_shape():
    """AC-10-41 verbatim: carry = [ItemDescription, ItemBaseUOM]; one summed
    measure alias 'qty'; one round rule, half_up, 0 dp, over 'qty'; two drop
    rules 'zero'/'negative' in that order, only 'negative' listing rows."""
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET

    combine = STOCK_BALANCE_HTTP_PRESET.combine
    assert combine["carry"] == ["ItemDescription", "ItemBaseUOM"]
    assert combine["measures"] == [{"source": "base_qty", "op": "sum", "alias": "qty"}]
    assert combine["measure"] == "base_qty"
    assert combine["round"] == [{"measure": "qty", "mode": "half_up", "dp": 0}]
    drop_names = [d["name"] for d in combine["drop"]]
    assert drop_names == ["zero", "negative"]
    assert combine["drop"][0].get("listRows") in (None, False)
    assert combine["drop"][1]["listRows"] is True


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_preset_combine_block_matches_the_agreed_shape_exactly dies if the
#   coder ships a "close enough" combine block that differs in ANY key order/
#   formula text from the already-GREEN `test_s10_s5a_preview_funnel.py`
#   fixture - the two files would then silently describe two different
#   reducers for the same preset.
# * test_every_combine_formula_parses_through_the_hand_written_engine dies if
#   a formula uses a token the engine's FUNCTION_CATALOG/OPERATOR_CATALOG
#   does not define (the save-time 422 gate any real task would hit).
