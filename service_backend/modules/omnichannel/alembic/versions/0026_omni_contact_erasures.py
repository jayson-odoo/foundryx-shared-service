"""omnichannel plan 58 - contact erase register (lane SS-FUJI-READINESS).

Adds `contact_erasures`: one row per erased contact (actor, ids, counts, time;
no personal data, no foreign keys). The table is new and no staff erase has
run in production yet, so no backfill is needed. Idempotent guard (inspector
check), same style as `0025_omni_migration_sync`. Revision id <= 32 chars.

Revision ID: 0026_omni_contact_erasures
Revises: 0025_omni_migration_sync
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_omni_contact_erasures"
down_revision = "0025_omni_migration_sync"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema=SCHEMA))

    if "contact_erasures" not in tables:
        op.create_table(
            "contact_erasures",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("contact_id", sa.String(), nullable=False),
            sa.Column("actor_kind", sa.String(), nullable=False),
            sa.Column("actor_user_id", sa.String(), nullable=True),
            sa.Column("api_key_id", sa.String(), nullable=True),
            sa.Column("messages", sa.Integer(), nullable=False),
            sa.Column("files", sa.Integer(), nullable=False),
            sa.Column("erased_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "(actor_kind = 'staff' AND actor_user_id IS NOT NULL AND api_key_id IS NULL)"
                " OR (actor_kind = 'api_key' AND api_key_id IS NOT NULL AND actor_user_id IS NULL)",
                name="ck_contact_erasures_actor",
            ),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_contact_erasures_tenant_erased", "contact_erasures", ["tenant_id", "erased_at"], schema=SCHEMA
        )
        op.create_index(
            "ix_contact_erasures_tenant_contact", "contact_erasures", ["tenant_id", "contact_id"], schema=SCHEMA
        )


def downgrade() -> None:
    op.drop_index("ix_contact_erasures_tenant_contact", table_name="contact_erasures", schema=SCHEMA)
    op.drop_index("ix_contact_erasures_tenant_erased", table_name="contact_erasures", schema=SCHEMA)
    op.drop_table("contact_erasures", schema=SCHEMA)
