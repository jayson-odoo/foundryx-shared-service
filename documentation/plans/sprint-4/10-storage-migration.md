# Sprint 4 · Plan 10 - Storage Provider Migration + Centralized Background Jobs

**Status:** GRILLED + LOCKED 2026-07-11. UAC: `10-storage-migration-acceptance-criteria.md` (write ACs pass = done).
**Closes:** BL-077 (asset re-upload migration on storage-connection switch). Folds in the tail of BL-078 (legacy omnichannel `media_url` → `media_key`).
**Depends on:** storage connection framework (sprint-2/06), `conn:<id>:` key model (sprint-2/06 D1), integration Resource shell (sprint-2/06), import-engine job pattern (sprint-3/09).

---

## 1. Problem

Storage blobs are keyed `conn:<connection_id>:<raw>` and reads route through the connection that WROTE them (sprint-2/06 D1) - switching connections never breaks *existing* assets, but there is **no supported way to actually move to a new bucket**. Editing the connection in place either strands every historical asset (new bucket, same connection id → blobs absent) or requires the tenant to abandon their data. Users need to change storage providers/buckets (cost, region, provider migration) and keep every avatar, document, form upload, branding asset, and chat-media resolvable.

This plan makes a bucket switch a **first-class, resumable, foolproof background operation**, and builds the generic machinery so (a) every future storage-key location and (b) every future async job type ride it for free.

## 2. Locked design decisions

**D1 - Migration model: transient A → B (grill Q1/Q5).** Not edit-in-place. Starting a migration atomically: create connection **B** (active), flip the tenant's storage **write-target** to B, mark **A `is_active=false`**. New uploads land on B (`conn:B:`) immediately; A is frozen for writes and only DRAINED. Reads route by each key's own id, so A-assets and B-assets both serve throughout. Cutover = batch-rewrite the copied `conn:A:` keys → `conn:B:`. A lingers as an inactive audit row.

**D2 - Copy PRESERVES the raw path via `put_raw` (grill Q16).** `save()` mints a fresh uuid → wrong for copy. New low-level `put_raw(raw, content, mime)` on every adapter writes at the EXACT key. Consequence: rewrite is a trivial prefix swap and resume needs no `{rawA→rawB}` map.

**D3 - Rewrite is value-checked (grill Q5).** `WHERE col LIKE 'conn:A:%'` only. A row re-pointed mid-run (avatar replaced → already `conn:B:`) is excluded → never clobbered.

**D4 - Continue-on-bad-blob (grill Q3).** A missing/corrupt source blob is recorded `failed` + skipped; the job never aborts. Failed keys are NOT rewritten and A is NOT retired for them → nothing silently stranded.

**D5 - Partial cutover on failure (grill Q3).** Rewrite only the successfully-copied keys. Failed keys keep `conn:A:` and keep serving from A. Cutover auto-runs when failures = 0; HOLDS at `needs_review` when ≥1 failure (explicit Complete/Retry).

**D6 - Centralized `background_jobs` table, new work only (grill Q4).** A generic `type`-dispatched job table + worker + ONE "Jobs" drawer. Storage migration = first `type`. Existing `import_jobs`/`document_download_jobs`/`workflow_runs`/`email_outbox` are LEFT UNTOUCHED (load-bearing, typed) - folding them in is backlogged.

**D7 - Writes → B at start; explicit write-target (grill Q5).** Two storage connections coexist during migration, so `resolve_for_type` can't stay "pick by type". An explicit write-target (a `is_active=true` filter - only B is active, A is inactive) disambiguates deterministically. Read-by-key ignores `is_active`.

**D8 - Orphans ignored in v1 (grill Q6).** Mid-run replace/delete leaves an already-copied `conn:A:` blob orphaned in B (never served). Harmless; log the count; scheduled GC backlogged.

