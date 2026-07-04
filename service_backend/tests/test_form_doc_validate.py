"""Publish-gate (422) matrix for ``validate_form_doc`` (plan sprint-3/01 D9).

One assertion per rule mirrored from the client gate (``lib/form-doc.ts``):
duplicate/missing/bad keys, empty page, choice options, computed
forward-ref / non-numeric-ref / bad expression, condition forward-ref,
condition on a non-conditionable type, repeater dup sub-keys / min>max,
pattern invalid / missing message, plus the happy path → ``[]``.
"""

from app.form_engine.schemas import validate_form_doc

# ---- compact doc-builder helpers ----


def field(type_, key=None, **extra):
    f = {"id": f"fld_{key or type_}", "type": type_, "label": key or type_}
    if key is not None:
        f["key"] = key
    f.update(extra)
    return f


def section(*fields, sid="sec_1", **extra):
    return {"id": sid, "fields": list(fields), **extra}


def page(*sections, pid="pg_1", **extra):
    return {"id": pid, "sections": list(sections), **extra}


def doc(*pages):
    return {"schemaVersion": 1, "pages": list(pages)}


def cond(fact, operator="eq", value="x"):
    return {
        "kind": "group",
        "combinator": "and",
        "rules": [
            {"kind": "condition", "fact": fact, "operator": operator, "value": value}
        ],
    }


def choice(key="pick", items=None, type_="select"):
    if items is None:
        items = [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]
    return field(type_, key=key, options={"kind": "static", "items": items})


# ---- happy path ----


def test_valid_doc_has_no_problems():
    d = doc(page(section(field("text", key="name"), choice())))
    assert validate_form_doc(d) == []


# ---- pages ----


def test_no_pages_is_a_problem():
    assert validate_form_doc({"schemaVersion": 1, "pages": []})


def test_empty_page_is_a_problem():
    d = doc(page(section()))  # section with zero fields
    problems = validate_form_doc(d)
    assert any("empty" in p.lower() for p in problems)


# ---- keys ----


def test_missing_key_on_input_field():
    d = doc(page(section(field("text"))))  # no key
    problems = validate_form_doc(d)
    assert any("answer key" in p.lower() for p in problems)


def test_bad_key_chars():
    d = doc(page(section(field("text", key="bad-key!"))))
    problems = validate_form_doc(d)
    assert any("letters" in p.lower() for p in problems)


def test_duplicate_keys_across_doc():
    d = doc(
        page(
            section(field("text", key="dup"), sid="s1"),
            section(field("number", key="dup"), sid="s2"),
        )
    )
    problems = validate_form_doc(d)
    assert any("duplicate" in p.lower() for p in problems)


def test_display_field_needs_no_key():
    d = doc(page(section(field("heading"), field("text", key="name"))))
    assert validate_form_doc(d) == []


# ---- choice options ----


def test_choice_needs_at_least_one_option():
    d = doc(page(section(choice(items=[]))))
    problems = validate_form_doc(d)
    assert any("option" in p.lower() for p in problems)


def test_choice_blank_option_value():
    d = doc(page(section(choice(items=[{"value": "", "label": "blank"}]))))
    problems = validate_form_doc(d)
    assert any("without a value" in p.lower() for p in problems)


def test_choice_duplicate_option_values():
    items = [{"value": "x", "label": "A"}, {"value": "x", "label": "B"}]
    d = doc(page(section(choice(items=items))))
    problems = validate_form_doc(d)
    assert any("duplicate option" in p.lower() for p in problems)


# ---- rating ----


def test_rating_max_below_one():
    d = doc(page(section(field("rating", key="r", rating={"max": 0}))))
    problems = validate_form_doc(d)
    assert any("rating scale" in p.lower() for p in problems)


# ---- computed ----


def test_computed_forward_ref_is_a_problem():
    # `total` references `qty` which appears AFTER it → forward ref.
    d = doc(
        page(
            section(
                field("computed", key="total", computed={"expression": "qty * 2"}),
                field("number", key="qty"),
            )
        )
    )
    problems = validate_form_doc(d)
    assert any("not an earlier field" in p for p in problems)


def test_computed_ref_to_non_numeric_field():
    d = doc(
        page(
            section(
                field("text", key="name"),
                field("computed", key="c", computed={"expression": "name + 1"}),
            )
        )
    )
    problems = validate_form_doc(d)
    assert any("not numeric" in p.lower() for p in problems)


