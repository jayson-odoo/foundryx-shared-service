"""Submit pipeline matrix for ``validate_submission`` (plan sprint-3/01 D14).

Covers: hidden-field dropping (no error), required-if-visible, the per-type
constraint matrix (pass + fail per type), options membership, computed
recompute (client value ignored), repeater row-keyed errors + min/max rows,
address whitelist (extra key DROPPED), unknown-key dropping, multiselect
duplicate rejection.
"""

from app.form_engine.validation import validate_submission

# ---- compact doc-builder helpers ----


def field(type_, key=None, **extra):
    f = {"id": f"fld_{key or type_}", "type": type_, "label": key or type_}
    if key is not None:
        f["key"] = key
    f.update(extra)
    return f


def section(*fields, sid="sec_1", **extra):
    return {"id": sid, "fields": list(fields), **extra}


def doc(*fields, **section_extra):
    return {
        "schemaVersion": 1,
        "pages": [{"id": "pg_1", "sections": [section(*fields, **section_extra)]}],
    }


def two_section_doc(s1_fields, s2_fields, s2_extra=None):
    return {
        "schemaVersion": 1,
        "pages": [
            {
                "id": "pg_1",
                "sections": [
                    section(*s1_fields, sid="s1"),
                    section(*s2_fields, sid="s2", **(s2_extra or {})),
                ],
            }
        ],
    }


def cond(fact, value):
    return {
        "kind": "group",
        "combinator": "and",
        "rules": [
            {"kind": "condition", "fact": fact, "operator": "is_true", "value": value}
        ],
    }


def cond_eq(fact, value):
    return {
        "kind": "group",
        "combinator": "and",
        "rules": [
            {"kind": "condition", "fact": fact, "operator": "eq", "value": value}
        ],
    }


def opts(*values):
    return {"kind": "static", "items": [{"value": v, "label": v.upper()} for v in values]}


# ---- visibility & required-if-visible ----


def test_hidden_field_answer_is_dropped_no_error():
    # `why` is visible only when `agree` is true. Submit agree=False but still
    # send a `why` answer - it must be dropped, and no required error fires.
    d = two_section_doc(
        [field("yesno", key="agree")],
        [field("text", key="why", required=True, conditionsJson=cond("answers.agree", True))],
    )
    clean, errors = validate_submission(d, {"agree": False, "why": "leftover"})
    assert "why" not in clean
    assert errors == {}


def test_visible_required_field_missing_is_error():
    d = two_section_doc(
        [field("yesno", key="agree")],
        [field("text", key="why", required=True, conditionsJson=cond("answers.agree", True))],
    )
    clean, errors = validate_submission(d, {"agree": True})
    assert errors == {"why": "This field is required."}


def test_hidden_required_field_not_an_error():
    d = doc(
        field("yesno", key="agree"),
        field("text", key="why", required=True, conditionsJson=cond("answers.agree", True)),
    )
    _clean, errors = validate_submission(d, {"agree": False})
    assert errors == {}


# ---- text family ----


def test_text_min_max_length():
    d = doc(field("text", key="t", text={"minLength": 3, "maxLength": 5}))
    assert validate_submission(d, {"t": "abcd"})[1] == {}
    assert "t" in validate_submission(d, {"t": "ab"})[1]
    assert "t" in validate_submission(d, {"t": "abcdef"})[1]


def test_text_pattern_search_semantics():
    # JS .test() = search (not fullmatch): "abc123" contains digits → passes.
    d = doc(field("text", key="t", text={"pattern": "[0-9]+", "patternMessage": "need a digit"}))
    assert validate_submission(d, {"t": "abc123"})[1] == {}
    errors = validate_submission(d, {"t": "abc"})[1]
    assert errors.get("t") == "need a digit"


def test_email_pass_fail():
    d = doc(field("email", key="e"))
    assert validate_submission(d, {"e": "a@b.co"})[1] == {}
    assert "e" in validate_submission(d, {"e": "nope"})[1]


def test_url_pass_fail():
    d = doc(field("url", key="u"))
    assert validate_submission(d, {"u": "https://x.com/path"})[1] == {}
    assert "u" in validate_submission(d, {"u": "ftp://x.com"})[1]
    assert "u" in validate_submission(d, {"u": "notaurl"})[1]


def test_phone_pass_fail():
    d = doc(field("phone", key="p"))
    assert validate_submission(d, {"p": "+1 (555) 123-4567"})[1] == {}
    assert "p" in validate_submission(d, {"p": "abc"})[1]
    assert "p" in validate_submission(d, {"p": "123"})[1]  # too short


# ---- number ----


