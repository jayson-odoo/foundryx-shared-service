"""autocount write-back action log + company write connection (plan 55, AC-55-28)

NEW table ``ac_write_action`` (audit trail, test-report source and per-document
busy lock) plus a nullable ``ac_company.write_connection_id`` (NULL = writes
disabled). The backfill for every existing company is NULL, i.e. the column
default, so no data step is needed (DoD 2).

Existence-checked (0020/0024/0031 convention) so a create_all-first host is a
clean no-op. Never commits: Alembic's own transaction owns that.

Revision ID: 0036_autocount_write_back   (25 chars <= 32)
Revises: 0035_autocount_debtor_type
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns
from app.models.utc_datetime import UTCDateTime

revision: str = "0036_autocount_write_back"
down_revision: Union[str, Sequence[str], None] = "0035_autocount_debtor_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_write_action"


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names(schema=SCHEMA))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"ALTER TABLE {SCHEMA}.ac_company ADD COLUMN IF NOT EXISTS write_connection_id VARCHAR NULL"
    )

    if TABLE not in _tables():
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("doc_type", sa.String(), nullable=False),
            sa.Column("doc_key", sa.BigInteger(), nullable=False),
            sa.Column("dtl_key", sa.BigInteger(), nullable=True),
            sa.Column("outcome", sa.String(), nullable=False),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("request_json", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("response_status", sa.Integer(), nullable=True),
            sa.Column("response_json", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("before_json", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("after_json", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("key_id", sa.String(), nullable=True),
            sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", UTCDateTime(), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            schema=SCHEMA,
        )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_ac_write_action_tenant_id ON {SCHEMA}.{TABLE} (tenant_id)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_ac_write_action_busy "
        f"ON {SCHEMA}.{TABLE} (tenant_id, company_id, doc_key, outcome)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if TABLE in _tables():
        op.drop_table(TABLE, schema=SCHEMA)
    op.execute(f"ALTER TABLE {SCHEMA}.ac_company DROP COLUMN IF EXISTS write_connection_id")
