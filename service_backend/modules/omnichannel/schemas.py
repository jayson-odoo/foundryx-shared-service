"""Omnichannel API schemas - camelCase out to the frontend (mirrors
service_frontend/types/omnichannel.ts). Status flags are resolved to string
keys by the services before constructing these models.
"""
import re
from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

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
    # Plan 32 (A7a, AC-CHN-36) - the Messenger/Instagram routing key (PAGE_ID
    # / IG professional account id) + its display name. Null on WHATSAPP
    # (which uses wabaId/phoneNumberId instead).
    externalAccountId: Optional[str] = None
    externalAccountName: Optional[str] = None
    # Plan 34 (A7b, D-A7B-25) - the opaque widget key for a WEBCHAT channel;
    # null on every other channel type. Not a secret (see `WebchatConnect
    # Result`/`RotateWidgetSecretResult` for the widget SECRET, which never
    # rides this object).
    widgetKey: Optional[str] = None
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


# ── Meta connect flow: Messenger + Instagram (plan 32 S3, A7a) ───────────────
class MetaPagesRequest(ApiModel):
    """`POST /omnichannel/onboarding/meta/pages` - exchanges the OAuth code
    server-side (D-A7-15); the token never reaches the browser."""

    channelType: Literal["FACEBOOK", "INSTAGRAM"]
    code: str
    redirectUri: Optional[str] = None


class MetaPageOption(ApiModel):
    """A connectable Facebook Page (Messenger) or its linked Instagram
    professional account (Instagram). `connected` marks a page/account
    already bound to a LIVE channel anywhere in the service - the wizard does
    not offer it (AC-CHN-02)."""

    id: str
    name: str
    connected: bool
    igAccountId: Optional[str] = None
    igUsername: Optional[str] = None


class MetaPagesResult(ApiModel):
    sessionId: str
    expiresAt: datetime
    pages: List[MetaPageOption]


class MetaConnectRequest(ApiModel):
    """`POST /omnichannel/onboarding/meta/connect` - finalizes the channel for
    the page (or Instagram account) picked from `MetaPagesResult.pages`."""

    sessionId: str
    workspaceId: str
    channelType: Literal["FACEBOOK", "INSTAGRAM"]
    pageId: str
    igAccountId: Optional[str] = None


# ── Web chat channel (plan 34 / A7b S1) - mirrors service_frontend/types/
# omnichannel.ts §"Plan 34 / A7b" byte-for-byte (contract pinned by the S0
# mock, see documentation/plans/sprint-4/
# 34-omnichannel-channel-web-chat.md §5.1). ──────────────────────────────────
class ConnectWebchatRequest(ApiModel):
    """`POST /omnichannel/onboarding/webchat/connect` (AC-WEB-18)."""

    name: str
    workspaceId: str
    allowedOrigins: List[str] = []


class WebchatAppearance(BaseModel):
    """Launcher side + header/agent-name appearance (AC-WEB-04)."""

    accentColor: str
    position: Literal["left", "right"]
    headerTitle: str
    agentDisplayName: str

    @field_validator("accentColor")
    @classmethod
    def _accent_color(cls, v: str) -> str:
        return _validate_hex_color(v)  # type: ignore[return-value]


class WebchatAppearanceUpdate(BaseModel):
    """Partial write - only the fields present are changed (mirrors
    `UpdateWebchatConfigInput.appearance` on the wire)."""

    accentColor: Optional[str] = None
    position: Optional[Literal["left", "right"]] = None
    headerTitle: Optional[str] = None
    agentDisplayName: Optional[str] = None

    @field_validator("accentColor")
    @classmethod
    def _accent_color(cls, v: Optional[str]) -> Optional[str]:
        return _validate_hex_color(v)


class WebchatPreChatToggles(BaseModel):
    """Fixed pre-chat capture toggles (D-A7B-23 - not a form-engine form)."""

    askName: bool
    askEmail: bool
    askPhone: bool


class WebchatPreChatTogglesUpdate(BaseModel):
    askName: Optional[bool] = None
    askEmail: Optional[bool] = None
    askPhone: Optional[bool] = None


