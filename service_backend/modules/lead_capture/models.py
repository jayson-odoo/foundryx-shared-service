"""Lead Capture models - all in ``app_lead_capture`` (plan 64 section 4).

Every table carries ``tenant_id`` as a plain indexed column (no cross-schema FK,
BL-030). Leads are personal data: the answers (``fields_encrypted``), the raw
platform payload (``raw_encrypted``) and every delivery body
(``body_encrypted``) are Fernet-encrypted with core ``app/secrets.py``
(AC-64-55); only ``email`` / ``phone_e164`` stay plain for duplicate checks and
search. Page tokens and endpoint secrets are Fernet too; gateway keys are
stored as a sha256 hash only.
"""

from __future__ import annotations
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
    text,
)
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from app.models.utc_datetime import UTCDateTime

from .db import LeadCaptureBase

_JSON = JSON(none_as_null=True)

SOURCE_DRAFT = "DRAFT"
SOURCE_WAITING_FOR_TEST = "WAITING_FOR_TEST"
SOURCE_LIVE = "LIVE"
SOURCE_NEEDS_RECONNECT = "NEEDS_RECONNECT"
SOURCE_DISCONNECTED = "DISCONNECTED"

PLATFORM_FACEBOOK = "facebook"

DELIVERY_PENDING = "PENDING"
DELIVERY_SUCCESS = "SUCCESS"
DELIVERY_FAILED = "FAILED"


def _uuid() -> str:
    return str(uuid.uuid4())


def _created() -> Column:
    return Column(UTCDateTime(), server_default=func.now(), nullable=False)


