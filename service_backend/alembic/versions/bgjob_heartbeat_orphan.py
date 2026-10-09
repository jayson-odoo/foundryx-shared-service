"""``background_jobs.heartbeat_at`` - job liveness for the orphan sweep.

Prod incident 2026-09-07 16:59Z: a PO sync job was mid-run when the
blue/green deploy stopped the old colour (30s drain); its ``background_jobs``
row stayed ``running`` and its ``ac_sync_run`` row open, every scheduler tick
skipped the task ("still in progress"), and after 60 minutes the scheduler
only wrote a JOB_STUCK skip and paused - nothing ever released it. The
worker now stamps ``heartbeat_at`` per page / push batch (its OWN short
transaction, same shape as ``workflow_runs.heartbeat_at``), and
``JobService.fail_orphaned_running_jobs`` fails a RUNNING row whose
``coalesce(heartbeat_at, started_at, created_at)`` is older than
``settings.background_job_orphan_after_minutes`` (at startup and from the
scheduler). Nullable, NO backfill: NULL = legacy / pre-first-checkpoint and
falls back to ``started_at``. Revision id length: 22 chars (<= 32).

Revision ID: bgjob_heartbeat_orphan
Revises: teams_core_s428
Create Date: 2026-09-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime

revision: str = "bgjob_heartbeat_orphan"
down_revision: Union[str, Sequence[str], None] = "teams_core_s428"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "background_jobs",
        sa.Column("heartbeat_at", app.models.utc_datetime.UTCDateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("background_jobs", "heartbeat_at")
