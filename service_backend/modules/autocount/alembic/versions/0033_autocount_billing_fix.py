"""Billing presets fixed against the real AutoCount schema (plan 35, SS-BILLING-PRESET-FIX)

The scout AC-BILLING-ACCESS-CHECK (27 Oct) ran the plan-32 billing queries on
the read-only grant: ``CS`` has no ``DocStatus``, ``DNDTL`` has no
``FromDoc*`` columns, ARDN / ARCN carry ``Cancelled``, a draft is ``D`` and
``DODTL`` IS granted. This migration runs ``backfill_billing_preset_fix`` (see
its docstring in ``modules/autocount/backfill.py``) for every ``invoice`` /
``cash_sale`` / ``credit_note`` / ``debit_note`` / ``ar_outstanding``
``ac_entity_config`` row across every tenant:

* a stored query byte-identical to the FROZEN pre-plan-35 text becomes the
  new preset text (IV/CS lines get the PR #127 DODTL join back, which 0032
  removed); a hand-written query is left untouched with one WARNING;
* a blank ``filterFormula`` on IV/CS/CN/DN becomes ``DocStatus != "D"``;
* the ``LinkDODocKey`` line row comes back enabled on IV/CS; the DN
  ``FromDoc*`` line rows are disabled.

Pure DATA, no column added; does not commit (Alembic's transaction owns that).
No wire change: the CRM contract already takes a DO line with no line ref.

Revision ID: 0033_autocount_billing_fix   (26 chars <= 32)
Revises: 0032_autocount_so_remark
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_billing_preset_fix

revision: str = "0033_autocount_billing_fix"
down_revision: Union[str, Sequence[str], None] = "0032_autocount_so_remark"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_billing_preset_fix(bind, schema="app_autocount")


def downgrade() -> None:
    # Rewritten statements and re-enabled rows are ordinary operator-editable
    # state once written - nothing to reverse (same posture as 0032).
    pass
