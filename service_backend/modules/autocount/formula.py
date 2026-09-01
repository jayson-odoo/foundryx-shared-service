"""Safe transform-formula engine (slice 16) - AutoCount source `value` → canonical.

    !!  NO eval / exec / Function / Jinja - a hand-written parser ONLY.  !!

An operator authors a transform as an EXPRESSION over a single input ``value``
(the raw AutoCount source value - usually a string like ``"T"``, ``"30000.0"``,
``"2026/03/18 16:03:21"``). That expression runs in the sync path over customer
data, so it MUST NOT be handed to any general evaluator: ``eval``/``exec``/
``ast.literal_eval``/Jinja would all open an SSTI→RCE hole. This is the same
house line as ``app/form_engine/computed.py`` (arithmetic) and the template
merge renderer - a deliberately tiny grammar with its own tokenizer +
recursive-descent parser + evaluator, nothing else accepted.

This module is the AUTHORITATIVE side of a client/server pair: its TypeScript
twin ``service_frontend/lib/autocount-formula.ts`` drives the builder's live
preview, and a shared golden matrix (``formula_parity.json``) is run by BOTH
pytest and vitest so the two evaluators cannot silently drift (AC-16-01).

Grammar (EBNF)
--------------
    expr        = or
    or          = and  ( "or"  and )*
    and         = notx ( "and" notx )*
    notx        = "not" notx | comparison
    comparison  = concat ( ("=="|"!="|"<"|"<="|">"|">=") concat )?
    concat      = add ( "&" add )*
    add         = mul ( ("+"|"-") mul )*
    mul         = unary ( ("*"|"/") unary )*
    unary       = "-" unary | call
    call        = primary | IDENT "(" args? ")"
    primary     = NUMBER | STRING | "true" | "false" | "null" | "value"
                | "(" expr ")"
    args        = expr ( "," expr )*

Fail-closed contract
--------------------
* PARSE time (``parse_formula`` / the PUT save-gate): unknown name, unknown
  function, wrong arity, syntax error, over-length → ``FormulaParseError``
  (mapped to a 422 that names the problem). A bad formula NEVER reaches a sync.
* EVALUATE time (``evaluate_formula`` in the mapping path): a runtime fault
  (``number("abc")``, division by zero, a type mismatch) → ``FormulaRuntimeError``,
  which the MappingEngine turns into a NAMED per-field error - never a silent
  null that would blank a Sorento field (AC-16-03).

Dates use a FIXED, documented token vocabulary (``yyyy MM dd HH mm ss`` + ISO
``yyyy-MM-ddTHH:mm:ssZ``) parsed/formatted by hand on BOTH sides - no
``strptime`` on one side and a JS date library on the other. ``parseDate``
extracts calendar COMPONENTS and ``formatDate`` re-emits them, with zero date
arithmetic, so date parity is provable (AC-16-14).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from app.services.filter_translator import MAX_GROUP_DEPTH as _MAX_DEPTH

# ── hard caps ────────────────────────────────────────────────────────────────
MAX_FORMULA_LEN: int = 1000
MAX_TOKENS: int = 200
MAX_DEPTH: int = _MAX_DEPTH  # reuse the ONE depth constant (rule_engine precedent)


# ── errors ───────────────────────────────────────────────────────────────────


class FormulaError(ValueError):
    """Base - a ``ValueError`` so callers may ``except (ValueError, FormulaError)``."""


class FormulaParseError(FormulaError):
    """A save-time fault: syntax, unknown name/function, bad arity, over-length.
    Mapped to a 422 that names the problem - a bad formula is un-saveable."""


class FormulaRuntimeError(FormulaError):
    """An evaluate-time fault over real data (``number("abc")``, div-by-zero, a
    type mismatch). Becomes a NAMED per-field error, never a silent null."""


# ── the fixed date-token vocabulary (AC-16-14) ────────────────────────────────
# Minimal v1: the known vendor format + ISO out. Every token is fixed-width, so
# parse walks format + value in lockstep with no ambiguity. Expand on demand -
# each added token is mirrored in the TS twin and parity-tested.
DATE_TOKENS: Tuple[Dict[str, Any], ...] = (
    {"token": "yyyy", "width": 4, "field": "year", "description": "4-digit year"},
    {"token": "MM", "width": 2, "field": "month", "description": "2-digit month (01-12)"},
    {"token": "dd", "width": 2, "field": "day", "description": "2-digit day (01-31)"},
    {"token": "HH", "width": 2, "field": "hour", "description": "2-digit hour (00-23)"},
    {"token": "mm", "width": 2, "field": "minute", "description": "2-digit minute (00-59)"},
    {"token": "ss", "width": 2, "field": "second", "description": "2-digit second (00-59)"},
)
# Longer tokens first so the greedy matcher never splits ``mm`` out of a stray
# ``MM`` (they differ in case, but ordering by length keeps the scan robust).
_DATE_TOKEN_ORDER: Tuple[str, ...] = ("yyyy", "MM", "dd", "HH", "mm", "ss")
_DATE_TOKEN_WIDTH: Dict[str, int] = {t["token"]: t["width"] for t in DATE_TOKENS}
_DATE_TOKEN_FIELD: Dict[str, str] = {t["token"]: t["field"] for t in DATE_TOKENS}

# The canonical ISO output the Date preset targets.
ISO_OUTPUT_FORMAT = "yyyy-MM-ddTHH:mm:ssZ"

# Documented input formats offered by the date-format tool. A free-form pattern
# is NOT accepted - the tool picks from this list (foolproof + parity-safe).
DATE_INPUT_FORMATS: Tuple[str, ...] = (
    "yyyy/MM/dd HH:mm:ss",
    "yyyy/MM/dd",
    "yyyy-MM-dd HH:mm:ss",
    "yyyy-MM-dd",
    "dd/MM/yyyy",
    "dd/MM/yyyy HH:mm:ss",
)
DATE_OUTPUT_FORMATS: Tuple[str, ...] = (
    ISO_OUTPUT_FORMAT,
    "yyyy-MM-dd",
    "yyyy/MM/dd",
    "dd/MM/yyyy",
    "yyyy-MM-dd HH:mm:ss",
)


@dataclass(frozen=True)
class FormulaDate:
    """A parsed date as calendar COMPONENTS, treated as aware-UTC wall clock.

    Carrying components (not an epoch, not a ``datetime``) means ``formatDate``
    is pure substitution with no calendar arithmetic - the property that makes
    client/server date parity provable. The house datetime rule (aware-UTC) is
    honoured: the components are UTC and the ISO form carries a ``Z``.
    """

    year: int
    month: int
    day: int
    hour: int = 0
    minute: int = 0
    second: int = 0

    def iso(self) -> str:
        return (
            f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
            f"T{self.hour:02d}:{self.minute:02d}:{self.second:02d}Z"
        )


# A runtime value in the language: None(null) | bool | float | str | FormulaDate.
Value = Union[None, bool, float, str, FormulaDate]


# ── tokeniser ─────────────────────────────────────────────────────────────────

_TK_NUMBER = "NUMBER"
_TK_STRING = "STRING"
_TK_IDENT = "IDENT"
_TK_OP = "OP"
_TK_LPAREN = "("
_TK_RPAREN = ")"
_TK_COMMA = ","
_TK_EOF = "EOF"

# Multi-char operators FIRST so ``==`` never tokenises as two ``=`` (and ``=``
# alone is illegal - the grammar demands ``==``).
_OPERATORS: Tuple[str, ...] = ("==", "!=", "<=", ">=", "<", ">", "&", "+", "-", "*", "/")

_KEYWORDS = {"value", "true", "false", "null", "and", "or", "not"}

_NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# String escapes shared verbatim with the TS twin (keep both tables identical).
_STRING_ESCAPES = {"\\": "\\", '"': '"', "'": "'", "n": "\n", "t": "\t"}


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


def _tokenise(source: str) -> List[_Token]:
    tokens: List[_Token] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "(":
            tokens.append(_Token(_TK_LPAREN, ch))
            i += 1
            continue
        if ch == ")":
            tokens.append(_Token(_TK_RPAREN, ch))
            i += 1
            continue
        if ch == ",":
            tokens.append(_Token(_TK_COMMA, ch))
            i += 1
            continue
        if ch == '"' or ch == "'":
            value, i = _scan_string(source, i)
            tokens.append(_Token(_TK_STRING, value))
            continue
        # operators (multi-char first)
        matched_op = None
        for op in _OPERATORS:
            if source.startswith(op, i):
                matched_op = op
                break
        if matched_op is not None:
            tokens.append(_Token(_TK_OP, matched_op))
            i += len(matched_op)
            continue
        if ch == "=":  # a lone '=' - guide the operator to '=='
            raise FormulaParseError("Use '==' for equality, not a single '='.")
        m = _NUMBER_RE.match(source, i)
        if m:
            tokens.append(_Token(_TK_NUMBER, m.group()))
            i = m.end()
            continue
        m = _IDENT_RE.match(source, i)
        if m:
            tokens.append(_Token(_TK_IDENT, m.group()))
            i = m.end()
            continue
        raise FormulaParseError(f"Unexpected character {ch!r} in the formula.")

    if len(tokens) > MAX_TOKENS:
        raise FormulaParseError(f"The formula exceeds the {MAX_TOKENS}-token limit.")
    tokens.append(_Token(_TK_EOF, ""))
    return tokens


def _scan_string(source: str, start: int) -> Tuple[str, int]:
    quote = source[start]
    out: List[str] = []
    i = start + 1
    n = len(source)
    while i < n:
        ch = source[i]
        if ch == "\\":
            if i + 1 >= n:
                raise FormulaParseError("The formula ends with a dangling '\\'.")
            esc = source[i + 1]
            if esc not in _STRING_ESCAPES:
                raise FormulaParseError(f"Unknown escape '\\{esc}' in a string.")
            out.append(_STRING_ESCAPES[esc])
            i += 2
            continue
        if ch == quote:
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise FormulaParseError("A string literal is missing its closing quote.")


# ── AST ───────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Lit:
    value: Value


@dataclass(frozen=True)
class _ValueRef:
    pass


@dataclass(frozen=True)
class _Unary:
    op: str  # "-" | "not"
    operand: object


@dataclass(frozen=True)
class _Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class _Call:
    name: str
    args: Tuple[object, ...]


# ── function catalogue (drives the builder reference + the arity save-gate) ────
# Each function: category, signature, argument docs, one-line description,
# example, and arity (min/max; max None = variadic). ONE source of truth, mirrored
# byte-for-byte in the TS twin (AC-16-13/15).


@dataclass(frozen=True)
class FunctionArg:
    name: str
    description: str


@dataclass(frozen=True)
class FunctionDef:
    name: str
    category: str  # String | Number | Boolean | Date | Logical
    signature: str
    args: Tuple[FunctionArg, ...]
    description: str
    example: str
    min_args: int
    max_args: Optional[int]  # None = variadic

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "signature": self.signature,
            "args": [{"name": a.name, "description": a.description} for a in self.args],
            "description": self.description,
            "example": self.example,
            "minArgs": self.min_args,
            "maxArgs": self.max_args,
        }


FUNCTION_CATALOG: Tuple[FunctionDef, ...] = (
    # ── String ──
    FunctionDef(
        "upper", "String", "upper(text)",
        (FunctionArg("text", "the text to convert"),),
        "Uppercases the text.", 'upper(value) → "ABC"', 1, 1,
    ),
    FunctionDef(
        "lower", "String", "lower(text)",
        (FunctionArg("text", "the text to convert"),),
        "Lowercases the text.", 'lower(value) → "abc"', 1, 1,
    ),
    FunctionDef(
        "trim", "String", "trim(text)",
        (FunctionArg("text", "the text to trim"),),
        "Removes leading and trailing whitespace.", 'trim(value) → "abc"', 1, 1,
    ),
    FunctionDef(
        "contains", "String", "contains(text, sub)",
        (FunctionArg("text", "the text to search in"),
         FunctionArg("sub", "the substring to look for")),
        "True when text contains sub.", 'contains(value, "-A") → true', 2, 2,
    ),
    FunctionDef(
        "replace", "String", "replace(text, search, replacement)",
        (FunctionArg("text", "the text to edit"),
         FunctionArg("search", "the substring to replace"),
         FunctionArg("replacement", "what to put in its place")),
        "Replaces every occurrence of search with replacement.",
        'replace(value, "-", "/") → "300/A001"', 3, 3,
    ),
    FunctionDef(
        "concat", "String", "concat(a, b, ...)",
        (FunctionArg("...", "two or more values to join as text"),),
        "Joins its arguments into one string.",
        'concat("AC-", value) → "AC-300"', 1, None,
    ),
    # ── Number ──
    FunctionDef(
        "number", "Number", "number(x)",
        (FunctionArg("x", "a numeric value or numeric string"),),
        "Converts a numeric string to a number (fails if not numeric).",
        'number("30000.0") → 30000', 1, 1,
    ),
    FunctionDef(
        "round", "Number", "round(x, digits)",
        (FunctionArg("x", "the number to round"),
         FunctionArg("digits", "how many decimal places (0 = whole number)")),
        "Rounds x to the given number of decimal places (half away from zero).",
        "round(number(value), 0) → 30000", 2, 2,
    ),
    FunctionDef(
        "abs", "Number", "abs(x)",
        (FunctionArg("x", "the number"),),
        "The absolute value of x.", "abs(-5) → 5", 1, 1,
    ),
    # ── Boolean ──
    FunctionDef(
        "bool", "Boolean", "bool(x)",
        (FunctionArg("x", "a value like 'T'/'F', 1/0, true/false"),),
        "Converts a truthy/falsey token to a real boolean.",
        'bool(value) → true', 1, 1,
    ),
    # ── Date ──
    FunctionDef(
        "parseDate", "Date", "parseDate(text, inputFormat)",
        (FunctionArg("text", "the date text AutoCount sends"),
         FunctionArg("inputFormat", "a token format like yyyy/MM/dd HH:mm:ss")),
        "Reads a date from text using the input format tokens.",
        'parseDate(value, "yyyy/MM/dd HH:mm:ss")', 2, 2,
    ),
    FunctionDef(
        "formatDate", "Date", "formatDate(date, outputFormat)",
        (FunctionArg("date", "a value from parseDate"),
         FunctionArg("outputFormat", "a token format like yyyy-MM-ddTHH:mm:ssZ")),
        "Writes a parsed date out using the output format tokens.",
        'formatDate(parseDate(value, "yyyy/MM/dd"), "yyyy-MM-ddTHH:mm:ssZ")', 2, 2,
    ),
    # ── Logical ──
    FunctionDef(
        "if", "Logical", "if(condition, then, else)",
        (FunctionArg("condition", "a true/false test"),
         FunctionArg("then", "the result when the condition is true"),
         FunctionArg("else", "the result when the condition is false")),
        "Returns then when condition is true, otherwise else.",
        'if(value == "T", true, false)', 3, 3,
    ),
    FunctionDef(
        "default", "Logical", "default(x, fallback)",
        (FunctionArg("x", "the value to check"),
         FunctionArg("fallback", "used when x is null")),
        "Returns x, or fallback when x is null.",
        'default(value, "N/A")', 2, 2,
    ),
)

_FUNCTION_BY_NAME: Dict[str, FunctionDef] = {f.name: f for f in FUNCTION_CATALOG}

# Operator reference for the builder's operator buttons (not callable functions).
OPERATOR_CATALOG: Tuple[Dict[str, str], ...] = (
    {"symbol": "==", "category": "Comparison", "description": "equal to"},
    {"symbol": "!=", "category": "Comparison", "description": "not equal to"},
    {"symbol": "<", "category": "Comparison", "description": "less than"},
    {"symbol": "<=", "category": "Comparison", "description": "less than or equal"},
    {"symbol": ">", "category": "Comparison", "description": "greater than"},
    {"symbol": ">=", "category": "Comparison", "description": "greater than or equal"},
    {"symbol": "and", "category": "Logical", "description": "both must be true"},
    {"symbol": "or", "category": "Logical", "description": "either may be true"},
    {"symbol": "not", "category": "Logical", "description": "negates a boolean"},
    {"symbol": "+", "category": "Arithmetic", "description": "add"},
    {"symbol": "-", "category": "Arithmetic", "description": "subtract"},
    {"symbol": "*", "category": "Arithmetic", "description": "multiply"},
    {"symbol": "/", "category": "Arithmetic", "description": "divide"},
    {"symbol": "&", "category": "Text", "description": "join as text"},
)

# Preset transforms → canonical formulas (AC-16-10). Picking a preset fills the
# formula; the operator edits from there. ``custom`` starts empty.
PRESETS: Tuple[Dict[str, str], ...] = (
    {"key": "text", "label": "Text", "formula": "value"},
    {"key": "boolean", "label": "Boolean", "formula": 'if(value == "T", true, false)'},
    {"key": "decimal", "label": "Decimal", "formula": "number(value)"},
    {"key": "integer", "label": "Integer", "formula": "round(number(value), 0)"},
    {
        "key": "date",
        "label": "Date",
        "formula": (
            'formatDate(parseDate(value, "yyyy/MM/dd HH:mm:ss"), '
            '"yyyy-MM-ddTHH:mm:ssZ")'
        ),
    },
    {"key": "custom", "label": "Custom", "formula": ""},
)

# The named transforms (the legacy, formula-NULL path) mapped onto their preset
# equivalents, so the editor can show an existing row's preset without a formula.
TRANSFORM_PRESET: Dict[str, str] = {
    "string": "text",
    "t_f_bool": "boolean",
    "bool": "boolean",
    "decimal": "decimal",
    "int": "integer",
    "date": "date",
    "datetime": "date",
    "slash_datetime": "date",
}


def catalog_payload() -> Dict[str, Any]:
    """The wire payload the builder consumes (AC-16-13/15): functions grouped by
    category, operators, presets, and the date-token vocabulary."""
    return {
        "functions": [f.to_dict() for f in FUNCTION_CATALOG],
        "operators": [dict(op) for op in OPERATOR_CATALOG],
        "presets": [dict(p) for p in PRESETS],
        "valueVariable": {
            "name": "value",
            "description": "the raw AutoCount source value for this field",
        },
        "dateTokens": [dict(t) for t in DATE_TOKENS],
        "dateInputFormats": list(DATE_INPUT_FORMATS),
        "dateOutputFormats": list(DATE_OUTPUT_FORMATS),
    }


# ── parser ────────────────────────────────────────────────────────────────────


class _Parser:
    def __init__(self, tokens: List[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0
        self._depth = 0

    def _peek(self) -> _Token:
        return self._tokens[self._pos]

    def _advance(self) -> _Token:
        tok = self._tokens[self._pos]
        if tok.kind != _TK_EOF:
            self._pos += 1
        return tok

    def _is_keyword(self, word: str) -> bool:
        tok = self._peek()
        return tok.kind == _TK_IDENT and tok.value == word

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise FormulaParseError(
                f"The formula nests deeper than the {MAX_DEPTH}-level limit."
            )

    def _leave(self) -> None:
        self._depth -= 1

    def parse(self) -> object:
        node = self._or()
        if self._peek().kind != _TK_EOF:
            raise FormulaParseError(
                f"Unexpected {self._peek().value!r}: the formula has trailing content."
            )
        return node

    def _or(self) -> object:
        node = self._and()
        while self._is_keyword("or"):
            self._advance()
            node = _Binary("or", node, self._and())
        return node

    def _and(self) -> object:
        node = self._not()
        while self._is_keyword("and"):
            self._advance()
            node = _Binary("and", node, self._not())
        return node

    def _not(self) -> object:
        if self._is_keyword("not"):
            self._advance()
            return _Unary("not", self._not())
        return self._comparison()

    def _comparison(self) -> object:
        node = self._concat()
        tok = self._peek()
        if tok.kind == _TK_OP and tok.value in ("==", "!=", "<", "<=", ">", ">="):
            self._advance()
            return _Binary(tok.value, node, self._concat())
        return node

    def _concat(self) -> object:
        node = self._add()
        while self._peek().kind == _TK_OP and self._peek().value == "&":
            self._advance()
            node = _Binary("&", node, self._add())
        return node

    def _add(self) -> object:
        node = self._mul()
        while self._peek().kind == _TK_OP and self._peek().value in ("+", "-"):
            op = self._advance().value
            node = _Binary(op, node, self._mul())
        return node

    def _mul(self) -> object:
        node = self._unary()
        while self._peek().kind == _TK_OP and self._peek().value in ("*", "/"):
            op = self._advance().value
            node = _Binary(op, node, self._unary())
        return node

    def _unary(self) -> object:
        if self._peek().kind == _TK_OP and self._peek().value == "-":
            self._advance()
            return _Unary("-", self._unary())
        return self._primary()

    def _primary(self) -> object:
        tok = self._peek()

        if tok.kind == _TK_NUMBER:
            self._advance()
            return _Lit(float(tok.value))

        if tok.kind == _TK_STRING:
            self._advance()
            return _Lit(tok.value)

        if tok.kind == _TK_IDENT:
            name = tok.value
            if name == "true":
                self._advance()
                return _Lit(True)
            if name == "false":
                self._advance()
                return _Lit(False)
            if name == "null":
                self._advance()
                return _Lit(None)
            if name == "value":
                self._advance()
                return _ValueRef()
            if name in ("and", "or", "not"):
                raise FormulaParseError(f"Unexpected operator {name!r}.")
            # Anything else must be a function call: IDENT '(' args ')'.
            self._advance()
            if self._peek().kind != _TK_LPAREN:
                raise FormulaParseError(
                    f"Unknown name {name!r} - expected the variable 'value', a "
                    f"literal, or a function call."
                )
            if name not in _FUNCTION_BY_NAME:
                raise FormulaParseError(f"Unknown function {name!r}.")
            self._enter()
            self._advance()  # consume '('
            args: List[object] = []
            if self._peek().kind != _TK_RPAREN:
                args.append(self._or())
                while self._peek().kind == _TK_COMMA:
                    self._advance()
                    args.append(self._or())
            if self._peek().kind != _TK_RPAREN:
                raise FormulaParseError(
                    f"{name}(...) is missing its closing parenthesis."
                )
            self._advance()  # consume ')'
            self._leave()
            _check_arity(name, len(args))
            return _Call(name, tuple(args))

        if tok.kind == _TK_LPAREN:
            self._enter()
            self._advance()
            node = self._or()
            if self._peek().kind != _TK_RPAREN:
                raise FormulaParseError("Unbalanced parentheses in the formula.")
            self._advance()
            self._leave()
            return node

        if tok.kind == _TK_EOF:
            raise FormulaParseError("The formula ended unexpectedly.")
        raise FormulaParseError(f"Unexpected {tok.value!r} in the formula.")


def _check_arity(name: str, count: int) -> None:
    fn = _FUNCTION_BY_NAME[name]
    if count < fn.min_args or (fn.max_args is not None and count > fn.max_args):
        if fn.max_args is None:
            need = f"at least {fn.min_args}"
        elif fn.min_args == fn.max_args:
            need = f"exactly {fn.min_args}"
        else:
            need = f"{fn.min_args}-{fn.max_args}"
        raise FormulaParseError(
            f"{name}() takes {need} argument(s), got {count}."
        )


@dataclass(frozen=True)
class ParsedFormula:
    source: str
    ast: object


def parse_formula(formula: str) -> ParsedFormula:
    """Parse + validate a formula. Raises ``FormulaParseError`` on any syntax
    error, unknown name/function, bad arity or over-length string. This is the
    save-time gate (AC-16-03) - a formula that parses clean is storable."""
    if not isinstance(formula, str) or not formula.strip():
        raise FormulaParseError("The formula must not be empty.")
    if len(formula) > MAX_FORMULA_LEN:
        raise FormulaParseError(
            f"The formula exceeds the {MAX_FORMULA_LEN}-character limit."
        )
    tokens = _tokenise(formula)
    ast = _Parser(tokens).parse()
    return ParsedFormula(source=formula.strip(), ast=ast)


def validate_formula(formula: str) -> None:
    """Parse purely for the side effect of raising on an invalid formula."""
    parse_formula(formula)


# ── evaluator ─────────────────────────────────────────────────────────────────


def _to_formula_value(raw: Any) -> Value:
    """Coerce a raw AutoCount source value into a language value. The vendor
    mixes types (a string ``"10"`` and an int ``2`` for one field), so bool /
    number / string / None are all admitted; a Decimal becomes a number."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        return raw
    # Decimal, or anything else numeric-ish → number if possible, else its text.
    try:
        return float(raw)  # Decimal
    except (TypeError, ValueError):
        return str(raw)


