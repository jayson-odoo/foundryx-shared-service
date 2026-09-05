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


def downgrade() -> None:
    op.drop_table("contact_tag_links", schema=SCHEMA)
    op.drop_table("contact_tags", schema=SCHEMA)
    op.drop_table("contact_fields", schema=SCHEMA)
    op.drop_index("ix_omni_contacts_lifecycle_status_id", table_name="contacts", schema=SCHEMA)
    for name in ("lifecycle_status_id", "country_code", "language"):
        op.drop_column("contacts", name, schema=SCHEMA)
