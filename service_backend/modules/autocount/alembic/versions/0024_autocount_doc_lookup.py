"""autocount doc finder (sprint-5/17, AC-DOC-FINDER)

NEW tables only - no existing row gains a column, so no backfill is needed
(DoD 2): a hint row appears on the first successful lookup, a settings row
on the first save (absent = the 7/14 defaults).

* ``ac_doc_lookup_hint`` - where a document was last found (never its content).
* ``ac_doc_lookup_settings`` - per-company live-search windows.
* Two expression indexes so the stored search (a case-insensitive DocNo match)
  is an index lookup, never a scan of every snapshot row / ledger row. They
  cover the rows that already exist the moment they are built. The expression
  must stay byte-identical to ``DocLookupRepository._norm_expr`` (``lower(trim(x))``)
  or Postgres will not use them.

Existence-checked (0020/0023 convention) so a create_all-first host is a
clean no-op for the tables.

Revision ID: 0024_autocount_doc_lookup   (25 chars <= 32)
Revises: 0023_autocount_doc_feed
Create Date: 2026-10-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns
from app.models.utc_datetime import UTCDateTime

revision: str = "0024_autocount_doc_lookup"
down_revision: Union[str, Sequence[str], None] = "0023_autocount_doc_feed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names(schema=SCHEMA))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if "ac_doc_lookup_hint" not in _tables():
        op.create_table(
            "ac_doc_lookup_hint",
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("doc_type", sa.String(), nullable=False),
            sa.Column("doc_no_norm", sa.String(), nullable=False),
            sa.Column("doc_key", sa.BigInteger(), nullable=True),
            sa.Column("doc_date", sa.Date(), nullable=True),
            sa.Column("last_modified", sa.String(), nullable=True),
            sa.Column(
                "found_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            sa.PrimaryKeyConstraint("tenant_id", "company_id", "doc_type", "doc_no_norm"),
            schema=SCHEMA,
        )

    if "ac_doc_lookup_settings" not in _tables():
        op.create_table(
            "ac_doc_lookup_settings",
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("back_days", sa.Integer(), nullable=False, server_default="7"),
            sa.Column("forward_days", sa.Integer(), nullable=False, server_default="14"),
            sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("tenant_id", "company_id"),
            schema=SCHEMA,
        )

    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_ac_pull_snapshot_row_docno "
        f"ON {SCHEMA}.ac_pull_snapshot_row "
        f"(tenant_id, company_id, lower(trim(payload_json ->> 'DocNo')))"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_ac_doc_feed_ledger_docno "
        f"ON {SCHEMA}.ac_doc_feed_ledger "
        f"(tenant_id, company_id, feed, lower(trim(doc_no)))"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ix_ac_doc_feed_ledger_docno")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ix_ac_pull_snapshot_row_docno")
    for table in ("ac_doc_lookup_settings", "ac_doc_lookup_hint"):
        if table in _tables():
            op.drop_table(table, schema=SCHEMA)
