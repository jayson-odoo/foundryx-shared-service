"""Billing lines carry AutoCount package keys (SS-PACKAGE-LINES)

A package sale is one PARENT line (blank ItemCode, ParentDtlKey 0) plus CHILD
lines pointing at it, and the first child repeats the parent's amount, so the
CRM double counts a plain line sum. This migration runs
``backfill_billing_package_lines`` (``modules/autocount/backfill.py``) for
every ``invoice`` ``ac_entity_config`` row across every tenant: a stored
``lineQuery`` byte-identical to the frozen plan-35 text also selects
``ParentDtlKey`` and gets its ``parent_dtl_key`` line row; a hand-written
query is left untouched with one WARNING. CS / CN / DN are not touched
(their tables are unconfirmed).

Pure DATA, no column added; does not commit (Alembic's transaction owns that).
The new wire fields reach only a CRM advertising contract >= 2.13.

Revision ID: 0041_autocount_package_lines   (28 chars <= 32)
Revises: 0040_autocount_write_ops
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_billing_package_lines

revision: str = "0041_autocount_package_lines"
down_revision: Union[str, Sequence[str], None] = "0040_autocount_write_ops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_billing_package_lines(bind, schema="app_autocount")


def downgrade() -> None:
    # A rewritten query and added rows are ordinary operator-editable state
    # once written - nothing to reverse (same posture as 0033).
    pass
