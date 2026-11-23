"""omnichannel - client apps: a real parent for workspaces and partner keys.

Step by step (every step idempotent, so a re-run or a database that already got
part of it from the `create_schema_and_tables` mirror is safe):

1. Create `client_apps` (tenant_id, name unique per tenant on
   lower(trim(name)), slug unique per tenant (left NULL for now), is_default
   with one default per tenant, status ACTIVE/DISABLED, allowed_return_origins
   reserved for later, created_by, created_at, updated_at). No secrets.
2. Add `workspaces.client_app_id` and `partner_api_keys.client_app_id`:
   NULLABLE, no default (metadata-only, no table rewrite). They stay nullable
   in this release so an older running version, which inserts without them,
   keeps working during blue/green and after a rollback (DEPLOY.md
   "Rollback"). A later migration makes them NOT NULL.
3. Backfill (only rows whose parent is still NULL; every step idempotent):
   a. Workspaces without an external_ref, live or trashed, are grouped per
      tenant by normalised name (trimmed, case-insensitive). Each group gets
      ONE client app named after the group's live workspace (exact name,
      trimmed), or the oldest one when several or none are live. An existing
      client app of the tenant with the same normalised name is reused, so a
      re-run creates nothing.
   b. Each such workspace is attached to its group's client app.
   c. A tenant with no default client app gets exactly one: the client app of
      its default workspace (`workspaces.is_default`, live first, oldest
      first), else its oldest client app.
   d. A workspace WITH an external_ref (made through the partner route,
      PR 269) attaches to the tenant's default client app, which is the one
      every pre-existing partner key belongs to. One whose external_ref
      another live workspace of the tenant also carries is left NULL, so the
      fill-in can never trip the unique index below.
   e. Partner keys attach to the tenant's default client app (Alembic
      ordering guarantees `partner_api_keys` exists: 0028 precedes this). A
      key of a tenant with no workspace at all stays NULL here; the code
      gives it a default client app named after the tenant on first use.
   Workspace keys and webhooks hang off the workspace and are untouched.
4. Foreign keys added NOT VALID, then VALIDATE (short locks), plus indexes.
5. `external_ref` uniqueness moves from per tenant to per client app: drop
   `uq_workspaces_tenant_external_ref` (IF EXISTS: works whether or not 0031
   ran anywhere) and create `uq_workspaces_client_app_external_ref`.

`workspaces` and `partner_api_keys` hold a handful of rows per tenant, so the
fill-in fits the bootstrap lock_timeout without batching. Revision id <= 32.

Downgrade drops the new index, restores the per-tenant external_ref index,
drops both columns (their foreign keys go with them) and the table. Only the
client app names are lost.

Revision ID: 0032_omni_client_apps
Revises: 0031_omni_workspace_external_ref
Create Date: 2026-11-20
"""
from alembic import op

revision = "0032_omni_client_apps"
down_revision = "0031_omni_workspace_external_ref"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"

CREATE_TABLE = (
    f'CREATE TABLE IF NOT EXISTS "{SCHEMA}".client_apps ('
    "id VARCHAR NOT NULL, "
    "tenant_id VARCHAR NOT NULL, "
    "name VARCHAR NOT NULL, "
    "slug VARCHAR, "
    "is_default BOOLEAN DEFAULT false NOT NULL, "
    "status VARCHAR DEFAULT 'ACTIVE' NOT NULL, "
    "allowed_return_origins JSON, "
    "created_by VARCHAR, "
    "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, "
    "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, "
    "PRIMARY KEY (id), "
    "CONSTRAINT ck_client_apps_status CHECK (status IN ('ACTIVE', 'DISABLED')))"
)

TABLE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_app_omnichannel_client_apps_tenant_id "
    f'ON "{SCHEMA}".client_apps (tenant_id)',
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_apps_tenant_slug "
    f'ON "{SCHEMA}".client_apps (tenant_id, slug)',
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_apps_tenant_name "
    f'ON "{SCHEMA}".client_apps (tenant_id, lower(trim(name)))',
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_apps_tenant_default "
    f'ON "{SCHEMA}".client_apps (tenant_id) WHERE is_default = true',
]


def _fk(table: str) -> str:
    name = f"fk_{table}_client_app_id"
    return (
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        f"WHERE conname = '{name}' AND connamespace = '{SCHEMA}'::regnamespace) THEN "
        f'ALTER TABLE "{SCHEMA}".{table} ADD CONSTRAINT {name} '
        f'FOREIGN KEY (client_app_id) REFERENCES "{SCHEMA}".client_apps (id) NOT VALID; '
        "END IF; END $$"
    )


