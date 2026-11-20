"""autocount pull api key scopes (plan 55, AC-55-40)

``ac_pull_api_key`` += ``scopes`` JSON. BACKFILL: every existing key becomes
``["pull"]`` (the only thing it could do before), on a frozen ``sa.table``,
then the column is made NOT NULL. Write routes need ``"write_back"``.

Existence-checked (create_all-first host is a clean no-op). Never commits:
Alembic's own transaction owns that.

Revision ID: 0037_autocount_key_scopes   (26 chars <= 32)
Revises: 0036_autocount_write_back
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_autocount_key_scopes"
down_revision: Union[str, Sequence[str], None] = "0036_autocount_write_back"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_pull_api_key"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} ADD COLUMN IF NOT EXISTS scopes JSON NULL")
    keys = sa.table(
        TABLE,
        sa.column("id", sa.String()),
        sa.column("scopes", sa.JSON(none_as_null=True)),
        schema=SCHEMA,
    )
    bind.execute(keys.update().where(keys.c.scopes.is_(None)).values(scopes=["pull"]))
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} ALTER COLUMN scopes SET NOT NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP COLUMN IF EXISTS scopes")
