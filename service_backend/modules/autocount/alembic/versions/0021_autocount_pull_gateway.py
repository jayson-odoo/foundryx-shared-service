"""The public pull gateway: API keys + audit (sprint-5/10 S4, AC-10-27).

* NEW ``ac_pull_api_key`` - one issued gateway key (scheme ``fxa_live_``,
  8-char indexed ``key_prefix``, sha256 ``key_hash``, an explicit
  ``company_ids`` SET). No FK to ``ac_company`` (BL-030, matching every
  other cross-row reference in this module) - ``PullKeyService.issue``
  validates the set against the tenant's own companies at issue time.
* NEW ``ac_pull_audit`` - one row per gateway call. No FK anywhere on this
  table either, and deliberately NO payload/plaintext column at all.

Revision ID: 0021_autocount_pull_gateway   (29 chars <= 32)
Revises: 0020_autocount_pull_snapshot
Create Date: 2026-09-20

Amended in place (review round 2, item 5, still unreleased at the time of
this amendment - the only stamped host was the lane Postgres
``foundryx_service_s40``, re-run downgrade-then-upgrade against it): adds
``ix_ac_pull_audit_created_at`` so the 90-day audit prune
(``prune_pull_snapshots``) no longer full-scans the table as it grows.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns
from app.models.utc_datetime import UTCDateTime

revision: str = "0021_autocount_pull_gateway"
down_revision: Union[str, Sequence[str], None] = "0020_autocount_pull_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names(schema=SCHEMA))


def _indexes(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table, schema=SCHEMA)}


def add_index(name: str, table: str, columns: list, **kwargs) -> None:
    """Existence-checked CREATE INDEX (module Alembic house rule, see 0020's
    own ``add_index``) - a create_all-first host already has every index
    ``models.py.__table_args__`` declares before this migration ever runs."""
    if name not in _indexes(table):
        op.create_index(name, table, columns, schema=SCHEMA, **kwargs)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if "ac_pull_api_key" not in _tables():
        op.create_table(
            "ac_pull_api_key",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False, server_default=""),
            sa.Column("key_prefix", sa.String(), nullable=False),
            sa.Column("key_hash", sa.String(), nullable=False),
            sa.Column("company_ids", sa.JSON(none_as_null=True), nullable=False),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column(
                "created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("last_used_at", UTCDateTime(), nullable=True),
            sa.Column("revoked_at", UTCDateTime(), nullable=True),
            schema=SCHEMA,
        )
    add_index("ix_ac_pull_api_key_tenant", "ac_pull_api_key", ["tenant_id"])
    add_index("ix_ac_pull_api_key_prefix", "ac_pull_api_key", ["key_prefix"])

    if "ac_pull_audit" not in _tables():
        op.create_table(
            "ac_pull_audit",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=True),
            sa.Column("entity_type", sa.String(), nullable=True),
            sa.Column("key_id", sa.String(), nullable=True),
            sa.Column("snapshot_id", sa.String(), nullable=True),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("page", sa.Integer(), nullable=True),
            sa.Column("record_count", sa.Integer(), nullable=True),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column(
                "created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            schema=SCHEMA,
        )
    add_index("ix_ac_pull_audit_tenant", "ac_pull_audit", ["tenant_id"])
    add_index("ix_ac_pull_audit_snapshot", "ac_pull_audit", ["snapshot_id"])
    add_index("ix_ac_pull_audit_key", "ac_pull_audit", ["key_id"])
    # review round 2 (item 5) - the 90-day prune sweep's own WHERE clause
    # (``created_at < cutoff``), matching the ORM's own new ``Index``.
    add_index("ix_ac_pull_audit_created_at", "ac_pull_audit", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if "ac_pull_audit" in _tables():
        op.drop_table("ac_pull_audit", schema=SCHEMA)
    if "ac_pull_api_key" in _tables():
        op.drop_table("ac_pull_api_key", schema=SCHEMA)
