"""ems — Cluster F slice 3 (sprint-4/07): per-project payment connection.

Adds ``projects.payment_connection_id`` (AC-07-25) — NULL = fall back to the
tenant default payment connection. Backfill is implicit (NULL is the correct
"use the default" value for every existing project). Postgres only; SQLite tests
use create_all in conftest.

Revision ID: 0008_project_payment_conn
Revises: 0007_persona_rbac
Create Date: 2026-06-23
"""
from alembic import op

revision = "0008_project_payment_conn"
down_revision = "0007_persona_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE app_ems.projects "
        "ADD COLUMN IF NOT EXISTS payment_connection_id VARCHAR"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_projects_payment_connection_id "
        "ON app_ems.projects (payment_connection_id)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS app_ems.ix_projects_payment_connection_id")
    op.execute("ALTER TABLE app_ems.projects DROP COLUMN IF EXISTS payment_connection_id")
