"""template engine plan 07 - templates table, branding socials/footer, notification template_id

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-06-07
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("context", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("doc_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_templates_tenant_id", "templates", ["tenant_id"])
    op.create_index("ix_templates_key", "templates", ["key"])
    # Two-tier uniqueness - partial indexes; a plain UNIQUE treats NULLs as
    # distinct and lets duplicate platform rows in (BL-065 lesson).
    op.create_index(
        "uq_templates_tenant_key",
        "templates",
        ["tenant_id", "key"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
        sqlite_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_index(
        "uq_templates_platform_key",
        "templates",
        ["key"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
        sqlite_where=sa.text("tenant_id IS NULL"),
    )

    with op.batch_alter_table("tenant_branding") as batch:
        batch.add_column(sa.Column("socials_json", sa.JSON(none_as_null=True), nullable=True))
        batch.add_column(sa.Column("footer_json", sa.JSON(none_as_null=True), nullable=True))

    with op.batch_alter_table("notification_specs") as batch:
        batch.add_column(sa.Column("template_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_notification_specs_template_id",
            "templates",
            ["template_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_specs") as batch:
        batch.drop_constraint("fk_notification_specs_template_id", type_="foreignkey")
        batch.drop_column("template_id")
    with op.batch_alter_table("tenant_branding") as batch:
        batch.drop_column("footer_json")
        batch.drop_column("socials_json")
    op.drop_index("uq_templates_platform_key", table_name="templates")
    op.drop_index("uq_templates_tenant_key", table_name="templates")
    op.drop_index("ix_templates_key", table_name="templates")
    op.drop_index("ix_templates_tenant_id", table_name="templates")
    op.drop_table("templates")
