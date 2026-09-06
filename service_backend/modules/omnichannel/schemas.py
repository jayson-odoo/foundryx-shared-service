"""Omnichannel API schemas - camelCase out to the frontend (mirrors
service_frontend/types/omnichannel.ts). Status flags are resolved to string
keys by the services before constructing these models.
"""
import re
from datetime import datetime
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.base import ApiModel
from app.schemas.filters import FilterGroup

# Foolproof-UI (user mandate): a colour picker on the frontend only ever emits
# a hex triplet, never a token name or arbitrary CSS - reject anything else at
# the wire boundary (review round 1, finding 11) instead of piping tenant
# input straight into a `style` attribute downstream.
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _validate_hex_color(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    if not _HEX_COLOR_RE.match(v):
        raise ValueError("Color must be a 6-digit hex value, e.g. #FF5A00.")
    return v


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
    """WhatsApp Business Profile mirror (plan 06). Rendered from the local DB -
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
    """Editable + write-through profile fields. All optional - only changed
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
    # identical value. None for the simulated popup (dev) - exchange stays
    # redirect-less.
    redirectUri: Optional[str] = None


class ManualConnectRequest(ApiModel):
    """Manual channel connect - paste a permanent System User token + phone IDs.

    Escape hatch for testing a number before Business Verification (the Embedded
    Signup popup is gated until verified). Provide phoneNumberId directly (easiest
    - it's on the WhatsApp API Setup page), or wabaId + phoneNumber to resolve it.
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


# ── Contact fields (plan 25 S1) ───────────────────────────────────────────────
class ContactFieldItem(ApiModel):
    id: str
    workspaceId: str
    key: str
    label: str
    description: Optional[str] = None
    type: str  # text|list|checkbox|email|number|url|date|time
    options: Optional[List[str]] = None  # `list` type only
    visibility: str = "always"  # always|hidden
    sortOrder: int
    valuesCount: int = 0
    createdAt: datetime


class ContactFieldCreate(ApiModel):
    key: str
    label: str
    description: Optional[str] = None
    type: str
    options: Optional[List[str]] = None
    visibility: Optional[Literal["always", "hidden"]] = "always"


class ContactFieldUpdate(ApiModel):
    """`key` + `type` are immutable after create (D6) - present-but-unchanged is
    fine, present-and-different is a 422 (enforced in the service)."""

    key: Optional[str] = None
    type: Optional[str] = None
    label: Optional[str] = None
    description: Optional[str] = None
    options: Optional[List[str]] = None
    visibility: Optional[Literal["always", "hidden"]] = None
    sortOrder: Optional[int] = None


# ── Contact tags (plan 25 S1) ─────────────────────────────────────────────────
class ContactTagItem(ApiModel):
    id: str
    workspaceId: str
    name: str
    emoji: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    contactsCount: int = 0
    createdAt: datetime


class ContactTagCreate(ApiModel):
    name: str
    emoji: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None

    @field_validator("color")
    @classmethod
    def _valid_color(cls, v: Optional[str]) -> Optional[str]:
        return _validate_hex_color(v)


class ContactTagUpdate(ApiModel):
    name: Optional[str] = None
    emoji: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None

    @field_validator("color")
    @classmethod
    def _valid_color(cls, v: Optional[str]) -> Optional[str]:
        return _validate_hex_color(v)


class ContactTagRefItem(ApiModel):
    """Compact tag ref carried on a `ThreadItem` (AC-CDM-12)."""

    id: str
    name: str
    emoji: Optional[str] = None
    color: Optional[str] = None


class ContactLifecycleSummary(ApiModel):
    """A contact's current lifecycle stage (AC-CDM-19, plan 25 S2)."""

    statusId: str
    key: str
    label: str
    color: Optional[str] = None
    isWon: bool = False
    isLost: bool = False


# ── Lifecycle (plan 25 S2) - the scoped `omnichannel_contact_lifecycle`
# status entity, one graph per workspace ─────────────────────────────────────
class LifecycleStageItem(ApiModel):
    """One stage of a workspace's lifecycle graph (AC-CDM contract §5.1)."""

    statusId: str
    key: str
    label: str
    color: Optional[str] = None
    sortOrder: int
    isInitial: bool
    isWon: bool  # is_terminal
    isLost: bool  # is_archived
    isActive: bool  # any other stage


class LifecycleMoveOption(ApiModel):
    """A fireable outgoing edge for a contact right now (AC-CDM-18)."""

    edgeId: str
    toStatusId: str
    label: str


class LifecycleMoveRequest(ApiModel):
    toStatusId: str


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
    # Set when the sender is a federated (embed) external agent, else None
    # (plan 11H Slice 1) - the bubble renders the agent's avatar either way.
    senderExternalAgentId: Optional[str] = None
    senderAvatarUrl: Optional[str] = None
    messageType: str
    body: Optional[str] = None
    mediaUrl: Optional[str] = None
    mediaMime: Optional[str] = None
    mediaFilename: Optional[str] = None
    mediaSize: Optional[int] = None
    voice: bool = False
    # Structured payload for interactive/interactive-reply/location/contacts
    # (plan 12 Slice 2) - the friendly definition the bubble renders.
    payload: Optional[dict] = None
    # Emoji reaction chips (plan 12 Slice 3) - [{emoji, reactorType, reactor}].
    reactions: List[dict] = []
    externalMessageId: Optional[str] = None
    deliveryStatus: Optional[str] = None  # QUEUED | SENT | DELIVERED | READ | FAILED
    errorCode: Optional[str] = None
    errorMessage: Optional[str] = None
    replyTo: Optional[ReplyRefItem] = None
    createdAt: datetime


class ThreadItem(ApiModel):
    id: str  # contact id - the contact IS the thread
    tenantId: str
    workspaceId: str
    name: str
    # System fields (plan 25) - editable from the internal PATCH + the Contact
    # panel Details tab. `name` (derived display name) stays for compatibility.
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    language: Optional[str] = None  # BCP-47 tag
    countryCode: Optional[str] = None  # ISO-3166 alpha-2, upper-cased
    avatarUrl: Optional[str] = None
    assignedUserId: Optional[str] = None
    assignedUserName: Optional[str] = None
    # Federated (embed) assignee - set instead of assignedUserId when an external
    # agent owns the thread (plan 11H Slice 1). The list resolves the display
    # name/avatar from whichever assignee column is set.
    assignedExternalAgentId: Optional[str] = None
    assignedAvatarUrl: Optional[str] = None
    status: str  # OPEN | SNOOZED | CLOSED
    priority: str
    channelId: Optional[str] = None
    channelType: str
    cswExpiresAt: Optional[datetime] = None
    lastIncomingMessageAt: Optional[datetime] = None
    lastMessageAt: Optional[datetime] = None
    lastMessagePreview: Optional[str] = None
    unreadCount: int = 0
    # Registered custom-field values, keyed by ContactField.key (plan 25).
    customFields: dict = {}
    # Tags attached to this contact (plan 25, AC-CDM-12).
    tags: List[ContactTagRefItem] = []
    # Current lifecycle stage; null until S2 registers the scoped status entity.
    lifecycle: Optional[ContactLifecycleSummary] = None
    createdAt: datetime


class ThreadListResponse(ApiModel):
    data: List[ThreadItem]
    total: int


# ── Contacts module (plan 26 S1) ─────────────────────────────────────────────
class ContactChannelRef(ApiModel):
    """One channel a contact has an identity on (AC-CTM-19) - resolved
    tenant-scoped from `contact_channel_identities`, batched for a whole page.
    Never defaulted: a contact with no identity yields `channels: []`."""

    channelId: str
    channelType: str
    name: str


class ContactListItem(ThreadItem):
    """`ThreadItem` (plan 25) + `channels[]` (D-A2-11) - the Contacts-module
    list/detail shape. No new fields beyond `channels` - everything else is
    inherited so the module never forks a second contact representation."""

    channels: List[ContactChannelRef] = []


class ContactListResponse(ApiModel):
    data: List[ContactListItem]
    total: int
    page: int


class ContactCreate(ApiModel):
    """Manual create (plan 26 S2, D-A2-4, §5.1). `phone` is required + create-
    only (never PATCH-able, AC-CTM-28); every other field mirrors the
    optional `ThreadPatch` system/custom/tag fields plus the lifecycle stage
    a brand new contact may start on. Omitted `lifecycleStatusId` defaults to
    the workspace's `is_initial` stage server-side."""

    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: str
    email: Optional[str] = None
    language: Optional[str] = None
    countryCode: Optional[str] = None
    lifecycleStatusId: Optional[str] = None
    tagIds: Optional[List[str]] = None
    customFields: Optional[dict] = None


class BulkFailure(ApiModel):
    id: str
    error: str


class BulkResult(ApiModel):
    """Per-record bulk-action outcome (D-A2-5) - `ok` is the list of ids that
    succeeded; a failed id always carries its own reason, never a bare
    "something went wrong"."""

    ok: List[str]
    failed: List[BulkFailure]


class BulkAssignRequest(ApiModel):
    ids: List[str] = Field(max_length=500)
    assigneeUserId: Optional[str] = None


class BulkTagsRequest(ApiModel):
    ids: List[str] = Field(max_length=500)
    mode: Literal["add", "remove"]
    tagIds: List[str]


class BulkLifecycleRequest(ApiModel):
    ids: List[str] = Field(max_length=500)
    toStatusId: str


# The STATIC export column whitelist (finding 14, review round 1) - the
# single source of truth `contact_export_service._COLUMN_LABELS` keys off
# too (imported from here, never duplicated). `customFields.<key>` is the
# one DYNAMIC (per-workspace) shape - matched by pattern here (a save-time
# 422 on a malformed key), then checked against the workspace's ACTUALLY
# registered fields in the service layer (`create_export_job`), which is the
# only place with DB + workspace context.
EXPORT_COLUMN_IDS = frozenset(
    {
        "id", "name", "firstName", "lastName", "phone", "email", "language",
        "countryCode", "lifecycle", "tags", "assignee", "channel",
        "lastMessageAt", "createdAt",
    }
)
MAX_EXPORT_COLUMNS = 50
_CUSTOM_FIELD_COLUMN_RE = re.compile(r"^customFields\.[A-Za-z0-9_]+$")


class ContactExportRequest(ApiModel):
    """Export job request (plan 26 S3, D-A2-6a). An explicit `ids` selection
    WINS over search/filter/segment/sort (`ContactListService.query_for_
    export`) - the current list query is otherwise honoured exactly."""

    columns: List[str]
    ids: Optional[List[str]] = None
    search: Optional[str] = None
    filter: Optional[FilterGroup] = None
    segment: Optional[str] = None
    sortBy: Optional[str] = None
    sortDir: Optional[Literal["asc", "desc"]] = None

    @field_validator("columns")
    @classmethod
    def _validate_columns(cls, v: List[str]) -> List[str]:
        """Finding 14: cap + reject an unknown column id at the wire boundary
        instead of the export silently rendering a blank cell for it
        (`_column_value`'s catch-all). `customFields.<key>` format is
        checked here (no DB in a pydantic validator); whether `<key>` is
        actually REGISTERED for this workspace is re-checked in
        `create_export_job` (DB + workspace-scoped)."""
        if not v:
            raise ValueError("At least one column is required.")
        if len(v) > MAX_EXPORT_COLUMNS:
            raise ValueError(f"At most {MAX_EXPORT_COLUMNS} columns.")
        unknown = [
            c for c in v if c not in EXPORT_COLUMN_IDS and not _CUSTOM_FIELD_COLUMN_RE.match(c)
        ]
        if unknown:
            raise ValueError(f"Unknown export column(s): {', '.join(unknown)}.")
        return v


class ContactSegmentItem(ApiModel):
    id: str
    workspaceId: str
    name: str
    description: Optional[str] = None
    filter: Optional[FilterGroup] = None
    createdAt: datetime
    updatedAt: datetime


class ContactSegmentCreate(ApiModel):
    name: str
    description: Optional[str] = None
    filter: Optional[FilterGroup] = None


class ContactSegmentUpdate(ApiModel):
    """Partial update (`model_fields_set` drives which fields apply)."""

    name: Optional[str] = None
    description: Optional[str] = None
    filter: Optional[FilterGroup] = None


# ── Broadcasts (plan 29, roadmap A4) ─────────────────────────────────────────
# See documentation/plans/sprint-4/29-omnichannel-broadcasts.md §5.2. Mirrors
# service_frontend/types/omnichannel.ts (S0 mock contract) verbatim.
class TemplateBindingStatic(ApiModel):
    """Verbatim text - no token syntax allowed (D-A4-4, anti-SSTI by
    construction: the server never renders a tenant string as a template)."""

    source: Literal["static"]
    text: str


class TemplateBindingContactField(ApiModel):
    """Reads a whitelisted contact field, falling back when empty (D-A4-5:
    the fallback is REQUIRED, so an empty-parameter send is unreachable)."""

    source: Literal["contactField"]
    field: str
    fallback: str


TemplateBinding = Annotated[
    Union[TemplateBindingStatic, TemplateBindingContactField],
    Field(discriminator="source"),
]

# `TemplateBinding.field` whitelist (plan §5.2) - the fixed contact fields
# plus `customFields.<key>` where `<key>` is REGISTERED on the workspace
# (checked in `services/broadcast_bindings.py`, not here - no DB in a schema).
BROADCAST_FIELD_BINDING_OPTIONS = frozenset(
    {"firstName", "lastName", "phone", "email", "language", "countryCode", "lifecycle"}
)
_CUSTOM_FIELD_BINDING_RE = re.compile(r"^customFields\.[A-Za-z0-9_]+$")


class BroadcastBindings(ApiModel):
    header: List[TemplateBinding] = []
    body: List[TemplateBinding] = []
    buttons: List[TemplateBinding] = []


class BroadcastAudienceIn(ApiModel):
    """Exactly one of `segmentId` / `filter` / `contactIds` must be set,
    matching `kind` (D-A4-2 - configuration only, never a stored list)."""

    kind: Literal["segment", "filter", "contacts"]
    segmentId: Optional[str] = None
    filter: Optional[FilterGroup] = None
    contactIds: Optional[List[str]] = None


class BroadcastAudienceOut(ApiModel):
    kind: Literal["segment", "filter", "contacts"]
    segmentId: Optional[str] = None
    segmentName: Optional[str] = None
    filter: Optional[FilterGroup] = None
    contactIds: Optional[List[str]] = None


class BroadcastCounts(ApiModel):
    total: int
    sent: int
    delivered: int
    read: int
    failed: int
    skipped: int


class BroadcastItem(ApiModel):
    id: str
    workspaceId: str
    name: str
    labels: List[str] = []
    channelId: str
    channelName: str
    audience: BroadcastAudienceOut
    templateId: str
    templateName: str
    templateLanguage: Optional[str] = None
    bindings: BroadcastBindings
    status: Literal["DRAFT", "SCHEDULED", "SENDING", "SENT", "CANCELLED", "FAILED"]
    statusLabel: str
    scheduledAt: Optional[datetime] = None
    startedAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None
    counts: BroadcastCounts
    jobId: Optional[str] = None
    error: Optional[str] = None
    createdByUserId: Optional[str] = None
    createdByName: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime


class BroadcastListResponse(ApiModel):
    data: List[BroadcastItem]
    total: int
    page: int


class BroadcastCreate(ApiModel):
    name: str
    labels: Optional[List[str]] = None
    channelId: str
    audience: BroadcastAudienceIn
    templateId: str
    bindings: BroadcastBindings
    scheduledAt: Optional[datetime] = None


class BroadcastUpdate(ApiModel):
    """Partial update (`model_fields_set` drives which fields apply) - the
    service enforces the status-gated write rules (AC-BRD-21: DRAFT only,
    except `scheduledAt` which may also change while SCHEDULED)."""

    name: Optional[str] = None
    labels: Optional[List[str]] = None
    channelId: Optional[str] = None
    audience: Optional[BroadcastAudienceIn] = None
    templateId: Optional[str] = None
    bindings: Optional[BroadcastBindings] = None
    scheduledAt: Optional[datetime] = None


class BroadcastSendRequest(ApiModel):
    """`scheduledAt` unset/None = send now (-> SENDING); a future instant ->
    SCHEDULED (plan 29 S2, matches the S0 frontend contract - `services/
    broadcast-service.ts send(workspaceId, id, scheduledAt?)`)."""

    scheduledAt: Optional[datetime] = None


class AudiencePreviewRequest(ApiModel):
    audience: BroadcastAudienceIn


class AudiencePreviewResponse(ApiModel):
    count: int


class BroadcastRecipientItem(ApiModel):
    id: str
    contactId: str
    contactName: str
    phone: Optional[str] = None
    state: Literal["queued", "sent", "delivered", "read", "failed", "skipped"]
    skipReason: Optional[str] = None
    errorCode: Optional[str] = None
    errorText: Optional[str] = None
    messageId: Optional[str] = None
    attemptedAt: Optional[datetime] = None


class BroadcastRecipientListResponse(ApiModel):
    data: List[BroadcastRecipientItem]
    total: int
    page: int


# ── Conversation events (plan 27 A3, S1) ─────────────────────────────────────
class ConversationEventItem(ApiModel):
    """One append-only `conversation_events` row (AC-IVE-13). `fromLabel`/
    `toLabel` are resolved tenant-scoped server-side (never a raw id echoed
    without its label) - a THREAD status id, a core lifecycle status id, or a
    user/external-agent display name, depending on `eventType`. `closeReasonId`/
    `closeReasonName` stay null until plan 27 A3 slice S2 lands close reasons."""

    id: str
    eventType: str
    actorName: Optional[str] = None
    actorUserId: Optional[str] = None
    fromValue: Optional[str] = None
    fromLabel: Optional[str] = None
    toValue: Optional[str] = None
    toLabel: Optional[str] = None
    closeReasonId: Optional[str] = None
    closeReasonName: Optional[str] = None
    note: Optional[str] = None
    payload: Optional[dict] = None
    createdAt: datetime


class ConversationEventListResponse(ApiModel):
    data: List[ConversationEventItem]
    total: int


# ── Close reasons (plan 27 A3, S2 - D-A3-3) ─────────────────────────────────
class CloseReasonItem(ApiModel):
    id: str
    workspaceId: str
    name: str
    sortOrder: int
    isActive: bool
    # Count of events referencing this reason - Delete is offered only at 0,
    # Deactivate otherwise (AC-IVE-31, D-A3-13).
    usesCount: int = 0
    createdAt: datetime


class CloseReasonCreate(ApiModel):
    name: str
    sortOrder: Optional[int] = None
    isActive: Optional[bool] = None


class CloseReasonUpdate(ApiModel):
    name: Optional[str] = None
    sortOrder: Optional[int] = None
    isActive: Optional[bool] = None


class ShortcutItem(ApiModel):
    """A published `entity.shortcut` workflow bound to `omnichannel_contact`
    the drawer's Shortcuts control may fire (AC-IVE-36)."""

    workflowId: str
    name: str


class ShortcutRunResponse(ApiModel):
    """Response of firing a shortcut (AC-IVE-37)."""

    runId: str
    status: str


class CloseThreadRequest(ApiModel):
    """`POST /contacts/{id}/close` (AC-IVE-28/29). `closeReasonId` is required
    (Close is disabled in the UI until one is picked); `note` is capped at
    2000 chars - stored on the event, never on the thread."""

    closeReasonId: str
    note: Optional[str] = Field(default=None, max_length=2000)


# ── Saved inbox views (plan 27 A3, S2 - D-A3-2) ─────────────────────────────
class InboxViewFilter(ApiModel):
    """Typed saved-view filter - NOT a rule-engine tree. Unknown keys 422
    (`extra="forbid"`, AC-IVE-18). `segmentId` is a reserved seam for A2
    (plan 26's `contact_segments`) - unused until that lane merges (D-A3-17)."""

    model_config = ConfigDict(extra="forbid")

    statuses: Optional[List[Literal["OPEN", "SNOOZED", "CLOSED"]]] = None
    assignee: Optional[Literal["all", "me", "unassigned", "user"]] = None
    assigneeUserIds: Optional[List[str]] = None
    lifecycleStageIds: Optional[List[str]] = None
    tagIds: Optional[List[str]] = None
    channelIds: Optional[List[str]] = None
    priority: Optional[Literal["ALL", "URGENT", "HIGH", "MEDIUM", "LOW"]] = None
    unreplied: Optional[bool] = None
    sort: Optional[Literal["newest", "oldest", "unreplied_first", "longest_waiting"]] = None
    segmentId: Optional[str] = None


class InboxViewItem(ApiModel):
    id: str
    workspaceId: str
    name: str
    ownerUserId: str
    ownerName: Optional[str] = None
    isShared: bool
    filter: InboxViewFilter
    sortOrder: int
    createdAt: datetime


class InboxViewCreate(ApiModel):
    name: str
    isShared: bool = False
    filter: InboxViewFilter = Field(default_factory=InboxViewFilter)


class InboxViewUpdate(ApiModel):
    name: Optional[str] = None
    isShared: Optional[bool] = None
    filter: Optional[InboxViewFilter] = None
    sortOrder: Optional[int] = None


class ThreadPatch(ApiModel):
    """PATCH /contacts/{id}. assignedUserId: explicit null = unassign (the
    handler distinguishes omitted vs null via model_fields_set). System-field +
    custom-field + tag writes (plan 25) are a PARTIAL merge - `customFields`
    keys omitted are left unchanged, a key set to `null` clears that key, and
    the WHOLE `customFields` value sent as `null` clears every registered
    field's value at once; `tagIds` REPLACES the whole tag set.

    `phone` is accepted on the WIRE only so the router can detect it was SENT
    (`model_fields_set`) and reject it with a named 422 - it is the inbound
    stitch key (no uniqueness guard, outside the AC-22 whitelist) and is never
    writable through this PATCH (review round 1, finding 12). The Contact
    panel must render phone read-only."""

    assignedUserId: Optional[str] = None
    status: Optional[str] = None  # OPEN | SNOOZED | CLOSED
    priority: Optional[str] = None  # LOW | MEDIUM | HIGH | URGENT
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None  # never applied - see docstring
    email: Optional[str] = None
    language: Optional[str] = None
    countryCode: Optional[str] = None
    customFields: Optional[dict] = None
    tagIds: Optional[List[str]] = None


class SendMessageRequest(ApiModel):
    messageType: str = "TEXT"  # TEXT | TEMPLATE
    body: Optional[str] = None
    templateId: Optional[str] = None
    templateVariables: Optional[List[str]] = None  # BODY {{n}} values
    templateHeaderVariables: Optional[List[str]] = None  # TEXT-header {{n}} values
    templateButtonVariables: Optional[List[str]] = None  # dynamic URL-button values
    replyToMessageId: Optional[str] = None


class SendLocationRequest(ApiModel):
    lat: float
    lng: float
    name: Optional[str] = None
    address: Optional[str] = None
    replyToMessageId: Optional[str] = None


class SendContactsRequest(ApiModel):
    contacts: List[dict]
    replyToMessageId: Optional[str] = None


class TemplateItem(ApiModel):
    id: str
    channelId: str
    name: str
    language: Optional[str] = None
    category: Optional[str] = None
    bodyText: str
    variableCount: int  # BODY {{n}} count (back-compat)
    # Rich-header/button metadata (plan 12 Slice 3) - drives the send dialog's
    # inputs so it asks for ONLY what a given template needs.
    headerFormat: Optional[str] = None  # None | TEXT | IMAGE | VIDEO | DOCUMENT
    headerVariableCount: int = 0  # TEXT-header {{n}} count
    buttonVariableCount: int = 0  # dynamic URL-button count
    status: Optional[str] = None


class QuickReplyItem(ApiModel):
    id: str
    workspaceId: str
    shortcut: Optional[str] = None
    body: str


class QuickReplyCreate(ApiModel):
    """Create a canned response. ``body`` required (non-blank); ``shortcut``
    optional (a leading ``/`` is fine - the composer matches ``/xyz``)."""

    shortcut: Optional[str] = None
    body: str

    @field_validator("shortcut")
    @classmethod
    def _norm_shortcut(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("body")
    @classmethod
    def _nonblank_body(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Message body is required.")
        return v


class QuickReplyUpdate(ApiModel):
    """Partial update. Only fields present in the payload are applied
    (``model_fields_set``); an explicit ``shortcut: null`` clears the shortcut."""

    shortcut: Optional[str] = None
    body: Optional[str] = None

    @field_validator("shortcut")
    @classmethod
    def _norm_shortcut(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("body")
    @classmethod
    def _nonblank_body(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Message body cannot be empty.")
        return v


# ── Omnichannel media settings (plan 12 - per-workspace caps) ────────────────
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


class PublicReactionBody(ApiModel):
    messageId: str  # OUR durable message id (never a raw wamid - AC-12-21)
    emoji: str = ""  # empty removes


class PublicSendRequest(ApiModel):
    to: str
    # text | template | image | video | audio | voice | document | sticker |
    # interactive | location | contacts | reaction
    type: str = "text"
    text: Optional[PublicTextBody] = None
    template: Optional[PublicTemplateBody] = None
    media: Optional[PublicMediaBody] = None
    # Structured types (plan 12 Slice 2) - friendly definitions (see structured.py).
    interactive: Optional[dict] = None
    location: Optional[dict] = None
    contacts: Optional[List[dict]] = None
    # Reaction (plan 12 Slice 3) - targets OUR durable id.
    reaction: Optional[PublicReactionBody] = None


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


class PublicMessageListResponse(ApiModel):
    """A contact's message history for the consumer API - full-fidelity
    ``MessageItem`` (every message type). ``nextBefore`` = pass back as
    ``before`` to page further into history (null when the page is the oldest)."""
    contactId: str
    data: List[MessageItem]
    nextBefore: Optional[str] = None


class PublicContactListResponse(ApiModel):
    """Paginated contacts (threads) for the consumer API."""
    data: List[ThreadItem]
    total: int
    page: int
    pageSize: int


class PublicContactUpdateRequest(ApiModel):
    """Partial update of a contact (plan 25 S3). Only the fields you SEND are
    changed; ``assignedUserId`` sent as ``null`` unassigns. ``customFields``
    sent as ``null`` (the whole value) clears EVERY registered field's value;
    sent as an object with a key set to ``null`` clears just that one key
    (other keys untouched - partial merge); omitted, ``customFields`` is left
    unchanged. ``tags`` REPLACES the whole tag set (names, auto-created if
    unknown - respond.io parity, D8); ``null`` clears every tag.
    ``lifecycle`` moves the contact along the workspace's lifecycle graph by
    stage KEY or LABEL - it cannot be cleared (send nothing to leave it
    unchanged)."""
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    priority: Optional[str] = None  # LOW|MEDIUM|HIGH|URGENT
    assignedUserId: Optional[str] = None
    customFields: Optional[dict] = None
    language: Optional[str] = None
    countryCode: Optional[str] = None
    tags: Optional[List[str]] = None
    lifecycle: Optional[str] = None


class PublicCommentRequest(ApiModel):
    body: str


# ── respond.io-parity response shapes (public gateway) ───────────────────────
# These deliberately do NOT inherit ApiModel: they mirror respond.io's documented
# JSON exactly - snake_case where respond.io uses it (``custom_fields``,
# ``created_at``), epoch-second integer timestamps, and a ``{items, pagination}``
# envelope with cursor URLs. Field NAMES/TYPES are the external contract.
# NB: respond.io ids are int64; ours are UUID strings - ``id``/``messageId`` are
# strings here (a documented, unavoidable deviation - we can't fabricate ints).
class RioCursorPagination(BaseModel):
    next: Optional[str] = None       # URL for the next page (older history), or null
    previous: Optional[str] = None   # URL for the previous page (newer), or null


class RioCustomField(BaseModel):
    name: str
    value: Optional[str] = None


class RioAssignee(BaseModel):
    id: str
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None


class RioContactItem(BaseModel):
    id: str
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    language: Optional[str] = None
    profilePic: Optional[str] = None
    countryCode: Optional[str] = None
    custom_fields: List[RioCustomField] = []
    status: str                       # open | snoozed | closed
    tags: List[str] = []
    assignee: Optional[RioAssignee] = None
    lifecycle: Optional[str] = None
    created_at: Optional[int] = None  # epoch seconds
    isBlocked: bool = False
    # ── Foundryx extensions (no respond.io equivalent) ──────────────────────
    # Kept so this shape is LOSSLESS vs the internal ThreadItem: a consumer has
    # no other read source for them, and an inbox list needs unreadCount +
    # lastMessagePreview. ISO-8601 Z (house convention) rather than the epoch
    # ints beside them, which exist only to mirror respond.io.
    #
    # When the WhatsApp 24-hour customer-service window closes. Past/None ⇒
    # free-form sends are refused (409 csw_window_closed); only an approved
    # template re-engages.
    cswExpiresAt: Optional[str] = None
    priority: Optional[str] = None            # LOW | MEDIUM | HIGH | URGENT
    channelId: Optional[str] = None
    channelType: Optional[str] = None         # WHATSAPP
    unreadCount: int = 0
    lastMessageAt: Optional[str] = None
    lastIncomingMessageAt: Optional[str] = None
    lastMessagePreview: Optional[str] = None


class RioContactListResponse(BaseModel):
    items: List[RioContactItem]
    pagination: RioCursorPagination


class RioMessageStatus(BaseModel):
    value: str                        # pending | sent | delivered | read | failed
    # Epoch seconds. NOTE: we do not record per-receipt times, so this is the
    # message's creation time (== the item's top-level `timestamp`), not the
    # moment the receipt landed. Don't compute send→delivered latency from it.
    timestamp: Optional[int] = None
    message: Optional[str] = None     # failure reason, when failed
    # Meta's numeric error code (e.g. "131047" re-engagement required) - stable
    # and branchable, unlike `message`, which is free text and localised.
    code: Optional[str] = None


class RioMessageSender(BaseModel):
    source: str                       # user | contact | system
    userId: Optional[str] = None
    teamId: Optional[str] = None


class RioMessagePayload(BaseModel):
    type: str                         # text | image | video | audio | voice | document | ...
    # `text` carries the body of a TEXT-family message; a media message puts its
    # caption in `caption` and leaves `text` null (respond.io's split - do NOT
    # populate both, it reads as a duplicated body).
    text: Optional[str] = None
    url: Optional[str] = None         # signed, clickable media URL
    caption: Optional[str] = None
    filename: Optional[str] = None
    mimeType: Optional[str] = None
    size: Optional[int] = None        # media bytes, when known
    # Structured definition for interactive / location / contacts / template -
    # the buttons, coordinates, cards or template binding that cannot survive
    # flattening into `text`. Same object the internal API exposes.
    payload: Optional[dict] = None
    messageTag: Optional[str] = None


class RioMessageReaction(BaseModel):
    emoji: str
    reactorType: str                  # AGENT | CONTACT
    reactor: Optional[str] = None


class RioMessageReplyTo(BaseModel):
    """The message this one replies to (WhatsApp quote)."""

    messageId: str
    text: Optional[str] = None
    senderType: Optional[str] = None  # AGENT | CONTACT | SYSTEM
    senderName: Optional[str] = None


class RioMessageItem(BaseModel):
    messageId: str
    channelMessageId: Optional[str] = None   # the provider's id (wamid)
    contactId: str
    channelId: Optional[str] = None
    traffic: str                      # incoming | outgoing
    # Epoch seconds the message was created - populated for INCOMING as well as
    # outgoing. `status[].timestamp` only exists once a delivery receipt lands
    # (never for inbound), so this is the only orderable key on a merged history.
    timestamp: Optional[int] = None
    message: RioMessagePayload
    status: List[RioMessageStatus] = []
    sender: RioMessageSender
    reactions: List[RioMessageReaction] = []
    replyTo: Optional[RioMessageReplyTo] = None


class RioMessageListResponse(BaseModel):
    items: List[RioMessageItem]
    pagination: RioCursorPagination


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


# ── Embed access config (plan 11H - tenant-level embed connection admin) ──────
class EmbedWorkspaceOption(ApiModel):
    """A (id, name) workspace pick for the iframe-snippet workspace selector."""

    id: str
    name: str


class EmbedConfigResponse(ApiModel):
    """The tenant's embed-access state. The ``embedSecret`` is NEVER included -
    ``hasSecret`` only reports whether one is set (write-only, echoed once at
    rotate)."""

    connectionId: Optional[str] = None
    allowedOrigins: List[str]
    hasSecret: bool
    # Public backend origin the consumer frames the iframe against.
    host: str
    workspaces: List[EmbedWorkspaceOption]


class EmbedRotateSecretResponse(ApiModel):
    """The freshly-minted secret - returned EXACTLY ONCE (write-only after)."""

    embedSecret: str


class EmbedOriginsUpdate(ApiModel):
    allowedOrigins: List[str]
