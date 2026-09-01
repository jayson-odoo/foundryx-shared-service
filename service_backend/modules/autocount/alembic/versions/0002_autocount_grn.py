"""autocount GRN read pipeline - companies, config, watermarks, mappings, staging

Creates the slice-1 persistence model (plan §7) inside the module's own schema
``app_autocount``. Core ``public`` is NEVER touched by a module migration.

Every table carries ``tenant_id`` AND ``company_id`` (AC-13-41); cross-schema
references to core (``connections.id``, ``background_jobs.id``) are plain
INDEXED columns, never DB-level FKs (BL-030).

No backfill is needed: every table here is new in this revision, so no existing
row can be stranded without a value.

    !!  IDEMPOTENT BY NECESSITY, NOT BY TASTE.  !!

``bootstrap_modules`` runs each module's ``install()`` - which is ``create_all``
- BEFORE ``run_module_migrations``. So on a deployment already stamped at 0001,
``create_all`` builds these tables and THEN Alembic runs this revision, which
would explode with ``DuplicateTable``. pytest never sees it (conftest is pure
``create_all``, and module Alembic is a Postgres-only no-op), so it would
surface for the first time on a real deploy. Hence every create below is
existence-checked - the same fix the ideation module needed for the same
ordering.

Revision ID: 0002_autocount_grn
Revises: 0001_autocount_baseline
Create Date: 2026-07-21
"""
from typing import Any, List, Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision ids MUST be <= 32 chars - ``alembic_version.version_num`` is
# VARCHAR(32). A longer id passes the create_all test suite and then breaks
# every real Postgres deploy.
revision: str = "0002_autocount_grn"
down_revision: Union[str, Sequence[str], None] = "0001_autocount_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


# ── idempotent DDL helpers (see the module docstring) ─────────────────────────


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names(schema=SCHEMA))


def _indexes(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table, schema=SCHEMA)}


#     !!  THESE GUARDS ARE NOT COVERED BY pytest - AND STRUCTURALLY CANNOT BE.  !!
#
# conftest builds the schema with ``create_all`` and module Alembic is a
# Postgres-only NO-OP, so NOTHING in the test suite ever executes this file.
# A green suite therefore says exactly nothing about it: an unguarded
# ``op.create_table`` here passes every test and then dies with
# ``DuplicateTable`` on the first real deploy already stamped at 0001 (where
# ``bootstrap_modules`` ran ``install()``/``create_all`` BEFORE the migration).
#
# So the ONLY gate on this file is CODE REVIEW plus a manual
# ``alembic upgrade head`` against live Postgres. Every create in this revision
# must go through ``make_table``/``make_index`` - a reviewer seeing a bare
# ``op.create_table``/``op.create_index`` below should reject it on sight.


def make_table(name: str, *columns: Any) -> None:
    if name not in _tables():
        op.create_table(name, *columns, schema=SCHEMA)


def make_index(name: str, table: str, columns: List[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, schema=SCHEMA)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
    )


def upgrade() -> None:
    make_table(
        "ac_company",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("connection_id", sa.String(), nullable=False),
        sa.Column("database_name", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False, server_default=""),
        sa.Column("name", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        _created_at(),
        _updated_at(),
        # The REAL company-identity guard. Core's uq_connection_tenant_provider
        # was carved out for `erp` precisely so this owns it (D16/D17).
        sa.UniqueConstraint(
            "tenant_id", "database_name", name="uq_ac_company_tenant_db"
        ),
    )
    make_index("ix_ac_company_tenant", "ac_company", ["tenant_id"])
    make_index("ix_ac_company_connection", "ac_company", ["connection_id"])

    make_table(
        "ac_entity_config",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("sync_mode", sa.String(), nullable=False, server_default="MANUAL"),
        sa.Column(
            "source_impl", sa.String(), nullable=False, server_default="autocount_read"
        ),
        sa.Column("record_cap", sa.Integer(), nullable=False, server_default="200"),
        sa.Column(
            "initial_lookback_days", sa.Integer(), nullable=False, server_default="30"
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint(
            "tenant_id", "company_id", "entity_type", name="uq_ac_entity_config"
        ),
    )
    make_index(
        "ix_ac_entity_config_scope", "ac_entity_config", ["tenant_id", "company_id"]
    )

    make_table(
        "ac_watermark",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("last_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_json", sa.JSON(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint(
            "tenant_id", "company_id", "entity_type", name="uq_ac_watermark"
        ),
    )
    make_index("ix_ac_watermark_scope", "ac_watermark", ["tenant_id", "company_id"])

    make_table(
        "ac_field_mapping",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False, server_default="header"),
        sa.Column("source_path", sa.String(), nullable=False),
        sa.Column("canonical_field", sa.String(), nullable=False),
        sa.Column("transform", sa.String(), nullable=False, server_default="string"),
        sa.Column(
            "is_required", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "is_source_owned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint(
            "tenant_id",
            "company_id",
            "entity_type",
            "scope",
            "canonical_field",
            name="uq_ac_field_mapping",
        ),
    )
    make_index(
        "ix_ac_field_mapping_scope",
        "ac_field_mapping",
        ["tenant_id", "company_id", "entity_type"],
    )

    make_table(
        "ac_staged_record",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("doc_no", sa.String(), nullable=True),
        sa.Column("source_last_modified", sa.DateTime(timezone=True), nullable=True),
        # Raw payload retained for debugging + retroactive re-mapping (AC-13-07).
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("canonical_json", sa.JSON(), nullable=True),
        sa.Column("diff_json", sa.JSON(), nullable=True),
        sa.Column("errors_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="STAGED"),
        sa.Column("error", sa.Text(), nullable=True),
        _created_at(),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
    )
    make_index(
        "ix_ac_staged_scope",
        "ac_staged_record",
        ["tenant_id", "company_id", "entity_type"],
    )
    make_index("ix_ac_staged_job", "ac_staged_record", ["tenant_id", "job_id"])
    make_index(
        "ix_ac_staged_ref", "ac_staged_record", ["tenant_id", "company_id", "source_ref"]
    )

    make_table(
        "ac_sync_run",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("window_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("staged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pushed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        # True when the record cap was hit - a truncated sync must NEVER read as
        # a complete one (AC-13-46).
        sa.Column(
            "truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("watermark_advanced_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    make_index(
        "ix_ac_sync_run_scope", "ac_sync_run", ["tenant_id", "company_id", "entity_type"]
    )
    make_index("ix_ac_sync_run_job", "ac_sync_run", ["tenant_id", "job_id"])


def downgrade() -> None:
    existing = _tables()
    for table in (
        "ac_sync_run",
        "ac_staged_record",
        "ac_field_mapping",
        "ac_watermark",
        "ac_entity_config",
        "ac_company",
    ):
        if table in existing:
            op.drop_table(table, schema=SCHEMA)
