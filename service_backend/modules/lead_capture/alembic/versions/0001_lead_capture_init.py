"""lead_capture init - creates every ``app_lead_capture`` table.

Tables: lc_source, lc_settings, lc_lead, lc_webhook_endpoint, lc_delivery,
lc_api_key, lc_api_audit. Postgres-only (per-module Alembic is a no-op on the
SQLite test engine).

Revision ID: 0001_lead_capture_init
Revises:
Create Date: 2026-11-15
"""

from __future__ import annotations
from alembic import op

revision = "0001_lead_capture_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import text

    from modules.lead_capture.db import LEAD_CAPTURE_SCHEMA, LeadCaptureBase
    from modules.lead_capture import models  # noqa: F401

    bind = op.get_bind()
    bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{LEAD_CAPTURE_SCHEMA}"'))
    LeadCaptureBase.metadata.create_all(bind=bind)


def downgrade() -> None:
    from modules.lead_capture.db import LeadCaptureBase
    from modules.lead_capture import models  # noqa: F401

    LeadCaptureBase.metadata.drop_all(bind=op.get_bind())
