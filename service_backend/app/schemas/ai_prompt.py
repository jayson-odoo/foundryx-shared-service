"""AI prompt registry wire schemas (Meetings S4, R4/R5).

Field names match `service_frontend/types/ai-prompt.ts` verbatim (the FE was
built against that contract first, Phase 1) - camelCase out, `ApiModel` for
Z-suffixed datetimes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.base import ApiModel


class AiPromptSummaryOut(ApiModel):
    """One row of `GET /ai-prompts`. `registry.list_prompts` returns
    snake_case dicts (service-layer convention); `validation_alias` +
    `populate_by_name` let the row build straight from `**row` without a
    manual rename, matching `app/schemas/ai.py`'s convention."""

    name: str
    productionVersion: Optional[int] = Field(default=None, validation_alias="production_version")
    latestVersion: Optional[int] = Field(default=None, validation_alias="latest_version")
    updatedAt: Optional[datetime] = Field(default=None, validation_alias="updated_at")
    updatedByName: Optional[str] = Field(default=None, validation_alias="updated_by_name")

    model_config = {"populate_by_name": True}


class AiPromptVersionOut(ApiModel):
    """One immutable version, as it appears in a prompt's version history."""

    id: str
    version: int
    template: str
    commitMessage: Optional[str] = Field(default=None, validation_alias="commit_message")
    createdByName: Optional[str] = Field(default=None, validation_alias="created_by_name")
    createdAt: Optional[datetime] = Field(default=None, validation_alias="created_at")
    labels: List[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class AiPromptDetailOut(ApiModel):
    """`GET /ai-prompts/{name}` - the full version history + label pointers."""

    name: str
    variables: List[str] = Field(default_factory=list)
    labels: Dict[str, Optional[int]] = Field(default_factory=dict)
    versions: List[AiPromptVersionOut] = Field(default_factory=list)


class CreatePromptVersionRequest(BaseModel):
    template: str
    commitMessage: str


class PublishPromptVersionRequest(BaseModel):
    versionId: str
    label: str
