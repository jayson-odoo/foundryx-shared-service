"""Template engine wire schemas (camelCase, plan 07)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import ApiModel


class TemplateItem(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    key: str
    name: str
    type: str
    context: str
    context_label: str = Field(serialization_alias="contextLabel")
    tier: str
    is_system: bool = Field(serialization_alias="isSystem")
    subject: str
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class TemplateDetail(TemplateItem):
    doc: Dict[str, Any]


class TemplateListResponse(BaseModel):
    data: List[TemplateItem]
    total: int
    page: int


class TemplateNeighborResponse(BaseModel):
    template: Optional[TemplateItem]
    total: int


class TemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(default="", max_length=500)
    context: str
    doc: Dict[str, Any]
    # F2 slice 2: 'email' (default) | 'document' | 'badge' (canvas-doc surface).
    type: str = Field(default="email", pattern="^(email|document|badge)$")


class TemplateUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(default="", max_length=500)
    doc: Dict[str, Any]


class TemplatePreviewRequest(BaseModel):
    subject: str = Field(default="", max_length=500)
    context: str
    doc: Dict[str, Any]
    # F2 (plan sprint-3/03 D7): "html" = email HTML preview (default, unchanged);
    # "pdf"/"docHtml" = flowing-document surface (slice 1); "canvasPdf"/
    # "canvasHtml" = fixed-canvas badge surface (slice 2). PDF flavors render →
    # application/pdf inline (download flavor via the ?download query param).
    format: str = Field(
        default="html", pattern="^(html|pdf|docHtml|canvasPdf|canvasHtml)$"
    )


class TemplatePreviewResponse(BaseModel):
    subject: str
    html: str
    text: str


class TemplateTestSendResponse(BaseModel):
    to_email: str = Field(serialization_alias="toEmail")


class ContextFactOut(BaseModel):
    key: str
    label: str
    sample: str


class ListFactOut(BaseModel):
    key: str
    label: str
    item_facts: List[ContextFactOut] = Field(serialization_alias="itemFacts")


class TemplateContextOut(BaseModel):
    key: str
    label: str
    fact_sources: List[str] = Field(serialization_alias="factSources")
    facts: List[ContextFactOut]
    list_facts: List[ListFactOut] = Field(default_factory=list, serialization_alias="listFacts")
    required_facts: List[str] = Field(serialization_alias="requiredFacts")