class WebchatConfig(ApiModel):
    """`GET/PUT /omnichannel/channels/{id}/widget` (plan §5.1). Never carries
    the widget secret - that is revealed exactly once, by connect/rotate-
    secret only."""

    widgetKey: str
    allowedOrigins: List[str]
    tokenEpoch: int
    appearance: WebchatAppearance
    greeting: str
    offlineGreeting: str
    preChat: WebchatPreChatToggles
    # The exact install snippet the backend serves for this channel - the
    # Widget tab renders this verbatim (AC-WEB-05), never rebuilding it
    # client-side.
    snippet: str


class UpdateWebchatConfigInput(ApiModel):
    """`PUT /omnichannel/channels/{id}/widget` - every field optional so a
    partial save never clobbers the rest (mirrors the channel profile
    write-through PATCH shape)."""

    allowedOrigins: Optional[List[str]] = None
    appearance: Optional[WebchatAppearanceUpdate] = None
    greeting: Optional[str] = None
    offlineGreeting: Optional[str] = None
    preChat: Optional[WebchatPreChatTogglesUpdate] = None


class WebchatConnectResult(ChannelItem):
    """`POST /omnichannel/onboarding/webchat/connect` result - the 201 body
    IS a `ChannelItem`, plus the widget secret, revealed exactly once
    (AC-WEB-18)."""

    widgetSecret: str


class RotateWidgetSecretResult(ApiModel):
    """`POST /omnichannel/channels/{id}/widget/rotate-secret` result - the
    new secret, revealed exactly once (AC-WEB-19)."""

    widgetSecret: str


class SignOutVisitorsResult(ApiModel):
    """`POST /omnichannel/channels/{id}/widget/sign-out-visitors` result -
    the secret is UNCHANGED (D-A7B-6); only the epoch moves."""

    tokenEpoch: int


# ── Web chat: the PUBLIC visitor API (plan 34 / A7b S2) ──────────────────────
class WebchatHostIdentity(BaseModel):
    """`{ userRef, hash }` (D-A7B-9) - a HOST identity assertion the
    customer's OWN server signs. Verified in
    `webchat_service.verify_host_identity` (HMAC-SHA256 against the
    channel's CURRENT widget secret, plan 34 S5) - missing, malformed or
    non-verifying is silently ignored (AC-WEB-56), never an error."""

    userRef: str
    hash: str


class WebchatSessionRequest(ApiModel):
    """`POST /public/omnichannel/webchat/{widgetKey}/session` body (plan
    §5.2). Every field optional - a brand-new visitor sends neither.

    Two deliberately different strictnesses (review round 1, S1):

    - `token` is typed. A non-string used to reach `decode_access_token(123)`
      -> `AttributeError` -> 500 on an unauthenticated surface; it is now
      just another session failure mode (the uniform 404).
    - `identity` is `Any`. AC-WEB-56 requires a missing, malformed or
      non-verifying host identity assertion to be SILENTLY IGNORED with the
      session proceeding anonymously - never an error and never a
      distinguishing response - so rejecting a wrong-shaped one at the
      envelope would break the contract. `webchat_service.
      verify_host_identity` is the ONE place it is inspected, and it already
      returns `None` for every non-`{userRef: str, hash: str}` shape
      (including a bare string or a list). `WebchatHostIdentity` stays the
      documented shape of the field.
    """

    token: Optional[str] = None
    identity: Optional[Any] = None


class VisitorMessage(ApiModel):
    """The visitor projection's wire shape (plan §5.2) - the ONLY shape a
    visitor's browser ever receives for a message, built EXCLUSIVELY by
    `services/webchat_projection.py` (D-A7B-17)."""

    id: str
    direction: Literal["in", "out"]
    text: Optional[str] = None
    media: Optional[Dict[str, Any]] = None
    quickReplies: Optional[List[Dict[str, Any]]] = None
    agentName: Optional[str] = None
    createdAt: datetime
    status: Optional[Literal["sent", "delivered", "read", "failed"]] = None


class WebchatSessionConfig(ApiModel):
    """The `config` block of the session response (plan §5.2) - everything
    the panel needs to render BEFORE a visitor sends a word."""

    appearance: WebchatAppearance
    greeting: str
    offlineGreeting: str
    preChat: WebchatPreChatToggles
    agentDisplayName: str
    # NEVER the raw `tenants.name` column (white-label; the `branding_service.
    # _to_response` precedent) - only a tenant's OWN configured branding
    # `appName`, else `None`. A `null` here is the panel's cue to render no
    # tenant name at all, never a house/product name.
    tenantName: Optional[str] = None
    brandTokens: Dict[str, Any] = {}


