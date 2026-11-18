"""ideation - History tab on the operator feedback record (lane FEEDBACK-SUBSCRIBE).

- ``idea_activity.actor_name``: who moved the status. Existing rows stay null
  (the actor was never recorded; History shows "-").
- ``idea_history``: the other tracked actions (field edits, follower added /
  removed, share link created / stopped).

New column is nullable and new table only: no backfill is possible or needed
(past actors were never stored). Idempotent ``IF NOT EXISTS`` DDL; a fresh
install gets them via ``create_all`` in ``install()``. Postgres-only; a no-op on
the SQLite test engine. Uses Alembic's own connection, never commits it.

Revision ID: 0024_ideation_history
Revises: 0023_ideation_follow_share
Create Date: 2026-11-17
"""
from alembic import op
from sqlalchemy import text

# <= 32 chars (alembic_version.version_num is VARCHAR(32)).
revision = "0024_ideation_history"
down_revision = "0023_ideation_follow_share"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    bind.execute(text(f'ALTER TABLE "{s}".idea_activity ADD COLUMN IF NOT EXISTS actor_name VARCHAR NULL'))
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{s}".idea_history ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            "  idea_id VARCHAR NOT NULL,"
            "  action VARCHAR NOT NULL,"
            "  from_value TEXT NULL,"
            "  to_value TEXT NULL,"
            "  actor_name VARCHAR NULL,"
            "  on_behalf_of_name VARCHAR NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )
    for col in ("tenant_id", "idea_id"):
        bind.execute(
            text(f'CREATE INDEX IF NOT EXISTS ix_{s}_idea_history_{col} ON "{s}".idea_history ({col})')
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    bind.execute(text(f'DROP TABLE IF EXISTS "{s}".idea_history'))
    bind.execute(text(f'ALTER TABLE "{s}".idea_activity DROP COLUMN IF EXISTS actor_name'))
