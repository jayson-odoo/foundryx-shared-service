"""omnichannel plan 32 S3 (A7a) - meta_connect_sessions (Messenger/Instagram
connect flow).

Adds `meta_connect_sessions` (D-A7-15) - a short-lived, single-use,
tenant-and-user-bound row holding the Fernet-encrypted user token exchanged
by `POST /meta/pages`, so it never reaches the browser; `POST /meta/connect`
decrypts it, provisions the channel and stamps `consumed_at`. Brand new table
(no existing-column ALTER), idempotent inspector guard, mirrors
`0015_omni_workflow_waits`'s style. Revision id <= 32 chars.

Revision ID: 0018_omni_meta_connect
Revises: 0017_omni_meta_channels
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

# UTCDateTime columns ride sa.DateTime(timezone=True) here (module-migration
# convention, matching 0015/0017); import kept for parity with the house rule.
import app.models.utc_datetime  # noqa: F401

revision = "0018_omni_meta_connect"
down_revision = "0017_omni_meta_channels"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema=SCHEMA))
    if "meta_connect_sessions" not in tables:
        op.create_table(
            "meta_connect_sessions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("channel_type", sa.String(), nullable=False),
            sa.Column("credentials_json", sa.Text(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_table("meta_connect_sessions", schema=SCHEMA)
