"""ideation — add ``ideas.submitter_name`` for operator-authored ideas.

The in-app operator create/edit surface authors ideas with no contact copy
(``submitter_contact_id`` stays NULL), so the submitter's display name is stored
directly in this nullable column. The read serializer prefers it when set, else
derives the name from the linked contact.

Postgres-only DDL; a no-op on the SQLite test engine (per-module Alembic runs
only on Postgres — see ``app/module_platform/migrations.run_module_migrations``).

Revision ID: 0003_ideation_idea_submitter_name
Revises: 0002_ideation_dedup_trgm
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_ideation_idea_submitter_name"
down_revision = "0002_ideation_dedup_trgm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    op.add_column(
        "ideas",
        sa.Column("submitter_name", sa.String(), nullable=True),
        schema=IDEATION_SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    op.drop_column("ideas", "submitter_name", schema=IDEATION_SCHEMA)
