"""Rule-tree validation (sprint-2/02 D11) - save-time gate. Consumers call
``validate_tree(tree, sources)`` before persisting a condition tree into
their JSON column; a non-empty problem list = 422. Runtime stays fail-closed
(D5) for trees that go stale AFTER save.
"""
from typing import Any, Dict, List, Optional, Sequence

from app.rule_engine.evaluator import _MAX_DEPTH, CROSS_FACT_OPERATORS
from app.rule_engine.registry import FactDef, fact_map

# Operators offered per fact type (D3 - mirror of the frontend table).
OPERATORS_BY_TYPE: Dict[str, List[str]] = {
    "string": ["eq", "neq", "contains", "in", "not_in"],
    "number": ["eq", "neq", "gt", "gte", "lt", "lte", "between"],
    "boolean": ["is_true", "is_false"],
    "date": ["before", "after", "between"],
    "enum": ["eq", "neq", "in", "not_in"],
    "list": ["contains_any", "contains_all", "not_contains"],
}

_LIST_VALUE_OPERATORS = {"in", "not_in", "contains_any", "contains_all", "not_contains"}
_NO_VALUE_OPERATORS = {"is_true", "is_false"}


def validate_tree(
    tree: Optional[Dict[str, Any]], sources: Sequence[str]
) -> List[str]:
    """Problems with the tree against the registered facts - empty = valid.
    ``None`` trees are the consumer's "unconditional" case; don't call."""
    facts = fact_map(sources)
    problems: List[str] = []
    if not isinstance(tree, dict) or tree.get("kind") != "group":
        return ["Conditions must be a group."]
    _validate_group(tree, facts, 1, problems)
    return problems


def _validate_group(
    node: Dict[str, Any], facts: Dict[str, FactDef], depth: int, problems: List[str]
) -> None:
    if depth > _MAX_DEPTH:
        problems.append(
            f"Maximum nesting depth of {_MAX_DEPTH} exceeded - flatten the tree."
        )
        return
    if node.get("combinator") not in ("and", "or"):
        problems.append("Each group needs an and/or combinator.")
    rules = node.get("rules")
    if not isinstance(rules, list) or not rules:
        problems.append("Empty group - add a condition or remove the group.")
        return
    for rule in rules:
        if not isinstance(rule, dict):
            problems.append("Malformed rule entry.")
        elif rule.get("kind") == "group":
            _validate_group(rule, facts, depth + 1, problems)
        elif rule.get("kind") == "condition":
            _validate_condition(rule, facts, problems)
        else:
            problems.append("Each entry must be a condition or a group.")


def _validate_condition(
    node: Dict[str, Any], facts: Dict[str, FactDef], problems: List[str]
) -> None:
    key = node.get("fact")
    fact = facts.get(key)
    if fact is None:
        problems.append(f"Unknown field '{key}' - it may have been removed.")
        return

    operator = node.get("operator")
    allowed = OPERATORS_BY_TYPE.get(fact.type, [])
    if operator not in allowed:
        problems.append(
            f"Operator '{operator}' is not valid for {fact.label} ({fact.type})."
        )
        return

    value = node.get("value")
    if node.get("valueKind") == "fact":
        if operator not in CROSS_FACT_OPERATORS:
            problems.append(
                f"Operator '{operator}' cannot compare against another field."
            )
            return
        other = facts.get(value)
        if other is None:
            problems.append(f"Compared field '{value}' is unknown.")
        elif other.type != fact.type:
            problems.append(
                f"Cannot compare {fact.label} ({fact.type}) with "
                f"{other.label} ({other.type})."
            )
        return

    if operator in _NO_VALUE_OPERATORS:
        return
    if operator == "between":
        # Blank/garbage bounds would save clean but fail closed forever at
        # runtime - the edge becomes silently unfireable (code-review fix).
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(_blank(member) for member in value)
        ):
            problems.append(f"'{fact.label} between' needs exactly two values.")
        elif fact.type == "number" and any(
            not _numeric(member) for member in value
        ):
            problems.append(f"'{fact.label} between' values must be numbers.")
        return
    if operator in _LIST_VALUE_OPERATORS:
        if not isinstance(value, list) or not value:
            problems.append(f"'{fact.label}' needs at least one value to match.")
        return
    if _blank(value):
        problems.append(f"'{fact.label}' needs a value.")
    elif fact.type == "number" and operator in ("gt", "gte", "lt", "lte") and not _numeric(value):
        problems.append(f"'{fact.label}' needs a numeric value.")


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
            return True
        except ValueError:
            return False
    return False
