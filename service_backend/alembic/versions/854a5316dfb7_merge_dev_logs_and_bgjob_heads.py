"""merge dev-logs and bgjob heads

Revision ID: 854a5316dfb7
Revises: bgjob_logs_ab12cd34, dlc_s412_integration_activity
Create Date: 2026-07-11 22:25:20.434417

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '854a5316dfb7'
down_revision: Union[str, Sequence[str], None] = ('bgjob_logs_ab12cd34', 'dlc_s412_integration_activity')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
