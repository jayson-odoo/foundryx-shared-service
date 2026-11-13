"""omnichannel plan 27 A3 S2 - close reasons + saved inbox views.

Adds `close_reasons` (per-workspace, seeded on create) and `inbox_views`
(typed-filter saved views, D-A3-2) tables, a case-insensitive per-workspace
UNIQUE index on each, and the FK `conversation_events.close_reason_id ->
close_reasons.id` that S1 reserved (always NULL until this slice's
`close_thread`). Backfills the four seeded close reasons for every
pre-existing workspace that has none (AC-IVE-27) - idempotent (a workspace
that already has a reason is skipped). Postgres-only, no-op under the SQLite
pytest suite (module Alembic convention); the Python twin
`close_reason_service.backfill_tenant` is what the test suite exercises.

Revision id <= 32 chars. Named `0009a` (not `0010`/`0011`) to dodge both the
A2 lane's `0010` and the A8 lane's `0011` claims on this same `main` base
(D-A3-16 sibling collision) - see the plan's Decisions table.

Revision ID: 0009a_omni_inbox_views
Revises: 0009_omni_conversation_events
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0009a_omni_inbox_views"
down_revision = "0009_omni_conversation_events"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"

SEEDED_REASONS = ("General Inquiry", "Sales Inquiry", "Payment Issue", "Others")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema=SCHEMA))

    if "close_reasons" not in tables:
        op.create_table(
            "close_reasons",
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
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            schema=SCHEMA,
        )
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("close_reasons", schema=SCHEMA)} if "close_reasons" in tables else set()
    if "uq_close_reasons_workspace_name" not in existing_indexes:
        op.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS uq_close_reasons_workspace_name '
            f'ON "{SCHEMA}".close_reasons (workspace_id, lower(name))'
        )

    tables = set(inspector.get_table_names(schema=SCHEMA))
    if "inbox_views" not in tables:
        op.create_table(
            "inbox_views",
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
            sa.Column("owner_user_id", sa.String(), nullable=False, index=True),
            sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("filter_json", sa.JSON(), nullable=True),
            sa.Column("segment_id", sa.String(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            schema=SCHEMA,
        )
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("inbox_views", schema=SCHEMA)} if "inbox_views" in tables else set()
    if "uq_inbox_views_workspace_name" not in existing_indexes:
        op.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS uq_inbox_views_workspace_name '
            f'ON "{SCHEMA}".inbox_views (workspace_id, lower(name))'
        )

    # FK reserved by S1 - add it now that close_reasons exists. Every existing
    # `close_reason_id` value is NULL (S2 is the first writer), so this can
    # never fail on live data.
    #
    # Round-3 codex triage B6: detect by (columns, referred table), NOT by
    # constraint NAME - `install()`'s `create_schema_and_tables` runs
    # `OmniBase.metadata.create_all` on EVERY boot BEFORE this per-module
    # Alembic detection (`_bootstrap_one_module`). On a deployment mid-upgrade
    # (an `alembic_version_omnichannel` row already at 0008, `conversation_
    # events` not created yet), that `create_all` call fresh-creates
    # `conversation_events` complete with the model's embedded
    # `ForeignKey("close_reasons.id")` - under a Postgres AUTO-GENERATED name
    # (`..._close_reason_id_fkey`), not this migration's literal
    # `fk_conv_events_close_reason`. A name-only check misses that constraint
    # and adds a SECOND, redundant FK on the same column/target; downgrade
    # then can't drop the auto-named one at all (it only knows its own
    # literal name). Detecting by the real (columns, table) shape is
    # name-agnostic on both sides.
    existing_fks = inspector.get_foreign_keys("conversation_events", schema=SCHEMA)

    def _find_close_reason_fk(fks):
        for fk in fks:
            if (
                list(fk.get("constrained_columns") or []) == ["close_reason_id"]
                and fk.get("referred_table") == "close_reasons"
            ):
                return fk
        return None

    if _find_close_reason_fk(existing_fks) is None:
        op.create_foreign_key(
            "fk_conv_events_close_reason",
            "conversation_events",
            "close_reasons",
            ["close_reason_id"],
            ["id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
        )

    # Backfill (AC-IVE-27): seed the four default reasons for every workspace
    # that has none yet - idempotent (a workspace with any reason is skipped).
    reasons_literal = ", ".join(f"'{name}'" for name in SEEDED_REASONS)
    op.execute(
        f"""
        INSERT INTO "{SCHEMA}".close_reasons
            (id, tenant_id, workspace_id, name, sort_order, is_active, created_at, updated_at)
        SELECT md5(random()::text || clock_timestamp()::text || w.id || r.name)::uuid::text,
               w.tenant_id, w.id, r.name, r.ord - 1, true, now(), now()
        FROM "{SCHEMA}".workspaces w
        CROSS JOIN (
            SELECT * FROM unnest(ARRAY[{reasons_literal}]) WITH ORDINALITY AS t(name, ord)
        ) r
        WHERE NOT EXISTS (
            SELECT 1 FROM "{SCHEMA}".close_reasons cr WHERE cr.workspace_id = w.id
        )
        """
    )


def downgrade() -> None:
    # B6 - drop by the ACTUAL constraint (columns, referred table), whatever
    # its name (this migration's `fk_conv_events_close_reason` OR the
    # auto-generated `..._close_reason_id_fkey` `create_all` may have left in
    # place - see the upgrade()-side comment). Conditional: nothing to drop on
    # a deployment that never created the column's FK at all.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys("conversation_events", schema=SCHEMA):
        if (
            list(fk.get("constrained_columns") or []) == ["close_reason_id"]
            and fk.get("referred_table") == "close_reasons"
            and fk.get("name")
        ):
            op.drop_constraint(
                fk["name"], "conversation_events", schema=SCHEMA, type_="foreignkey"
            )
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".uq_inbox_views_workspace_name')
    op.drop_table("inbox_views", schema=SCHEMA)
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".uq_close_reasons_workspace_name')
    op.drop_table("close_reasons", schema=SCHEMA)
