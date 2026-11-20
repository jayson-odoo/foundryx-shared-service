"""ideation - add ``is_test`` to ``business_requirements`` (issue #90 W3,
owner ruling 26 Sep 2026 ~12:50Z).

A test idea (``ideas.is_test``, 0009) may now be promoted to a TEST Business
Requirement - this column mirrors it on ``business_requirements``, server-
derived only (never client input). Idempotent ``ADD COLUMN IF NOT EXISTS``
(same lesson as 0004/0009) - ``NOT NULL DEFAULT false`` so every
existing/real row backfills false.

Postgres-only DDL; a no-op on the SQLite test engine (per-module Alembic
runs only on Postgres - see ``app/module_platform/migrations.run_module_migrations``).

Revision ID: 0011_ideation_br_is_test
Revises: 0010_ideation_intake_contract
Create Date: 2026-09-26
"""
from alembic import op
from sqlalchemy import text

revision = "0011_ideation_br_is_test"
down_revision = "0010_ideation_intake_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(
        text(
            f'ALTER TABLE "{IDEATION_SCHEMA}".business_requirements '
            "ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(
        text(
            f'ALTER TABLE "{IDEATION_SCHEMA}".business_requirements '
            "DROP COLUMN IF EXISTS is_test"
        )
    )
