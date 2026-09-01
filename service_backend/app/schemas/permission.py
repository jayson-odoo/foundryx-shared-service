"""Permission catalog schemas - the grouped shape the role Permissions tab reads."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PermissionActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    action: str
    actionLabel: str = Field(validation_alias="action_label")
    description: Optional[str] = None


class PermissionResourceOut(BaseModel):
    """One resource (matrix row) + its available actions, owned by a module."""

    resource: str
    resourceLabel: str
    module: str
    actions: List[PermissionActionOut] = []