def test_number_pass_fail_and_coerce_string():
    d = doc(field("number", key="n", number={"min": 0, "max": 10, "step": 2}))
    assert validate_submission(d, {"n": 4})[1] == {}
    assert validate_submission(d, {"n": "4"})[1] == {}  # numeric string coerced
    assert "n" in validate_submission(d, {"n": 11})[1]  # > max
    assert "n" in validate_submission(d, {"n": 3})[1]  # off-step
    assert "n" in validate_submission(d, {"n": "x"})[1]  # not a number


# ---- choice membership ----


def test_select_membership():
    d = doc(field("select", key="s", options=opts("a", "b")))
    assert validate_submission(d, {"s": "a"})[1] == {}
    assert "s" in validate_submission(d, {"s": "z"})[1]


def test_multiselect_membership_and_duplicate():
    d = doc(field("multiselect", key="m", options=opts("a", "b", "c")))
    assert validate_submission(d, {"m": ["a", "c"]})[1] == {}
    assert "m" in validate_submission(d, {"m": ["a", "z"]})[1]  # bad member
    assert "m" in validate_submission(d, {"m": ["a", "a"]})[1]  # duplicate


# ---- yesno / date / datetime / rating ----


def test_yesno_must_be_boolean():
    d = doc(field("yesno", key="y"))
    assert validate_submission(d, {"y": True})[1] == {}
    assert "y" in validate_submission(d, {"y": "true"})[1]


def test_date_pass_fail():
    d = doc(field("date", key="d"))
    assert validate_submission(d, {"d": "2026-06-10"})[1] == {}
    assert "d" in validate_submission(d, {"d": "06/10/2026"})[1]
    assert "d" in validate_submission(d, {"d": "2026-13-99"})[1]


def test_datetime_pass_fail():
    d = doc(field("datetime", key="dt"))
    assert validate_submission(d, {"dt": "2026-06-10T14:30:00"})[1] == {}
    assert validate_submission(d, {"dt": "2026-06-10T14:30:00Z"})[1] == {}
    assert "dt" in validate_submission(d, {"dt": "not-a-time"})[1]


def test_rating_pass_fail():
    d = doc(field("rating", key="r", rating={"max": 5}))
    assert validate_submission(d, {"r": 3})[1] == {}
    assert "r" in validate_submission(d, {"r": 6})[1]
    assert "r" in validate_submission(d, {"r": 0})[1]


# ---- signature ----


def test_signature_accepts_any_nonempty_str():
    d = doc(field("signature", key="sig", required=True))
    assert validate_submission(d, {"sig": "data:image/png;base64,AAAA"})[1] == {}
    assert "sig" in validate_submission(d, {"sig": ""})[1]


# ---- address whitelist ----


def test_address_extra_key_dropped_and_required():
    d = doc(field("address", key="addr", required=True))
    answer = {
        "line1": "1 Main St",
        "city": "Town",
        "country": "US",
        "evil": "DROP ME",
    }
    clean, errors = validate_submission(d, {"addr": answer})
    assert errors == {}
    assert "evil" not in clean["addr"]  # whitelist drops the extra key
    assert clean["addr"]["line1"] == "1 Main St"


def test_address_missing_required_lines():
    d = doc(field("address", key="addr", required=True))
    _clean, errors = validate_submission(d, {"addr": {"city": "Town"}})
    assert "addr" in errors  # line1/country missing


def test_address_empty_when_not_required():
    d = doc(field("address", key="addr"))
    _clean, errors = validate_submission(d, {"addr": {}})
    assert errors == {}


# ---- file ----


def test_file_shape_and_maxcount():
    d = doc(field("file", key="f", required=True, file={"maxCount": 1}))
    one = [{"key": "k1", "name": "a.pdf", "size": 10, "mime": "application/pdf"}]
    two = one + [{"key": "k2", "name": "b.pdf", "size": 10, "mime": "application/pdf"}]
    assert validate_submission(d, {"f": one})[1] == {}
    assert "f" in validate_submission(d, {"f": two})[1]  # over maxCount
    assert "f" in validate_submission(d, {"f": []})[1]  # required, empty


# ---- computed recompute ----


def test_computed_recompute_ignores_client_value():
    d = doc(
        field("number", key="qty"),
        field("number", key="price"),
        field("computed", key="total", computed={"expression": "qty * price"}),
    )
    # Client lies: sends total=999; server recomputes 10 * 100 = 1000.
    clean, errors = validate_submission(d, {"qty": 10, "price": 100, "total": 999})
    assert errors == {}
    assert clean["total"] == 1000


def test_computed_none_when_inputs_missing():
    d = doc(
        field("number", key="qty"),
        field("computed", key="total", computed={"expression": "qty * 2"}),
    )
    clean, _errors = validate_submission(d, {})
    assert clean["total"] is None


