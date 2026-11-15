"""lc_lead.form_name - the Instant Form's name on the Lead (additive, nullable).

Live-run finding 1 (15 Nov 2026): the consumer needs the form NAME, not only the
id. Existing rows keep NULL (the name was never read for them; a null name is a
documented value). Idempotent so a database built by ``create_all`` from the
current models (column already there) upgrades cleanly. Postgres-only.

Revision ID: 0002_lc_lead_form_name
Revises: 0001_lead_capture_init
Create Date: 2026-11-15
"""

from __future__ import annotations
from alembic import op

revision = "0002_lc_lead_form_name"
down_revision = "0001_lead_capture_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        'ALTER TABLE "app_lead_capture"."lc_lead" ADD COLUMN IF NOT EXISTS form_name VARCHAR(200)'
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        'ALTER TABLE "app_lead_capture"."lc_lead" DROP COLUMN IF EXISTS form_name'
    )
