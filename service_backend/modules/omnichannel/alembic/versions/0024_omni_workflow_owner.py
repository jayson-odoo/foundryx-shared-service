"""omnichannel plan 38 gap 7 - workflows owned by an API key's workspace.

Creates ``workflow_owners``: one row per workflow built through a workspace
API key. ``workflow_id`` is a plain unique indexed column (a soft reference to
core ``public.workflows.id``, no cross-schema foreign key); ``workspace_id``
references this schema's ``workspaces``.

No data step: every workflow that exists today stays unowned and dashboard
only.

Idempotent: the table and its indexes are created only when absent.

Downgrade drops the table: owned workflows become unowned and stay in the
dashboard.

Revision ID: 0024_omni_workflow_owner
Revises: 0023_omni_webhook_all_channels
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

# UTCDateTime columns ride sa.DateTime(timezone=True) here (module-migration
# convention, see 0021_omni_webchat).
import app.models.utc_datetime  # noqa: F401

revision = "0024_omni_workflow_owner"
down_revision = "0023_omni_webhook_all_channels"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"
TABLE = "workflow_owners"


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{SCHEMA}.workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        f"ix_{TABLE}_tenant_id", TABLE, ["tenant_id"], schema=SCHEMA
    )
    op.create_index(
        f"ix_{TABLE}_workspace_id", TABLE, ["workspace_id"], schema=SCHEMA
    )
    op.create_index(
        f"ix_{TABLE}_workflow_id",
        TABLE,
        ["workflow_id"],
        unique=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        op.drop_table(TABLE, schema=SCHEMA)
