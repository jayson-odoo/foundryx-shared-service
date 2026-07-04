"""Integration connections (plan 09 §3) — the core registry every external
service integration plugs into.

One row per (tenant, provider). The PLATFORM tenant's row is the deployment
default (e.g. the SMTP connection auth emails fall back to). Non-secret config
lives in ``config_json`` (displayable); secrets in ``credentials_json``,
Fernet-encrypted via ``app/secrets.py`` and write-only over the API.
"""
import uuid

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base

# Connection health — code branches only on these.
CONNECTION_STATUS_ACTIVE = "ACTIVE"
CONNECTION_STATUS_UNVERIFIED = "UNVERIFIED"
CONNECTION_STATUS_ERROR = "ERROR"


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_connection_tenant_provider"),
        # ONE connection per TYPE per tenant (plan 06 D7) — StorageService /
        # EmailService resolution must be deterministic. RELAXED for
        # ``type='payment'`` (sprint-4/07 Cluster F AC-07-24): a tenant may hold
        # MULTIPLE payment connections (Stripe + Billplz), so checkout can resolve
        # per-project; same-provider duplicates stay blocked by the
        # (tenant, provider) unique above. A PARTIAL unique index enforces
        # one-per-type for every NON-payment type.
        Index(
            "uq_connection_tenant_type",
            "tenant_id",
            "type",
            unique=True,
            postgresql_where=Column("type") != "payment",
            sqlite_where=Column("type") != "payment",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Provider identity, e.g. "smtp" (registry key, app/integrations).
    provider = Column(String, nullable=False, index=True)
    # Category: email | storage | llm | erp — grouping, not behavior.
    type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    # Non-secret config (host, port, from_email, …) — displayable/queryable.
    config_json = Column(JSON, nullable=False, default=dict)
    # Fernet-encrypted secrets dict — write-only over the API.
    credentials_json = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default=CONNECTION_STATUS_UNVERIFIED)
    last_tested_at = Column(UTCDateTime(), nullable=True)
    last_error = Column(Text, nullable=True)
    # Outbox dispatcher throttle (plan 09 §5 — low-spec SMTP guard).
    rate_limit_per_minute = Column(Integer, nullable=False, default=30)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