def _is_number(v: Value) -> bool:
    return isinstance(v, float) and not isinstance(v, bool)


def _stringify(v: Value) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, FormulaDate):
        return v.iso()
    if _is_number(v):
        return _stringify_number(v)  # type: ignore[arg-type]
    return str(v)


def _stringify_number(n: float) -> str:
    if n == int(n) and abs(n) < 1e15:
        return str(int(n))
    return repr(n)


_NUMERIC_STRING_RE = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$")


def _to_number(v: Value, *, ctx: str = "number") -> float:
    if _is_number(v):
        return v  # type: ignore[return-value]
    if isinstance(v, bool):
        raise FormulaRuntimeError(f"{ctx}() cannot convert a true/false value.")
    if v is None:
        raise FormulaRuntimeError(f"{ctx}() cannot convert an empty value.")
    if isinstance(v, str):
        s = v.strip()
        if not _NUMERIC_STRING_RE.match(s):
            raise FormulaRuntimeError(f"{ctx}() expected a number, got {v!r}.")
        return float(s)
    raise FormulaRuntimeError(f"{ctx}() expected a number, got {v!r}.")


_BOOL_TRUE = {"t", "true", "y", "yes", "1"}
_BOOL_FALSE = {"f", "false", "n", "no", "0"}


def _to_bool(v: Value) -> bool:
    if isinstance(v, bool):
        return v
    if _is_number(v):
        return v != 0.0
    if isinstance(v, str):
        token = v.strip().lower()
        if token in _BOOL_TRUE:
            return True
        if token in _BOOL_FALSE:
            return False
        raise FormulaRuntimeError(f"bool() expected a true/false value, got {v!r}.")
    raise FormulaRuntimeError("bool() expected a true/false value, got null.")


