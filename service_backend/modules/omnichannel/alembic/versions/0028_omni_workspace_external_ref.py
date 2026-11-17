"""omnichannel S7 - partner workspaces keyed by the partner's organisation id.

Adds `workspaces.external_ref` (VARCHAR, nullable) and the partial unique index
`uq_workspaces_tenant_external_ref (tenant_id, external_ref) WHERE external_ref
IS NOT NULL AND is_trashed = false`.

Online-safe: adding a nullable column with no default is a metadata-only change;
`workspaces` is a small table (a handful of rows per tenant), so a plain index
build is brief. Existing rows stay NULL and are outside the partial index, so
no backfill is needed (no workspace ever had a partner organisation id).
Idempotent (IF NOT EXISTS), same style as the `create_schema_and_tables`
mirror. Revision id <= 32 chars.

Revision ID: 0028_omni_workspace_external_ref
Revises: 0027_omni_partner_api_keys
Create Date: 2026-11-18
"""
from alembic import op

revision = "0028_omni_workspace_external_ref"
down_revision = "0027_omni_partner_api_keys"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    op.execute(f'ALTER TABLE "{SCHEMA}".workspaces ADD COLUMN IF NOT EXISTS external_ref VARCHAR')
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_tenant_external_ref "
        f'ON "{SCHEMA}".workspaces (tenant_id, external_ref) '
        "WHERE external_ref IS NOT NULL AND is_trashed = false"
    )


def downgrade() -> None:
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".uq_workspaces_tenant_external_ref')
    op.execute(f'ALTER TABLE "{SCHEMA}".workspaces DROP COLUMN IF EXISTS external_ref')
