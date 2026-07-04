"""Arithmetic expression parser and evaluator for computed form fields (sprint-3/01 D7).

Security rationale
------------------
Tenant-authored expressions run inside the platform on user-supplied field data.
We must NEVER use Python ``eval``/``exec``/``ast.literal_eval`` on expression
strings, and NEVER pass them through Jinja2 or any general-purpose template
engine — any of these paths would open an SSTI → RCE vector.

Instead, we ship our own minimal recursive-descent parser for a deliberately
tiny grammar:  numbers, field references, the four arithmetic operators
(``+ - * /``), unary minus, and parentheses.  Nothing else is accepted.  The
parser rejects the expression with ``ComputedExpressionError`` at parse time
(before any data touches it), so a mis-configured formula never silently
produces wrong output at runtime.

At *evaluate* time the evaluator is fail-closed: a missing field, a None value,
a non-numeric value, or a division by zero all produce ``None`` — never an
exception and never a crash in the calling request.

Grammar (EBNF)
--------------
    expr        = term  (( '+' | '-' )  term)*
    term        = unary (( '*' | '/' | '×' | '÷' )  unary)*
    unary       = '-' unary | primary
    primary     = NUMBER | IDENT | '(' expr ')'
    NUMBER      = [0-9]+ ('.' [0-9]+)?
    IDENT       = [a-zA-Z_] [a-zA-Z0-9_]*

Hard caps
---------
- ``MAX_EXPR_LEN``  = 1000 characters — reject longer strings at parse entry.
- ``MAX_TOKENS``    = 100  — reject after tokenisation (DoS guard).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple, Union

# ── hard caps ────────────────────────────────────────────────────────────────
MAX_EXPR_LEN: int = 1000
MAX_TOKENS: int = 100

# ── token kinds ──────────────────────────────────────────────────────────────
_TK_NUMBER = "NUMBER"
_TK_IDENT = "IDENT"
_TK_PLUS = "+"
_TK_MINUS = "-"
_TK_STAR = "*"
_TK_SLASH = "/"
_TK_LPAREN = "("
_TK_RPAREN = ")"
_TK_EOF = "EOF"

# Accept ASCII * / and their unicode aliases × ÷ (D plan requirement).
_UNICODE_MUL = "×"
_UNICODE_DIV = "÷"

# Compiled tokeniser pattern — order matters (longer matches first). IDENT may
# carry ONE dotted segment (`repeater.subKey`) so an aggregate argument is a
# single token (sprint-3/02 follow-up — repeater column aggregates).
_TOKEN_RE = re.compile(
    r"(?P<NUMBER>[0-9]+(?:\.[0-9]+)?)"
    r"|(?P<IDENT>[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)"
    r"|(?P<OP>[+\-*/×÷()])"
    r"|(?P<WS>\s+)"
    r"|(?P<BAD>.)"  # catch-all for illegal chars
)

# Whitelisted aggregate functions over a repeater column (sprint-3/02 follow-up):
# `sum/avg/min/max(repeaterKey.subKey)` and `count(repeaterKey)`.
AGGREGATE_FUNCS: FrozenSet[str] = frozenset({"sum", "avg", "count", "min", "max"})


class ComputedExpressionError(ValueError):
    """Raised on any parse-time syntax or safety error.

    A ``ValueError`` subclass so callers that want to map it to a 422 can do
    ``except (ValueError, ComputedExpressionError)`` without an extra import.
    """


# ── Token dataclass ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    value: str  # raw text from the source


# ── ParsedExpression (public) ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedExpression:
    """The result of a successful ``parse_expression`` call.

    Attributes
    ----------
    source:
        Original expression string (trimmed).
    field_refs:
        Frozen set of field keys referenced by the expression.  Used at form
        publish time to validate that all refs point at real numeric fields.
    _ast:
        Internal AST node — an implementation detail; callers should use
        :func:`evaluate` rather than inspecting this directly.
    """

    source: str
    field_refs: FrozenSet[str]
    aggregates: Tuple[AggregateRef, ...] = ()
    _ast: object = field(default=None, repr=False, compare=False)  # _ASTNode


# ── internal AST node types (not exported) ────────────────────────────────────


@dataclass(slots=True)
class _Num:
    value: float


@dataclass(slots=True)
class _Ref:
    key: str


@dataclass(slots=True)
class _BinOp:
    op: str  # one of + - * /
    left: object
    right: object


@dataclass(slots=True)
class _UnaryMinus:
    operand: object


@dataclass(slots=True)
class _Aggregate:
    func: str  # one of AGGREGATE_FUNCS
    repeater_key: str
    sub_key: Optional[str]  # None for count(repeater)


_ASTNode = Union[_Num, _Ref, _BinOp, _UnaryMinus, _Aggregate]


@dataclass(frozen=True)
class AggregateRef:
    func: str
    repeater_key: str
    sub_key: Optional[str]


# ── tokeniser ─────────────────────────────────────────────────────────────────


def _tokenise(source: str) -> List[_Token]:
    """Return a flat token list (whitespace skipped). Raises
    ``ComputedExpressionError`` on any illegal character, including ``**``
    (exponentiation is not part of our grammar and must be rejected explicitly
    to prevent confusion with repeated ``*`` multiply — a common typo that
    should error loudly, not silently mis-parse)."""
    tokens: List[_Token] = []
    prev_star = False  # track consecutive '*' for the ** rejection

    for m in _TOKEN_RE.finditer(source):
        kind = m.lastgroup
        raw = m.group()

        if kind == "WS":
            prev_star = False
            continue

        if kind == "BAD":
            raise ComputedExpressionError(
                f"Unexpected character {raw!r} in expression."
            )

        if kind == "OP":
            # Normalise unicode aliases to ASCII equivalents.
            if raw == _UNICODE_MUL:
                raw = "*"
            elif raw == _UNICODE_DIV:
                raw = "/"

            # Explicitly reject ** (exponentiation) as a syntax error.
            if raw == "*" and prev_star:
                raise ComputedExpressionError(
                    "Operator '**' is not supported; use '* *' for repeated "
                    "multiplication or rearrange with parentheses."
                )
            prev_star = raw == "*"

            op_map = {
                "+": _TK_PLUS, "-": _TK_MINUS,
                "*": _TK_STAR, "/": _TK_SLASH,
                "(": _TK_LPAREN, ")": _TK_RPAREN,
            }
            tokens.append(_Token(op_map[raw], raw))
        elif kind == "NUMBER":
            prev_star = False
            tokens.append(_Token(_TK_NUMBER, raw))
        elif kind == "IDENT":
            prev_star = False
            tokens.append(_Token(_TK_IDENT, raw))

    if len(tokens) > MAX_TOKENS:
        raise ComputedExpressionError(
            f"Expression exceeds the {MAX_TOKENS}-token limit."
        )

    tokens.append(_Token(_TK_EOF, ""))
    return tokens


# ── recursive-descent parser ──────────────────────────────────────────────────


class _Parser:
    """Single-use recursive-descent parser.  Instantiate, call ``parse()``,
    discard."""

    def __init__(self, tokens: List[_Token]) -> None:
        self._tokens = tokens
        self._pos: int = 0

    # -- helpers --

    def _peek(self) -> _Token:
        return self._tokens[self._pos]

    def _advance(self) -> _Token:
        tok = self._tokens[self._pos]
        if tok.kind != _TK_EOF:
            self._pos += 1
        return tok

    def _expect(self, kind: str) -> _Token:
        tok = self._advance()
        if tok.kind != kind:
            raise ComputedExpressionError(
                f"Expected {kind!r} but got {tok.kind!r} ({tok.value!r})."
            )
        return tok

    # -- grammar rules --

    def parse(self) -> _ASTNode:
        node = self._expr()
        if self._peek().kind != _TK_EOF:
            # There are unconsumed tokens — syntax error (e.g. "2 3").
            leftover = self._peek().value
            raise ComputedExpressionError(
                f"Unexpected token {leftover!r}: expression has trailing content."
            )
        return node

    def _expr(self) -> _ASTNode:
        """expr = term (('+' | '-') term)*  — left-associative."""
        node = self._term()
        while self._peek().kind in (_TK_PLUS, _TK_MINUS):
            op = self._advance().value
            right = self._term()
            node = _BinOp(op, node, right)
        return node

    def _term(self) -> _ASTNode:
        """term = unary (('*' | '/') unary)*  — left-associative."""
        node = self._unary()
        while self._peek().kind in (_TK_STAR, _TK_SLASH):
            op = self._advance().value
            right = self._unary()
            node = _BinOp(op, node, right)
        return node

    def _unary(self) -> _ASTNode:
        """unary = '-' unary | primary."""
        if self._peek().kind == _TK_MINUS:
            self._advance()
            operand = self._unary()
            return _UnaryMinus(operand)
        return self._primary()

    def _primary(self) -> _ASTNode:
        """primary = NUMBER | IDENT | '(' expr ')'."""
        tok = self._peek()

        if tok.kind == _TK_NUMBER:
            self._advance()
            return _Num(float(tok.value))

        if tok.kind == _TK_IDENT:
            self._advance()
            name = tok.value
            # `func(...)` = an aggregate over a repeater column (no dot in the
            # function name itself). Anything else is a scalar field reference.
            if self._peek().kind == _TK_LPAREN and "." not in name:
                func = name.lower()
                if func not in AGGREGATE_FUNCS:
                    raise ComputedExpressionError(f"Unknown function {name!r}.")
                self._advance()  # consume '('
                arg = self._expect(_TK_IDENT).value
                self._expect(_TK_RPAREN)
                repeater_key, _, sub = arg.partition(".")
                sub_key = sub or None
                if func != "count" and sub_key is None:
                    raise ComputedExpressionError(
                        f"{func}() needs a column, e.g. {func}(repeater.column)."
                    )
                return _Aggregate(func, repeater_key, sub_key)
            return _Ref(name)

        if tok.kind == _TK_LPAREN:
            self._advance()
            node = self._expr()
            self._expect(_TK_RPAREN)
            return node

        if tok.kind == _TK_EOF:
            raise ComputedExpressionError(
                "Unexpected end of expression; expected a number, field "
                "reference, or '('."
            )

        raise ComputedExpressionError(
            f"Unexpected token {tok.value!r} in expression."
        )


# ── field-ref collector ───────────────────────────────────────────────────────


def _collect_refs(node: _ASTNode) -> Tuple[FrozenSet[str], Tuple[AggregateRef, ...]]:
    """Walk an AST → (scalar field-ref keys, aggregate refs). Scalar refs feed
    the earlier-numeric-field gate; aggregate refs feed the repeater-column gate."""
    refs: set[str] = set()
    aggs: List[AggregateRef] = []

    def _walk(n: object) -> None:
        if isinstance(n, _Ref):
            refs.add(n.key)
        elif isinstance(n, _Aggregate):
            aggs.append(AggregateRef(n.func, n.repeater_key, n.sub_key))
        elif isinstance(n, _BinOp):
            _walk(n.left)
            _walk(n.right)
        elif isinstance(n, _UnaryMinus):
            _walk(n.operand)
        # _Num — no refs

    _walk(node)
    return frozenset(refs), tuple(aggs)


# ── public parse API ──────────────────────────────────────────────────────────


def parse_expression(expr: str) -> ParsedExpression:
    """Parse *expr* and return a :class:`ParsedExpression`.

    Raises
    ------
    ComputedExpressionError
        On any syntax error: empty expression, unbalanced parentheses,
        trailing garbage, illegal characters, expression too long, etc.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise ComputedExpressionError("Expression must be a non-empty string.")

    if len(expr) > MAX_EXPR_LEN:
        raise ComputedExpressionError(
            f"Expression length {len(expr)} exceeds the {MAX_EXPR_LEN}-character limit."
        )

    source = expr.strip()
    tokens = _tokenise(source)
    ast_node = _Parser(tokens).parse()
    refs, aggs = _collect_refs(ast_node)
    return ParsedExpression(source=source, field_refs=refs, aggregates=aggs, _ast=ast_node)


