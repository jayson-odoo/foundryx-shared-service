"""ideation - add ``is_test`` to ``ideas`` (owner ruling 24 Sep 2026, issue #1179).

A console/``--say`` ideation turn now calls the REAL intake tool instead of
returning a fixed placeholder, and marks the created row ``is_test = true`` so
it never reaches the board/list or a Business Requirement promotion by
default. Idempotent ``ADD COLUMN IF NOT EXISTS`` (same lesson as 0004) -
``NOT NULL DEFAULT false`` so every existing/real row backfills false.

Postgres-only DDL; a no-op on the SQLite test engine (per-module Alembic runs
only on Postgres - see ``app/module_platform/migrations.run_module_migrations``).

Revision ID: 0009_ideation_is_test
Revises: 0008_ideation_business_reqs
Create Date: 2026-09-24
"""
from alembic import op
from sqlalchemy import text

revision = "0009_ideation_is_test"
down_revision = "0008_ideation_business_reqs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(
        text(
            f'ALTER TABLE "{IDEATION_SCHEMA}".ideas '
            "ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(
        text(f'ALTER TABLE "{IDEATION_SCHEMA}".ideas DROP COLUMN IF EXISTS is_test')
    )