def _round(x: float, digits: float) -> float:
    if digits != int(digits) or digits < 0 or digits > 12:
        raise FormulaRuntimeError("round() digits must be a whole number 0-12.")
    n = int(digits)
    factor = 10 ** n
    # Half away from zero, hand-rolled so Python's banker's rounding and JS's
    # Math.round (half up) can never diverge.
    import math

    sign = 1.0 if x >= 0 else -1.0
    return sign * math.floor(abs(x) * factor + 0.5) / factor


# ── date tools (hand-rolled, mirrored - AC-16-14) ─────────────────────────────


def _split_format(fmt: str) -> List[Tuple[str, Any]]:
    """Split a token format into ``("token", name)`` / ``("literal", text)`` parts.
    Greedy longest-token match; anything else is a literal separator."""
    parts: List[Tuple[str, Any]] = []
    i = 0
    n = len(fmt)
    while i < n:
        matched = None
        for tok in _DATE_TOKEN_ORDER:
            if fmt.startswith(tok, i):
                matched = tok
                break
        if matched is not None:
            parts.append(("token", matched))
            i += len(matched)
        else:
            parts.append(("literal", fmt[i]))
            i += 1
    return parts


_MONTH_MAX = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _parse_date(text: Value, fmt: Value) -> FormulaDate:
    if not isinstance(fmt, str):
        raise FormulaRuntimeError("parseDate() needs a text input format.")
    raw = _stringify(text)
    parts = _split_format(fmt)
    fields: Dict[str, int] = {"hour": 0, "minute": 0, "second": 0}
    pos = 0
    for kind, payload in parts:
        if kind == "literal":
            if pos >= len(raw) or raw[pos] != payload:
                raise FormulaRuntimeError(
                    f"parseDate() could not match {raw!r} against {fmt!r}."
                )
            pos += 1
            continue
        width = _DATE_TOKEN_WIDTH[payload]
        chunk = raw[pos : pos + width]
        if len(chunk) != width or not chunk.isdigit():
            raise FormulaRuntimeError(
                f"parseDate() could not read '{payload}' from {raw!r}."
            )
        fields[_DATE_TOKEN_FIELD[payload]] = int(chunk)
        pos += width
    if pos != len(raw):
        raise FormulaRuntimeError(
            f"parseDate() found trailing characters in {raw!r} for {fmt!r}."
        )
    if "year" not in fields or "month" not in fields or "day" not in fields:
        raise FormulaRuntimeError(
            "parseDate() input format must include yyyy, MM and dd."
        )
    _validate_date_fields(fields)
    return FormulaDate(
        year=fields["year"],
        month=fields["month"],
        day=fields["day"],
        hour=fields.get("hour", 0),
        minute=fields.get("minute", 0),
        second=fields.get("second", 0),
    )