# The part `create_schema_and_tables` mirrors statement for statement
# (pinned by tests/test_omnichannel_client_apps.py).
MIRRORED = [
    f'ALTER TABLE "{SCHEMA}".workspaces ADD COLUMN IF NOT EXISTS client_app_id VARCHAR',
    f'ALTER TABLE "{SCHEMA}".partner_api_keys ADD COLUMN IF NOT EXISTS client_app_id VARCHAR',
    # 3a. one client app per normalised workspace name per tenant
    f'INSERT INTO "{SCHEMA}".client_apps '
    "(id, tenant_id, name, is_default, status, created_by, created_at, updated_at) "
    "SELECT gen_random_uuid()::text, g.tenant_id, g.name, false, 'ACTIVE', 'backfill', now(), now() "
    "FROM (SELECT DISTINCT ON (w.tenant_id, lower(trim(w.name))) "
    "w.tenant_id, trim(w.name) AS name, lower(trim(w.name)) AS norm "
    f'FROM "{SCHEMA}".workspaces w '
    "WHERE w.client_app_id IS NULL AND w.external_ref IS NULL "
    "ORDER BY w.tenant_id, lower(trim(w.name)), w.is_trashed ASC, w.created_at ASC, w.id ASC) g "
    f'WHERE NOT EXISTS (SELECT 1 FROM "{SCHEMA}".client_apps c '
    "WHERE c.tenant_id = g.tenant_id AND lower(trim(c.name)) = g.norm)",
    # 3b. attach each workspace to its name group's client app
    f'UPDATE "{SCHEMA}".workspaces w SET client_app_id = c.id '
    f'FROM "{SCHEMA}".client_apps c '
    "WHERE w.client_app_id IS NULL AND w.external_ref IS NULL "
    "AND c.tenant_id = w.tenant_id AND lower(trim(c.name)) = lower(trim(w.name))",
    # 3c. exactly one default per tenant: the default workspace's client app, else the oldest
    f'UPDATE "{SCHEMA}".client_apps SET is_default = true '
    "WHERE id IN (SELECT DISTINCT ON (a.tenant_id) a.id "
    f'FROM "{SCHEMA}".client_apps a '
    f'LEFT JOIN "{SCHEMA}".workspaces dw ON dw.client_app_id = a.id AND dw.is_default = true '
    f'WHERE NOT EXISTS (SELECT 1 FROM "{SCHEMA}".client_apps d '
    "WHERE d.tenant_id = a.tenant_id AND d.is_default = true) "
    "ORDER BY a.tenant_id, (dw.id IS NULL) ASC, dw.is_trashed ASC, dw.created_at ASC, "
    "a.created_at ASC, "
    f'(SELECT min(x.created_at) FROM "{SCHEMA}".workspaces x WHERE x.client_app_id = a.id) ASC NULLS LAST, '
    "a.id ASC)",
    # 3d. partner-made workspaces (external_ref) join the tenant's default client app
    f'UPDATE "{SCHEMA}".workspaces w SET client_app_id = c.id '
    f'FROM "{SCHEMA}".client_apps c '
    "WHERE c.tenant_id = w.tenant_id AND c.is_default = true "
    "AND w.client_app_id IS NULL AND w.external_ref IS NOT NULL "
    "AND (w.is_trashed = true OR NOT EXISTS ("
    f'SELECT 1 FROM "{SCHEMA}".workspaces d WHERE d.tenant_id = w.tenant_id '
    "AND d.id <> w.id AND d.external_ref = w.external_ref AND d.is_trashed = false))",
    # 3e. partner keys join the tenant's default client app
    f'UPDATE "{SCHEMA}".partner_api_keys k SET client_app_id = c.id '
    f'FROM "{SCHEMA}".client_apps c '
    "WHERE c.tenant_id = k.tenant_id AND c.is_default = true AND k.client_app_id IS NULL",
    # 4. foreign keys (NOT VALID then VALIDATE) and indexes
    _fk("workspaces"),
    _fk("partner_api_keys"),
    f'ALTER TABLE "{SCHEMA}".workspaces VALIDATE CONSTRAINT fk_workspaces_client_app_id',
    f'ALTER TABLE "{SCHEMA}".partner_api_keys VALIDATE CONSTRAINT fk_partner_api_keys_client_app_id',
    "CREATE INDEX IF NOT EXISTS ix_app_omnichannel_workspaces_client_app_id "
    f'ON "{SCHEMA}".workspaces (client_app_id)',
    "CREATE INDEX IF NOT EXISTS ix_app_omnichannel_partner_api_keys_client_app_id "
    f'ON "{SCHEMA}".partner_api_keys (client_app_id)',
    # 5. external_ref unique per client app instead of per tenant
    f'DROP INDEX IF EXISTS "{SCHEMA}".uq_workspaces_tenant_external_ref',
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_client_app_external_ref "
    f'ON "{SCHEMA}".workspaces (client_app_id, external_ref) '
    "WHERE external_ref IS NOT NULL AND is_trashed = false",
]


def upgrade() -> None:
    op.execute(CREATE_TABLE)
    for statement in TABLE_INDEXES:
        op.execute(statement)
    for statement in MIRRORED:
        op.execute(statement)


def downgrade() -> None:
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".uq_workspaces_client_app_external_ref')
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_tenant_external_ref "
        f'ON "{SCHEMA}".workspaces (tenant_id, external_ref) '
        "WHERE external_ref IS NOT NULL AND is_trashed = false"
    )
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".ix_app_omnichannel_partner_api_keys_client_app_id')
    op.execute(f'DROP INDEX IF EXISTS "{SCHEMA}".ix_app_omnichannel_workspaces_client_app_id')
    op.execute(f'ALTER TABLE "{SCHEMA}".partner_api_keys DROP COLUMN IF EXISTS client_app_id')
    op.execute(f'ALTER TABLE "{SCHEMA}".workspaces DROP COLUMN IF EXISTS client_app_id')
    op.execute(f'DROP TABLE IF EXISTS "{SCHEMA}".client_apps')
