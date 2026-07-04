"""Generic recursive filter → SQLAlchemy clause translator.

Entity-agnostic: the caller passes a **whitelist column map** (filter field →
ORM column) and an optional `special` resolver for non-column fields (e.g. a
many-to-many membership). Unknown fields raise FilterError, so a client can never
reach arbitrary columns. Used by both Users and Roles (each supplies its own map).
"""
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from sqlalchemy import and_, not_, or_  # noqa: F401 (or_/not_ used by callers' specials)

from app.schemas.filters import FilterCondition, FilterGroup, FilterRule

# field -> SQLAlchemy column (whitelist). Special resolver handles the rest.
ColumnMap = Dict[str, Any]
# Resolve a non-column field to a clause, or return None to fall through.
SpecialResolver = Callable[[FilterCondition], Optional[Any]]

# Guard against absurd nesting from a hostile client. Exported as the ONE
# depth cap for every condition-tree walker (rule engine imports it too).
MAX_GROUP_DEPTH = 5
_MAX_DEPTH = MAX_GROUP_DEPTH


class FilterError(Exception):
    """Invalid filter field/operator/value."""


def _to_dt(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise FilterError(f"invalid date: {value!r}") from exc


def _condition_clause(cond: FilterCondition, columns: ColumnMap, special: Optional[SpecialResolver]):
    # Entity-specific fields (e.g. M2M membership) get first refusal.
    if special is not None:
        clause = special(cond)
        if clause is not None:
            return clause

    col = columns.get(cond.field)
    if col is None:
        raise FilterError(f"field not filterable: {cond.field}")

    op, val = cond.operator, cond.value
    if op == "contains":
        return col.ilike(f"%{val}%")
    if op == "eq":
        return col == val
    if op == "neq":
        return col != val
    if op == "in":
        values = val if isinstance(val, list) else [val]
        return col.in_(values)
    if op == "before":
        return col < _to_dt(val)
    if op == "after":
        return col > _to_dt(val)
    if op == "between":
        if not isinstance(val, list) or len(val) < 2:
            raise FilterError("between requires [from, to]")
        return and_(col >= _to_dt(val[0]), col <= _to_dt(val[1]))
    if op == "is_true":
        return col.is_(True)
    if op == "is_false":
        return col.is_(False)
    raise FilterError(f"unknown operator: {op}")


def _rule_clause(rule: FilterRule, depth: int, columns: ColumnMap, special: Optional[SpecialResolver]):
    if rule.kind == "group":
        return _group_clause(rule, depth + 1, columns, special)
    return _condition_clause(rule, columns, special)


def _group_clause(group: FilterGroup, depth: int, columns: ColumnMap, special: Optional[SpecialResolver]):
    if depth > _MAX_DEPTH:
        raise FilterError("filter nested too deeply")
    clauses = [_rule_clause(r, depth, columns, special) for r in group.rules]
    clauses = [c for c in clauses if c is not None]
    if not clauses:
        return None
    return and_(*clauses) if group.combinator == "and" else or_(*clauses)


def translate_filter(
    group: Optional[FilterGroup],
    columns: ColumnMap,
    special: Optional[SpecialResolver] = None,
):
    """Return a SQLAlchemy clause for `group` over the whitelisted `columns`
    (+ optional `special` resolver), or None if empty/absent."""
    if group is None:
        return None
    return _group_clause(group, 0, columns, special)
