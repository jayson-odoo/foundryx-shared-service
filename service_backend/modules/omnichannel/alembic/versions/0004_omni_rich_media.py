"""omnichannel plan 12 Slice 1 — rich media columns + per-workspace settings.

Adds the rich-media columns to ``conversation_messages`` (``media_key``,
``media_mime``, ``media_filename``, ``media_size``, ``payload_json``) and the
``omnichannel_settings`` table (per-workspace media caps). Idempotent guards —
the module baseline runs ``create_all`` so a fresh deploy may already have these.
Backfill-safe: existing rows keep their legacy ``media_url``; new media rides
``media_key``. Revision id ≤ 32 chars.

Revision ID: 0004_omni_rich_media
Revises: 0003_omni_webhooks
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_omni_rich_media"
down_revision = "0003_omni_webhooks"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_cols = {c["name"] for c in inspector.get_columns("conversation_messages", schema=SCHEMA)}
    new_cols = [
        ("media_key", sa.String()),
        ("media_mime", sa.String()),
        ("media_filename", sa.String()),
        ("media_size", sa.Integer()),
        ("payload_json", sa.JSON()),
    ]
    for name, coltype in new_cols:
        if name not in existing_cols:
            op.add_column(
                "conversation_messages", sa.Column(name, coltype, nullable=True), schema=SCHEMA
            )

    if "omnichannel_settings" not in set(inspector.get_table_names(schema=SCHEMA)):
        op.create_table(
            "omnichannel_settings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("workspace_id", sa.String(), nullable=True, index=True),
            sa.Column("image_max_bytes", sa.Integer(), nullable=True),
            sa.Column("video_max_bytes", sa.Integer(), nullable=True),
            sa.Column("audio_max_bytes", sa.Integer(), nullable=True),
            sa.Column("document_max_bytes", sa.Integer(), nullable=True),
            sa.Column("sticker_max_bytes", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "workspace_id", name="uq_omnichannel_settings_ws"),
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_table("omnichannel_settings", schema=SCHEMA)
    for name in ("payload_json", "media_size", "media_filename", "media_mime", "media_key"):
        op.drop_column("conversation_messages", name, schema=SCHEMA)
