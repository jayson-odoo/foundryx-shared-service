"""Sprint-5/10 S5a - AC-10-77/78/79/81 (R11): the combine ROWS engine's
runtime behaviour - computed columns, require rules, group/measure/carry,
rounding, ordered drop rules, and the generic (entity-agnostic) metadata
shape.

RED before the coder: ``modules.autocount.http_source.combine`` does not
exist yet (see ``test_s10_s5a_combine_validate.py`` for the collection-error
rationale, identical here).

ASSUMED CONTRACT - a single pure runtime entry point, deliberately NOT split
into the per-stage private functions the plan's files list names loosely
("computed, require, group, round, drop") - those are internal to
``combine.py`` and free for the coder to shape however is convenient
(mirroring how ``test_s10_http_lookups.py`` deliberately avoided pinning
``lookups.py``'s own ``build_index``/``merge_onto_rows`` signatures). This
file pins the ONE seam a caller (``HttpApiSource.fetch_changes`` and the
preview route) actually needs:

    @dataclass
    class CombineResult:
        rows: List[dict]       # the REDUCED (grouped) rows
        metadata: dict         # AC-10-81's generic shape, see below

    apply_combine(rows: Sequence[dict], combine: dict) -> CombineResult

``apply_combine`` TRUSTS its input (already validated at save time) - it
does not re-run ``validate_combine`` - mirroring ``merge_onto_rows``/
``build_index`` trusting a saved ``lookups`` config as-is.

Stage order (AC-10-77/78/79, pinned literally): computed (list order) ->
require (list order, first falsy excludes) -> group by ``groupBy`` (exact
values, first-appearance order) -> measures + carry -> round -> drop
(list order, first match wins).

Formula evaluation: every ``computed``/``require``/``drop`` formula runs
through the EXISTING ``modules.autocount.formula.evaluate_formula(formula,
None, facts=row)`` - the SAME calling shape a document header formula
already uses (a raw dict of EXACT-cased column names as ``facts``, no
fold-matching - that variant is ``evaluate_row_filter``'s own distinct
entry point for a different calling shape, per ``formula.py``'s own
docstring). This is the house anti-SSTI line applied to one more surface.

Generic metadata shape (AC-10-81, pinned BYTE-FOR-BYTE as the AC states it):
    {
      "excludedRows": [ {<groupBy col>: v, ..., "measure": <raw value or
                          None>, "reason": <str>}, ... ],
      "excludedCount": int,
      "dropped": { "<rule name>": {"count": int, "rows"?: [...]} },
      "roundedCount": int,
    }
``dropped[<rule>]["rows"]`` is present ONLY when that rule's ``listRows`` is
true, and is CAPPED at ``DROPPED_ROWS_CAP`` (50, AC-10-79) - ``"count"`` is
always the FULL, uncapped total. A dropped/listed row is the GROUPED output
shape (groupBy columns + measure aliases), matching AC-10-42's own
``{item_code, location_code, qty}`` example.

TWO GENUINE PLAN-VS-ENGINE TENSIONS, RESOLVED HERE (flagged prominently in
the tester's report - the coder should confirm rather than silently
reshape):

1. AC-10-77 fixes stage order as computed-THEN-require, but the stock
   preset's OWN ``base_qty`` computed formula
   (``number(BalQty) * number(UomRate)``) raises ``FormulaRuntimeError``
   for the 5 live rows whose ItemUOM lookup MISSED (``UomRate`` genuinely
   ABSENT) - exactly the case its sibling ``require`` rule
   (``uom_rate_unresolved``) exists to catch, but require never gets a
   chance to run first. Resolved here BY SYMMETRY with AC-10-77's own
   "a require formula that raises is itself an exclusion, never a run
   failure" rule: a COMPUTED formula that raises ALSO excludes the row
   (assumed reason ``"computed_error"``), never crashes the run. This
   keeps the require rule meaningful for its OTHER live case (a resolved
   but non-positive rate, which does not raise) without a contradiction.
   Test: ``test_computed_formula_runtime_error_excludes_the_row``.
2. For a row excluded by a COMPUTED-stage failure, the DESIGNATED measure
   column was never successfully computed - there is no raw value to
   report. This file does not pin what ``excludedRows[i]["measure"]`` reads
   in that one case (asserts only the reason and groupBy-derived identity),
   leaving the exact value (``None`` vs the pre-computed raw column) to the
   coder.

A numeric ``measures`` op (``sum``/``min``/``max``) over a value that is
genuinely non-numeric at RUN TIME (AC-10-76's own text: "a runtime
non-numeric still raises the normal named TransformError") raises
``modules.autocount.mapping.TransformError`` - a hard run failure, never a
silent per-row exclusion (that distinguishes it sharply from a ``require``/
computed failure, which excludes).
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from modules.autocount.http_source.combine import DROPPED_ROWS_CAP, apply_combine
from modules.autocount.mapping import TransformError

STOCK_COMBINE: Dict[str, Any] = {
    # ``item_code``/``location_code`` (the groupBy columns) are computed
    # BEFORE the failure-prone ``base_qty`` (deliberately reordered from the
    # plan's bullet-list prose order, which does not itself pin computed[]
    # array order - see tension #1/#2 above): this way a row whose
    # ``base_qty`` formula raises still carries valid groupBy identity in
    # its ``excludedRows`` entry, honouring AC-10-77's "carries the row's
    # groupBy values" guarantee even for a computed-stage failure.
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


def _row(**kw: Any) -> Dict[str, Any]:
    base = {
        "ItemCode": "X", "UOM": "UNIT", "ItemBaseUOM": "UNIT", "Location": "L",
        "BatchNo": "", "BalQty": 1, "ItemDescription": "Item", "UomRate": 1.0,
    }
    base.update(kw)
    return base


# ── the full funnel (AC-10-41/42/43/77/78/79/81), one deterministic fixture ──


def _funnel_rows() -> List[Dict[str, Any]]:
    return [
        # Group (SRT-01, MAIN): base row (10) + non-base row (2*5=10) -> 20.
        _row(ItemCode="SRT-01", UOM="UNIT", Location="MAIN", BalQty=10,
             ItemDescription="Widget-First"),
        _row(ItemCode="SRT-01", UOM="BOX", Location="MAIN", BalQty=2, UomRate=5.0,
             ItemDescription="Widget-Second"),
        # Group (SRT-02, MBS) via trim-fold ('MBS ' == 'MBS'): 5 + -8 = -3
        # -> DROPPED by "negative", listed.
        _row(ItemCode="SRT-02", UOM="UNIT", Location="MBS ", BalQty=5,
             ItemDescription="Gadget"),
        _row(ItemCode="SRT-02", UOM="UNIT", Location="MBS", BalQty=-8,
             ItemDescription="Gadget"),
        # Group (SRT-03, LOC1): base row only, BalQty 0 -> DROPPED by "zero",
        # not listed (listRows unset/false).
        _row(ItemCode="SRT-03", UOM="UNIT", Location="LOC1", BalQty=0,
             ItemDescription="Thing"),
        # (SRT-04, LOC2): non-base, UomRate PRESENT but 0 -> base_qty computes
        # cleanly to 0.0 (no raise), then `require` EXCLUDES it
        # (uom_rate_unresolved) - the "resolved but non-positive" case.
        _row(ItemCode="SRT-04", UOM="BOX", Location="LOC2", BalQty=3, UomRate=0,
             ItemDescription="Thing2"),
        # (SRT-05, LOC3): non-base, UomRate ABSENT entirely -> the computed
        # base_qty formula itself raises -> excluded (tension #1 above).
        {
            "ItemCode": "SRT-05", "UOM": "BOX", "ItemBaseUOM": "UNIT",
            "Location": "LOC3", "BatchNo": "", "BalQty": 4,
            "ItemDescription": "Thing3",
        },
        # Group (SRT-06, LOC4): base row (3) + non-base (1*0.5=0.5) -> 3.5,
        # half_up rounds to 4 -> roundedCount += 1, survives (positive).
        _row(ItemCode="SRT-06", UOM="UNIT", Location="LOC4", BalQty=3,
             ItemDescription="Frac"),
        _row(ItemCode="SRT-06", UOM="BOX", Location="LOC4", BalQty=1, UomRate=0.5,
             ItemDescription="Frac"),
    ]


def test_full_funnel_rows_out():
    result = apply_combine(_funnel_rows(), STOCK_COMBINE)
    by_key = {(r["item_code"], r["location_code"]): r for r in result.rows}
    assert set(by_key) == {("SRT-01", "MAIN"), ("SRT-06", "LOC4")}, result.rows
    assert by_key[("SRT-01", "MAIN")]["qty"] == 20
    assert by_key[("SRT-06", "LOC4")]["qty"] == 4  # 3.5 half-up


def test_carry_takes_the_first_value_seen_in_the_group():
    result = apply_combine(_funnel_rows(), STOCK_COMBINE)
    by_key = {(r["item_code"], r["location_code"]): r for r in result.rows}
    assert by_key[("SRT-01", "MAIN")]["ItemDescription"] == "Widget-First"


def test_excluded_count_and_dropped_counts():
    result = apply_combine(_funnel_rows(), STOCK_COMBINE)
    meta = result.metadata
    assert meta["excludedCount"] == 2  # SRT-04/LOC2 + SRT-05/LOC3
    assert meta["dropped"]["zero"]["count"] == 1  # SRT-03/LOC1
    assert meta["dropped"]["negative"]["count"] == 1  # SRT-02/MBS
    assert meta["roundedCount"] == 1  # SRT-06/LOC4 (3.5 -> 4)


def test_negative_drop_rule_lists_rows_zero_rule_does_not():
    result = apply_combine(_funnel_rows(), STOCK_COMBINE)
    dropped = result.metadata["dropped"]
    assert "rows" not in dropped["zero"], dropped["zero"]
    assert dropped["negative"]["rows"] == [
        {"item_code": "SRT-02", "location_code": "MBS", "qty": -3}
    ], dropped["negative"]


def test_require_excludes_with_its_own_reason():
    result = apply_combine(_funnel_rows(), STOCK_COMBINE)
    excluded = result.metadata["excludedRows"]
    by_item = {row.get("item_code"): row for row in excluded}
    assert by_item["SRT-04"]["reason"] == "uom_rate_unresolved"
    assert by_item["SRT-04"]["location_code"] == "LOC2"


def test_computed_formula_runtime_error_excludes_the_row():
    """Tension #1 (module docstring): a computed-stage formula that raises
    (here: ``number(UomRate)`` with ``UomRate`` genuinely absent) excludes
    the row rather than crashing the whole combine step."""
    result = apply_combine(_funnel_rows(), STOCK_COMBINE)
    excluded = result.metadata["excludedRows"]
    by_item = {row.get("item_code"): row for row in excluded}
    assert "SRT-05" in by_item, excluded
    assert by_item["SRT-05"]["reason"] == "computed_error"


def test_generic_metadata_shape_is_exactly_four_keys():
    """AC-10-81, pinned literally: the step's OWN output never grows an
    entity-specific key - the stock header names are produced from THIS by
    a separate declarative map (S5b), not baked in here."""
    result = apply_combine(_funnel_rows(), STOCK_COMBINE)
    assert set(result.metadata.keys()) == {
        "excludedRows", "excludedCount", "dropped", "roundedCount"
    }, result.metadata


# ── measures ops, isolated (a plain single-column fixture) ──────────────────


SIMPLE_COMBINE: Dict[str, Any] = {
    "computed": [],
    "require": [],
    "measure": "v",
    "groupBy": ["g"],
    "measures": [
        {"source": "v", "op": "sum", "alias": "total"},
        {"source": "v", "op": "count", "alias": "n"},
        {"source": "v", "op": "min", "alias": "lo"},
        {"source": "v", "op": "max", "alias": "hi"},
        {"source": "v", "op": "first", "alias": "f"},
        {"source": "v", "op": "last", "alias": "l"},
    ],
    "carry": [],
    "round": [],
    "drop": [],
}


def test_measure_ops_sum_count_min_max_first_last():
    rows = [{"g": "A", "v": 3}, {"g": "A", "v": 5}, {"g": "A", "v": 1}]
    result = apply_combine(rows, SIMPLE_COMBINE)
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["total"] == 9
    assert row["n"] == 3
    assert row["lo"] == 1
    assert row["hi"] == 5
    assert row["f"] == 3
    assert row["l"] == 1


def test_group_ordering_is_first_appearance():
    rows = [{"g": "B", "v": 1}, {"g": "A", "v": 2}, {"g": "B", "v": 3}]
    combine = {**SIMPLE_COMBINE, "measures": [{"source": "v", "op": "sum", "alias": "total"}]}
    result = apply_combine(rows, combine)
    assert [r["g"] for r in result.rows] == ["B", "A"]


def test_numeric_measure_over_non_numeric_value_raises_transform_error():
    """AC-10-76's own text: a RUNTIME non-numeric on a numeric op is a
    named ``TransformError``, never a silent per-row exclusion."""
    rows = [{"g": "A", "v": "not-a-number"}]
    combine = {**SIMPLE_COMBINE, "measures": [{"source": "v", "op": "sum", "alias": "total"}]}
    with pytest.raises(TransformError):
        apply_combine(rows, combine)


# ── AC-10-79: dropped rows capped at 50, count stays the FULL total ─────────


def test_dropped_rows_list_capped_at_50_count_stays_full():
    rows: List[Dict[str, Any]] = []
    for i in range(60):
        rows.append({"g": f"G{i}", "v": -1})
    combine = {
        "computed": [],
        "require": [],
        "measure": "v",
        "groupBy": ["g"],
        "measures": [{"source": "v", "op": "sum", "alias": "qty"}],
        "carry": [],
        "round": [],
        "drop": [{"name": "negative", "formula": "qty < 0", "listRows": True}],
    }
    result = apply_combine(rows, combine)
    dropped = result.metadata["dropped"]["negative"]
    assert dropped["count"] == 60
    assert len(dropped["rows"]) == DROPPED_ROWS_CAP == 50


def test_no_rows_survive_to_output_when_all_dropped():
    rows = [{"g": "A", "v": -1}]
    combine = {
        "computed": [], "require": [], "measure": "v", "groupBy": ["g"],
        "measures": [{"source": "v", "op": "sum", "alias": "qty"}],
        "carry": [], "round": [],
        "drop": [{"name": "negative", "formula": "qty < 0"}],
    }
    result = apply_combine(rows, combine)
    assert result.rows == []


# ── ordered drop rules: FIRST match wins, never double-counted ──────────────


def test_first_matching_drop_rule_wins_no_double_count():
    rows = [{"g": "A", "v": 0}]
    combine = {
        "computed": [], "require": [], "measure": "v", "groupBy": ["g"],
        "measures": [{"source": "v", "op": "sum", "alias": "qty"}],
        "carry": [], "round": [],
        "drop": [
            {"name": "zero", "formula": "qty == 0"},
            {"name": "non_positive", "formula": "qty <= 0"},
        ],
    }
    result = apply_combine(rows, combine)
    dropped = result.metadata["dropped"]
    assert dropped["zero"]["count"] == 1
    assert dropped.get("non_positive", {}).get("count", 0) == 0
