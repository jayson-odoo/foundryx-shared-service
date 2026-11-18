"""ideation - comment attachments (lane FEEDBACK-ATTACH-IMAGE).

Adds ``comment_id`` (nullable, indexed, FK to ``idea_comments``) to
``idea_attachments`` so a file can hang off a comment. NULL = a report-level
file, which is every row that already exists - so no backfill is needed.

Adds ``thumb_key`` (nullable): the storage key of an image's small preview.
Existing rows start NULL and the lazy path IS the backfill - the first
``?variant=thumb`` read of an old image generates and stores its thumbnail.

Idempotent ``ADD COLUMN IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS`` (same
lesson as 0013). Postgres-only DDL; a no-op on the SQLite test engine (the suite
creates the column via ``IdeationBase.metadata.create_all``).

Revision ID: 0025_ideation_comment_attach
Revises: 0022_ideation_board_product
Create Date: 2026-11-17
"""
from alembic import op
from sqlalchemy import text

# <= 32 chars (alembic_version.version_num is VARCHAR(32)).
revision = "0025_ideation_comment_attach"
down_revision = "0022_ideation_board_product"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    bind.execute(
        text(
            f'ALTER TABLE "{s}".idea_attachments '
            f'ADD COLUMN IF NOT EXISTS comment_id VARCHAR NULL REFERENCES "{s}".idea_comments (id)'
        )
    )
    bind.execute(text(f'ALTER TABLE "{s}".idea_attachments ADD COLUMN IF NOT EXISTS thumb_key VARCHAR NULL'))
    bind.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS ix_{s}_idea_attachments_comment_id "
            f'ON "{s}".idea_attachments (comment_id)'
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    bind.execute(text(f'DROP INDEX IF EXISTS "{s}".ix_{s}_idea_attachments_comment_id'))
    bind.execute(text(f'ALTER TABLE "{s}".idea_attachments DROP COLUMN IF EXISTS thumb_key'))
    bind.execute(text(f'ALTER TABLE "{s}".idea_attachments DROP COLUMN IF EXISTS comment_id'))