class WebchatSessionResult(ApiModel):
    """`POST /public/omnichannel/webchat/{widgetKey}/session` 200 body (plan
    §5.2). `online` is computed by the EXISTING `BusinessHoursService`
    (D-A7B-24/AC-WEB-52): an unconfigured workspace resolves `online: true`
    rather than guessing a schedule."""

    token: str
    expiresAt: datetime
    visitorId: str
    # S3 (AC-WEB-38) - the panel needs this to open the EXISTING conversation
    # WebSocket (`?workspaceId=<id>&token=<visitor token>`); the widget key
    # alone does not carry it and the plan's own contract never named a
    # field for it, so this is where it lands (parallel to `visitorId`).
    workspaceId: str
    config: WebchatSessionConfig
    online: bool
    messages: List[VisitorMessage] = []


class WebchatMessageRequest(ApiModel):
    """`POST /public/omnichannel/webchat/{widgetKey}/messages` body (plan
    §5.2). `hp` is the honeypot - a legitimate visitor's browser never fills
    it in (AC-WEB-32).

    `preChat` values are written write-if-empty (D-A7B-8/AC-WEB-54) - NEVER
    a lookup or a stitch against any other contact. Since review round 1
    (B3): `name` onto the visitor's OWN contact, `email`/`phone` onto their
    identity's `visitor_profile_json` as unverified, visitor-declared values,
    never onto `contacts.email`/`phone`/`phone_digits` (inbound stitch keys
    an unauthenticated caller must not be able to set).

    `Dict[str, Any]`, not `Dict[str, str]`, on purpose: AC-WEB-54 says a bad
    pre-chat value is silently DROPPED, never rejected (the visitor cannot
    see or fix the field any more), so type-checking happens value by value
    in `_clean_pre_chat_value`, not at the envelope. `text`/`hp` are the
    opposite: they are the request itself, so a non-string there is a
    typed 422 rather than an `AttributeError` 500 (review round 1, S1)."""

    text: str
    preChat: Optional[Dict[str, Any]] = None
    hp: Optional[str] = None


