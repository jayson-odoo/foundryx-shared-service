"""autocount direct-DB ETL - the WHOLE plan-22 schema in one revision

One migration for every slice of plan 22 so later slices never stack a chain
of one-column revisions:

* ``ac_entity_config`` += ``source_config`` (JSON), ``etl_status`` (draft |
  active | paused, default ``draft``), ``activated_at``, ``next_incremental_at``
  + ``next_reconcile_at`` (indexed - the sweep's due query), ``last_run_error``.
* ``ac_company`` += ``sorento_company_code`` (nullable; Appendix A6 anchor).
* NEW ``ac_row_hash`` (tenant_id, company_id, entity_type, source_ref PK;
  row_hash; last_seen_at) - reconcile hash state, never row copies.
* ``ac_staged_record`` += ``op`` (default ``upsert``).
* ``ac_sync_run`` += ``mode`` (default ``manual``), ``rows_scanned``,
  ``deleted_count`` (``duration_ms`` already exists since 0002).

    !!  EXISTING ROWS NEED A REAL BACKFILL, NOT JUST A COLUMN DEFAULT.  !!

Every pre-plan-22 row must land on ``draft`` / ``upsert`` / ``manual`` / ``0``.
A ``server_default`` covers the ADD path, but a host where ``create_all`` ran
FIRST (``bootstrap_modules`` calls ``install()`` before ``run_module_migrations``)
already has the columns from the model - so the DDL is existence-checked AND
``backfill_etl_defaults`` runs unconditionally (correct in both orders, see
``backfill.py``). pytest sees neither path (conftest is pure ``create_all``,
module Alembic is a Postgres-only no-op): the backfill FUNCTION is unit-tested,
this wrapper is verified by a real ``alembic upgrade head`` against Postgres.

Revision ID: 0007_autocount_db_etl   (21 chars <= 32)
Revises: 0006_autocount_entity_backfill
Create Date: 2026-08-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns
from app.models.utc_datetime import UTCDateTime
from modules.autocount.backfill import backfill_etl_defaults

# Revision ids MUST be <= 32 chars - ``alembic_version.version_num`` is
# VARCHAR(32). "0007_autocount_db_etl" is 21.
revision: str = "0007_autocount_db_etl"
down_revision: Union[str, Sequence[str], None] = "0006_autocount_entity_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names(schema=SCHEMA))


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {col["name"] for col in inspector.get_columns(table, schema=SCHEMA)}


def _indexes(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table, schema=SCHEMA)}


def add_column(table: str, column: sa.Column) -> None:
    """Existence-checked ADD - a bare ``op.add_column`` below should be
    rejected on sight (see the module docstring)."""
    if column.name not in _columns(table):
        op.add_column(table, column, schema=SCHEMA)


def add_index(name: str, table: str, columns: list) -> None:
    if name not in _indexes(table) and set(columns) <= _columns(table):
        op.create_index(name, table, columns, unique=False, schema=SCHEMA)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # ── ac_entity_config: the task (plan 22 §2.4) ───────────────────────────
    add_column("ac_entity_config", sa.Column("source_config", sa.JSON(none_as_null=True), nullable=True))
    add_column(
        "ac_entity_config",
        sa.Column("etl_status", sa.String(), nullable=False, server_default="draft"),
    )
    add_column("ac_entity_config", sa.Column("activated_at", UTCDateTime(), nullable=True))
    add_column("ac_entity_config", sa.Column("next_incremental_at", UTCDateTime(), nullable=True))
    add_column("ac_entity_config", sa.Column("next_reconcile_at", UTCDateTime(), nullable=True))
    add_column("ac_entity_config", sa.Column("last_run_error", sa.Text(), nullable=True))
    add_index("ix_ac_entity_config_next_incremental_at", "ac_entity_config", ["next_incremental_at"])
    add_index("ix_ac_entity_config_next_reconcile_at", "ac_entity_config", ["next_reconcile_at"])

    # ── ac_company: Sorento company anchor (Appendix A6) ────────────────────
    add_column("ac_company", sa.Column("sorento_company_code", sa.String(), nullable=True))

    # ── ac_row_hash: reconcile state (plan 22 §2.5) ─────────────────────────
    if "ac_row_hash" not in _tables():
        op.create_table(
            "ac_row_hash",
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("source_ref", sa.String(), nullable=False),
            sa.Column("row_hash", sa.String(), nullable=False),
            sa.Column(
                "last_seen_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            sa.PrimaryKeyConstraint("tenant_id", "company_id", "entity_type", "source_ref"),
            schema=SCHEMA,
        )
    add_index("ix_ac_row_hash_scope", "ac_row_hash", ["tenant_id", "company_id", "entity_type"])

    # ── ac_staged_record: delete intents ride staging (plan 22 §2.5) ────────
    add_column(
        "ac_staged_record",
        sa.Column("op", sa.String(), nullable=False, server_default="upsert"),
    )

    # ── ac_sync_run: run-history cost columns (plan 22 §2.7) ────────────────
    add_column(
        "ac_sync_run", sa.Column("mode", sa.String(), nullable=False, server_default="manual")
    )
    add_column(
        "ac_sync_run",
        sa.Column("rows_scanned", sa.Integer(), nullable=False, server_default="0"),
    )
    add_column(
        "ac_sync_run",
        sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
    )
    add_column("ac_sync_run", sa.Column("duration_ms", sa.Integer(), nullable=True))

    # Runs on BOTH orderings: a no-op after the ADDs (server defaults filled the
    # rows), the only thing that fills them on a create_all-first host.
    backfill_etl_defaults(bind, schema=SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, columns, indexes in (
        (
            "ac_sync_run",
            ("deleted_count", "rows_scanned", "mode"),
            (),
        ),
        ("ac_staged_record", ("op",), ()),
        ("ac_company", ("sorento_company_code",), ()),
        (
            "ac_entity_config",
            (
                "last_run_error",
                "next_reconcile_at",
                "next_incremental_at",
                "activated_at",
                "etl_status",
                "source_config",
            ),
            ("ix_ac_entity_config_next_reconcile_at", "ix_ac_entity_config_next_incremental_at"),
        ),
    ):
        existing_indexes = _indexes(table)
        for index in indexes:
            if index in existing_indexes:
                op.drop_index(index, table_name=table, schema=SCHEMA)
        existing = _columns(table)
        for column in columns:
            if column in existing:
                op.drop_column(table, column, schema=SCHEMA)
    if "ac_row_hash" in _tables():
        op.drop_table("ac_row_hash", schema=SCHEMA)
