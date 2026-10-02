"""autocount direct-DB ETL S2 - task lifecycle + run-history columns

Columns plan 22 S2 needs that 0007 did not carry:

* ``ac_entity_config`` += ``last_run_error_code`` (task-level Sorento anchor
  code, Appendix A6/A7), ``result_columns`` (JSON - the validation preview's
  column names, stored at PUT), ``last_preview_at`` (the activate-once gate,
  AC-22-18), ``last_run_at``.
* ``ac_sync_run`` += ``added_count`` + ``updated_count`` (hash-diff
  classification, AC-22-17), ``skip_reason`` (overlap-skipped ticks,
  AC-22-14); ``job_id`` becomes NULLABLE (a skipped tick never enqueues).

Same two-order discipline as 0007: every ADD is existence-checked (a
create_all-first host already has the columns from the model) and the shared
``backfill_etl_defaults`` runs unconditionally so pre-existing run rows land
on zero counters in both orders. All columns here are nullable or
server-defaulted - no NOT NULL without a fill.

Revision ID: 0008_autocount_etl_s2   (20 chars <= 32)
Revises: 0007_autocount_db_etl
Create Date: 2026-08-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns
from app.models.utc_datetime import UTCDateTime
from modules.autocount.backfill import backfill_etl_defaults

revision: str = "0008_autocount_etl_s2"
down_revision: Union[str, Sequence[str], None] = "0007_autocount_db_etl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {col["name"] for col in inspector.get_columns(table, schema=SCHEMA)}


def add_column(table: str, column: sa.Column) -> None:
    """Existence-checked ADD (see 0007's docstring - a bare ``op.add_column``
    here should be rejected on sight)."""
    if column.name not in _columns(table):
        op.add_column(table, column, schema=SCHEMA)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # ── ac_entity_config: lifecycle + editor state (plan 22 S2) ─────────────
    add_column("ac_entity_config", sa.Column("last_run_error_code", sa.String(), nullable=True))
    add_column(
        "ac_entity_config",
        sa.Column("result_columns", sa.JSON(none_as_null=True), nullable=True),
    )
    add_column("ac_entity_config", sa.Column("last_preview_at", UTCDateTime(), nullable=True))
    add_column("ac_entity_config", sa.Column("last_run_at", UTCDateTime(), nullable=True))

    # ── ac_sync_run: hash-diff counters + skip bookkeeping (AC-22-17) ───────
    add_column(
        "ac_sync_run",
        sa.Column("added_count", sa.Integer(), nullable=False, server_default="0"),
    )
    add_column(
        "ac_sync_run",
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
    )
    add_column("ac_sync_run", sa.Column("skip_reason", sa.Text(), nullable=True))
    # A skipped tick records a run row with NO job (AC-22-14). Idempotent -
    # dropping an already-absent NOT NULL is a no-op via the guard.
    inspector = sa.inspect(bind)
    for col in inspector.get_columns("ac_sync_run", schema=SCHEMA):
        if col["name"] == "job_id" and not col["nullable"]:
            op.alter_column(
                "ac_sync_run",
                "job_id",
                existing_type=sa.String(),
                nullable=True,
                schema=SCHEMA,
            )

    # Correct in both orders (see 0007): a no-op after the ADDs, the only
    # thing that fills counters on a create_all-first host.
    backfill_etl_defaults(bind, schema=SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    existing = _columns("ac_sync_run")
    for column in ("skip_reason", "updated_count", "added_count"):
        if column in existing:
            op.drop_column("ac_sync_run", column, schema=SCHEMA)
    existing = _columns("ac_entity_config")
    for column in ("last_run_at", "last_preview_at", "result_columns", "last_run_error_code"):
        if column in existing:
            op.drop_column("ac_entity_config", column, schema=SCHEMA)
    # job_id nullability is left as-is on downgrade (rows may hold NULLs).
