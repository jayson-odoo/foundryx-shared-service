"""Raw line `FurtherDescription` on SO + PO (SS-FURTHER-DESC-SEND)

Runs ``backfill_further_desc_fields`` (see its docstring in
``modules/autocount/backfill.py``) across every tenant:

* every ``sales_order`` task gets a ``FurtherDescription ->
  further_description_rtf`` ``raw_text`` line row (the RTF bytes unchanged),
  ENABLED when the task already reads the column, else DISABLED + one WARNING;
* every ``purchase_order`` task whose line query is the FROZEN previous preset
  text gets ``d.FurtherDescription AS FurtherDescription`` and an ENABLED row
  of the same kind; a hand-written query is left untouched and its row is
  seeded DISABLED with one WARNING.

``line_remark`` rows are not touched.

Pure DATA, no column added; does not commit (Alembic's transaction owns that).
``further_description_rtf`` reaches the CRM only once it advertises 2.16,
so this can ship before the CRM change.

Revision ID: 0050_autocount_further_desc   (27 chars <= 32)
Revises: 0049_autocount_line_notes_conn
Create Date: 2026-11-25
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_further_desc_fields

revision: str = "0050_autocount_further_desc"
down_revision: Union[str, Sequence[str], None] = "0049_autocount_line_notes_conn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_further_desc_fields(bind, schema="app_autocount")


def downgrade() -> None:
    # Rewritten statements and seeded rows are ordinary operator-editable
    # state once written - nothing to reverse (same posture as 0032).
    pass
