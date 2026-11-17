"""omnichannel S6 - partner API keys (tenant-scoped `fxp_live_` credential).

Adds `partner_api_keys`: one row per partner key (tenant, name, 8-char lookup
prefix, SHA-256 hash, optional return-origin allow-list, usage and revoke
stamps). The table is new, so there is nothing to backfill, and creating it
takes no lock on any existing table (online-safe). Idempotent guard
(inspector check), same style as `0026_omni_contact_erasures`. Revision id
<= 32 chars.

Revision ID: 0027_omni_partner_api_keys
Revises: 0026_omni_contact_erasures
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_omni_partner_api_keys"
down_revision = "0026_omni_contact_erasures"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema=SCHEMA))

    if "partner_api_keys" not in tables:
        op.create_table(
            "partner_api_keys",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("key_prefix", sa.String(), nullable=False),
            sa.Column("key_hash", sa.String(), nullable=False),
            sa.Column("allowed_return_origins", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_app_omnichannel_partner_api_keys_tenant_id",
            "partner_api_keys",
            ["tenant_id"],
            schema=SCHEMA,
        )
        op.create_index(
            "ix_app_omnichannel_partner_api_keys_key_prefix",
            "partner_api_keys",
            ["key_prefix"],
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_app_omnichannel_partner_api_keys_key_prefix", table_name="partner_api_keys", schema=SCHEMA
    )
    op.drop_index(
        "ix_app_omnichannel_partner_api_keys_tenant_id", table_name="partner_api_keys", schema=SCHEMA
    )
    op.drop_table("partner_api_keys", schema=SCHEMA)
