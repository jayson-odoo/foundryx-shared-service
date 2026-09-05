"""omnichannel plan 25 S1 - contact data model (typed fields registry + tags).

Adds `contacts.language` / `contacts.country_code` / `contacts.lifecycle_status_id`
(all nullable - no backfill needed, S2 sets `lifecycle_status_id` on new/existing
rows once the scoped status entity lands; the wire `lifecycle` field stays null
until then) plus three new tables: `contact_fields` (per-workspace custom-field
registry), `contact_tags`, `contact_tag_links`. Idempotent guards (inspector
checks) - the module baseline runs create_all so a fresh deploy may already
have these. Revision id <= 32 chars.

Revision ID: 0008_omni_contact_model
Revises: 0007_omni_merge_heads
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_omni_contact_model"
down_revision = "0007_omni_merge_heads"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_cols = {c["name"] for c in inspector.get_columns("contacts", schema=SCHEMA)}
    new_cols = [
        ("language", sa.String()),
        ("country_code", sa.String()),
        ("lifecycle_status_id", sa.String()),
    ]
    for name, coltype in new_cols:
        if name not in existing_cols:
            op.add_column("contacts", sa.Column(name, coltype, nullable=True), schema=SCHEMA)
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("contacts", schema=SCHEMA)}
    if "ix_omni_contacts_lifecycle_status_id" not in existing_indexes:
        op.create_index(
            "ix_omni_contacts_lifecycle_status_id",
            "contacts",
            ["lifecycle_status_id"],
            schema=SCHEMA,
        )

    tables = set(inspector.get_table_names(schema=SCHEMA))

    if "contact_fields" not in tables:
        op.create_table(
            "contact_fields",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("workspace_id", sa.String(), nullable=False, index=True),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("options_json", sa.JSON(), nullable=True),
            sa.Column("visibility", sa.String(), nullable=False, server_default="always"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            schema=SCHEMA,
        )

    if "contact_tags" not in tables:
        op.create_table(
            "contact_tags",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("workspace_id", sa.String(), nullable=False, index=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("emoji", sa.String(), nullable=True),
            sa.Column("color", sa.String(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            schema=SCHEMA,
        )

    if "contact_tag_links" not in tables:
        op.create_table(
            "contact_tag_links",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("contact_id", sa.String(), nullable=False, index=True),
            sa.Column("tag_id", sa.String(), nullable=False, index=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint("contact_id", "tag_id", name="uq_contact_tag_link"),
            schema=SCHEMA,
        )

    # Review round 1, finding 9: the app-level `_find_by_key`/`_find_by_name`
    # case-insensitive checks race (two concurrent creates can both pass the
    # SELECT before either INSERTs) - `resolve_or_create_by_name` on the public
    # gateway is the exposed race. Add the DB backstop as a functional unique
    # index (mirrors the `uq_channels_phone_number_id` partial-index pattern
    # above). Best-effort auto-heal any pre-existing duplicate FIRST (a field's
    # `key`/a tag's `name` is NOT NULL and user-visible, so - unlike
    # `phone_number_id` - losers are renamed with a short id-derived suffix,
    # never nulled) so the index can be created on a live DB with stray dupes.
    op.execute(
        f"""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY workspace_id, lower(key)
                       ORDER BY created_at, id
                   ) AS rn
            FROM "{SCHEMA}".contact_fields
        )
        UPDATE "{SCHEMA}".contact_fields cf
        SET key = substr(cf.key, 1, 30) || '_' || substr(cf.id, 1, 8)
        FROM ranked
        WHERE cf.id = ranked.id AND ranked.rn > 1
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_fields_workspace_key "
        f'ON "{SCHEMA}".contact_fields (workspace_id, lower(key))'
    )
    op.execute(
        f"""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY workspace_id, lower(name)
                       ORDER BY created_at, id
                   ) AS rn
            FROM "{SCHEMA}".contact_tags
        )
        UPDATE "{SCHEMA}".contact_tags ct
        SET name = substr(ct.name, 1, 50) || '_' || substr(ct.id, 1, 8)
        FROM ranked
        WHERE ct.id = ranked.id AND ranked.rn > 1
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_tags_workspace_name "
        f'ON "{SCHEMA}".contact_tags (workspace_id, lower(name))'
    )


def downgrade() -> None:
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".uq_contact_tags_workspace_name')
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".uq_contact_fields_workspace_key')
    op.drop_table("contact_tag_links", schema=SCHEMA)
    op.drop_table("contact_tags", schema=SCHEMA)
    op.drop_table("contact_fields", schema=SCHEMA)
    op.drop_index("ix_omni_contacts_lifecycle_status_id", table_name="contacts", schema=SCHEMA)
    for name in ("lifecycle_status_id", "country_code", "language"):
        op.drop_column("contacts", name, schema=SCHEMA)
