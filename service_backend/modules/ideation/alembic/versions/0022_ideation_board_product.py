"""ideation - feedback board served per product (lane SS-MULTI-PRODUCT-BOARD).

- ``idea_contact_links.product_id``: a personal board link belongs to the
  product of the item it was minted for; the live-link unique index becomes
  one live link per contact PER product.
- ``product_delivery.board_color`` / ``board_name``: the product's look on its
  board, set on the Products screen.
- Backfill: an old link whose contact submitted items on exactly ONE product
  is stamped with it (``feedback_links.backfill_link_products_sql`` - the same
  statement the tests run).

Idempotent DDL (``IF NOT EXISTS``). A fresh install gets the columns via
``create_all`` in ``install()``. Postgres-only; a no-op on the SQLite test
engine. Uses Alembic's own connection, never commits it.

Revision ID: 0022_ideation_board_product
Revises: 0021_ideation_type_labels
Create Date: 2026-11-17
"""
from alembic import op
from sqlalchemy import text

# <= 32 chars (alembic_version.version_num is VARCHAR(32)).
revision = "0022_ideation_board_product"
down_revision = "0021_ideation_type_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s
    from modules.ideation.services.feedback_links import backfill_link_products_sql

    bind.execute(text(f'ALTER TABLE "{s}".idea_contact_links ADD COLUMN IF NOT EXISTS product_id VARCHAR NULL'))
    bind.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS ix_{s}_idea_contact_links_product_id "
            f'ON "{s}".idea_contact_links (product_id)'
        )
    )
    bind.execute(text(f'DROP INDEX IF EXISTS "{s}".uq_idea_contact_links_live'))
    bind.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_idea_contact_links_live "
            f'ON "{s}".idea_contact_links (tenant_id, contact_id, coalesce(product_id, \'\')) '
            "WHERE revoked_at IS NULL"
        )
    )
    bind.execute(text(f'ALTER TABLE "{s}".product_delivery ADD COLUMN IF NOT EXISTS board_color VARCHAR(7) NULL'))
    bind.execute(text(f'ALTER TABLE "{s}".product_delivery ADD COLUMN IF NOT EXISTS board_name VARCHAR(80) NULL'))
    bind.execute(text(backfill_link_products_sql(s)))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    # Back to one live link per contact: keep the oldest live link of each
    # contact, cancel the rest, then restore the old index.
    bind.execute(
        text(
            f'UPDATE "{s}".idea_contact_links l SET revoked_at = now() '
            "WHERE l.revoked_at IS NULL AND EXISTS (SELECT 1 FROM "
            f'"{s}".idea_contact_links o WHERE o.tenant_id = l.tenant_id '
            "AND o.contact_id = l.contact_id AND o.revoked_at IS NULL "
            "AND (o.created_at, o.id) < (l.created_at, l.id))"
        )
    )
    bind.execute(text(f'DROP INDEX IF EXISTS "{s}".uq_idea_contact_links_live'))
    bind.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_idea_contact_links_live "
            f'ON "{s}".idea_contact_links (tenant_id, contact_id) WHERE revoked_at IS NULL'
        )
    )
    bind.execute(text(f'ALTER TABLE "{s}".product_delivery DROP COLUMN IF EXISTS board_name'))
    bind.execute(text(f'ALTER TABLE "{s}".product_delivery DROP COLUMN IF EXISTS board_color'))
    bind.execute(text(f'ALTER TABLE "{s}".idea_contact_links DROP COLUMN IF EXISTS product_id'))
