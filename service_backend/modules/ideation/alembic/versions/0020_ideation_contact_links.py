"""ideation - personal feedback links (lane PUBLIC-IDEAS-BOARD).

``idea_contact_links``: one live token per contact that opens the idea portal
with no login. Idempotent ``IF NOT EXISTS`` DDL; a fresh install gets the table
via ``create_all`` in ``install()``. Postgres-only; a no-op on the SQLite test
engine. Uses Alembic's own connection, never commits it.

Revision ID: 0020_ideation_contact_links
Revises: 0019_ideation_idea_type
Create Date: 2026-11-15
"""
from alembic import op
from sqlalchemy import text

# <= 32 chars (alembic_version.version_num is VARCHAR(32)).
revision = "0020_ideation_contact_links"
down_revision = "0019_ideation_idea_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{s}".idea_contact_links ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            "  contact_id VARCHAR NOT NULL,"
            "  token VARCHAR NOT NULL UNIQUE,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  revoked_at TIMESTAMPTZ NULL"
            ")"
        )
    )
    for col in ("tenant_id", "contact_id"):
        bind.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_{s}_idea_contact_links_{col} "
                f'ON "{s}".idea_contact_links ({col})'
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    bind.execute(text(f'DROP TABLE IF EXISTS "{s}".idea_contact_links'))
