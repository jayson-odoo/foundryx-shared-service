"""ideation - feedback item Share link + Follow (lane FEEDBACK-SUBSCRIBE).

- ``idea_followers``: contacts following an item (same WhatsApp status update
  as the submitter); one row per (item, contact).
- ``idea_share_links``: one live read-only share token per item.
- ``idea_phone_codes``: hashed WhatsApp codes proving a share-link visitor's
  phone (10 minutes, 5 tries, single use).

New tables only - no backfill needed (nobody follows or shares yet; the
submitter is implicitly followed without a row). Idempotent ``IF NOT EXISTS``
DDL; a fresh install gets the tables via ``create_all`` in ``install()``.
Postgres-only; a no-op on the SQLite test engine. Uses Alembic's own
connection, never commits it.

Chained on 0021 (main). PR #252 adds 0022_ideation_board_product: whichever of
the two merges second re-points its ``down_revision`` onto the other.

Revision ID: 0023_ideation_follow_share
Revises: 0021_ideation_type_labels
Create Date: 2026-11-17
"""
from alembic import op
from sqlalchemy import text

# <= 32 chars (alembic_version.version_num is VARCHAR(32)).
revision = "0023_ideation_follow_share"
down_revision = "0021_ideation_type_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    for stmt in (
        f'CREATE TABLE IF NOT EXISTS "{s}".idea_followers ('
        "  id VARCHAR PRIMARY KEY,"
        "  tenant_id VARCHAR NOT NULL,"
        f'  idea_id VARCHAR NOT NULL REFERENCES "{s}".ideas(id),'
        "  contact_id VARCHAR NOT NULL,"
        "  added_by_user_id VARCHAR NULL,"
        "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  CONSTRAINT uq_idea_follower_contact UNIQUE (idea_id, contact_id)"
        ")",
        f'CREATE TABLE IF NOT EXISTS "{s}".idea_share_links ('
        "  id VARCHAR PRIMARY KEY,"
        "  tenant_id VARCHAR NOT NULL,"
        f'  idea_id VARCHAR NOT NULL REFERENCES "{s}".ideas(id),'
        "  token VARCHAR NOT NULL UNIQUE,"
        "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  revoked_at TIMESTAMPTZ NULL"
        ")",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_idea_share_links_live "
        f'ON "{s}".idea_share_links (idea_id) WHERE revoked_at IS NULL',
        f'CREATE TABLE IF NOT EXISTS "{s}".idea_phone_codes ('
        "  id VARCHAR PRIMARY KEY,"
        "  tenant_id VARCHAR NOT NULL,"
        "  phone_digits VARCHAR NOT NULL,"
        "  code_hash VARCHAR NOT NULL,"
        "  contact_name VARCHAR NULL,"
        "  attempts INTEGER NOT NULL DEFAULT 0,"
        "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  expires_at TIMESTAMPTZ NOT NULL,"
        "  used_at TIMESTAMPTZ NULL"
        ")",
    ):
        bind.execute(text(stmt))
    for table, cols in (
        ("idea_followers", ("tenant_id", "idea_id", "contact_id")),
        ("idea_share_links", ("tenant_id", "idea_id")),
        ("idea_phone_codes", ("tenant_id", "phone_digits")),
    ):
        for col in cols:
            bind.execute(
                text(f'CREATE INDEX IF NOT EXISTS ix_{s}_{table}_{col} ON "{s}".{table} ({col})')
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    for table in ("idea_phone_codes", "idea_share_links", "idea_followers"):
        bind.execute(text(f'DROP TABLE IF EXISTS "{s}".{table}'))
