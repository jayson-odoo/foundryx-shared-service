# Omnichannel - deep reference

The narrative overview (manifest, dev-safe adapter, message pipeline, WABA
config/templates, public gateway, AI-workflow nodes) lives in the root
`CLAUDE.md` "First real module: `omnichannel`" section - read that first. This
file carries only the topic-specific notes that don't fit there.

## Contact data model (plan 25) - Deploy / upgrade

Plan 25 adds the per-workspace contact-fields registry, contact tags, and a
workspace-scoped lifecycle status machine on top of the existing `Contact`
row, plus four new module permission keys (`contacts.manage`,
`contact_fields.manage`, `contact_tags.manage`, and the pre-existing
`contacts.read`/`conversations.read` reuse). Module version bumps
`0.1.0 -> 0.2.0`.

- **An existing tenant that already installed omnichannel (ACTIVE, version
  `0.1.0`) needs an App Store *Update*** (`/app-store` or the operator
  console's Modules tab -> Update) to receive the new permission grants on
  its Admin role, the lifecycle status graph per workspace, and every
  existing contact stamped with its workspace's initial lifecycle stage.
  `update_tenant(db, tenant_id, from_version="0.1.0")` runs
  `lifecycle_service.backfill_tenant` - idempotent, safe to re-run.
- **A tenant with NO `tenant_modules` row at all** (pre-App-Store data,
  `tenant_has_data` backfill path) is stamped straight to the CURRENT
  manifest version (`0.2.0`) by the loader's install backfill, which means
  `update_tenant` never runs for it - `install_tenant` is the hook that
  fires instead, and it now calls `lifecycle_service.backfill_tenant`
  unconditionally before returning (review round 1, finding 17), so no
  separate manual step is required. If a workspace was somehow created by
  hand outside both hooks, run `modules.omnichannel.services.
  lifecycle_service.backfill_tenant(db, tenant_id)` directly to materialize
  its graph and stamp its contacts.
- The two new functional unique indexes (`uq_contact_fields_workspace_key`,
  `uq_contact_tags_workspace_name`) ship in module migration `0008` AND in
  `bootstrap.create_schema_and_tables` (the `create_all` path) - `alembic
  upgrade head` (module Alembic) or a fresh `bootstrap_modules()` call picks
  them up; `create_all` alone (a bare `init_db` on an existing DB) will NOT
  add them to a table that already exists.