# ── evaluator ────────────────────────────────────────────────────────────────


def _coerce(value: object) -> Optional[float]:
    """Try to coerce *value* to float.  Returns ``None`` on failure (including
    ``bool`` — booleans are not numeric in this domain)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except (ValueError, OverflowError):
            return None
    return None


def _eval_node(
    node: _ASTNode, values: Dict[str, object]
) -> Optional[float]:
    """Recursively evaluate *node* against *values*.

    Returns ``None`` (fail-closed) for: missing fields, None values,
    non-numeric values, division by zero.  Never raises.
    """
    if isinstance(node, _Num):
        return node.value

    if isinstance(node, _Ref):
        raw = values.get(node.key)  # missing key → None
        if raw is None:
            return None
        return _coerce(raw)

    if isinstance(node, _UnaryMinus):
        inner = _eval_node(node.operand, values)
        if inner is None:
            return None
        return -inner

    if isinstance(node, _Aggregate):
        rows = values.get(node.repeater_key)
        if not isinstance(rows, list):
            rows = []
        if node.func == "count":
            return float(len(rows))
        nums: List[float] = []
        for row in rows:
            if isinstance(row, dict):
                coerced = _coerce(row.get(node.sub_key))
                if coerced is not None:
                    nums.append(coerced)
        if node.func == "sum":
            return float(sum(nums))  # empty column → 0
        if not nums:
            return None  # avg/min/max over nothing → None (fail-closed)
        if node.func == "avg":
            return sum(nums) / len(nums)
        if node.func == "min":
            return min(nums)
        if node.func == "max":
            return max(nums)
        return None

    if isinstance(node, _BinOp):
        left = _eval_node(node.left, values)
        if left is None:
            return None
        right = _eval_node(node.right, values)
        if right is None:
            return None

        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            if right == 0.0:
                return None  # div-by-zero → None, never raise
            return left / right

    return None  # unreachable but satisfies type-checker


def evaluate(
    expr: Union[ParsedExpression, str],
    values: Dict[str, object],
) -> Optional[float]:
    """Evaluate *expr* against the field *values* dict.

    Parameters
    ----------
    expr:
        Either a :class:`ParsedExpression` (pre-parsed, preferred for hot
        paths) or a raw expression string (will be parsed on the fly).
    values:
        Mapping from field key → field value.  Values are coerced: int/float
        are accepted directly; numeric strings are coerced; anything else
        (None, non-numeric string, list, …) causes the result to be ``None``.

    Returns
    -------
    float
        The computed result.
    None
        If any referenced field is missing, None, or non-numeric, or if
        division by zero occurs.  Never raises at runtime.
    """
    try:
        if isinstance(expr, str):
            parsed = parse_expression(expr)
        elif isinstance(expr, ParsedExpression):
            parsed = expr
        else:
            return None  # defensive: wrong type passed, fail closed

        return _eval_node(parsed._ast, values)  # type: ignore[attr-defined]
    except ComputedExpressionError:
        return None  # a raw-str with a syntax error → None (fail closed)
    except Exception:  # noqa: BLE001 — belt-and-suspenders, never raise
        return None


# ── convenience: collect refs from a raw string ───────────────────────────────


def field_refs(expr: str) -> FrozenSet[str]:
    """Return the SCALAR field keys referenced in *expr* (not aggregate-over-
    repeater refs — those are :func:`aggregate_refs`).

    Raises ``ComputedExpressionError`` on syntax errors (same as
    :func:`parse_expression`).  Useful for quick validation at save time.
    """
    return parse_expression(expr).field_refs


def aggregate_refs(expr: str) -> Tuple[AggregateRef, ...]:
    """Return the aggregate-over-repeater refs in *expr* (``sum(rep.col)`` …)."""
    return parse_expression(expr).aggregates
