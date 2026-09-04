"""autocount document line fixed-field repair (sprint-5/02 review round B1)

0010's backfill converted a document task's THREE picker columns
(``lineKeyColumn``/``lineProductColumn``/``lineWarehouseColumn``) into
operator-editable ``ac_field_mapping`` line rows (``source_ref``/
``product_ref``/``warehouse_ref``) - but never seeded the FIXED line fields
the deleted ``document_line_rows`` code-generated (``qty_ordered``,
``unit_price``, ``uom``, ... - see ``mapping.DOCUMENT_LINE_FIXED_FIELDS``).
So every task 0010 already migrated is left with only its 2-3 picker rows,
and every one of those fixed-field pushes goes out null forever.

``backfill_document_line_mapping_pickers`` was rewritten (review round B1)
to guard PER CANONICAL FIELD instead of "does any line row exist" - so
simply RE-RUNNING it here tops every already-migrated task up to the full
expected line set, and is a genuine no-op for a task that somehow already
has it (idempotent, safe to run more than once).

Same two-connection discipline as 0010's own docstring: this migration
alters no schema, so re-running the backfill on a session sharing Alembic's
own bind is safe (nothing here needs the storage-migration lesson's
separate-connection treatment - there is no batched multi-commit loop, one
flush at the end, Alembic owns the single commit).

Revision ID: 0011_autocount_doc_line_fix   (26 chars <= 32)
Revises: 0010_autocount_doc_lines
Create Date: 2026-09-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from modules.autocount.backfill import backfill_document_line_mapping_pickers
from modules.autocount.canonical.documents import DOCUMENT_ENTITY_TYPES

revision: str = "0011_autocount_doc_line_fix"
down_revision: Union[str, Sequence[str], None] = "0010_autocount_doc_lines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

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
    # The fixed-field rows this migration adds are ordinary operator-editable
    # ac_field_mapping rows, indistinguishable from ones an operator created
    # by hand after upgrade - same "nothing to reverse" stance as 0010.
    pass
