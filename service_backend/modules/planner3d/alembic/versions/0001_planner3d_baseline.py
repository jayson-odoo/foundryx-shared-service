"""planner3d baseline - creates the ``app_planner3d`` tables.

Tables: p3_job, p3_job_file. Postgres-only (per-module Alembic is a no-op on
the SQLite test engine).

Revision ID: 0001_planner3d_baseline
Revises:
Create Date: 2026-11-26
"""

from __future__ import annotations
from alembic import op

revision = "0001_planner3d_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import text

    from modules.planner3d.db import PLANNER3D_SCHEMA, Planner3dBase
    from modules.planner3d import models  # noqa: F401

    bind = op.get_bind()
    bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{PLANNER3D_SCHEMA}"'))
    Planner3dBase.metadata.create_all(bind=bind)


def downgrade() -> None:
    from modules.planner3d.db import Planner3dBase
    from modules.planner3d import models  # noqa: F401

    Planner3dBase.metadata.drop_all(bind=op.get_bind())
