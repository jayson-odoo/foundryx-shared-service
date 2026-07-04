"""rbac permissions

Adds RBAC (plan 03): roles.description + roles.is_system, user_roles.assigned_at,
the global `permissions` catalog table, and the `role_permissions` grant M2M.

Revision ID: b1f2c3d4e5a6
Revises: 79c3adb77ab0
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "b1f2c3d4e5a6"
down_revision = "79c3adb77ab0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # roles: description + is_system
    op.add_column("roles", sa.Column("description", sa.String(), nullable=True))
    op.add_column(
        "roles",
        sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )

    # user_roles: assigned_at (when the membership was granted)
    op.add_column(
        "user_roles",
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # permissions: global catalog (no tenant scope)
    op.create_table(
        "permissions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("module", sa.String(), nullable=False),
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("resource_label", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("action_label", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_permissions_key", "permissions", ["key"], unique=True)
    op.create_index("ix_permissions_module", "permissions", ["module"])

    # role_permissions: tenant-scoped grants (cascade on role/permission delete)
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.String(), nullable=False),
        sa.Column("permission_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )


def downgrade() -> None:
    op.drop_table("role_permissions")
    op.drop_index("ix_permissions_module", table_name="permissions")
    op.drop_index("ix_permissions_key", table_name="permissions")
    op.drop_table("permissions")
    op.drop_column("user_roles", "assigned_at")
    op.drop_column("roles", "is_system")
    op.drop_column("roles", "description")
