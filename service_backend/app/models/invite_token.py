"""Invite tokens for the create-user invitation flow.

On create, a user is INVITED + a token is issued; the dev mailer logs the
set-password link. The user redeems the token to set a password → ACTIVE.
"""
import uuid

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base
from app.models.tenant import DEFAULT_TENANT_ID


class InviteToken(Base):
    __tablename__ = "invite_tokens"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    token = Column(String, nullable=False, unique=True, index=True)
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id = Column(String, nullable=False, default=DEFAULT_TENANT_ID)
    expires_at = Column(UTCDateTime(), nullable=False)
    used_at = Column(UTCDateTime(), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
