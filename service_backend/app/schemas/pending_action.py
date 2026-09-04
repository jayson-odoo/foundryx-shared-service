"""Deferred-actions wire schemas (sprint-4/23, T5) - camelCase, Z-suffixed
datetimes (AC-DLA-39/40)."""
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import ApiModel


class PendingActionCreate(BaseModel):
    actionKey: str
    entityType: str
    entityId: str
    payload: Optional[Dict[str, Any]] = None


class PendingActionOut(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    actionKey: str = Field(validation_alias="action_key")
    entityType: str = Field(validation_alias="entity_type")
    entityId: str = Field(validation_alias="entity_id")
    commitAt: datetime = Field(validation_alias="commit_at")
    windowSeconds: int = Field(validation_alias="window_seconds")
    requestedById: Optional[str] = Field(default=None, validation_alias="requested_by_id")
    requestedByName: Optional[str] = None


class PendingActionOutcomeOut(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    actionKey: str = Field(validation_alias="action_key")
    status: str
    errorText: Optional[str] = Field(default=None, validation_alias="error_text")
    endedAt: Optional[datetime] = Field(default=None, validation_alias="ended_at")


class PendingActionCurrentOut(ApiModel):
    pending: Optional[PendingActionOut] = None
    lastOutcome: Optional[PendingActionOutcomeOut] = None


class PendingActionCreateResponse(ApiModel):
    id: str
    commitAt: datetime
    windowSeconds: int


class PendingActionCancelResponse(ApiModel):
    id: str
    status: str
