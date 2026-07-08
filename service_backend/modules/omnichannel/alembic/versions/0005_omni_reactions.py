"""omnichannel plan 12 Slice 3 — message_reactions table.

A reaction is never a message row — it upserts here keyed to the target message
+ the reactor (``UNIQUE(target_message_id, reactor)``). Idempotent guard — the
module baseline runs ``create_all`` so a fresh deploy may already have this
table. Revision id ≤ 32 chars.

Revision ID: 0005_omni_reactions
Revises: 0004_omni_rich_media
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_omni_reactions"
down_revision = "0004_omni_rich_media"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "message_reactions" not in set(inspector.get_table_names(schema=SCHEMA)):
        op.create_table(
            "message_reactions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("workspace_id", sa.String(), nullable=True, index=True),
            sa.Column(
                "target_message_id",
                sa.String(),
                sa.ForeignKey(f"{SCHEMA}.conversation_messages.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("reactor_type", sa.String(), nullable=False),
            sa.Column("reactor", sa.String(), nullable=False),
            sa.Column("emoji", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("target_message_id", "reactor", name="uq_reaction_target_reactor"),
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_table("message_reactions", schema=SCHEMA)
