"""App Store (plan 08): global module catalog + per-tenant install state.

- `modules`: synced from on-disk manifest.json at bootstrap (delist, not delete)
- `tenant_modules`: INSTALL→ACTIVE / DEACTIVATE→INACTIVE / UNINSTALL→row gone;
  `installed_version` gates features (D4 — version gating, not code pinning)

The transitional backfill (existing tenants with pre-App-Store omnichannel
data → ACTIVE rows) is data-driven and runs in `bootstrap_modules()`, not here
— a core migration must not read module-schema tables.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
"""
import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "modules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icon", sa.String(), nullable=True),
        sa.Column("is_listed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_modules_name"),
    )
    op.create_index("ix_modules_name", "modules", ["name"])

    op.create_table(
        "tenant_modules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("module_id", sa.String(), sa.ForeignKey("modules.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("installed_version", sa.String(), nullable=False),
        sa.Column("installed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "module_id", name="uq_tenant_module"),
    )
    op.create_index("ix_tenant_modules_tenant_id", "tenant_modules", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_modules_tenant_id", table_name="tenant_modules")
    op.drop_table("tenant_modules")
    op.drop_index("ix_modules_name", table_name="modules")
    op.drop_table("modules")
