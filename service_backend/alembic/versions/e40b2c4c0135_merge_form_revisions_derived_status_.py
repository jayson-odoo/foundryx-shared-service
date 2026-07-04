"""merge form-revisions + derived-status/catalog heads

Revision ID: e40b2c4c0135
Revises: 39d06839e402, e6f7a8b9c0d1
Create Date: 2026-06-20 21:18:08.230339

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e40b2c4c0135'
down_revision: Union[str, Sequence[str], None] = ('39d06839e402', 'e6f7a8b9c0d1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