class VisitorProfile(ApiModel):
    """What a WEB CHAT visitor typed into the pre-chat form - UNVERIFIED and
    read-only (plan 34 review round 1, B3). Present on `ThreadItem` (and
    therefore on both gateway contact shapes, per the losslessness rule) so
    an agent can see the email/phone a visitor gave without those values
    being written onto the contact's own `email`/`phone` columns, which are
    inbound STITCH KEYS. Every field is optional and `null` on every channel
    type but `WEBCHAT`."""

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class WebchatMessagesPage(ApiModel):
    """`GET /public/omnichannel/webchat/{widgetKey}/messages` 200 body (plan
    §5.2) - oldest to newest, page-capped; also the poll-fallback shape
    (D-A7B-16, the SAME endpoint serves history and the fallback)."""

    data: List[VisitorMessage]
    nextAfter: Optional[str] = None


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
    # The channel's type (plan 32 / A7a, AC-CHN-56) - resolved the SAME
    # tenant-scoped way as `ThreadItem.channelType`. Lets a consumer (or the
    # frontend composer/badge) branch per message without a second lookup;
    # `null` only for a legacy/internal row with no channel (e.g. a comment).
    channelType: Optional[str] = None
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
    # A Messenger/Instagram inbound attachment whose short-lived CDN url
    # could not be fetched in time (D-A7-12/plan 32 S5) - the message still
    # lands (never dropped), but there is no blob to render. Promoted to a
    # typed top-level flag (never left inside the free-form `payload`, which
    # is reserved for structured interactive/location/contacts content) so
    # the composer can render a muted placeholder without sniffing `payload`.
    mediaUnavailable: bool = False
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
    # A CORE `public.teams` id (plan 28 S2, D-A8-3) - resolved tenant-scoped
    # through the teams capability, batched per page. A foreign/deleted team
    # id (or the capability not being registered, AC-TEM-15) renders
    # `assignedTeamName: null`, never another tenant's team name.
    assignedTeamId: Optional[str] = None
    assignedTeamName: Optional[str] = None
    status: str  # OPEN | SNOOZED | CLOSED
    priority: str
    channelId: Optional[str] = None
    channelType: str
    cswExpiresAt: Optional[datetime] = None
    # Per-identity messaging window (plan 32 / A7a, D-A7-5) - generalizes
    # `cswExpiresAt` to every channel type. For a WHATSAPP thread this is the
    # SAME instant as `cswExpiresAt`; for FACEBOOK/INSTAGRAM `cswExpiresAt`
    # stays null (it is a documented WhatsApp-only field, F4) while these two
    # carry the real window.
    windowExpiresAt: Optional[datetime] = None
    humanAgentExpiresAt: Optional[datetime] = None
    # Plan 34 (A7b, D-A7B-19/AC-WEB-42) - a presence fact, not an
    # authorization fact: null on every channel type but WEBCHAT, and null
    # on a WEBCHAT thread until the visitor's first session/message/socket
    # connect. Also read on both gateway shapes (S6, the losslessness rule).
    visitorLastSeenAt: Optional[datetime] = None
    # Plan 34 (A7b, review round 1 B3) - the UNVERIFIED name/email/phone a
    # web chat visitor typed into pre-chat, read-only. Null on every channel
    # type but WEBCHAT, and null on a WEBCHAT thread whose visitor was never
    # asked (or never answered). Never a lookup key anywhere.
    visitorProfile: Optional[VisitorProfile] = None
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
    matching `kind` (D-A4-2 - configuration only, never a stored list).

    `filter` is a RAW dict here, not a typed `FilterGroup` (post-approval
    fix, O-5): a typed nested model with `extra="forbid"` rejects a stray
    filter key during FastAPI's automatic body validation, BEFORE the
    router function ever runs - the caller gets pydantic's raw
    `{"detail": [{"type": "extra_forbidden", ...}]}` shape instead of the
    uniform `{"fieldErrors"}` 422 every other broadcast validation error
    uses. `BroadcastService` re-validates it into a real `FilterGroup`
    (`_parse_audience_filter`) inside the service layer, where a bad shape
    can be turned into `{"fieldErrors": {"audience.filter": "..."}}` like
    every other audience error (same path as the empty-group guard, D-4)."""

    kind: Literal["segment", "filter", "contacts"]
    segmentId: Optional[str] = None
    filter: Optional[Dict[str, Any]] = None
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


class BroadcastTestSendRequest(ApiModel):
    """Plan 29 S2b, AC-BRD-41 - ONE explicit contact, never a recipient
    picker over the audience (D-A4-18: a test send is a message, not a
    campaign event)."""

    contactId: str


class BroadcastTestSendResponse(ApiModel):
    messageId: str


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


class TeamAssignmentSettingItem(ApiModel):
    """The per-(workspace, CORE team) pick-strategy row (plan 28 S2,
    AC-TEM-28). `teamName` resolves through the teams capability (null on a
    foreign/deleted team, same rule as `ThreadItem.assignedTeamName`).

    Review round 1, finding 4/5/6: `GET .../team-settings` now returns one
    row per ACTIVE core team (not just previously-configured ones), so
    `updatedAt` is `None`/`isConfigured` is `false` for a team that has never
    had its strategy set."""

    teamId: str
    teamName: Optional[str] = None
    strategy: str  # round_robin | least_open
    lastAssignedUserId: Optional[str] = None
    updatedAt: Optional[datetime] = None
    isConfigured: bool = False


class TeamAssignmentSettingUpdate(ApiModel):
    strategy: str  # round_robin | least_open


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
    # AC-TEM-46 (plan 28, roadmap A8, review round 1 finding 9) - a Team
    # Inbox scope a saved view can pin. Validated tenant-scoped at save time
    # via the core `team.resolve@1` capability (`_validate_filter_ids`
    # below); views saved before this slice have no `teamIds` key and keep
    # working unchanged (`None` = no team scope, not "every team").
    teamIds: Optional[List[str]] = None


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
    # A CORE team id, or explicit `null` to clear it (plan 28 S2) - native-
    # only (an embed/external-agent token gets 403, D-A8-13).
    assignedTeamId: Optional[str] = None
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


# ── Business hours (plan sprint-4/31 S5, D-A5-13) ────────────────────────────
class BusinessHoursUpdate(ApiModel):
    """`timezone` = an IANA name; `windows` = {mon: [{from,to}], ..., sun: []}
    (§5.4 - overnight windows where `to` <= `from` are valid). Validated
    server-side (`business_hours.validate_timezone`/`validate_windows`) - the
    router maps a `BusinessHoursValidationError` to a 422 `{fieldErrors}`."""

    timezone: str
    windows: dict


class BusinessHoursResponse(ApiModel):
    workspaceId: str
    timezone: Optional[str] = None
    windows: dict


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
    # Optional explicit channel selector (plan 32 / A7a, D-A7-18, AC-CHN-53) -
    # an ACTIVE channel of THIS workspace. Omitted → prefer an active
    # WHATSAPP channel, else the oldest active channel of any type (byte-
    # identical to every pre-slice consumer). An unknown/foreign/inactive id
    # is a typed `422 invalid_channel`, never a silent fallback.
    channelId: Optional[str] = None
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
    # A CORE `public.teams` id, or explicit `null` to clear it (plan 28 S4).
    # BY ID ONLY - never by name, never auto-creating a team (D-A8-6).
    assignedTeamId: Optional[str] = None
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
    # Per-identity messaging window (plan 32 / A7a, D-A7-5) - the Foundryx
    # extension every non-WhatsApp consumer needs; `cswExpiresAt` above keeps
    # its documented WhatsApp-only meaning verbatim.
    windowExpiresAt: Optional[str] = None
    humanAgentExpiresAt: Optional[str] = None
    priority: Optional[str] = None            # LOW | MEDIUM | HIGH | URGENT
    channelId: Optional[str] = None
    channelType: Optional[str] = None         # WHATSAPP | FACEBOOK | INSTAGRAM | WEBCHAT
    # Plan 34 (A7b, D-A7B-19) - the same presence fact as `ThreadItem.
    # visitorLastSeenAt` (losslessness rule, AC-WEB-59): null on every
    # channel type but WEBCHAT, and null on a WEBCHAT contact until the
    # visitor's first session/message/socket connect.
    visitorLastSeenAt: Optional[str] = None
    # Plan 34 (A7b, review round 1 B3) - the same UNVERIFIED pre-chat values
    # as `ThreadItem.visitorProfile` (losslessness rule): a gateway consumer
    # has no other read source for them, and they are deliberately NOT the
    # contact's own `phone`/`email` above.
    visitorProfile: Optional[VisitorProfile] = None
    unreadCount: int = 0
    lastMessageAt: Optional[str] = None
    lastIncomingMessageAt: Optional[str] = None
    lastMessagePreview: Optional[str] = None
    # A CORE `public.teams` id/name (plan 28 S4, D-A8-6). respond.io has no
    # team field on a contact - kept here as a Foundryx extension so this
    # shape stays lossless versus the internal `ThreadItem` (a consumer has
    # no other read source for it). Null on a foreign/deleted team or when
    # the teams capability is not registered, same rule as `ThreadItem`.
    assignedTeamId: Optional[str] = None
    assignedTeamName: Optional[str] = None


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
    # Deliberately ALWAYS null (plan 28, D-A8-6 flag 8) - a message-level team
    # concept (which team sent this) is a second, distinct notion from the
    # thread-level `assignedTeamId` on the contact and is out of scope here.
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
    # Mirrors `MessageItem.mediaUnavailable` (plan 32 / A7a) - a Messenger/
    # Instagram inbound attachment whose short-lived CDN url expired before
    # it could be fetched. `None` (never `False`) for a message that was
    # never media in the first place, keeping this shape lossless vs the
    # internal item without inventing a value the source never had.
    mediaUnavailable: Optional[bool] = None


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
    channelType: Optional[str] = None  # WHATSAPP | FACEBOOK | INSTAGRAM | WEBCHAT
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


# ── Plan 30 - Dashboard + Reports v1 (roadmap A9) ────────────────────────────
# No new fact tables (D-A9-1) - every shape below is an aggregate over
# `conversation_events` + `conversation_messages` + `contacts`. Mirrors
# `service_frontend/types/omnichannel.ts` (the S0 mock's own contract).


class ReportBucketItem(ApiModel):
    """A bucket's `key` is already LOCAL (D-A9-11: `2026-03-01`,
    `2026-03-01T09`, `2026-W10`, `2026-03`) - the client formats the axis
    label from it and NEVER re-applies a timezone. Only `startsAt`/`endsAt`
    are UTC instants."""

    key: str
    startsAt: datetime
    endsAt: datetime


class ReportSeriesItem(ApiModel):
    key: str
    label: str
    points: List[int]


class DurationStatsItem(ApiModel):
    """Response-time / resolution-time reduction (Python-side, D-A9-9)."""

    medianSeconds: Optional[int] = None
    p90Seconds: Optional[int] = None
    averageSeconds: Optional[int] = None
    sampleCount: int
    # How many datapoints were derived from messages rather than the
    # `first_agent_reply` event (D-A9-6) - carried for support, never
    # rendered as on-screen caveat copy (plan §8.1 item 10).
    derivedFromMessages: Optional[int] = None


class DashboardLifecycleStageItem(ApiModel):
    statusId: str
    key: str
    label: str
    color: Optional[str] = None
    sortOrder: int
    count: int
    percent: float


class DashboardTopAgentItem(ApiModel):
    userId: str
    name: str
    closedCount: int
    medianResponseSeconds: Optional[int] = None


class DashboardTiles(ApiModel):
    open: int
    assigned: int
    unassigned: int
    snoozed: int


class DashboardSeries(ApiModel):
    opened: List[int]
    closed: List[int]


class ReportRange(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str


class DashboardResponse(ApiModel):
    timezone: str
    range: ReportRange
    granularity: str
    buckets: List[ReportBucketItem]
    tiles: DashboardTiles
    lifecycle: List[DashboardLifecycleStageItem]
    series: DashboardSeries
    responseTotals: DurationStatsItem
    resolutionTotals: DurationStatsItem
    topAgents: List[DashboardTopAgentItem]


class ReportDimensionAvailability(ApiModel):
    available: bool


class ReportDimensions(ApiModel):
    team: ReportDimensionAvailability


class ReportDescriptorItem(ApiModel):
    key: str
    label: str
    supportsGroupBy: List[str]
    paginated: bool
    exportable: bool


class ReportMetaResponse(ApiModel):
    reports: List[ReportDescriptorItem]
    granularities: List[str]
    dimensions: ReportDimensions


# ── Plan 30 - S2 the seven report builders + assignment log ─────────────────
# `rows`/`totals` are per-report shapes (plan §5.2 table) - kept as plain
# JSON-safe dict/list here rather than a per-report Pydantic union so ONE
# envelope serves all seven `reportKey`s (mirrors `types/omnichannel.ts`
# `ReportResponse<TRow, TTotals>`, which is generic for the same reason).
# Every datetime a row carries (only the assignment log's `createdAt`) is
# pre-formatted to a Z-suffixed ISO string by the service BEFORE it lands in
# this dict - `ApiModel`'s wildcard datetime serializer only nets top-level
# fields, never a `datetime` nested inside a `Dict[str, Any]` (see its own
# docstring caveat), so a raw `datetime` must never be placed in `rows` here.
class ReportResponse(ApiModel):
    reportKey: str
    timezone: str
    range: ReportRange
    granularity: str
    buckets: List[ReportBucketItem]
    series: List[ReportSeriesItem]
    rows: List[Dict[str, Any]]
    totals: Dict[str, Any]
    page: Optional[int] = None
    pageSize: Optional[int] = None
    total: Optional[int] = None


# ── Plan 30 - S3 report export (plan §5.1/§5.4, D-A9-4) ─────────────────────
class ReportExportRequest(ApiModel):
    """`POST .../reports/{reportKey}/export` body - the SAME filter shape the
    read route accepts as query params (plan §5.1), carried as JSON so the
    job payload can echo it verbatim. `groupBy`/`teamId` are validated the
    SAME way the read route validates them (`report_export_service` calls
    the ONE `report_service.report`/`build_query` gate - never a second
    validation path)."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    tz: str
    granularity: Optional[str] = None
    userId: Optional[str] = None
    channelId: Optional[str] = None
    teamId: Optional[str] = None
    groupBy: Optional[str] = None


