"""Document sharing — file_shares + file_share_users + file_links (plan sprint-3/05)

Google-Drive model: ONE stable share per target (unique tenant+kind+id), an
editable ``general_access`` (restricted|workspace|public) + ``general_capability``,
and an additive named-people list each with its own capability. Plus the deferred
polymorphic ``file_links`` seam (D8). Chains the slice-04 document-engine head.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa

import app.models.utc_datetime  # noqa: F401 — UTCDateTime columns
from app.models.utc_datetime import UTCDateTime

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_shares",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("target_kind", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("general_access", sa.String(), nullable=False, server_default="restricted"),
        sa.Column("general_capability", sa.String(), nullable=False, server_default="view"),
        sa.Column("expires_at", UTCDateTime(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("max_uploads", sa.Integer(), nullable=True),
        sa.Column("max_total_mb", sa.Integer(), nullable=True),
        sa.Column("uploads_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploads_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("is_disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "target_kind", "target_id", name="uq_file_shares_target"),
    )
    op.create_index("ix_file_shares_tenant_id", "file_shares", ["tenant_id"])
    op.create_index("ix_file_shares_target_id", "file_shares", ["target_id"])
    op.create_index("ix_file_shares_token", "file_shares", ["token"], unique=True)
    op.create_index("ix_file_shares_is_disabled", "file_shares", ["is_disabled"])

    op.create_table(
        "file_share_users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("share_id", sa.String(), sa.ForeignKey("file_shares.id"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("capability", sa.String(), nullable=False, server_default="view"),
        sa.UniqueConstraint("share_id", "user_id", name="uq_file_share_users"),
    )
    op.create_index("ix_file_share_users_share_id", "file_share_users", ["share_id"])
    op.create_index("ix_file_share_users_user_id", "file_share_users", ["user_id"])

    op.create_table(
        "file_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("file_id", sa.String(), sa.ForeignKey("files.id"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_file_links_tenant_id", "file_links", ["tenant_id"])
    op.create_index("ix_file_links_entity_type", "file_links", ["entity_type"])
    op.create_index("ix_file_links_entity_id", "file_links", ["entity_id"])
    op.create_index("ix_file_links_file_id", "file_links", ["file_id"])


def downgrade() -> None:
    op.drop_table("file_links")
    op.drop_table("file_share_users")
    op.drop_table("file_shares")
