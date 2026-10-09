"""omnichannel plan 29 S1 - broadcasts (campaign model + audience + recipients).

Adds `channels.broadcast_rate_per_second` (D-A4-12, per-channel send pacing
tier) and two new tables: `broadcasts` (the campaign object - audience
CONFIGURATION, template + structured bindings, denormalized status/counts)
and `broadcast_recipients` (the send-time ledger, `UNIQUE(broadcast_id,
contact_id)` the per-recipient idempotency backstop S2 relies on). Idempotent
guards (inspector checks), mirrors `0010_omni_contacts_module`'s style.
Revision id <= 32 chars.

`broadcasts.channel_id`/`template_id`/`audience_segment_id` and
`broadcast_recipients.contact_id` are PLAIN INDEXED columns - NOT DB-level
FKs (BL-030 convention, same as `job_id`/`created_by_user_id`/`message_id`
elsewhere on this table). A channel/template/segment/contact hard-delete
must never be blocked by a historical broadcast (review round 1, B1).

Revision ID: 0011_omni_broadcasts
Revises: 0010_omni_contacts_module
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_omni_broadcasts"
down_revision = "0010_omni_contacts_module"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── channels.broadcast_rate_per_second (D-A4-12) ────────────────────────
    existing_channel_cols = {c["name"] for c in inspector.get_columns("channels", schema=SCHEMA)}
    if "broadcast_rate_per_second" not in existing_channel_cols:
        op.add_column(
            "channels",
            sa.Column("broadcast_rate_per_second", sa.Integer(), nullable=True),
            schema=SCHEMA,
        )

    tables = set(inspector.get_table_names(schema=SCHEMA))

    # ── broadcasts (D-A4-1) ──────────────────────────────────────────────────
    if "broadcasts" not in tables:
        op.create_table(
            "broadcasts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column(
                "workspace_id", sa.String(), sa.ForeignKey(f"{SCHEMA}.workspaces.id"),
                nullable=False, index=True,
            ),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("labels_json", sa.JSON(), nullable=True),
            # No FK (BL-030) - a channel hard-delete must not be blocked.
            sa.Column("channel_id", sa.String(), nullable=False, index=True),
            sa.Column("audience_kind", sa.String(), nullable=False),
            # No FK (BL-030) - a segment delete must not be blocked.
            sa.Column("audience_segment_id", sa.String(), nullable=True, index=True),
            sa.Column("audience_filter_json", sa.JSON(), nullable=True),
            sa.Column("audience_contact_ids_json", sa.JSON(), nullable=True),
            # No FK (BL-030) - a template delete must not be blocked;
            # template_name/template_language below are denormalized.
            sa.Column("template_id", sa.String(), nullable=False, index=True),
            sa.Column("template_name", sa.String(), nullable=False),
            sa.Column("template_language", sa.String(), nullable=True),
            sa.Column("bindings_json", sa.JSON(), nullable=True),
            sa.Column(
                "status_id", sa.String(), sa.ForeignKey(f"{SCHEMA}.statuses.id"),
                nullable=False, index=True,
            ),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("read_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("job_id", sa.String(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", sa.String(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_broadcasts_tenant_ws_status_scheduled",
            "broadcasts",
            ["tenant_id", "workspace_id", "status_id", "scheduled_at"],
            schema=SCHEMA,
        )

    # ── broadcast_recipients (D-A4-1) ────────────────────────────────────────
    if "broadcast_recipients" not in tables:
        op.create_table(
            "broadcast_recipients",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column(
                "broadcast_id", sa.String(), sa.ForeignKey(f"{SCHEMA}.broadcasts.id"),
                nullable=False, index=True,
            ),
            # No FK (BL-030) - a contact hard-delete must not be blocked.
            sa.Column("contact_id", sa.String(), nullable=False, index=True),
            sa.Column("message_id", sa.String(), nullable=True, index=True),
            sa.Column("state", sa.String(), nullable=False, server_default="queued"),
            sa.Column("skip_reason", sa.String(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("error_text", sa.Text(), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint("broadcast_id", "contact_id", name="uq_broadcast_recipient"),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_broadcast_recipients_tenant_broadcast_state",
            "broadcast_recipients",
            ["tenant_id", "broadcast_id", "state"],
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_table("broadcast_recipients", schema=SCHEMA)
    op.drop_table("broadcasts", schema=SCHEMA)
    op.drop_column("channels", "broadcast_rate_per_second", schema=SCHEMA)
