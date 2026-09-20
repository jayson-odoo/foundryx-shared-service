"""Sprint-5/10 S5a - AC-10-76 (combine config and its save gate, R11): the
save-time validator for a task's ``source_config.combine`` block.

RED before the coder: ``modules.autocount.http_source.combine`` does not
exist at all yet (verified 2026-09-20 - ``http_source/`` only has
``__init__.py``/``client.py``/``envelope.py``/``errors.py``/``lookups.py``/
``preview.py``/``source.py``). Every test here imports
``modules.autocount.http_source.combine.validate_combine`` (plain top-level
import, no try/except, mirroring ``test_s10_lookups_validate.py``'s own
precedent for this module) and is expected to fail COLLECTION with
``ImportError``/``ModuleNotFoundError`` until S5a lands.

ASSUMED CONTRACT (the plan/AC name the shape and the caps but not the exact
Python signature or the module's constant names - this file pins one,
mirroring the ``validate_lookups`` idiom exactly):

    validate_combine(
        combine: Optional[dict],
        source_columns: Optional[Sequence[str]],
        lookup_aliases: Optional[Sequence[str]] = None,
    ) -> dict[str, str]

``combine`` is optional (``None`` -> no combine step configured -> ``{}``).
``source_columns`` is the task's STORED raw ``result_columns`` (``None`` when
never previewed - every STRUCTURAL rule still runs; only "is this a known
column" checks are skipped, exactly mirroring ``validate_lookups``'s own
"accepted un-checked" contract). ``lookup_aliases`` is the task's configured
lookups' own projected aliases (``lookups[].fields[].as``) - a computed
formula/groupBy/measure/carry/drop MAY reference one, same as a raw source
column.

Error shape: ``{"combine.<part>[i].<field>": "<message>"}`` - the same
bracket convention ``validate_lookups`` already established, applied one
level for ``combine``'s own six list-shaped parts (``computed``, ``require``,
``groupBy``, ``measures``, ``carry``, ``drop``) plus the two scalar fields
(``measure``, and each ``round[i]``). A list-level cap violation (more than
the max) is keyed at the BARE part name with no index (``combine.computed``),
mirroring ``validate_lookups``'s own ``errors["lookups"]`` cap message.

ASSUMED CONSTANTS (module-level, importable - AC-10-76's own numbers):
    MAX_COMBINE_COMPUTED = 10
    MAX_COMBINE_REQUIRE = 10
    MAX_COMBINE_GROUP_BY = 5
    MAX_COMBINE_MEASURES = 10
    MAX_COMBINE_DROP = 10
    MAX_COMBINE_CARRY = 20
    MEASURE_OPS = frozenset({"sum", "min", "max", "count", "first", "last"})
    ROUND_MODES = frozenset({"none", "half_up"})

Every formula (``computed[].formula``, ``require[].formula``,
``drop[].formula``) is parsed by the EXISTING, hand-written
``modules.autocount.formula.parse_formula`` with ``known_variables`` built
from the columns known AT THAT POINT (source columns + lookup aliases +
EARLIER computed aliases for ``computed``/``require``; groupBy + carry +
measures aliases for ``drop``, i.e. the POST-GROUP schema) - never
eval/Jinja, the house anti-SSTI line. An unknown column/alias therefore
surfaces as ``parse_formula``'s own "Unknown name" ``FormulaParseError``,
wrapped into the named field key.

NOT tested here (explicitly out of scope, flagged as ambiguities in the
tester's report rather than guessed): the two SAMPLE-based checks AC-10-76
also names (a numeric op over a column whose PREVIEWED SAMPLE is
non-numeric; a require/drop formula whose INFERRED TYPE is not boolean) -
neither the sampling parameter shape nor the "inferred type" static-analysis
technique is pinned by the AC text, so inventing one here would be an
un-earned assumption the coder could not safely treat as the contract.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

import pytest

from modules.autocount.http_source.combine import (
    MAX_COMBINE_CARRY,
    MAX_COMBINE_COMPUTED,
    MAX_COMBINE_DROP,
    MAX_COMBINE_GROUP_BY,
    MAX_COMBINE_MEASURES,
    MAX_COMBINE_REQUIRE,
    validate_combine,
)

SOURCE_COLUMNS = ["ItemCode", "UOM", "Location", "BatchNo", "BalQty"]
LOOKUP_ALIASES = ["ItemBaseUOM", "ItemDescription", "UomRate"]


def _stock_combine(**overrides: Any) -> Dict[str, Any]:
    """The AC-10-41 stock preset, verbatim - the KNOWN-GOOD baseline every
    negative test mutates one field of."""
    combine: Dict[str, Any] = {
        "computed": [
            {
                "alias": "base_qty",
                "formula": (
                    "if(lower(trim(UOM)) == lower(trim(ItemBaseUOM)), "
                    "number(BalQty), number(BalQty) * number(UomRate))"
                ),
            },
            {"alias": "item_code", "formula": "trim(ItemCode)"},
            {"alias": "location_code", "formula": "trim(Location)"},
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
    combine.update(overrides)
    return combine


def _errors(combine: Dict[str, Any]) -> Dict[str, str]:
    return validate_combine(combine, SOURCE_COLUMNS, LOOKUP_ALIASES)


# ── the happy path (a control - proves the fixture itself is well-formed) ────


def test_valid_stock_combine_has_no_errors():
    assert _errors(_stock_combine()) == {}


def test_no_combine_is_optional():
    assert validate_combine(None, SOURCE_COLUMNS, LOOKUP_ALIASES) == {}


def test_never_previewed_accepts_unchecked_columns():
    """Mirrors ``validate_lookups``'s own contract: with ``source_columns``
    ``None`` (never previewed), a column/alias-existence check is skipped -
    only structural rules (caps, regex, shape) still run."""
    combine = _stock_combine()
    assert validate_combine(combine, None, None) == {}


# ── AC-10-76: caps ────────────────────────────────────────────────────────────


def test_max_combine_caps_are_10_10_5_10_10_20():
    assert MAX_COMBINE_COMPUTED == 10
    assert MAX_COMBINE_REQUIRE == 10
    assert MAX_COMBINE_GROUP_BY == 5
    assert MAX_COMBINE_MEASURES == 10
    assert MAX_COMBINE_DROP == 10
    assert MAX_COMBINE_CARRY == 20


def test_over_max_computed_rejected():
    extra = [
        {"alias": f"c{i}", "formula": "1"} for i in range(MAX_COMBINE_COMPUTED + 1)
    ]
    combine = _stock_combine(computed=extra, groupBy=[], measure="c0")
    # groupBy is intentionally left invalid too (irrelevant to this check) -
    # the cap error must still fire independent of other violations.
    errors = _errors({**combine, "groupBy": ["c0"]})
    assert "combine.computed" in errors, errors
    assert str(MAX_COMBINE_COMPUTED) in errors["combine.computed"], errors


def test_over_max_require_rejected():
    extra = [
        {"name": f"r{i}", "formula": "true", "reason": f"r{i}"}
        for i in range(MAX_COMBINE_REQUIRE + 1)
    ]
    combine = _stock_combine(require=extra)
    errors = _errors(combine)
    assert "combine.require" in errors, errors
    assert str(MAX_COMBINE_REQUIRE) in errors["combine.require"], errors


def test_over_max_group_by_rejected():
    combine = _stock_combine(groupBy=[f"g{i}" for i in range(MAX_COMBINE_GROUP_BY + 1)])
    errors = _errors(combine)
    assert "combine.groupBy" in errors, errors
    assert str(MAX_COMBINE_GROUP_BY) in errors["combine.groupBy"], errors


def test_over_max_measures_rejected():
    extra = [
        {"source": "base_qty", "op": "sum", "alias": f"m{i}"}
        for i in range(MAX_COMBINE_MEASURES + 1)
    ]
    combine = _stock_combine(measures=extra)
    errors = _errors(combine)
    assert "combine.measures" in errors, errors
    assert str(MAX_COMBINE_MEASURES) in errors["combine.measures"], errors


def test_over_max_drop_rejected():
    extra = [
        {"name": f"d{i}", "formula": "qty == 0"} for i in range(MAX_COMBINE_DROP + 1)
    ]
    combine = _stock_combine(drop=extra)
    errors = _errors(combine)
    assert "combine.drop" in errors, errors
    assert str(MAX_COMBINE_DROP) in errors["combine.drop"], errors


def test_over_max_carry_rejected():
    combine = _stock_combine(carry=[f"c{i}" for i in range(MAX_COMBINE_CARRY + 1)])
    errors = _errors(combine)
    assert "combine.carry" in errors, errors
    assert str(MAX_COMBINE_CARRY) in errors["combine.carry"], errors


def test_empty_group_by_rejected():
    combine = _stock_combine(groupBy=[])
    errors = _errors(combine)
    assert "combine.groupBy" in errors, errors


def test_empty_dict_combine_is_invalid_shape():
    """An explicit ``{}`` (as opposed to omitting the key / ``None``) is a
    combine step with no groupBy - invalid, not "no combine configured"."""
    errors = _errors({})
    assert "combine.groupBy" in errors, errors


# ── AC-10-76: computed columns ────────────────────────────────────────────────


def test_computed_alias_must_match_identifier_regex():
    combine = _stock_combine(
        computed=[{"alias": "base qty", "formula": "1"}], groupBy=["base qty"]
    )
    errors = _errors(combine)
    assert "combine.computed[0].alias" in errors, errors


def test_computed_alias_colliding_with_source_column_rejected():
    combine = _stock_combine(
        computed=[{"alias": "ItemCode", "formula": "trim(ItemCode)"}],
        groupBy=["ItemCode"],
        measure="ItemCode",
    )
    errors = _errors(combine)
    assert "combine.computed[0].alias" in errors, errors


def test_computed_alias_colliding_with_lookup_alias_rejected():
    combine = _stock_combine(
        computed=[{"alias": "ItemBaseUOM", "formula": "1"}],
        groupBy=["ItemBaseUOM"],
        measure="ItemBaseUOM",
    )
    errors = _errors(combine)
    assert "combine.computed[0].alias" in errors, errors


def test_computed_alias_colliding_with_earlier_computed_alias_rejected():
    combine = _stock_combine(
        computed=[
            {"alias": "x", "formula": "1"},
            {"alias": "x", "formula": "2"},
        ],
        groupBy=["x"],
        measure="x",
    )
    errors = _errors(combine)
    assert "combine.computed[1].alias" in errors, errors


def test_computed_formula_unknown_column_rejected():
    combine = _stock_combine(
        computed=[{"alias": "x", "formula": "trim(NotAColumn)"}],
        groupBy=["x"],
        measure="x",
    )
    errors = _errors(combine)
    assert "combine.computed[0].formula" in errors, errors


def test_computed_formula_forward_reference_rejected():
    """A computed formula may name any EARLIER computed alias only - naming
    a LATER one is a 422, mirroring lookups' own forward-reference rule."""
    combine = _stock_combine(
        computed=[
            {"alias": "a", "formula": "location_code"},  # not known YET
            {"alias": "location_code", "formula": "trim(Location)"},
        ],
        groupBy=["a", "location_code"],
        measure="a",
    )
    errors = _errors(combine)
    assert "combine.computed[0].formula" in errors, errors


