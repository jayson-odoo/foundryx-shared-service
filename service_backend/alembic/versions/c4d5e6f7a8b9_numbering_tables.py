"""Numbering tables (sprint-4/07, Cluster F) — gapless document numbering.

Creates the two core tables backing the numbering engine:
- ``number_formats`` — per-tenant override of a doc type's prefix / format /
  reset cadence (absence = code-side ``NumberSequenceDef`` default).
- ``number_counters`` — the gapless running counter, one row per
  (tenant, doc_type, period_key).

Columns/constraints mirror ``app/models/numbering.py`` exactly (create_all parity).
The new core ``numbering.read/manage`` permissions reach the Admin role of
tenants provisioned before this slice via ``sweep_tenant_admin_grants`` in
``seed_all`` (run by bootstrap), NOT this migration (DoD #4).

Revision ID: c4d5e6f7a8b9
Revises: f7b8c9d0e1a2
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

from app.models.utc_datetime import UTCDateTime  # house autogen gotcha

revision = "c4d5e6f7a8b9"
down_revision = "f7b8c9d0e1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "number_formats",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("doc_type", sa.String(), nullable=False),
        sa.Column("prefix", sa.String(), nullable=False),
        sa.Column("format_pattern", sa.String(), nullable=False),
        sa.Column("reset_period", sa.String(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "doc_type", name="uq_number_format_tenant_doctype"
        ),
    )
    op.create_index(
        "ix_number_formats_tenant_id", "number_formats", ["tenant_id"]
    )

    op.create_table(
        "number_counters",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("doc_type", sa.String(), nullable=False),
        sa.Column("period_key", sa.String(), nullable=False),
        sa.Column("next_val", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "doc_type",
            "period_key",
            name="uq_number_counter_tenant_doctype_period",
        ),
    )
    op.create_index(
        "ix_number_counters_tenant_id", "number_counters", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_number_counters_tenant_id", table_name="number_counters")
    op.drop_table("number_counters")
    op.drop_index("ix_number_formats_tenant_id", table_name="number_formats")
    op.drop_table("number_formats")
