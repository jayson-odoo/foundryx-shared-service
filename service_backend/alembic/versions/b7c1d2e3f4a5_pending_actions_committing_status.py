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
    # T5 fix round 2, N4: re-adding the 4-value CHECK below would fail
    # outright on a live DB carrying any row still `committing` (a real
    # possibility - it's the beat-sweep atomic-claim state, not a rare
    # edge case). Reassign those rows to `failed` first - honest (a
    # downgrade mid-commit means the app can no longer resolve their
    # outcome) and never destructive (the row + its error/audit trail
    # survive, only the transient status changes). Plain `UPDATE`, so this
    # is a no-op (0 rows) on a DB that never reached this revision, and
    # works identically on SQLite (module/core migration tests) and
    # Postgres.
    op.execute(
        "UPDATE pending_actions SET status='failed', "
        "error_text=COALESCE(error_text, 'Downgraded while committing.') "
        "WHERE status='committing'"
    )
    op.drop_constraint('ck_pending_actions_status', 'pending_actions', type_='check')
    op.create_check_constraint(
        'ck_pending_actions_status',
        'pending_actions',
        "status IN ('pending','committed','cancelled','failed')",
    )
