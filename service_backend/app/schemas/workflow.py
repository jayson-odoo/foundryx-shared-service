"""Workflow engine wire schemas (plan sprint-2/08) - camelCase out (mirror of
frontend ``types/workflows.ts``). Requests use camel field names directly."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.workflow import Workflow, WorkflowRun, WorkflowRunNode, WorkflowVersion
from app.schemas.base import ApiModel


def _duration_ms(start: Optional[datetime], end: Optional[datetime]) -> Optional[int]:
    if start is None or end is None:
        return None
    return int((end - start).total_seconds() * 1000)


# ---- output ----


class WorkflowSettingsOut(ApiModel):
    run_retention_days: int = Field(serialization_alias="runRetentionDays")
    is_default: bool = Field(serialization_alias="isDefault")


class WorkflowSettingsUpdate(BaseModel):
    runRetentionDays: int = Field(ge=1, le=3650)


class WorkflowVersionSummaryOut(ApiModel):
    id: str
    version_number: int = Field(serialization_alias="versionNumber")
    published_at: datetime = Field(serialization_alias="publishedAt")
    published_by_name: str = Field(serialization_alias="publishedByName")
    notes: Optional[str] = None

    @classmethod
    def from_row(cls, v: WorkflowVersion, published_by_name: str = "") -> "WorkflowVersionSummaryOut":
        return cls(
            id=v.id,
            version_number=v.version_number,
            published_at=v.published_at,
            published_by_name=published_by_name or "-",
            notes=v.notes,
        )


class WorkflowListItemOut(ApiModel):
    id: str
    name: str
    description: str
    is_active: bool = Field(serialization_alias="isActive")
    is_trashed: bool = Field(serialization_alias="isTrashed")
    trigger_type: str = Field(serialization_alias="triggerType")
    trigger_label: str = Field(serialization_alias="triggerLabel")
    current_version_number: Optional[int] = Field(serialization_alias="currentVersionNumber")
    has_unpublished_changes: bool = Field(serialization_alias="hasUnpublishedChanges")
    last_run_at: Optional[datetime] = Field(serialization_alias="lastRunAt")
    last_run_status: Optional[str] = Field(serialization_alias="lastRunStatus")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class WorkflowDetailOut(WorkflowListItemOut):
    draft_definition: Dict[str, Any] = Field(serialization_alias="draftDefinition")
    current_version_id: Optional[str] = Field(serialization_alias="currentVersionId")
    current_version: Optional[WorkflowVersionSummaryOut] = Field(serialization_alias="currentVersion")
    created_by_name: str = Field(serialization_alias="createdByName")
    created_at: datetime = Field(serialization_alias="createdAt")


class WorkflowListResponse(ApiModel):
    data: List[WorkflowListItemOut]
    total: int
    page: int


class WorkflowNeighborResponse(ApiModel):
    workflow: Optional[WorkflowListItemOut] = None
    total: int


class WorkflowRunItemOut(ApiModel):
    id: str
    status: str
    triggered_by: str = Field(serialization_alias="triggeredBy")
    is_test: bool = Field(serialization_alias="isTest")
    actor_name: str = Field(serialization_alias="actorName")
    started_at: Optional[datetime] = Field(serialization_alias="startedAt")
    finished_at: Optional[datetime] = Field(serialization_alias="finishedAt")
    duration_ms: Optional[int] = Field(serialization_alias="durationMs")
    version_number: int = Field(serialization_alias="versionNumber")
    error: Optional[str] = None
    created_at: datetime = Field(serialization_alias="createdAt")

    @classmethod
    def from_row(cls, r: WorkflowRun, actor_name: str = "") -> "WorkflowRunItemOut":
        return cls(
            id=r.id,
            status=r.status,
            triggered_by=r.triggered_by,
            is_test=r.is_test,
            actor_name=actor_name or "-",
            started_at=r.started_at,
            finished_at=r.finished_at,
            duration_ms=_duration_ms(r.started_at, r.finished_at),
            version_number=r.version_number,
            error=r.error,
            created_at=r.created_at,
        )


class WorkflowRunNodeOut(ApiModel):
    node_id: str = Field(serialization_alias="nodeId")
    node_type: str = Field(serialization_alias="nodeType")
    status: str
    input_json: Optional[Dict[str, Any]] = Field(serialization_alias="inputJson")
    output_json: Optional[Dict[str, Any]] = Field(serialization_alias="outputJson")
    error: Optional[str] = None
    started_at: Optional[datetime] = Field(serialization_alias="startedAt")
    finished_at: Optional[datetime] = Field(serialization_alias="finishedAt")

    @classmethod
    def from_row(cls, n: WorkflowRunNode) -> "WorkflowRunNodeOut":
        return cls(
            node_id=n.node_id,
            node_type=n.node_type,
            status=n.status,
            input_json=n.input_json,
            output_json=n.output_json,
            error=n.error,
            started_at=n.started_at,
            finished_at=n.finished_at,
        )


class WorkflowRunDetailOut(WorkflowRunItemOut):
    definition: Dict[str, Any]
    trigger_payload: Dict[str, Any] = Field(serialization_alias="triggerPayload")
    nodes: List[WorkflowRunNodeOut]


class WorkflowRunListResponse(ApiModel):
    data: List[WorkflowRunItemOut]
    total: int
    page: int


class WorkflowVersionListResponse(ApiModel):
    data: List[WorkflowVersionSummaryOut]
    total: int
    page: int


class TemplateOptionOut(ApiModel):
    value: str
    label: str


class WorkflowDebugResultOut(ApiModel):
    nodes: List[WorkflowRunNodeOut]


# ---- requests (camelCase field names - frontend sends these) ----


class WorkflowCreateRequest(BaseModel):
    name: str
    description: str = ""
    draftDefinition: Dict[str, Any] = Field(default_factory=dict)


class WorkflowUpdateRequest(BaseModel):
    name: str
    description: str = ""
    draftDefinition: Dict[str, Any] = Field(default_factory=dict)


class WorkflowActiveRequest(BaseModel):
    isActive: bool


class WorkflowTestTriggerRequest(BaseModel):
    """Module-owned test data envelope.

    Core validates the discriminant and preserves the remaining camelCase
    fields; the selected trigger's registered callback owns their strict
    schema and tenant-scoped resolution.
    """

    model_config = ConfigDict(extra="allow")

    type: str = Field(min_length=1, max_length=120)


class WorkflowRunRequest(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)
    isTest: bool = False
    testTrigger: Optional[WorkflowTestTriggerRequest] = None


class WorkflowDebugRequest(BaseModel):
    runId: str
    targetNodeId: str
    scratch: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    staleNodeIds: List[str] = Field(default_factory=list)
