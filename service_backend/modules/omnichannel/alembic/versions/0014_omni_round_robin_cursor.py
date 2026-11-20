"""omnichannel plan 31 S2 - workspaces.round_robin_cursor.

Adds `workspaces.round_robin_cursor` (D-A5-15, §5.4) - the last-assigned
member's user id for `omnichannel.assign_conversation`'s round-robin mode.
Idempotent `ADD COLUMN IF NOT EXISTS` (mirrors `0010_omni_contacts_module`'s
style) so a rerun / a `create_all` local DB (which already has the column via
the model) is a no-op either way.

Down-revision note: this lane (S31) branched at `58759ed`; S1 already claimed
`0013` on top of `0010`. Plan 29 (A4) and plan 28 (A8) are expected to add
their own revisions on sibling branches - the merge step must renumber/rebase
this file's `down_revision` onto whichever of those lands first (same
rebase-the-chain-tip pattern `0010`'s own docstring used for A2 vs A3).

Revision ID: 0014_omni_round_robin_cursor
Revises: 0013_omni_workflow_fires
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_omni_round_robin_cursor"
down_revision = "0013_omni_workflow_fires"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f'ALTER TABLE "{SCHEMA}".workspaces ADD COLUMN IF NOT EXISTS round_robin_cursor VARCHAR'
        )
    else:
        inspector = sa.inspect(bind)
        cols = {c["name"] for c in inspector.get_columns("workspaces", schema=SCHEMA)}
        if "round_robin_cursor" not in cols:
            with op.batch_alter_table("workspaces", schema=SCHEMA) as batch_op:
                batch_op.add_column(sa.Column("round_robin_cursor", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspaces", schema=SCHEMA) as batch_op:
        batch_op.drop_column("round_robin_cursor")
