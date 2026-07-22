"""ai_agents.key + is_system (Phase B-i S3, grill agent stable binding)

The grill binds its agent by a STABLE key, never by the mutable display name
(AC-BI-20b lets a tenant rename/swap the agent — a name lookup would silently
degrade the Grill tab to the "no agent" warning: the hardcode-a-tenant-editable-
value trap). Mirrors `ai_skills.key`/`is_system`.

Backfills any already-seeded "Ideation grill" agent to key='ideation-grill',
is_system=true so the S3 backfill/live-verify DB resolves it by key.

Revision id length: 14 chars (≤ 32 — a longer id passes create_all tests but
breaks a real deploy against `alembic_version.version_num VARCHAR(32)`).

Revision ID: ai_agent_key_s3
Revises: c91c717fcdb7
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ai_agent_key_s3"
down_revision: Union[str, Sequence[str], None] = "c91c717fcdb7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_agents", sa.Column("key", sa.String(), nullable=True))
    op.add_column(
        "ai_agents",
        sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_ai_agents_key", "ai_agents", ["key"])
    # Partial unique per (tenant, key) — only where a key is set (system agents).
    op.create_index(
        "uq_ai_agents_tenant_key",
        "ai_agents",
        ["tenant_id", "key"],
        unique=True,
        postgresql_where=sa.text("key IS NOT NULL"),
    )
    # Backfill a pre-seeded grill agent so an existing deploy resolves it by key.
    op.get_bind().execute(
        sa.text(
            "UPDATE ai_agents SET key = 'ideation-grill', is_system = true "
            "WHERE name = 'Ideation grill' AND key IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index("uq_ai_agents_tenant_key", table_name="ai_agents")
    op.drop_index("ix_ai_agents_key", table_name="ai_agents")
    op.drop_column("ai_agents", "is_system")
    op.drop_column("ai_agents", "key")
