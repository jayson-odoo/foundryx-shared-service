"""Dashboards models - all in ``app_dashboards``. ``tenant_id`` is a plain indexed
column (no cross-schema FK); every row also carries ``product`` (the product the
key was issued for). Ids are UUID strings."""

from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.types import JSON

from app.models.utc_datetime import UTCDateTime

from .db import DashboardsBase

_JSON = JSON(none_as_null=True)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DashApiKey(DashboardsBase):
    """Gateway key: ``fxd_live_`` + secret, shown once; only a sha256 hash and an
    8-character lookup prefix are stored. Bound to ONE tenant and ONE product."""

    __tablename__ = "dash_api_key"
    __table_args__ = (
        Index("ix_dash_api_key_tenant", "tenant_id"),
        Index("ix_dash_api_key_prefix", "key_prefix"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    product = Column(String(64), nullable=False)
    name = Column(String(200), nullable=False, default="")
    key_prefix = Column(String(16), nullable=False)
    key_hash = Column(String(64), nullable=False)
    key_last4 = Column(String(4), nullable=False, default="")
    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)
    last_used_at = Column(UTCDateTime(), nullable=True)
    revoked_at = Column(UTCDateTime(), nullable=True)


class DashApiAudit(DashboardsBase):
    """One row per gateway call whose key resolved: tenant, product, key, route, status. No payload."""

    __tablename__ = "dash_api_audit"
    __table_args__ = (Index("ix_dash_api_audit_tenant_created", "tenant_id", "created_at"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    product = Column(String(64), nullable=False)
    key_id = Column(String, nullable=False)
    method = Column(String(8), nullable=False)
    route = Column(String(200), nullable=False)
    status_code = Column(Integer, nullable=False)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)


class DashDashboard(DashboardsBase):
    __tablename__ = "dash_dashboard"
    __table_args__ = (
        Index("ix_dash_dashboard_scope", "tenant_id", "product", "owner_ref"),
        Index("ix_dash_dashboard_updated", "tenant_id", "product", "updated_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    product = Column(String(64), nullable=False)
    owner_ref = Column(String(64), nullable=False)
    name = Column(String(80), nullable=False)
    spec_json = Column(_JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)
    updated_at = Column(UTCDateTime(), default=_now, nullable=False)


class DashShare(DashboardsBase):
    """One recipient of a dashboard. "Shared with me" is a query on user_ref."""

    __tablename__ = "dash_share"
    __table_args__ = (
        UniqueConstraint("dashboard_id", "user_ref", name="uq_dash_share_user"),
        Index("ix_dash_share_lookup", "tenant_id", "product", "user_ref"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    dashboard_id = Column(String, ForeignKey("dash_dashboard.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String, nullable=False)
    product = Column(String(64), nullable=False)
    user_ref = Column(String(64), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)


class DashVersion(DashboardsBase):
    __tablename__ = "dash_version"
    __table_args__ = (
        UniqueConstraint("dashboard_id", "version", name="uq_dash_version_number"),
        Index("ix_dash_version_tenant", "tenant_id", "product"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    dashboard_id = Column(String, ForeignKey("dash_dashboard.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String, nullable=False)
    product = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False)
    action = Column(String(16), nullable=False)
    actor_ref = Column(String(64), nullable=False)
    changes_json = Column(_JSON, nullable=True)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)


class DashIdempotency(DashboardsBase):
    """A save's first response, replayed for the same key + actor + idempotency key within 24 h."""

    __tablename__ = "dash_idempotency"
    __table_args__ = (
        UniqueConstraint("key_id", "actor_ref", "idem_ref", name="uq_dash_idempotency"),
        Index("ix_dash_idempotency_tenant", "tenant_id", "product"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    product = Column(String(64), nullable=False)
    key_id = Column(String, nullable=False)
    actor_ref = Column(String(64), nullable=False)
    idem_ref = Column(String(128), nullable=False)
    response_json = Column(_JSON, nullable=False)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)


class DashUsage(DashboardsBase):
    """One row per builder turn (tokens summed over the turn's LLM calls). Kept: not pruned by AI retention."""

    __tablename__ = "dash_usage"
    __table_args__ = (Index("ix_dash_usage_tenant_created", "tenant_id", "product", "created_at"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    product = Column(String(64), nullable=False)
    feature = Column(String(32), nullable=False, default="dashboard_builder")
    dashboard_id = Column(String, nullable=True)
    actor_ref = Column(String(64), nullable=False)
    provider = Column(String(64), nullable=True)
    model = Column(String(128), nullable=False, default="")
    tokens_in = Column(Integer, nullable=False, default=0)
    tokens_out = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Numeric(14, 6), nullable=True)  # NULL when the model has no price row
    latency_ms = Column(Integer, nullable=False, default=0)
    llm_calls = Column(Integer, nullable=False, default=0)
    trace_id = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), default=_now, nullable=False)


class DashModelPrice(DashboardsBase):
    """List price per million tokens for a model (global, not tenant data). Usage cost is computed from it."""

    __tablename__ = "dash_model_price"

    model = Column(String(128), primary_key=True)
    input_per_mtok = Column(Numeric(12, 4), nullable=False)
    output_per_mtok = Column(Numeric(12, 4), nullable=False)
    cache_read_per_mtok = Column(Numeric(12, 4), nullable=True)
    currency = Column(String(3), nullable=False, default="USD")
    source = Column(String(500), nullable=True)
    verified_at = Column(UTCDateTime(), nullable=True)  # NULL = unverified
    updated_at = Column(UTCDateTime(), default=_now, nullable=False)
