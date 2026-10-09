"""connector baseline - creates every ``app_connector`` table.

Tables: "oauth_clients", "pending_requests", "auth_codes", "tokens", "grants",
"assertion_jti", "call_log", "grant_events", "manifest_cache" (schema
app_connector). Existing DBs whose tables were built by the legacy create_all are
stamped to this rev (no DDL); fresh DBs build here. Postgres-only (per-module
Alembic is a no-op on the SQLite test engine).

Revision ID: 0001_connector_baseline
Revises:
Create Date: 2026-10-09
"""
from alembic import op

revision = "0001_connector_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import text

    from modules.connector.db import CONNECTOR_SCHEMA, ConnectorBase
    from modules.connector import models  # noqa: F401

    bind = op.get_bind()
    bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{CONNECTOR_SCHEMA}"'))
    ConnectorBase.metadata.create_all(bind=bind)


def downgrade() -> None:
    from modules.connector.db import ConnectorBase
    from modules.connector import models  # noqa: F401

    ConnectorBase.metadata.drop_all(bind=op.get_bind())
