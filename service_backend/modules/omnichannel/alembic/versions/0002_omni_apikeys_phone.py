"""omnichannel Slice 3 — workspace_api_keys + phone_number_id UNIQUE.

Adds the public-gateway API-key table and a service-wide partial-unique index on
``channels.phone_number_id`` (O(1) inbound routing, AC-01-20). Existing duplicate
phone rows are reconciled (earliest kept, losers NULLed) BEFORE the index so the
constraint can be created on a live DB (DoD backfill gate).

Revision ID: 0002_omni_apikeys
Revises: 0001_omni_baseline
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_omni_apikeys"
down_revision = "0001_omni_baseline"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    # The module baseline (0001) runs ``OmniBase.metadata.create_all`` over the
    # CURRENT metadata, which already includes ``workspace_api_keys`` — so on a
    # fresh alembic deploy the table may already exist. Guard existence so this
    # migration is idempotent (BL-029: per-module Alembic still shares the
    # create_all baseline).
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("workspace_api_keys", schema=SCHEMA):
        op.create_table(
            "workspace_api_keys",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("workspace_id", sa.String(), nullable=False, index=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("key_prefix", sa.String(), nullable=False, index=True),
            sa.Column("key_hash", sa.String(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            schema=SCHEMA,
        )

    # Reconcile duplicate phone_number_id among LIVE (non-trashed) channels:
    # keep the earliest by (created_at, id), NULL the losers, then add a partial
    # unique index scoped to live rows. The scope matches both the connect guard
    # and "route inbound to the ACTIVE channel" — a disconnected (is_trashed)
    # channel keeps its phone_number_id so the same number can be reconnected.
    op.execute(
        f'UPDATE "{SCHEMA}".channels c SET phone_number_id = NULL '
        "WHERE c.phone_number_id IS NOT NULL AND c.is_trashed = false AND EXISTS ("
        f'  SELECT 1 FROM "{SCHEMA}".channels c2 '
        "  WHERE c2.phone_number_id = c.phone_number_id AND c2.is_trashed = false "
        "    AND (c2.created_at < c.created_at "
        "         OR (c2.created_at = c.created_at AND c2.id < c.id)))"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_channels_phone_number_id "
        f'ON "{SCHEMA}".channels (phone_number_id) '
        "WHERE phone_number_id IS NOT NULL AND is_trashed = false"
    )


def downgrade() -> None:
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".uq_channels_phone_number_id')
    op.drop_table("workspace_api_keys", schema=SCHEMA)
