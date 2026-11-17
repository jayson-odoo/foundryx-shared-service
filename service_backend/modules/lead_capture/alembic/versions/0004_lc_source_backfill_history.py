"""Backfill status + claim columns on lc_source + the lc_source_event History table
(lane L-B: AC-64-28 backfill, AC-64-38 History).

Additive only: two nullable columns and one new table. Existing sources keep
NULL (never run yet). Idempotent so a database whose tables came from
``create_all`` of the current models upgrades cleanly. Postgres-only.

Revision ID: 0004_lc_source_backfill_history
Revises: 0003_lc_source_routing_unique
Create Date: 2026-11-17
"""

from __future__ import annotations
from alembic import op

revision = "0004_lc_source_backfill_history"
down_revision = "0003_lc_source_routing_unique"
branch_labels = None
depends_on = None

_SCHEMA = '"app_lead_capture"'


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        f"ALTER TABLE {_SCHEMA}.lc_source ADD COLUMN IF NOT EXISTS backfill_last_run_at TIMESTAMPTZ"
    )
    bind.exec_driver_sql(
        f"ALTER TABLE {_SCHEMA}.lc_source ADD COLUMN IF NOT EXISTS backfill_last_error VARCHAR(500)"
    )
    bind.exec_driver_sql(
        f"ALTER TABLE {_SCHEMA}.lc_source ADD COLUMN IF NOT EXISTS backfill_started_at TIMESTAMPTZ"
    )
    bind.exec_driver_sql(
        f"""CREATE TABLE IF NOT EXISTS {_SCHEMA}.lc_source_event (
            id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            source_id VARCHAR NOT NULL REFERENCES {_SCHEMA}.lc_source (id),
            action VARCHAR(32) NOT NULL,
            actor_type VARCHAR(8) NOT NULL,
            actor_id VARCHAR,
            on_behalf_of_id VARCHAR,
            from_value VARCHAR(500),
            to_value VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""
    )
    bind.exec_driver_sql(
        f"CREATE INDEX IF NOT EXISTS ix_lc_source_event_source ON {_SCHEMA}.lc_source_event "
        "(tenant_id, source_id, created_at)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(f"DROP TABLE IF EXISTS {_SCHEMA}.lc_source_event")
    bind.exec_driver_sql(f"ALTER TABLE {_SCHEMA}.lc_source DROP COLUMN IF EXISTS backfill_started_at")
    bind.exec_driver_sql(f"ALTER TABLE {_SCHEMA}.lc_source DROP COLUMN IF EXISTS backfill_last_error")
    bind.exec_driver_sql(f"ALTER TABLE {_SCHEMA}.lc_source DROP COLUMN IF EXISTS backfill_last_run_at")
