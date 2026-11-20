"""Product `ItemType` backfill (ITEM-TYPE-SS, partner of sorento #1450)

Every existing ``product`` task predates the ``ItemType -> item_type_code``
preset row: this migration runs ``backfill_product_item_type`` (see its own
docstring, ``modules/autocount/backfill.py``) across every tenant. A row is
created only when none exists in ANY state - ENABLED for a task on the
AutoCount ``/itembypage`` preset path (every row carries ``ItemType``) or
whose ``result_columns`` already list ``ItemType``, DISABLED with one WARNING
otherwise.

Pure DATA, no column added. Every product row re-stages ONCE after deploy
(the new key enters the payload hash) - intended, same as 0025.

Deploy order: the pull snapshot path is additive. The PUSH path to a Sorento
ingest that still forbids unknown fields would reject products carrying a
non-blank ItemType, so sorento #1450 should land first where any product
task pushes.

Frozen ``sa.table`` backfill, never the live ORM model; does not commit -
Alembic's own transaction owns that (0019/0025 precedent).

Revision ID: 0028_autocount_item_type   (24 chars <= 32)
Revises: 0027_autocount_doc_feed_window
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_product_item_type

revision: str = "0028_autocount_item_type"
down_revision: Union[str, Sequence[str], None] = "0027_autocount_doc_feed_window"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_product_item_type(bind, schema="app_autocount")


def downgrade() -> None:
    # The mapping row is ordinary operator-editable state once written -
    # nothing to reverse (same posture as 0019/0025).
    pass
