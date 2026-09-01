"""Integration webhook/event log (sprint-4/07 Cluster F slice 3) - core
``public`` table. ONE row per inbound webhook delivery, the idempotency ledger
AND the masked audit trail (AC-07-28/30).

``UNIQUE(tenant_id, provider, external_event_id)`` is the idempotency guard: a
second delivery of the same provider event collides → the ingest treats it as a
no-op. Request/response bodies are stored MASKED (no raw secrets/PAN) via
``app.integrations.masking.mask_payload``.
"""
import uuid

from sqlalchemy import Column, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime

# Ingest outcomes - code branches on these.
LOG_STATUS_RECEIVED = "RECEIVED"
LOG_STATUS_PROCESSED = "PROCESSED"
LOG_STATUS_REJECTED = "REJECTED"  # bad signature / stale / malformed
LOG_STATUS_DUPLICATE = "DUPLICATE"  # idempotency collision (no-op)
LOG_STATUS_RETRY = "RETRY"  # out-of-order - referenced record not yet present


class IntegrationLog(Base):
    __tablename__ = "integration_logs"
    __table_args__ = (
        # Idempotency ledger (AC-07-30): a provider event lands at most once per
        # tenant. ``external_event_id`` is NULLABLE - a rejected/unparseable
        # delivery may have none; the partial uniqueness only bites real events.
        UniqueConstraint(
            "tenant_id", "provider", "external_event_id",
            name="uq_integration_log_event",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id = Column(String, nullable=True, index=True)
    provider = Column(String, nullable=False, index=True)  # stripe | billplz | …
    # Provider's event id (Stripe evt_…, Billplz event id). NULL when the body
    # carried none (a rejected delivery).
    external_event_id = Column(String, nullable=True)
    event_type = Column(String, nullable=True)  # charge.succeeded, paid, …
    status = Column(String, nullable=False, default=LOG_STATUS_RECEIVED)
    # MASKED request + response (AC-07-28) - never raw secrets/PAN.
    request_json = Column(JSON, nullable=True)
    response_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
