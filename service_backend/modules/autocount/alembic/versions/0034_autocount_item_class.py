"""Product `ItemClass` backfill (ITEM-CLASS, partner of sorento-crm ITEM-CLASS)

Every existing ``product`` task predates the ``ItemClass -> item_class_code``
preset row: this migration runs ``backfill_product_item_class`` (see its own
docstring, ``modules/autocount/backfill.py``) across every tenant. The 0028
ItemType repair exactly: ENABLED on the AutoCount ``/itembypage`` preset path
or when ``result_columns`` already list ``ItemClass``, DISABLED with one
WARNING otherwise.

Pure DATA, no column added. Every product row whose ItemClass is non-blank
re-stages ONCE after deploy (the new key enters the payload hash); a blank
ItemClass is omitted from the payload, so most rows do not.

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
