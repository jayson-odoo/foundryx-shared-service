"""Team + TeamMember models (plan 28, roadmap A8, D-A8-1).

A core `public.teams` grouping of tenant users, platform-wide, next to roles -
any future Service (omnichannel first) assigns work to a team instead of only
a single user. Tenant-scoped like every core entity; name is unique per tenant
case-insensitively (a Postgres functional index in the migration + a service-
level check so the sqlite test path behaves identically).

`TeamMember.tenant_id` is ALWAYS set from the owning Team at insert time (the
service layer does this explicitly, never trusting the payload) - the same
house rule as `user_roles.tenant_id` deriving from the owning role (BL-015).
"""
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.tenant import DEFAULT_TENANT_ID
from app.models.utc_datetime import UTCDateTime

TEAM_MEMBER_ROLES = ("member", "lead")


class Team(Base):
    __tablename__ = "teams"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String,
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        default=DEFAULT_TENANT_ID,
    )
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Replace-set membership (create/update `members`) - delete-orphan so
    # reassigning `team.members = [...]` clears removed rows in one flush.
    members = relationship(
        "TeamMember",
        cascade="all, delete-orphan",
        order_by="TeamMember.created_at",
        lazy="selectin",
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
        CheckConstraint("role IN ('member','lead')", name="ck_team_members_role"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id = Column(
        String, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Derived from the owning Team at insert (never from client payload) -
    # carried for tenant-scoped queries without a join (BL-015 pattern).
    tenant_id = Column(
        String,
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        default=DEFAULT_TENANT_ID,
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False, default="member")

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    # Read-side convenience (name/email for TeamMemberRef) - joined so listing
    # a team's members costs no N+1.
    user = relationship("User", lazy="joined")
