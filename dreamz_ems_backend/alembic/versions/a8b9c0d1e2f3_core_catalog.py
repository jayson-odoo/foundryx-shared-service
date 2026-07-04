"""core catalog: products + product_categories + tenant_settings (sprint-4/08)

Moves the product catalog out of modules/ems into core public (horizontal —
consumed by CRM quotations, EMS ticketing, future commerce). Money is Numeric
(exact cents). Adds tenant_settings (default currency).

Revision ID: a8b9c0d1e2f3
Revises: d5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa

import app.models.utc_datetime  # noqa: F401 (UTCDateTime column type)
from app.models.utc_datetime import UTCDateTime

revision = "a8b9c0d1e2f3"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(14, 4)


def upgrade() -> None:
    op.create_table(
        "product_categories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("parent_id", sa.String(), sa.ForeignKey("product_categories.id"), nullable=True, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("category_id", sa.String(), sa.ForeignKey("product_categories.id"), nullable=True, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sku", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False, server_default="service"),
        sa.Column("default_price", MONEY, nullable=True),
        sa.Column("tax", MONEY, nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("uom", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("default_currency", sa.String(), nullable=True),
        sa.Column("price_decimals", sa.Integer(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("tenant_settings")
    op.drop_table("products")
    op.drop_table("product_categories")
