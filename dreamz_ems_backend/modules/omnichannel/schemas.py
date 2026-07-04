"""Omnichannel API schemas — camelCase out to the frontend (mirrors
dreamz_ems_frontend/types/omnichannel.ts). Status flags are resolved to string
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
    wabaId: str
    phoneNumberId: str
    # Optional: the real Embedded Signup SDK omits these; resolved server-side
    # from phone_number_id via Graph. The simulated popup supplies them.
    displayPhoneNumber: Optional[str] = None
    businessName: Optional[str] = None


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
    externalMessageId: Optional[str] = None
    deliveryStatus: Optional[str] = None  # SENT | DELIVERED | READ | FAILED
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
