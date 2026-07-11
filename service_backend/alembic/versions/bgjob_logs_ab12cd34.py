"""background_jobs.logs_json (sprint-4/12)

Adds a milestone log column to background_jobs so a job (storage migration first)
surfaces human-readable troubleshooting logs on its detail page.

Revision id length: 18 chars (≤ 32 — alembic_version.version_num is VARCHAR(32)).

Revision ID: bgjob_logs_ab12cd34
Revises: migrate_storage_perm410
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import JSON as GenericJSON

revision: str = "bgjob_logs_ab12cd34"
down_revision: Union[str, Sequence[str], None] = "migrate_storage_perm410"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = GenericJSON(none_as_null=True)


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("logs_json", _JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("background_jobs", "logs_json")
