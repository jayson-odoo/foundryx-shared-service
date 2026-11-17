"""autocount write-back index build state (lane AUTOCOUNT-INDEX-JOB)

* ``ac_index_build``: one row per (tenant, company, index) - ``spo_po_link`` / ``so_row_index``. ``cursor_ref``
  = the last staged document (``source_ref``) the ``autocount_index_build`` job has indexed (the resume point);
  ``built_at`` set = the index holds every staged document of that company, and only then do the write-back
  lookups read it (``link_index.index_ready``); before that they take the old full read.
* Create only, no rows: a company with no row is simply "not built yet" (prod 17 Nov: the 0047 / 0048
  backfills inside the migration ran the backend past its health budget; the fill is a job now).

Revision ID: 0049_autocount_index_build   (26 chars <= 32)
Revises: 0048_autocount_so_row_index
Create Date: 2026-11-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0049_autocount_index_build"
down_revision: Union[str, Sequence[str], None] = "0048_autocount_so_row_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_index_build"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        return
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("company_id", sa.String(), primary_key=True),
        sa.Column("index_name", sa.String(), primary_key=True),
        sa.Column("cursor_ref", sa.String(), nullable=True),
        sa.Column("docs_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_table(TABLE, schema=SCHEMA, if_exists=True)
