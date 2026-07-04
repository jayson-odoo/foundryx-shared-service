"""notification_specs.doc_json (per-use template copy) — plan sprint-2/10

Revision ID: 2d3e4f5a6b7c
Revises: 1c2d3e4f5a6b
Create Date: 2026-06-09

"""
from alembic import op
import sqlalchemy as sa

revision = "2d3e4f5a6b7c"
down_revision = "1c2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notification_specs", sa.Column("doc_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("notification_specs", "doc_json")
