"""Snapshot and index serialized workflow run correlation (sprint-4/19 S2)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "serialized_run_s4"
down_revision: Union[str, Sequence[str], None] = "agent_state_s4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("correlation_key", sa.String(), nullable=True))
    op.add_column(
        "workflow_runs",
        sa.Column("correlation_key_digest", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_workflow_runs_serialized_pending",
        "workflow_runs",
        [
            "tenant_id",
            "workflow_id",
            "correlation_key_digest",
            "status",
            "created_at",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_serialized_pending", table_name="workflow_runs")
    op.drop_column("workflow_runs", "correlation_key_digest")
    op.drop_column("workflow_runs", "correlation_key")
