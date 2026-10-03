"""Per-feed doc-feed read window + ledger content digest (DOC-FEED-WINDOW)

Adds the nullable JSON ``ac_doc_feed.window_config`` (poll basis, poll
lookback days, re-check days) and the nullable ``ac_doc_feed_ledger.
content_digest`` (sha256 of the last delivered record). Additive only: a NULL
window resolves to the pre-window behaviour, and a NULL digest means
"unknown" - the next re-check re-pushes that document once (the CRM answers
``unchanged``) and records its digest. No backfill is needed for either.

Revision ID: 0027_autocount_doc_feed_window   (30 chars <= 32)
Revises: 0026_autocount_doc_feed_schedule
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0027_autocount_doc_feed_window"
down_revision: Union[str, Sequence[str], None] = "0026_autocount_doc_feed_schedule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        f"ALTER TABLE {SCHEMA}.ac_doc_feed ADD COLUMN IF NOT EXISTS window_config JSON"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.ac_doc_feed_ledger "
        "ADD COLUMN IF NOT EXISTS content_digest VARCHAR(64)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {SCHEMA}.ac_doc_feed_ledger DROP COLUMN IF EXISTS content_digest")
    op.execute(f"ALTER TABLE {SCHEMA}.ac_doc_feed DROP COLUMN IF EXISTS window_config")
