"""storage integrations (plan sprint-2/06)

- connections: UNIQUE(tenant_id, type) — ONE connection per type per tenant
  (D7); race/bypass-proof backstop for the service-level 409.
- users: avatar URL column → avatar_key (storage key, D4) + avatar_version
  (?v= cache-bust). The old column only ever held NULLs (BL-007 was open),
  so no data migrates.

Revision ID: a6b7c8d9e0f1
Revises: 9d2e3f4a5b6c
Create Date: 2026-06-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "9d2e3f4a5b6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_connection_tenant_type", ["tenant_id", "type"])

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("avatar_key", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("avatar_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.drop_column("avatar")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("avatar", sa.String(), nullable=True))
        batch_op.drop_column("avatar_version")
        batch_op.drop_column("avatar_key")

    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.drop_constraint("uq_connection_tenant_type", type_="unique")
