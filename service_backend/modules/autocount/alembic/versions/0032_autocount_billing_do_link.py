"""Billing DO link off DODTL (lane SS-BILLING-DO-API, owner ruling 25 Oct)

The AutoCount admin will not grant ``DODTL``. Every existing ``invoice`` /
``cash_sale`` task whose stored ``lineQuery`` is still the plan-32 text
(which joins ``DODTL`` only to read the DO DocKey) is rewritten to the
DODTL-free preset, ``LinkDODocKey`` leaves its ``line_result_columns`` and
its ``LinkDODocKey`` line mapping row is disabled. The DO DocKey now comes
from the Delivery Orders feed ledger (``http_source.book.billing_do_doc_keys``).
See ``backfill_billing_do_link_queries`` (``modules/autocount/backfill.py``).

Pure DATA, no column added. ``result_columns`` is untouched, so no row hash
moves and nothing re-stages because of this migration.

Frozen ``sa.table`` backfill, never the live ORM model; does not commit -
Alembic's own transaction owns that (0030 precedent).

Revision ID: 0032_autocount_billing_do_link   (30 chars <= 32)
Revises: 0031_autocount_task_incident
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_billing_do_link_queries

revision: str = "0032_autocount_billing_do_link"
down_revision: Union[str, Sequence[str], None] = "0031_autocount_task_incident"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    backfill_billing_do_link_queries(bind, schema="app_autocount")


def downgrade() -> None:
    # Operator-editable state once written - nothing to reverse (0030 precedent).
    pass
