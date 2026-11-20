"""Connect sessions for the hosted wizard + allowed origins on gateway keys
(lane L-C: AC-64-06/07/20).

Additive only: one nullable column on ``lc_api_key`` (NULL = the key may not
open connect sessions until its origins are set, the safe default for keys
issued before this lane) and one new table. Idempotent so a database whose
tables came from ``create_all`` of the current models upgrades cleanly.
Postgres-only.

Revision ID: 0005_lc_connect_session
Revises: 0004_lc_source_backfill_history
Create Date: 2026-11-17
"""

from __future__ import annotations
from alembic import op

revision = "0005_lc_connect_session"
down_revision = "0004_lc_source_backfill_history"
branch_labels = None
depends_on = None

_SCHEMA = '"app_lead_capture"'


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(f"ALTER TABLE {_SCHEMA}.lc_api_key ADD COLUMN IF NOT EXISTS allowed_origins_json JSON")
    bind.exec_driver_sql(
        f"""CREATE TABLE IF NOT EXISTS {_SCHEMA}.lc_connect_session (
            id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            kind VARCHAR(16) NOT NULL,
            key_id VARCHAR,
            user_id VARCHAR,
            return_origin VARCHAR(255),
            source_id VARCHAR,
            token_hash VARCHAR(64) UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            meta_encrypted TEXT,
            meta_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""
    )
    bind.exec_driver_sql(
        f"CREATE INDEX IF NOT EXISTS ix_lc_connect_session_tenant ON {_SCHEMA}.lc_connect_session (tenant_id)"
    )
    bind.exec_driver_sql(
        f"CREATE INDEX IF NOT EXISTS ix_lc_connect_session_expires ON {_SCHEMA}.lc_connect_session (expires_at)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(f"DROP TABLE IF EXISTS {_SCHEMA}.lc_connect_session")
    bind.exec_driver_sql(f"ALTER TABLE {_SCHEMA}.lc_api_key DROP COLUMN IF EXISTS allowed_origins_json")