def test_computed_bad_expression():
    d = doc(page(section(field("computed", key="c", computed={"expression": "1 +"}))))
    problems = validate_form_doc(d)
    assert any("invalid expression" in p.lower() for p in problems)


def test_computed_missing_expression():
    d = doc(page(section(field("computed", key="c", computed={"expression": ""}))))
    problems = validate_form_doc(d)
    assert any("missing its expression" in p.lower() for p in problems)


def test_computed_valid_backward_ref():
    d = doc(
        page(
            section(
                field("number", key="qty"),
                field("number", key="price"),
                field("computed", key="t", computed={"expression": "qty * price"}),
            )
        )
    )
    assert validate_form_doc(d) == []


# ---- conditions ----


def test_condition_forward_ref_on_field():
    # `q1` condition references `q2` which is defined later.
    d = doc(
        page(
            section(
                field("text", key="q1", conditionsJson=cond("answers.q2")),
                field("text", key="q2"),
            )
        )
    )
    problems = validate_form_doc(d)
    assert any("not an earlier field" in p for p in problems)


def test_condition_backward_ref_ok():
    d = doc(
        page(
            section(
                field("yesno", key="agree"),
                field("text", key="why", conditionsJson=cond("answers.agree")),
            )
        )
    )
    assert validate_form_doc(d) == []


def test_section_condition_forward_ref():
    d = doc(
        page(
            section(field("text", key="q1"), sid="s1"),
            section(
                field("text", key="q2"),
                sid="s2",
                conditionsJson=cond("answers.q3"),  # q3 doesn't exist yet
            ),
        )
    )
    problems = validate_form_doc(d)
    assert any("section condition" in p.lower() for p in problems)


def test_condition_on_non_conditionable_type():
    # A condition referencing a `file` field's key: file is not conditionable,
    # so it never enters earlier_keys-as-conditionable → forward/unknown ref.
    d = doc(
        page(
            section(
                field("file", key="doc"),
                field("text", key="note", conditionsJson=cond("answers.doc")),
            )
        )
    )
    problems = validate_form_doc(d)
    # `doc` is a file field; conditioning on it is rejected (not a valid fact).
    assert problems  # at minimum, not publishable


# ---- repeater ----


def test_repeater_needs_a_sub_field():
    d = doc(page(section(field("repeater", key="rows", repeater={"fields": []}))))
    problems = validate_form_doc(d)
    assert any("sub-field" in p.lower() for p in problems)


def test_repeater_duplicate_sub_keys():
    subs = [
        {"id": "a", "type": "text", "key": "x", "label": "X"},
        {"id": "b", "type": "text", "key": "x", "label": "X2"},
    ]
    d = doc(page(section(field("repeater", key="rows", repeater={"fields": subs}))))
    problems = validate_form_doc(d)
    assert any("duplicate sub-field" in p.lower() for p in problems)


def test_repeater_min_greater_than_max():
    subs = [{"id": "a", "type": "text", "key": "x", "label": "X"}]
    d = doc(
        page(
            section(
                field(
                    "repeater",
                    key="rows",
                    repeater={"fields": subs, "minRows": 5, "maxRows": 2},
                )
            )
        )
    )
    problems = validate_form_doc(d)
    assert any("min rows greater" in p.lower() for p in problems)


# ---- text pattern ----


def test_pattern_without_message():
    d = doc(
        page(section(field("text", key="t", text={"pattern": "^[0-9]+$"})))
    )
    problems = validate_form_doc(d)
    assert any("message for its pattern" in p.lower() for p in problems)


def test_pattern_invalid_regex():
    d = doc(
        page(
            section(
                field(
                    "text",
                    key="t",
                    text={"pattern": "([0-9]+", "patternMessage": "digits"},
                )
            )
        )
    )
    problems = validate_form_doc(d)
    assert any("invalid pattern" in p.lower() for p in problems)


def test_pattern_valid_with_message():
    d = doc(
        page(
            section(
                field(
                    "text",
                    key="t",
                    text={"pattern": "^[0-9]+$", "patternMessage": "Digits only"},
                )
            )
        )
    )
    assert validate_form_doc(d) == []


# ---- unknown keys forbidden (forever-contract) ----


def test_unknown_field_key_is_rejected():
    d = doc(page(section(field("text", key="t", bogus="nope"))))
    problems = validate_form_doc(d)
    assert any("malformed" in p.lower() for p in problems)
