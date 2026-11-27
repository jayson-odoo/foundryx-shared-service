"""Planner 3D models - all in ``app_planner3d``. ``tenant_id`` is a plain
indexed column (no cross-schema FK). Files hold a storage KEY, never a URL."""

from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.types import JSON

from app.models.utc_datetime import UTCDateTime

from .db import Planner3dBase

_JSON = JSON(none_as_null=True)

KIND_MODEL = "model"
KIND_RENDER = "render"
KIND_CONVERT = "convert"
KINDS = (KIND_MODEL, KIND_RENDER, KIND_CONVERT)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUSES = (STATUS_QUEUED, STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED)

DIRECTION_IN = "in"
DIRECTION_OUT = "out"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class P3Job(Planner3dBase):
    __tablename__ = "p3_job"
    __table_args__ = (
        Index("ix_p3_job_tenant_created", "tenant_id", "created_at"),
        Index("ix_p3_job_queue", "status", "kind", "created_at"),
        # One live Idempotency-Key per tenant (S1, contract 3.7). The column is
        # cleared when its 24 hour window has passed, so the key can be reused.
        Index("uq_p3_job_idempotency", "tenant_id", "idempotency_ref", unique=True),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    kind = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default=STATUS_QUEUED)
    engine = Column(String(32), nullable=True)
    params_json = Column(_JSON, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    progress = Column(Integer, nullable=False, default=0)
    gpu_seconds = Column(Float, nullable=True)
    peak_rss_mb = Column(Integer, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    worker_name = Column(String(100), nullable=True)
    claimed_at = Column(UTCDateTime(), nullable=True)
    heartbeat_at = Column(UTCDateTime(), nullable=True)
    approved_candidate = Column(String(64), nullable=True)
    source_job_id = Column(String, nullable=True)
    created_by_user_id = Column(String, nullable=True)
    # S1 gateway: the key that submitted the job, the consumer's Idempotency-Key and
    # the sha256 of the submitted body (contract 3.7). NULL for staff jobs.
    api_key_id = Column(String, nullable=True)
    idempotency_ref = Column(String(128), nullable=True)
    request_hash = Column(String(64), nullable=True)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)
    started_at = Column(UTCDateTime(), nullable=True)
    finished_at = Column(UTCDateTime(), nullable=True)


class P3JobFile(Planner3dBase):
    __tablename__ = "p3_job_file"
    __table_args__ = (
        UniqueConstraint("job_id", "direction", "name", name="uq_p3_job_file_name"),
        Index("ix_p3_job_file_job", "tenant_id", "job_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    job_id = Column(String, ForeignKey("p3_job.id"), nullable=False)
    direction = Column(String(3), nullable=False)
    role = Column(String(32), nullable=False)
    name = Column(String(100), nullable=False)
    mime = Column(String(100), nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_key = Column(String(500), nullable=False)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)


# ── S1 gateway (lane PLANNER-3D-S1) ─────────────────────────────────────────

DELIVERY_PENDING = "PENDING"
DELIVERY_SUCCESS = "SUCCESS"
DELIVERY_FAILED = "FAILED"


class P3ApiKey(Planner3dBase):
    """Tenant gateway key (contract 2.1): ``fx3_live_`` + secret, shown once; only a
    sha256 hash and an 8-character lookup prefix are stored. Repeats the lead-capture
    key table (cross-module reads are not allowed, BL-SS-210)."""

    __tablename__ = "p3_api_key"
    __table_args__ = (
        Index("ix_p3_api_key_tenant", "tenant_id"),
        Index("ix_p3_api_key_prefix", "key_prefix"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    name = Column(String(200), nullable=False, default="")
    key_prefix = Column(String(16), nullable=False)
    key_hash = Column(String(64), nullable=False)
    key_last4 = Column(String(4), nullable=False, default="")
    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)
    last_used_at = Column(UTCDateTime(), nullable=True)
    revoked_at = Column(UTCDateTime(), nullable=True)


class P3ApiAudit(Planner3dBase):
    """One row per gateway call whose key resolved: tenant, key, route, status. No payload."""

    __tablename__ = "p3_api_audit"
    __table_args__ = (
        Index("ix_p3_api_audit_tenant", "tenant_id"),
        Index("ix_p3_api_audit_created_at", "created_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    key_id = Column(String, nullable=False)
    method = Column(String(8), nullable=False)
    route = Column(String(200), nullable=False)
    status_code = Column(Integer, nullable=False)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)


class P3Upload(Planner3dBase):
    """An input image sent with ``POST /uploads`` (contract 3.2). ``used_at`` is set when
    a job takes it; an unused upload is removed after ``expires_at``."""

    __tablename__ = "p3_upload"
    __table_args__ = (
        Index("ix_p3_upload_tenant", "tenant_id"),
        Index("ix_p3_upload_expiry", "used_at", "expires_at"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    api_key_id = Column(String, nullable=True)
    mime = Column(String(100), nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_key = Column(String(500), nullable=False)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)
    expires_at = Column(UTCDateTime(), nullable=False)
    used_at = Column(UTCDateTime(), nullable=True)


class P3Receiver(Planner3dBase):
    """A tenant's webhook receiver (contract 5.1). The signing secret is Fernet-encrypted."""

    __tablename__ = "p3_receiver"
    __table_args__ = (Index("ix_p3_receiver_tenant", "tenant_id"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    url = Column(String(2048), nullable=False)
    events_json = Column(_JSON, nullable=False, default=list)
    secret_encrypted = Column(Text, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    last_success_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)


class P3Delivery(Planner3dBase):
    """One event to one receiver (contract 5.2-5.4). ``body_encrypted`` holds the exact
    JSON body; a retry resends it with a new signature."""

    __tablename__ = "p3_delivery"
    __table_args__ = (
        Index("ix_p3_delivery_tenant", "tenant_id"),
        Index("ix_p3_delivery_due", "status", "next_at"),
        Index("ix_p3_delivery_job", "job_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    receiver_id = Column(String, ForeignKey("p3_receiver.id"), nullable=False)
    job_id = Column(String, nullable=True)
    event_id = Column(String(64), nullable=False)
    event = Column(String(40), nullable=False)
    body_encrypted = Column(Text, nullable=False)
    attempt = Column(Integer, nullable=False, default=0)
    next_at = Column(UTCDateTime(), nullable=True)
    status = Column(String(16), nullable=False, default=DELIVERY_PENDING)
    last_code = Column(Integer, nullable=True)
    last_error = Column(String(500), nullable=True)
    last_attempt_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)
