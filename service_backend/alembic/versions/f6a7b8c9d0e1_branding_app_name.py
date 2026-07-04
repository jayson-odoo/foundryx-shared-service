"""Tenant branding: app_name (brandable system name for "Welcome to {name}")

White-label: the sign-in heading and tab title should use a tenant-chosen
product/system name, never the FoundryX product name. NULL = fall back to the
tenant name. Chains the document-sharing head.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_branding", sa.Column("app_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_branding", "app_name")
