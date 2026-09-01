"""User schemas for the management list/form."""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import ConfigDict, EmailStr, Field, field_validator

from app.schemas.base import ApiModel

from app.schemas.filters import FilterCondition, FilterGroup, FilterRule  # re-exported
from app.schemas.password import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    validate_password_strength,
)
from app.schemas.role import RoleOut

__all__ = [
    "FilterCondition",
    "FilterGroup",
    "FilterRule",
    "UserItem",
    "UserListResponse",
    "NeighborResponse",
    "UserCreate",
    "UserUpdate",
    "IdsRequest",
    "SetPasswordRequest",
    "ExportRequest",
]


# ---- User read models ----


class UserItem(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenantId: str = Field(validation_alias="tenant_id")
    name: Optional[str] = None
    email: EmailStr
    status: str
    avatar: Optional[str] = None
    roles: List[RoleOut] = []
    createdAt: datetime = Field(validation_alias="created_at")
    lastSignInAt: Optional[datetime] = Field(default=None, validation_alias="last_sign_in_at")
    emailVerifiedAt: Optional[datetime] = Field(default=None, validation_alias="email_verified_at")
    isTrashed: bool = Field(validation_alias="is_trashed")


class UserListResponse(ApiModel):
    data: List[UserItem]
    total: int
    page: int


class NeighborResponse(ApiModel):
    user: Optional[UserItem] = None
    total: int


# ---- Write models ----


class UserCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    roleIds: List[str] = []
    status: Literal["ACTIVE", "INACTIVE", "BLOCKED"] = "ACTIVE"


class UserUpdate(ApiModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    # Admin instant path (plan sprint-2/04): applies immediately + notifies
    # both addresses. Self-edit is rejected (409) - own email goes through the
    # dual-confirmation ceremony (/me/change-email), no self-bypass.
    email: Optional[EmailStr] = None
    roleIds: Optional[List[str]] = None
    status: Optional[Literal["ACTIVE", "INACTIVE", "BLOCKED"]] = None


class IdsRequest(ApiModel):
    ids: List[str]


class SetPasswordRequest(ApiModel):
    token: str
    # Full server-side policy (plan 10 §3) - mirrors the frontend password
    # schema; 72-byte cap protects bcrypt (see app/security.py).
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    _password_policy = field_validator("password")(validate_password_strength)


class ExportRequest(ApiModel):
    columns: List[str]
    ids: Optional[List[str]] = None
    search: Optional[str] = None
    sortBy: Optional[str] = None
    sortDir: Optional[Literal["asc", "desc"]] = None
    statusView: Literal["active", "trashed"] = "active"
    filter: Optional[FilterGroup] = None
