"""ideation - submitter CRM-user link on ideas (SS-IDEATION-OWN).

Adds ``ideas.submitter_crm_user_id`` (nullable, indexed): the host CRM user id
of the submitter, set by the one-shot chatbot create and the embed create. It is
the ownership link for ``isMine`` / embed ``mine=true`` / own-similar, alongside
the submitter contact's phone (never the display name).

No backfill: no existing row carries a CRM user id anywhere to copy from.
Pre-existing WhatsApp ideas stay ownable through the phone link
(``submitter_contact_id`` -> contact phone), which needs no new data.

Idempotent ``ADD COLUMN IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS`` (same
lesson as 0004/0009/0011/0013). Postgres-only DDL; a no-op on the SQLite test
engine (the suite creates the column via ``IdeationBase.metadata.create_all``).

Revision ID: 0015_ideation_submitter_crm_user
Revises: 0014_ideation_br_build
Create Date: 2026-10-02
"""
from alembic import op
from sqlalchemy import text

revision = "0015_ideation_submitter_crm_user"
down_revision = "0014_ideation_br_build"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(
        text(
            f'ALTER TABLE "{IDEATION_SCHEMA}".ideas '
            "ADD COLUMN IF NOT EXISTS submitter_crm_user_id VARCHAR NULL"
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ideas_submitter_crm_user_id "
            f'ON "{IDEATION_SCHEMA}".ideas (submitter_crm_user_id)'
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(
        text(f'DROP INDEX IF EXISTS "{IDEATION_SCHEMA}".ix_ideas_submitter_crm_user_id')
    )
    bind.execute(
        text(
            f'ALTER TABLE "{IDEATION_SCHEMA}".ideas '
            "DROP COLUMN IF EXISTS submitter_crm_user_id"
        )
    )
