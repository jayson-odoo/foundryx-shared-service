"""Role schemas - list/detail/write contracts + assigned-users (plan 03).

Exposes camelCase to the frontend; reads snake_case off ORM via validation_alias.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel

from app.schemas.filters import FilterGroup


class RoleOut(ApiModel):
    """Lightweight role ref (id + name) - used by auth + the user role multi-select."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str


# ---- List / detail read models (counts computed in the service) ----


class RoleItem(ApiModel):
    id: str
    name: str
    description: Optional[str] = None
    isSystem: bool
    userCount: int
    permissionCount: int
    createdAt: datetime


class RoleDetail(RoleItem):
    permissionKeys: List[str] = []


class RoleListResponse(ApiModel):
    data: List[RoleItem]
    total: int
    page: int


class RoleNeighborResponse(ApiModel):
    role: Optional[RoleDetail] = None
    total: int


# ---- Assigned users ----


class RoleUserItem(ApiModel):
    id: str
    name: Optional[str] = None
    email: str
    avatar: Optional[str] = None
    status: str
    assignedAt: datetime


class AssignableUserItem(ApiModel):
    id: str
    name: Optional[str] = None
    email: str
    avatar: Optional[str] = None
    status: str


# ---- Write models ----


class RoleCreate(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=240)
    permissionKeys: List[str] = []
    isSystem: bool = False


class RoleUpdate(ApiModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=240)
    permissionKeys: Optional[List[str]] = None
    isSystem: Optional[bool] = None


class AssignUsersRequest(ApiModel):
    userIds: List[str]


class RoleExportRequest(ApiModel):
    columns: List[str]
    ids: Optional[List[str]] = None
    search: Optional[str] = None
    sortBy: Optional[str] = None
    sortDir: Optional[str] = None
    filter: Optional[FilterGroup] = None
