"""Deferred actions - add 'committing' to pending_actions.status (T5 fix round 1, item 4)

Revision ID: b7c1d2e3f4a5
Revises: 65458ac6203e
Create Date: 2026-09-05 00:00:00.000000

Atomic-claim fix: `commit_one` now claims a row with
`UPDATE pending_actions SET status='committing' WHERE id=:id AND status='pending'`
before executing its handler, so two concurrent commit attempts (a beat tick
racing the frontend's lazy `current` poll) can never both run the handler.
No backfill needed - existing rows are never in this new transient state.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c1d2e3f4a5'
down_revision: Union[str, Sequence[str], None] = '65458ac6203e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('ck_pending_actions_status', 'pending_actions', type_='check')
    op.create_check_constraint(
        'ck_pending_actions_status',
        'pending_actions',
        "status IN ('pending','committing','committed','cancelled','failed')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_pending_actions_status', 'pending_actions', type_='check')
    op.create_check_constraint(
        'ck_pending_actions_status',
        'pending_actions',
        "status IN ('pending','committed','cancelled','failed')",
    )
