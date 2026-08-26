"""Change-email ceremony requests (plan sprint-2/04 - dual confirmation).

One row per attempt: the OLD mailbox approves (old_token), then the NEW
mailbox proves deliverability (new_token, generated only at approve time);
``users.email`` flips only on the new-side verify. A new request for the
same user cancels prior non-terminal rows.

Tokens are stored like the plan-10 invite/reset tokens: the 256-bit
``secrets.token_urlsafe(32)`` value IS the capability (unique-indexed
plaintext - see ``models/invite_token.py``).
"""
import uuid

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base

# Request lifecycle (EXPIRED is implicit - ``expires_at`` is checked at every
# read/redeem; terminal states are written explicitly).
CHANGE_PENDING_OLD = "PENDING_OLD"
CHANGE_PENDING_NEW = "PENDING_NEW"
CHANGE_COMPLETED = "COMPLETED"
CHANGE_CANCELLED = "CANCELLED"


class EmailChangeRequest(Base):
    __tablename__ = "email_change_requests"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Normalized lowercase at save time.
    new_email = Column(String, nullable=False)

    old_token = Column(String, nullable=False, unique=True, index=True)
    # Generated only when the old side approves (plan 04 data model).
    new_token = Column(String, nullable=True, unique=True, index=True)

    status = Column(String, nullable=False, default=CHANGE_PENDING_OLD)

    # The WHOLE request expires (both links share the window).
    expires_at = Column(UTCDateTime(), nullable=False)
    completed_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
