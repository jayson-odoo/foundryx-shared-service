"""workflow_settings (per-tenant run retention) — plan sprint-2/10

Revision ID: 1c2d3e4f5a6b
Revises: 0b0a96337c3d
Create Date: 2026-06-09

"""
from alembic import op
import sqlalchemy as sa

revision = "1c2d3e4f5a6b"
down_revision = "0b0a96337c3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_settings",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("run_retention_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("workflow_settings")
