"""Lead Capture wire shapes (camelCase, ISO-Z). The consumer guide
(``documentation/lead-capture/consumer-integration-guide.md``) is the contract
of record for every gateway shape here: change one, change the guide."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

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


class SourceItem(ApiModel):
    id: str
    platform: str
    name: str
    status: str
    pageId: Optional[str] = None
    pageName: Optional[str] = None
    formsMode: Optional[str] = None
    needsMapping: List[FormNotice] = []
    lastLeadAt: Optional[datetime] = None
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
