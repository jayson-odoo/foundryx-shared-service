"""omnichannel plan 11H - embed host (external-agent identity + jti ledger).

Creates ``external_agent`` (federated agent identity, UNIQUE(connection_id, sub))
and ``embed_jti`` (single-use assertion ledger), and adds the two nullable
federated-attribution columns (``conversation_messages.sender_external_agent_id``,
``contacts.assigned_external_agent_id``). All idempotent - the module baseline
runs ``create_all`` so a fresh deploy may already have these. Revision id ≤ 32
chars.

Revision ID: 0006_omni_embed
Revises: 0005_omni_reactions
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

# UTCDateTime columns ride sa.DateTime(timezone=True) here (module-migration
# convention, matching 0005); import kept for parity with the house rule.
import app.models.utc_datetime  # noqa: F401

revision = "0006_omni_embed"
down_revision = "0005_omni_reactions"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema=SCHEMA))

    if "external_agent" not in tables:
        op.create_table(
            "external_agent",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("connection_id", sa.String(), nullable=False, index=True),
            sa.Column("sub", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("avatar_url", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "connection_id", "sub", name="uq_external_agent_conn_sub"
            ),
            schema=SCHEMA,
        )

    if "embed_jti" not in tables:
        op.create_table(
            "embed_jti",
            sa.Column("jti", sa.String(), primary_key=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            schema=SCHEMA,
        )

    # Nullable federated-attribution columns (idempotent add for existing deploys).
    msg_cols = {c["name"] for c in inspector.get_columns("conversation_messages", schema=SCHEMA)}
    if "sender_external_agent_id" not in msg_cols:
        op.add_column(
            "conversation_messages",
            sa.Column("sender_external_agent_id", sa.String(), nullable=True),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_conversation_messages_sender_external_agent_id",
            "conversation_messages",
            ["sender_external_agent_id"],
            schema=SCHEMA,
        )

    contact_cols = {c["name"] for c in inspector.get_columns("contacts", schema=SCHEMA)}
    if "assigned_external_agent_id" not in contact_cols:
        op.add_column(
            "contacts",
            sa.Column("assigned_external_agent_id", sa.String(), nullable=True),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_contacts_assigned_external_agent_id",
            "contacts",
            ["assigned_external_agent_id"],
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_contacts_assigned_external_agent_id", table_name="contacts", schema=SCHEMA
    )
    op.drop_column("contacts", "assigned_external_agent_id", schema=SCHEMA)
    op.drop_index(
        "ix_conversation_messages_sender_external_agent_id",
        table_name="conversation_messages",
        schema=SCHEMA,
    )
    op.drop_column("conversation_messages", "sender_external_agent_id", schema=SCHEMA)
    op.drop_table("embed_jti", schema=SCHEMA)
    op.drop_table("external_agent", schema=SCHEMA)
