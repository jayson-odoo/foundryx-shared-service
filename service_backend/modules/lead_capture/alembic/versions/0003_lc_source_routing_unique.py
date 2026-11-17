"""uq_lc_source_live_account covers WAITING_FOR_TEST as well as LIVE (AC-64-16).

A new source is now saved WAITING_FOR_TEST and already receives leads, so the
one-row-per-(tenant, platform, Page) backstop must cover both routing states.
No WAITING_FOR_TEST row existed before this revision, so recreating the index
cannot fail on existing data. Idempotent; Postgres-only.

Revision ID: 0003_lc_source_routing_unique
Revises: 0002_lc_lead_form_name
Create Date: 2026-11-17
"""

from __future__ import annotations
from alembic import op

revision = "0003_lc_source_routing_unique"
down_revision = "0002_lc_lead_form_name"
branch_labels = None
depends_on = None

_TABLE = '"app_lead_capture"."lc_source"'


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql('DROP INDEX IF EXISTS "app_lead_capture"."uq_lc_source_live_account"')
    bind.exec_driver_sql(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_lc_source_live_account ON {_TABLE} "
        "(tenant_id, platform, account_ref) WHERE status IN ('WAITING_FOR_TEST', 'LIVE')"
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql('DROP INDEX IF EXISTS "app_lead_capture"."uq_lc_source_live_account"')
    bind.exec_driver_sql(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_lc_source_live_account ON {_TABLE} "
        "(tenant_id, platform, account_ref) WHERE status = 'LIVE'"
    )
