"""autocount doc feed (sprint-5/14, D1/D16)

NEW tables only - no existing row gains a column, so no backfill migration
is needed (DoD 2): rows are created on first configure.

* ``ac_doc_feed`` - one row per (tenant, company, feed).
* ``ac_doc_feed_ledger`` - what the CRM holds from us, per (feed, book, DocKey).
* ``ac_doc_feed_issue`` - documents the CRM did not take (retryable/failed).
* ``ac_doc_feed_run`` - one row per job (poll/sweep/backfill segment).
* ``ac_doc_feed_backfill`` - the durable backfill progress record; at most
  one OPEN (status <> 'done') row per (tenant, feed_id).

Existence-checked ``create_table`` (0020/0022 convention) so a create_all-
first host (``bootstrap_modules`` calls ``install()`` before
``run_module_migrations``) is a clean no-op here.

Revision ID: 0023_autocount_doc_feed   (23 chars <= 32)
Revises: 0022_autocount_preview_job
Create Date: 2026-09-29
"""
from typing import Any, List, Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns
from app.models.utc_datetime import UTCDateTime

revision: str = "0023_autocount_doc_feed"
down_revision: Union[str, Sequence[str], None] = "0022_autocount_preview_job"
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


def add_index(name: str, table: str, columns: List[str], **kwargs: Any) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, schema=SCHEMA, **kwargs)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if "ac_doc_feed" not in _tables():
        op.create_table(
            "ac_doc_feed",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("feed", sa.String(), nullable=False),
            sa.Column("connection_id", sa.String(), nullable=True),
            sa.Column("book", sa.String(length=20), nullable=True),
            sa.Column("mode", sa.String(), nullable=False, server_default="off"),
            sa.Column("cursor_day", sa.Date(), nullable=True),
            sa.Column("next_poll_at", UTCDateTime(), nullable=True),
            sa.Column("next_sweep_at", UTCDateTime(), nullable=True),
            sa.Column("last_poll_at", UTCDateTime(), nullable=True),
            sa.Column("last_poll_ok_at", UTCDateTime(), nullable=True),
            sa.Column("last_sweep_ok_at", UTCDateTime(), nullable=True),
            sa.Column("full_backfill_done_at", UTCDateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_error_code", sa.String(), nullable=True),
            sa.Column(
                "created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("updated_at", UTCDateTime(), nullable=True),
            sa.UniqueConstraint("tenant_id", "company_id", "feed", name="uq_ac_doc_feed"),
            schema=SCHEMA,
        )
    add_index("ix_ac_doc_feed_scope", "ac_doc_feed", ["tenant_id", "company_id"])
    add_index("ix_ac_doc_feed_next_sweep_at", "ac_doc_feed", ["next_sweep_at"])
    add_index("ix_ac_doc_feed_tenant", "ac_doc_feed", ["tenant_id"])
    add_index("ix_ac_doc_feed_company", "ac_doc_feed", ["company_id"])
    add_index("ix_ac_doc_feed_connection", "ac_doc_feed", ["connection_id"])
    add_index("ix_ac_doc_feed_next_poll_at", "ac_doc_feed", ["next_poll_at"])

    if "ac_doc_feed_ledger" not in _tables():
        op.create_table(
            "ac_doc_feed_ledger",
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("feed", sa.String(), nullable=False),
            sa.Column("book", sa.String(length=20), nullable=False),
            sa.Column("doc_key", sa.BigInteger(), nullable=False),
            sa.Column("doc_no", sa.String(), nullable=True),
            sa.Column("doc_date", sa.Date(), nullable=True),
            sa.Column("source_modified_at", UTCDateTime(), nullable=True),
            sa.Column("last_outcome", sa.String(), nullable=True),
            sa.Column("pushed_at", UTCDateTime(), nullable=True),
            sa.Column("vanished_at", UTCDateTime(), nullable=True),
            sa.PrimaryKeyConstraint("tenant_id", "company_id", "feed", "book", "doc_key"),
            schema=SCHEMA,
        )
    add_index(
        "ix_ac_doc_feed_ledger_window", "ac_doc_feed_ledger",
        ["tenant_id", "company_id", "feed", "book", "doc_date"],
    )

    if "ac_doc_feed_issue" not in _tables():
        op.create_table(
            "ac_doc_feed_issue",
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("feed", sa.String(), nullable=False),
            sa.Column("book", sa.String(length=20), nullable=False),
            sa.Column("doc_key", sa.BigInteger(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("doc_no", sa.String(), nullable=True),
            sa.Column("doc_date", sa.Date(), nullable=True),
            sa.Column("source_modified_at", UTCDateTime(), nullable=True),
            sa.Column("record_json", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("errors_json", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("warnings_json", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "first_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column(
                "last_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("last_run_id", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("tenant_id", "company_id", "feed", "book", "doc_key"),
            schema=SCHEMA,
        )
    add_index(
        "ix_ac_doc_feed_issue_scope", "ac_doc_feed_issue",
        ["tenant_id", "company_id", "feed", "kind"],
    )

    if "ac_doc_feed_run" not in _tables():
        op.create_table(
            "ac_doc_feed_run",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("feed_id", sa.String(), nullable=False),
            sa.Column("feed", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("job_id", sa.String(), nullable=True),
            sa.Column("day_from", sa.Date(), nullable=True),
            sa.Column("day_to", sa.Date(), nullable=True),
            sa.Column("requests", sa.Integer(), nullable=True),
            sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary_json", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("outcome", sa.String(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column(
                "started_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("finished_at", UTCDateTime(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            schema=SCHEMA,
        )
    add_index(
        "ix_ac_doc_feed_run_scope", "ac_doc_feed_run", ["tenant_id", "company_id", "feed_id"],
    )
    add_index("ix_ac_doc_feed_run_job", "ac_doc_feed_run", ["tenant_id", "job_id"])
    add_index("ix_ac_doc_feed_run_tenant", "ac_doc_feed_run", ["tenant_id"])
    add_index("ix_ac_doc_feed_run_company", "ac_doc_feed_run", ["company_id"])
    add_index("ix_ac_doc_feed_run_feed_id", "ac_doc_feed_run", ["feed_id"])

    if "ac_doc_feed_backfill" not in _tables():
        op.create_table(
            "ac_doc_feed_backfill",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("feed_id", sa.String(), nullable=False),
            sa.Column("feed", sa.String(), nullable=False),
            sa.Column("book", sa.String(length=20), nullable=True),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("from_day", sa.Date(), nullable=False),
            sa.Column("to_day", sa.Date(), nullable=False),
            sa.Column("next_day", sa.Date(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="running"),
            sa.Column("job_id", sa.String(), nullable=True),
            sa.Column("days_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("days_done", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary_json", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("started_by", sa.String(), nullable=True),
            sa.Column(
                "started_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("finished_at", UTCDateTime(), nullable=True),
            sa.Column("updated_at", UTCDateTime(), nullable=True),
            schema=SCHEMA,
        )
    add_index(
        "ix_ac_doc_feed_backfill_scope", "ac_doc_feed_backfill",
        ["tenant_id", "company_id", "feed_id"],
    )
    add_index("ix_ac_doc_feed_backfill_tenant", "ac_doc_feed_backfill", ["tenant_id"])
    add_index("ix_ac_doc_feed_backfill_company", "ac_doc_feed_backfill", ["company_id"])
    add_index("ix_ac_doc_feed_backfill_feed_id", "ac_doc_feed_backfill", ["feed_id"])
    # At most one OPEN (status <> 'done') backfill per (tenant, feed) -
    # mirrors ``models.py``'s own partial unique index (the ``AcPullSnapshot``
    # precedent).
    add_index(
        "uq_ac_doc_feed_backfill_one_open",
        "ac_doc_feed_backfill",
        ["tenant_id", "feed_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'done'"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in (
        "ac_doc_feed_backfill", "ac_doc_feed_run", "ac_doc_feed_issue",
        "ac_doc_feed_ledger", "ac_doc_feed",
    ):
        if table in _tables():
            op.drop_table(table, schema=SCHEMA)
