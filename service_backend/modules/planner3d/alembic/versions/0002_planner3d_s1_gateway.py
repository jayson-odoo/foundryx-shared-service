"""planner3d S1 gateway - keys, audit, uploads, receivers, deliveries + p3_job
idempotency columns. Additive only, idempotent (IF NOT EXISTS / checkfirst).

Revision ID: 0002_planner3d_s1_gateway
Revises: 0001_planner3d_baseline
Create Date: 2026-11-27
"""

from __future__ import annotations
from alembic import op

revision = "0002_planner3d_s1_gateway"
down_revision = "0001_planner3d_baseline"
branch_labels = None
depends_on = None

NEW_TABLES = ("p3_api_key", "p3_api_audit", "p3_upload", "p3_receiver", "p3_delivery")


def upgrade() -> None:
    from sqlalchemy import text

    from modules.planner3d import models  # noqa: F401
    from modules.planner3d.db import PLANNER3D_SCHEMA, Planner3dBase

    bind = op.get_bind()
    s = PLANNER3D_SCHEMA
    bind.execute(text(f'ALTER TABLE "{s}".p3_job ADD COLUMN IF NOT EXISTS api_key_id VARCHAR'))
    bind.execute(text(f'ALTER TABLE "{s}".p3_job ADD COLUMN IF NOT EXISTS idempotency_ref VARCHAR(128)'))
    bind.execute(text(f'ALTER TABLE "{s}".p3_job ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64)'))
    bind.execute(
        text(f'CREATE UNIQUE INDEX IF NOT EXISTS uq_p3_job_idempotency ON "{s}".p3_job (tenant_id, idempotency_ref)')
    )
    tables = [Planner3dBase.metadata.tables[f"{s}.{name}"] for name in NEW_TABLES]
    Planner3dBase.metadata.create_all(bind=bind, tables=tables, checkfirst=True)


def downgrade() -> None:
    from sqlalchemy import text

    from modules.planner3d import models  # noqa: F401
    from modules.planner3d.db import PLANNER3D_SCHEMA, Planner3dBase

    bind = op.get_bind()
    s = PLANNER3D_SCHEMA
    tables = [Planner3dBase.metadata.tables[f"{s}.{name}"] for name in NEW_TABLES]
    Planner3dBase.metadata.drop_all(bind=bind, tables=tables, checkfirst=True)
    bind.execute(text(f'DROP INDEX IF EXISTS "{s}".uq_p3_job_idempotency'))
    for col in ("request_hash", "idempotency_ref", "api_key_id"):
        bind.execute(text(f'ALTER TABLE "{s}".p3_job DROP COLUMN IF EXISTS {col}'))
