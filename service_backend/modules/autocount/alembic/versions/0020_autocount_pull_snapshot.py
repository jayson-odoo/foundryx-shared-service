"""Human-invoked pull: delivery mode + the snapshot store (sprint-5/10 §2.1/
§2.4, AC-10-10/18).

* ``ac_entity_config`` += ``delivery_mode`` (``push`` | ``pull``, NOT NULL,
  ``server_default 'push'``) - every existing task reads ``push`` and
  behaves exactly as it does today. ``backfill_delivery_mode_defaults``
  covers the create_all-first host (correct ADD ordering already carries
  every existing row via the server default; the backfill is the
  belt-and-braces sweep every sibling column in this module ships with).
* NEW ``ac_pull_snapshot`` / ``ac_pull_snapshot_row`` - the immutable
  extraction store (AC-10-18/19). No FK between them (BL-030 - a
  within-schema reference is still a plain indexed column here, matching
  every other cross-row reference in this module); the repository is the
  only writer either way.

Revision ID: 0020_autocount_pull_snapshot   (29 chars <= 32)
Revises: 0019_autocount_so_ref
Create Date: 2026-09-20

Both this revision and its child, 0021, were amended IN PLACE at least once
before either ever shipped (this file's own SHOULD-FIX 4 partial-unique-index
addition, then 0021's review round 2 ``ac_pull_audit.created_at`` index) - the
only stamped host at every amendment was the lane Postgres
(``foundryx_service_s40``), re-verified each time with a downgrade-then-
upgrade against it. Amend in place while unreleased; add a new revision only
once a migration has actually shipped.
"""
from typing import Any, List, Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns
from app.models.utc_datetime import UTCDateTime
from modules.autocount.backfill import backfill_delivery_mode_defaults

revision: str = "0020_autocount_pull_snapshot"
down_revision: Union[str, Sequence[str], None] = "0019_autocount_so_ref"
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
    """Existence-checked ADD (module Alembic house rule, see 0007's own
    ``add_column``): a create_all-first host already has this column from
    ``models.py`` before this migration ever runs - a bare ``op.add_column``
    would explode with ``DuplicateColumn``."""
    if column.name not in _columns(table):
        op.add_column(table, column, schema=SCHEMA)


def add_index(name: str, table: str, columns: List[str], **kwargs: Any) -> None:
    """Existence-checked CREATE INDEX (module Alembic house rule, see 0002's
    own ``make_index``): a create_all-first host already has every index
    ``models.py.__table_args__`` declares before this migration ever runs -
    a bare ``op.create_index`` would explode with ``DuplicateTable``
    (Postgres names index-creation failures that way)."""
    if name not in _indexes(table):
        op.create_index(name, table, columns, schema=SCHEMA, **kwargs)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # ── ac_entity_config: delivery mode (AC-10-10) ──────────────────────────
    add_column(
        "ac_entity_config",
        sa.Column(
            "delivery_mode", sa.String(), nullable=False, server_default="push"
        ),
    )

    # ── ac_pull_snapshot / ac_pull_snapshot_row (AC-10-18) ──────────────────
    if "ac_pull_snapshot" not in _tables():
        op.create_table(
            "ac_pull_snapshot",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("company_code", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="building"),
            sa.Column("job_id", sa.String(), nullable=True),
            sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("content_hash", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("requested_via", sa.String(), nullable=False, server_default="operator"),
            sa.Column("requested_by", sa.String(), nullable=True),
            sa.Column(
                "created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("extracted_at", UTCDateTime(), nullable=True),
            sa.Column("expires_at", UTCDateTime(), nullable=True),
            schema=SCHEMA,
        )
    add_index(
        "ix_ac_pull_snapshot_triple",
        "ac_pull_snapshot",
        ["tenant_id", "company_id", "entity_type"],
    )
    add_index("ix_ac_pull_snapshot_status", "ac_pull_snapshot", ["tenant_id", "status"])
    add_index("ix_ac_pull_snapshot_expires_at", "ac_pull_snapshot", ["expires_at"])
    add_index("ix_ac_pull_snapshot_job", "ac_pull_snapshot", ["job_id"])
    # sprint-5/10 review round 1 SHOULD-FIX 4 (AC-10-26) - at most ONE
    # ``building`` snapshot per (tenant, company, entity) triple, enforced by
    # the database (mirrors ``models.py``'s own partial unique index - S4
    # owns the NEXT revision id, so this amends 0020 rather than adding
    # 0021).
    add_index(
        "uq_ac_pull_snapshot_one_building",
        "ac_pull_snapshot",
        ["tenant_id", "company_id", "entity_type"],
        unique=True,
        postgresql_where=sa.text("status = 'building'"),
    )

    if "ac_pull_snapshot_row" not in _tables():
        op.create_table(
            "ac_pull_snapshot_row",
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("snapshot_id", sa.String(), nullable=False),
            sa.Column("row_index", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("source_ref", sa.String(), nullable=False),
            sa.Column("payload_json", sa.JSON(none_as_null=True), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "snapshot_id", "row_index"),
            schema=SCHEMA,
        )
    add_index(
        "ix_ac_pull_snapshot_row_snapshot",
        "ac_pull_snapshot_row",
        ["tenant_id", "snapshot_id"],
    )
    add_index("ix_ac_pull_snapshot_row_company", "ac_pull_snapshot_row", ["company_id"])

    # Runs on BOTH orderings (create_all-first vs a stamped host) - a no-op
    # after the ADD above already carried every row via the server default.
    backfill_delivery_mode_defaults(bind, schema=SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if "ac_pull_snapshot_row" in _tables():
        op.drop_table("ac_pull_snapshot_row", schema=SCHEMA)
    if "ac_pull_snapshot" in _tables():
        op.drop_table("ac_pull_snapshot", schema=SCHEMA)
    if "delivery_mode" in _columns("ac_entity_config"):
        op.drop_column("ac_entity_config", "delivery_mode", schema=SCHEMA)
