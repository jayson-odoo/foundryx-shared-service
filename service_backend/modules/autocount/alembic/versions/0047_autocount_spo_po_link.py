"""autocount SPO -> PO-row index (lane AUTOCOUNT-STRANDED-OPS, C.d)

* ``ac_spo_po_link``: one row per line (``FromDocDtlKey``) of a shipping purchase order's NEWEST
  staged copy, so the ROW_ON_SPO guard and the SPO over-link sum are one indexed query instead of
  loading every staged SPO into the request (prod 17 Nov: that load ran a worker past its timeout).
  Two indexes: (tenant, company, po_dtl_key) for the lookups, (tenant, company, spo_source_ref) for
  the per-SPO rewrite.
* NO backfill here (lane AUTOCOUNT-INDEX-JOB): the table + indexes only, so the migration is seconds. The
  rows of SPOs staged before this revision are filled by the ``autocount_index_build`` background job
  (``write_back/index_build.py``); until a company's index is complete its lookups take the old full read
  (``link_index.index_ready``). Prod 17 Nov: the in-migration backfill ran the backend past its 240 s
  health budget and the deploy aborted.

Revision ID: 0047_autocount_spo_po_link   (27 chars <= 32)
Revises: 0046_autocount_call_person
Create Date: 2026-11-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047_autocount_spo_po_link"
down_revision: Union[str, Sequence[str], None] = "0046_autocount_call_person"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_spo_po_link"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # tolerant of a table created ahead of this revision (the crew test copy's idempotent SQL): create if absent
    if not sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        _create()
    op.create_index("ix_ac_spo_po_link_po_dtl", TABLE, ["tenant_id", "company_id", "po_dtl_key"], schema=SCHEMA,
                    if_not_exists=True)
    op.create_index("ix_ac_spo_po_link_spo_ref", TABLE, ["tenant_id", "company_id", "spo_source_ref"], schema=SCHEMA,
                    if_not_exists=True)


def _create() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("spo_source_ref", sa.String(), nullable=False),
        sa.Column("spo_doc_no", sa.String(), nullable=True),
        sa.Column("spo_dtl_key", sa.BigInteger(), nullable=True),
        sa.Column("po_dtl_key", sa.BigInteger(), nullable=False),
        sa.Column("qty", sa.Numeric(20, 8), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index("ix_ac_spo_po_link_spo_ref", table_name=TABLE, schema=SCHEMA)
    op.drop_index("ix_ac_spo_po_link_po_dtl", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