def test_computed_formula_may_reference_a_lookup_alias():
    combine = _stock_combine(
        computed=[{"alias": "priced", "formula": "number(UomRate) > 0"}],
        groupBy=["priced"],
        measure="priced",
    )
    assert _errors(combine) == {}, _errors(combine)


# ── AC-10-76: require rules ────────────────────────────────────────────────────


def test_require_formula_unknown_column_rejected():
    combine = _stock_combine(
        require=[{"name": "r", "formula": "NotAColumn == 1", "reason": "bad"}]
    )
    errors = _errors(combine)
    assert "combine.require[0].formula" in errors, errors


def test_require_name_required():
    combine = _stock_combine(
        require=[{"name": "", "formula": "true", "reason": "bad"}]
    )
    errors = _errors(combine)
    assert "combine.require[0].name" in errors, errors


def test_require_reason_required():
    combine = _stock_combine(
        require=[{"name": "r", "formula": "true", "reason": ""}]
    )
    errors = _errors(combine)
    assert "combine.require[0].reason" in errors, errors


def test_require_formula_may_reference_an_earlier_computed_alias():
    """AC-10-41's own live shape: the ``uom_rate`` require rule references
    only raw/lookup columns, but a require rule referencing an earlier
    COMPUTED alias (e.g. ``base_qty``) must also be accepted - require runs
    strictly after every computed column (AC-10-77)."""
    combine = _stock_combine(
        require=[{"name": "r", "formula": "base_qty >= 0", "reason": "negative_qty"}]
    )
    assert _errors(combine) == {}, _errors(combine)


