"""Terminology overrides (sprint-3/08, F10) - per-tenant entity relabeling.

One row per (tenant, entity_key); absence = code default. Reset = delete row.

Revision ID: c3d4e5f6a7b8
Revises: f6a7b8c9d0e1
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

from app.models.utc_datetime import UTCDateTime  # house autogen gotcha

revision = "c3d4e5f6a7b8"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "terminology_overrides",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("entity_key", sa.String(), nullable=False),
        sa.Column("singular", sa.String(), nullable=False),
        sa.Column("plural", sa.String(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "entity_key", name="uq_terminology_tenant_entity"
        ),
    )
    op.create_index(
        "ix_terminology_overrides_tenant_id",
        "terminology_overrides",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_terminology_overrides_tenant_id", table_name="terminology_overrides"
    )
    op.drop_table("terminology_overrides")
