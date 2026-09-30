"""BR "Send to build" - build repo on the delivery config, the three build tables
and the BR status re-sort.

Plan: ``documentation/plans/ideation/PLAN-ideation-br-send-to-build.md`` 3.1.

1. ``product_delivery.build_repo`` (nullable ``owner/repo``).
2. ``br_builds`` (one row per BR, ``business_requirement_id`` UNIQUE = the
   idempotency anchor), ``br_build_events`` (append-only Trace; ``seq`` SERIAL is
   the ordering cursor, ``created_at`` defaults to ``clock_timestamp()``) and
   ``br_build_keys`` (write-back keys, sha256 + 8-char prefix).
3. Data step: ``sent_to_build`` takes sort 4, so ``in_fr``/``delivered``/
   ``archived`` shift to 5/6/7 on the module-seeded platform-tier rows of
   ``public.statuses`` (the status engine's own seed data - a frozen
   ``sa.table``, never the live ORM model). The new status + edges themselves
   land via ``seed_br_statuses`` at bootstrap (insert-if-missing).

Idempotent (``IF NOT EXISTS``). Postgres-only DDL; a no-op on the SQLite test
engine (the suite builds the same schema via ``IdeationBase.metadata.create_all``).

Revision ID: 0014_ideation_br_build
Revises: 0013_ideation_attachment_upload
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0014_ideation_br_build"
down_revision = "0013_ideation_attachment_upload"
branch_labels = None
depends_on = None

_BR_ENTITY = "ideation_business_requirement"
_NEW_SORT = {"in_fr": 5, "delivered": 6, "archived": 7}
_OLD_SORT = {"in_fr": 4, "delivered": 5, "archived": 6}


def _resort(bind, mapping) -> None:
    statuses = sa.table(
        "statuses",
        sa.column("entity_type", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("key", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    for key, sort_order in mapping.items():
        bind.execute(
            sa.update(statuses)
            .where(
                statuses.c.entity_type == _BR_ENTITY,
                statuses.c.tenant_id.is_(None),
                statuses.c.key == key,
            )
            .values(sort_order=sort_order)
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    schema = IDEATION_SCHEMA

    # ---- 1. product_delivery.build_repo ----
    bind.execute(
        text(
            f'ALTER TABLE "{schema}".product_delivery '
            "ADD COLUMN IF NOT EXISTS build_repo VARCHAR NULL"
        )
    )

    # ---- 2. br_builds ----
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{schema}".br_builds ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            "  business_requirement_id VARCHAR NOT NULL,"
            "  repo VARCHAR NOT NULL,"
            "  state VARCHAR NOT NULL,"
            "  issue_number INTEGER NULL,"
            "  issue_url TEXT NULL,"
            "  issue_node_id VARCHAR NULL,"
            "  sent_by VARCHAR NULL,"
            "  sent_at TIMESTAMPTZ NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  CONSTRAINT uq_br_builds_br UNIQUE (business_requirement_id)"
            ")"
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_br_builds_tenant_id "
            f'ON "{schema}".br_builds (tenant_id)'
        )
    )

    # ---- br_build_events ----
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{schema}".br_build_events ('
            "  seq SERIAL PRIMARY KEY,"
            "  id VARCHAR NOT NULL,"
            "  tenant_id VARCHAR NOT NULL,"
            "  business_requirement_id VARCHAR NOT NULL,"
            "  kind VARCHAR NOT NULL,"
            "  stage VARCHAR(40) NOT NULL,"
            "  message TEXT NOT NULL,"
            "  pr_url TEXT NULL,"
            "  handtest_url TEXT NULL,"
            "  status VARCHAR NULL,"
            "  actor_user_id VARCHAR NULL,"
            "  key_id VARCHAR NULL,"
            "  status_moved BOOLEAN NOT NULL DEFAULT false,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),"
            "  CONSTRAINT uq_br_build_events_id UNIQUE (id)"
            ")"
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_br_build_events_tenant_id "
            f'ON "{schema}".br_build_events (tenant_id)'
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_br_build_events_business_requirement_id "
            f'ON "{schema}".br_build_events (business_requirement_id)'
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_br_build_events_tenant_br_seq "
            f'ON "{schema}".br_build_events (tenant_id, business_requirement_id, seq)'
        )
    )

    # ---- br_build_keys ----
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{schema}".br_build_keys ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            "  name VARCHAR NOT NULL DEFAULT '',"
            "  key_prefix VARCHAR NOT NULL,"
            "  key_hash VARCHAR NOT NULL,"
            "  last_used_at TIMESTAMPTZ NULL,"
            "  revoked_at TIMESTAMPTZ NULL,"
            "  created_by VARCHAR NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_br_build_keys_tenant_id "
            f'ON "{schema}".br_build_keys (tenant_id)'
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_br_build_keys_key_prefix "
            f'ON "{schema}".br_build_keys (key_prefix)'
        )
    )

    # ---- 3. BR status re-sort (frozen table, module-seeded platform rows) ----
    _resort(bind, _NEW_SORT)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    schema = IDEATION_SCHEMA

    _resort(bind, _OLD_SORT)
    bind.execute(text(f'DROP TABLE IF EXISTS "{schema}".br_build_keys'))
    bind.execute(text(f'DROP TABLE IF EXISTS "{schema}".br_build_events'))
    bind.execute(text(f'DROP TABLE IF EXISTS "{schema}".br_builds'))
    bind.execute(
        text(f'ALTER TABLE "{schema}".product_delivery DROP COLUMN IF EXISTS build_repo')
    )
