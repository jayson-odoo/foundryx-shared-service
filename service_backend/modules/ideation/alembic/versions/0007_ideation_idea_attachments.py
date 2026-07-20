"""ideation — idea media attachments (voice/image/video/file).

Create ``app_ideation.idea_attachments`` — the media pointers on an Idea captured
over WhatsApp (§5.1 ``attachments[]``, DC-9). Sorento durably stores the Respond
CDN bytes (R2/S3) and passes a durable ``url``; this table only persists the
resolved pointer + metadata. ``source_msg_id`` (Respond.io message id) is the
idempotency key — ``UNIQUE(idea_id, source_msg_id)`` so a re-sent/retried media
upserts one row, never duplicates.

CRITICAL (same deploy lesson as 0005): idempotent (``CREATE TABLE IF NOT EXISTS``)
AND the same table lands via ``IdeationBase.metadata.create_all`` in the module's
``install()`` — a fresh install gets the table whether the stamp-path or the
upgrade-path runs. Postgres-only DDL; a no-op on the SQLite test engine (the test
suite creates the table via ``create_all``).

Revision ID: 0007_ideation_idea_attachments
Revises: 0006_ideation_embed_widen_uuid
Create Date: 2026-07-20
"""
from alembic import op
from sqlalchemy import text

revision = "0007_ideation_idea_attachments"
down_revision = "0006_ideation_embed_widen_uuid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{IDEATION_SCHEMA}".idea_attachments ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            "  idea_id VARCHAR NOT NULL,"
            "  source_msg_id VARCHAR NOT NULL,"
            "  kind VARCHAR NOT NULL,"
            "  url TEXT NOT NULL,"
            "  filename VARCHAR NULL,"
            "  caption TEXT NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            f'  CONSTRAINT uq_idea_attachment_source_msg UNIQUE (idea_id, source_msg_id)'
            ")"
        )
    )
    bind.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS ix_idea_attachments_tenant_id '
            f'ON "{IDEATION_SCHEMA}".idea_attachments (tenant_id)'
        )
    )
    bind.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS ix_idea_attachments_idea_id '
            f'ON "{IDEATION_SCHEMA}".idea_attachments (idea_id)'
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(text(f'DROP TABLE IF EXISTS "{IDEATION_SCHEMA}".idea_attachments'))
