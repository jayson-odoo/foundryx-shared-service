"""Omnichannel module models - all live in the ``app_omnichannel`` schema.

Every tenant-scoped table carries ``tenant_id`` (FK core ``tenants``) and, where
workspace-scoped, ``workspace_id``. Datetimes are tz-aware UTC (CLAUDE.md rule).
Contacts/messages/identities/templates/quick_replies tables are created here
(schema is owned by plan 04) but only operated on from plan 05.
"""
import uuid
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import JSON
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from .db import OmniBase


def _uuid() -> str:
    return str(uuid.uuid4())


# Full outbound/inbound message-type vocabulary (plan 12 §Locked D3). Slice 1
# sends/receives the media set; INTERACTIVE*/LOCATION/CONTACTS/REACTION land in
# slices 2/3 (the enum is widened now so their rows validate).
MESSAGE_TYPES = (
    "TEXT",
    "IMAGE",
    "VIDEO",
    "AUDIO",
    "VOICE",
    "DOCUMENT",
    "STICKER",
    "INTERACTIVE",
    "INTERACTIVE_REPLY",
    "LOCATION",
    "CONTACTS",
    "REACTION",
    "TEMPLATE",
)
# The media-bearing kinds handled by the upload-by-id pipeline (Slice 1).
MEDIA_MESSAGE_TYPES = ("IMAGE", "VIDEO", "AUDIO", "VOICE", "DOCUMENT", "STICKER")


class Status(OmniBase):
    """Static lookup for workspace/channel/thread state (no transition engine yet)."""

    __tablename__ = "statuses"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String,nullable=False, index=True)
    scope = Column(String, nullable=False)  # WORKSPACE | CHANNEL | THREAD
    key = Column(String, nullable=False)  # OPEN | SNOOZED | CLOSED | ACTIVE | ...
    label = Column(String, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    is_terminal = Column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("tenant_id", "scope", "key", name="uq_status_scope_key"),)


class Workspace(OmniBase):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String,nullable=False, index=True)
    name = Column(String, nullable=False)
    status_id = Column(String, ForeignKey("statuses.id"), nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    is_trashed = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkspaceMember(OmniBase):
    __tablename__ = "workspace_members"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String,nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id = Column(String,nullable=False, index=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )


class Channel(OmniBase):
    __tablename__ = "channels"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String,nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    channel_type = Column(String, nullable=False, default="WHATSAPP")
    name = Column(String, nullable=False)
    credentials_json = Column(Text, nullable=True)  # Fernet-encrypted
    waba_id = Column(String, nullable=True)
    # Service-wide unique among live channels via a PARTIAL unique index (migration
    # 0002, WHERE phone_number_id IS NOT NULL AND is_trashed=false) - inbound
    # routing keys off it (O(1)). index=True mirrors that for the create_all path.
    phone_number_id = Column(String, nullable=True, index=True)
    display_phone_number = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    status_id = Column(String, ForeignKey("statuses.id"), nullable=True)
    webhook_verify_token = Column(String, nullable=True)
    last_verified_at = Column(UTCDateTime(), nullable=True)
    # ── WABA configuration mirror (plan 06 §2; Meta system-of-record, synced) ──
    business_account_name = Column(String, nullable=True)  # GET /{waba_id}?fields=name
    verified_name = Column(String, nullable=True)  # from fetch_phone_details
    # ── WhatsApp Business Profile mirror (write-through, plan 06 §2) ──
    profile_about = Column(String, nullable=True)
    profile_address = Column(String, nullable=True)
    profile_description = Column(Text, nullable=True)
    profile_email = Column(String, nullable=True)
    profile_vertical = Column(String, nullable=True)  # Meta industry enum value
    profile_website_1 = Column(String, nullable=True)
    profile_website_2 = Column(String, nullable=True)
    profile_picture_url = Column(String, nullable=True)  # display-only (upload BL-108)
    profile_synced_at = Column(UTCDateTime(), nullable=True)
    is_trashed = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Contact(OmniBase):
    """Consolidated CRM profile + thread metadata (operated on in plan 05)."""

    __tablename__ = "contacts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String,nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True, index=True)
    avatar_url = Column(String, nullable=True)
    custom_fields_json = Column(JSON, nullable=True)
    assigned_user_id = Column(String,nullable=True)
    # Federated (embed) assignee - set instead of ``assigned_user_id`` when the
    # thread is assigned by an external agent (plan 11H Slice 1). Plain indexed
    # str, no FK (mirrors ``assigned_user_id`` - external_agent lives in this
    # schema but the no-FK convention keeps the assignee columns symmetric).
    assigned_external_agent_id = Column(String, nullable=True, index=True)
    status_id = Column(String, ForeignKey("statuses.id"), nullable=True)
    priority = Column(String, nullable=False, default="MEDIUM")
    # ── Contact data model (plan 25 S1/S2) ──────────────────────────────────
    # BCP-47 tag (e.g. "en", "zh-Hans"); ISO-3166 alpha-2 upper-cased.
    language = Column(String, nullable=True)
    country_code = Column(String, nullable=True)
    # Plain indexed column pointing at a CORE `statuses` row - no cross-schema
    # FK (BL-030 pattern, matches `assigned_external_agent_id` above). Set by
    # S2 (the scoped `omnichannel_contact_lifecycle` status entity); stays NULL
    # until that lands, and the wire `lifecycle` field stays null until then.
    lifecycle_status_id = Column(String, nullable=True, index=True)
    csw_expires_at = Column(UTCDateTime(), nullable=True)
    last_incoming_message_at = Column(UTCDateTime(), nullable=True)
    last_message_at = Column(UTCDateTime(), nullable=True)
    # When an agent last opened the thread - unreadCount = inbound newer than
    # this (plan 05; added Phase B, idempotent ALTER in bootstrap.install).
    agent_last_read_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ContactChannelIdentity(OmniBase):
    __tablename__ = "contact_channel_identities"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String,nullable=False, index=True)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    channel_id = Column(String, ForeignKey("channels.id"), nullable=False, index=True)
    external_user_id = Column(String, nullable=False)
    profile_name = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("channel_id", "external_user_id", name="uq_identity_channel_external"),
    )


