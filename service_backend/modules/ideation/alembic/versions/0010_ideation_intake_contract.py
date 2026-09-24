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
import uuid

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
                # Postgres' lpad() TRUNCATES (on the right) when the input is
                # already longer than the target length - a plain
                # lpad(n::text, 4, '0') would corrupt IDEA-10000+ into
                # "IDEA-1000". Only pad below 10000; format n::text as-is at
                # or past it (review round 1, should-fix #5).
                "'IDEA-' || (CASE WHEN n < 10000 THEN lpad(n::text, 4, '0') ELSE n::text END) "
                f"FROM (SELECT nextval('\"{schema}\".ideas_idea_number_seq') AS n) seq "
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

    # Seed the new draft -> duplicate edge onto every EXISTING tenant fork of
    # the Idea status set (review round 1, should-fix #4a). ``seed_idea_statuses``
    # already adds the platform-tier edge on every boot (idempotent), and a
    # FUTURE fork copies whatever the platform graph holds AT FORK TIME
    # (``StatusService._fork`` queries the live platform edges, never a
    # hardcoded list) - so only a tenant that forked BEFORE this edge existed
    # is missing it. Idempotent: only inserts where the fork has both a
    # ``draft`` and a ``duplicate`` Idea status and lacks the edge.
    fork_rows = bind.execute(
        text(
            "SELECT d.tenant_id, d.id, dup.id "
            "FROM public.statuses d "
            "JOIN public.statuses dup "
            "  ON dup.entity_type = 'idea' AND dup.tenant_id = d.tenant_id AND dup.key = 'duplicate' "
            "WHERE d.entity_type = 'idea' AND d.key = 'draft' AND d.tenant_id IS NOT NULL "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM public.status_transitions t "
            "  WHERE t.entity_type = 'idea' AND t.tenant_id = d.tenant_id "
            "  AND t.from_status_id = d.id AND t.to_status_id = dup.id"
            ")"
        )
    ).fetchall()
    for tenant_id, draft_status_id, duplicate_status_id in fork_rows:
        bind.execute(
            text(
                "INSERT INTO public.status_transitions "
                "(id, entity_type, tenant_id, from_status_id, to_status_id, label, sort_order) "
                "VALUES (:id, 'idea', :tenant_id, :from_id, :to_id, 'Vote with existing', 17)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "from_id": draft_status_id,
                "to_id": duplicate_status_id,
            },
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
