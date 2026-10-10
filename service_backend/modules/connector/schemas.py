"""Connector admin wire schemas (camelCase names are fixed - the UI is built to them)."""

from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Literal, Optional

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


# --- settings in the database (lane SETTINGS-IN-DB-SS) ---------------------------------


class SettingValue(ApiModel):
    value: Optional[str] = None
    source: str  # database | environment | default | unset


class SecretValue(ApiModel):
    state: str  # set | missing | unreadable
    source: str  # database | environment | unset | unreadable


class ProductSettings(ApiModel):
    key: str
    stored: bool  # a database row exists (only then can it be deleted)
    status: str
    fields: Dict[str, SettingValue]
    secrets: Dict[str, SecretValue]


class ProductSettingsUpdate(ApiModel):
    """Omitted = unchanged; "" or null on a plain field = clear (fall back);
    a blank secret = keep; ``clearSecrets`` drops the stored secret."""

    displayName: Optional[str] = None
    connectionId: Optional[str] = None
    consentUrl: Optional[str] = None
    apiBaseUrl: Optional[str] = None
    issuer: Optional[str] = None
    consentAudience: Optional[str] = None
    callAudience: Optional[str] = None
    ssToProductSecret: Optional[str] = None
    productToSsSecret: Optional[str] = None
    clearSecrets: List[Literal["ssToProduct", "productToSs"]] = Field(default_factory=list)


class ProductSettingsCreate(ProductSettingsUpdate):
    key: str


class ProductDelete(ApiModel):
    confirmKey: str


class TenantSettings(ApiModel):
    publicBaseUrl: SettingValue
    allowedClientCidrs: SettingValue
    redirectAllowlist: SettingValue
    manifestTtlSeconds: SettingValue
    callTimeoutSeconds: SettingValue
    callLogRetentionDays: SettingValue
    forwardedForWarning: bool = False
    # wire field -> the deployment value a saved value must stay within
    ceilings: Dict[str, str] = Field(default_factory=dict)


class TenantSettingsUpdate(ApiModel):
    """Omitted = unchanged; null or "" = clear (fall back to environment/default)."""

    publicBaseUrl: Optional[str] = None
    allowedClientCidrs: Optional[str] = None
    redirectAllowlist: Optional[str] = None
    manifestTtlSeconds: Optional[int] = None
    callTimeoutSeconds: Optional[int] = None
    callLogRetentionDays: Optional[int] = None


class SettingsAuditItem(ApiModel):
    id: str
    target: str
    action: str
    fields: List[str] = Field(default_factory=list)
    actorUserId: Optional[str] = None
    actorName: Optional[str] = None
    at: datetime


class SettingsAuditList(ApiModel):
    data: List[SettingsAuditItem]
