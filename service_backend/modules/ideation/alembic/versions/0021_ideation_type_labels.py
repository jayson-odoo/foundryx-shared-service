"""ideation - idea type labels say what a user reads (lane FEEDBACK-RENAME).

Owner ruling 15 Nov: no user reads "idea". The catalog KEYS stay ``idea`` /
``issue``; the stock labels "Idea" / "Issue" become "Feature request" /
"Problem report" (the Sorento CRM labels, sorento-crm #2434). Guarded: only a row
still on its stock label changes, so a deliberate relabel survives. Idempotent,
data-only, no schema change. Postgres-only; a no-op on the SQLite test engine
(``seed_idea_types`` applies the same guarded relabel at every install()).
Uses Alembic's own connection (``op.get_bind()``) - never commits it.

Revision ID: 0021_ideation_type_labels
Revises: 0020_ideation_contact_links
Create Date: 2026-11-15
"""
from alembic import op
from sqlalchemy import text

# <= 32 chars (alembic_version.version_num is VARCHAR(32)).
revision = "0021_ideation_type_labels"
down_revision = "0020_ideation_contact_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s
    from modules.ideation.services.idea_types import relabel_idea_types_sql

    for stmt in relabel_idea_types_sql(s):
        bind.execute(text(stmt))


def downgrade() -> None:
    # Labels are display data; leave whatever the catalog now carries.
    pass
