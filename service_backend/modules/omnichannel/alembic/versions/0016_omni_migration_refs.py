"""omnichannel plan 33 S2 - respond.io migration refs (roadmap A6).

Adds `migration_refs` (the ONE idempotency index for the respond.io migration
tool, D-A6-3, §5.3) and descriptive `migrated_from` markers on
`contacts`/`conversation_messages`. Idempotent guards (inspector checks),
mirrors `0012_omni_team_assignment`'s style. Revision id <= 32 chars.

Merge-renumber note (plan §3, D-A6-21, binding on whoever merges A6): `0016`
is a placeholder matching this lane's cut of `main` (module head `0012`,
manifest `0.7.0`, S1 commit). Before merging, re-check
`modules/omnichannel/alembic/versions/` on the then-current `main`: rename
this file + its `revision` id to `00NN` (`NN = max(existing) + 1`), re-point
`down_revision` at the then-current head (add a merge revision if two lanes
left two heads - never silently pick one), and bump `manifest.json` to
`0.<max existing minor + 1>.0` if another lane has since taken `0.7.0` first.

Revision ID: 0016_omni_migration_refs
Revises: 0012_omni_team_assignment
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_omni_migration_refs"
down_revision = "0012_omni_team_assignment"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── migration_refs (D-A6-3, §5.3) ───────────────────────────────────────
    tables = set(inspector.get_table_names(schema=SCHEMA))
    if "migration_refs" not in tables:
        op.create_table(
            "migration_refs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column(
                "workspace_id",
                sa.String(),
                sa.ForeignKey(f"{SCHEMA}.workspaces.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("external_id", sa.String(), nullable=False),
            sa.Column("local_id", sa.String(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint(
                "tenant_id", "workspace_id", "source", "entity_type", "external_id",
                name="uq_migration_refs_external",
            ),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_migration_refs_local",
            "migration_refs",
            ["tenant_id", "workspace_id", "source", "entity_type", "local_id"],
            schema=SCHEMA,
        )

    # ── contacts.migrated_from (descriptive marker, D-A6-3) ─────────────────
    existing_cols = {c["name"] for c in inspector.get_columns("contacts", schema=SCHEMA)}
    if "migrated_from" not in existing_cols:
        op.add_column(
            "contacts", sa.Column("migrated_from", sa.String(), nullable=True), schema=SCHEMA
        )
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("contacts", schema=SCHEMA)}
    if "ix_omni_contacts_migrated_from" not in existing_indexes:
        op.create_index(
            "ix_omni_contacts_migrated_from", "contacts", ["migrated_from"], schema=SCHEMA
        )

    # ── conversation_messages.migrated_from (S3+ writes it; column lands now
    # so the whole S2-S4 arc shares ONE migration for both marker columns) ──
    existing_msg_cols = {
        c["name"] for c in inspector.get_columns("conversation_messages", schema=SCHEMA)
    }
    if "migrated_from" not in existing_msg_cols:
        op.add_column(
            "conversation_messages",
            sa.Column("migrated_from", sa.String(), nullable=True),
            schema=SCHEMA,
        )
    existing_msg_indexes = {
        ix["name"] for ix in inspector.get_indexes("conversation_messages", schema=SCHEMA)
    }
    if "ix_omni_conv_messages_migrated_from" not in existing_msg_indexes:
        op.create_index(
            "ix_omni_conv_messages_migrated_from",
            "conversation_messages",
            ["migrated_from"],
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_omni_conv_messages_migrated_from", table_name="conversation_messages", schema=SCHEMA
    )
    op.drop_column("conversation_messages", "migrated_from", schema=SCHEMA)
    op.drop_index("ix_omni_contacts_migrated_from", table_name="contacts", schema=SCHEMA)
    op.drop_column("contacts", "migrated_from", schema=SCHEMA)
    op.drop_index("ix_migration_refs_local", table_name="migration_refs", schema=SCHEMA)
    op.drop_table("migration_refs", schema=SCHEMA)
