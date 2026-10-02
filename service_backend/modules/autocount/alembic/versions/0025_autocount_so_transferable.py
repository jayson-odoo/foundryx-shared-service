"""SO `Transferable` flag backfill (SS-SO-TRANSFERABLE, partner of sorento #1421)

Every existing ``sales_order`` task predates ``h.Transferable AS Transferable``
on the header query and the ``Transferable -> transferable`` mapping row: this
migration runs ``backfill_sales_order_transferable`` (see its own docstring,
``modules/autocount/backfill.py``) for every ``sales_order``
``ac_entity_config`` row across every tenant - the 0019 (``Ref``) repair, one
column later:

* a query byte-identical to the 0019 preset text (own company's
  ``database_name`` substituted) is rewritten to the NEW text and
  ``"Transferable"`` is appended to ``result_columns``;
* a ``Transferable -> transferable`` header row (transform ``bool``, not
  required, source-owned) is created when none exists in ANY state - ENABLED
  when the query was rewritten or already selects ``Transferable``, DISABLED
  with one WARNING otherwise (the production ``AED_SORENTO`` shape, whose
  hand-written query is left byte-untouched - see
  ``documentation/plans/sprint-5/18-autocount-so-transferable-acceptance-criteria.md``
  for the operator step).

Pure DATA, no column added. Every rewritten SO task re-stages ONCE after
deploy (the new column enters the row hash) - intended, same as 0019.

Deploy order: Sorento ingest ignores unknown fields (sorento #1421), so this
can ship before or after #1421; before it, Sorento drops ``transferable``.

Frozen ``sa.table`` backfill, never the live ORM model; does not commit -
Alembic's own transaction owns that (0016/0017/0018/0019 precedent).

Revision ID: 0025_autocount_so_transferable   (30 chars <= 32)
Revises: 0024_autocount_doc_lookup
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_sales_order_transferable

revision: str = "0025_autocount_so_transferable"
down_revision: Union[str, Sequence[str], None] = "0024_autocount_doc_lookup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_sales_order_transferable(bind, schema="app_autocount")


def downgrade() -> None:
    # The mapping row and rewritten statement are ordinary operator-editable
    # state once written - nothing to reverse (same posture as 0019).
    pass
