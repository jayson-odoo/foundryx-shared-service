"""tenant branding (plan sprint-2/03)

Revision ID: a1b2c3d4e5f6
Revises: 750ac500c3b5
Create Date: 2026-06-06 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '750ac500c3b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tenant_branding',
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('slogan', sa.String(), nullable=True),
        sa.Column('logo_key', sa.String(), nullable=True),
        sa.Column('logo_mime', sa.String(), nullable=True),
        sa.Column('favicon_key', sa.String(), nullable=True),
        sa.Column('favicon_mime', sa.String(), nullable=True),
        sa.Column('illustration_key', sa.String(), nullable=True),
        sa.Column('illustration_mime', sa.String(), nullable=True),
        sa.Column('tokens_json', sa.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tenant_id'),
    )


def downgrade() -> None:
    op.drop_table('tenant_branding')