# ── Plan 33 - respond.io migration, S1 preflight (plan §5.2, AC-MIG-14) ─────
# Mirrors `service_frontend/types/respondio-migration.ts` exactly - S2 adds
# the job-create/list/detail schemas alongside `MigrationService` (the phase
# orchestrator) in the same slice that needs them.
class MigrationSourceChannel(ApiModel):
    id: str
    name: str
    source: str


class MigrationSourceUser(ApiModel):
    id: str
    firstName: str
    lastName: str
    email: str
    role: str
    teamId: Optional[str] = None
    teamName: Optional[str] = None


class MigrationSourceTeam(ApiModel):
    id: str
    name: str


class MigrationSourceField(ApiModel):
    id: str
    name: str
    dataType: str


class MigrationTargetChannel(ApiModel):
    id: str
    name: str
    channelType: str


class MigrationTargetStage(ApiModel):
    statusId: str
    label: str


class MigrationPreflight(ApiModel):
    apiAvailable: bool
    spaceLabel: str
    channels: List[MigrationSourceChannel]
    users: List[MigrationSourceUser]
    teams: List[MigrationSourceTeam]
    fields: List[MigrationSourceField]
    # Decision taken where the plan's §5.2 preflight response was silent (S0
    # evidence README "what S1 must know"): AC-MIG-06 needs every OBSERVED
    # source lifecycle label before any dry run exists, and none of the other
    # preflight calls touch a contact - so this is filled by one read-only
    # distinct-value pass over `contact.lifecycle` (zero writes, AC-MIG-14).
    lifecycles: List[str]
    targetChannels: List[MigrationTargetChannel]
    targetStages: List[MigrationTargetStage]
    warnings: List[str]


