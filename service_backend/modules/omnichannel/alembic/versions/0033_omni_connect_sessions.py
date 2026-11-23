"""omnichannel FSS-1 - partner connect sessions.

Adds `partner_connect_sessions`: one row per hosted WhatsApp connect a partner
key starts for one workspace of its client app (tenant, client app, workspace,
creating key, sha256 of the single-use state, return URL, opaque client state,
status, encrypted token between callback and completion, created channel ids,
error code, timestamps). `client_app_id` is NOT NULL from the start because
the table is new. The table is new, so there is nothing to backfill, and
creating it takes no lock on any existing table beyond the foreign-key
references (online-safe). Idempotent guard (inspector check), same style as
`0028_omni_partner_api_keys`. The `create_schema_and_tables` path gets the
same table from the model through `create_all`. Revision id <= 32 chars.

Revision ID: 0033_omni_connect_sessions
Revises: 0032_omni_client_apps
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_omni_connect_sessions"
down_revision = "0032_omni_client_apps"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"
TABLE = "partner_connect_sessions"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE in set(inspector.get_table_names(schema=SCHEMA)):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column(
            "client_app_id",
            sa.String(),
            sa.ForeignKey(
                f"{SCHEMA}.client_apps.id", name="fk_partner_connect_sessions_client_app_id"
            ),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey(
                f"{SCHEMA}.workspaces.id", name="fk_partner_connect_sessions_workspace_id"
            ),
            nullable=False,
        ),
        sa.Column("partner_key_id", sa.String(), nullable=False),
        sa.Column("state_hash", sa.String(), nullable=False),
        sa.Column("channel_type", sa.String(), nullable=False),
        sa.Column("return_url", sa.Text(), nullable=False),
        sa.Column("client_state", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("credentials_json", sa.Text(), nullable=True),
        sa.Column("result_channel_ids", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('OPEN', 'AUTHORIZED', 'COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED')",
            name="ck_partner_connect_sessions_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_partner_connect_sessions_state_hash", TABLE, ["state_hash"], unique=True, schema=SCHEMA
    )
    for col in ("tenant_id", "client_app_id", "workspace_id", "expires_at"):
        op.create_index(f"ix_{SCHEMA}_{TABLE}_{col}", TABLE, [col], schema=SCHEMA)


def downgrade() -> None:
    for col in ("expires_at", "workspace_id", "client_app_id", "tenant_id"):
        op.drop_index(f"ix_{SCHEMA}_{TABLE}_{col}", table_name=TABLE, schema=SCHEMA)
    op.drop_index("uq_partner_connect_sessions_state_hash", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