# ── AC-10-76: the designated `measure` ────────────────────────────────────────


def test_measure_referencing_a_computed_alias_is_valid():
    """The stock preset's own worked example: ``measure: base_qty`` names a
    COMPUTED alias (the pre-group designated quantity), not a
    ``measures[].alias`` - this is the control the negative test below
    mutates."""
    assert _errors(_stock_combine()) == {}


def test_measure_referencing_an_unknown_column_rejected():
    combine = _stock_combine(measure="NotAColumn")
    errors = _errors(combine)
    assert "combine.measure" in errors, errors


# ── AC-10-76: groupBy ──────────────────────────────────────────────────────────


def test_group_by_unknown_column_rejected():
    combine = _stock_combine(groupBy=["item_code", "NotAColumn"])
    errors = _errors(combine)
    assert "combine.groupBy[1]" in errors, errors


# ── AC-10-76: measures ─────────────────────────────────────────────────────────


def test_measures_source_unknown_column_rejected():
    combine = _stock_combine(
        measures=[{"source": "NotAColumn", "op": "sum", "alias": "qty"}]
    )
    errors = _errors(combine)
    assert "combine.measures[0].source" in errors, errors


def test_measures_invalid_op_rejected():
    combine = _stock_combine(
        measures=[{"source": "base_qty", "op": "average", "alias": "qty"}]
    )
    errors = _errors(combine)
    assert "combine.measures[0].op" in errors, errors


