"""ideation - idea attachment uploads (plan sprint-5/15 B1).

Adds ``storage_key`` / ``mime`` / ``size_bytes`` to ``idea_attachments`` so an
operator or embed user can upload a file onto an idea (bytes in tenant storage,
served through the api). All three nullable: existing rows are WhatsApp captures
that keep their durable ``url``, so no backfill is needed.

Idempotent ``ADD COLUMN IF NOT EXISTS`` (same lesson as 0004/0009/0011).
Postgres-only DDL; a no-op on the SQLite test engine (the suite creates the
columns via ``IdeationBase.metadata.create_all``).

Revision ID: 0013_ideation_attachment_upload
Revises: 0012_ideation_merge_rank_events
Create Date: 2026-09-29
"""
from alembic import op
from sqlalchemy import text

revision = "0013_ideation_attachment_upload"
down_revision = "0012_ideation_merge_rank_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    for ddl in (
        "storage_key VARCHAR NULL",
        "mime VARCHAR NULL",
        "size_bytes INTEGER NULL",
    ):
        bind.execute(
            text(
                f'ALTER TABLE "{IDEATION_SCHEMA}".idea_attachments '
                f"ADD COLUMN IF NOT EXISTS {ddl}"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    for col in ("size_bytes", "mime", "storage_key"):
        bind.execute(
            text(
                f'ALTER TABLE "{IDEATION_SCHEMA}".idea_attachments '
                f"DROP COLUMN IF EXISTS {col}"
            )
        )
