"""Tenant core (plan 07): statuses foundation + tenant lifecycle/platform
columns + BL-015 association tenant_id backfill.

- create `statuses` + seed the 3 tenant lifecycle system rows
- tenants: is_active -> status_id (FK statuses), + is_platform / contacts /
  custom_domain / notes (platform tenant itself is seeded by seed.py)
- backfill user_roles.tenant_id / role_permissions.tenant_id from the owning
  role (they were written via a static default - wrong for tenant #2, BL-015)

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""
import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None

# Stable system-row ids - keep in sync with app/models/status.py.
_ACTIVE_ID = "20000000-0000-0000-0000-000000000001"
_SUSPENDED_ID = "20000000-0000-0000-0000-000000000002"
_ARCHIVED_ID = "20000000-0000-0000-0000-000000000003"

_STATUS_ROWS = [
    (_ACTIVE_ID, "active", "ACTIVE", "Active", "green", 1),
    (_SUSPENDED_ID, "suspended", "SUSPENDED", "Suspended", "amber", 2),
    (_ARCHIVED_ID, "archived", "ARCHIVED", "Archived", "gray", 3),
]


def upgrade() -> None:
    # 1. statuses foundation
    op.create_table(
        "statuses",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("entity_type", "tenant_id", "key", name="uq_statuses_entity_tenant_key"),
    )
    op.create_index("ix_statuses_entity_type", "statuses", ["entity_type"])
    op.create_index("ix_statuses_tenant_id", "statuses", ["tenant_id"])

    statuses = sa.table(
        "statuses",
        sa.column("id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("key", sa.String),
        sa.column("category", sa.String),
        sa.column("label", sa.String),
        sa.column("color", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("is_system", sa.Boolean),
        sa.column("tenant_id", sa.String),
    )
    op.bulk_insert(
        statuses,
        [
            {
                "id": sid,
                "entity_type": "tenant",
                "key": key,
                "category": category,
                "label": label,
                "color": color,
                "sort_order": sort_order,
                "is_system": True,
                "tenant_id": None,
            }
            for sid, key, category, label, color, sort_order in _STATUS_ROWS
        ],
    )

    # 2. tenants: lifecycle + platform/contact columns
    with op.batch_alter_table("tenants") as batch:
        batch.add_column(sa.Column("status_id", sa.String(), nullable=True))
        batch.add_column(
            sa.Column("is_platform", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("contact_name", sa.String(), nullable=True))
        batch.add_column(sa.Column("contact_email", sa.String(), nullable=True))
        batch.add_column(sa.Column("custom_domain", sa.String(), nullable=True))
        batch.add_column(sa.Column("notes", sa.String(), nullable=True))

    # Backfill lifecycle from the old boolean: active -> ACTIVE, else ARCHIVED.
    op.execute(
        f"UPDATE tenants SET status_id = CASE WHEN is_active THEN '{_ACTIVE_ID}' "
        f"ELSE '{_ARCHIVED_ID}' END"
    )

    with op.batch_alter_table("tenants") as batch:
        batch.alter_column("status_id", nullable=False)
        batch.create_foreign_key("fk_tenants_status_id", "statuses", ["status_id"], ["id"])
        batch.create_index("ix_tenants_status_id", ["status_id"])
        batch.create_unique_constraint("uq_tenants_custom_domain", ["custom_domain"])
        batch.drop_column("is_active")

    # 3. BL-015: association tenant_id follows the owning role (was the static
    # default - wrong the moment a 2nd tenant exists).
    op.execute(
        "UPDATE user_roles SET tenant_id = "
        "(SELECT tenant_id FROM roles WHERE roles.id = user_roles.role_id)"
    )
    op.execute(
        "UPDATE role_permissions SET tenant_id = "
        "(SELECT tenant_id FROM roles WHERE roles.id = role_permissions.role_id)"
    )


def downgrade() -> None:
    with op.batch_alter_table("tenants") as batch:
        batch.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )

    op.execute(
        f"UPDATE tenants SET is_active = (status_id = '{_ACTIVE_ID}')"
    )

    with op.batch_alter_table("tenants") as batch:
        batch.drop_constraint("uq_tenants_custom_domain", type_="unique")
        batch.drop_index("ix_tenants_status_id")
        batch.drop_constraint("fk_tenants_status_id", type_="foreignkey")
        batch.drop_column("notes")
        batch.drop_column("custom_domain")
        batch.drop_column("contact_email")
        batch.drop_column("contact_name")
        batch.drop_column("is_platform")
        batch.drop_column("status_id")

    op.drop_index("ix_statuses_tenant_id", table_name="statuses")
    op.drop_index("ix_statuses_entity_type", table_name="statuses")
    op.drop_table("statuses")
