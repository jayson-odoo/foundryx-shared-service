"""Omnichannel module models — all live in the ``app_omnichannel`` schema.

Every tenant-scoped table carries ``tenant_id`` (FK core ``tenants``) and, where
workspace-scoped, ``workspace_id``. Datetimes are tz-aware UTC (CLAUDE.md rule).
Contacts/messages/identities/templates/quick_replies tables are created here
(schema is owned by plan 04) but only operated on from plan 05.
"""
import uuid

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
    # 0002, WHERE phone_number_id IS NOT NULL AND is_trashed=false) — inbound
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
    status_id = Column(String, ForeignKey("statuses.id"), nullable=True)
    priority = Column(String, nullable=False, default="MEDIUM")
    csw_expires_at = Column(UTCDateTime(), nullable=True)
    last_incoming_message_at = Column(UTCDateTime(), nullable=True)
    last_message_at = Column(UTCDateTime(), nullable=True)
    # When an agent last opened the thread — unreadCount = inbound newer than
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


class ConversationMessage(OmniBase):
    __tablename__ = "conversation_messages"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String,nullable=False, index=True)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    # Nullable: SYSTEM internal notes belong to the thread, not a channel.
    channel_id = Column(String, ForeignKey("channels.id"), nullable=True, index=True)
    sender_type = Column(String, nullable=False)  # AGENT | CONTACT | SYSTEM
    sender_id = Column(String, nullable=True)
    message_type = Column(String, nullable=False, default="TEXT")
    body = Column(Text, nullable=True)
    media_url = Column(String, nullable=True)
    external_message_id = Column(String, nullable=True, index=True)
    delivery_status = Column(String, nullable=True)  # SENT | DELIVERED | READ | FAILED
    error_code = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("external_message_id", name="uq_message_external_id"),
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

    The plaintext key (``fxw_live_…``) is shown ONCE at mint and never stored —
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
    secret (reversible — we HMAC-sign every delivery with it AND reveal it to the
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
