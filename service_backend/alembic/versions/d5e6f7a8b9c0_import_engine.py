"""Import engine tables (sprint-3/09, F8) - import_jobs + import_settings.

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

from app.models.utc_datetime import UTCDateTime  # house autogen gotcha

revision = "d5e6f7a8b9c0"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("abort_on_invalid", sa.Boolean(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("trigger_automations", sa.Boolean(), nullable=False),
        sa.Column("assumed_tz", sa.String(), nullable=True),
        sa.Column("file_storage_key", sa.String(), nullable=True),
        sa.Column("files_purged", sa.Boolean(), nullable=False),
        sa.Column("sheet_name", sa.String(), nullable=True),
        sa.Column("mapping_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("valid_rows", sa.Integer(), nullable=False),
        sa.Column("invalid_rows", sa.Integer(), nullable=False),
        sa.Column("error_report_key", sa.String(), nullable=True),
        sa.Column("errors_json", sa.JSON(), nullable=True),
        sa.Column("created_ids", sa.JSON(), nullable=True),
        sa.Column("updated_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("validated_at", UTCDateTime(), nullable=True),
        sa.Column("committed_at", UTCDateTime(), nullable=True),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_jobs_tenant_id", "import_jobs", ["tenant_id"])
    op.create_index("ix_import_jobs_status", "import_jobs", ["status"])
    op.create_table(
        "import_settings",
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("max_rows", sa.Integer(), nullable=True),
        sa.Column("max_file_mb", sa.Integer(), nullable=True),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id"),
    )


def downgrade() -> None:
    op.drop_table("import_settings")
    op.drop_index("ix_import_jobs_status", table_name="import_jobs")
    op.drop_index("ix_import_jobs_tenant_id", table_name="import_jobs")
    op.drop_table("import_jobs")
