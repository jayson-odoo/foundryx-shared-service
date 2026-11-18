"""Lead Capture wire shapes (camelCase, ISO-Z). The consumer guide
(``documentation/lead-capture/consumer-integration-guide.md``) is the contract
of record for every gateway shape here: change one, change the guide."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import ApiModel


class ConnectFacebookRequest(BaseModel):
    """``systemUserToken`` (script / server path) OR ``loginId`` (from
    ``POST /facebook/login``, a product's own wizard): exactly one."""

    pageId: str = Field(min_length=1, max_length=64)
    systemUserToken: Optional[str] = Field(default=None, max_length=4096)
    loginId: Optional[str] = Field(default=None, max_length=64)
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


class GuidedSourceCreated(BaseModel):
    """A new Google source (card 68a R1): the inbound URL + the Google key,
    shown only in this answer (and again after a rotate)."""

    source: SourceItem
    url: str
    key: str


class KeyRotated(BaseModel):
    url: str
    key: str


class SettingsItem(ApiModel):
    allowSharedPages: bool
    updatedAt: Optional[datetime] = None


class SettingsUpdate(BaseModel):
    allowSharedPages: bool


class KeyCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    allowedOrigins: List[str] = Field(default_factory=list, max_length=10)


class KeyOriginsUpdate(BaseModel):
    allowedOrigins: List[str] = Field(default_factory=list, max_length=10)


class KeyItem(ApiModel):
    id: str
    name: str
    keyMasked: str
    allowedOrigins: List[str] = []
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



# ── lane L-C: connect sessions, hosted wizard, Facebook login ────────────────

class ConnectSessionCreate(BaseModel):
    returnOrigin: Optional[str] = Field(default=None, max_length=255)
    sourceId: Optional[str] = Field(default=None, max_length=64)


class ConnectSessionCreated(ApiModel):
    url: str
    expiresAt: datetime


class ConnectSessionRedeem(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class Channel(BaseModel):
    key: str
    label: str
    setup: str  # automatic | guided


class ChannelList(BaseModel):
    data: List[Channel]


class LoginConfig(BaseModel):
    available: bool
    simulated: bool
    appId: Optional[str] = None
    configId: Optional[str] = None
    graphVersion: str
    scopes: List[str]


class GoogleLoginConfig(BaseModel):
    """Google sign-in for the hosted wizard (plan 68). ``simulated`` = no
    Google client on this server: any code works."""

    available: bool
    simulated: bool
    clientId: Optional[str] = None
    scopes: List[str]


class GoogleLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    redirectUri: Optional[str] = Field(default=None, max_length=500)


class GoogleAccount(BaseModel):
    id: str
    name: str


class GoogleAccountList(BaseModel):
    data: List[GoogleAccount]


class GoogleLeadForm(BaseModel):
    id: str
    name: str


class GoogleLeadFormList(BaseModel):
    data: List[GoogleLeadForm]


class GoogleConnectRequest(BaseModel):
    accountId: str = Field(min_length=1, max_length=32)
    formIds: List[str] = Field(default_factory=list, max_length=200)


class GoogleFormResult(BaseModel):
    id: str
    name: str
    ok: bool
    message: Optional[str] = None


class GoogleConnectResult(BaseModel):
    source: SourceItem
    forms: List[GoogleFormResult]


class FacebookLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    redirectUri: Optional[str] = Field(default=None, max_length=2048)

    def __repr__(self) -> str:  # the code never reaches a repr / log line
        return "FacebookLoginRequest(code=***)"

    __str__ = __repr__


class FacebookPage(BaseModel):
    id: str
    name: str


class FacebookPageList(BaseModel):
    data: List[FacebookPage]


class FacebookLogin(ApiModel):
    loginId: str
    pages: List[FacebookPage]
    expiresAt: datetime


class WizardBranding(BaseModel):
    name: str
    logoUrl: Optional[str] = None


class WizardSession(ApiModel):
    accessToken: str
    expiresAt: datetime
    returnOrigin: Optional[str] = None
    sourceId: Optional[str] = None


class WizardContext(BaseModel):
    branding: WizardBranding
    channels: List[Channel]
    login: LoginConfig
    googleLogin: GoogleLoginConfig
    returnOrigin: Optional[str] = None
    source: Optional[SourceItem] = None


class WizardConnect(BaseModel):
    pageId: str = Field(min_length=1, max_length=64)


class WizardTestLead(ApiModel):
    leadId: Optional[str] = None
    receivedAt: Optional[datetime] = None
    formId: Optional[str] = None


class WizardDone(ApiModel):
    source: SourceItem
    connectedBy: Optional[str] = None
    connectedAt: Optional[datetime] = None
    testLeadAt: Optional[datetime] = None
    testLeadFormName: Optional[str] = None
    waitingForRealLead: bool


# ── lane L-C: staff Sources + Leads lists (AC-64-05/53) ─────────────────────

class StaffSourceItem(SourceItem):
    leads7d: int = 0


class StaffSourcePage(BaseModel):
    data: List[StaffSourceItem]
    total: int


class StaffLeadItem(ApiModel):
    id: str
    sourceId: str
    sourceName: str
    platform: str
    formId: Optional[str] = None
    formName: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    isTest: bool
    duplicateOf: Optional[str] = None
    receivedAt: datetime
    deliveryStatus: Optional[str] = None  # worst of the lead's deliveries; None = no receiver


class StaffLeadPage(BaseModel):
    data: List[StaffLeadItem]
    total: int


class DeliveryAttemptItem(DeliveryItem):
    endpointUrl: Optional[str] = None
    lastAttemptAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None


class StaffLeadDetail(ApiModel):
    lead: Dict[str, Any]
    deliveries: List[DeliveryAttemptItem]
