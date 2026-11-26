"""Planner 3D models - all in ``app_planner3d``. ``tenant_id`` is a plain
indexed column (no cross-schema FK). Files hold a storage KEY, never a URL."""

from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
