"""meetings init — the whole ten-table shape in ONE migration.

S0 only writes four of the tables (``user_opt_ins``, ``calendar_events``,
``meetings``, ``meeting_participants``); the transcript / minutes / action-item /
share tables are created empty here so the module has one shape from day one and
S3-S5 add no DDL drip (S0 plan §1).

Postgres-only DDL; a no-op on the SQLite test engine (per-module Alembic runs
only on Postgres — see ``app/module_platform/migrations.run_module_migrations``).

Revision ID: 0001_meetings_init
Revises:
Create Date: 2026-08-24
"""
from alembic import op

revision = "0001_meetings_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Build from the module's metadata so the tables are never hand-transcribed
    # and can never drift from models.py.
    from sqlalchemy import text

    from modules.meetings.db import MEETINGS_SCHEMA, MeetingsBase

    bind = op.get_bind()
    bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{MEETINGS_SCHEMA}"'))
    MeetingsBase.metadata.create_all(bind=bind)
    # Transcript search is pg_trgm text-similarity (spine M19) — the index has
    # no SQLAlchemy equivalent, so it is declared here rather than in models.py.
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_meetings_segments_text_trgm "
            f'ON "{MEETINGS_SCHEMA}".transcript_segments '
            "USING gin (text gin_trgm_ops)"
        )
    )


def downgrade() -> None:
    from sqlalchemy import text

    from modules.meetings.db import MEETINGS_SCHEMA, MeetingsBase

    bind = op.get_bind()
    bind.execute(
        text(f'DROP INDEX IF EXISTS "{MEETINGS_SCHEMA}".ix_meetings_segments_text_trgm')
    )
    MeetingsBase.metadata.drop_all(bind=bind)
