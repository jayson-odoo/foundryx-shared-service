"""ideation - idea type (SS-IDEA-TYPE): ``idea_types`` catalog + ``ideas.type``.

The ONE table of allowed idea types (``idea`` default, ``issue``) + an
additive ``ideas.type`` column (NOT NULL DEFAULT 'idea', so every existing row is
an ``idea`` - Postgres 11+ adds a constant-default column as a metadata-only
change, no table rewrite) + FK into the catalog + an index for the list filter.

Idempotent (``IF NOT EXISTS`` / ``ON CONFLICT DO NOTHING`` / constraint lookup):
a fresh install also gets the table + column via ``create_all`` in ``install()``,
so whichever of stamp-path / upgrade-path runs, the result is the same.
Postgres-only; a no-op on the SQLite test engine (tests use ``create_all``).
Uses Alembic's own connection (``op.get_bind()``) - never commits it.

Revision ID: 0019_ideation_idea_type
Revises: 0018_ideation_portal
Create Date: 2026-11-13
"""
from alembic import op
from sqlalchemy import text

# ≤ 32 chars (alembic_version.version_num is VARCHAR(32)).
revision = "0019_ideation_idea_type"
down_revision = "0018_ideation_portal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s
    from modules.ideation.services.idea_types import upgrade_idea_type_sql

    for stmt in upgrade_idea_type_sql(s):
        bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    bind.execute(text(f'ALTER TABLE "{s}".ideas DROP CONSTRAINT IF EXISTS fk_ideas_type_idea_types'))
    bind.execute(text(f'DROP INDEX IF EXISTS "{s}".ix_ideas_type'))
    bind.execute(text(f'ALTER TABLE "{s}".ideas DROP COLUMN IF EXISTS type'))
    bind.execute(text(f'DROP TABLE IF EXISTS "{s}".idea_types'))
