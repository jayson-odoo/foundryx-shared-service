"""integration_log_settings table (per-tenant developer-logs retention).

sprint-4/12 Slice 3 (AC-DLC-21) — one row per tenant, ``retention_days`` NULL =
use the global default (``settings.integration_activity_retention_days``).
Mirrors ``workflow_settings``. No new permission (``integration_logs.manage`` was
added + swept to existing tenants' Admin in the Slice-1 migration).

Deploy via ``bootstrap_db`` (runs ``alembic upgrade``), NOT ``init_db``.

Revision id: ``dlc_s412b_log_settings`` (22 chars ≤ 32).

Revision ID: dlc_s412b_log_settings
Revises: 854a5316dfb7
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "dlc_s412b_log_settings"
down_revision: Union[str, Sequence[str], None] = "854a5316dfb7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "integration_log_settings" not in insp.get_table_names():
        op.create_table(
            "integration_log_settings",
            sa.Column("tenant_id", sa.String(), primary_key=True),
            sa.Column("retention_days", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("integration_log_settings")
