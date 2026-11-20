"""autocount API call log (plan 61 section 4.8, owner ruling R3)

* ``ac_api_call_log``: one row per HTTP call the write layer makes to AutoCount.
  Additive only: a new table and its two indexes (tenant + company + created_at,
  doc_key); no existing table changes, so nothing to backfill. Never commits.

Revision ID: 0044_autocount_api_call_log   (27 chars <= 32)
Revises: 0043_autocount_display_term
Create Date: 2026-11-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044_autocount_api_call_log"
down_revision: Union[str, Sequence[str], None] = "0043_autocount_display_term"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_api_call_log"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("operation_id", sa.String(), nullable=True),
        sa.Column("action_id", sa.String(), nullable=True),
        sa.Column("book", sa.String(), nullable=True),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("doc_type", sa.String(), nullable=True),
        sa.Column("doc_no", sa.String(), nullable=True),
        sa.Column("doc_key", sa.BigInteger(), nullable=True),
        sa.Column("request_json", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("response_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ac_api_call_log_tenant_company_created", TABLE, ["tenant_id", "company_id", "created_at"], schema=SCHEMA
    )
    op.create_index("ix_ac_api_call_log_doc_key", TABLE, ["doc_key"], schema=SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index("ix_ac_api_call_log_doc_key", table_name=TABLE, schema=SCHEMA)
    op.drop_index("ix_ac_api_call_log_tenant_company_created", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
