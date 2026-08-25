"""statuses.scope_id - scoped status machines (plan sprint-3/01 D4)

Revision ID: 3e4f5a6b7c8d
Revises: 2d3e4f5a6b7c
Create Date: 2026-06-10

"""
from alembic import op
import sqlalchemy as sa

revision = "3e4f5a6b7c8d"
down_revision = "2d3e4f5a6b7c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch mode: SQLite-safe constraint swap (house rule, env.py render_as_batch).
    with op.batch_alter_table("statuses") as batch:
        batch.add_column(sa.Column("scope_id", sa.String(), nullable=True))
        batch.drop_constraint("uq_statuses_entity_tenant_key", type_="unique")
        batch.create_unique_constraint(
            "uq_statuses_entity_tenant_key",
            ["entity_type", "tenant_id", "scope_id", "key"],
        )
    op.create_index("ix_statuses_scope_id", "statuses", ["scope_id"])


def downgrade() -> None:
    op.drop_index("ix_statuses_scope_id", table_name="statuses")
    with op.batch_alter_table("statuses") as batch:
        batch.drop_constraint("uq_statuses_entity_tenant_key", type_="unique")
        batch.create_unique_constraint(
            "uq_statuses_entity_tenant_key", ["entity_type", "tenant_id", "key"]
        )
        batch.drop_column("scope_id")
