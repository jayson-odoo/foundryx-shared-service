"""Lead Capture wire shapes (camelCase, ISO-Z). The consumer guide
(``documentation/lead-capture/consumer-integration-guide.md``) is the contract
of record for every gateway shape here: change one, change the guide."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import ApiModel


class ConnectFacebookRequest(BaseModel):
    pageId: str = Field(min_length=1, max_length=64)
    systemUserToken: str = Field(min_length=1, max_length=4096)
    formsMode: str = "all"

    def __repr__(self) -> str:  # the token never reaches a repr / log line
        return f"ConnectFacebookRequest(pageId={self.pageId!r}, formsMode={self.formsMode!r})"

    __str__ = __repr__


class FormNotice(BaseModel):
    formId: str
    formName: Optional[str] = None
    unmappedCount: int = 0


class ConsumerField(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=200)
    type: str = "text"


class ConsumerFieldList(BaseModel):
    data: List[ConsumerField]
    isDefault: bool = False


class FormQuestionOption(BaseModel):
    key: str
    value: str


class FormQuestion(BaseModel):
    key: str
    label: str
    type: str
    options: List[FormQuestionOption] = []


class FormQuestionList(BaseModel):
    formId: str
    formName: Optional[str] = None
    data: List[FormQuestion]


class TestLeadRequest(BaseModel):
    formId: str = Field(min_length=1, max_length=64)


class TestLeadAccepted(BaseModel):
    formId: str


class FieldMapUpdate(BaseModel):
    formId: str = Field(min_length=1, max_length=64)
    map: Dict[str, Optional[str]]


class SourceItem(ApiModel):
    id: str
    platform: str
    name: str
    status: str
    pageId: Optional[str] = None
    pageName: Optional[str] = None
    formsMode: Optional[str] = None
    formIds: List[str] = []
    needsMapping: List[FormNotice] = []
    fieldMap: Dict[str, Dict[str, str]] = {}
    lastLeadAt: Optional[datetime] = None
    backfillLastRunAt: Optional[datetime] = None
    backfillLastError: Optional[str] = None
    createdAt: datetime


class SourceList(BaseModel):
    data: List[SourceItem]


class SettingsItem(ApiModel):
    allowSharedPages: bool
    updatedAt: Optional[datetime] = None


class SettingsUpdate(BaseModel):
    allowSharedPages: bool


class KeyCreate(BaseModel):
    name: str = Field(default="", max_length=200)


class KeyItem(ApiModel):
    id: str
    name: str
    keyMasked: str
    createdAt: datetime
    lastUsedAt: Optional[datetime] = None
    revokedAt: Optional[datetime] = None


class KeyCreated(KeyItem):
    key: str  # shown once


class KeyList(BaseModel):
    data: List[KeyItem]


class WebhookCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    events: List[str] = ["lead.created"]


class WebhookItem(ApiModel):
    id: str
    url: str
    events: List[str]
    createdAt: datetime
    lastSuccessAt: Optional[datetime] = None


class WebhookCreated(WebhookItem):
    secret: str  # shown once


class WebhookList(BaseModel):
    data: List[WebhookItem]


class DeliveryItem(ApiModel):
    id: str
    leadId: Optional[str] = None
    event: str
    status: str
    attempt: int
    nextAttemptAt: Optional[datetime] = None
    lastStatusCode: Optional[int] = None
    lastError: Optional[str] = None


class LeadPage(BaseModel):
    data: List[Dict[str, Any]]
    nextCursor: Optional[str] = None
    hasMore: bool = False


# ── lane L-B: forms, backfill, history ──────────────────────────────────────

class FormItem(ApiModel):
    id: str
    name: Optional[str] = None
    status: Optional[str] = None
    createdAt: Optional[datetime] = None


class FormList(BaseModel):
    formsMode: str
    formIds: List[str] = []
    tosAccepted: Optional[bool] = None
    data: List[FormItem]


class FormsUpdate(BaseModel):
    formsMode: str = Field(max_length=16)
    formIds: List[str] = Field(default_factory=list, max_length=500)


class BackfillAccepted(BaseModel):
    sourceId: str


class EventActor(BaseModel):
    type: str
    name: str


class SourceEventItem(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    action: str
    actor: EventActor
    onBehalfOf: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    createdAt: datetime


class SourceEventList(BaseModel):
    data: List[SourceEventItem]
