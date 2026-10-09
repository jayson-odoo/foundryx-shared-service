"""autocount S5 review follow-ups - last-preview failed-count column

Plan 22 S5 review SHOULD-FIX 4b: ``ac_entity_config`` += ``last_preview_failed_count``
(Integer, nullable) - the last dry-run preview's genuinely-``failed`` prediction
count, so ``EtlService.activate_task`` can refuse activation when the last
preview reported failed rows (retryable rows stay allowed - a legitimate
dependency-order carry-over, AC-22-23).

Nullable, no NOT NULL, no computed backfill needed: NULL alongside a NULL
``last_preview_at`` means "never previewed" - the exact same semantics
``last_preview_at`` itself already carries for a pre-existing row, so a
pre-existing config lands here with nothing to fill in (existing tasks are
never retroactively blocked from activating; the new gate only ever
evaluates a preview taken AFTER this column exists).

Revision ID: 0009_autocount_s5_review   (24 chars <= 32)
Revises: 0008_autocount_etl_s2
Create Date: 2026-08-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_autocount_s5_review"
down_revision: Union[str, Sequence[str], None] = "0008_autocount_etl_s2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_entity_config"
COLUMN = "last_preview_failed_count"


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {col["name"] for col in inspector.get_columns(table, schema=SCHEMA)}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Existence-checked (0007/0008's own convention) - a create_all-first host
    # already has the column from the model.
    if COLUMN not in _columns(TABLE):
        op.add_column(
            TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True), schema=SCHEMA
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if COLUMN in _columns(TABLE):
        op.drop_column(TABLE, COLUMN, schema=SCHEMA)