class ContactField(OmniBase):
    """A per-workspace registered custom field (plan 25 S1). Values live in
    `Contact.custom_fields_json[key]`, validated against this row's `type` on
    every write (`ContactFieldService`). `key` + `type` are immutable after
    create (D6) - enforced in the service, not the DB. Uniqueness (per
    workspace, case-insensitive) is also app-enforced (`func.lower` lookup) -
    no DB constraint, so it stays portable across the SQLite test suite."""

    __tablename__ = "contact_fields"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    key = Column(String, nullable=False)
    label = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String, nullable=False)  # text|list|checkbox|email|number|url|date|time
    options_json = Column(JSON(none_as_null=True), nullable=True)  # `list` type only
    visibility = Column(String, nullable=False, default="always")  # always|hidden
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ContactTag(OmniBase):
    """A per-workspace tag (plan 25 S1). Attached to contacts via
    `ContactTagLink`. Name uniqueness (per workspace, case-insensitive) is
    app-enforced, same reasoning as `ContactField.key`."""

    __tablename__ = "contact_tags"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    emoji = Column(String, nullable=True)
    color = Column(String, nullable=True)  # hex
    description = Column(Text, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ContactTagLink(OmniBase):
    """A contact <-> tag attachment (plan 25 S1). Replaced wholesale on every
    `tagIds` PATCH (`ContactTagService.replace_links`) - never merged."""

    __tablename__ = "contact_tag_links"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    tag_id = Column(String, ForeignKey("contact_tags.id"), nullable=False, index=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("contact_id", "tag_id", name="uq_contact_tag_link"),
    )


class ConversationMessage(OmniBase):
    __tablename__ = "conversation_messages"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String,nullable=False, index=True)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    # Nullable: SYSTEM internal notes belong to the thread, not a channel.
    channel_id = Column(String, ForeignKey("channels.id"), nullable=True, index=True)
    sender_type = Column(String, nullable=False)  # AGENT | CONTACT | SYSTEM
    sender_id = Column(String, nullable=True)
    # Federated (embed) sender - set instead of ``sender_id`` when the message is
    # sent by an external agent (plan 11H Slice 1). The conversation mapper
    # resolves display name/avatar from whichever column is set.
    sender_external_agent_id = Column(String, nullable=True, index=True)
    message_type = Column(String, nullable=False, default="TEXT")
    body = Column(Text, nullable=True)
    # LEGACY (plan 04/05): full public URL of an inbound media blob. Deprecated by
    # plan 12 - new media rides ``media_key`` (served via the blob endpoint). Kept
    # so pre-plan-12 rows stay valid; the wire ``mediaUrl`` prefers ``media_key``.
    media_url = Column(String, nullable=True)
    # ── Rich media (plan 12 §Locked D3): storage KEY (never a presigned URL) +
    # sniffed metadata. The wire ``mediaUrl`` is a @property off ``media_key``. ──
    media_key = Column(String, nullable=True)
    media_mime = Column(String, nullable=True)
    media_filename = Column(String, nullable=True)
    media_size = Column(Integer, nullable=True)
    # Structured payload for non-text types (interactive/location/contacts/
    # reaction definitions - slices 2/3). JSON(none_as_null) per the house rule.
    payload_json = Column(JSON(none_as_null=True), nullable=True)
    external_message_id = Column(String, nullable=True, index=True)
    delivery_status = Column(String, nullable=True)  # QUEUED | SENT | DELIVERED | READ | FAILED
    error_code = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    @property
    def media_url_wire(self) -> Optional[str]:
        """The URL the frontend renders (plan 12 D3/D8). A stored ``media_key``
        resolves to the authed blob-fetch endpoint (relative path - the agent's
        browser fetches it with the Bearer via ``apiFetchBlob``); otherwise fall
        back to the legacy stored ``media_url``. No presigned URL is ever
        persisted (it would expire)."""
        if self.media_key:
            return f"/omnichannel/media/{self.id}"
        return self.media_url

    __table_args__ = (
        UniqueConstraint("external_message_id", name="uq_message_external_id"),
    )