# ── Plan 33 S2 - migration job (plan §5.2, AC-MIG-18..29) ───────────────────
class MigrationChannelMapEntry(ApiModel):
    sourceChannelId: str
    targetChannelId: Optional[str] = None  # None = "Skip this channel" (AC-MIG-04)


class MigrationUserMapEntry(ApiModel):
    sourceUserId: str
    targetUserId: Optional[str] = None


class MigrationTeamMapEntry(ApiModel):
    sourceTeamId: str
    targetTeamId: Optional[str] = None


class MigrationLifecycleMapEntry(ApiModel):
    sourceLabel: str
    targetStatusId: Optional[str] = None  # None = unmapped, allowed (AC-MIG-06)


class MigrationJobCreate(ApiModel):
    """`POST /omnichannel/migration/jobs` body (§5.2). `messagesSince` stays a
    plain `Optional[str]` (not `datetime`) so a malformed value is a HOUSE
    `{fieldErrors: {messagesSince: ...}}` 422 the service raises itself,
    never FastAPI's own un-housed pydantic-datetime 422 shape - the plan's
    §5.2 422-paths list treats it exactly like `connectionId`/`workspaceId`.

    `extra="forbid"` (review round 1, finding B2) - the RETIRED free-string
    `contactsCsvKey`/`snippetsCsvKey` fields must 422 (`extra_forbidden`)
    rather than silently pass through and be ignored; a caller still on the
    old contract needs a loud failure, not a job that quietly never reads a
    contacts file."""

    model_config = ConfigDict(extra="forbid")

    # S5 (D-A6-25 below): a CSV-mode job has no working respond.io API access
    # at all, so `connectionId` is OPTIONAL - a customer with zero API access
    # never created a connection row. When present (even in CSV mode, purely
    # to carry `spaceLabel` for display), it is still resolved tenant-scoped
    # exactly like an API-mode job (AC-MIG-51/52) - never a bare lookup.
    connectionId: Optional[str] = None
    workspaceId: str
    mode: Literal["dry_run", "run"]
    source: Literal["api", "csv"] = "api"
    channelMap: List[MigrationChannelMapEntry] = []
    userMap: List[MigrationUserMapEntry] = []
    teamMap: List[MigrationTeamMapEntry] = []
    lifecycleMap: List[MigrationLifecycleMapEntry] = []
    messagesSince: Optional[str] = None
    contactsOnly: bool = False
    # S5 (AC-MIG-47, D-A6-25) - `source="csv"` reads this contacts export
    # through `app/import_engine/readers.py read_rows`, mapped by
    # `csvHeaderMap` (system field key -> the file's own header string; a
    # key with no entry falls back to a case-insensitive alias guess,
    # `migration_service._HEADER_ALIASES`).
    #
    # `contactsUploadId`/`snippetsUploadId` (review round 1, finding B2 -
    # REPLACES the earlier `contactsCsvKey`/`snippetsCsvKey` free-string
    # fields) are the OPAQUE id `POST /omnichannel/migration/uploads`
    # returns (`kind=contacts`/`kind=snippets`) - never a raw storage key a
    # client could substitute for path traversal or another tenant's blob.
    # `MigrationService.create_job` resolves each id tenant-scoped
    # (`_require_upload`, uniform 404 on foreign/unknown) and carries the
    # RESOLVED storage key forward internally under the job payload's own
    # `contactsCsvKey`/`snippetsCsvKey` keys - the phase-processing code
    # never changes, only this wire contract does.
    contactsUploadId: Optional[str] = None
    csvHeaderMap: Dict[str, str] = {}
    snippetsUploadId: Optional[str] = None


