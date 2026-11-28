"""dashboards baseline - creates the ``app_dashboards`` tables.

Tables: dash_api_key, dash_api_audit, dash_dashboard, dash_share, dash_version,
dash_idempotency, dash_usage, dash_model_price. New tables only (additive); Postgres-only (per-module
Alembic is a no-op on the SQLite test engine).

Revision ID: 0001_dashboards_baseline
Revises:
Create Date: 2026-11-28
"""

from __future__ import annotations
from alembic import op

revision = "0001_dashboards_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import text

    from modules.dashboards.db import DASHBOARDS_SCHEMA, DashboardsBase
    from modules.dashboards import models  # noqa: F401

    bind = op.get_bind()
    bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{DASHBOARDS_SCHEMA}"'))
    DashboardsBase.metadata.create_all(bind=bind)


def downgrade() -> None:
    from modules.dashboards.db import DashboardsBase
    from modules.dashboards import models  # noqa: F401

    DashboardsBase.metadata.drop_all(bind=op.get_bind())
