"""autocount run pages + pause (SS-STOCK-PAGE-PAUSE-CONFIG)

``ac_sync_run`` += nullable ``source_pages`` (pages of the main walk) and
``page_pause_ms`` (the pause between pages that run used). They feed the
"About N pages per run -> about X min per run" hint under the connection's
pause field. Historic rows stay NULL (the hint falls back to rows / page size
and the saved pause), so no backfill. Existence-checked, never commits.

Revision ID: 0051_autocount_run_pages   (24 chars <= 32)
Revises: 0050_autocount_further_desc
Create Date: 2026-11-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0051_autocount_run_pages"
down_revision: Union[str, Sequence[str], None] = "0050_autocount_further_desc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {SCHEMA}.ac_sync_run ADD COLUMN IF NOT EXISTS source_pages INTEGER NULL")
    op.execute(f"ALTER TABLE {SCHEMA}.ac_sync_run ADD COLUMN IF NOT EXISTS page_pause_ms INTEGER NULL")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {SCHEMA}.ac_sync_run DROP COLUMN IF EXISTS page_pause_ms")
    op.execute(f"ALTER TABLE {SCHEMA}.ac_sync_run DROP COLUMN IF EXISTS source_pages")
