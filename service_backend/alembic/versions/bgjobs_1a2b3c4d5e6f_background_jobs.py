"""background_jobs table (sprint-4/10 slice 1)

Centralized, type-dispatched background-jobs table (core public). Storage
migration is its first ``type``; existing typed job tables are untouched.

Revision id length: 19 chars (≤ 32 — alembic_version.version_num is VARCHAR(32)).

Revision ID: bgjobs_1a2b3c4d5e6f
Revises: d6e7f8a9b0c1
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import JSON as GenericJSON

import app.models.utc_datetime  # noqa: F401 — UTCDateTime columns

revision: str = "bgjobs_1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = GenericJSON(none_as_null=True)


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("payload_json", _JSON, nullable=True),
        sa.Column("result_json", _JSON, nullable=True),
        sa.Column("cursor_json", _JSON, nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            app.models.utc_datetime.UTCDateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", app.models.utc_datetime.UTCDateTime(), nullable=True),
        sa.Column("finished_at", app.models.utc_datetime.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_background_jobs_tenant_id", "background_jobs", ["tenant_id"])
    op.create_index("ix_background_jobs_type", "background_jobs", ["type"])
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_index("ix_background_jobs_type", table_name="background_jobs")
    op.drop_index("ix_background_jobs_tenant_id", table_name="background_jobs")
    op.drop_table("background_jobs")
