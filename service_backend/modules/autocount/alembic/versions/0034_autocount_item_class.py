"""Product `ItemClass` backfill (ITEM-CLASS, partner of sorento-crm ITEM-CLASS)

Every existing ``product`` task predates the ``ItemClass -> item_class_code``
preset row: this migration runs ``backfill_product_item_class`` (see its own
docstring, ``modules/autocount/backfill.py``) across every tenant. The 0028
ItemType repair exactly: ENABLED on the AutoCount ``/itembypage`` preset path
or when ``result_columns`` already list ``ItemClass``, DISABLED with one
WARNING otherwise.

Pure DATA, no column added. Every product row re-stages ONCE after deploy:
the new key enters the payload hash, and a blank ItemClass is sent as ""
(crew ruling 29 Oct, security M1) so the CRM clears a class AutoCount
cleared. Live size 29 Oct: db1 11,962 + db2 3,520 = 15,482 rows, pushed by the
ordinary master push (`autocount_sink_batch_size` 200 per request, inside the
600 s `autocount_run_time_budget_seconds` per run; a run cut short resumes on
the next tick), so about 78 requests in total.

Deploy order: the sorento-crm ITEM-CLASS PR should land first where any
product task pushes (the CRM drops unknown keys, so an older CRM only loses
the value, it never refuses the push).

Frozen ``sa.table`` backfill, never the live ORM model; does not commit -
Alembic's own transaction owns that (0028 precedent).

Revision ID: 0034_autocount_item_class   (25 chars <= 32)
Revises: 0033_autocount_billing_fix
Create Date: 2026-10-29
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_product_item_class

revision: str = "0034_autocount_item_class"
down_revision: Union[str, Sequence[str], None] = "0033_autocount_billing_fix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_product_item_class(bind, schema="app_autocount")


def downgrade() -> None:
    # The mapping row is ordinary operator-editable state once written -
    # nothing to reverse (0028 precedent).
    pass
