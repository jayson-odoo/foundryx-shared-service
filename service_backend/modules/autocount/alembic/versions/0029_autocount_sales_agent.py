"""Customer `SalesAgent` backfill (SS-DEBTOR-AGENT, partner of sorento
CUSTOMER-SALES-AGENT)

Every existing ``customer`` task predates the ``SalesAgent ->
sales_agent_code`` mapping row: this migration runs
``backfill_customer_sales_agent`` (see its own docstring,
``modules/autocount/backfill.py``) across every tenant. A row is created only
when none exists in ANY state - ENABLED for a task on the vendor Debtor API
or the AutoCount ``/debtorbypage`` preset path (every row carries
``SalesAgent``) or whose ``result_columns`` already list ``SalesAgent``,
DISABLED with one WARNING otherwise.

Pure DATA, no column added. Every customer row with a non-blank agent
re-stages ONCE after deploy (the new key enters the payload hash) - intended,
same as 0028.

Deploy order: the pull snapshot path is additive. The PUSH path to a Sorento
ingest that still forbids unknown fields would reject customers carrying a
non-blank SalesAgent, so the sorento CUSTOMER-SALES-AGENT lane should land
first where any customer task pushes.

Frozen ``sa.table`` backfill, never the live ORM model; does not commit -
Alembic's own transaction owns that (0019/0025/0028 precedent).

Revision ID: 0029_autocount_sales_agent   (26 chars <= 32)
Revises: 0028_autocount_item_type
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_customer_sales_agent

revision: str = "0029_autocount_sales_agent"
down_revision: Union[str, Sequence[str], None] = "0028_autocount_item_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_customer_sales_agent(bind, schema="app_autocount")


def downgrade() -> None:
    # The mapping row is ordinary operator-editable state once written -
    # nothing to reverse (same posture as 0019/0025/0028).
    pass
