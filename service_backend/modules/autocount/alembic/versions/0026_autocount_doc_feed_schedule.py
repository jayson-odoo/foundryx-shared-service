"""Per-feed Document feed schedule (sprint-5/19, DOC-FEED-INTERVAL)

Adds the nullable JSON ``ac_doc_feed.schedule_config`` - the feed's poll /
deletion-sweep cadence in the same shape as an ETL task's schedule. Additive
only: every existing row stays NULL, which resolves to the pre-19 hard-coded
cadence (poll 60 min, sweep every 24 h), so nothing changes until an owner
edits a feed. No backfill is needed for that reason.

Revision ID: 0026_autocount_doc_feed_schedule   (32 chars <= 32)
Revises: 0025_autocount_so_transferable
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0026_autocount_doc_feed_schedule"
down_revision: Union[str, Sequence[str], None] = "0025_autocount_so_transferable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        f"ALTER TABLE {SCHEMA}.ac_doc_feed ADD COLUMN IF NOT EXISTS schedule_config JSON"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {SCHEMA}.ac_doc_feed DROP COLUMN IF EXISTS schedule_config")
