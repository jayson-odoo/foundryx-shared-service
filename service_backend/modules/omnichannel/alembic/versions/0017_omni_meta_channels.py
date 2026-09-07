"""omnichannel plan 32 S1 (A7a) - Messenger/Instagram channel routing columns.

Adds ``channels.external_account_id`` (PAGE_ID / IG account id - the routing
key an unauthenticated webhook resolves a tenant BY, D-A7-3, byte-for-byte the
``phone_number_id`` design from migration ``0002``) + a PARTIAL UNIQUE index
over live rows, ``channels.external_account_name``, and three
``contact_channel_identities`` window columns (``window_expires_at``,
``human_agent_expires_at``, ``last_inbound_at`` - D-A7-5, the per-identity
re-engagement window every channel type now gets).

Backfill (AC-CHN-14): every EXISTING WhatsApp identity gets its
``window_expires_at``/``last_inbound_at`` seeded from the contact's own
``csw_expires_at``/``last_incoming_message_at`` so no pre-existing open thread
loses its window when ``messaging_policy`` (plan 32 S2) starts reading the
identity column instead of the contact column for non-WhatsApp types.
Idempotent (``WHERE i.window_expires_at IS NULL``) - a rerun changes nothing.

``external_account_id``/``external_account_name`` are brand-new columns with
no pre-existing data, so (unlike ``phone_number_id`` in migration ``0002``)
there is no duplicate-reconciliation step before the unique index.

Idempotent ``ADD COLUMN IF NOT EXISTS`` / ``CREATE ... IF NOT EXISTS``
(mirrors ``0002_omni_apikeys``/``0016_omni_business_hours``'s style) so a
rerun, or a ``create_all`` local DB that already has the columns via the
model, is a no-op either way. Postgres-only DDL branch; the inspector-guarded
SQLite branch mirrors ``0016`` for parity but this orchestrator already skips
non-Postgres dialects entirely (module-platform.md), so it never runs under
pytest (``conftest`` stays on ``create_all``).

Revision ID: 0017_omni_meta_channels
Revises: 0016_omni_business_hours
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

# UTCDateTime columns ride sa.DateTime(timezone=True) here (module-migration
# convention, matching 0006/0013/0015); import kept for parity with the house
# rule (CLAUDE.md: "add `import app.models.utc_datetime` by hand").
import app.models.utc_datetime  # noqa: F401

revision = "0017_omni_meta_channels"
down_revision = "0016_omni_business_hours"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f'ALTER TABLE "{SCHEMA}".channels '
            "ADD COLUMN IF NOT EXISTS external_account_id VARCHAR"
        )
        op.execute(
            f'ALTER TABLE "{SCHEMA}".channels '
            "ADD COLUMN IF NOT EXISTS external_account_name VARCHAR"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_omni_channels_external_account_id "
            f'ON "{SCHEMA}".channels (external_account_id)'
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_channels_external_account_id "
            f'ON "{SCHEMA}".channels (external_account_id) '
            "WHERE external_account_id IS NOT NULL AND is_trashed = false"
        )
        op.execute(
            f'ALTER TABLE "{SCHEMA}".contact_channel_identities '
            "ADD COLUMN IF NOT EXISTS window_expires_at TIMESTAMPTZ"
        )
        op.execute(
            f'ALTER TABLE "{SCHEMA}".contact_channel_identities '
            "ADD COLUMN IF NOT EXISTS human_agent_expires_at TIMESTAMPTZ"
        )
        op.execute(
            f'ALTER TABLE "{SCHEMA}".contact_channel_identities '
            "ADD COLUMN IF NOT EXISTS last_inbound_at TIMESTAMPTZ"
        )
        # AC-CHN-14 backfill: every existing WhatsApp identity inherits the
        # window/last-inbound instant its CONTACT already carries, so no
        # pre-existing open thread appears closed once messaging_policy
        # (plan 32 S2) reads the identity column for non-WhatsApp types.
        op.execute(
            f'UPDATE "{SCHEMA}".contact_channel_identities i '
            "SET window_expires_at = c.csw_expires_at, "
            "    last_inbound_at = c.last_incoming_message_at "
            f'FROM "{SCHEMA}".contacts c, "{SCHEMA}".channels ch '
            "WHERE i.contact_id = c.id AND i.channel_id = ch.id "
            "  AND ch.channel_type = 'WHATSAPP' "
            "  AND i.window_expires_at IS NULL"
        )
    else:
        inspector = sa.inspect(bind)
        channel_cols = {c["name"] for c in inspector.get_columns("channels", schema=SCHEMA)}
        with op.batch_alter_table("channels", schema=SCHEMA) as batch_op:
            if "external_account_id" not in channel_cols:
                batch_op.add_column(
                    sa.Column("external_account_id", sa.String(), nullable=True)
                )
            if "external_account_name" not in channel_cols:
                batch_op.add_column(
                    sa.Column("external_account_name", sa.String(), nullable=True)
                )
        identity_cols = {
            c["name"] for c in inspector.get_columns("contact_channel_identities", schema=SCHEMA)
        }
        with op.batch_alter_table("contact_channel_identities", schema=SCHEMA) as batch_op:
            if "window_expires_at" not in identity_cols:
                batch_op.add_column(
                    sa.Column("window_expires_at", sa.DateTime(timezone=True), nullable=True)
                )
            if "human_agent_expires_at" not in identity_cols:
                batch_op.add_column(
                    sa.Column("human_agent_expires_at", sa.DateTime(timezone=True), nullable=True)
                )
            if "last_inbound_at" not in identity_cols:
                batch_op.add_column(
                    sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True)
                )


def downgrade() -> None:
    with op.batch_alter_table("contact_channel_identities", schema=SCHEMA) as batch_op:
        batch_op.drop_column("last_inbound_at")
        batch_op.drop_column("human_agent_expires_at")
        batch_op.drop_column("window_expires_at")
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".uq_channels_external_account_id')
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".ix_omni_channels_external_account_id')
    with op.batch_alter_table("channels", schema=SCHEMA) as batch_op:
        batch_op.drop_column("external_account_name")
        batch_op.drop_column("external_account_id")
