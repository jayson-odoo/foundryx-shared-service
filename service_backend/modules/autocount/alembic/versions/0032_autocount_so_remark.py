"""SO `ShipInfo`, line `FurtherDescription` and `SectionHeading` backfill (FULFIL-SO-REMARK)

Every existing ``sales_order`` task predates ``h.ShipInfo AS ShipInfo`` on the
header query and the ``FurtherDescription`` / ``SectionHeading`` line columns.
This migration runs ``backfill_so_remark_fields`` (see its docstring in
``modules/autocount/backfill.py``) for every ``sales_order`` ``ac_entity_config``
row across every tenant, the 0025 (``Transferable``) repair in the same shape:

* a header / line query byte-identical to the FROZEN previous preset text is
  rewritten to the new preset text and the new columns are appended to
  ``result_columns`` / ``line_result_columns``;
* the ``ship_info``, ``line_remark`` and ``section_heading`` mapping rows are
  created when none exists in ANY state - ENABLED when the query was rewritten,
  DISABLED with one WARNING for a hand-written query (prod ``AED_SORENTO``),
  which is left byte-untouched (operator step: see
  ``documentation/engineering/autocount-mapping.md``).

Pure DATA, no column added; does not commit (Alembic's transaction owns that).
The Sorento CRM drops unknown keys, so this can ship before the CRM change.

Revision ID: 0032_autocount_so_remark   (25 chars <= 32)
Revises: 0031_autocount_task_incident
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_so_remark_fields

revision: str = "0032_autocount_so_remark"
down_revision: Union[str, Sequence[str], None] = "0031_autocount_task_incident"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_so_remark_fields(bind, schema="app_autocount")


def downgrade() -> None:
    # Rewritten statements and seeded rows are ordinary operator-editable
    # state once written - nothing to reverse (same posture as 0025).
    pass
