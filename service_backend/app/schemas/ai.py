"""AI wire schemas — camelCase out, `ApiModel` for Z-suffixed datetimes."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.base import ApiModel


# ── agents ───────────────────────────────────────────────────────────────
class EquippedSkillOut(ApiModel):
    """One skill in an agent's equipped set (AC-BI-06b)."""

    id: str
    name: str


class AgentOut(ApiModel):
    id: str
    name: str
    description: str = ""
    connectionId: Optional[str] = Field(default=None, validation_alias="connection_id")
    # Denormalised for display — the list must show which credential an agent
    # uses without the client resolving it.
    connectionName: Optional[str] = None
    provider: Optional[str] = None
    model: str = ""
    temperature: float = 0.0
    # The equipped skill set (AC-BI-06b) — an agent equips MANY skills, like a
    # Claude agent's skill set. Which one RUNS a grill is slice 3's choice.
    skills: List[EquippedSkillOut] = []
    isEnabled: bool = Field(default=True, validation_alias="is_enabled")
    # Missing-prerequisite warning (AC-BI-06): the agent's connection is gone,
    # inactive or errored. The UI shows it; it is never a silent runtime failure.
    warning: Optional[str] = None
    createdAt: Optional[datetime] = Field(default=None, validation_alias="created_at")
    updatedAt: Optional[datetime] = Field(default=None, validation_alias="updated_at")

    model_config = {"from_attributes": True, "populate_by_name": True}


class AgentCreateRequest(BaseModel):
    name: str
    description: str = ""
    connectionId: Optional[str] = None
    model: str = ""
    temperature: float = 0.0
    skillIds: List[str] = []
    isEnabled: bool = True


class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    connectionId: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    # None = leave the equipped set unchanged; [] = clear it.
    skillIds: Optional[List[str]] = None
    isEnabled: Optional[bool] = None


class AgentListResponse(ApiModel):
    data: List[AgentOut]
    total: int
    page: int


class AgentNeighborResponse(ApiModel):
    agent: Optional[AgentOut] = None
    total: int


# ── skills ───────────────────────────────────────────────────────────────
class SkillVersionOut(ApiModel):
    id: str
    version: int
    body: str = ""
    isActive: bool = False
    createdByName: Optional[str] = None
    createdAt: Optional[datetime] = Field(default=None, validation_alias="created_at")

    model_config = {"from_attributes": True, "populate_by_name": True}


class SkillOut(ApiModel):
    id: str
    key: str
    name: str
    description: str = ""
    # The ACTIVE version's body — what an agent actually runs.
    body: str = ""
    activeVersionId: Optional[str] = Field(default=None, validation_alias="active_version_id")
    activeVersionNumber: Optional[int] = None
    versionCount: int = 0
    isSystem: bool = Field(default=False, validation_alias="is_system")
    # True when this row is the shared platform-tier default (tenant_id NULL).
    isPlatform: bool = False
    createdAt: Optional[datetime] = Field(default=None, validation_alias="created_at")
    updatedAt: Optional[datetime] = Field(default=None, validation_alias="updated_at")

    model_config = {"from_attributes": True, "populate_by_name": True}


class SkillCreateRequest(BaseModel):
    key: str
    name: str
    description: str = ""
    body: str = ""


class SkillUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    # A changed body mints a NEW immutable version + moves the active label.
    body: Optional[str] = None


class SkillListResponse(ApiModel):
    data: List[SkillOut]
    total: int
    page: int


class SkillNeighborResponse(ApiModel):
    skill: Optional[SkillOut] = None
    total: int


class SkillVersionListResponse(ApiModel):
    data: List[SkillVersionOut]
    total: int
    page: int


class SkillRollbackRequest(BaseModel):
    """Rollback = a LABEL MOVE, never a content copy (AC-BI-07)."""

    versionId: str


# ── models picker ────────────────────────────────────────────────────────
class ModelOptionOut(ApiModel):
    id: str
    label: str


class ModelListResponse(ApiModel):
    data: List[ModelOptionOut]
    # False when the live catalog call failed and the curated static list is
    # being served instead — the form still renders either way (AC-BI-05).
    isLive: bool = True
    message: Optional[str] = None


# ── traces ───────────────────────────────────────────────────────────────
class SpanOut(ApiModel):
    id: str
    parentId: Optional[str] = Field(default=None, validation_alias="parent_id")
    dottedOrder: str = Field(default="", validation_alias="dotted_order")
    spanKind: str = Field(validation_alias="span_kind")
    name: str = ""
    inputJson: Optional[Any] = Field(default=None, validation_alias="input_json")
    outputJson: Optional[Any] = Field(default=None, validation_alias="output_json")
    tokensIn: int = Field(default=0, validation_alias="tokens_in")
    tokensOut: int = Field(default=0, validation_alias="tokens_out")
    latencyMs: int = Field(default=0, validation_alias="latency_ms")
    status: str = "ok"
    error: Optional[str] = None
    startedAt: Optional[datetime] = Field(default=None, validation_alias="started_at")

    model_config = {"from_attributes": True, "populate_by_name": True}


class TraceOut(ApiModel):
    id: str
    conversationId: Optional[str] = Field(default=None, validation_alias="conversation_id")
    agentId: Optional[str] = Field(default=None, validation_alias="agent_id")
    agentName: str = Field(default="", validation_alias="agent_name")
    skillKey: Optional[str] = Field(default=None, validation_alias="skill_key")
    promptVersion: Optional[int] = Field(default=None, validation_alias="prompt_version")
    provider: str = ""
    model: str = ""
    tokensIn: int = Field(default=0, validation_alias="tokens_in")
    tokensOut: int = Field(default=0, validation_alias="tokens_out")
    latencyMs: int = Field(default=0, validation_alias="latency_ms")
    status: str = "ok"
    error: Optional[str] = None
    flagged: bool = False
    spanCount: int = Field(default=0, validation_alias="span_count")
    createdAt: Optional[datetime] = Field(default=None, validation_alias="created_at")

    model_config = {"from_attributes": True, "populate_by_name": True}


class TraceDetailOut(TraceOut):
    """Trace + its ordered flat step list (Bi-D17 — no tree renderer in v1)."""

    spans: List[SpanOut] = []


class TraceListResponse(ApiModel):
    data: List[TraceOut]
    total: int
    page: int


class TraceFlagRequest(BaseModel):
    flagged: bool


class ConnectionOptionOut(ApiModel):
    """An LLM connection the agent form may point at."""

    id: str
    name: str
    provider: str
    status: str
    isPlatform: bool = False


class AiPrerequisiteOut(ApiModel):
    """AC-BI-11: is any LLM connection configured at all?"""

    hasConnection: bool
    connections: List[ConnectionOptionOut] = []


class SkillOptionOut(ApiModel):
    id: str
    name: str


__all__ = [
    "AgentOut",
    "EquippedSkillOut",
    "AgentCreateRequest",
    "AgentUpdateRequest",
    "AgentListResponse",
    "AgentNeighborResponse",
    "SkillOut",
    "SkillVersionOut",
    "SkillCreateRequest",
    "SkillUpdateRequest",
    "SkillListResponse",
    "SkillNeighborResponse",
    "SkillVersionListResponse",
    "SkillRollbackRequest",
    "ModelOptionOut",
    "ModelListResponse",
    "SpanOut",
    "TraceOut",
    "TraceDetailOut",
    "TraceListResponse",
    "TraceFlagRequest",
    "ConnectionOptionOut",
    "AiPrerequisiteOut",
    "SkillOptionOut",
]
