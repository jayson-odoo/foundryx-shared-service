"""merge plan 01 connection erp/llm head with plan 27 head

Revision ID: 82497a2fcea3
Revises: b7c1d2e3f4a5, conn_erp_llm_s501
Create Date: 2026-09-06 11:37:29.220792

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82497a2fcea3'
down_revision: Union[str, Sequence[str], None] = ('b7c1d2e3f4a5', 'conn_erp_llm_s501')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
