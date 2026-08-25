"""Role model + the user_roles association (many-to-many, both directions).

A role carries a set of permissions (RBAC, plan 03); users gain a permission by
holding a role that grants it. One user has many roles; one role has many users.
"""
import uuid

from sqlalchemy import Boolean, Column, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base
from app.models.permission import role_permissions, tenant_id_from_role
from app.models.tenant import DEFAULT_TENANT_ID

# Association table - tenant_id carried for tenant-scoped integrity; assigned_at
# records when the membership was granted (Assigned Users "Joined" column).
# tenant_id is derived from the OWNING ROLE at insert (BL-015) - relationship
# appends (`user.roles.append(...)`) only set the FK columns, so a static
# default would stamp the wrong tenant the moment a 2nd tenant exists.
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", String, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("tenant_id", String, nullable=False, default=tenant_id_from_role),
    Column("assigned_at", UTCDateTime(), server_default=func.now(), nullable=False),
)


class Role(Base):
    __tablename__ = "roles"
    # Role names are unique per tenant.
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)

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
    # Seeded/protected role - cannot be deleted while true (admin-toggleable).
    is_system = Column(Boolean, default=False, nullable=False)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Granted permissions (M2M). selectin so effective-keys resolution + the
    # detail form load the grants in one extra query, never N+1.
    permissions = relationship("Permission", secondary=role_permissions, lazy="selectin")
