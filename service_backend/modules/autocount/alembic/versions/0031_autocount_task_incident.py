"""autocount integration failure alerts (plan 33, AC-33-16)

``ac_entity_config`` += nullable ``resumed_at`` (set only by resume; NULL =
never resumed, so no backfill) plus the NEW table ``ac_task_incident``, one OPEN row per integration
(``ac_entity_config`` row) enforced by a partial unique index. No existing row
gains a column and the four alert settings live in ``source_config`` (an absent
key is the default), so no backfill is needed (DoD 2): every existing
integration is covered by the evaluator from the next sweep tick.

Existence-checked (0020/0024 convention) so a create_all-first host is a clean
no-op. The crew SQL twin is idempotent (``IF NOT EXISTS``).

Revision ID: 0031_autocount_task_incident   (29 chars <= 32)
Revises: 0030_autocount_consign_xfer
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns
from app.models.utc_datetime import UTCDateTime

revision: str = "0031_autocount_task_incident"
down_revision: Union[str, Sequence[str], None] = "0030_autocount_consign_xfer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_task_incident"


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names(schema=SCHEMA))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"ALTER TABLE {SCHEMA}.ac_entity_config ADD COLUMN IF NOT EXISTS resumed_at TIMESTAMPTZ NULL"
    )

    if TABLE not in _tables():
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("entity_config_id", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("reason", sa.String(), nullable=False),
            sa.Column("opened_at", UTCDateTime(), nullable=False),
            sa.Column("first_failure_at", UTCDateTime(), nullable=True),
            sa.Column("failed_runs", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_notified_at", UTCDateTime(), nullable=True),
            sa.Column("notices_sent", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("closed_at", UTCDateTime(), nullable=True),
            sa.Column("close_reason", sa.String(), nullable=True),
            sa.Column("created_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            schema=SCHEMA,
        )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_ac_task_incident_tenant_id "
        f"ON {SCHEMA}.{TABLE} (tenant_id)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_ac_task_incident_scope "
        f"ON {SCHEMA}.{TABLE} (tenant_id, company_id)"
    )
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_ac_task_incident_one_open "
        f"ON {SCHEMA}.{TABLE} (entity_config_id) WHERE closed_at IS NULL"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if TABLE in _tables():
        op.drop_table(TABLE, schema=SCHEMA)
    op.execute(f"ALTER TABLE {SCHEMA}.ac_entity_config DROP COLUMN IF EXISTS resumed_at")
