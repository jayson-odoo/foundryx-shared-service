"""omnichannel plan 34 review round 1 (B3) - unverified visitor pre-chat profile.

Adds ``contact_channel_identities.visitor_profile_json``: the ``{"name"?,
"email"?, "phone"?}`` a WEB CHAT visitor typed into the pre-chat form.

Why a new column instead of the contact's own fields: pre-chat is an
UNAUTHENTICATED write (anyone holding the public widget key, which is in the
customer's page source, can post one), and ``contacts.phone``/``phone_digits``
is the key ``InboundService._resolve_contact`` stitches a first WhatsApp
inbound on. Writing an attacker-chosen phone there let a stranger pre-create a
contact carrying a victim's number and fuse the victim's later WhatsApp thread
onto it. The values still need to reach the agent, so they land here -
unverified, per identity, read-only on the agent side, and never a lookup key
anywhere in the codebase.

No backfill required: brand new, empty-until-used, and meaningless-and-NULL
for every non-WEBCHAT identity row.

Idempotent ``ADD COLUMN IF NOT EXISTS`` (mirrors ``0021_omni_webchat``'s
style); the inspector-guarded SQLite branch is parity only - the module
migration orchestrator skips non-Postgres dialects entirely, so it never runs
under pytest (``conftest`` stays on ``create_all``).

Revision ID: 0022_omni_webchat_profile
Revises: 0021_omni_webchat
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_omni_webchat_profile"
down_revision = "0021_omni_webchat"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f'ALTER TABLE "{SCHEMA}".contact_channel_identities '
            "ADD COLUMN IF NOT EXISTS visitor_profile_json JSON"
        )
    else:
        inspector = sa.inspect(bind)
        cols = {
            c["name"] for c in inspector.get_columns("contact_channel_identities", schema=SCHEMA)
        }
        if "visitor_profile_json" not in cols:
            with op.batch_alter_table("contact_channel_identities", schema=SCHEMA) as batch_op:
                batch_op.add_column(sa.Column("visitor_profile_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contact_channel_identities", schema=SCHEMA) as batch_op:
        batch_op.drop_column("visitor_profile_json")
