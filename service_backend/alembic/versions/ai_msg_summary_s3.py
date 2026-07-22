"""ai_messages.captured_summary_json (Phase B-i S3, grill captured summary)

The grill turn's ONE structured call now also returns a running per-field
captured summary (AC-BI-24c) — a {fieldKey: shortValue} map the Grill panel
renders. It is persisted on the assistant turn so the panel survives a reload /
resumed session (durable draft, AC-BI-21). Additive, nullable JSON — no backfill
needed (an absent value is an empty summary until the next turn).

Revision id length: 17 chars (<= 32 — a longer id passes create_all tests but
breaks a real deploy against `alembic_version.version_num VARCHAR(32)`).

Revision ID: ai_msg_summary_s3
Revises: ai_agent_key_s3
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ai_msg_summary_s3"
down_revision: Union[str, Sequence[str], None] = "ai_agent_key_s3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_messages",
        sa.Column("captured_summary_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_messages", "captured_summary_json")