def _validate_date_fields(f: Dict[str, int]) -> None:
    month = f["month"]
    if month < 1 or month > 12:
        raise FormulaRuntimeError(f"parseDate() got an invalid month {month}.")
    max_day = _MONTH_MAX[month - 1]
    if f["day"] < 1 or f["day"] > max_day:
        raise FormulaRuntimeError(f"parseDate() got an invalid day {f['day']}.")
    if not (0 <= f.get("hour", 0) <= 23):
        raise FormulaRuntimeError("parseDate() got an invalid hour.")
    if not (0 <= f.get("minute", 0) <= 59):
        raise FormulaRuntimeError("parseDate() got an invalid minute.")
    if not (0 <= f.get("second", 0) <= 59):
        raise FormulaRuntimeError("parseDate() got an invalid second.")


def _format_date(value: Value, fmt: Value) -> str:
    if not isinstance(fmt, str):
        raise FormulaRuntimeError("formatDate() needs a text output format.")
    if not isinstance(value, FormulaDate):
        raise FormulaRuntimeError(
            "formatDate() expects a date from parseDate() as its first argument."
        )
    field_value = {
        "year": f"{value.year:04d}",
        "month": f"{value.month:02d}",
        "day": f"{value.day:02d}",
        "hour": f"{value.hour:02d}",
        "minute": f"{value.minute:02d}",
        "second": f"{value.second:02d}",
    }
    out: List[str] = []
    for kind, payload in _split_format(fmt):
        if kind == "literal":
            out.append(payload)
        else:
            out.append(field_value[_DATE_TOKEN_FIELD[payload]])
    return "".join(out)


