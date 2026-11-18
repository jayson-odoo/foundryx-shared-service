"""omnichannel - per-number WhatsApp window opt-in (S12, decision D3, 2026-11-18).

Adds `omnichannel_settings.strict_number_window` (nullable boolean). NULL or
false = today's contact-level window for every existing workspace, so no
backfill: no existing row changes meaning. Online-safe: a nullable column with
no default on a small per-workspace table is a catalog-only change in Postgres.
Idempotent guard (inspector check), same style as `0026_omni_contact_erasures`.
Revision id <= 32 chars.

Revision ID: 0029_omni_strict_number_window
Revises: 0028_omni_partner_api_keys
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0029_omni_strict_number_window"
down_revision = "0028_omni_partner_api_keys"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("omnichannel_settings", schema=SCHEMA)}
    if "strict_number_window" not in columns:
        op.add_column(
            "omnichannel_settings",
            sa.Column("strict_number_window", sa.Boolean(), nullable=True),
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_column("omnichannel_settings", "strict_number_window", schema=SCHEMA)
