"""Customer `DisplayTerm` backfill (SS-PAYMENT-TERMS, partner of sorento-crm
#2305 QUOTE-TERMS-SELECT, contract 2.14)

Every existing ``customer`` task predates the ``DisplayTerm ->
payment_terms_code`` mapping row: this migration runs
``backfill_customer_display_term`` (see its own docstring,
``modules/autocount/backfill.py``) across every tenant, the 0035 DebtorType
rules exactly.

Pure DATA, no column added. Adding a mapping row re-stages NOTHING by itself:
change detection hashes the RAW AutoCount row, so an unchanged debtor is not
re-sent. Existing customers reach the CRM with ``payment_terms_code`` only on
their next AutoCount edit, or when an operator presses Re-push on the customer
task (which clears the hashes). And the push strips the key until the CRM
advertises 2.14, so a customer edited BEFORE the CRM upgrade goes without it.
Rollout (plan 60 D6): after the CRM advertises 2.14, Re-push the customer task
of each company once.

Frozen ``sa.table`` backfill, never the live ORM model; does not commit -
Alembic's own transaction owns that (0029 precedent).

Revision ID: 0043_autocount_display_term   (27 chars <= 32)
Revises: 0042_autocount_queue_wait
Create Date: 2026-11-10
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_customer_display_term

revision: str = "0043_autocount_display_term"
down_revision: Union[str, Sequence[str], None] = "0042_autocount_queue_wait"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_customer_display_term(bind, schema="app_autocount")


def downgrade() -> None:
    # The mapping row is ordinary operator-editable state once written -
    # nothing to reverse (0029 precedent).
    pass
