"""omnichannel plan 31 S4 - workflow_waits (parked runs: ask a question, wait).

Adds `workflow_waits` (§5.4) - the module-side index from (tenant, workspace,
contact) to a run parked by `omnichannel.ask_question`, and the deadline-only
row a plain `omnichannel.wait` parks. Brand new table (no existing-column
ALTER), idempotent inspector guard, mirrors `0013_omni_workflow_fires`'s style.
Revision id <= 32 chars.

`contact_id`/`workspace_id` are NULLABLE on purpose: a `delay` wait has no
contact, so its NULL never collides with the UNIQUE (tenant_id, contact_id)
constraint that enforces "one open question per contact" (D-A5-9).

Down-revision note: this lane (S31) branched at `58759ed`, where the module head
was `0010_omni_contacts_module`; S1/S2 added `0013`/`0014` on top. Plan 29 (A4)
and plan 28 (A8) are expected to add their own revisions on sibling branches -
the merge step must renumber/rebase this chain onto whichever lands first
(tracked as BL-SS-120).

Revision ID: 0015_omni_workflow_waits
Revises: 0014_omni_round_robin_cursor
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

# UTCDateTime columns ride sa.DateTime(timezone=True) here (module-migration
# convention, matching 0006/0013); import kept for parity with the house rule.
import app.models.utc_datetime  # noqa: F401

revision = "0015_omni_workflow_waits"
down_revision = "0014_omni_round_robin_cursor"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema=SCHEMA))
    if "workflow_waits" not in tables:
        op.create_table(
            "workflow_waits",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("workspace_id", sa.String(), nullable=True, index=True),
            sa.Column("contact_id", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=False, index=True),
            sa.Column("workflow_id", sa.String(), nullable=False, index=True),
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("answer_spec_json", sa.JSON(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "is_test", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["workspace_id"], [f"{SCHEMA}.workspaces.id"]
            ),
            sa.ForeignKeyConstraint(["contact_id"], [f"{SCHEMA}.contacts.id"]),
            sa.UniqueConstraint(
                "tenant_id", "contact_id", name="uq_workflow_wait_contact"
            ),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_workflow_waits_due",
            "workflow_waits",
            ["tenant_id", "deadline_at"],
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_index("ix_workflow_waits_due", table_name="workflow_waits", schema=SCHEMA)
    op.drop_table("workflow_waits", schema=SCHEMA)