class LcSource(LeadCaptureBase):
    """One connected lead source (a Facebook Page for one tenant). D13: one LIVE
    source per (tenant, platform, Page); the cross-tenant rule is applied by the
    connect service under an advisory lock, not by an index."""

    __tablename__ = "lc_source"
    __table_args__ = (
        Index("ix_lc_source_tenant", "tenant_id"),
        Index("ix_lc_source_account", "platform", "account_ref"),
        Index(
            "uq_lc_source_live_account",
            "tenant_id",
            "platform",
            "account_ref",
            unique=True,
            postgresql_where=text("status = 'LIVE'"),
            sqlite_where=text("status = 'LIVE'"),
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    platform = Column(String(32), nullable=False)
    mode = Column(String(16), nullable=False, default="auto")
    name = Column(String(200), nullable=False, default="")
    status = Column(String(32), nullable=False, default=SOURCE_DRAFT)
    account_ref = Column(String(64), nullable=True)
    account_name = Column(String(200), nullable=True)
    config_json = Column(_JSON, nullable=True)
    field_map_json = Column(_JSON, nullable=True)
    # Forms whose leads arrived with no field map (AC-64-35 notice data):
    # {formId: {"formId", "formName", "unmappedCount"}}.
    needs_mapping_json = Column(_JSON, nullable=True)
    credentials_encrypted = Column(Text, nullable=True)  # Fernet {"pageToken": ...}
    source_key = Column(String(64), nullable=True, unique=True)
    cursor_at = Column(UTCDateTime(), nullable=True)
    created_by = Column(String, nullable=True)
    created_at = _created()
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_lead_at = Column(UTCDateTime(), nullable=True)


class LcSettings(LeadCaptureBase):
    __tablename__ = "lc_settings"

    tenant_id = Column(String, primary_key=True)
    allow_shared_pages = Column(Boolean, nullable=False, default=False)
    updated_by = Column(String, nullable=True)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LcLead(LeadCaptureBase):
    """One captured lead per (source, platform lead id) - AC-64-27/37."""

    __tablename__ = "lc_lead"
    __table_args__ = (
        UniqueConstraint("source_id", "platform_lead_id", name="uq_lc_lead_source_platform_id"),
        Index("ix_lc_lead_tenant_received", "tenant_id", "received_at", "id"),
        Index("ix_lc_lead_tenant_phone", "tenant_id", "phone_e164"),
        Index("ix_lc_lead_tenant_email", "tenant_id", "email"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    source_id = Column(String, ForeignKey("lc_source.id"), nullable=False)
    platform = Column(String(32), nullable=False)
    platform_lead_id = Column(String(64), nullable=False)
    form_id = Column(String(64), nullable=True)
    received_at = Column(UTCDateTime(), nullable=False)
    platform_created_at = Column(UTCDateTime(), nullable=True)
    fields_encrypted = Column(Text, nullable=True)  # Fernet {"fields": {...}, "answers": [...]}
    raw_encrypted = Column(Text, nullable=True)  # Fernet {"raw": <platform lead object>}
    attribution_json = Column(_JSON, nullable=True)  # ids only, no personal data
    phone_e164 = Column(String(32), nullable=True)
    email = Column(String(320), nullable=True)
    duplicate_of = Column(String, nullable=True)
    is_test = Column(Boolean, nullable=False, default=False)
    purged_at = Column(UTCDateTime(), nullable=True)


class LcWebhookEndpoint(LeadCaptureBase):
    __tablename__ = "lc_webhook_endpoint"
    __table_args__ = (Index("ix_lc_webhook_endpoint_tenant", "tenant_id"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    url = Column(String(2048), nullable=False)
    events_json = Column(_JSON, nullable=False, default=list)
    secret_encrypted = Column(Text, nullable=False)  # Fernet {"secret": ...}
    active = Column(Boolean, nullable=False, default=True)
    last_success_at = Column(UTCDateTime(), nullable=True)
    created_at = _created()


class LcDelivery(LeadCaptureBase):
    """One event to one endpoint. ``body_encrypted`` holds the exact JSON body
    (personal data, so Fernet); a redelivery resends it with a new signature."""

    __tablename__ = "lc_delivery"
    __table_args__ = (
        Index("ix_lc_delivery_tenant", "tenant_id"),
        Index("ix_lc_delivery_due", "status", "next_at"),
        Index("ix_lc_delivery_lead", "lead_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    endpoint_id = Column(String, ForeignKey("lc_webhook_endpoint.id"), nullable=False)
    lead_id = Column(String, nullable=True)
    event = Column(String(32), nullable=False)
    body_encrypted = Column(Text, nullable=False)
    attempt = Column(Integer, nullable=False, default=0)
    next_at = Column(UTCDateTime(), nullable=True)
    status = Column(String(16), nullable=False, default=DELIVERY_PENDING)
    last_code = Column(Integer, nullable=True)
    last_error = Column(String(500), nullable=True)
    last_attempt_at = Column(UTCDateTime(), nullable=True)
    created_at = _created()


class LcApiKey(LeadCaptureBase):
    """Gateway key (D8, AC-64-72): ``fxl_live_`` + secret, returned once; only a
    sha256 hash and an 8-char lookup prefix are stored. Mirrors the omnichannel
    and autocount keys (BL-SS-210 duplication, acknowledged)."""

    __tablename__ = "lc_api_key"
    __table_args__ = (
        Index("ix_lc_api_key_tenant", "tenant_id"),
        Index("ix_lc_api_key_prefix", "key_prefix"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    name = Column(String(200), nullable=False, default="")
    key_prefix = Column(String(16), nullable=False)
    key_hash = Column(String(64), nullable=False)
    key_last4 = Column(String(4), nullable=False, default="")
    created_by = Column(String, nullable=True)
    created_at = _created()
    last_used_at = Column(UTCDateTime(), nullable=True)
    revoked_at = Column(UTCDateTime(), nullable=True)


class LcApiAudit(LeadCaptureBase):
    """One row per gateway call: tenant, key, route, status. No payload."""

    __tablename__ = "lc_api_audit"
    __table_args__ = (
        Index("ix_lc_api_audit_tenant", "tenant_id"),
        Index("ix_lc_api_audit_created_at", "created_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    key_id = Column(String, nullable=False)
    method = Column(String(8), nullable=False)
    route = Column(String(200), nullable=False)
    status_code = Column(Integer, nullable=False)
    created_at = _created()