# ── eager function implementations ────────────────────────────────────────────


def _fn_upper(a: List[Value]) -> Value:
    return _stringify(a[0]).upper()


def _fn_lower(a: List[Value]) -> Value:
    return _stringify(a[0]).lower()


def _fn_trim(a: List[Value]) -> Value:
    return _stringify(a[0]).strip()


def _fn_contains(a: List[Value]) -> Value:
    return _stringify(a[1]) in _stringify(a[0])


def _fn_replace(a: List[Value]) -> Value:
    return _stringify(a[0]).replace(_stringify(a[1]), _stringify(a[2]))


def _fn_concat(a: List[Value]) -> Value:
    return "".join(_stringify(x) for x in a)


def _fn_number(a: List[Value]) -> Value:
    return _to_number(a[0])


def _fn_round(a: List[Value]) -> Value:
    return _round(_to_number(a[0], ctx="round"), _to_number(a[1], ctx="round"))


def _fn_abs(a: List[Value]) -> Value:
    return abs(_to_number(a[0], ctx="abs"))


def _fn_bool(a: List[Value]) -> Value:
    return _to_bool(a[0])


def _fn_parse_date(a: List[Value]) -> Value:
    return _parse_date(a[0], a[1])


def _fn_format_date(a: List[Value]) -> Value:
    return _format_date(a[0], a[1])


