"""ideation — add segregated intake columns to ``ideas``.

Promote the captured intake answers to first-class Idea columns so the operator
surface + serializer read them directly (not lumped as problem + raw notes):
``proposed_solution`` / ``impact`` (Text) and ``department`` (String). All
nullable — they fill in as the intake collects them; ``problem`` stays the
required headline.

Idempotent ``ADD COLUMN IF NOT EXISTS`` because the live DB's ``app_ideation``
tables predate module Alembic (built by ``create_all``, stamped at baseline), so
the columns may already have been added out-of-band before this revision runs.

Postgres-only DDL; a no-op on the SQLite test engine (per-module Alembic runs
only on Postgres — see ``app/module_platform/migrations.run_module_migrations``).

Revision ID: 0004_ideation_segregated
Revises: 0003_ideation_submitter
Create Date: 2026-07-19
"""
from alembic import op
from sqlalchemy import text

revision = "0004_ideation_segregated"
down_revision = "0003_ideation_submitter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    for col, ddl_type in (
        ("proposed_solution", "TEXT"),
        ("impact", "TEXT"),
        ("department", "VARCHAR"),
    ):
        bind.execute(
            text(
                f'ALTER TABLE "{IDEATION_SCHEMA}".ideas '
                f"ADD COLUMN IF NOT EXISTS {col} {ddl_type}"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    for col in ("department", "impact", "proposed_solution"):
        bind.execute(
            text(f'ALTER TABLE "{IDEATION_SCHEMA}".ideas DROP COLUMN IF EXISTS {col}')
        )