class MessageReaction(OmniBase):
    """A reaction (emoji) on a message - plan 12 Slice 3 (AC-12-19).

    Never a message row: reactions upsert here keyed to the target message +
    the reactor, so re-reacting replaces and an empty emoji deletes. ``reactor``
    is the stable id of who reacted - the contact's wa id/phone for CONTACT,
    the user id for AGENT - so ``UNIQUE(target_message_id, reactor)`` holds one
    reaction per party per message.
    """

    __tablename__ = "message_reactions"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    workspace_id = Column(String, nullable=True, index=True)  # WS realtime room
    target_message_id = Column(
        String, ForeignKey("conversation_messages.id"), nullable=False, index=True
    )
    reactor_type = Column(String, nullable=False)  # CONTACT | AGENT
    reactor = Column(String, nullable=False)  # wa id/phone (contact) or user id (agent)
    emoji = Column(String, nullable=False)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("target_message_id", "reactor", name="uq_reaction_target_reactor"),
    )


class WhatsappTemplate(OmniBase):
    __tablename__ = "whatsapp_templates"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String,nullable=False, index=True)
    channel_id = Column(String, ForeignKey("channels.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    language = Column(String, nullable=True)
    category = Column(String, nullable=True)
    components_json = Column(JSON, nullable=True)
    status = Column(String, nullable=True)
    synced_at = Column(UTCDateTime(), nullable=True)
    # ── Template management (plan 07 §2) ──
    meta_template_id = Column(String, nullable=True)  # Meta message_template_id / hsm_id
    quality = Column(String, nullable=True)  # GREEN/YELLOW/RED
    rejected_reason = Column(String, nullable=True)
    last_synced_at = Column(UTCDateTime(), nullable=True)
    media_sample_key = Column(String, nullable=True)  # storage key for a draft media-header sample
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class WorkspaceApiKey(OmniBase):
    """Public-gateway API key, issued per workspace (plan sprint-1/01 Slice 3).

    The plaintext key (``fxw_live_…``) is shown ONCE at mint and never stored -
    only its SHA-256 ``key_hash`` (for constant-time verification) and an 8-char
    ``key_prefix`` (indexed O(1) lookup). A key resolves to (tenant, workspace,
    service=omnichannel); multiple active keys per workspace support rotation.
    """

    __tablename__ = "workspace_api_keys"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    key_prefix = Column(String, nullable=False, index=True)  # 8 chars after "fxw_live_"
    key_hash = Column(String, nullable=False)  # sha256 hex (64 chars)
    last_used_at = Column(UTCDateTime(), nullable=True)
    revoked_at = Column(UTCDateTime(), nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class WebhookEndpoint(OmniBase):
    """A consumer's webhook subscription (plan sprint-1/01 Slice 4, AC-01-22).

    Scope = per CHANNEL (one WhatsApp number). A channel can have many endpoints
    (fan-out to N consumer systems). ``secret`` is a Fernet-encrypted signing
    secret (reversible - we HMAC-sign every delivery with it AND reveal it to the
    consumer on create/rotate). ``events`` selects which event types forward.
    Auto-disable: after ``consecutive_failures`` exhausted deliveries reach the
    threshold the status flips to AUTO_DISABLED until re-enabled.
    """

    __tablename__ = "webhook_endpoints"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    workspace_id = Column(String, nullable=False, index=True)
    channel_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    secret_encrypted = Column(Text, nullable=False)  # Fernet(signing secret)
    events_json = Column(JSON, nullable=False, default=list)  # ["message.inbound", …]
    status = Column(String, nullable=False, default="ACTIVE")  # ACTIVE|DISABLED|AUTO_DISABLED
    consecutive_failures = Column(Integer, nullable=False, default=0)
    disabled_at = Column(UTCDateTime(), nullable=True)
    disabled_reason = Column(String, nullable=True)
    last_success_at = Column(UTCDateTime(), nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WebhookDelivery(OmniBase):
    """One durable delivery attempt-set for an event → endpoint (AC-01-24).

    The outbox row is the source of truth: created PENDING, POSTed with backoff
    retries, marked SUCCESS on 2xx or FAILED (dead-letter, attempts preserved)
    on exhaustion. ``event_id`` is the consumer's dedup key (at-least-once).
    """

    __tablename__ = "webhook_deliveries"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    endpoint_id = Column(String, nullable=False, index=True)
    event_id = Column(String, nullable=False)  # stable dedup key
    event_type = Column(String, nullable=False)
    payload_json = Column(JSON, nullable=False)  # the full signed envelope
    status = Column(String, nullable=False, default="PENDING")  # PENDING|SUCCESS|FAILED
    attempt_count = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(UTCDateTime(), nullable=True)
    last_attempt_at = Column(UTCDateTime(), nullable=True)
    response_status = Column(Integer, nullable=True)
    response_ms = Column(Integer, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
    )


class QuickReply(OmniBase):
    __tablename__ = "quick_replies"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String,nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    shortcut = Column(String, nullable=True)
    body = Column(Text, nullable=False)
    created_by = Column(String,nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OmnichannelSettings(OmniBase):
    """Per-workspace media caps (plan 12 §Locked D12/AC-12-12).

    ``workspace_id`` NULL = the tenant-wide default (resolved when a workspace has
    no row of its own). Per-type max-size overrides are clamped to Meta's hard
    ceilings at enforcement; NULL = use the Meta ceiling. Accepted mimes are fixed
    (Meta's set) and never tenant-configurable - the sniff-gate is the security
    boundary, not this table.
    """

    __tablename__ = "omnichannel_settings"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    workspace_id = Column(String, nullable=True, index=True)  # NULL = tenant default
    image_max_bytes = Column(Integer, nullable=True)
    video_max_bytes = Column(Integer, nullable=True)
    audio_max_bytes = Column(Integer, nullable=True)
    document_max_bytes = Column(Integer, nullable=True)
    sticker_max_bytes = Column(Integer, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace_id", name="uq_omnichannel_settings_ws"),
    )


class ExternalAgent(OmniBase):
    """Federated (embed) agent identity - plan 11H Slice 1 (AC-11H-01/02/03).

    A consumer (EMS) embeds the conversation UI as a chromeless iframe; its
    agents have NO shared-service login. On ``/embed/session`` we provision-or-load
    an external agent keyed by ``(connection_id, sub)`` - the connection is the
    consumer link, ``sub`` the consumer's agent id. ``(connection_id, sub)`` keeps
    two consumers whose agents share a ``sub`` value ("u-1") strictly distinct
    (cross-consumer isolation). No password, no login - provisioned on first use,
    name/email/avatar refreshed on later assertions.
    """

    __tablename__ = "external_agent"

    id = Column(String, primary_key=True, default=_uuid)
    # Derivable from the connection, but stored so display-name/avatar resolution
    # stays tenant-scoped (the polymorphic-target_id rule - never resolve a stored
    # id unscoped).
    tenant_id = Column(String, nullable=False, index=True)
    connection_id = Column(String, nullable=False, index=True)
    sub = Column(String, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("connection_id", "sub", name="uq_external_agent_conn_sub"),
    )


class EmbedJti(OmniBase):
    """Single-use ledger for embed assertion ``jti`` values - plan 11H Slice 2
    (AC-11H-05). An assertion may be exchanged at ``/embed/session`` exactly once;
    a replay (same ``jti``) is rejected ``401 replayed``. Rows are retained ≥ the
    assertion TTL (``expires_at`` = the assertion ``exp``) and pruned
    opportunistically once past expiry.
    """

    __tablename__ = "embed_jti"

    jti = Column(String, primary_key=True)
    expires_at = Column(UTCDateTime(), nullable=False)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