def test_measures_alias_regex_invalid_rejected():
    combine = _stock_combine(
        measures=[{"source": "base_qty", "op": "sum", "alias": "q ty"}]
    )
    errors = _errors(combine)
    assert "combine.measures[0].alias" in errors, errors


def test_measures_alias_colliding_with_group_by_column_rejected():
    combine = _stock_combine(
        measures=[{"source": "base_qty", "op": "sum", "alias": "item_code"}]
    )
    errors = _errors(combine)
    assert "combine.measures[0].alias" in errors, errors


def test_measures_alias_colliding_with_another_measure_alias_rejected():
    combine = _stock_combine(
        measures=[
            {"source": "base_qty", "op": "sum", "alias": "qty"},
            {"source": "base_qty", "op": "count", "alias": "qty"},
        ]
    )
    errors = _errors(combine)
    assert "combine.measures[1].alias" in errors, errors


# ── AC-10-76: carry ────────────────────────────────────────────────────────────


def test_carry_unknown_column_rejected():
    combine = _stock_combine(carry=["ItemDescription", "NotAColumn"])
    errors = _errors(combine)
    assert "combine.carry[1]" in errors, errors


# ── AC-10-76: round ────────────────────────────────────────────────────────────


def test_round_measure_not_a_declared_measure_alias_rejected():
    combine = _stock_combine(round=[{"measure": "NotAMeasure", "mode": "half_up", "dp": 0}])
    errors = _errors(combine)
    assert "combine.round[0].measure" in errors, errors


def test_round_invalid_mode_rejected():
    combine = _stock_combine(round=[{"measure": "qty", "mode": "banker", "dp": 0}])
    errors = _errors(combine)
    assert "combine.round[0].mode" in errors, errors


def test_round_negative_dp_rejected():
    combine = _stock_combine(round=[{"measure": "qty", "mode": "half_up", "dp": -1}])
    errors = _errors(combine)
    assert "combine.round[0].dp" in errors, errors


# ── AC-10-76: drop ─────────────────────────────────────────────────────────────


def test_drop_formula_unknown_column_rejected():
    combine = _stock_combine(drop=[{"name": "bad", "formula": "NotAColumn == 0"}])
    errors = _errors(combine)
    assert "combine.drop[0].formula" in errors, errors


def test_drop_name_required():
    combine = _stock_combine(drop=[{"name": "", "formula": "qty == 0"}])
    errors = _errors(combine)
    assert "combine.drop[0].name" in errors, errors


def test_drop_duplicate_name_rejected():
    combine = _stock_combine(
        drop=[
            {"name": "zero", "formula": "qty == 0"},
            {"name": "zero", "formula": "qty <= 0"},
        ]
    )
    errors = _errors(combine)
    assert "combine.drop[1].name" in errors, errors


def test_drop_formula_may_reference_a_carry_column():
    combine = _stock_combine(
        drop=[{"name": "no_desc", "formula": "ItemDescription == \"\""}]
    )
    assert _errors(combine) == {}, _errors(combine)


def test_drop_formula_may_reference_a_group_by_column():
    combine = _stock_combine(
        drop=[{"name": "no_loc", "formula": "location_code == \"\""}]
    )
    assert _errors(combine) == {}, _errors(combine)


# ── deep-copy hygiene: validate_combine must never mutate its input ─────────


def test_validate_combine_never_mutates_the_input():
    combine = _stock_combine()
    before = copy.deepcopy(combine)
    validate_combine(combine, SOURCE_COLUMNS, LOOKUP_ALIASES)
    assert combine == before


# KILL TEST (for the reviewer): comment out the "measures[].alias colliding
# with a groupBy column" branch in the coder's implementation - exactly
# ``test_measures_alias_colliding_with_group_by_column_rejected`` must flip
# green-to-red (its fixture has no other violation to be caught by).
