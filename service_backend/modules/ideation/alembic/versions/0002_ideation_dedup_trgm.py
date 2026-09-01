"""ideation dedup - pg_trgm extension + GIN trigram index (AC-A-30).

Provisions ``CREATE EXTENSION IF NOT EXISTS pg_trgm`` and a GIN trigram index
(``gin_trgm_ops``) on the Idea dedup text (``lower(problem)``) so the deterministic
``create_idea`` dedup query (per ``(tenant, product)``) is index-accelerated. There
is **no ``vector`` extension and no ``embedding`` column** (D20 - shared-service
runs no embedding model).

Postgres-only; a graceful no-op on the SQLite test engine (per-module Alembic runs
only on Postgres - see ``app/module_platform/migrations.run_module_migrations`` -
and the provisioning helper itself guards the dialect).

Revision ID: 0002_ideation_dedup_trgm
Revises: 0001_ideation_baseline
Create Date: 2026-07-19
"""
from alembic import op

revision = "0002_ideation_dedup_trgm"
down_revision = "0001_ideation_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from modules.ideation.services.dedup import ensure_pg_trgm_index

    ensure_pg_trgm_index(op.get_bind())


def downgrade() -> None:
    from modules.ideation.db import IDEATION_SCHEMA

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    bind.execute(
        text(f'DROP INDEX IF EXISTS "{IDEATION_SCHEMA}".ix_ideas_problem_trgm')
    )
