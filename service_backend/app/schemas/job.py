"""Background-job wire schemas (sprint-4/10) - camelCase, Z-suffixed datetimes.

``JobOut`` surfaces the generic ``background_jobs`` row for the Jobs drawer /
list; the storage-migration start takes the new-bucket connection config.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import ApiModel


class JobOut(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    tenantId: str = Field(validation_alias="tenant_id")
    type: str
    status: str
    actorUserId: Optional[str] = Field(default=None, validation_alias="actor_user_id")
    payload: Optional[Dict[str, Any]] = Field(default=None, validation_alias="payload_json")
    result: Optional[Dict[str, Any]] = Field(default=None, validation_alias="result_json")
    logs: Optional[List[Dict[str, Any]]] = Field(default=None, validation_alias="logs_json")
    progressTotal: int = Field(validation_alias="progress_total")
    progressDone: int = Field(validation_alias="progress_done")
    progressFailed: int = Field(validation_alias="progress_failed")
    error: Optional[str] = None
    createdAt: datetime = Field(validation_alias="created_at")
    startedAt: Optional[datetime] = Field(default=None, validation_alias="started_at")
    finishedAt: Optional[datetime] = Field(default=None, validation_alias="finished_at")


class JobListResponse(ApiModel):
    items: List[JobOut]
    total: int


class StorageMigrationStartRequest(BaseModel):
    provider: str
    name: str
    config: Dict[str, str]
    credentials: Dict[str, str] = Field(default_factory=dict)


class StorageMigrationTestRequest(BaseModel):
    """Non-destructive pre-create probe of a candidate new bucket (wizard Test
    step). No ``name`` - nothing is persisted."""

    provider: str
    config: Dict[str, str]
    credentials: Dict[str, str] = Field(default_factory=dict)


class StorageMigrationTestResult(BaseModel):
    ok: bool
    message: str
