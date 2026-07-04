"""ems — project schedule columns to date-only (sprint-4/03 Slice 5).

An event's start/end/validity are calendar DATES, not instants — retype the 3
timestamptz columns to ``date`` (USING an explicit cast so any existing value
truncates cleanly). Postgres only; SQLite tests use create_all (already ``Date``).

Revision ID: 0002_project_dates_to_date
Revises: 0001_ems_baseline
Create Date: 2026-06-19
"""
from alembic import op

revision = "0002_project_dates_to_date"
down_revision = "0001_ems_baseline"
branch_labels = None
depends_on = None

_COLS = ("start_date", "end_date", "event_validity_end")


def upgrade() -> None:
    from sqlalchemy import text

    from modules.ems.db import EMS_SCHEMA

    bind = op.get_bind()
    for col in _COLS:
        bind.execute(
            text(
                f'ALTER TABLE "{EMS_SCHEMA}".projects '
                f"ALTER COLUMN {col} TYPE date USING ({col}::date)"
            )
        )


def downgrade() -> None:
    from sqlalchemy import text

    from modules.ems.db import EMS_SCHEMA

    bind = op.get_bind()
    for col in _COLS:
        bind.execute(
            text(
                f'ALTER TABLE "{EMS_SCHEMA}".projects '
                f"ALTER COLUMN {col} TYPE timestamptz USING ({col}::timestamptz)"
            )
        )