class MigrationEntityCounts(ApiModel):
    fetched: int = 0
    wouldCreate: int = 0
    wouldUpdate: int = 0
    wouldSkip: int = 0
    errors: int = 0


class MigrationReport(ApiModel):
    entities: Dict[str, MigrationEntityCounts]
    messagesWithInferredTimestamp: int = 0
    # S4 (D-A6-22) - messages older than the job's `messagesSince` floor are
    # excluded from the walk entirely (never written, never counted as an
    # error) - this is how many were skipped that way, reported so the
    # operator's volume estimate (plan §7 prerequisite 9) still reconciles.
    messagesSkippedBeforeFloor: int = 0
    # S11 (review round 1) - contacts whose whole message history exceeded
    # `MAX_MESSAGES_PER_CONTACT` and were skipped entirely (also surfaced as
    # a human-readable `blockers` line).
    messagesSkippedOverCap: int = 0
    # Defect 2 fix (test report round 1) - CSV-mode's per-VALUE unmapped
    # lifecycle tally (raw CSV value -> contact count), also surfaced as
    # per-value `blockers` lines. Empty for API-mode jobs.
    lifecycleUnmappedByValue: Dict[str, int] = {}
    blockers: List[str] = []
    samples: Dict[str, List[dict]]


class MigrationFailureRow(ApiModel):
    entity: str
    sourceId: str
    sourceLabel: str
    reason: str
    action: str


