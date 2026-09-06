"""omnichannel plan 28 S2 - team assignment (roadmap A8).

Adds `contacts.assigned_team_id` (plain indexed String holding a CORE
`teams.id`, no cross-schema FK - the `lifecycle_status_id`/BL-030 pattern) and
`team_assignment_settings` (per (workspace, team) pick strategy + the
persisted round-robin cursor, D-A8-8/9). Idempotent guards (inspector checks),
mirrors `0010_omni_contacts_module`'s style. Revision id <= 32 chars.

Merge-order note (flagged at build time 2026-09-06): the sibling lane A4
(plan 29, broadcasts) is ALSO taking `0011_omni_broadcasts` on `0010` +
manifest `0.5.0` concurrently. Whichever of the two merges to `main` SECOND
must renumber its migration to `0012`, rebase `down_revision` onto the other's
tip, and bump the manifest to `0.6.0` - noted here so the merging agent does
not have to re-derive it from scratch.

Revision ID: 0011_omni_team_assignment
Revises: 0010_omni_contacts_module
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_omni_team_assignment"
down_revision = "0010_omni_contacts_module"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── contacts.assigned_team_id (D-A8-3) ──────────────────────────────────
    existing_cols = {c["name"] for c in inspector.get_columns("contacts", schema=SCHEMA)}
    if "assigned_team_id" not in existing_cols:
        op.add_column(
            "contacts", sa.Column("assigned_team_id", sa.String(), nullable=True), schema=SCHEMA
        )
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("contacts", schema=SCHEMA)}
    if "ix_omni_contacts_assigned_team_id" not in existing_indexes:
        op.create_index(
            "ix_omni_contacts_assigned_team_id", "contacts", ["assigned_team_id"], schema=SCHEMA
        )

    # No data backfill needed - a nullable column starting NULL on every
    # existing row is a valid "no team assigned" state (AC-TEM-18).

    # ── team_assignment_settings (D-A8-8/9) ─────────────────────────────────
    tables = set(inspector.get_table_names(schema=SCHEMA))
    if "team_assignment_settings" not in tables:
        op.create_table(
            "team_assignment_settings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column(
                "workspace_id",
                sa.String(),
                sa.ForeignKey(f"{SCHEMA}.workspaces.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("team_id", sa.String(), nullable=False, index=True),
            sa.Column("strategy", sa.String(), nullable=False, server_default="round_robin"),
            sa.Column("last_assigned_user_id", sa.String(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint(
                "workspace_id", "team_id", name="uq_team_assignment_settings_ws_team"
            ),
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_table("team_assignment_settings", schema=SCHEMA)
    op.drop_index("ix_omni_contacts_assigned_team_id", table_name="contacts", schema=SCHEMA)
    op.drop_column("contacts", "assigned_team_id", schema=SCHEMA)
