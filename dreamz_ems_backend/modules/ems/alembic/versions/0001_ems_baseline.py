"""ems baseline (sprint-3/11) — the app_ems schema + spine tables, rev 1.

ems starts clean under Alembic (never create_all in prod): a fresh DB runs this
upgrade to build the schema + all spine tables. Future ems schema changes chain
from here. (The orchestrator stamps if legacy tables somehow exist; ems has none.)

Revision ID: 0001_ems_baseline
Revises:
Create Date: 2026-06-16
"""
from alembic import op

revision = "0001_ems_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import text

    from modules.ems.db import EMS_SCHEMA, EmsBase

    bind = op.get_bind()
    bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{EMS_SCHEMA}"'))
    EmsBase.metadata.create_all(bind=bind)


def downgrade() -> None:
    from modules.ems.db import EmsBase

    EmsBase.metadata.drop_all(bind=op.get_bind())