**D9 - StorageKeyLocation registry: declarative + JSON callback + drift test (grill Q2/Q15).** Scalar `*_key` columns register declaratively; JSON-embedded keys (form answers, template docs) register a `rewrite_json` callback. A drift test hard-fails CI if a `*_key` column is unregistered. Modules register their own locations at install (omnichannel `media_key`).

**D10 - `is_active` on `connections` (grill Q11).** Column name aligns with the rest of the system. Retire = `is_active=false`; unique index relaxed to `WHERE type != 'payment' AND is_active`; `resolve_for_type` filters `is_active=true`; resolve-by-key ignores it. Bucket A contents NEVER touched by us (grill Q10).

**D11 - Both tenant-own AND platform connections (grill Q9/Q10).** Dedicated perm `integrations.migrate_storage` (tenant Admin). Enumeration is connection-scoped: tenant-own naturally stays single-tenant; the platform connection sweeps all fallback tenants. Same code path; scope derived from `connection.tenant_id == PLATFORM_TENANT_ID`. One key, one UI (the platform operator manages the platform connection through the platform tenant's own `/settings/integrations`; the platform double-lock is inherent).

## 3. Data model

### 3.1 `background_jobs` (core `public`, new)
```
id                PK str(uuid)
tenant_id         str, indexed
type              str, indexed           # 'storage_migration' (first)
status            str, indexed           # pending|running|needs_review|done|failed|aborted
actor_user_id     str, nullable
payload_json      JSON(none_as_null)     # type input, e.g. {fromConnectionId, toConnectionId}
result_json       JSON(none_as_null)     # type output, e.g. {copied, failed, orphaned, failures:[{key,reason}]}
cursor_json       JSON(none_as_null)     # resume point (enumerated key list + index)
progress_total    int default 0
progress_done     int default 0
progress_failed   int default 0
error             Text nullable
created_at/started_at/finished_at  UTCDateTime
```
Migration revision id **≤ 32 chars**. Response schema inherits `ApiModel` (Z-wire), camelCase aliases.

### 3.2 `connections` - add `is_active`
```
is_active  Boolean, default True
```
- Migration: add column + **backfill every existing row to `true`**.
- Replace the partial unique index: `unique WHERE type != 'payment' AND is_active`.
- `ConnectionRepository.resolve_for_type` gains `AND is_active` filter. `get_by_id` (key-resolve path) unchanged (ignores `is_active`).

### 3.3 omnichannel `conversation_messages` - no schema change
`media_key` already exists (plan 12). Legacy `media_url` rows are backfilled to `media_key` (data-only, D9/AC-10-20). Column `media_url` retained until backfill verified, then optional drop (separate).

## 4. Backend components

### 4.1 `app/jobs/` - centralized background jobs (new package)
- `models` → `background_jobs` (§3.1).
- `registry.py` → `register_job_handler(JobHandlerDef(type, handler, label))`, `handler_for(type)`. Loud on unknown type / duplicate registration (mirrors engine registries).
- `service.py` → `JobService`: `create(type, tenant_id, actor, payload)`, atomic status-claim `claim(job_id)`, `enqueue` (eager-inline vs Celery `.delay` on `celery_task_always_eager`), progress helpers.
- `worker.py` → Celery task `run_job(job_id)` → `claim` → `handler_for(job.type)(db, job)`; failure-isolated (mirrors workflow/import worker). Resume: handler reads `cursor_json`.
- `scheduler.py` hook → `prune_jobs` into the existing beat task (retention, failure-isolated).
- Router `app/api/v1/jobs.py` → `GET /jobs` (paginated, tenant-scoped, Resource-shell fetcher), `GET /jobs/{id}`, `POST /jobs/{id}/abort`, `POST /jobs/{id}/retry`, `POST /jobs/{id}/complete` (needs_review path). Auth `get_current_user`; the storage-migration ones additionally gated by the migration perm at the migration-start endpoint (below).

### 4.2 `app/storage_migration/` (new package) - the first job type
- `registry.py` → `StorageKeyLoc` + `register_storage_key_location(...)`:
  - scalar: `StorageKeyLoc(model, column, tenant_column)` → generic enumerate (`LIKE 'conn:A:%'`) + rewrite (`replace(...) WHERE LIKE`).
  - JSON: `StorageKeyLoc(model, json_column, tenant_column, rewrite_json=callback)` → prefilter `LIKE '%conn:A:%'`, callback walks + reassigns a **fresh dict**.
  - `enumerate_keys(db, connection_id) -> set[str]` (distinct blobs, all locations).
  - `rewrite_keys(db, from_id, to_id, only_keys) -> int` (value-checked, all locations).
- `core_locations.py` (`lazy_once`) registers core scalar columns: `users.avatar_key`, `tenant_branding.{logo,favicon,illustration}_key`, `import_jobs.{file_storage,error_report}_key`, `documents.storage_key`, `document_download_jobs.zip_storage_key`; JSON callbacks for `form_submissions.answers_json` + template docs (`templates`, `notification_specs.doc_json`, workflow `email.send config.doc`). Omnichannel registers `conversation_messages.media_key` at install.
- `drift_test` support: `all_key_columns()` reflection helper the test asserts ⊆ registered.
- `service.py` → `StorageMigrationService`:
  - `start(db, tenant_id, actor, new_config, new_credentials)`:
    1. validate no active migration for the connection (else 409);
    2. **test B** config (adapter `test()` - head_bucket + round-trip); refuse if fails;
    3. atomic txn: create B (active), set A `is_active=false`, create `background_jobs` row;
    4. enqueue.
  - `run(db, job)` (registered handler): enumerate A-keys → set `progress_total` + `cursor_json` → copy loop (`fetch(rawA)` from A adapter → `put_raw(rawA, ...)` on B adapter; skip if exists in B; bad blob → record failure, continue; advance cursor); on finish → if `failed==0` auto-`_cutover` else set `needs_review`.
  - `_cutover(db, job)`: `rewrite_keys(from=A, to=B, only_keys=copied)`; job `done`. (A already inactive.)
  - `abort(db, job)`: stop, no rewrite, keep B, restore A active as write-target (set A `is_active=true`, B `is_active=false`? - see write-target note), job `aborted`.
  - `retry(db, job)`: re-run copy over remaining/failed, then cutover when clean.
  - `complete(db, job)`: from `needs_review` - rewrite copied keys, accept failures list, job `done`.
- Enforcement: `start` endpoint gated `require_permission("integrations.migrate_storage")` + connection-ownership check (own connection, or platform connection when caller is platform tenant).

**Write-target note.** Because "active storage connection" = the single `is_active=true` storage row, the write-target flip IS the `is_active` flip (start: A→false, B→true; abort: A→true, B→false). `_write_connection()` already calls `resolve_for_type` which now filters `is_active` - so it picks B during migration with no extra pointer column. This unifies D7 + D10 into one mechanism.

### 4.3 Adapters - `put_raw`
- `StorageService` Protocol gains `put_raw(raw: str, content: bytes, mime: str) -> None`.
- `LocalDiskStorage.put_raw` → write bytes at `root / raw` (mkdir parents).
- `S3CompatibleAdapter.put_raw` → `put_object(Key=raw, ...)` (no uuid mint).
- `TenantStorage` does not expose `put_raw` at the tenant level - the migration operates on the raw A/B adapters directly (via `_adapter_for(connection)`), not through key-prefixing.

### 4.4 Permissions + grant sweep
- Add `integrations,Integrations,migrate_storage,Migrate storage,Migrate assets to a new storage bucket` to `app/permissions/permissions.csv` (grep core first - no collision).
- `tenant_admin_grant` picks it up for new tenants. **Grant sweep migration** for existing tenants (re-run grant / insert into existing Admin `role_permissions`).

### 4.5 omnichannel legacy backfill
- One-time data migration/bootstrap step: for each `conversation_messages` with `media_url` set + `media_key` null → fetch bytes (local disk path or HTTP for CDN URL) → `save()` through current storage → set `media_key`, clear `media_url`. Idempotent, capped/batched. Failure-isolated per row (log + skip).

## 5. Frontend

- `services/storage-migration-service.{ts,mock,real}` + `services/jobs-service.{ts,mock,real}`.
- `hooks/use-storage-migration.ts`, `hooks/use-jobs.ts`.
- **Migrate wizard** (`components/platform/storage-migration-wizard/`): reuse the `fields()`-driven connection form for step 1; step 2 Test (Start disabled until pass); step 3 typed-confirm with blob count/size. Entry = a `Migrate storage` action in the storage connection detail `…` action registry, gated `integrations.migrate_storage`.
- **Jobs drawer** (`components/platform/jobs-drawer/`): generic `type`-aware activity drawer, header trigger (sibling of Uploads/Downloads/Imports). Progress bar from `progress_*`.
- `/jobs` Resource list (Type column) + `/jobs/[id]` detail (result/failures). Sidebar entry under Settings or a top-level Jobs (gated: any job read).
- Responsive verified 375px + 1280px.
- Frontend-first: build + verify on the mock (copying/failed/done/needs_review), THEN swap to real.

## 6. Slicing

1. **Slice 1** - `background_jobs` infra (table, registry, service, worker, dispatch, retention) + `put_raw` on adapters + StorageKeyLocation registry (core locations) + drift test. AC-10-01..07.
2. **Slice 2** - migration engine (start/copy/rewrite/cutover/retire/abort/retry) + `is_active` column & relaxed index & resolve filter + perm + grant sweep + tenant/platform scope. AC-10-08..16.
3. **Slice 3** - frontend (wizard + Jobs drawer + job pages, mock→real) + omnichannel `media_key` registration & legacy `media_url` backfill + E2E. AC-10-17..22.

## 7. Tests (TDD, both layers)

- **pytest:** registry enumerate/rewrite (scalar + JSON fresh-dict), drift test, `put_raw` path preservation, copy idempotent/resume, continue-on-bad-blob, value-checked rewrite skips re-pointed rows, `is_active` resolve filter vs key-resolve, start atomic (create-B + flip + retire-A), auto-cutover-on-clean, needs_review hold, abort safe-partial, retry idempotent, one-active 409, tenant-own vs platform cross-tenant sweep, three backfills (`is_active`, legacy media, grant). Keep status-engine + tenant-lifecycle suites green.
- **vitest:** wizard test-gated Start, Jobs drawer render, service mock→real, migration service states.
- **E2E** (`e2e/storage-migration.spec.ts`, dedicated tenant, offline-deterministic adapter like `integrations.spec.ts`): connect → Migrate wizard → test B → start → job done in Jobs drawer → pre-existing asset still resolves + new upload on B. Real clicks only.

## 8. Backlog (log in `documentation/backlogs/backlog.md`)

- **BL-125:** Move existing job tables onto `background_jobs` (`import_jobs`, `document_download_jobs`, `workflow_runs`, `email_outbox`; fold their drawers into the Jobs drawer). Medium.
- **BL-126:** Scheduled orphan-GC sweep of bucket B (reclaim mid-run replace/delete orphans; guarded diff of B contents vs live `conn:B:` keys). Low.
- **BL-127:** Drop `media_url` column after legacy backfill verified in prod. Low.

## 9. Definition-of-Done gate
1. Mock swapped to real + verified with REAL data (AC-10-17).
2. Backfills shipped (not seed-if-absent): `is_active`→true, legacy `media_url`→`media_key`, Admin grant sweep.
3. `integrations.migrate_storage` reaches existing tenants' Admin.
4. Drift test green; backend + frontend suites green; status-engine + tenant-lifecycle untouched.
5. Verified E2E at 375px + 1280px on a freshly rebuilt frontend (`rm -rf .next && npm run build`), correctly-owned ports (3001 FE, 8001 BE).
6. CLAUDE.md lesson added: centralized `background_jobs` pattern + `conn:<id>:` rewrite / `put_raw` migration mechanics.
```
