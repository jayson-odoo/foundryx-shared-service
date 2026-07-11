"""Background-job wire schemas (sprint-4/10). camelCase via ApiModel (Z-suffixed
datetimes). Slice-1 ships the read schema; the /jobs router lands with the
migration engine (Slice 2/3)."""
from datetime import datetime
from typing import Optional

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel


class BackgroundJobOut(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenantId: str = Field(validation_alias="tenant_id")
    type: str
    status: str
    actorUserId: Optional[str] = Field(default=None, validation_alias="actor_user_id")
    payload: Optional[dict] = Field(default=None, validation_alias="payload_json")
    result: Optional[dict] = Field(default=None, validation_alias="result_json")
    cursor: Optional[dict] = Field(default=None, validation_alias="cursor_json")
    progressTotal: int = Field(validation_alias="progress_total")
    progressDone: int = Field(validation_alias="progress_done")
    progressFailed: int = Field(validation_alias="progress_failed")
    error: Optional[str] = None
    createdAt: datetime = Field(validation_alias="created_at")
    startedAt: Optional[datetime] = Field(default=None, validation_alias="started_at")
    finishedAt: Optional[datetime] = Field(default=None, validation_alias="finished_at")
