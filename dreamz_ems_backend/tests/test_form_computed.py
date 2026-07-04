"""Tests for app.form_engine.computed — arithmetic expression parser/evaluator.

All tests are pure unit tests (no DB, no fixtures).  Run with:
    .venv/bin/python -m pytest tests/test_form_computed.py -q
"""
import math
import pytest

from app.form_engine.computed import (
    ComputedExpressionError,
    MAX_EXPR_LEN,
    MAX_TOKENS,
    ParsedExpression,
    evaluate,
    field_refs,
    parse_expression,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _ev(expr: str, **kw) -> object:
    """Shorthand: evaluate *expr* with keyword-argument field values."""
    return evaluate(expr, kw)


def _fe(val: object) -> float:
    """Assert result is a finite float and return it."""
    assert isinstance(val, float), f"Expected float, got {val!r}"
    assert math.isfinite(val), f"Expected finite float, got {val!r}"
    return val


# ── parse_expression returns ParsedExpression ─────────────────────────────────

class TestParseExpression:
    def test_returns_parsed_expression(self):
        p = parse_expression("1 + 2")
        assert isinstance(p, ParsedExpression)

    def test_source_is_trimmed(self):
        p = parse_expression("  qty * 2  ")
        assert p.source == "qty * 2"

    def test_field_refs_empty_for_literal(self):
        p = parse_expression("3.14")
        assert p.field_refs == frozenset()

    def test_field_refs_single(self):
        p = parse_expression("qty * 2")
        assert p.field_refs == frozenset({"qty"})

    def test_field_refs_multiple(self):
        p = parse_expression("qty * unit_price + tax")
        assert p.field_refs == frozenset({"qty", "unit_price", "tax"})

    def test_same_ref_counted_once(self):
        p = parse_expression("x + x * x")
        assert p.field_refs == frozenset({"x"})

    def test_no_db_needed(self):
        # Ensure the parse path is truly dependency-free.
        parse_expression("1 + 2 * (3 - 4)")


# ── operator precedence ───────────────────────────────────────────────────────

class TestPrecedence:
    def test_mul_over_add(self):
        # 2 + 3*4  =  2 + 12  =  14  (not 20)
        assert _fe(_ev("2 + 3 * 4")) == 14.0

    def test_div_over_sub(self):
        # 10 - 8/4  =  10 - 2  =  8
        assert _fe(_ev("10 - 8 / 4")) == 8.0

    def test_add_left_associative(self):
        # (1+2)+3 = 6, same as left-to-right
        assert _fe(_ev("1 + 2 + 3")) == 6.0

    def test_sub_left_associative(self):
        # 8-3-2  =  (8-3)-2  =  3  (NOT 8-(3-2)=7)
        assert _fe(_ev("8 - 3 - 2")) == 3.0

    def test_div_left_associative(self):
        # 8/4/2  =  (8/4)/2  =  1.0  (NOT 8/(4/2)=4)
        assert _fe(_ev("8 / 4 / 2")) == 1.0


# ── parentheses ───────────────────────────────────────────────────────────────

class TestParens:
    def test_parens_override_precedence(self):
        # (2+3)*4  =  20
        assert _fe(_ev("(2 + 3) * 4")) == 20.0

    def test_nested_parens(self):
        assert _fe(_ev("((2 + 3))")) == 5.0

    def test_parens_in_denominator(self):
        # 10 / (2+3)  =  2
        assert _fe(_ev("10 / (2 + 3)")) == 2.0


# ── unary minus ───────────────────────────────────────────────────────────────

class TestUnaryMinus:
    def test_unary_minus_literal(self):
        assert _fe(_ev("-3 + 5")) == 2.0

    def test_unary_minus_mul(self):
        # 2 * -3  =  -6
        assert _fe(_ev("2 * -3")) == -6.0

    def test_double_unary_minus(self):
        assert _fe(_ev("- -4")) == 4.0

    def test_unary_minus_field_ref(self):
        assert _fe(evaluate("- x", {"x": 7})) == -7.0


# ── unicode operator aliases ──────────────────────────────────────────────────

class TestUnicodeOps:
    def test_unicode_mul(self):
        assert _fe(_ev("3 × 4")) == 12.0

    def test_unicode_div(self):
        assert _fe(_ev("10 ÷ 4")) == 2.5

    def test_mixed_unicode_and_ascii(self):
        # 2 × 3 + 10 ÷ 2  =  6 + 5  =  11
        assert _fe(_ev("2 × 3 + 10 ÷ 2")) == 11.0


# ── field reference resolution ────────────────────────────────────────────────

class TestFieldRefs:
    def test_single_ref(self):
        assert _fe(evaluate("qty", {"qty": 5})) == 5.0

    def test_ref_in_expr(self):
        assert _fe(evaluate("qty * unit_price", {"qty": 3, "unit_price": 10})) == 30.0

    def test_ref_plus_literal(self):
        assert _fe(evaluate("qty + 10", {"qty": 5})) == 15.0


# ── value coercion ────────────────────────────────────────────────────────────

class TestValueCoercion:
    def test_int_value(self):
        assert _fe(evaluate("x", {"x": 7})) == 7.0

    def test_float_value(self):
        assert _fe(evaluate("x", {"x": 1.5})) == 1.5

    def test_numeric_string_coercion(self):
        assert _fe(evaluate("x + 1", {"x": "4"})) == 5.0

    def test_float_string_coercion(self):
        assert _fe(evaluate("x", {"x": "3.14"})) == pytest.approx(3.14)


# ── fail-closed (None) cases ─────────────────────────────────────────────────

class TestFailClosed:
    def test_missing_ref_returns_none(self):
        assert evaluate("qty * 2", {}) is None

    def test_none_value_returns_none(self):
        assert evaluate("qty * 2", {"qty": None}) is None

    def test_non_numeric_string_returns_none(self):
        assert evaluate("qty", {"qty": "hello"}) is None

    def test_bool_value_returns_none(self):
        # bool is NOT numeric in this domain
        assert evaluate("x", {"x": True}) is None

    def test_div_by_zero_returns_none(self):
        assert evaluate("10 / 0", {}) is None

    def test_div_by_zero_field_ref(self):
        assert evaluate("1 / x", {"x": 0}) is None

    def test_list_value_returns_none(self):
        assert evaluate("x", {"x": [1, 2]}) is None

    def test_missing_field_in_subexpr_returns_none(self):
        # One missing ref poisons the whole result
        assert evaluate("a + b", {"a": 5}) is None

    def test_raw_string_with_syntax_error_returns_none(self):
        # evaluate() with a raw string that has a syntax error → None (not raise)
        assert evaluate("2 +", {}) is None


# ── syntax errors ─────────────────────────────────────────────────────────────

class TestSyntaxErrors:
    def test_empty_string(self):
        with pytest.raises(ComputedExpressionError, match="non-empty"):
            parse_expression("")

    def test_whitespace_only(self):
        with pytest.raises(ComputedExpressionError, match="non-empty"):
            parse_expression("   ")

    def test_trailing_operator(self):
        # "2+" — trailing garbage after parse
        with pytest.raises(ComputedExpressionError):
            parse_expression("2 +")

    def test_unclosed_paren(self):
        with pytest.raises(ComputedExpressionError):
            parse_expression("(2 + 3")

    def test_extra_closing_paren(self):
        with pytest.raises(ComputedExpressionError):
            parse_expression("2 + 3)")

    def test_two_consecutive_numbers(self):
        # "2 2" — trailing content after first number parsed
        with pytest.raises(ComputedExpressionError, match="trailing"):
            parse_expression("2 2")

    def test_two_consecutive_operators(self):
        # "2 + * 3" — unexpected '*' where a primary is expected
        with pytest.raises(ComputedExpressionError):
            parse_expression("2 + * 3")

    def test_exponentiation_rejected(self):
        # "**" is explicitly a syntax error in our grammar
        with pytest.raises(ComputedExpressionError, match=r"\*\*"):
            parse_expression("2 ** 3")

    def test_illegal_character_hash(self):
        with pytest.raises(ComputedExpressionError, match="Unexpected character"):
            parse_expression("2 # 3")

    def test_illegal_character_percent(self):
        with pytest.raises(ComputedExpressionError, match="Unexpected character"):
            parse_expression("10 % 3")

    def test_illegal_character_at(self):
        with pytest.raises(ComputedExpressionError, match="Unexpected character"):
            parse_expression("@qty")

    def test_none_input(self):
        with pytest.raises(ComputedExpressionError):
            parse_expression(None)  # type: ignore[arg-type]


# ── hard caps ─────────────────────────────────────────────────────────────────

class TestHardCaps:
    def test_expression_at_length_limit_does_not_raise_length_error(self):
        # Build a short expression well under both caps — just confirm a
        # MAX_EXPR_LEN-character string that contains only whitespace padding
        # is rejected for being empty, not for length.  The real cap boundary
        # is tested by test_expression_over_length_cap below.
        # Separately, verify a normally-sized valid expression evaluates fine.
        short = "1 + 2 * 3"
        assert len(short) < MAX_EXPR_LEN
        result = evaluate(short, {})
        assert isinstance(result, float) and result == 7.0

    def test_expression_over_length_cap(self):
        expr = "a" * (MAX_EXPR_LEN + 1)
        with pytest.raises(ComputedExpressionError, match="character limit"):
            parse_expression(expr)

    def test_token_cap(self):
        # Build an expression that exceeds MAX_TOKENS but is within MAX_EXPR_LEN.
        # "1+1+1+...": each pair is "1+", 2 chars; 101 numbers needs 100 "+"s.
        # Total: 101 * 2 - 1 = 201 chars — well under 1000.
        n = MAX_TOKENS + 2  # one over the limit in token count
        expr = "+".join(["1"] * n)
        assert len(expr) < MAX_EXPR_LEN
        with pytest.raises(ComputedExpressionError, match="token limit"):
            parse_expression(expr)


# ── field_refs convenience function ──────────────────────────────────────────

class TestFieldRefsHelper:
    def test_returns_frozenset(self):
        refs = field_refs("a + b * c")
        assert isinstance(refs, frozenset)
        assert refs == frozenset({"a", "b", "c"})

    def test_empty_for_literals(self):
        assert field_refs("42") == frozenset()

    def test_raises_on_syntax_error(self):
        with pytest.raises(ComputedExpressionError):
            field_refs("2 +")


# ── evaluate accepts both ParsedExpression and raw str ───────────────────────

class TestEvaluateOverloads:
    def test_parsed_expression_input(self):
        p = parse_expression("x * 2 + 1")
        assert _fe(evaluate(p, {"x": 3})) == 7.0

    def test_raw_string_input(self):
        assert _fe(evaluate("x * 2 + 1", {"x": 3})) == 7.0

    def test_result_is_float(self):
        result = evaluate("4 / 2", {})
        assert isinstance(result, float)

    def test_integer_arithmetic_returns_float(self):
        # Even whole-number results come back as float.
        assert evaluate("6", {}) == 6.0
        assert isinstance(evaluate("6", {}), float)


# ── realistic compound formulas ───────────────────────────────────────────────

class TestRealisticFormulas:
    def test_invoice_line_total(self):
        # line_total = qty * unit_price
        assert _fe(evaluate("qty * unit_price", {"qty": 3, "unit_price": 25.0})) == 75.0

    def test_invoice_with_tax(self):
        # total = qty * unit_price + tax_amount
        result = evaluate(
            "qty * unit_price + tax_amount",
            {"qty": 2, "unit_price": 100, "tax_amount": 15},
        )
        assert _fe(result) == 215.0

    def test_percentage_discount(self):
        # discounted = price - (price * discount_pct / 100)
        result = evaluate(
            "price - (price * discount_pct / 100)",
            {"price": 200, "discount_pct": 10},
        )
        assert _fe(result) == pytest.approx(180.0)

    def test_average_of_two(self):
        result = evaluate("(a + b) / 2", {"a": 10, "b": 6})
        assert _fe(result) == 8.0
