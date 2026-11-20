"""autocount write operations and exact action recording (plan 57 S3)

* ``ac_write_operation``: the level-2 operation log (idempotency unique key, and a
  partial unique index = one ``in_progress`` operation per document).
* ``ac_write_action`` gains nullable ``operation_id``, ``step``, ``request_method``,
  ``request_path``; ``doc_key`` becomes nullable (a create has no DocKey until the
  vendor answers). Existing rows keep nulls: they read as plan 55 actions, so no
  backfill is needed. Never commits.

Revision ID: 0040_autocount_write_ops   (25 chars <= 32)
Revises: 0039_autocount_write_status
Create Date: 2026-11-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040_autocount_write_ops"
down_revision: Union[str, Sequence[str], None] = "0039_autocount_write_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
ACTION = "ac_write_action"
OPERATION = "ac_write_operation"
NEW_COLUMNS = ("operation_id", "step", "request_method", "request_path")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    json_type = sa.JSON(none_as_null=True)
    op.create_table(
        OPERATION,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("key_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("op", sa.String(), nullable=False),
        sa.Column("doc_type", sa.String(), nullable=True),
        sa.Column("doc_key", sa.BigInteger(), nullable=True),
        sa.Column("dtl_key", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("snapshot_json", json_type, nullable=True),
        sa.Column("steps_json", json_type, nullable=True),
        sa.Column("result_json", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "company_id", "key_id", "idempotency_key", name="uq_ac_write_operation_idem"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_ac_write_operation_tenant_id", OPERATION, ["tenant_id"], schema=SCHEMA)
    op.create_index(
        "uq_ac_write_operation_one_in_progress",
        OPERATION,
        ["company_id", "doc_type", "doc_key"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'in_progress'"),
    )
    for name in NEW_COLUMNS:
        op.add_column(ACTION, sa.Column(name, sa.String(), nullable=True), schema=SCHEMA)
    op.alter_column(ACTION, "doc_key", existing_type=sa.BigInteger(), nullable=True, schema=SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # A create row has no DocKey; the NOT NULL column cannot hold it, so drop those first.
    op.execute(f"DELETE FROM {SCHEMA}.{ACTION} WHERE doc_key IS NULL")
    op.alter_column(ACTION, "doc_key", existing_type=sa.BigInteger(), nullable=False, schema=SCHEMA)
    for name in NEW_COLUMNS:
        op.drop_column(ACTION, name, schema=SCHEMA)
    op.drop_index("uq_ac_write_operation_one_in_progress", table_name=OPERATION, schema=SCHEMA)
    op.drop_index("ix_ac_write_operation_tenant_id", table_name=OPERATION, schema=SCHEMA)
    op.drop_table(OPERATION, schema=SCHEMA)
