"""Status transition graph (sprint-2/01 §data-model).

An edge is the ONLY way a record moves between statuses (strict graph, D4):
no wildcards, no self-loops, no admin override. ``label`` is the action button
text ("Approve" / "Reject" / "Resubmit"); ``sort_order`` orders the buttons.

Authorization: ``transition_roles`` M2M — the actor must hold ≥1 of the edge's
roles to fire it; an edge with NO roles is unrestricted (the endpoint's own
permission gate still applies). ``statuses.manage`` gates who *configures*;
edge roles gate who can *fire* (D5).
"""
import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base


def tenant_id_from_transition(context) -> str | None:
    """Derive the association ``tenant_id`` from the owning transition at insert
    (same BL-015 pattern as ``tenant_id_from_role`` — relationship appends only
    populate the FK columns)."""
    transition_id = context.get_current_parameters().get("transition_id")
    if transition_id:
        return context.connection.execute(
            text("SELECT tenant_id FROM status_transitions WHERE id = :tid"),
            {"tid": transition_id},
        ).scalar()
    return None


# Who may FIRE an edge (≥1 of these roles). Empty = unrestricted.
transition_roles = Table(
    "transition_roles",
    Base.metadata,
    Column(
        "transition_id",
        String,
        ForeignKey("status_transitions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("role_id", String, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    # NULL = platform-default edge (roles are tenant-scoped, so platform
    # defaults normally carry no role rows at all).
    Column("tenant_id", String, nullable=True, default=tenant_id_from_transition),
)


class StatusTransition(Base):
    __tablename__ = "status_transitions"
    __table_args__ = (
        CheckConstraint("from_status_id != to_status_id", name="ck_transition_no_self_loop"),
        UniqueConstraint(
            "tenant_id", "from_status_id", "to_status_id", name="uq_transition_edge"
        ),
        # Derived status (sprint-4/03) — the re-eval loop looks up outgoing AUTO
        # edges from a record's current status; index the pair it filters on.
        Index("ix_transition_from_trigger", "from_status_id", "trigger_mode"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_type = Column(String, nullable=False, index=True)
    # NULL = platform default set (two-tier, same resolution as statuses).
    tenant_id = Column(String, nullable=True, index=True)
    from_status_id = Column(String, ForeignKey("statuses.id"), nullable=False, index=True)
    to_status_id = Column(String, ForeignKey("statuses.id"), nullable=False, index=True)
    # Action button text shown to the user ("Approve", "Reject", …).
    label = Column(String, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    # Derived status (sprint-4/03 G1): 'manual' = a user fires it (action
    # button); 'auto' = the engine fires it when conditions_json becomes true
    # (reevaluate). An AUTO edge MUST carry conditions and MUST NOT carry roles
    # (system-fired) — both enforced at save. Auto edges are excluded from the
    # user-facing transition surfaces (available_transitions / fireable_edge_ids).
    trigger_mode = Column(
        String, nullable=False, default="manual", server_default="manual"
    )
    # Rule-engine condition tree (sprint-2/02 D1 — rule = property, not
    # entity): camelCase wire JSON stored as-is. NULL = unconditional edge.
    # none_as_null: Python None must store SQL NULL, not JSON null — the
    # rule-site lister and the fireable-ids trigger filter on IS NOT NULL
    # (a cleared edge once ghosted on the Rules page as "Always allowed").
    conditions_json = Column(JSON(none_as_null=True), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    from_status = relationship("Status", foreign_keys=[from_status_id], lazy="joined")
    to_status = relationship("Status", foreign_keys=[to_status_id], lazy="joined")
    # selectin: the graph read + the executor's role check load grants in one
    # extra query, never N+1.
    roles = relationship("Role", secondary=transition_roles, lazy="selectin")
    notification_specs = relationship(
        "NotificationSpec",
        secondary="notification_spec_transitions",
        lazy="selectin",
    )
