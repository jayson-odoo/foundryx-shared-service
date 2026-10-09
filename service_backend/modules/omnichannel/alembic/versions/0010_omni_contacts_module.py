"""omnichannel plan 26 S1 - contacts module (segments + phone_digits).

Adds `contact_segments` (per-workspace saved filter trees, plan §5.2/D-A2-3)
and `contacts.phone_digits` (normalized digits mirror of `phone`, D-A2-9) +
backfills every existing row. Idempotent guards (inspector checks), mirrors
`0008_omni_contact_model`'s style. Revision id <= 32 chars.

Merge note (resolved 2026-09-06): this branch's manifest was at 0.2.0 when
this migration was authored; `down_revision` was originally pinned to 0008
because a sibling lane (A3) owned 0009 (`omni_conversation_events`) +
0009a (`omni_inbox_views`) on a different branch/worktree. This lane (A2)
merged second, so `down_revision` is rebased onto A3's chain tip (0009a) to
keep the module's Alembic history linear (exactly one head).

Revision ID: 0010_omni_contacts_module
Revises: 0009a_omni_inbox_views
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_omni_contacts_module"
down_revision = "0009a_omni_inbox_views"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── contacts.phone_digits (D-A2-9) ──────────────────────────────────────
    existing_cols = {c["name"] for c in inspector.get_columns("contacts", schema=SCHEMA)}
    if "phone_digits" not in existing_cols:
        op.add_column("contacts", sa.Column("phone_digits", sa.String(), nullable=True), schema=SCHEMA)
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("contacts", schema=SCHEMA)}
    if "ix_omni_contacts_phone_digits" not in existing_indexes:
        op.create_index("ix_omni_contacts_phone_digits", "contacts", ["phone_digits"], schema=SCHEMA)

    # Backfill every existing row whose phone_digits hasn't been stamped yet -
    # idempotent (only NULL rows are touched), Postgres-only (module Alembic
    # never runs under pytest - CLAUDE.md), matches the file's other bulk
    # backfills (plain `op.execute`, no separate engine/session - stays inside
    # Alembic's own migration transaction).
    op.execute(
        f'UPDATE "{SCHEMA}".contacts '
        "SET phone_digits = regexp_replace(phone, '[^0-9]', '', 'g') "
        "WHERE phone_digits IS NULL AND phone IS NOT NULL"
    )

    # ── contact_segments (D-A2-3) ────────────────────────────────────────────
    tables = set(inspector.get_table_names(schema=SCHEMA))
    if "contact_segments" not in tables:
        op.create_table(
            "contact_segments",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column(
                "workspace_id",
                sa.String(),
                sa.ForeignKey(f"{SCHEMA}.workspaces.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("filter_json", sa.JSON(), nullable=True),
            sa.Column("created_by_user_id", sa.String(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            schema=SCHEMA,
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_segments_workspace_name "
        f'ON "{SCHEMA}".contact_segments (workspace_id, lower(name))'
    )


def downgrade() -> None:
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".uq_contact_segments_workspace_name')
    op.drop_table("contact_segments", schema=SCHEMA)
    op.drop_index("ix_omni_contacts_phone_digits", table_name="contacts", schema=SCHEMA)
    op.drop_column("contacts", "phone_digits", schema=SCHEMA)
