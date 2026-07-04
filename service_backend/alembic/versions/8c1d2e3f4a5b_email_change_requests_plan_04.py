"""change-email ceremony: email_change_requests (plan sprint-2/04)

Revision ID: 8c1d2e3f4a5b
Revises: a1b2c3d4e5f6
Create Date: 2026-06-06 20:00:00.000000

Re-parented onto plan 03's tenant_branding head when 04 rebased onto the
merged main (both plans developed off the same parent on sibling branches).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c1d2e3f4a5b'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'email_change_requests',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('new_email', sa.String(), nullable=False),
        sa.Column('old_token', sa.String(), nullable=False),
        sa.Column('new_token', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('email_change_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_email_change_requests_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_email_change_requests_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_email_change_requests_old_token'), ['old_token'], unique=True)
        batch_op.create_index(batch_op.f('ix_email_change_requests_new_token'), ['new_token'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('email_change_requests')
