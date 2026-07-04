"""Permission catalog model + the role_permissions association (RBAC, plan 03).

A permission is a flat key ``"<resource>.<action>"`` (e.g. ``users.create``,
``orders.approve``). The catalog is **global** (not tenant-scoped) — it's what the
platform core + installed App-Store modules declare via their permissions CSV.
**Grants** (``role_permissions``) are tenant-scoped through the owning role.

Modules own their catalog rows via ``module``; uninstall = delete the rows
``WHERE module = X`` (+ cascade their grants), leaving core clean.
"""
import uuid

from sqlalchemy import Column, ForeignKey, String, Table, text
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base
from app.models.tenant import DEFAULT_TENANT_ID


def tenant_id_from_role(context) -> str:
    """Context-sensitive default for association ``tenant_id`` (BL-015 fix).

    Association rows are written by relationship appends, which only populate
    the FK columns — so the column default must derive the tenant from the
    owning role at insert time instead of stamping a static value.
    """
    role_id = context.get_current_parameters().get("role_id")
    if role_id:
        tenant_id = context.connection.execute(
            text("SELECT tenant_id FROM roles WHERE id = :rid"), {"rid": role_id}
        ).scalar()
        if tenant_id:
            return tenant_id
    return DEFAULT_TENANT_ID


# Grants: which role holds which permission. tenant_id carried for scoping;
# both FKs cascade so deleting a role (or a permission) clears its grants.
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        String,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("tenant_id", String, nullable=False, default=tenant_id_from_role),
)


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Globally-unique flat key — `<resource>.<action>`.
    key = Column(String, nullable=False, unique=True, index=True)
    # Owning module — `core` or an App-Store module name (groups + uninstall scope).
    module = Column(String, nullable=False, index=True)
    resource = Column(String, nullable=False)
    resource_label = Column(String, nullable=False)
    action = Column(String, nullable=False)
    action_label = Column(String, nullable=False)
    description = Column(String, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
