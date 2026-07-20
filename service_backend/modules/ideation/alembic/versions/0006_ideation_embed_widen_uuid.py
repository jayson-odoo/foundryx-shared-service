"""ideation — widen embed_connections UUID columns (self-heal legacy VARCHAR(32)).

An existing prod ``app_ideation.embed_connections`` was found with
``tenant_id VARCHAR(32)`` — 4 chars too short for a 36-char UUID string. It
SILENTLY TRUNCATED the tenant on write (``…b5ef0bc827b8`` → ``…b5ef0bc8``), so the
minted embed token carried a truncated tenant and ``GET /embed/ideas`` matched
ZERO ideas (their tenant_id is the full 36-char UUID) → the sorento iframe showed
an empty Ideas list even though the connection "pointed at the right tenant".

Root defence: this table's ``0005`` migration + the model already declare
unbounded ``VARCHAR``/``String``, so a FRESH install is correct. This migration
converges any EXISTING DB whose column was created narrow (create_all vs
migration-stamp ordering, or a pre-widen build): idempotent ``ALTER … TYPE
VARCHAR`` widens ``tenant_id`` / ``connection_id`` / ``product_id`` — including
the future product-scope filter, which is also a 36-char UUID and would truncate
the same way. ALTER to the same type is a harmless no-op on an already-wide
column.

Postgres-only (per-module Alembic runs only on Postgres); a no-op on SQLite.

Revision ID: 0006_ideation_embed_widen_uuid
Revises: 0005_ideation_embed_connections
Create Date: 2026-07-20
"""
from alembic import op
from sqlalchemy import text

revision = "0006_ideation_embed_widen_uuid"
down_revision = "0005_ideation_embed_connections"
branch_labels = None
depends_on = None

_COLUMNS = ("connection_id", "tenant_id", "product_id")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA

    for col in _COLUMNS:
        bind.execute(
            text(
                f'ALTER TABLE "{IDEATION_SCHEMA}".embed_connections '
                f"ALTER COLUMN {col} TYPE VARCHAR"
            )
        )


def downgrade() -> None:
    # No-op: narrowing back to VARCHAR(32) would re-introduce the truncation bug
    # and could fail on rows already holding a full 36-char UUID.
    return
