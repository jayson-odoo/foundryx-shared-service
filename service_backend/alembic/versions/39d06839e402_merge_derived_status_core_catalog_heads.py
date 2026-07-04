"""merge derived-status + core catalog heads

Revision ID: 39d06839e402
Revises: a7b8c9d0e1f2, a8b9c0d1e2f3
Create Date: 2026-06-20 15:43:06.853357

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39d06839e402'
down_revision: Union[str, Sequence[str], None] = ('a7b8c9d0e1f2', 'a8b9c0d1e2f3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
