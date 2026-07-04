"""Per-user, per-view column preferences (order / width / visibility).

Keyed by `view_key` (e.g. 'users.list'). Stored as JSON so the shape can evolve
without migrations. JSON maps to JSONB on Postgres and TEXT on SQLite (tests).
"""
import uuid

from sqlalchemy import Column, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base
from app.models.tenant import DEFAULT_TENANT_ID


class UserViewPreference(Base):
    __tablename__ = "user_view_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "view_key", name="uq_view_pref_user_key"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id = Column(String, nullable=False, default=DEFAULT_TENANT_ID)
    view_key = Column(String, nullable=False)
    prefs = Column(JSON, nullable=False, default=dict)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
