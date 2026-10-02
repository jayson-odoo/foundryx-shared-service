"""omnichannel plan 27 A3 S1 - conversation events (roadmap D9).

Adds the append-only `conversation_events` table (idempotent - the module
baseline may already have it via `create_all`) + `contacts.last_agent_message_at`
(nullable, indexed), then backfills BOTH: every contact with no events yet gets
`opened`/`closed`/`assigned` rows (`payload_json.backfilled = true`), and
`last_agent_message_at` is filled from each contact's own AGENT-message
history. Idempotent (guarded by a temp table snapshotting "no events yet"
BEFORE any insert, so a re-run - or a fresh install where `install_tenant`
already ran `event_service.backfill_tenant` - is a no-op). Postgres-only, no-op
under the SQLite pytest suite (module Alembic convention); the Python twin
`event_service.backfill_tenant` is what the test suite exercises directly.

Revision id <= 32 chars.

Revision ID: 0009_omni_conversation_events
Revises: 0008_omni_contact_model
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_omni_conversation_events"
down_revision = "0008_omni_contact_model"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_cols = {c["name"] for c in inspector.get_columns("contacts", schema=SCHEMA)}
    if "last_agent_message_at" not in existing_cols:
        op.add_column(
            "contacts",
            sa.Column("last_agent_message_at", sa.DateTime(timezone=True), nullable=True),
            schema=SCHEMA,
        )
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("contacts", schema=SCHEMA)}
    if "ix_omni_contacts_last_agent_message_at" not in existing_indexes:
        op.create_index(
            "ix_omni_contacts_last_agent_message_at",
            "contacts",
            ["last_agent_message_at"],
            schema=SCHEMA,
        )

    tables = set(inspector.get_table_names(schema=SCHEMA))
    if "conversation_events" not in tables:
        op.create_table(
            "conversation_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column(
                "workspace_id",
                sa.String(),
                sa.ForeignKey(f"{SCHEMA}.workspaces.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "contact_id",
                sa.String(),
                sa.ForeignKey(f"{SCHEMA}.contacts.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("actor_user_id", sa.String(), nullable=True),
            sa.Column("actor_external_agent_id", sa.String(), nullable=True),
            sa.Column("from_value", sa.String(), nullable=True),
            sa.Column("to_value", sa.String(), nullable=True),
            # No FK yet - `close_reasons` is plan 27 A3 slice S2's table.
            sa.Column("close_reason_id", sa.String(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_conv_events_ws_created", "conversation_events",
            ["tenant_id", "workspace_id", "created_at"], schema=SCHEMA,
        )
        op.create_index(
            "ix_conv_events_contact_created", "conversation_events",
            ["tenant_id", "contact_id", "created_at"], schema=SCHEMA,
        )
        op.create_index(
            "ix_conv_events_type_created", "conversation_events",
            ["tenant_id", "event_type", "created_at"], schema=SCHEMA,
        )

    # ── Backfill (§5.4) - snapshot "no events yet" BEFORE any insert into a
    # temp table so the three subsequent inserts (opened/closed/assigned) all
    # see the SAME candidate set, not a moving target (inserting `opened` rows
    # first would otherwise make every later `NOT EXISTS` check false within
    # this same transaction). ────────────────────────────────────────────────
    op.execute(
        f"""
        CREATE TEMP TABLE _conv_events_backfill AS
        SELECT c.id, c.tenant_id, c.workspace_id, c.status_id, c.created_at,
               c.updated_at, c.assigned_user_id, c.assigned_external_agent_id
        FROM "{SCHEMA}".contacts c
        WHERE NOT EXISTS (
            SELECT 1 FROM "{SCHEMA}".conversation_events e WHERE e.contact_id = c.id
        )
        """
    )
    op.execute(
        f"""
        INSERT INTO "{SCHEMA}".conversation_events
            (id, tenant_id, workspace_id, contact_id, event_type, to_value,
             payload_json, created_at)
        SELECT md5(random()::text || clock_timestamp()::text || b.id || 'opened')::uuid::text,
               b.tenant_id, b.workspace_id, b.id, 'opened', b.status_id,
               '{{"backfilled": true}}'::json, b.created_at
        FROM _conv_events_backfill b
        """
    )
    op.execute(
        f"""
        INSERT INTO "{SCHEMA}".conversation_events
            (id, tenant_id, workspace_id, contact_id, event_type, to_value,
             payload_json, created_at)
        SELECT md5(random()::text || clock_timestamp()::text || b.id || 'closed')::uuid::text,
               b.tenant_id, b.workspace_id, b.id, 'closed', b.status_id,
               '{{"backfilled": true}}'::json, b.updated_at
        FROM _conv_events_backfill b
        JOIN "{SCHEMA}".statuses s ON s.id = b.status_id AND s.scope = 'THREAD' AND s.key = 'CLOSED'
        """
    )
    op.execute(
        f"""
        INSERT INTO "{SCHEMA}".conversation_events
            (id, tenant_id, workspace_id, contact_id, event_type, to_value,
             payload_json, created_at)
        SELECT md5(random()::text || clock_timestamp()::text || b.id || 'assigned')::uuid::text,
               b.tenant_id, b.workspace_id, b.id, 'assigned',
               coalesce(b.assigned_user_id, b.assigned_external_agent_id),
               json_build_object(
                   'backfilled', true,
                   'assigneeKind',
                   CASE WHEN b.assigned_user_id IS NOT NULL THEN 'user' ELSE 'external_agent' END
               ),
               b.updated_at
        FROM _conv_events_backfill b
        WHERE b.assigned_user_id IS NOT NULL OR b.assigned_external_agent_id IS NOT NULL
        """
    )
    op.execute("DROP TABLE _conv_events_backfill")

    # last_agent_message_at (AC-IVE-11) - idempotent on its own (NULL guard),
    # no temp table needed.
    op.execute(
        f"""
        UPDATE "{SCHEMA}".contacts c
        SET last_agent_message_at = sub.max_at
        FROM (
            SELECT contact_id, max(created_at) AS max_at
            FROM "{SCHEMA}".conversation_messages
            WHERE sender_type = 'AGENT'
            GROUP BY contact_id
        ) sub
        WHERE sub.contact_id = c.id AND c.last_agent_message_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_conv_events_type_created", table_name="conversation_events", schema=SCHEMA)
    op.drop_index("ix_conv_events_contact_created", table_name="conversation_events", schema=SCHEMA)
    op.drop_index("ix_conv_events_ws_created", table_name="conversation_events", schema=SCHEMA)
    op.drop_table("conversation_events", schema=SCHEMA)
    op.drop_index("ix_omni_contacts_last_agent_message_at", table_name="contacts", schema=SCHEMA)
    op.drop_column("contacts", "last_agent_message_at", schema=SCHEMA)
