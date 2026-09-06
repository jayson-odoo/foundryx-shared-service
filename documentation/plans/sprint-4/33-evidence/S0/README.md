# Plan 33 S0 - agent-browser evidence run

Lane: `.claude/worktrees/s33`, backend `:8012` (DB `foundryx_service_s33`), frontend `:3010`
(`npx next start -p 3010`), `agent-browser --session s33c`. Logged in as `demo@example.com` /
`demo1234` (tenant `default`), real clicks from `/`, never a typed URL (except the initial
`open http://localhost:3010` which is the login page itself and the 375px re-open of `/` to
reach the mobile mega-menu - every subsequent navigation is a click).

## Hand-inserted rows (documented per the coder brief; S1 must add these properly)

The `omnichannel_migration.read`/`.manage` permission CSV rows and the `respondio` provider
registration do not exist yet (S1 scope). To make the menu entry render and to exercise the
Source picker with at least one option, two rows were hand-inserted into the LANE database only:

```sql
-- 1. Permission rows + grant to the demo tenant's Admin role (S1 replaces this with the
--    real modules/omnichannel/permissions/permissions.csv rows + sync_permissions).
INSERT INTO permissions (id, key, module, resource, resource_label, action, action_label, description)
VALUES
  (gen_random_uuid()::text, 'omnichannel_migration.read', 'omnichannel', 'omnichannel_migration', 'Data Migration', 'read', 'Read', 'View respond.io migration jobs and their reports (plan 33 S0 hand-insert).'),
  (gen_random_uuid()::text, 'omnichannel_migration.manage', 'omnichannel', 'omnichannel_migration', 'Data Migration', 'manage', 'Manage', 'Run respond.io migration dry runs and migrations (plan 33 S0 hand-insert).')
ON CONFLICT (key) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id, tenant_id)
SELECT '5a354802-5271-4387-b5f6-46bbbf858468', p.id, '00000000-0000-0000-0000-000000000001'
FROM permissions p
WHERE p.key IN ('omnichannel_migration.read', 'omnichannel_migration.manage')
ON CONFLICT DO NOTHING;

-- 2. One fake respond.io connection row so the Source picker has an option (S1 registers the
--    real `respondio` IntegrationProvider via bootstrap.register_providers; until then
--    `IntegrationService._registered_providers()` correctly excludes an unregistered provider
--    key from the list, which is why this row alone was NOT enough - see "What S1 must know").
INSERT INTO connections (id, tenant_id, provider, type, name, config_json, credentials_json, status, is_active, rate_limit_per_minute, created_at, updated_at)
VALUES ('conn-rio-smoke-1', '00000000-0000-0000-0000-000000000001', 'respondio', 'migration',
        'Acme respond.io space',
        '{"baseUrl":"https://api.respond.io/v2","spaceLabel":"Acme Support","timezone":"Asia/Kuala_Lumpur","requestsPerSecond":"4"}',
        '', 'UNVERIFIED', true, 60, now(), now());
```

Neither row is committed to the repo; both live only in the `foundryx_service_s33` Postgres
database and can be dropped once S1 lands its own provider registration + CSV grant sweep.

## What was verified (real clicks, both viewports)

1. **Menu gating (AC-MIG-01).** Sidebar (1280px) and mobile mega-menu (375px, "Open
   navigation" -> Omnichannel -> scrolled to Migration) both show the entry only now that the
   permission rows exist; `filterMenu` prunes it correctly (verified the entry is absent before
   the SQL insert, present after).
2. **List (AC-MIG-02).** `01-list-1280.png` - all six seeded `MigrationJobStatus` values render
   with the right `StatusBadge` tone (Running/blue, Done/green, Needs review/amber,
   Failed/red, Aborted/gray), the exact column set (Source, Target workspace, Mode, Status,
   Progress, Contacts, Messages, Failures, Started, Finished), server-side "All" segment
   control. `05-list-375.png` - same list, non-clipped at 375px (columns scroll horizontally,
   the DataGrid's own existing behavior).
3. **Detail (AC-MIG-08).** `02-detail-running-1280.png` (a `running` job: Progress bar +
   `96/1840 processed, 1 failed`, Details card, `Actions` menu opened to confirm ONLY "Abort" is
   offered while in flight - screenshot not kept for the open-menu state, verified via
   `snapshot -i` -> `menuitem "Abort"` with no Retry/Complete). `06-detail-needs-review-375.png`
   (a `needs_review` job at 375px: Progress, Details, the Counts-report `DataGrid` with the
   Blocker pill, the Failures `DataGrid` + Download CSV button, all non-clipped).
4. **Setup form (AC-MIG-03/04/06/07).** `03-new-form-1280.png` / `04-new-form-375.png` - ordered
   Source/Target/Scope/Review sections (Channels/People/Lifecycle correctly ABSENT until a
   connection AND workspace are both chosen - verified live: picking the real "General"
   workspace alone, with Source still empty, leaves those three sections hidden and throws no
   console error). "Run dry run" and "Start migration" both start `disabled` (confirmed via
   `disabled` in the accessibility snapshot, not just visual shade). The Target workspace
   picker resolves REAL tenant workspaces (`workspace-service`, already-real per plan design);
   the Source (respond.io connection) picker correctly shows ZERO options - see below.
5. **Console.** Only a pre-existing generic Radix `DialogContent` a11y warning appeared
   throughout the run (present before this slice's changes too); no errors.

## What S1 must know

- **The Source picker stayed empty even with the hand-inserted connection row present.**
  `IntegrationService._registered_providers()` (core, `app/services/integration_service.py`)
  restricts `GET /integrations/connections` to the provider keys the Integrations surface
  KNOWS about (`app/integrations/registry.py` or wherever `register_providers` populates it) -
  an unregistered `provider='respondio'` row is correctly excluded, exactly as designed (the
  same guard that keeps the embed `omnichannel_shared` connection from being destroyed by a
  stray Disconnect). This is NOT a bug: it means the full mapping/dry-run/start flow cannot be
  exercised live until S1 calls `bootstrap.register_providers` for `respondio`. Once that
  lands, re-run this same smoke script from "pick the connection" onward - the picker will
  show real options and the rest of the setup form (Channels/People/Lifecycle sections,
  preflight fetch, dry run, Start migration) can be verified end-to-end for the first time
  against a live backend (still the S0 mock service today; S6 swaps it to real).
- **`bootstrap_db`'s `ensure_role_and_db()` hardcodes `APP_DB = "foundryx_service"`** - it never
  creates a lane-specific database from `DATABASE_URL`. Every future lane must `createdb`/
  `ALTER DATABASE ... OWNER TO foundryx` by hand BEFORE running `bootstrap_db` (this bit this
  lane too - worth a one-line fix in `scripts/bootstrap_db.py` to read `APP_DB` from the
  connection string, filed as a process note, not part of this slice's scope).
- Two decisions were taken where the plan's §5.2 contract was silent (both documented inline
  in `types/respondio-migration.ts`): `MigrationPreflight.lifecycles: string[]` (source
  lifecycle labels for the Lifecycle section - the plan's preflight calls never touch a
  contact) and `MigrationJob.entityCounts`/`failureSample` (live per-entity counts + a capped
  failure sample riding the SAME `GET .../jobs/{jobId}`, distinct from the final `report` and
  the full CSV). S1's real preflight/job-read implementations need to fill these fields.