def test_non_finite_number_rejected():
    # inf/nan would serialize as invalid JSON and 500 the insert (code-review).
    d = doc(field("number", key="n"))
    _clean, errors = validate_submission(d, {"n": "1e400"})  # overflows to inf
    assert "n" in errors


def test_computed_overflow_is_none_not_inf():
    d = doc(
        field("number", key="a"),
        field("number", key="b"),
        field("computed", key="c", computed={"expression": "a * b"}),
    )
    # a*b overflows to inf - must fail closed to None, never store inf.
    clean, _errors = validate_submission(d, {"a": 1e308, "b": 1e308})
    assert clean["c"] is None


def test_select_answer_coerced_to_string_option_value():
    d = doc(
        field(
            "select",
            key="pick",
            options={"kind": "static", "items": [{"value": "0", "label": "Zero"}]},
        )
    )
    # Client sends the numeric 0; option value is the string "0".
    clean, errors = validate_submission(d, {"pick": 0})
    assert errors == {}
    assert clean["pick"] == "0"  # stored as the string option value


def test_hidden_field_value_cannot_drive_downstream_visibility():
    # A curl client force-feeds a HIDDEN field's value to try to reveal a
    # later field. The hidden value must NOT count as a fact (D14): the
    # downstream field stays hidden + dropped.
    cond = {
        "kind": "group",
        "combinator": "and",
        "rules": [
            {"kind": "condition", "fact": "answers.gate", "operator": "is_true", "valueKind": "literal", "value": None}
        ],
    }
    never = {
        "kind": "group",
        "combinator": "and",
        "rules": [
            {"kind": "condition", "fact": "answers.never", "operator": "is_true", "valueKind": "literal", "value": None}
        ],
    }
    d = {
        "schemaVersion": 1,
        "pages": [
            {
                "id": "pg_1",
                "sections": [
                    {
                        "id": "sec_1",
                        "fields": [
                            # `never` is always-false (no `never` answer) → gate hidden+dropped.
                            field("yesno", key="gate", conditionsJson=never),
                            field("text", key="secret", conditionsJson=cond),
                        ],
                    }
                ],
            }
        ],
    }
    clean, errors = validate_submission(d, {"gate": True, "secret": "leak"})
    assert "gate" not in clean  # hidden → dropped
    assert "secret" not in clean  # its gate fact is absent → stays hidden
    assert errors == {}


# ---- repeater ----


def test_repeater_row_errors_keyed_by_index_subkey():
    subs = [
        {"id": "a", "type": "text", "key": "name", "label": "Name", "required": True},
        {"id": "b", "type": "number", "key": "qty", "label": "Qty"},
    ]
    d = doc(field("repeater", key="rows", repeater={"fields": subs}))
    rows = [
        {"name": "ok", "qty": 5},
        {"name": "", "qty": "bad"},  # row 1: name required, qty not numeric
    ]
    _clean, errors = validate_submission(d, {"rows": rows})
    assert errors.get("rows.1.name") == "This field is required."
    assert "rows.1.qty" in errors


def test_repeater_min_max_rows():
    subs = [{"id": "a", "type": "text", "key": "x", "label": "X"}]
    d = doc(field("repeater", key="rows", repeater={"fields": subs, "minRows": 2, "maxRows": 3}))
    assert "rows" in validate_submission(d, {"rows": [{"x": "1"}]})[1]  # too few
    over = [{"x": str(i)} for i in range(4)]
    assert "rows" in validate_submission(d, {"rows": over})[1]  # too many
    assert validate_submission(d, {"rows": [{"x": "1"}, {"x": "2"}]})[1] == {}


def test_repeater_drops_undeclared_subkeys():
    subs = [{"id": "a", "type": "text", "key": "x", "label": "X"}]
    d = doc(field("repeater", key="rows", repeater={"fields": subs}))
    clean, errors = validate_submission(d, {"rows": [{"x": "ok", "junk": "DROP"}]})
    assert errors == {}
    assert clean["rows"] == [{"x": "ok"}]


# ---- unknown keys ----


def test_unknown_answer_key_dropped():
    d = doc(field("text", key="name"))
    clean, errors = validate_submission(d, {"name": "Jay", "ghost": "boo"})
    assert errors == {}
    assert clean == {"name": "Jay"}


# ---- enum-conditioned visibility (eq operator) ----


def test_enum_condition_controls_visibility():
    d = two_section_doc(
        [field("select", key="kind", options=opts("a", "b"))],
        [field("text", key="detail", required=True, conditionsJson=cond_eq("answers.kind", "a"))],
    )
    # kind=b → detail hidden, no error
    _c1, e1 = validate_submission(d, {"kind": "b"})
    assert e1 == {}
    # kind=a → detail visible & required → error
    _c2, e2 = validate_submission(d, {"kind": "a"})
    assert "detail" in e2
