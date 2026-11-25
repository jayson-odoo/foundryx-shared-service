"""autocount company line-notes connection (plan 73, lane PO-LINK-KEEP-FURTHER-DESC)

* ``ac_company.line_notes_connection_id``: core ``connections.id`` of a same-tenant ``sql_database``
  connection the PO line Further Description is read through. NULL = hapi only; every existing row stays
  NULL (no backfill needed: unset means "unknown", the safe default).

Revision ID: 0049_autocount_line_notes_conn   (30 chars <= 32)
Revises: 0048_autocount_so_row_index
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0049_autocount_line_notes_conn"
down_revision: Union[str, Sequence[str], None] = "0048_autocount_so_row_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.ac_company ADD COLUMN IF NOT EXISTS line_notes_connection_id VARCHAR")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.ac_company DROP COLUMN IF EXISTS line_notes_connection_id")
