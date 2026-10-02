"""Tenant settings: public_link_base_url (SS-PUBLIC-LINK-BASE)

Per-tenant origin for public links minted for the tenant's end-users (idea
tracking links on the Sorento CRM customer portal). NULL = today's behaviour
(each feature's own default origin), so this is additive and changes nothing
until a tenant fills it in. Idempotent: ``ADD COLUMN IF NOT EXISTS`` on Postgres.

Revision ID: ss_public_link_base
Revises: ai_msg_summary_s3
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

# <= 32 chars (alembic_version.version_num is VARCHAR(32)).
revision = "ss_public_link_base"
down_revision = "ai_msg_summary_s3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE tenant_settings "
            "ADD COLUMN IF NOT EXISTS public_link_base_url VARCHAR NULL"
        )
    else:
        op.add_column(
            "tenant_settings", sa.Column("public_link_base_url", sa.String(), nullable=True)
        )


def downgrade() -> None:
    op.drop_column("tenant_settings", "public_link_base_url")
