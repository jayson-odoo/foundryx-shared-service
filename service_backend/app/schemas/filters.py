"""The recursive filter contract (mirrors the frontend's {combinator, rules} tree).

Lives in its own module so any resource schema (users, roles, …) can use it
without import cycles.

`extra="forbid"` (review round 1, plan 29 D-4) - a stray/unrecognised key on
a condition or group used to be silently dropped by pydantic's default
"ignore extra fields" behaviour; reject it instead, the same way an unknown
`field`/`operator` already 422s inside `translate_filter`. The frontend's
emitted shape (`filter-builder.tsx toFilterRule`) never carries anything
beyond these keys, so this tightens nothing a real client relies on.
"""
from typing import Any, List, Literal, Union

from pydantic import BaseModel, ConfigDict


class FilterCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["condition"]
    field: str
    operator: str
    value: Any = None


class FilterGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["group"]
    combinator: Literal["and", "or"]
    rules: List["FilterRule"] = []


FilterRule = Union[FilterCondition, "FilterGroup"]
FilterGroup.model_rebuild()


def has_leaf_condition(rule: "FilterRule") -> bool:
    """True if `rule` (a condition, or a group) contains at least one real
    `FilterCondition` leaf ANYWHERE in its tree - recursively, so a group
    whose only content is further empty sub-groups still counts as empty.
    A consumer for whom a vacuous filter is dangerous (plan 29 D-4: an empty
    broadcast audience filter silently resolved to "every contact in the
    workspace") should reject `not has_leaf_condition(tree)` at save time;
    consumers for whom "empty = unfiltered, show everything" is the correct,
    intended UX (a plain resource list's filter bar) do NOT call this."""
    if isinstance(rule, FilterCondition):
        return True
    return any(has_leaf_condition(r) for r in rule.rules)
