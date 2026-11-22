"""Google sign-in on a hosted-wizard session (plan 68, G-D3).

Additive only: two nullable columns on ``lc_connect_session`` holding the
Google sign-in (Fernet ``{refreshToken, accessToken, email, dev}``) and when it
stops being usable, the same shape as the Facebook ``meta_*`` pair. A session
row lives 30 minutes, so no backfill is needed. Idempotent; Postgres-only.

Revision ID: 0006_lc_google_login
Revises: 0005_lc_connect_session
Create Date: 2026-11-18
"""

from __future__ import annotations
from alembic import op

revision = "0006_lc_google_login"
down_revision = "0005_lc_connect_session"
branch_labels = None
depends_on = None

_SCHEMA = '"app_lead_capture"'


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(f"ALTER TABLE {_SCHEMA}.lc_connect_session ADD COLUMN IF NOT EXISTS google_encrypted TEXT")
    bind.exec_driver_sql(
        f"ALTER TABLE {_SCHEMA}.lc_connect_session ADD COLUMN IF NOT EXISTS google_expires_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(f"ALTER TABLE {_SCHEMA}.lc_connect_session DROP COLUMN IF EXISTS google_expires_at")
    bind.exec_driver_sql(f"ALTER TABLE {_SCHEMA}.lc_connect_session DROP COLUMN IF EXISTS google_encrypted")
