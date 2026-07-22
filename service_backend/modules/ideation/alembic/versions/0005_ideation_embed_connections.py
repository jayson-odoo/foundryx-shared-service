"""ideation — embed-connection registry (iframe SSO).

Create ``app_ideation.embed_connections`` — the DB registry of host applications
authorised to embed a tenant's Ideas workspace over SSO (PLAN-ideation-embed-sso
§7, AC-E-5/12). One row per connection: the non-secret ``connection_id`` (PK),
the Fernet-encrypted shared signing secret, the parent-origin allow-list, an
optional product scope, and an ``is_active`` flag.

CRITICAL (deploy lesson — the module builds tables via ``create_all`` and the
per-module Alembic runner may STAMP head without running migrations on an
existing DB): this migration is idempotent (``CREATE TABLE IF NOT EXISTS``) AND
the same table lands via ``IdeationBase.metadata.create_all`` in the module's
``install()`` — so a fresh install always gets the table whether the stamp-path
or the upgrade-path runs (see LESSONS: pg_trgm + idea statuses skipped on prod).

Postgres-only DDL; a no-op on the SQLite test engine (per-module Alembic runs
only on Postgres — see ``app/module_platform/migrations.run_module_migrations``;
the test suite creates the table via ``create_all``).

Revision ID: 0005_ideation_embed_connections
Revises: 0004_ideation_segregated
Create Date: 2026-07-20
"""
from alembic import op
from sqlalchemy import text

revision = "0005_ideation_embed_connections"
down_revision = "0004_ideation_segregated"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{IDEATION_SCHEMA}".embed_connections ('
            "  connection_id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            "  signing_secret_ciphertext TEXT NOT NULL,"
            "  allowed_origins JSON NOT NULL,"
            "  product_id VARCHAR NULL,"
            "  is_active BOOLEAN NOT NULL DEFAULT TRUE,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )
    bind.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS ix_embed_connections_tenant_id '
            f'ON "{IDEATION_SCHEMA}".embed_connections (tenant_id)'
        )
    )
    bind.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS ix_embed_connections_product_id '
            f'ON "{IDEATION_SCHEMA}".embed_connections (product_id)'
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    bind.execute(text(f'DROP TABLE IF EXISTS "{IDEATION_SCHEMA}".embed_connections'))