_EAGER_FUNCS: Dict[str, Callable[[List[Value]], Value]] = {
    "upper": _fn_upper,
    "lower": _fn_lower,
    "trim": _fn_trim,
    "contains": _fn_contains,
    "replace": _fn_replace,
    "concat": _fn_concat,
    "number": _fn_number,
    "round": _fn_round,
    "abs": _fn_abs,
    "bool": _fn_bool,
    "parseDate": _fn_parse_date,
    "formatDate": _fn_format_date,
}


def _values_equal(a: Value, b: Value) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, FormulaDate) and isinstance(b, FormulaDate):
        return a.iso() == b.iso()
    return False  # different types are never equal (deterministic, no coercion)


def _compare(op: str, a: Value, b: Value) -> bool:
    if _is_number(a) and _is_number(b):
        left, right = a, b  # type: ignore[assignment]
    elif isinstance(a, str) and isinstance(b, str):
        left, right = a, b
    elif isinstance(a, FormulaDate) and isinstance(b, FormulaDate):
        left, right = a.iso(), b.iso()
    else:
        raise FormulaRuntimeError(
            f"Cannot compare {_type_name(a)} and {_type_name(b)} with '{op}'."
        )
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right


def _type_name(v: Value) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if _is_number(v):
        return "number"
    if isinstance(v, FormulaDate):
        return "date"
    return "text"


