"""ideation - intake contract columns (S1 turn-algorithm + S5 public status
page, lane feat/ideation-intake-s1-s5).

Adds ``title`` / ``submitter_tier`` / ``idea_number`` / ``status_token`` /
``intake_state`` to ``ideas``, then backfills ``idea_number`` +
``status_token`` for every existing NON-draft idea (join ``public.statuses``
on the idea's ``status_id`` to skip drafts, oldest-first by ``created_at,
id``): ``idea_number`` via a Postgres sequence
(``app_ideation.ideas_idea_number_seq``, ``IDEA-<n, zero-padded to at least
4 digits>``), ``status_token`` via ``secrets.token_urlsafe(24)`` generated
per row in Python.

Idempotent - ``ADD COLUMN IF NOT EXISTS`` / ``CREATE SEQUENCE IF NOT
EXISTS`` / ``IF NOT EXISTS`` unique indexes, and the backfill only touches
rows where the target column is still NULL, so a re-run is a no-op.

Postgres-only DDL; a no-op on the SQLite test engine (per-module Alembic
runs only on Postgres - see ``app/module_platform/migrations``).

Revision ID: 0010_ideation_intake_contract
Revises: 0009_ideation_is_test
Create Date: 2026-09-24
"""
import secrets

from alembic import op
from sqlalchemy import text

revision = "0010_ideation_intake_contract"
down_revision = "0009_ideation_is_test"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    schema = IDEATION_SCHEMA
    bind.execute(text(f'ALTER TABLE "{schema}".ideas ADD COLUMN IF NOT EXISTS title TEXT'))
    bind.execute(
        text(f'ALTER TABLE "{schema}".ideas ADD COLUMN IF NOT EXISTS submitter_tier TEXT')
    )
    bind.execute(
        text(f'ALTER TABLE "{schema}".ideas ADD COLUMN IF NOT EXISTS idea_number TEXT')
    )
    bind.execute(
        text(f'ALTER TABLE "{schema}".ideas ADD COLUMN IF NOT EXISTS status_token TEXT')
    )
    bind.execute(
        text(f'ALTER TABLE "{schema}".ideas ADD COLUMN IF NOT EXISTS intake_state JSONB')
    )

    bind.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{schema}".ideas_idea_number_seq'))
    bind.execute(
        text(
            f'CREATE UNIQUE INDEX IF NOT EXISTS uq_ideas_idea_number '
            f'ON "{schema}".ideas (idea_number)'
        )
    )
    bind.execute(
        text(
            f'CREATE UNIQUE INDEX IF NOT EXISTS uq_ideas_status_token '
            f'ON "{schema}".ideas (status_token)'
        )
    )

    # Backfill idea_number - every existing NON-draft idea whose number is
    # still NULL, oldest first (created_at, id): a stable, deterministic order.
    rows = bind.execute(
        text(
            f'SELECT i.id FROM "{schema}".ideas i '
            "JOIN public.statuses s ON s.id = i.status_id "
            "WHERE i.idea_number IS NULL AND s.key <> 'draft' "
            "ORDER BY i.created_at, i.id"
        )
    ).fetchall()
    for (idea_id,) in rows:
        bind.execute(
            text(
                f'UPDATE "{schema}".ideas SET idea_number = '
                f"'IDEA-' || lpad(nextval('\"{schema}\".ideas_idea_number_seq')::text, 4, '0') "
                "WHERE id = :id AND idea_number IS NULL"
            ),
            {"id": idea_id},
        )

    # Backfill status_token - every existing NON-draft idea whose token is
    # still NULL; one secrets.token_urlsafe(24) generated in Python per row.
    rows = bind.execute(
        text(
            f'SELECT i.id FROM "{schema}".ideas i '
            "JOIN public.statuses s ON s.id = i.status_id "
            "WHERE i.status_token IS NULL AND s.key <> 'draft' "
            "ORDER BY i.created_at, i.id"
        )
    ).fetchall()
    for (idea_id,) in rows:
        bind.execute(
            text(
                f'UPDATE "{schema}".ideas SET status_token = :token '
                "WHERE id = :id AND status_token IS NULL"
            ),
            {"id": idea_id, "token": secrets.token_urlsafe(24)},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    schema = IDEATION_SCHEMA
    bind.execute(text(f'DROP INDEX IF EXISTS "{schema}".uq_ideas_idea_number'))
    bind.execute(text(f'DROP INDEX IF EXISTS "{schema}".uq_ideas_status_token'))
    bind.execute(text(f'ALTER TABLE "{schema}".ideas DROP COLUMN IF EXISTS title'))
    bind.execute(text(f'ALTER TABLE "{schema}".ideas DROP COLUMN IF EXISTS submitter_tier'))
    bind.execute(text(f'ALTER TABLE "{schema}".ideas DROP COLUMN IF EXISTS idea_number'))
    bind.execute(text(f'ALTER TABLE "{schema}".ideas DROP COLUMN IF EXISTS status_token'))
    bind.execute(text(f'ALTER TABLE "{schema}".ideas DROP COLUMN IF EXISTS intake_state'))
    bind.execute(text(f'DROP SEQUENCE IF EXISTS "{schema}".ideas_idea_number_seq'))
