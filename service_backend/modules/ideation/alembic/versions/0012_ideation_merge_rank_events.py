"""ideation round 2 (issue #94) - merge/unmerge columns, requester status-event
feed table, priority backfill.

Plan: ``documentation/plans/ideation/PLAN-ideation-round-2-merge-unmerge.md``
section 9.

1. ``ideas.merged_into_id`` (D1 - plain indexed VARCHAR, **NO FK**: a FK on the
   hot ``ideas`` table would take a lock that hangs a blue/green deploy behind
   any live connection touching ``ideas``, the same BL-030 lesson as
   ``idea_business_requirements.idea_id`` in migration 0008) + ``merged_at``.
2. ``idea_votes.origin_idea_id`` (D4 - NULL = the vote was cast on this idea;
   set = the vote moved here from a merged member).
3. ``idea_status_events`` (section 7.1/S4) - the requester status-update event
   feed the CRM pulls. ``seq`` is the feed cursor (Postgres SERIAL, insert
   order); ``id`` is the payload's stable ``event_id``.
4. Backfill: dense 1-based ``priority`` per ``(tenant_id, is_test)`` lane,
   ordered exactly as today's visible order (``priority`` ascending ties
   broken newest-first) so the backfill never reshuffles what an operator
   already sees (plan section 5 root-cause fix).

Idempotent (``ADD COLUMN IF NOT EXISTS`` / ``CREATE TABLE IF NOT EXISTS`` /
``CREATE INDEX IF NOT EXISTS``, same lesson as 0004/0007/0009/0011).
Postgres-only DDL; a no-op on the SQLite test engine (the test suite creates
the matching columns/table via ``IdeationBase.metadata.create_all`` - see
``modules/ideation/models.py``).

Revision ID: 0012_ideation_merge_rank_events
Revises: 0011_ideation_br_is_test
Create Date: 2026-09-28
"""
from alembic import op
from sqlalchemy import text

revision = "0012_ideation_merge_rank_events"
down_revision = "0011_ideation_br_is_test"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    schema = IDEATION_SCHEMA

    # ---- 1. ideas.merged_into_id / merged_at (D1) ----
    bind.execute(
        text(
            f'ALTER TABLE "{schema}".ideas '
            "ADD COLUMN IF NOT EXISTS merged_into_id VARCHAR NULL"
        )
    )
    bind.execute(
        text(
            f'ALTER TABLE "{schema}".ideas '
            "ADD COLUMN IF NOT EXISTS merged_at TIMESTAMPTZ NULL"
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ideas_merged_into_id "
            f'ON "{schema}".ideas (merged_into_id)'
        )
    )

    # ---- 2. idea_votes.origin_idea_id (D4) ----
    bind.execute(
        text(
            f'ALTER TABLE "{schema}".idea_votes '
            "ADD COLUMN IF NOT EXISTS origin_idea_id VARCHAR NULL"
        )
    )

    # ---- 3. idea_status_events (section 7.1) ----
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{schema}".idea_status_events ('
            "  seq SERIAL PRIMARY KEY,"
            "  id VARCHAR NOT NULL,"
            "  tenant_id VARCHAR NOT NULL,"
            "  idea_id VARCHAR NOT NULL,"
            "  kind VARCHAR NOT NULL,"
            "  is_test BOOLEAN NOT NULL DEFAULT false,"
            "  payload_json JSON NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  CONSTRAINT uq_idea_status_events_id UNIQUE (id)"
            ")"
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_idea_status_events_tenant_seq "
            f'ON "{schema}".idea_status_events (tenant_id, seq)'
        )
    )

    # ---- 4. Priority backfill (dense, order-preserving) ----
    bind.execute(
        text(
            f'UPDATE "{schema}".ideas AS i SET priority = ranked.rn '
            "FROM ("
            "  SELECT id, ROW_NUMBER() OVER ("
            "    PARTITION BY tenant_id, is_test "
            "    ORDER BY priority ASC, created_at DESC, id DESC"
            "  ) AS rn"
            f'  FROM "{schema}".ideas'
            ") AS ranked "
            "WHERE i.id = ranked.id"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    schema = IDEATION_SCHEMA

    bind.execute(text(f'DROP TABLE IF EXISTS "{schema}".idea_status_events'))
    bind.execute(
        text(f'ALTER TABLE "{schema}".idea_votes DROP COLUMN IF EXISTS origin_idea_id')
    )
    bind.execute(text("DROP INDEX IF EXISTS ix_ideas_merged_into_id"))
    bind.execute(
        text(f'ALTER TABLE "{schema}".ideas DROP COLUMN IF EXISTS merged_at')
    )
    bind.execute(
        text(f'ALTER TABLE "{schema}".ideas DROP COLUMN IF EXISTS merged_into_id')
    )
