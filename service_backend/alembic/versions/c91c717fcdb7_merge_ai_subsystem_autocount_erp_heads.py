"""merge ai subsystem + autocount erp heads

Revision ID: c91c717fcdb7
Revises: ai_perms_s1b_grant_sweep, ac_erp_multi_s413
Create Date: 2026-07-22 08:04:37.140849

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c91c717fcdb7'
down_revision: Union[str, Sequence[str], None] = ('ai_perms_s1b_grant_sweep', 'ac_erp_multi_s413')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
