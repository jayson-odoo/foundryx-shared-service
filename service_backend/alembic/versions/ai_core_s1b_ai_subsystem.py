"""Core AI subsystem tables + the `llm` one-per-type carve-out (Phase B-i S1)

Creates `ai_agents`, `ai_skills`, `ai_skill_versions`, `ai_conversations`,
`ai_messages`, `ai_traces`, `ai_spans` (plan §5).

`ai_conversations` / `ai_messages` land HERE even though slice 3 is what fills
them — so the grill engine adds no core migration later.

It also RECREATES `uq_connection_tenant_type` with `llm` added to the exempt set
(AC-BI-03b / Bi-D21): a tenant may hold several ACTIVE LLM connections, so an
agent can pick a cheap model for clustering and a strong one for grilling.
`uq_connection_tenant_provider` is untouched — two ACTIVE Anthropic rows stay
forbidden — and storage/email keep their one-active-per-type invariant.

Revision id length: 11 chars (≤ 32 — a longer id silently breaks a real deploy
against `alembic_version.version_num VARCHAR(32)` while passing create_all tests).

Revision ID: ai_core_s1b
Revises: dlc_s412b_log_settings
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 — UTCDateTime columns below

revision: str = "ai_core_s1b"
down_revision: Union[str, Sequence[str], None] = "dlc_s412b_log_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UTC = app.models.utc_datetime.UTCDateTime


def upgrade() -> None:
    # ── skills (two-tier: tenant_id NULL = platform default) ─────────────
    op.create_table(
        "ai_skills",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("active_version_id", sa.String(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_skills_tenant_id", "ai_skills", ["tenant_id"])
    op.create_index("ix_ai_skills_active_version_id", "ai_skills", ["active_version_id"])
    # PARTIAL uniques per tier (the BL-065 lesson — a plain unique over a
    # nullable column doesn't constrain the platform tier).
    op.create_index(
        "uq_ai_skills_tenant_key",
        "ai_skills",
        ["tenant_id", "key"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
        sqlite_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_index(
        "uq_ai_skills_platform_key",
        "ai_skills",
        ["key"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
        sqlite_where=sa.text("tenant_id IS NULL"),
    )

    op.create_table(
        "ai_skill_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("skill_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["ai_skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_skill_versions_skill_id", "ai_skill_versions", ["skill_id"])
    op.create_index("ix_ai_skill_versions_tenant_id", "ai_skill_versions", ["tenant_id"])
    op.create_index(
        "uq_ai_skill_versions_skill_version",
        "ai_skill_versions",
        ["skill_id", "version"],
        unique=True,
    )

    # ── agents ────────────────────────────────────────────────────────────
    op.create_table(
        "ai_agents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("connection_id", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=False, server_default=""),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("created_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        # SET NULL, not RESTRICT: a deleted connection must leave the agent
        # visible with its missing-prerequisite warning (AC-BI-06), not block
        # the delete or strand the UI.
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agents_tenant_id", "ai_agents", ["tenant_id"])
    op.create_index("ix_ai_agents_connection_id", "ai_agents", ["connection_id"])
    op.create_index("ix_ai_agents_tenant_name", "ai_agents", ["tenant_id", "name"])

    # ── agent ↔ skill many-many (AC-BI-06b) ───────────────────────────────
    # An agent equips a SET of skills. `tenant_id` denormalised (derived from
    # the owning agent) so join reads stay tenant-scoped. Both sides CASCADE:
    # deleting an agent or a skill just drops the link.
    op.create_table(
        "ai_agent_skills",
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("skill_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["ai_skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "skill_id"),
        sa.UniqueConstraint("agent_id", "skill_id", name="uq_ai_agent_skills"),
    )
    op.create_index("ix_ai_agent_skills_tenant_id", "ai_agent_skills", ["tenant_id"])
    op.create_index("ix_ai_agent_skills_skill_id", "ai_agent_skills", ["skill_id"])

    # ── transcript store (slice 3 fills these) ────────────────────────────
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("source_ids_json", sa.JSON(), nullable=True),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("grill_definition_key", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column("template_version", sa.Integer(), nullable=True),
        sa.Column("created_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_conversations_tenant_id", "ai_conversations", ["tenant_id"])
    op.create_index("ix_ai_conversations_target_type", "ai_conversations", ["target_type"])
    op.create_index("ix_ai_conversations_target_id", "ai_conversations", ["target_id"])

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("covered_fields_json", sa.JSON(), nullable=True),
        sa.Column("created_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_messages_conversation_id", "ai_messages", ["conversation_id"])
    op.create_index("ix_ai_messages_tenant_id", "ai_messages", ["tenant_id"])
    op.create_index(
        "ix_ai_messages_conversation_created",
        "ai_messages",
        ["conversation_id", "created_at"],
    )

    # ── traces + spans (OTel GenAI naming) ────────────────────────────────
    op.create_table(
        "ai_traces",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("agent_name", sa.String(), nullable=False, server_default=""),
        sa.Column("skill_key", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False, server_default=""),
        sa.Column("model", sa.String(), nullable=False, server_default=""),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("span_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["ai_conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_traces_tenant_id", "ai_traces", ["tenant_id"])
    op.create_index("ix_ai_traces_conversation_id", "ai_traces", ["conversation_id"])
    op.create_index("ix_ai_traces_agent_id", "ai_traces", ["agent_id"])
    op.create_index("ix_ai_traces_tenant_created", "ai_traces", ["tenant_id", "created_at"])
    # The retention sweep scans (status, created_at).
    op.create_index("ix_ai_traces_status_created", "ai_traces", ["status", "created_at"])

    op.create_table(
        "ai_spans",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("dotted_order", sa.String(), nullable=False, server_default=""),
        sa.Column("span_kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False, server_default=""),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", _UTC(), nullable=True),
        sa.Column("created_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["trace_id"], ["ai_traces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_spans_trace_id", "ai_spans", ["trace_id"])
    op.create_index("ix_ai_spans_tenant_id", "ai_spans", ["tenant_id"])
    op.create_index("ix_ai_spans_trace_order", "ai_spans", ["trace_id", "dotted_order"])

    # ── `llm` carve-out on the one-per-type index (AC-BI-03b) ─────────────
    op.drop_index("uq_connection_tenant_type", table_name="connections")
    op.create_index(
        "uq_connection_tenant_type",
        "connections",
        ["tenant_id", "type"],
        unique=True,
        postgresql_where=sa.text("type NOT IN ('payment', 'llm') AND is_active"),
        sqlite_where=sa.text("type NOT IN ('payment', 'llm') AND is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_connection_tenant_type", table_name="connections")
    op.create_index(
        "uq_connection_tenant_type",
        "connections",
        ["tenant_id", "type"],
        unique=True,
        postgresql_where=sa.text("type != 'payment' AND is_active"),
        sqlite_where=sa.text("type != 'payment' AND is_active"),
    )

    op.drop_table("ai_spans")
    op.drop_table("ai_traces")
    op.drop_table("ai_messages")
    op.drop_table("ai_conversations")
    op.drop_table("ai_agent_skills")
    op.drop_table("ai_agents")
    op.drop_table("ai_skill_versions")
    op.drop_table("ai_skills")
