"""Computed aggregate functions over repeater columns (sprint-3/02 follow-up).

`sum/avg/min/max(repeater.column)` + `count(repeater)` — eval matrix, arithmetic
composition, fail-closed, and the publish-gate validation (the repeater must be
an earlier repeater field; the column must be numeric; count needs no column).
"""
from app.form_engine.computed import aggregate_refs, evaluate, field_refs
from app.form_engine.schemas import validate_form_doc


def _vals(rows):
    return {"lines": rows}


ROWS = [{"item": "A", "qty": "3"}, {"item": "B", "qty": 5}, {"item": "C", "qty": None}]


def test_sum_skips_non_numeric():
    assert evaluate("sum(lines.qty)", _vals(ROWS)) == 8.0


def test_avg_over_present_values():
    assert evaluate("avg(lines.qty)", _vals(ROWS)) == 4.0  # (3+5)/2


def test_count_is_row_count():
    assert evaluate("count(lines)", _vals(ROWS)) == 3.0


def test_min_max():
    assert evaluate("min(lines.qty)", _vals(ROWS)) == 3.0
    assert evaluate("max(lines.qty)", _vals(ROWS)) == 5.0


def test_aggregate_composes_with_arithmetic():
    assert evaluate("sum(lines.qty) * 2 + 1", _vals(ROWS)) == 17.0


def test_empty_repeater_sum_is_zero_avg_is_none():
    assert evaluate("sum(lines.qty)", {"lines": []}) == 0.0
    assert evaluate("avg(lines.qty)", {"lines": []}) is None


def test_missing_repeater_fails_closed():
    assert evaluate("sum(lines.qty)", {}) == 0.0  # no rows → empty sum
    assert evaluate("max(lines.qty)", {}) is None


def test_refs_split_scalar_and_aggregate():
    assert field_refs("sum(lines.qty) + fee") == frozenset({"fee"})
    aggs = aggregate_refs("sum(lines.qty) + fee")
    assert len(aggs) == 1
    assert (aggs[0].func, aggs[0].repeater_key, aggs[0].sub_key) == ("sum", "lines", "qty")


# ---- publish-gate validation ----


def _doc(*fields):
    return {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "title": "P", "sections": [{"id": "s1", "fields": list(fields)}]}],
    }


def _repeater(key="lines"):
    return {
        "id": "r1",
        "type": "repeater",
        "key": key,
        "label": "Lines",
        "repeater": {
            "fields": [
                {"id": "rs1", "type": "text", "key": "item", "label": "Item"},
                {"id": "rs2", "type": "number", "key": "qty", "label": "Qty"},
            ]
        },
    }


def _computed(expr, key="total"):
    return {"id": "c1", "type": "computed", "key": key, "label": "Total", "computed": {"expression": expr}}


def test_valid_aggregate_publishes():
    assert validate_form_doc(_doc(_repeater(), _computed("sum(lines.qty)"))) == []


def test_count_needs_no_column():
    assert validate_form_doc(_doc(_repeater(), _computed("count(lines)"))) == []


def test_aggregate_over_non_repeater_is_blocked():
    field = {"id": "n1", "type": "number", "key": "fee", "label": "Fee"}
    problems = validate_form_doc(_doc(field, _computed("sum(fee.x)")))
    assert any("not an earlier repeater" in p for p in problems)


def test_aggregate_over_non_numeric_column_is_blocked():
    problems = validate_form_doc(_doc(_repeater(), _computed("sum(lines.item)")))
    assert any("not a numeric column" in p for p in problems)


def test_aggregate_forward_ref_is_blocked():
    # computed BEFORE the repeater → repeater not yet "earlier".
    problems = validate_form_doc(_doc(_computed("sum(lines.qty)"), _repeater()))
    assert any("not an earlier repeater" in p for p in problems)
