"""autocount document line mapping (sprint-5/02 S2) - line_result_columns +
picker-to-rows backfill

``ac_entity_config`` += ``line_result_columns`` (JSON, nullable) - the operator's
picked line-aggregate names (``lines.count`` etc.), mirroring ``result_columns``
but for the LINE side of a document entity (AC-02-07). Existence-checked, same
two-order discipline as 0008/0009: a create_all-first host already has the
column from the model.

The real backfill here is behavioural, not columnar: a document task's line
fields used to be code-generated from three ``source_config`` picker keys
(``lineKeyColumn``/``lineProductColumn``/``lineWarehouseColumn`` - the now-
deleted ``mapping.document_line_rows``). Every EXISTING document task's
pickers are converted into real, operator-editable ``ac_field_mapping`` rows
(scope='line') via ``backfill_document_line_mapping_pickers`` - see that
function's own docstring (``modules/autocount/backfill.py``) for the full
idempotency contract. A never-configured / non-document entity is a no-op.

    !!  ORM-LEVEL BACKFILL, DELIBERATELY NOT sa.table.  !!
Unlike a bare column UPDATE (which always queries a frozen snapshot per the
BL-SS-082 lesson), this backfill BUILDS ROWS and is naturally an ORM insert.
That is safe here specifically because every column the ORM touches already
exists BY CONSTRUCTION at this point in the migration: ``ac_field_mapping.scope``
has existed since 0002 (long before this revision), and ``line_result_columns``
is added by THIS SAME migration, above, before the backfill runs - so there is
no revision gap where the live model outruns the schema (the exact failure
BL-SS-082 describes). The backfill only ``flush()``es (never `commit()`s) on a
``Session(bind=op.get_bind())`` sharing Alembic's own transaction/connection,
so Alembic's transaction still owns the single commit at the end - the
storage-migration lesson (a migration must never commit Alembic's own
connection) is honoured.

Revision ID: 0010_autocount_doc_lines   (24 chars <= 32)
Revises: 0009_autocount_s5_review
Create Date: 2026-09-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from modules.autocount.backfill import backfill_document_line_mapping_pickers
from modules.autocount.canonical.documents import DOCUMENT_ENTITY_TYPES

revision: str = "0010_autocount_doc_lines"
down_revision: Union[str, Sequence[str], None] = "0009_autocount_s5_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_entity_config"
COLUMN = "line_result_columns"


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {col["name"] for col in inspector.get_columns(table, schema=SCHEMA)}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Existence-checked (0007/0008/0009's own convention) - a create_all-first
    # host already has the column from the model.
    if COLUMN not in _columns(TABLE):
        op.add_column(
            TABLE, sa.Column(COLUMN, sa.JSON(none_as_null=True), nullable=True), schema=SCHEMA
        )

    # Enumerate ONLY the (tenant, company, entity_type) triple via a minimal,
    # frozen-column raw-SQL select (never the live ORM for the enumeration
    # itself) - the per-row backfill below is the part that is safe to run
    # ORM-level, per this file's own docstring.
    rows = bind.execute(
        sa.text(
            f'SELECT tenant_id, company_id, entity_type FROM "{SCHEMA}".ac_entity_config '
            f"WHERE entity_type = ANY(:entity_types)"
        ),
        {"entity_types": list(DOCUMENT_ENTITY_TYPES)},
    ).fetchall()

    if not rows:
        return

    session = Session(bind=bind)
    try:
        for tenant_id, company_id, entity_type in rows:
            backfill_document_line_mapping_pickers(session, tenant_id, company_id, entity_type)
        session.flush()
    finally:
        session.close()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if COLUMN in _columns(TABLE):
        op.drop_column(TABLE, COLUMN, schema=SCHEMA)
    # The line rows the upgrade backfilled are left in place on downgrade -
    # they are ordinary operator-editable ac_field_mapping rows now, no
    # different from ones an operator created by hand; nothing to reverse.
