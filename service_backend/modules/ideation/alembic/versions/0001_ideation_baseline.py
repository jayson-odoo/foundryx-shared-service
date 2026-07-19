"""ideation baseline (sprint-3/10 D3) — adopt per-module Alembic.

Captures the current ``app_ideation`` schema as rev 1. Existing DBs (tables
already built by the legacy ``create_all``) are STAMPED to this rev (no DDL);
fresh DBs run ``upgrade`` which builds the schema + tables here. Future ideation
schema changes get their own revisions chaining from this one.

Postgres-only DDL; a no-op on the SQLite test engine (per-module Alembic runs
only on Postgres — see ``app/module_platform/migrations.run_module_migrations``).

Revision ID: 0001_ideation_baseline
Revises:
Create Date: 2026-07-19
"""
from alembic import op

revision = "0001_ideation_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline = the current schema. Build it from the module's metadata so we
    # never hand-transcribe tables; fresh DBs get the exact create_all shape,
    # existing DBs are stamped (this body never runs for them).
    from sqlalchemy import text

    from modules.ideation.db import IDEATION_SCHEMA, IdeationBase

    bind = op.get_bind()
    bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{IDEATION_SCHEMA}"'))
    IdeationBase.metadata.create_all(bind=bind)


def downgrade() -> None:
    from modules.ideation.db import IdeationBase

    IdeationBase.metadata.drop_all(bind=op.get_bind())
