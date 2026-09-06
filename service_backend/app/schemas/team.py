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
    "MyTeamMemberRef",
    "MyTeamItem",
]


class TeamMemberRef(ApiModel):
    userId: str
    name: str
    email: str
    role: str


class MyTeamMemberRef(ApiModel):
    """`GET /teams/mine` member shape (review round 1, finding 7) - NO email.
    That route is authenticated-only (no `teams.read`), so it must never
    leak teammates' email addresses to a caller who only holds the plain
    `teams.of_user@1`-equivalent self-read - `TeamMemberRef` (the admin
    shape) carries `email` and is reserved for `teams.read` holders."""

    userId: str
    name: str
    role: str


class MyTeamItem(ApiModel):
    """Trimmed `GET /teams/mine` team shape - `{id, name, isActive,
    memberCount, members}`, no `description`/`sortOrder`/timestamps and no
    member emails (finding 7)."""

    id: str
    name: str
    isActive: bool
    memberCount: int = 0
    members: List[MyTeamMemberRef] = []


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
    page: int = 0


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
