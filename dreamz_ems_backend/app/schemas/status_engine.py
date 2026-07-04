"""Status-engine schemas (sprint-2/01) — camelCase wire contracts.

The graph read returns the resolved tier (``source``: tenant fork vs platform
defaults) so the UI can surface "customized" vs "inherited".
"""
from datetime import date
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class StatusEntityItem(BaseModel):
    entityType: str
    label: str
    module: str
    platformOwned: bool
    requiredFlags: List[str]
    # Caller-tier stats for the entity list (sprint-2/01 UI rework).
    statusCount: int = 0
    transitionCount: int = 0
    # True when the caller's tenant forked this entity's set.
    customized: bool = False
    # True when the entity has time-based auto edges (sprint-4/03 Slice 6) —
    # gates the "Simulate date" admin tool in the UI.
    hasTimeAutoEdges: bool = False


class StatusEntityListResponse(BaseModel):
    data: List[StatusEntityItem]


class SimulateRequest(BaseModel):
    asOf: date
    apply: bool = False


class SimulateRow(BaseModel):
    id: str
    label: str
    fromId: Optional[str] = None
    toId: Optional[str] = None


class SimulateResponse(BaseModel):
    data: List[SimulateRow]
    applied: bool


class StatusItem(BaseModel):
    id: str
    entityType: str
    key: str
    label: str
    color: str
    sortOrder: int
    isInitial: bool
    isTerminal: bool
    isActive: bool
    blocksAccess: bool
    isArchived: bool
    isDefault: bool
    positionX: Optional[float] = None
    positionY: Optional[float] = None
    isSystem: bool
    recordCount: int = 0


class RecipientItem(BaseModel):
    targetType: Literal["USER", "ROLE", "DYNAMIC"]
    targetId: Optional[str] = None
    dynamicKey: Optional[Literal["ACTOR", "ASSIGNEE", "RECORD_OWNER"]] = None


class NotificationItem(BaseModel):
    channel: Literal["EMAIL", "IN_APP"] = "EMAIL"
    templateSubject: str = Field(min_length=1, max_length=300)
    templateBody: str = Field(min_length=1, max_length=10_000)
    templateKey: Optional[str] = None
    # Engine template reference (plan 07 D10) — set = render through the
    # template engine; inline subject/body stay as the fallback.
    templateId: Optional[str] = None
    # Per-use COPY of a template's block document (plan 10 follow-up) — set =
    # render this branded doc (subject = templateSubject), edited inline.
    doc: Optional[Dict[str, Any]] = None
    recipients: List[RecipientItem] = Field(min_length=1)


class TransitionRoleItem(BaseModel):
    id: str
    name: str


class TransitionItem(BaseModel):
    id: str
    entityType: str
    fromStatusId: str
    toStatusId: str
    label: str
    sortOrder: int
    roles: List[TransitionRoleItem] = []
    notifications: List[NotificationItem] = []
    # Rule-engine condition tree (sprint-2/02) — None = unconditional.
    conditionsJson: Optional[Dict[str, Any]] = None
    # Derived status (sprint-4/03) — 'manual' (user fires) | 'auto' (engine fires).
    triggerMode: Literal["manual", "auto"] = "manual"


class StatusGraphResponse(BaseModel):
    entityType: str
    # Which tier the caller sees — their fork or the platform defaults (D7).
    source: Literal["tenant", "platform"]
    statuses: List[StatusItem]
    transitions: List[TransitionItem]


class StatusFlags(BaseModel):
    """Trait flags (D2) — omitted = unchanged (update) / False (create)."""

    isInitial: Optional[bool] = None
    isTerminal: Optional[bool] = None
    isActive: Optional[bool] = None
    blocksAccess: Optional[bool] = None
    isArchived: Optional[bool] = None
    isDefault: Optional[bool] = None

    def to_columns(self) -> dict:
        mapping = {
            "isInitial": "is_initial",
            "isTerminal": "is_terminal",
            "isActive": "is_active",
            "blocksAccess": "blocks_access",
            "isArchived": "is_archived",
            "isDefault": "is_default",
        }
        return {
            mapping[name]: value
            for name, value in self.model_dump(exclude_none=True).items()
        }


class StatusCreateRequest(BaseModel):
    entityType: str
    # Scoped machines (sprint-3/01 D4) — the owning record (e.g. form id).
    scopeId: Optional[str] = None
    label: str = Field(min_length=1, max_length=80)
    color: str = Field(default="gray", max_length=40)
    key: Optional[str] = Field(default=None, min_length=1, max_length=80)
    flags: Optional[StatusFlags] = None
    positionX: Optional[float] = None
    positionY: Optional[float] = None


class StatusUpdateRequest(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=80)
    color: Optional[str] = Field(default=None, max_length=40)
    flags: Optional[StatusFlags] = None
    positionX: Optional[float] = None
    positionY: Optional[float] = None


class StatusReorderRequest(BaseModel):
    entityType: str
    scopeId: Optional[str] = None
    orderedIds: List[str] = Field(min_length=1)


class MigrateRecordsRequest(BaseModel):
    toStatusId: str


class MigrateRecordsResponse(BaseModel):
    migrated: int


class TransitionCreateRequest(BaseModel):
    entityType: str
    # Scoped machines (sprint-3/01 D4) — both endpoints must share this scope.
    scopeId: Optional[str] = None
    fromStatusId: str
    toStatusId: str
    label: str = Field(min_length=1, max_length=80)
    sortOrder: Optional[int] = None
    roleIds: List[str] = []
    notifications: List[NotificationItem] = []
    conditionsJson: Optional[Dict[str, Any]] = None
    # Derived status (sprint-4/03) — 'auto' requires conditions + no roles (422).
    triggerMode: Literal["manual", "auto"] = "manual"


class TransitionUpdateRequest(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=80)
    sortOrder: Optional[int] = None
    roleIds: Optional[List[str]] = None
    notifications: Optional[List[NotificationItem]] = None
    # PATCH semantics via model_fields_set: absent = keep, null = clear.
    conditionsJson: Optional[Dict[str, Any]] = None
    # Derived status (sprint-4/03) — absent = keep (PATCH semantics).
    triggerMode: Optional[Literal["manual", "auto"]] = None
