"""Customer `DebtorType` backfill (SS-DEBTOR-TYPE, partner of sorento-crm
SALES-ACCOUNT-TYPE)

Every existing ``customer`` task predates the ``DebtorType ->
market_segment_code`` mapping row: this migration runs
``backfill_customer_debtor_type`` (see its own docstring,
``modules/autocount/backfill.py``) across every tenant. The 0029 SalesAgent
repair exactly: a row is created only when none exists in ANY state, ENABLED
for a task on the vendor Debtor API or the AutoCount ``/debtorbypage`` preset
path or whose ``result_columns`` already list ``DebtorType``, DISABLED with
one WARNING otherwise.

Pure DATA, no column added. Every customer row with a non-blank DebtorType
re-stages ONCE after deploy (the new key enters the payload hash); a blank
type is omitted, so those rows keep their hash and do not re-stage.

Deploy order: free. ``market_segment_code`` is already an accepted key of the
CRM's customer contract, so this can land before or after the CRM's
SALES-ACCOUNT-TYPE lane.

Frozen ``sa.table`` backfill, never the live ORM model; does not commit -
Alembic's own transaction owns that (0029 precedent).

Revision ID: 0035_autocount_debtor_type   (26 chars <= 32)
Revises: 0034_autocount_item_class
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_customer_debtor_type

revision: str = "0035_autocount_debtor_type"
down_revision: Union[str, Sequence[str], None] = "0034_autocount_item_class"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_customer_debtor_type(bind, schema="app_autocount")


def downgrade() -> None:
    # The mapping row is ordinary operator-editable state once written -
    # nothing to reverse (0029 precedent).
    pass
