"""omnichannel plan 52 - continuous respond.io sync (lane SS-MIGRATION-SYNC).

Adds `migration_syncs` (one row per tenant + workspace) and
`migration_sync_hints` (webhook-flagged contact ids awaiting the next tick).
Both tables are new and start empty, so no backfill is needed. Idempotent
guards (inspector checks), same style as `0018_omni_migration_uploads`.
Revision id <= 32 chars.

Revision ID: 0025_omni_migration_sync
Revises: 0024_omni_workflow_owner
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_omni_migration_sync"
down_revision = "0024_omni_workflow_owner"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema=SCHEMA))

    if "migration_syncs" not in tables:
        op.create_table(
            "migration_syncs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey(f"{SCHEMA}.workspaces.id"), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("paused_reason", sa.String(), nullable=True),
            sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="15"),
            sa.Column("full_sweep_hours", sa.Integer(), nullable=False, server_default="6"),
            sa.Column("webhook_secret_enc", sa.Text(), nullable=False),
            sa.Column("created_by_user_id", sa.String(), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_full_sweep_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("running_job_id", sa.String(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_result_json", sa.JSON(), nullable=True),
            sa.Column("totals_json", sa.JSON(), nullable=True),
            sa.Column("source_contact_count", sa.Integer(), nullable=True),
            sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "workspace_id", name="uq_migration_syncs_workspace"),
            schema=SCHEMA,
        )
        op.create_index("ix_migration_syncs_tenant_id", "migration_syncs", ["tenant_id"], schema=SCHEMA)
        op.create_index("ix_migration_syncs_next_sync_at", "migration_syncs", ["next_sync_at"], schema=SCHEMA)

    if "migration_sync_hints" not in tables:
        op.create_table(
            "migration_sync_hints",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column(
                "sync_id", sa.String(),
                sa.ForeignKey(f"{SCHEMA}.migration_syncs.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("external_contact_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("sync_id", "external_contact_id", name="uq_migration_sync_hints_contact"),
            schema=SCHEMA,
        )
        op.create_index("ix_migration_sync_hints_tenant_id", "migration_sync_hints", ["tenant_id"], schema=SCHEMA)
        op.create_index("ix_migration_sync_hints_sync_id", "migration_sync_hints", ["sync_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_migration_sync_hints_sync_id", table_name="migration_sync_hints", schema=SCHEMA)
    op.drop_index("ix_migration_sync_hints_tenant_id", table_name="migration_sync_hints", schema=SCHEMA)
    op.drop_table("migration_sync_hints", schema=SCHEMA)
    op.drop_index("ix_migration_syncs_next_sync_at", table_name="migration_syncs", schema=SCHEMA)
    op.drop_index("ix_migration_syncs_tenant_id", table_name="migration_syncs", schema=SCHEMA)
    op.drop_table("migration_syncs", schema=SCHEMA)
