"""Omnichannel API schemas — camelCase out to the frontend (mirrors
service_frontend/types/omnichannel.ts). Status flags are resolved to string
keys by the services before constructing these models.
"""
from datetime import datetime
from typing import List, Optional


from app.schemas.base import ApiModel

from app.schemas.filters import FilterGroup


# ── Workspaces ──────────────────────────────────────────────────────────────
class WorkspaceItem(ApiModel):
    id: str
    tenantId: str
    name: str
    status: str  # ACTIVE | INACTIVE
    channelCount: int
    memberCount: int
    isDefault: bool
    isTrashed: bool
    createdAt: datetime
    updatedAt: datetime


class WorkspaceListResponse(ApiModel):
    data: List[WorkspaceItem]
    total: int
    page: int


class WorkspaceNeighborResponse(ApiModel):
    workspace: Optional[WorkspaceItem] = None
    total: int


class WorkspaceCreate(ApiModel):
    name: str
    status: str = "ACTIVE"


class WorkspaceUpdate(ApiModel):
    name: Optional[str] = None
    status: Optional[str] = None


class WorkspaceMemberItem(ApiModel):
    id: str
    userId: str
    name: Optional[str] = None
    email: str
    status: str
    assignedAt: datetime


class MemberCandidateItem(ApiModel):
    userId: str
    name: Optional[str] = None
    email: str
    status: str


class AssignMembersRequest(ApiModel):
    userIds: List[str]


# ── Channels ────────────────────────────────────────────────────────────────
class ChannelItem(ApiModel):
    id: str
    tenantId: str
    workspaceId: str
    workspaceName: str
    channelType: str
    name: str
    status: str  # ACTIVE | PENDING | INACTIVE | ERROR
    isActive: bool
    wabaId: Optional[str] = None
    phoneNumberId: Optional[str] = None
    displayPhoneNumber: Optional[str] = None
    businessAccountName: Optional[str] = None
    verifiedName: Optional[str] = None
    lastVerifiedAt: Optional[datetime] = None
    profileSyncedAt: Optional[datetime] = None
    isTrashed: bool
    createdAt: datetime
    updatedAt: datetime


class ChannelProfileOut(ApiModel):
    """WhatsApp Business Profile mirror (plan 06). Rendered from the local DB —
    no Meta call on read."""

    about: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    email: Optional[str] = None
    vertical: Optional[str] = None
    website1: Optional[str] = None
    website2: Optional[str] = None
    profilePictureUrl: Optional[str] = None
    profileSyncedAt: Optional[datetime] = None


class ChannelProfileUpdate(ApiModel):
    """Editable + write-through profile fields. All optional — only changed
    fields are POSTed to Meta. ``websites`` capped at 2 (website1/website2)."""

    about: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    email: Optional[str] = None
    vertical: Optional[str] = None
    website1: Optional[str] = None
    website2: Optional[str] = None


class ChannelListResponse(ApiModel):
    data: List[ChannelItem]
    total: int
    page: int


class ChannelNeighborResponse(ApiModel):
    channel: Optional[ChannelItem] = None
    total: int


class ChannelUpdate(ApiModel):
    name: Optional[str] = None
    isActive: Optional[bool] = None


class TestConnectionResult(ApiModel):
    ok: bool
    message: str
    checkedAt: datetime


# ── Onboarding (Embedded Signup) ─────────────────────────────────────────────
class OnboardingCallbackRequest(ApiModel):
    workspaceId: str
    code: str
    # Resolved server-side from the exchanged token (debug_token → phone_numbers)
    # when the client omits them. The self-hosted redirect flow sends neither;
    # the simulated popup (dev) supplies both.
    wabaId: Optional[str] = None
    phoneNumberId: Optional[str] = None
    displayPhoneNumber: Optional[str] = None
    businessName: Optional[str] = None
    # The redirect_uri the OAuth dialog was minted against. Under Meta "strict
    # mode" the code is redirect_uri-bound; the token exchange MUST send the
    # identical value. None for the simulated popup (dev) — exchange stays
    # redirect-less.
    redirectUri: Optional[str] = None


class ManualConnectRequest(ApiModel):
    """Manual channel connect — paste a permanent System User token + phone IDs.

    Escape hatch for testing a number before Business Verification (the Embedded
    Signup popup is gated until verified). Provide phoneNumberId directly (easiest
    — it's on the WhatsApp API Setup page), or wabaId + phoneNumber to resolve it.
    """

    workspaceId: str
    accessToken: str
    phoneNumberId: Optional[str] = None
    wabaId: Optional[str] = None
    phoneNumber: Optional[str] = None


