"""omnichannel plan 31 S1 - workflow_contact_fires (trigger once per contact).

Adds `workflow_contact_fires` (D-A5-4, §5.4) - the "trigger once per contact"
claim table backing `TriggerDef.fire_guard` for every plan-31 trigger. Brand
new table (no existing-column ALTER needed) - `create_all` picks it up on a
local `init_db` DB too; this migration is what a live Postgres deploy runs.
Idempotent guard (inspector check), mirrors `0010_omni_contacts_module`'s
style. Revision id <= 32 chars.

Down-revision note: this lane (S31) branched at `58759ed`, where the module
head was `0010_omni_contacts_module`. Re-parented at the plan 31 merge onto
`0012_omni_team_assignment` (plan 29/A4 landed `0011_omni_broadcasts`, plan
28/A8 landed `0012_omni_team_assignment` - both merged to main before this
branch did, same rebase-the-chain-tip pattern `0010`'s own docstring used for
A2 vs A3).

Revision ID: 0013_omni_workflow_fires
Revises: 0012_omni_team_assignment
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

# UTCDateTime columns ride sa.DateTime(timezone=True) here (module-migration
# convention, matching 0006); import kept for parity with the house rule.
import app.models.utc_datetime  # noqa: F401

revision = "0013_omni_workflow_fires"
down_revision = "0012_omni_team_assignment"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema=SCHEMA))
    if "workflow_contact_fires" not in tables:
        op.create_table(
            "workflow_contact_fires",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("workflow_id", sa.String(), nullable=False, index=True),
            sa.Column("contact_id", sa.String(), nullable=False, index=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint(
                "tenant_id", "workflow_id", "contact_id", name="uq_workflow_contact_fire"
            ),
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_table("workflow_contact_fires", schema=SCHEMA)