class MigrationJobLogEntry(ApiModel):
    """One milestone log line (`JobService.log()`'s `{ts, level, message}`
    shape off `background_jobs.logs_json`) - S6 (AC-MIG-08) surfaces these on
    the detail page; S0-S2 wrote them (rate-limit backoff, abort, page
    milestones) but never plumbed them past `logs_json` itself."""

    ts: datetime
    level: str
    message: str


# ── Plan 33 S5 - CSV upload (plan §5.2 extension, AC-MIG-46..49) ────────────
class MigrationUploadResult(ApiModel):
    """`POST /omnichannel/migration/uploads` response - an OPAQUE receipt
    `id` (review round 1, finding B2 - NEVER the raw storage key; see
    `MigrationJobCreate.contactsUploadId`/`snippetsUploadId`'s own docstring)
    the job payload then references, plus enough of the sniffed file (row
    count + headers) for the setup form to render the header-mapping step
    without a second round trip."""

    id: str
    rowCount: int
    headers: List[str]


class MigrationJobItem(ApiModel):
    """Read shape for the list + detail routes (§5.2) - built by
    `MigrationService._to_item` from a `background_jobs` row (never
    `from_attributes`, since `mode`/`source`/`spaceLabel`/`workspaceName`/
    `report`/`failure*` are all derived from `payload_json`/`cursor_json`/
    `result_json`, not native columns)."""

    id: str
    mode: str
    source: str
    # Optional (test report Defect 1) - `payload.get("connectionId", "")`
    # only defaults when the KEY IS ABSENT, not when it is present-and-JSON-
    # `null` (every REAL create path stores `connectionId or ""`, so a
    # genuine CSV-mode job never persists a literal `null` - this is a
    # defensive-coding gap for a hand-built/legacy row, not a reachable
    # regression). `Optional[str] = None` matches the request-side
    # `MigrationJobCreate.connectionId` and never 500s the whole list route.
    connectionId: Optional[str] = None
    spaceLabel: str
    workspaceId: str
    workspaceName: str
    status: str
    progressTotal: int
    progressDone: int
    progressFailed: int
    entityCounts: Optional[Dict[str, int]] = None
    report: Optional[MigrationReport] = None
    failureCount: int = 0
    failureSample: List[MigrationFailureRow] = []
    startedAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None
    createdAt: datetime
    actorUserName: Optional[str] = None
    # S6 (AC-MIG-08) - the milestone log the detail page renders. Omitted
    # from the LIST read (`_to_item(..., include_logs=False)`) - a page of
    # 25 jobs has no use for each row's own log line-by-line, and every
    # abort/backoff/page-milestone line would bloat that response for free.
    logs: List[MigrationJobLogEntry] = []


class MigrationJobListResponse(ApiModel):
    data: List[MigrationJobItem]
    total: int
    page: int
