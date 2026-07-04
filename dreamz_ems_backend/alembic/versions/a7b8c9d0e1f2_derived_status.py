"""Derived / computed status (sprint-4/03) — status_transitions.trigger_mode.

An 'auto' edge is fired by the engine when its conditions_json becomes true
(reevaluate), never by a user. Default 'manual' keeps every existing edge a
normal action button. Indexed on (from_status_id, trigger_mode) for the re-eval
outgoing-auto-edge lookup.

Revision ID: a7b8c9d0e1f2
Revises: d5e6f7a8b9c0
Create Date: 2026-06-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "status_transitions",
        sa.Column(
            "trigger_mode",
            sa.String(),
            nullable=False,
            server_default="manual",
        ),
    )
    op.create_index(
        "ix_transition_from_trigger",
        "status_transitions",
        ["from_status_id", "trigger_mode"],
    )


def downgrade() -> None:
    op.drop_index("ix_transition_from_trigger", table_name="status_transitions")
    op.drop_column("status_transitions", "trigger_mode")
