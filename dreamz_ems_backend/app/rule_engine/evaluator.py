"""Pure rule evaluator (sprint-2/02 D3–D5) — condition tree + fact dict →
bool. No I/O, no ORM. Fail closed, uniformly (D5): a missing or null fact, a
garbage value, an unknown operator or an over-deep tree makes that node
False — never an exception. The whole rule may still pass via an OR branch.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

# ONE nesting guard for every condition-tree walker in the system
# (code-review fix: was an independent literal here AND in filter_translator).
from app.services.filter_translator import MAX_GROUP_DEPTH as _MAX_DEPTH

# Scalar compare operators allowed in cross-fact mode (D4).
CROSS_FACT_OPERATORS = {"eq", "neq", "gt", "gte", "lt", "lte", "before", "after"}


def evaluate(tree: Optional[Dict[str, Any]], facts: Dict[str, Any]) -> bool:
    """True when the tree passes against the facts. None/empty = True
    (unconditional edge — today's behavior)."""
    if not tree or not tree.get("rules"):
        return True
    return _eval_group(tree, facts, depth=1)


def failed_conditions(
    tree: Optional[Dict[str, Any]], facts: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """The condition nodes that actually BLOCK the tree — feeds the specific
    409 message (D6). Combinator-aware (code-review fix): a failing leaf
    inside an OR group whose sibling already passed is irrelevant and is NOT
    listed — only failing leaves of failing groups count."""
    failed: List[Dict[str, Any]] = []
    if not tree:
        return failed

    def _walk(node: Dict[str, Any], depth: int) -> None:
        # Only called for groups that evaluate False — every rule inspected
        # here genuinely contributes to the block.
        if depth > _MAX_DEPTH:
            return
        for rule in node.get("rules", []):
            if rule.get("kind") == "group":
                if not _eval_group(rule, facts, depth + 1):
                    _walk(rule, depth + 1)
            elif not _eval_condition(rule, facts):
                failed.append(rule)

    if not _eval_group(tree, facts, 1):
        _walk(tree, 1)
    return failed


def collect_fact_keys(tree: Optional[Dict[str, Any]]) -> Set[str]:
    """Every fact key the tree reads (LHS + cross-fact RHS) — lets callers
    resolve only the facts a rule actually needs (code-review perf fix)."""
    keys: Set[str] = set()
    if not tree:
        return keys

    def _walk(node: Dict[str, Any], depth: int) -> None:
        if depth > _MAX_DEPTH:
            return
        for rule in node.get("rules", []):
            if rule.get("kind") == "group":
                _walk(rule, depth + 1)
            else:
                if rule.get("fact"):
                    keys.add(rule["fact"])
                if rule.get("valueKind") == "fact" and rule.get("value"):
                    keys.add(rule["value"])

    _walk(tree, 1)
    return keys


def _eval_group(node: Dict[str, Any], facts: Dict[str, Any], depth: int) -> bool:
    if depth > _MAX_DEPTH:
        return False
    results = (
        _eval_group(rule, facts, depth + 1)
        if rule.get("kind") == "group"
        else _eval_condition(rule, facts)
        for rule in node.get("rules", [])
    )
    if node.get("combinator") == "or":
        return any(results)
    return all(results)


def _eval_condition(node: Dict[str, Any], facts: Dict[str, Any]) -> bool:
    try:
        value = facts.get(node.get("fact"))
        if value is None:
            return False  # D5 — uniformly, including negative operators

        operand = node.get("value")
        if node.get("valueKind") == "fact":
            operand = facts.get(operand)
            if operand is None:
                return False

        return _apply(node.get("operator"), value, operand)
    except Exception:  # noqa: BLE001 — fail closed, never raise (D5)
        return False


def _apply(operator: Optional[str], value: Any, operand: Any) -> bool:
    if operator == "eq":
        return _eq(value, operand)
    if operator == "neq":
        return not _eq(value, operand)
    if operator == "contains":
        return str(operand).lower() in str(value).lower()
    if operator == "in":
        return any(_eq(value, item) for item in _as_list(operand))
    if operator == "not_in":
        return not any(_eq(value, item) for item in _as_list(operand))
    if operator in ("gt", "gte", "lt", "lte"):
        left, right = _comparable_pair(value, operand)
        if operator == "gt":
            return left > right
        if operator == "gte":
            return left >= right
        if operator == "lt":
            return left < right
        return left <= right
    if operator == "between":
        low, high = _as_list(operand)
        left, lo = _comparable_pair(value, low)
        _, hi = _comparable_pair(value, high)
        # Date-only END bound is inclusive of the whole day (code-review fix:
        # 'between …-01 and …-31' must not exclude records after midnight on
        # the 31st). Numbers and full datetimes are unaffected.
        if isinstance(hi, datetime) and _is_date_only(high):
            hi = hi + timedelta(days=1) - timedelta(microseconds=1)
        return lo <= left <= hi
    if operator == "before":
        return _as_dt(value) < _as_dt(operand)
    if operator == "after":
        return _as_dt(value) > _as_dt(operand)
    if operator == "is_true":
        return bool(value) is True
    if operator == "is_false":
        return bool(value) is False
    if operator == "contains_any":
        return bool(_str_set(value) & _str_set(_as_list(operand)))
    if operator == "contains_all":
        return _str_set(_as_list(operand)) <= _str_set(value)
    if operator == "not_contains":
        return not (_str_set(value) & _str_set(_as_list(operand)))
    return False  # unknown operator — fail closed


# ---- coercion helpers ----


def _eq(a: Any, b: Any) -> bool:
    number = _maybe_float(a)
    if number is not None:
        other = _maybe_float(b)
        return other is not None and number == other
    if isinstance(a, (datetime, date)):
        return _as_dt(a) == _as_dt(b)
    return str(a) == str(b)


def _maybe_float(x: Any) -> Optional[float]:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    # Decimal money/rate facts (sprint-4/07 Cluster F) — coerce to float for the
    # numeric comparison (a Numeric(14,4) value is < 2^53, so exact in float64).
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x)
        except ValueError:
            return None
    return None


def _comparable_pair(value: Any, operand: Any):
    """(value, operand) as floats, else as datetimes. Raises on garbage —
    the caller fails closed."""
    left = _maybe_float(value)
    right = _maybe_float(operand)
    if left is not None and right is not None:
        return left, right
    return _as_dt(value), _as_dt(operand)


def _as_dt(x: Any) -> datetime:
    if isinstance(x, datetime):
        dt = x
    elif isinstance(x, date):
        dt = datetime(x.year, x.month, x.day)
    elif isinstance(x, str):
        dt = datetime.fromisoformat(x.replace("Z", "+00:00"))
    else:
        raise ValueError(f"not a datetime: {x!r}")
    # Columns are aware-UTC since plan sprint-2/05; comparisons here run on
    # naive-UTC internally — both sides normalize through this function.
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _is_date_only(x: Any) -> bool:
    """A wire value like '2026-01-31' (no time part)."""
    return (isinstance(x, str) and len(x) == 10) or (
        isinstance(x, date) and not isinstance(x, datetime)
    )


def _as_list(x: Any) -> list:
    if not isinstance(x, list):
        raise ValueError("expected a list value")
    return x


def _str_set(items: Any) -> set:
    return {str(item) for item in items}
