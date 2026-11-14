"""omnichannel plan 31 S5 - business hours columns on omnichannel_settings.

Adds `omnichannel_settings.business_hours_json` + `business_timezone`
(D-A5-13/§5.4) - the workspace's own row, else the tenant-default row
(workspace_id IS NULL), resolved by `services/business_hours.py` for the
`omnichannel.business_hours` workflow action. Both nullable, no backfill
(an unconfigured workspace/tenant simply has neither column set - the action
fails loudly per AC-WFP-56 rather than guessing "always open").

Idempotent `ADD COLUMN IF NOT EXISTS` (mirrors `0014_omni_round_robin_cursor`'s
style) so a rerun / a `create_all` local DB (which already has the columns via
the model) is a no-op either way.

Down-revision note: this lane (S31) chain is 0010 (main at branch point) ->
0013 (S1) -> 0014 (S2) -> 0015 (S4) -> this file. Tracked under the same
merge-time renumber as 0013/0014/0015 (BL-SS-120) once A4/A8 land.

Revision ID: 0016_omni_business_hours
Revises: 0015_omni_workflow_waits
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_omni_business_hours"
down_revision = "0015_omni_workflow_waits"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f'ALTER TABLE "{SCHEMA}".omnichannel_settings '
            "ADD COLUMN IF NOT EXISTS business_hours_json JSON"
        )
        op.execute(
            f'ALTER TABLE "{SCHEMA}".omnichannel_settings '
            "ADD COLUMN IF NOT EXISTS business_timezone VARCHAR"
        )
    else:
        inspector = sa.inspect(bind)
        cols = {c["name"] for c in inspector.get_columns("omnichannel_settings", schema=SCHEMA)}
        with op.batch_alter_table("omnichannel_settings", schema=SCHEMA) as batch_op:
            if "business_hours_json" not in cols:
                batch_op.add_column(sa.Column("business_hours_json", sa.JSON(), nullable=True))
            if "business_timezone" not in cols:
                batch_op.add_column(sa.Column("business_timezone", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("omnichannel_settings", schema=SCHEMA) as batch_op:
        batch_op.drop_column("business_timezone")
        batch_op.drop_column("business_hours_json")