def _eval(node: object, value: Value) -> Value:
    if isinstance(node, _Lit):
        return node.value
    if isinstance(node, _ValueRef):
        return value
    if isinstance(node, _Unary):
        if node.op == "not":
            return not _to_bool_strict(_eval(node.operand, value))
        # unary minus
        return -_to_number(_eval(node.operand, value), ctx="negation")
    if isinstance(node, _Binary):
        return _eval_binary(node, value)
    if isinstance(node, _Call):
        return _eval_call(node, value)
    raise FormulaRuntimeError("Corrupt formula node.")


def _to_bool_strict(v: Value) -> bool:
    """``not`` / ``and`` / ``or`` / ``if`` require a real boolean - a non-bool
    is a fail-closed error, never coerced (foolproof)."""
    if isinstance(v, bool):
        return v
    raise FormulaRuntimeError(
        f"Expected a true/false value, got {_type_name(v)}."
    )


def _eval_binary(node: _Binary, value: Value) -> Value:
    op = node.op
    if op == "and":
        return _to_bool_strict(_eval(node.left, value)) and _to_bool_strict(
            _eval(node.right, value)
        )
    if op == "or":
        return _to_bool_strict(_eval(node.left, value)) or _to_bool_strict(
            _eval(node.right, value)
        )

    left = _eval(node.left, value)
    right = _eval(node.right, value)

    if op == "==":
        return _values_equal(left, right)
    if op == "!=":
        return not _values_equal(left, right)
    if op in ("<", "<=", ">", ">="):
        return _compare(op, left, right)
    if op == "&":
        return _stringify(left) + _stringify(right)
    # arithmetic
    ln = _to_number(left, ctx="arithmetic")
    rn = _to_number(right, ctx="arithmetic")
    if op == "+":
        return ln + rn
    if op == "-":
        return ln - rn
    if op == "*":
        return ln * rn
    if op == "/":
        if rn == 0.0:
            raise FormulaRuntimeError("Division by zero.")
        return ln / rn
    raise FormulaRuntimeError(f"Unknown operator {op!r}.")


