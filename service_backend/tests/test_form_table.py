"""Table block tests (sprint-3/02) - publish gate + submit pipeline.

Covers: publish gate (columns non-empty, unique keys, computed col refs earlier
numeric col, forward-ref blocked); submit recomputes computed columns
server-side per row (client value ignored); column-key whitelist; required-cell
422; a form-level `sum(table.amount)` aggregate over the table.
"""
from app.form_engine.schemas import validate_form_doc
from app.form_engine.validation import validate_submission


def _doc(*fields):
    return {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "title": "P", "sections": [{"id": "s1", "fields": list(fields)}]}],
    }


def _table(key="po_lines", **table):
    cols = table.pop("columns", None) or [
        {"id": "c1", "type": "text", "key": "item", "label": "Item", "required": True},
        {"id": "c2", "type": "number", "key": "qty", "label": "Qty", "required": True},
        {"id": "c3", "type": "number", "key": "unit_price", "label": "Unit Price"},
        {
            "id": "c4", "type": "computed", "key": "amount", "label": "Amount",
            "computed": {"expression": "qty * unit_price"}, "summarize": "sum",
        },
    ]
    return {"id": "t1", "type": "table", "key": key, "label": "PO Lines", "table": {"columns": cols, **table}}


# ---- publish gate ----


def test_valid_table_publishes():
    assert validate_form_doc(_doc(_table())) == []


def test_table_needs_columns():
    problems = validate_form_doc(_doc({"id": "t1", "type": "table", "key": "t", "label": "T", "table": {"columns": []}}))
    assert any("at least one column" in p for p in problems)


def test_table_duplicate_column_keys_blocked():
    cols = [
        {"id": "c1", "type": "text", "key": "dup", "label": "A"},
        {"id": "c2", "type": "number", "key": "dup", "label": "B"},
    ]
    problems = validate_form_doc(_doc(_table(columns=cols)))
    assert any("duplicate column keys" in p for p in problems)


def test_computed_column_forward_ref_blocked():
    # amount references qty which comes AFTER it → not an earlier column.
    cols = [
        {"id": "c1", "type": "computed", "key": "amount", "label": "Amount", "computed": {"expression": "qty"}},
        {"id": "c2", "type": "number", "key": "qty", "label": "Qty"},
    ]
    problems = validate_form_doc(_doc(_table(columns=cols)))
    assert any("not an earlier numeric column" in p for p in problems)


# ---- submit ----


def test_submit_recomputes_computed_columns_server_side():
    doc = _doc(_table())
    answers = {
        "po_lines": [
            {"item": "Tesla", "qty": 5, "unit_price": 10, "amount": 9999},  # client amount is a LIE
            {"item": "Rivian", "qty": "2", "unit_price": "3"},
        ]
    }
    clean, errors = validate_submission(doc, answers)
    assert errors == {}
    rows = clean["po_lines"]
    assert rows[0]["amount"] == 50  # server recomputed, client 9999 ignored
    assert rows[1]["amount"] == 6


def test_submit_drops_undeclared_keys():
    doc = _doc(_table())
    answers = {"po_lines": [{"item": "X", "qty": 1, "unit_price": 1, "junk": "evil"}]}
    clean, _ = validate_submission(doc, answers)
    assert "junk" not in clean["po_lines"][0]


def test_required_cell_422():
    doc = _doc(_table())
    answers = {"po_lines": [{"item": "", "qty": 5, "unit_price": 2}]}  # item required, blank
    _clean, errors = validate_submission(doc, answers)
    assert "po_lines.0.item" in errors


def test_form_level_aggregate_over_table():
    grand = {"id": "g1", "type": "computed", "key": "grand", "label": "Grand", "computed": {"expression": "sum(po_lines.amount)"}}
    doc = _doc(_table(), grand)
    # publish-gate accepts the aggregate over the table column
    assert validate_form_doc(doc) == []
    answers = {"po_lines": [{"item": "A", "qty": 2, "unit_price": 3}, {"item": "B", "qty": 4, "unit_price": 5}]}
    clean, errors = validate_submission(doc, answers)
    assert errors == {}
    assert clean["grand"] == 26  # (2*3) + (4*5)


# ---- fixed-value column (F2) + decimals ----


def test_fixed_column_is_stamped_server_side_and_feeds_computed():
    cols = [
        {"id": "c1", "type": "number", "key": "qty", "label": "Qty", "required": True},
        {"id": "c2", "type": "fixed", "key": "tax_rate", "label": "Tax", "fixedValue": "0.06"},
        {
            "id": "c3", "type": "computed", "key": "tax", "label": "Tax amt",
            "computed": {"expression": "qty * tax_rate"}, "summarize": "sum",
        },
    ]
    doc = _doc(_table(columns=cols))
    # publish-gate: computed may reference the fixed numeric column
    assert validate_form_doc(doc) == []
    answers = {"po_lines": [{"qty": 10, "tax_rate": "999"}]}  # client tax_rate is a LIE
    clean, errors = validate_submission(doc, answers)
    assert errors == {}
    row = clean["po_lines"][0]
    assert row["tax_rate"] == "0.06"  # server-stamped constant, client 999 ignored
    assert row["tax"] == 0.6  # 10 * 0.06


def test_decimal_places_and_integer_enforced():
    cols = [
        {"id": "c1", "type": "number", "key": "price", "label": "Price", "decimals": 2},
        {"id": "c2", "type": "number", "key": "age", "label": "Age", "integer": True},
    ]
    doc = _doc(_table(columns=cols))
    # too many decimals on price + a fraction on the integer column
    _clean, errors = validate_submission(doc, {"po_lines": [{"price": "1.234", "age": "2.5"}]})
    assert "po_lines.0.price" in errors and "decimal" in errors["po_lines.0.price"].lower()
    assert "po_lines.0.age" in errors and "whole" in errors["po_lines.0.age"].lower()
    # within precision → clean
    _clean2, errors2 = validate_submission(doc, {"po_lines": [{"price": "1.23", "age": "30"}]})
    assert errors2 == {}


def test_integer_field_type_rejects_fraction():
    from app.form_engine.validation import validate_submission as vs
    field = {"id": "f1", "type": "integer", "key": "age", "label": "Age", "required": True}
    doc = {"schemaVersion": 1, "pages": [{"id": "p1", "title": "P", "sections": [{"id": "s1", "fields": [field]}]}]}
    _c, errors = vs(doc, {"age": "2.5"})
    assert "age" in errors and "whole" in errors["age"].lower()
    _c2, errors2 = vs(doc, {"age": "30"})
    assert errors2 == {}


def test_integer_column_type_rejects_fraction():
    cols = [{"id": "c1", "type": "integer", "key": "qty", "label": "Qty"}]
    doc = _doc(_table(columns=cols))
    _c, errors = validate_submission(doc, {"po_lines": [{"qty": "1.5"}]})
    assert "po_lines.0.qty" in errors


def test_decimals_reject_scientific_notation():
    # 1e-07 has 7 decimal places - must NOT slip past a string-digit count.
    from app.form_engine.validation import _decimal_places, _number_kind_error
    assert _decimal_places("1e-07") == 7
    assert _decimal_places(0.0000001) == 7
    assert _number_kind_error("1e-07", 1e-07, integer=False, decimals=2) is not None
    assert _number_kind_error("1.23", 1.23, integer=False, decimals=2) is None
