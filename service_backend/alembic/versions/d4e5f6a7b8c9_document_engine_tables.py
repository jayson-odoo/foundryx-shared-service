"""Document engine tables - folders / files / file_versions / attachment_types /
document_settings / document_download_jobs (plan sprint-3/04)

Revision ID: d4e5f6a7b8c9
Revises: 4f5a6b7c8d9e
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns (workflow lesson)
from app.models.utc_datetime import UTCDateTime

revision = "d4e5f6a7b8c9"
down_revision = "4f5a6b7c8d9e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("parent_id", sa.String(), sa.ForeignKey("folders.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("deleted_by", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_folders_tenant_id", "folders", ["tenant_id"])
    op.create_index("ix_folders_parent_id", "folders", ["parent_id"])
    op.create_index("ix_folders_is_deleted", "folders", ["is_deleted"])

    op.create_table(
        "attachment_types",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("allowed_exts_json", sa.JSON(), nullable=False),
        sa.Column("max_mb", sa.Integer(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_attachment_types_tenant_id", "attachment_types", ["tenant_id"])

    op.create_table(
        "files",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("folder_id", sa.String(), sa.ForeignKey("folders.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("current_version_id", sa.String(), nullable=True),
        sa.Column(
            "attachment_type_id",
            sa.String(),
            sa.ForeignKey("attachment_types.id"),
            nullable=True,
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.Column("deleted_by", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_files_tenant_id", "files", ["tenant_id"])
    op.create_index("ix_files_folder_id", "files", ["folder_id"])
    op.create_index("ix_files_is_deleted", "files", ["is_deleted"])

    op.create_table(
        "file_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "file_id",
            sa.String(),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("uploaded_by", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_file_versions_file_id", "file_versions", ["file_id"])

    op.create_table(
        "document_settings",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("public_sharing", sa.String(), nullable=False, server_default="off"),
        sa.Column("default_max_file_mb", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("storage_quota_mb", sa.Integer(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "document_download_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="zip"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("zip_storage_key", sa.String(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("ready_at", UTCDateTime(), nullable=True),
    )
    op.create_index(
        "ix_document_download_jobs_tenant_id", "document_download_jobs", ["tenant_id"]
    )
    op.create_index(
        "ix_document_download_jobs_user_id", "document_download_jobs", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("document_download_jobs")
    op.drop_table("document_settings")
    op.drop_table("file_versions")
    op.drop_table("files")
    op.drop_table("attachment_types")
    op.drop_table("folders")
