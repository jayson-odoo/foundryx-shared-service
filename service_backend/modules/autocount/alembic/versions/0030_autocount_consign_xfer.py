"""Consignment `TransferedQty` backfill (AC-CONSIGN-PULL, partner of
sorento-crm#1654, CRM contract 2.9)

Every existing ``consignment`` task whose stored queries are still the #122
preset text is rewritten to the preset that selects ``TransferedQty`` on the
lines and a ``TransferedSum`` aggregate on the header and the fingerprint
sweep; it also gets a ``TransferedQty -> qty_transferred`` line mapping row.
See ``backfill_consignment_transferred_qty`` (``modules/autocount/backfill.py``).

Pure DATA, no column added. Every consignment re-stages ONCE after deploy
(``TransferedSum`` enters the row hash) - intended: it is how a CRM on
contract 2.9 receives ``TransferedQty``. Below 2.9 the wire record is the
unchanged 2.8 shape (the column is stripped by the sink's contract gate), so
deploy order against the CRM does not matter.

Frozen ``sa.table`` backfill, never the live ORM model; does not commit -
Alembic's own transaction owns that (0019/0025/0028/0029 precedent).

Revision ID: 0030_autocount_consign_xfer   (27 chars <= 32)
Revises: 0029_autocount_sales_agent
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_consignment_transferred_qty

revision: str = "0030_autocount_consign_xfer"
down_revision: Union[str, Sequence[str], None] = "0029_autocount_sales_agent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_consignment_transferred_qty(bind, schema="app_autocount")


def downgrade() -> None:
    # Operator-editable state once written - nothing to reverse (0029 precedent).
    pass
