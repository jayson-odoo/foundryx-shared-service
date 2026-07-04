"""Condition tree → human sentences (sprint-2/02). Consumers: the
``TransitionConditionsNotMet`` 409 message (failed conditions only) and the
Rules observability list ``summary`` column.
"""
from typing import Any, Dict, Optional

from app.rule_engine.registry import FactDef

# KEEP IN SYNC with the operator enum: OPERATORS_BY_TYPE (schemas.py) and the
# frontend builder labels (service_frontend/types/rules.ts RULE_OPERATORS).
# Wording intentionally differs (builder = terse UI labels, prose = sentences)
# but every operator key must exist in BOTH tables — a missing entry leaks the
# raw key ("amount starts_with 5") into 409s and the Rules page.
_PHRASES = {
    "eq": "is",
    "neq": "is not",
    "contains": "contains",
    "in": "is any of",
    "not_in": "is none of",
    "gt": "must be greater than",
    "gte": "must be at least",
    "lt": "must be less than",
    "lte": "must be at most",
    "between": "must be between",
    "before": "before",
    "after": "after",
    "is_true": "is yes",
    "is_false": "is no",
    "contains_any": "contains any of",
    "contains_all": "contains all of",
    "not_contains": "contains none of",
}


def condition_text(node: Dict[str, Any], facts: Dict[str, FactDef]) -> str:
    fact = facts.get(node.get("fact"))
    label = fact.label if fact else str(node.get("fact"))
    phrase = _PHRASES.get(node.get("operator"), str(node.get("operator")))
    value = _value_text(node, facts)
    return f"{label} {phrase} {value}".strip() if value else f"{label} {phrase}"


def tree_text(tree: Optional[Dict[str, Any]], facts: Dict[str, FactDef]) -> str:
    """"A AND (B OR C)" — nested groups parenthesized."""
    if not tree or not tree.get("rules"):
        return "Always allowed"
    return _group_text(tree, facts, top=True)


def _group_text(node: Dict[str, Any], facts: Dict[str, FactDef], *, top: bool) -> str:
    joiner = " OR " if node.get("combinator") == "or" else " AND "
    parts = [
        _group_text(rule, facts, top=False)
        if rule.get("kind") == "group"
        else condition_text(rule, facts)
        for rule in node.get("rules", [])
    ]
    text = joiner.join(parts)
    return text if top or len(parts) <= 1 else f"({text})"


def _value_text(node: Dict[str, Any], facts: Dict[str, FactDef]) -> str:
    operator = node.get("operator")
    if operator in ("is_true", "is_false"):
        return ""
    value = node.get("value")
    if node.get("valueKind") == "fact":
        other = facts.get(value)
        return other.label if other else str(value)
    if operator == "between" and isinstance(value, list) and len(value) == 2:
        return f"{value[0]} and {value[1]}"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value) if value is not None else ""
