"""omnichannel plan 33 review round 1 - migration upload receipts (finding B2).

Adds `migration_uploads` (the tenant-scoped upload receipt `MigrationJobCreate.
contactsUploadId`/`snippetsUploadId` resolve against, review B2) - a client
used to be able to hand the job-create route ANY storage-key string
(`contactsCsvKey`/`snippetsCsvKey`), fetched unvalidated (path traversal /
cross-tenant blob read). Idempotent guards (inspector checks), mirrors
`0016_omni_migration_refs`'s own style. Revision id <= 32 chars.

Merge-renumber note (mirrors 0016's own, D-A6-21, binding on whoever merges
A6): re-check `modules/omnichannel/alembic/versions/` on the then-current
`main` before merging - rename this file + its `revision`/`down_revision` to
the then-current head's next free number.

`created_at` uses `sa.DateTime(timezone=True)` (review round 1 nit, checked
against `0012_omni_team_assignment` - confirmed the SAME convention this
whole module's Alembic migrations already use; the ORM model's `UTCDateTime`
TypeDecorator only affects the Python-side value, not the underlying
Postgres column type, so no `app.models.utc_datetime` import is needed here).

Revision ID: 0017_omni_migration_uploads
Revises: 0016_omni_migration_refs
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_omni_migration_uploads"
down_revision = "0016_omni_migration_refs"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names(schema=SCHEMA))
    if "migration_uploads" not in tables:
        op.create_table(
            "migration_uploads",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column(
                "workspace_id",
                sa.String(),
                sa.ForeignKey(f"{SCHEMA}.workspaces.id"),
                nullable=True,
                index=True,
            ),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("storage_key", sa.String(), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("headers_json", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_omni_migration_uploads_tenant",
            "migration_uploads",
            ["tenant_id"],
            schema=SCHEMA,
        )
        op.create_index(
            "ix_omni_migration_uploads_workspace",
            "migration_uploads",
            ["workspace_id"],
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_index("ix_omni_migration_uploads_workspace", table_name="migration_uploads", schema=SCHEMA)
    op.drop_index("ix_omni_migration_uploads_tenant", table_name="migration_uploads", schema=SCHEMA)
    op.drop_table("migration_uploads", schema=SCHEMA)
