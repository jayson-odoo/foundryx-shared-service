"""rule engine: normalize JSON-null conditions to SQL NULL

Revision ID: 750ac500c3b5
Revises: 0a026bef96c4
Create Date: 2026-06-06 15:25:45.843271

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '750ac500c3b5'
down_revision: Union[str, Sequence[str], None] = '0a026bef96c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Data fix: edges cleared before none_as_null landed stored JSON null
    (not SQL NULL) - they ghosted on the Rules page as "Always allowed" and
    needlessly triggered per-record fireable computation."""
    op.execute(
        "UPDATE status_transitions SET conditions_json = NULL "
        "WHERE conditions_json::text = 'null'"
    )


def downgrade() -> None:
    """No-op - SQL NULL is the canonical 'unconditional' either way."""
    pass