def _eval_call(node: _Call, value: Value) -> Value:
    name = node.name
    if name == "if":
        cond = _to_bool_strict(_eval(node.args[0], value))
        # Lazy: only the taken branch is evaluated (so the untaken branch may
        # legitimately be an expression that would error on this input).
        return _eval(node.args[1], value) if cond else _eval(node.args[2], value)
    if name == "default":
        first = _eval(node.args[0], value)
        return first if first is not None else _eval(node.args[1], value)
    impl = _EAGER_FUNCS.get(name)
    if impl is None:
        raise FormulaRuntimeError(f"Unknown function {name!r}.")
    return impl([_eval(arg, value) for arg in node.args])


def evaluate_formula(formula: Union[str, ParsedFormula], value: Any) -> Value:
    """Evaluate ``formula`` with the input ``value`` and return a language value
    (None | bool | float | str | FormulaDate).

    Raises ``FormulaParseError`` if a raw string doesn't parse, and
    ``FormulaRuntimeError`` on any evaluation fault. The mapping path passes a
    non-blank ``value`` (blank is short-circuited to None upstream, mirroring the
    named transforms) and turns a raised error into a NAMED per-field failure.
    """
    parsed = formula if isinstance(formula, ParsedFormula) else parse_formula(formula)
    return _eval(parsed.ast, _to_formula_value(value))


def result_to_json(v: Value) -> Any:
    """A JSON-safe projection of an evaluated value, for the test-formula /
    simulate wires. A ``FormulaDate`` becomes its ISO string; an integer-valued
    number becomes an int for a clean wire."""
    if isinstance(v, FormulaDate):
        return v.iso()
    if _is_number(v):
        if v == int(v) and abs(v) < 1e15:  # type: ignore[arg-type]
            return int(v)  # type: ignore[arg-type]
        return v
    return v
