"""impersonation sessions

Adds the impersonation_sessions table (plan 03 §13). One active session per admin
(partial-unique on ended_at IS NULL).

Revision ID: c2d3e4f5a6b7
Revises: b1f2c3d4e5a6
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5a6b7"
down_revision = "b1f2c3d4e5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "impersonation_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("admin_user_id", sa.String(), nullable=False),
        sa.Column("target_user_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("started_ip", sa.String(length=100), nullable=True),
        sa.Column("started_user_agent", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_impersonation_sessions_admin_user_id", "impersonation_sessions", ["admin_user_id"]
    )
    op.create_index(
        "ix_impersonation_sessions_target_user_id", "impersonation_sessions", ["target_user_id"]
    )
    op.create_index(
        "uq_impersonation_active_admin",
        "impersonation_sessions",
        ["admin_user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_impersonation_active_admin", table_name="impersonation_sessions")
    op.drop_index("ix_impersonation_sessions_target_user_id", table_name="impersonation_sessions")
    op.drop_index("ix_impersonation_sessions_admin_user_id", table_name="impersonation_sessions")
    op.drop_table("impersonation_sessions")
