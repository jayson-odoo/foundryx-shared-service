"""ideation - own-idea links on ideas (SS-IDEATION-OWN).

Adds to ``app_ideation.ideas``:

- ``submitter_crm_user_id`` (nullable, indexed) - the submitter's host CRM user
  id, set by the one-shot chatbot create and the embed create. The ownership link
  for ``isMine`` / embed ``mine=true`` / own-similar, alongside the submitter
  contact's phone (never the display name).
- ``intake_ref`` (nullable) + ``uq_ideas_tenant_intake_ref`` UNIQUE
  ``(tenant_id, intake_ref)`` - the host idempotency key of a one-shot create
  (NULLs are distinct, so no other create path is affected).

No backfill: no existing row carries a CRM user id or an intake ref anywhere to
copy from. Pre-existing WhatsApp ideas stay ownable through the phone link
(``submitter_contact_id`` -> contact phone), which needs no new data.

Idempotent ``IF NOT EXISTS`` DDL (same lesson as 0004/0009/0011/0013).
Postgres-only; a no-op on the SQLite test engine (the suite creates the columns
via ``IdeationBase.metadata.create_all``).

Revision ID: 0016_ideation_own_ideas
Revises: 0015_ideation_idea_comments
Create Date: 2026-10-02
"""
from alembic import op
from sqlalchemy import text

revision = "0016_ideation_own_ideas"
down_revision = "0015_ideation_idea_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    for col in ("submitter_crm_user_id", "intake_ref"):
        bind.execute(
            text(
                f'ALTER TABLE "{IDEATION_SCHEMA}".ideas '
                f"ADD COLUMN IF NOT EXISTS {col} VARCHAR NULL"
            )
        )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ideas_submitter_crm_user_id "
            f'ON "{IDEATION_SCHEMA}".ideas (submitter_crm_user_id)'
        )
    )
    bind.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ideas_tenant_intake_ref "
            f'ON "{IDEATION_SCHEMA}".ideas (tenant_id, intake_ref)'
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    for idx in ("uq_ideas_tenant_intake_ref", "ix_ideas_submitter_crm_user_id"):
        bind.execute(text(f'DROP INDEX IF EXISTS "{IDEATION_SCHEMA}".{idx}'))
    for col in ("intake_ref", "submitter_crm_user_id"):
        bind.execute(
            text(f'ALTER TABLE "{IDEATION_SCHEMA}".ideas DROP COLUMN IF EXISTS {col}')
        )
