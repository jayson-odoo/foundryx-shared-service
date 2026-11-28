"""Dashboards wire shapes (contract section 3). snake_case, as the contract writes them; times ISO Z
via ``ApiModel``. Request bodies ignore unknown keys (a ``tenant`` / ``product`` echo is read by the
gateway auth, never trusted); the spec itself is checked by ``spec.py``, not by these models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints
from typing_extensions import Annotated

from app.schemas.base import ApiModel

ActorRef = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class Problem(BaseModel):
    path: str
    reason: str


class UserRef(BaseModel):
    user_ref: ActorRef


# -- requests --------------------------------------------------------------------------------------------

class TurnHistory(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class TurnRequest(BaseModel):
    actor_ref: ActorRef
    dashboard_id: Optional[str] = Field(default=None, max_length=64)
    draft: Dict[str, Any]
    message: str = Field(min_length=1, max_length=2000)
    turn_id: str = Field(min_length=1, max_length=64)
    images: List[Any] = Field(default_factory=list)  # checked by the builder: 422 images_invalid, not spec_invalid
    catalogue: Dict[str, Any]
    refusals: List[Dict[str, Any]] = Field(default_factory=list, max_length=50)
    history: List[TurnHistory] = Field(default_factory=list, max_length=10)


class SaveRequest(BaseModel):
    actor_ref: ActorRef
    dashboard_id: Optional[str] = Field(default=None, max_length=64)
    name: Name
    spec: Dict[str, Any]
    base_version: Optional[int] = Field(default=None, ge=1)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=128)  # null / omitted = no replay


class ShareRequest(BaseModel):
    actor_ref: ActorRef
    shared_with: List[UserRef] = Field(max_length=50)


class DeleteRequest(BaseModel):
    actor_ref: ActorRef


# -- responses -------------------------------------------------------------------------------------------

class DashboardOut(ApiModel):
    id: str
    name: str
    owner_ref: str
    mine: bool
    shared_with: List[UserRef]
    spec: Dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class DashboardWithProblemsOut(DashboardOut):
    spec_problems: List[Problem]


class DashboardListItem(ApiModel):
    id: str
    name: str
    owner_ref: str
    mine: bool
    shared: bool
    shared_count: int
    updated_at: datetime
    version: int


class DashboardList(BaseModel):
    items: List[DashboardListItem]
    total: int
    page: int
    limit: int


class VersionChange(BaseModel):
    field: str
    old: Any
    new: Any


class VersionItem(ApiModel):
    version: int
    action: str
    actor_ref: str
    at: datetime
    changes: List[VersionChange]


class VersionList(BaseModel):
    items: List[VersionItem]
    total: int
    page: int
    limit: int


class Deleted(BaseModel):
    deleted: bool


class Question(BaseModel):
    text: str
    options: List[str]


class TurnUsage(BaseModel):
    tokens_in: int
    tokens_out: int
    model: str


class TurnResponse(BaseModel):
    draft: Dict[str, Any]
    operations: Optional[List[Dict[str, Any]]] = None
    changed_tile_ids: List[str]
    reply: Optional[str] = None
    question: Optional[Question] = None
    need_entities: Optional[List[str]] = None  # lookup round (contract 3.1): only this, the draft and usage
    usage: TurnUsage


# -- staff keys ------------------------------------------------------------------------------------------

class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    product: Literal["sorento_crm", "ecohub"]


class KeyItem(ApiModel):
    id: str
    name: str
    product: str
    masked: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class KeyCreated(KeyItem):
    key: str


class KeyList(BaseModel):
    data: List[KeyItem]
