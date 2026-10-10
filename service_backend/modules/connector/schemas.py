"""Connector admin wire schemas (camelCase names are fixed - the UI is built to them)."""

from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from pydantic import Field

from app.schemas.base import ApiModel


class GrantItem(ApiModel):
    id: str
    status: str
    product: str
    productName: str
    productUserId: str
    userName: Optional[str] = None
    userEmail: Optional[str] = None
    clientName: Optional[str] = None
    grantedAt: datetime
    consentedAt: datetime
    lastUsedAt: Optional[datetime] = None
    calls30d: int = 0
    revokedReason: Optional[str] = None


class GrantPage(ApiModel):
    data: List[GrantItem]
    total: int
    page: int


class CallItem(ApiModel):
    id: str
    tool: str
    statusCode: Optional[int] = None
    rows: Optional[int] = None
    chars: Optional[int] = None
    ms: int
    truncated: bool = False
    at: datetime
    # not part of the fixed wire but needed by the activity view: ok|error + code
    status: str
    errorCode: Optional[str] = None
    args: Optional[str] = None


class EventItem(ApiModel):
    id: str
    type: str
    at: datetime
    detail: Optional[str] = None


class Activity(ApiModel):
    calls: List[CallItem]
    events: List[EventItem]


class ToolSummary(ApiModel):
    name: str
    method: str
    path: str


class SecretState(ApiModel):
    ssToProduct: str
    productToSs: str


class ProductItem(ApiModel):
    key: str
    displayName: str
    mcpUrl: str
    consentUrl: str
    apiBase: str
    manifestVersion: Optional[str] = None
    toolCount: int = 0
    tools: List[ToolSummary] = Field(default_factory=list)
    fetchedAt: Optional[datetime] = None
    stale: bool = False
    lastError: Optional[str] = None
    secrets: SecretState
    status: str = "ok"


class ProductList(ApiModel):
    data: List[ProductItem]


class BulkRevokeRequest(ApiModel):
    ids: List[str] = Field(min_length=1, max_length=500)


class BulkRevokeResult(ApiModel):
    revoked: int
