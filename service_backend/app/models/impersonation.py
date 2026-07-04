"""Impersonation session model (plan 03 §13).

An authorized user (holds `users.impersonate`) browses the system with a target
user's *effective permissions* to verify access. The effective user is signaled
per-request via the ``X-Impersonate-User-Id`` header, honored only while an active
row exists for that (admin, target) pair. Audit / actor always stays the real
admin — see ``app.dependencies.get_actor_user_id``.
"""
import uuid

from sqlalchemy import Column, ForeignKey, Index, String
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base
from app.models.tenant import DEFAULT_TENANT_ID


class ImpersonationSession(Base):
    __tablename__ = "impersonation_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    admin_user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, default=DEFAULT_TENANT_ID)
    started_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    ended_at = Column(UTCDateTime(), nullable=True)
    started_ip = Column(String(100), nullable=True)
    started_user_agent = Column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_impersonation_sessions_admin_user_id", "admin_user_id"),
        Index("ix_impersonation_sessions_target_user_id", "target_user_id"),
        # At most one active session per admin (Postgres partial unique; the
        # service also defensively ends any prior session before inserting).
        Index(
            "uq_impersonation_active_admin",
            "admin_user_id",
            unique=True,
            postgresql_where="ended_at IS NULL",
        ),
    )
