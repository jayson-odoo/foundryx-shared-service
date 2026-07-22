"""Integration connections (plan 09 §3) — the core registry every external
service integration plugs into.

One row per (tenant, provider). The PLATFORM tenant's row is the deployment
default (e.g. the SMTP connection auth emails fall back to). Non-secret config
lives in ``config_json`` (displayable); secrets in ``credentials_json``,
Fernet-encrypted via ``app/secrets.py`` and write-only over the API.
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    and_,
)
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base

# Connection types exempt from the ONE-active-per-type rule. ``payment``
# (sprint-4/07 AC-07-24 — Stripe + Billplz resolve per-project) and ``llm``
# (Phase B-i Bi-D21 / AC-BI-03b — agents resolve by connection_id, so several
# providers coexist). Everything else — notably ``storage`` and ``email``, whose
# resolution MUST stay deterministic — is still one active row per tenant.
# Keep this list and the migration's index predicate in step.
EXEMPT_FROM_ONE_PER_TYPE = ("payment", "llm")

# Connection health — code branches only on these.
CONNECTION_STATUS_ACTIVE = "ACTIVE"
CONNECTION_STATUS_UNVERIFIED = "UNVERIFIED"
CONNECTION_STATUS_ERROR = "ERROR"


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (
        # ONE ACTIVE connection per (tenant, provider). RELAXED to a partial
        # unique index on ``is_active`` (sprint-4/10 D10): a SAME-PROVIDER bucket
        # migration (s3→s3) needs the retired A (is_active=false) and its active
        # successor B to coexist — a plain unique on (tenant, provider) would
        # block creating B. Two ACTIVE same-provider connections stay blocked
        # (the payment invariant: two active Stripe rows forbidden; Stripe +
        # Billplz still fine — different providers).
        Index(
            "uq_connection_tenant_provider",
            "tenant_id",
            "provider",
            unique=True,
            postgresql_where=Column("is_active"),
            sqlite_where=Column("is_active"),
        ),
        # ONE connection per TYPE per tenant (plan 06 D7) — StorageService /
        # EmailService resolution must be deterministic. RELAXED for
        # ``type='payment'`` (sprint-4/07 Cluster F AC-07-24): a tenant may hold
        # MULTIPLE payment connections (Stripe + Billplz), so checkout can resolve
        # per-project.
        # RELAXED again (sprint-4/10 D10): the predicate also requires
        # ``is_active`` so a RETIRED storage connection (A, ``is_active=false``)
        # and its ACTIVE successor (B) coexist during a bucket migration
        # WITHOUT violating one-per-type. Only the single active row is the
        # write-target; ``resolve_for_type`` filters on ``is_active`` to pick it.
        # RELAXED for ``type='llm'`` (Phase B-i, Bi-D21 / AC-BI-03b): a tenant
        # may hold SEVERAL active LLM connections (Anthropic + Gemini + OpenAI)
        # so different agents can use different providers — a cheap model for
        # clustering, a strong one for grilling. An agent therefore resolves by
        # its own ``connection_id``, never by type; type-resolution survives
        # only as the "is any LLM configured?" prerequisite probe (AC-BI-11).
        # Storage and email keep their one-active-per-type invariant untouched.
        Index(
            "uq_connection_tenant_type",
            "tenant_id",
            "type",
            unique=True,
            postgresql_where=and_(
                Column("type").notin_(EXEMPT_FROM_ONE_PER_TYPE), Column("is_active")
            ),
            sqlite_where=and_(
                Column("type").notin_(EXEMPT_FROM_ONE_PER_TYPE), Column("is_active")
            ),
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
    # Write-target flag (sprint-4/10 D10). Only an ``is_active`` connection is
    # the type-level write/resolve target; a retired ``A`` stays readable by
    # KEY (``get_by_id`` ignores this flag) so its historical blobs keep serving.
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    last_tested_at = Column(UTCDateTime(), nullable=True)
    last_error = Column(Text, nullable=True)
    # Outbox dispatcher throttle (plan 09 §5 — low-spec SMTP guard).
    rate_limit_per_minute = Column(Integer, nullable=False, default=30)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