# ── Shared ──────────────────────────────────────────────────────────────────
class IdsRequest(ApiModel):
    ids: List[str]


class ExportRequest(ApiModel):
    columns: List[str]
    ids: Optional[List[str]] = None
    search: Optional[str] = None
    sortBy: Optional[str] = None
    sortDir: Optional[str] = None
    statusView: Optional[str] = "active"
    filter: Optional[FilterGroup] = None


# ── Conversations (plan 05) ──────────────────────────────────────────────────
class ReplyRefItem(ApiModel):
    id: str
    body: Optional[str] = None
    senderType: str
    senderName: Optional[str] = None


class MessageItem(ApiModel):
    id: str
    contactId: str
    channelId: Optional[str] = None
    senderType: str  # AGENT | CONTACT | SYSTEM
    senderId: Optional[str] = None
    senderName: Optional[str] = None
    messageType: str
    body: Optional[str] = None
    mediaUrl: Optional[str] = None
    mediaMime: Optional[str] = None
    mediaFilename: Optional[str] = None
    mediaSize: Optional[int] = None
    voice: bool = False
    externalMessageId: Optional[str] = None
    deliveryStatus: Optional[str] = None  # QUEUED | SENT | DELIVERED | READ | FAILED
    errorCode: Optional[str] = None
    errorMessage: Optional[str] = None
    replyTo: Optional[ReplyRefItem] = None
    createdAt: datetime


class ThreadItem(ApiModel):
    id: str  # contact id — the contact IS the thread
    tenantId: str
    workspaceId: str
    name: str
    phone: Optional[str] = None
    avatarUrl: Optional[str] = None
    assignedUserId: Optional[str] = None
    assignedUserName: Optional[str] = None
    status: str  # OPEN | SNOOZED | CLOSED
    priority: str
    channelId: Optional[str] = None
    channelType: str
    cswExpiresAt: Optional[datetime] = None
    lastIncomingMessageAt: Optional[datetime] = None
    lastMessageAt: Optional[datetime] = None
    lastMessagePreview: Optional[str] = None
    unreadCount: int = 0
    createdAt: datetime


class ThreadListResponse(ApiModel):
    data: List[ThreadItem]
    total: int


class ThreadPatch(ApiModel):
    """PATCH /contacts/{id}. assignedUserId: explicit null = unassign (the
    handler distinguishes omitted vs null via model_fields_set)."""

    assignedUserId: Optional[str] = None
    status: Optional[str] = None  # OPEN | SNOOZED | CLOSED
    priority: Optional[str] = None  # LOW | MEDIUM | HIGH | URGENT


class SendMessageRequest(ApiModel):
    messageType: str = "TEXT"  # TEXT | TEMPLATE
    body: Optional[str] = None
    templateId: Optional[str] = None
    templateVariables: Optional[List[str]] = None
    replyToMessageId: Optional[str] = None


class TemplateItem(ApiModel):
    id: str
    channelId: str
    name: str
    language: Optional[str] = None
    category: Optional[str] = None
    bodyText: str
    variableCount: int
    status: Optional[str] = None


class QuickReplyItem(ApiModel):
    id: str
    workspaceId: str
    shortcut: Optional[str] = None
    body: str


# ── Omnichannel media settings (plan 12 — per-workspace caps) ────────────────
class MediaCapItem(ApiModel):
    maxBytes: int
    ceilingBytes: int
    acceptedMimes: List[str]


class OmnichannelSettingsUpdate(ApiModel):
    """Per-type max-size overrides (bytes). Null clears an override (= Meta
    ceiling). Values are clamped ≤ the Meta ceiling at enforcement."""

    imageMaxBytes: Optional[int] = None
    videoMaxBytes: Optional[int] = None
    audioMaxBytes: Optional[int] = None
    documentMaxBytes: Optional[int] = None
    stickerMaxBytes: Optional[int] = None


class OmnichannelSettingsResponse(ApiModel):
    workspaceId: Optional[str] = None
    overrides: dict  # {imageMaxBytes: int|null, ...}
    effective: dict  # {IMAGE: {maxBytes, ceilingBytes, acceptedMimes}, ...}


