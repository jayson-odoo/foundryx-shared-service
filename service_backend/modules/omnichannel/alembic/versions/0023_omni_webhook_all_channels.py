"""omnichannel plan 38 gap 2 - a webhook endpoint can cover every channel.

Makes ``webhook_endpoints.channel_id`` nullable. A NULL ``channel_id`` means the
endpoint receives events of every channel in its own tenant and workspace.

No backfill: existing rows keep their ``channel_id`` untouched, and the change
moves no data.

Idempotent: ``DROP NOT NULL`` on an already nullable column is a no-op. The
non-Postgres branch is parity only - the module migration orchestrator skips
non-Postgres dialects, so it never runs under pytest.

Downgrade leaves the column nullable on purpose: NULL rows cannot fit the old
rule, and deleting them would drop a consumer's registration.

Revision ID: 0023_omni_webhook_all_channels
Revises: 0022_omni_webchat_profile
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_omni_webhook_all_channels"
down_revision = "0022_omni_webchat_profile"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f'ALTER TABLE "{SCHEMA}".webhook_endpoints ALTER COLUMN channel_id DROP NOT NULL'
        )
    else:
        with op.batch_alter_table("webhook_endpoints", schema=SCHEMA) as batch_op:
            batch_op.alter_column("channel_id", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # Intentionally a no-op: see the module docstring.
    pass
