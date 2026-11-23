"""omnichannel - delivery history index (S5, 2026-11-18).

`GET /api/v1/omnichannel/webhooks/{id}/deliveries` reads one endpoint's
deliveries newest first. `webhook_deliveries` keeps every delivery (no
retention), and the only per-endpoint index is on `endpoint_id` alone, so each
page would sort every delivery the endpoint ever had. This adds
`(endpoint_id, created_at)`.

Online-safe: built with CREATE INDEX CONCURRENTLY inside Alembic's
autocommit block (no write lock on a live outbox table). An INVALID index left
by an earlier interrupted concurrent build is dropped first, so a retried
deploy finishes the job. No data change, no backfill. Revision id <= 32 chars.

Revision ID: 0030_omni_delivery_history_ix
Revises: 0029_omni_strict_number_window
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_omni_delivery_history_ix"
down_revision = "0029_omni_strict_number_window"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"
INDEX = "ix_webhook_deliveries_endpoint_created"


def _index_state(bind):
    """None (absent), True (valid) or False (left INVALID by a failed build)."""
    row = bind.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i"
            " JOIN pg_class c ON c.oid = i.indexrelid"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = :schema AND c.relname = :name"
        ),
        {"schema": SCHEMA, "name": INDEX},
    ).first()
    return None if row is None else bool(row[0])


def upgrade() -> None:
    bind = op.get_bind()
    if "webhook_deliveries" not in set(sa.inspect(bind).get_table_names(schema=SCHEMA)):
        return  # defensive: 0003 creates the table; nothing to index without it
    state = _index_state(bind)
    if state is True:
        return
    with op.get_context().autocommit_block():
        if state is False:
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{SCHEMA}"."{INDEX}"')
        op.create_index(
            INDEX,
            "webhook_deliveries",
            ["endpoint_id", "created_at"],
            schema=SCHEMA,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{SCHEMA}"."{INDEX}"')
