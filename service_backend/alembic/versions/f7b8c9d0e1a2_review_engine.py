"""generic review/approval engine (plan sprint-4/06 Part 2)

Creates the five core review tables (configurations / roles / role-actors /
assignments / decisions). All tenant-scoped (``tenant_id`` indexed); cross-engine
references (status ids, bound persona/staff-role ids, actor ids) are plain string
columns, not FKs (the polymorphic-target_id rule - they may point into a module
schema).

Revision ID: f7b8c9d0e1a2
Revises: e40b2c4c0135
"""
from alembic import op
import sqlalchemy as sa

import app.models.utc_datetime as utc  # UTCDateTime columns


revision = "f7b8c9d0e1a2"
down_revision = "e40b2c4c0135"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_configurations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("form_id", sa.String(), nullable=False),
        sa.Column("review_form_id", sa.String(), nullable=False),
        sa.Column("required_review_count", sa.Integer(), nullable=False),
        sa.Column("score_field_key", sa.String(), nullable=True),
        # Event/context binding (AC-06-25/24) - plain indexed cols (BL-030).
        sa.Column("context_type", sa.String(), nullable=True),
        sa.Column("context_id", sa.String(), nullable=True),
        sa.Column("window_start", utc.UTCDateTime(), nullable=True),
        sa.Column("window_end", utc.UTCDateTime(), nullable=True),
        sa.Column("review_start_status_id", sa.String(), nullable=True),
        sa.Column("revisions_status_id", sa.String(), nullable=True),
        sa.Column("accepted_status_id", sa.String(), nullable=True),
        sa.Column("rejected_status_id", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", utc.UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", utc.UTCDateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_review_configurations_tenant_id", "review_configurations", ["tenant_id"])
    op.create_index("ix_review_configurations_form_id", "review_configurations", ["form_id"])
    op.create_index("ix_review_configurations_review_form_id", "review_configurations", ["review_form_id"])
    op.create_index("ix_review_configurations_context_type", "review_configurations", ["context_type"])
    op.create_index("ix_review_configurations_context_id", "review_configurations", ["context_id"])

    op.create_table(
        "review_roles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("review_configuration_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("can_submit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_decide", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actor_source", sa.String(), nullable=False),
        sa.Column("actor_identity_kind", sa.String(), nullable=False),
        sa.Column("bound_persona_id", sa.String(), nullable=True),
        sa.Column("bound_staff_role_id", sa.String(), nullable=True),
        sa.Column("conditions_json", sa.JSON(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_review_roles_tenant_id", "review_roles", ["tenant_id"])
    op.create_index("ix_review_roles_review_configuration_id", "review_roles", ["review_configuration_id"])

    op.create_table(
        "review_role_actors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("role_id", sa.String(), nullable=False),
        sa.Column("actor_kind", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("conditions_json", sa.JSON(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_review_role_actors_tenant_id", "review_role_actors", ["tenant_id"])
    op.create_index("ix_review_role_actors_role_id", "review_role_actors", ["role_id"])

    op.create_table(
        "review_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("review_configuration_id", sa.String(), nullable=False),
        sa.Column("reviewed_submission_group_id", sa.String(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("role_id", sa.String(), nullable=False),
        sa.Column("actor_kind", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("review_submission_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("assigned_at", utc.UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", utc.UTCDateTime(), nullable=True),
        sa.UniqueConstraint(
            "review_configuration_id",
            "reviewed_submission_group_id",
            "actor_kind",
            "actor_id",
            "revision_number",
            name="uq_review_assignments_actor_revision",
        ),
    )
    op.create_index("ix_review_assignments_tenant_id", "review_assignments", ["tenant_id"])
    op.create_index("ix_review_assignments_review_configuration_id", "review_assignments", ["review_configuration_id"])
    op.create_index("ix_review_assignments_reviewed_submission_group_id", "review_assignments", ["reviewed_submission_group_id"])
    op.create_index("ix_review_assignments_role_id", "review_assignments", ["role_id"])

    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("review_configuration_id", sa.String(), nullable=False),
        sa.Column("reviewed_submission_group_id", sa.String(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("decider_kind", sa.String(), nullable=False),
        sa.Column("decider_id", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("decided_at", utc.UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "review_configuration_id",
            "reviewed_submission_group_id",
            "revision_number",
            name="uq_review_decisions_group_revision",
        ),
    )
    op.create_index("ix_review_decisions_tenant_id", "review_decisions", ["tenant_id"])
    op.create_index("ix_review_decisions_review_configuration_id", "review_decisions", ["review_configuration_id"])
    op.create_index("ix_review_decisions_reviewed_submission_group_id", "review_decisions", ["reviewed_submission_group_id"])


def downgrade() -> None:
    op.drop_table("review_decisions")
    op.drop_table("review_assignments")
    op.drop_table("review_role_actors")
    op.drop_table("review_roles")
    op.drop_table("review_configurations")
