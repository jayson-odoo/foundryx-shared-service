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
    # Review round 1 NIT #9 - the model declares `index=True` on this column;
    # this hand-written migration must provision the same index (autogenerate
    # is not used here), matching SQLAlchemy's default `ix_<table>_<col>` name.
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_idea_votes_origin_idea_id "
            f'ON "{schema}".idea_votes (origin_idea_id)'
        )
    )

    # ---- 3. idea_status_events (section 7.1) ----
    # `created_at` defaults to `clock_timestamp()` (review round 1 #6) - the
    # real wall clock at INSERT time, unlike `now()` which is fixed for the
    # whole transaction (a merge/unmerge writing several rows in one commit
    # would otherwise stamp them all identically, defeating the settle
    # window's per-row cursor precision). Postgres-only DDL, so this is safe
    # here (the SQLAlchemy model uses a Python-side default instead, for the
    # SQLite test engine's `create_all` path - see `modules/ideation/models.py`).
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
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),"
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
    # Review round 1 NIT #9 - the model also declares `index=True` on
    # `tenant_id` and `idea_id` individually (in addition to the composite
    # above); provision those too so a migrated database matches `create_all`.
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_idea_status_events_tenant_id "
            f'ON "{schema}".idea_status_events (tenant_id)'
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_idea_status_events_idea_id "
            f'ON "{schema}".idea_status_events (idea_id)'
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

    # `DROP TABLE`/column drops automatically drop indexes defined solely on
    # the dropped column/table (Postgres CASCADE-by-dependency) - only the
    # standalone `ix_ideas_merged_into_id` (on the pre-existing `ideas`
    # table, which is NOT dropped) needs an explicit drop. Schema-qualified
    # (review round 1 NIT #9) - an index name is schema-scoped too; a bare
    # name risks missing it (or hitting a same-named index elsewhere) when
    # `search_path` doesn't include this module's schema.
    bind.execute(text(f'DROP TABLE IF EXISTS "{schema}".idea_status_events'))
    bind.execute(
        text(f'ALTER TABLE "{schema}".idea_votes DROP COLUMN IF EXISTS origin_idea_id')
    )
    bind.execute(text(f'DROP INDEX IF EXISTS "{schema}".ix_ideas_merged_into_id'))
    bind.execute(
        text(f'ALTER TABLE "{schema}".ideas DROP COLUMN IF EXISTS merged_at')
    )
    bind.execute(
        text(f'ALTER TABLE "{schema}".ideas DROP COLUMN IF EXISTS merged_into_id')
    )
