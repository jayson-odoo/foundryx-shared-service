"""omnichannel Slice 4 - consumer webhook endpoints + delivery outbox.

Adds ``webhook_endpoints`` (per-channel consumer subscriptions) and
``webhook_deliveries`` (durable signed-delivery outbox). Idempotent: the module
baseline runs ``OmniBase.metadata.create_all`` which already includes these
tables, so on a fresh deploy they may exist - guard each create.

Revision ID: 0003_omni_webhooks
Revises: 0002_omni_apikeys
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_omni_webhooks"
down_revision = "0002_omni_apikeys"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names(schema=SCHEMA))

    if "webhook_endpoints" not in existing:
        op.create_table(
            "webhook_endpoints",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("workspace_id", sa.String(), nullable=False, index=True),
            sa.Column("channel_id", sa.String(), nullable=False, index=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("url", sa.String(), nullable=False),
            sa.Column("secret_encrypted", sa.Text(), nullable=False),
            sa.Column("events_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
            sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("disabled_reason", sa.String(), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            schema=SCHEMA,
        )

    if "webhook_deliveries" not in existing:
        op.create_table(
            "webhook_deliveries",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("endpoint_id", sa.String(), nullable=False, index=True),
            sa.Column("event_id", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("response_status", sa.Integer(), nullable=True),
            sa.Column("response_ms", sa.Integer(), nullable=True),
            sa.Column("error", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_webhook_deliveries_due",
            "webhook_deliveries",
            ["status", "next_attempt_at"],
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_table("webhook_deliveries", schema=SCHEMA)
    op.drop_table("webhook_endpoints", schema=SCHEMA)
