"""Idea comments - ``idea_comments`` table.

Plan: ``documentation/plans/sprint-5/19-ideation-comments.md`` section 1.

A new table, no existing rows, so no backfill. Idempotent (``IF NOT EXISTS``).
Postgres-only DDL; a no-op on the SQLite test engine (the suite builds the same
schema via ``IdeationBase.metadata.create_all``).

Revision ID: 0015_ideation_idea_comments
Revises: 0014_ideation_br_build
Create Date: 2026-10-02
"""
from alembic import op
from sqlalchemy import text

revision = "0015_ideation_idea_comments"
down_revision = "0014_ideation_br_build"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    schema = IDEATION_SCHEMA

    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{schema}".idea_comments ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            f'  idea_id VARCHAR NOT NULL REFERENCES "{schema}".ideas(id),'
            f'  parent_id VARCHAR NULL REFERENCES "{schema}".idea_comments(id),'
            "  author_kind VARCHAR NOT NULL,"
            "  author_id VARCHAR NOT NULL,"
            "  author_name VARCHAR NULL,"
            "  body TEXT NOT NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  edited_at TIMESTAMPTZ NULL,"
            "  deleted_at TIMESTAMPTZ NULL"
            ")"
        )
    )
    bind.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS ix_{schema}_idea_comments_tenant_id "
            f'ON "{schema}".idea_comments (tenant_id)'
        )
    )
    bind.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS ix_{schema}_idea_comments_idea_id "
            f'ON "{schema}".idea_comments (idea_id)'
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(text(f'DROP TABLE IF EXISTS "{IDEATION_SCHEMA}".idea_comments'))
