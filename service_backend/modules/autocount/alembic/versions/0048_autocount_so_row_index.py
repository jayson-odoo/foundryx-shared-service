"""autocount SO-row index (lane AUTOCOUNT-STRANDED-OPS, C.d)

* ``ac_so_row_index``: one row per line (``DtlKey``) of a sales order's NEWEST staged copy (every copy
  staged at that same newest moment), with the SO number and the line's location; ``ambiguous`` = equally
  new copies disagree on the location. The unlink snapshot (the SO number of a PO row that reads back
  without ``FromDocNo``) and the relocate (the SO row's location) become one indexed query instead of
  loading every staged sales order into the request. Two indexes: (tenant, company, so_dtl_key) for the
  lookups, (tenant, company, so_source_ref) for the per-SO rewrite.
* ``ix_ac_staged_doc_no`` on ``ac_staged_record`` (tenant, company, entity_type, doc_no): the SPO re-stage
  finds the POs its lines name by number instead of loading every staged PO.
* NO backfill here (lane AUTOCOUNT-INDEX-JOB): tables + indexes only. The rows of SOs staged before this
  revision are filled by the ``autocount_index_build`` background job (``write_back/index_build.py``); until a
  company's index is complete its lookups take the old full read (``link_index.index_ready``).

Revision ID: 0048_autocount_so_row_index   (27 chars <= 32)
Revises: 0047_autocount_spo_po_link
Create Date: 2026-11-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048_autocount_so_row_index"
down_revision: Union[str, Sequence[str], None] = "0047_autocount_spo_po_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_so_row_index"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # tolerant of a table created ahead of this revision (the crew test copy's idempotent SQL): create if absent
    if not sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        _create()
    bind.execute(sa.text(f"ALTER TABLE {SCHEMA}.{TABLE} ADD COLUMN IF NOT EXISTS so_doc_key varchar"))
    op.create_index("ix_ac_so_row_index_dtl", TABLE, ["tenant_id", "company_id", "so_dtl_key"], schema=SCHEMA,
                    if_not_exists=True)
    op.create_index("ix_ac_so_row_index_so_ref", TABLE, ["tenant_id", "company_id", "so_source_ref"], schema=SCHEMA,
                    if_not_exists=True)
    # the SPO re-stage finds the POs its lines name by number (write_back/doc_mapping._po_dtl_lookup)
    op.create_index("ix_ac_staged_doc_no", "ac_staged_record", ["tenant_id", "company_id", "entity_type", "doc_no"],
                    schema=SCHEMA, if_not_exists=True)


def _create() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("so_source_ref", sa.String(), nullable=False),
        sa.Column("so_doc_no", sa.String(), nullable=True),
        sa.Column("so_dtl_key", sa.BigInteger(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("ambiguous", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("staged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("so_doc_key", sa.String(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index("ix_ac_staged_doc_no", table_name="ac_staged_record", schema=SCHEMA, if_exists=True)
    op.drop_index("ix_ac_so_row_index_so_ref", table_name=TABLE, schema=SCHEMA)
    op.drop_index("ix_ac_so_row_index_dtl", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
