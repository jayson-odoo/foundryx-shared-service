"""ideation - canny-style card fields + field-level merge snapshot (plan 20).

Adds to ``app_ideation.ideas`` (all nullable, additive):

- ``desired_outcome`` TEXT, ``use_cases`` JSON (list of str),
  ``current_workaround`` TEXT - the card fields (owner ruling 13 Oct).
- ``merge_snapshot_json`` JSON - on an absorbed child, the survivor field
  values a field-level merge replaced, so unmerge can restore them.

No backfill: old ideas have no source for these fields; they show empty by
design. ``proposed_solution`` / ``impact`` / ``department`` are untouched (hidden
in the UI, data kept). Idempotent ``IF NOT EXISTS`` DDL; Postgres-only, a no-op
on the SQLite test engine (the suite uses ``create_all``).

Revision ID: 0017_ideation_canny_fields
Revises: 0016_ideation_own_ideas
Create Date: 2026-10-13
"""
from alembic import op
from sqlalchemy import text

revision = "0017_ideation_canny_fields"
down_revision = "0016_ideation_own_ideas"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("desired_outcome", "TEXT"),
    ("use_cases", "JSON"),
    ("current_workaround", "TEXT"),
    ("merge_snapshot_json", "JSON"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    for col, sql_type in _COLUMNS:
        bind.execute(
            text(
                f'ALTER TABLE "{IDEATION_SCHEMA}".ideas '
                f"ADD COLUMN IF NOT EXISTS {col} {sql_type} NULL"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    for col, _ in reversed(_COLUMNS):
        bind.execute(
            text(f'ALTER TABLE "{IDEATION_SCHEMA}".ideas DROP COLUMN IF EXISTS {col}')
        )
