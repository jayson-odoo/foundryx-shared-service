"""Form engine tables - forms / form_versions / form_submissions (plan sprint-3/01)

Revision ID: 4f5a6b7c8d9e
Revises: 3e4f5a6b7c8d
Create Date: 2026-06-10

"""
from alembic import op
import sqlalchemy as sa

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns (workflow lesson)
from app.models.utc_datetime import UTCDateTime

revision = "4f5a6b7c8d9e"
down_revision = "3e4f5a6b7c8d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forms",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("access", sa.String(), nullable=False, server_default="internal"),
        sa.Column("draft_definition_json", sa.JSON(), nullable=False),
        sa.Column("current_version_id", sa.String(), nullable=True),
        sa.Column("opens_at", UTCDateTime(), nullable=True),
        sa.Column("closes_at", UTCDateTime(), nullable=True),
        sa.Column("max_submissions", sa.Integer(), nullable=True),
        sa.Column("submission_limit_per_user", sa.Integer(), nullable=True),
        sa.Column("pinned_columns_json", sa.JSON(), nullable=True),
        sa.Column("display_mode", sa.String(), nullable=False, server_default="paged"),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_forms_tenant_slug"),
    )
    op.create_index("ix_forms_tenant_id", "forms", ["tenant_id"])
    op.create_index("ix_forms_status", "forms", ["status"])

    op.create_table(
        "form_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "form_id",
            sa.String(),
            sa.ForeignKey("forms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("published_by", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("form_id", "version_number", name="uq_form_versions_number"),
    )
    op.create_index("ix_form_versions_form_id", "form_versions", ["form_id"])

    op.create_table(
        "form_submissions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column(
            "form_id",
            sa.String(),
            sa.ForeignKey("forms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id", sa.String(), sa.ForeignKey("form_versions.id"), nullable=False
        ),
        sa.Column("status_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("subject_type", sa.String(), nullable=True),
        sa.Column("subject_id", sa.String(), nullable=True),
        sa.Column("answers_json", sa.JSON(), nullable=False),
        sa.Column("submitted_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_form_submissions_tenant_id", "form_submissions", ["tenant_id"])
    op.create_index("ix_form_submissions_form_id", "form_submissions", ["form_id"])
    op.create_index("ix_form_submissions_status_id", "form_submissions", ["status_id"])
    op.create_index("ix_form_submissions_user_id", "form_submissions", ["user_id"])


def downgrade() -> None:
    op.drop_table("form_submissions")
    op.drop_table("form_versions")
    op.drop_table("forms")
