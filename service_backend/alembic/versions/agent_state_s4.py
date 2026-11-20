"""Durable state for stateful workflow AI Agent nodes (sprint-4/19 S1)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401

revision: str = "agent_state_s4"
down_revision: Union[str, Sequence[str], None] = "ai_msg_summary_s3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UTC = app.models.utc_datetime.UTCDateTime


def upgrade() -> None:
    op.create_table(
        "workflow_agent_states",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("correlation_key", sa.String(), nullable=False),
        sa.Column("state_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("provenance_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("pending_question", sa.String(), nullable=True),
        sa.Column("pending_field", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "workflow_id",
            "node_id",
            "correlation_key",
            name="uq_workflow_agent_state_scope",
        ),
    )
    op.create_index("ix_workflow_agent_states_tenant_id", "workflow_agent_states", ["tenant_id"])
    op.create_index("ix_workflow_agent_states_workflow_id", "workflow_agent_states", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_agent_states_workflow_id", table_name="workflow_agent_states")
    op.drop_index("ix_workflow_agent_states_tenant_id", table_name="workflow_agent_states")
    op.drop_table("workflow_agent_states")
