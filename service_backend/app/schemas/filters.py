"""The recursive filter contract (mirrors the frontend's {combinator, rules} tree).

Lives in its own module so any resource schema (users, roles, …) can use it
without import cycles.
"""
from typing import Any, List, Literal, Union

from pydantic import BaseModel


class FilterCondition(BaseModel):
    kind: Literal["condition"]
    field: str
    operator: str
    value: Any = None


class FilterGroup(BaseModel):
    kind: Literal["group"]
    combinator: Literal["and", "or"]
    rules: List["FilterRule"] = []


FilterRule = Union[FilterCondition, "FilterGroup"]
FilterGroup.model_rebuild()
