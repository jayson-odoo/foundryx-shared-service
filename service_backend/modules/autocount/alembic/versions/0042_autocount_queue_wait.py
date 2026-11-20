"""autocount run queue wait (SS-SO-FAST-QUEUE)

``ac_sync_run`` += nullable ``queue_wait_ms``: how long the run's job waited
for a worker. Historic rows stay NULL (the wait was never recorded; the run
history shows "-"), so no backfill.
``ac_watermark`` += nullable ``last_fast_line_check_at`` (the once-a-minute
gate on the fast line check). NULL = due, so no backfill either.
Existence-checked, never commits.

Revision ID: 0042_autocount_queue_wait   (25 chars <= 32)
Revises: 0041_autocount_package_lines
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0042_autocount_queue_wait"
down_revision: Union[str, Sequence[str], None] = "0041_autocount_package_lines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"ALTER TABLE {SCHEMA}.ac_sync_run ADD COLUMN IF NOT EXISTS queue_wait_ms INTEGER NULL"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.ac_watermark "
        "ADD COLUMN IF NOT EXISTS last_fast_line_check_at TIMESTAMPTZ NULL"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {SCHEMA}.ac_sync_run DROP COLUMN IF EXISTS queue_wait_ms")
    op.execute(f"ALTER TABLE {SCHEMA}.ac_watermark DROP COLUMN IF EXISTS last_fast_line_check_at")
