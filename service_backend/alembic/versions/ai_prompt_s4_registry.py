"""AI prompt registry: ai_prompt_versions + ai_prompt_labels (Meetings S4, R4)

Platform-global tables (no `tenant_id`, deliberate - prompts are platform
infra, R4/R5). Seeds `meetings_minutes` v1 + a `production` label pointing at
it, so the minutes job resolves a real row on day one instead of only ever
exercising the hardcoded fallback (`app/services/ai_prompt_registry.py`).

The `ai_prompts.manage` permission catalog row is NOT created here - it rides
the existing platform-permission sync (`app/permissions/platform_permissions.csv`
+ `PermissionService.sync_platform()`, called by `seed_permissions` on every
`scripts.bootstrap_db` run, which every container boot performs via
`start.sh`) and is granted to the seeded Platform Admin role by
`seed_platform_admin` the same way, idempotently, on the next restart/deploy -
no bespoke grant migration needed for a platform-only key.

Revision id length: 20 chars (<= 32).

Revision ID: ai_prompt_s4_registry
Revises: run_heartbeat_s4
Create Date: 2026-09-01
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime

revision: str = "ai_prompt_s4_registry"
down_revision: Union[str, Sequence[str], None] = "run_heartbeat_s4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UTC = app.models.utc_datetime.UTCDateTime

# Keep in sync with app/services/ai_prompt_registry.py's
# `_meetings_minutes_fallback()` - this is the same text, seeded as v1 so the
# job resolves a real DB row (not just the hardcoded fallback) on day one.
_MEETINGS_MINUTES_V1 = (
    'You are taking minutes for a meeting titled "{{title}}".\n\n'
    "Participants: {{participants}}\n\n"
    "Write the minutes in {{language}}. Use only what is said in the "
    "transcript below - never invent a decision, an action item, or a "
    "fact that was not said.\n\n"
    "Transcript:\n"
    "{{transcript}}\n\n"
    "Return STRICT JSON only, no prose, no markdown fence, with exactly "
    "these keys:\n\n"
    "{\n"
    '  "summary": "one short paragraph capturing what the meeting covered",\n'
    '  "decisions": ["decision made, one per entry"],\n'
    '  "action_items": [\n'
    '    {"text": "what needs to be done", "owner_email": "email as stated or null", '
    '"due_on": "YYYY-MM-DD or null"}\n'
    "  ],\n"
    '  "open_questions": ["question raised but not resolved"],\n'
    '  "topic_notes": [\n'
    '    {"topic": "topic discussed", "notes": "key points raised on that topic"}\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Every list may be empty ([]) when the transcript has nothing for it - "
    "never invent content to fill a section.\n"
    "- owner_email is the participant's email exactly as it appears in the "
    "transcript or participant list; use null when no owner is named.\n"
    "- due_on is an ISO date (YYYY-MM-DD); use null when no date is stated.\n"
    "- Write summary, decisions, open_questions and topic_notes in "
    "{{language}}. Never translate or alter the transcript itself.\n"
)
_MEETINGS_MINUTES_VARIABLES = ["title", "participants", "language", "transcript"]


def upgrade() -> None:
    op.create_table(
        "ai_prompt_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False, server_default=""),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("commit_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_prompt_versions_name", "ai_prompt_versions", ["name"])
    op.create_index(
        "uq_ai_prompt_versions_name_version",
        "ai_prompt_versions",
        ["name", "version"],
        unique=True,
    )

    op.create_table(
        "ai_prompt_labels",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", _UTC(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["ai_prompt_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_prompt_labels_name", "ai_prompt_labels", ["name"])
    op.create_index(
        "uq_ai_prompt_labels_name_label", "ai_prompt_labels", ["name", "label"], unique=True
    )

    # ── seed meetings_minutes v1 + production label ───────────────────────
    version_id = str(uuid.uuid4())
    label_id = str(uuid.uuid4())

    versions = sa.table(
        "ai_prompt_versions",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("version", sa.Integer),
        sa.column("template", sa.Text),
        sa.column("variables", sa.JSON),
        sa.column("commit_message", sa.Text),
    )
    op.bulk_insert(
        versions,
        [
            {
                "id": version_id,
                "name": "meetings_minutes",
                "version": 1,
                "template": _MEETINGS_MINUTES_V1,
                "variables": _MEETINGS_MINUTES_VARIABLES,
                "commit_message": "Initial minutes prompt.",
            }
        ],
    )

    labels = sa.table(
        "ai_prompt_labels",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("label", sa.String),
        sa.column("version_id", sa.String),
    )
    op.bulk_insert(
        labels,
        [
            {
                "id": label_id,
                "name": "meetings_minutes",
                "label": "production",
                "version_id": version_id,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("ai_prompt_labels")
    op.drop_table("ai_prompt_versions")
