"""Team schemas for the management list/form (plan 28 S1).

Field-level constraints on `name`/`members[].role` are deliberately loose
here (plain `str`) - ALL substantive validation (blank/too-long/duplicate
name, member role/tenant/dup checks) happens in `TeamService` so every
failure renders the SAME `{fieldErrors: {...}}` shape (AC-TEM-02/03/04)
instead of FastAPI's default `{detail: [...]}` pydantic-validation body.
"""
from datetime import datetime
from typing import List, Optional

from app.schemas.base import ApiModel

__all__ = [
    "TeamMemberRef",
    "TeamMemberInput",
    "TeamItem",
    "TeamListResponse",
    "TeamNeighborResponse",
    "TeamCreate",
    "TeamUpdate",
]


class TeamMemberRef(ApiModel):
    userId: str
    name: str
    email: str
    role: str


class TeamMemberInput(ApiModel):
    userId: str
    role: str = "member"


class TeamItem(ApiModel):
    id: str
    name: str
    description: Optional[str] = None
    isActive: bool
    sortOrder: int
    members: List[TeamMemberRef] = []
    memberCount: int = 0
    createdAt: datetime
    updatedAt: datetime


class TeamListResponse(ApiModel):
    data: List[TeamItem]
    total: int


class TeamNeighborResponse(ApiModel):
    team: Optional[TeamItem] = None
    total: int


class TeamCreate(ApiModel):
    name: str
    description: Optional[str] = None
    isActive: Optional[bool] = None
    sortOrder: Optional[int] = None
    members: List[TeamMemberInput] = []


class TeamUpdate(ApiModel):
    name: Optional[str] = None
    description: Optional[str] = None
    isActive: Optional[bool] = None
    sortOrder: Optional[int] = None
    members: Optional[List[TeamMemberInput]] = None
