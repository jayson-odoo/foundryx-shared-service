"""omnichannel plan 34 S1 (A7b) - web chat widget columns.

Adds ``channels.widget_key`` (the opaque, globally-unique key a customer's
public website snippet carries - D-A7B-25, byte-for-byte the
``phone_number_id``/``external_account_id`` design) + a PARTIAL UNIQUE index
over live rows, ``channels.widget_config_json`` (appearance/greetings/pre-chat
toggles/allowed origins - everything except the secret, which stays in the
existing ``credentials_json``), ``channels.widget_token_epoch`` (the mass
visitor-revocation counter, D-A7B-5/D-A7B-6), and
``contact_channel_identities.last_seen_at`` (a presence marker, D-A7B-19).

No backfill required (AC-WEB-16, plan §5.4): all four are brand-new,
empty-until-used columns with no pre-existing data - a tenant that predates
this slice simply has no WEBCHAT channel yet, which is a valid state, not a
gap to repair.

Idempotent ``ADD COLUMN IF NOT EXISTS`` / ``CREATE ... IF NOT EXISTS``
(mirrors ``0019_omni_meta_channels``'s style) so a rerun, or a ``create_all``
local DB that already has the columns via the model, is a no-op either way.
Postgres-only DDL branch; the inspector-guarded SQLite branch mirrors 0019
for parity but this orchestrator already skips non-Postgres dialects
entirely (module-platform.md), so it never runs under pytest (``conftest``
stays on ``create_all``).

Revision ID: 0021_omni_webchat
Revises: 0020_omni_meta_connect
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

# UTCDateTime columns ride sa.DateTime(timezone=True) here (module-migration
# convention, matching 0006/0013/0015/0019); import kept for parity with the
# house rule (CLAUDE.md: "add `import app.models.utc_datetime` by hand").
import app.models.utc_datetime  # noqa: F401

revision = "0021_omni_webchat"
down_revision = "0020_omni_meta_connect"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f'ALTER TABLE "{SCHEMA}".channels '
            "ADD COLUMN IF NOT EXISTS widget_key VARCHAR"
        )
        op.execute(
            f'ALTER TABLE "{SCHEMA}".channels '
            "ADD COLUMN IF NOT EXISTS widget_config_json JSON"
        )
        op.execute(
            f'ALTER TABLE "{SCHEMA}".channels '
            "ADD COLUMN IF NOT EXISTS widget_token_epoch INTEGER NOT NULL DEFAULT 0"
        )
        # Byte-for-byte the `phone_number_id`/`external_account_id` precedent
        # (migrations 0002/0019): only the PARTIAL UNIQUE index is
        # migration-created - a separate plain `CREATE INDEX` would carry a
        # different name than the one `Channel.widget_key`'s `index=True`
        # generates via `create_all`, so this is the ONE index for the
        # column regardless of provisioning route.
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_channels_widget_key "
            f'ON "{SCHEMA}".channels (widget_key) '
            "WHERE widget_key IS NOT NULL AND is_trashed = false"
        )
        op.execute(
            f'ALTER TABLE "{SCHEMA}".contact_channel_identities '
            "ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ"
        )
    else:
        inspector = sa.inspect(bind)
        channel_cols = {c["name"] for c in inspector.get_columns("channels", schema=SCHEMA)}
        with op.batch_alter_table("channels", schema=SCHEMA) as batch_op:
            if "widget_key" not in channel_cols:
                batch_op.add_column(sa.Column("widget_key", sa.String(), nullable=True))
            if "widget_config_json" not in channel_cols:
                batch_op.add_column(sa.Column("widget_config_json", sa.JSON(), nullable=True))
            if "widget_token_epoch" not in channel_cols:
                batch_op.add_column(
                    sa.Column(
                        "widget_token_epoch", sa.Integer(), nullable=False, server_default="0"
                    )
                )
        identity_cols = {
            c["name"] for c in inspector.get_columns("contact_channel_identities", schema=SCHEMA)
        }
        with op.batch_alter_table("contact_channel_identities", schema=SCHEMA) as batch_op:
            if "last_seen_at" not in identity_cols:
                batch_op.add_column(
                    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
                )


def downgrade() -> None:
    with op.batch_alter_table("contact_channel_identities", schema=SCHEMA) as batch_op:
        batch_op.drop_column("last_seen_at")
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".uq_channels_widget_key')
    with op.batch_alter_table("channels", schema=SCHEMA) as batch_op:
        batch_op.drop_column("widget_token_epoch")
        batch_op.drop_column("widget_config_json")
        batch_op.drop_column("widget_key")
