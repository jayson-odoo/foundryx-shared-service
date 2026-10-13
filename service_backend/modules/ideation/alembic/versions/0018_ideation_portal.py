"""ideation - idea portal (lane IDEA-PORTAL).

- ``ideas.portal_hidden`` BOOLEAN NOT NULL DEFAULT false (Q5). A constant
  default is a metadata-only ADD COLUMN on Postgres 11+ (no table rewrite);
  every existing row reads false = visible, which matches today's behaviour.
- ``ideas.portal_note`` TEXT NULL (Q3) - the changelog note managers edit.
  NULL for every existing row (nothing to copy from).
- ``ideas.submitter_user_id`` VARCHAR NULL + index - the staff creator (portal
  "Yours"). No backfill: existing operator-created rows only stored the
  operator's NAME, and ownership is never inferred from a name.
- ``idea_votes.voter_name`` / ``voter_role`` (nullable) - stamped by portal
  votes for the voters list. Existing votes stay NULL; the portal falls back
  to a role-only label for them (there is no name to copy from).
- ``idea_comment_likes`` - new table, no backfill.
- ``idea_activity`` - new table, BACKFILLED from the ``status_changed`` rows of
  ``idea_status_events`` so ideas moved before this deploy still show their
  history. ``source_event_id`` is UNIQUE, so the backfill is idempotent and a
  re-run inserts nothing. Runs on Alembic's own connection, inside its
  transaction (no side-connection commit).

Idempotent ``IF NOT EXISTS`` DDL. Postgres-only; a no-op on the SQLite test
engine (the suite builds the schema via ``IdeationBase.metadata.create_all``;
``services/portal.py::backfill_activity_from_status_events`` is the same
backfill in ORM form, unit-tested directly).

Revision ID: 0018_ideation_portal
Revises: 0017_ideation_canny_fields
Create Date: 2026-10-13
"""
from alembic import op
from sqlalchemy import text

revision = "0018_ideation_portal"
down_revision = "0017_ideation_canny_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    s = IDEATION_SCHEMA
    bind.execute(
        text(
            f'ALTER TABLE "{s}".ideas '
            "ADD COLUMN IF NOT EXISTS portal_hidden BOOLEAN NOT NULL DEFAULT false"
        )
    )
    bind.execute(text(f'ALTER TABLE "{s}".ideas ADD COLUMN IF NOT EXISTS portal_note TEXT NULL'))
    bind.execute(
        text(f'ALTER TABLE "{s}".ideas ADD COLUMN IF NOT EXISTS submitter_user_id VARCHAR NULL')
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ideas_submitter_user_id "
            f'ON "{s}".ideas (submitter_user_id)'
        )
    )
    for col in ("voter_name", "voter_role"):
        bind.execute(
            text(f'ALTER TABLE "{s}".idea_votes ADD COLUMN IF NOT EXISTS {col} VARCHAR NULL')
        )
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{s}".idea_comment_likes ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            f'  idea_id VARCHAR NOT NULL REFERENCES "{s}".ideas(id),'
            f'  comment_id VARCHAR NOT NULL REFERENCES "{s}".idea_comments(id),'
            "  liker_id VARCHAR NOT NULL,"
            "  liker_name VARCHAR NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  CONSTRAINT uq_idea_comment_like UNIQUE (comment_id, liker_id)"
            ")"
        )
    )
    for col in ("tenant_id", "idea_id", "comment_id"):
        bind.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_{s}_idea_comment_likes_{col} "
                f'ON "{s}".idea_comment_likes ({col})'
            )
        )
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{s}".idea_activity ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            "  idea_id VARCHAR NOT NULL,"
            "  kind VARCHAR NOT NULL,"
            "  from_label VARCHAR NULL,"
            "  to_label VARCHAR NULL,"
            "  to_color VARCHAR NULL,"
            "  source_event_id VARCHAR NULL UNIQUE,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )
    for col in ("tenant_id", "idea_id"):
        bind.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_{s}_idea_activity_{col} "
                f'ON "{s}".idea_activity ({col})'
            )
        )
    # Backfill: one activity row per historical status move.
    bind.execute(
        text(
            f'INSERT INTO "{s}".idea_activity '
            "(id, tenant_id, idea_id, kind, from_label, to_label, source_event_id, created_at) "
            "SELECT 'ise:' || e.id, e.tenant_id, e.idea_id, 'status_changed', "
            "e.payload_json->>'from_status_label', e.payload_json->>'status_label', e.id, e.created_at "
            f'FROM "{s}".idea_status_events e '
            "WHERE e.kind = 'status_changed' "
            "ON CONFLICT DO NOTHING"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    s = IDEATION_SCHEMA
    bind.execute(text(f'DROP TABLE IF EXISTS "{s}".idea_activity'))
    bind.execute(text(f'DROP TABLE IF EXISTS "{s}".idea_comment_likes'))
    for col in ("voter_role", "voter_name"):
        bind.execute(text(f'ALTER TABLE "{s}".idea_votes DROP COLUMN IF EXISTS {col}'))
    bind.execute(text(f'DROP INDEX IF EXISTS "{s}".ix_ideas_submitter_user_id'))
    bind.execute(text(f'ALTER TABLE "{s}".ideas DROP COLUMN IF EXISTS submitter_user_id'))
    bind.execute(text(f'ALTER TABLE "{s}".ideas DROP COLUMN IF EXISTS portal_note'))
    bind.execute(text(f'ALTER TABLE "{s}".ideas DROP COLUMN IF EXISTS portal_hidden'))
