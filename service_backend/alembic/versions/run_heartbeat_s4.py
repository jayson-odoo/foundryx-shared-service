"""``workflow_runs.heartbeat_at`` (sprint-4/19 review fix, AC-SAR-37/39).

A serialized run's worker stamps it while executing; the drain refuses to
advance past a RUNNING row whose heartbeat is fresh and the beat reaper fails
one whose heartbeat stopped. Revision id length: 16 chars (<= 32).

Revision ID: run_heartbeat_s4
Revises: code_action_s4
Create Date: 2026-08-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime

revision: str = "run_heartbeat_s4"
down_revision: Union[str, Sequence[str], None] = "code_action_s4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("heartbeat_at", app.models.utc_datetime.UTCDateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "heartbeat_at")
