"""Deferred actions - the grace-window engine (sprint-4/23, T5, D2).

The product has no confirmation dialogs for destructive/reversible record
actions. An action is PARKED here for the length of its grace window (10s
destructive / 5s reversible by default, tenant-configurable); the frontend
button becomes a countdown with Cancel, and the server applies the action
(via its registered handler, see ``app/deferred_actions/registry.py``) when
the window lapses - even if the tab is closed (a beat sweep + the frontend's
lazy `GET current` both apply an overdue row).

ONE pending action per (tenant, entity_type, entity_id) at a time - enforced
by a PARTIAL unique index scoped to ``status = 'pending'`` (a settled row
never blocks a new one on the same record).
"""
import uuid

from sqlalchemy import CheckConstraint, Column, Index, Integer, String, Text
from sqlalchemy.sql import func
from sqlalchemy.types import JSON as GenericJSON

from app.database import Base
from app.models.utc_datetime import UTCDateTime

# none_as_null so a cleared/absent payload stores SQL NULL, not JSON 'null'
# (house gotcha, sprint-2/02 D1 - JSON `null` would pass `IS NOT NULL`).
_JSON = GenericJSON(none_as_null=True)

PENDING_ACTION_PENDING = "pending"
PENDING_ACTION_COMMITTED = "committed"
PENDING_ACTION_CANCELLED = "cancelled"
PENDING_ACTION_FAILED = "failed"

PENDING_ACTION_STATUSES = (
    PENDING_ACTION_PENDING,
    PENDING_ACTION_COMMITTED,
    PENDING_ACTION_CANCELLED,
    PENDING_ACTION_FAILED,
)


def _uuid() -> str:
    return str(uuid.uuid4())


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    action_key = Column(String, nullable=False)  # `<entity>.<verb>` registry key
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    payload_json = Column(_JSON, nullable=True)
    status = Column(String, nullable=False, default=PENDING_ACTION_PENDING, index=True)
    commit_at = Column(UTCDateTime(), nullable=False)
    window_seconds = Column(Integer, nullable=False)
    requested_by_id = Column(String, nullable=True)
    error_text = Column(Text, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    ended_at = Column(UTCDateTime(), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','committed','cancelled','failed')",
            name="ck_pending_actions_status",
        ),
        # One PENDING action per record - a settled row (committed/cancelled/
        # failed) never blocks a fresh park on the same entity.
        Index(
            "uq_pending_actions_one_per_record",
            "tenant_id",
            "entity_type",
            "entity_id",
            unique=True,
            postgresql_where=(status == PENDING_ACTION_PENDING),
            sqlite_where=(status == PENDING_ACTION_PENDING),
        ),
    )
