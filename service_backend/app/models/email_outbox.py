"""Email outbox (plan 09 §3, §5) — durable queue + sent-mail audit.

Every product email is a row here; the dispatcher drains it with
per-connection rate limiting, retry/backoff and tenant→platform fallback.
NEVER send product mail directly — enqueue (wizard test-send excepted).
"""
import uuid

from sqlalchemy import Boolean, Column, Integer, String, Text
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base

# Outbox row lifecycle — code branches only on these.
OUTBOX_PENDING = "pending"
OUTBOX_SENDING = "sending"
OUTBOX_SENT = "sent"
OUTBOX_FAILED = "failed"
# Operator-cancelled while PENDING (plan 07 D14); retryable like FAILED.
OUTBOX_CANCELLED = "cancelled"

# Retry backoff schedule (seconds) per attempt — then fallback / failed.
RETRY_BACKOFF_SECONDS = (60, 300, 1500)
MAX_ATTEMPTS = 3


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Recipient's tenant — drives connection resolution (tenant → platform).
    tenant_id = Column(String, nullable=False, index=True)
    # Resolved at dispatch time; NULL until the first attempt.
    connection_id = Column(String, nullable=True)
    to_email = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    html_body = Column(Text, nullable=False)
    text_body = Column(Text, nullable=False)
    # invite | password_reset | verification | test — audit/filtering.
    template_key = Column(String, nullable=False)
    status = Column(String, nullable=False, default=OUTBOX_PENDING, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(UTCDateTime(), nullable=False, index=True)
    last_error = Column(Text, nullable=True)
    # True once the platform connection took over from a failing tenant one.
    used_fallback = Column(Boolean, nullable=False, default=False)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    sent_at = Column(UTCDateTime(), nullable=True)