# ── Public gateway API keys (plan sprint-1/01 Slice 3) ───────────────────────
class ApiKeyItem(ApiModel):
    id: str
    workspaceId: str
    name: str
    keyPrefix: str
    maskedKey: str  # fxw_live_{prefix}••••
    status: str  # ACTIVE | REVOKED
    lastUsedAt: Optional[datetime] = None
    revokedAt: Optional[datetime] = None
    createdAt: datetime


class ApiKeyListResponse(ApiModel):
    data: List[ApiKeyItem]


class ApiKeyCreateRequest(ApiModel):
    name: str


class ApiKeyMintResponse(ApiModel):
    key: ApiKeyItem
    fullKey: str  # shown ONCE at mint, never again


# ── Public send API (respond.io-style; text/template in v1) ──────────────────
class PublicTextBody(ApiModel):
    body: str


class PublicTemplateBody(ApiModel):
    id: Optional[str] = None  # our template id (from GET /templates)
    name: Optional[str] = None  # OR the Meta template name
    variables: Optional[List[str]] = None


class PublicMediaBody(ApiModel):
    url: Optional[str] = None  # fetched + re-uploaded (never passed to Meta as a bare link)
    caption: Optional[str] = None
    filename: Optional[str] = None


class PublicSendRequest(ApiModel):
    to: str
    # text | template | image | video | audio | voice | document | sticker
    # (interactive/location/contacts/reaction land in slices 2/3)
    type: str = "text"
    text: Optional[PublicTextBody] = None
    template: Optional[PublicTemplateBody] = None
    media: Optional[PublicMediaBody] = None


class PublicSendResponse(ApiModel):
    id: str  # OUR durable message id (not Meta's wamid)
    status: str  # queued
    idempotencyReplay: bool = False


class PublicTemplateItem(ApiModel):
    id: str
    name: str
    language: Optional[str] = None
    category: Optional[str] = None
    bodyText: str
    variableCount: int


class PublicTemplateListResponse(ApiModel):
    data: List[PublicTemplateItem]


# ── Consumer webhooks (plan sprint-1/01 Slice 4) ─────────────────────────────
class WebhookEndpointItem(ApiModel):
    id: str
    tenantId: str
    workspaceId: str
    channelId: str
    name: str
    url: str
    events: List[str]
    status: str  # ACTIVE | DISABLED | AUTO_DISABLED
    consecutiveFailures: int
    lastSuccessAt: Optional[datetime] = None
    disabledAt: Optional[datetime] = None
    disabledReason: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime


class WebhookEndpointListResponse(ApiModel):
    data: List[WebhookEndpointItem]


class WebhookEndpointCreateRequest(ApiModel):
    name: str
    url: str
    events: List[str]


class WebhookEndpointUpdateRequest(ApiModel):
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[List[str]] = None


class WebhookEndpointMintResponse(ApiModel):
    endpoint: WebhookEndpointItem
    signingSecret: str  # shown ONCE at create/rotate


class WebhookSecretResponse(ApiModel):
    signingSecret: str


class WebhookDeliveryItem(ApiModel):
    id: str
    eventId: str
    eventType: str
    status: str  # PENDING | SUCCESS | FAILED
    attemptCount: int
    responseStatus: Optional[int] = None
    responseMs: Optional[int] = None
    error: Optional[str] = None
    lastAttemptAt: Optional[datetime] = None
    nextAttemptAt: Optional[datetime] = None
    createdAt: datetime


class WebhookDeliveryListResponse(ApiModel):
    data: List[WebhookDeliveryItem]


# ── Template management (plan 07) ─────────────────────────────────────────────
class TemplateManageItem(ApiModel):
    id: str
    channelId: str
    name: str
    language: Optional[str] = None
    category: Optional[str] = None
    status: str  # LOCAL_DRAFT | PENDING | APPROVED | REJECTED | PAUSED | DISABLED
    quality: Optional[str] = None  # GREEN | YELLOW | RED (FE maps to High/Med/Low)
    rejectedReason: Optional[str] = None
    bodyPreview: str
    variableCount: int
    metaTemplateId: Optional[str] = None
    lastSyncedAt: Optional[datetime] = None
    createdAt: datetime


class TemplateManageListResponse(ApiModel):
    data: List[TemplateManageItem]
    total: int
    page: int


class TemplateDetail(TemplateManageItem):
    """List item + the friendly builder doc + raw Meta components (View payload)."""

    doc: dict
    components: List[dict]
