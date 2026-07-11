# Sprint 4 · Plan 10 — Storage Provider Migration + Centralized Background Jobs · Acceptance Criteria

**Source plan:** `10-storage-migration.md` (GRILLED + LOCKED 2026-07-11)
**Scope:** let a tenant (and the platform operator) switch their storage connection to a new bucket and **migrate all existing assets** to it, with zero downtime for asset serving. Built on a NEW, reusable **centralized `background_jobs`** table + worker dispatch (storage migration = its first `type`), and a generic **StorageKeyLocation registry** so every current and future storage-key location is covered automatically. Closes **BL-077** (asset re-upload migration) and folds in the tail of **BL-078** (legacy omnichannel `media_url` → `media_key`).

Format: each AC is independently verifiable (Given / When / Then). Grouped by slice. `[BE]` backend · `[FE]` frontend · `[E2E]` real-click · `[T]` unit/integration test. The Test Execution Report keys back PASS/FAIL/DEFERRED per AC id.

> **The problem this solves:** storage blobs are keyed `conn:<connection_id>:<raw>` and reads route through the connection that WROTE the blob (plan sprint-2/06 D1). So a tenant who edits their storage connection to a new bucket strands every historical asset (or 404s them all if the connection id is reused). There has been **no supported way to change buckets**. This plan makes it a first-class, resumable, foolproof operation — and the machinery is generic so the next storage-key location and the next async job type both ride it for free.

> **Migration model (locked — grill Q1/Q5):** transient **old connection A → new connection B**. Starting a migration atomically (a) creates B, (b) flips the tenant's storage **write-target** to B, and (c) marks A `is_active=false`. New uploads land on B immediately; A is frozen for writes and only DRAINED (its snapshot copied). Reads always route by each key's own connection id, so old assets (A) and new assets (B) both serve throughout. Cutover = **batch-rewrite** the successfully-copied `conn:A:` keys → `conn:B:`. A lingers as an inactive row (audit + serves any un-migrated straggler); its bucket contents are never touched by us.

> **Key architectural facts (locked):**
> - **Copy PRESERVES the raw path** via a new adapter `put_raw(raw, content, mime)` (grill Q16) — `save()` mints a fresh uuid and must NOT be used for copy. Path-preserving copy makes rewrite a trivial prefix swap `conn:A:`→`conn:B:` and makes resume mapless.
> - **Rewrite is value-checked** (`WHERE col LIKE 'conn:A:%'`) so a row re-pointed mid-run (user replaced their avatar → already `conn:B:`) is never clobbered (grill Q5).
> - **Enumeration is connection-scoped, not tenant-scoped** — a tenant-own connection's keys live only in that tenant's rows; the platform connection's keys span every fallback tenant. One rule serves both (grill Q9/Q10).
> - **Continue-on-bad-blob** — a missing/corrupt source blob is recorded `failed` and skipped; the job never aborts. A is NOT retired / keys NOT rewritten for failed blobs (grill Q3).

---

## Slice 1 — Centralized `background_jobs` infra + `put_raw` + StorageKeyLocation registry

### AC-10-01 — `background_jobs` table [BE][T]
- **Given** the core Alembic migration ran (revision id **≤ 32 chars**), **when** inspecting the schema, **then** a `background_jobs` table exists with: `id`, `tenant_id` (indexed), `type` (indexed), `status` (indexed), `actor_user_id`, `payload_json`, `result_json`, `cursor_json` (all `JSON(none_as_null=True)`), `progress_total`, `progress_done`, `progress_failed` (int, default 0), `error` (Text), `created_at`, `started_at`, `finished_at` (`UTCDateTime`).
- **Given** a datetime-bearing response schema for a job, **then** it inherits `ApiModel` (Z-suffixed wire) and exposes camelCase.

### AC-10-02 — job-type handler registry + dispatch [BE][T]
- **Given** `register_job_handler(JobHandlerDef(type, handler, label))` at boot, **when** a job row of that `type` is processed, **then** the registered `handler(db, job)` runs; an unknown `type` is a loud error, never a silent no-op.
- **Given** `settings.celery_task_always_eager` (dev/E2E/tests), **when** a job is enqueued, **then** it runs INLINE on the request session (mirrors import/workflow engines); prod uses the real Celery worker.
- **Given** two attempts to process the same job row, **then** an **atomic status-claim** admits exactly one (the import-engine double-commit guard) — no double execution.

### AC-10-03 — resumability + retention [BE][T]
- **Given** a job with `status=running` and a persisted `cursor_json`, **when** the worker restarts and re-picks it, **then** it RESUMES from the cursor (no work redone, no corruption).
- **Given** finished jobs older than the retention window, **when** the pruner runs (wired into the beat task, failure-isolated), **then** they are deleted; running/pending jobs are never pruned.

### AC-10-04 — `put_raw` path-preserving write on every adapter [BE][T]
- **Given** `S3CompatibleAdapter.put_raw(raw, content, mime)` and `LocalDiskStorage.put_raw(...)`, **when** called, **then** the blob is written at the EXACT `raw` key (no uuid re-mint) and a subsequent `fetch(raw)` / `resolve(raw)` returns those bytes.
- **Given** `put_raw` is part of the `StorageService` protocol, **then** both adapters satisfy it (a Protocol/typing test asserts presence).

### AC-10-05 — StorageKeyLocation registry (declarative scalar columns) [BE][T]
- **Given** `register_storage_key_location(StorageKeyLoc(model, column, tenant_column))` for each scalar `*_key` column (`users.avatar_key`, `tenant_branding.{logo,favicon,illustration}_key`, `import_jobs.{file_storage,error_report}_key`, `documents.storage_key` + zip, omnichannel `conversation_messages.media_key`, …), **when** the migration enumerates keys for connection A, **then** it finds every `conn:A:%` occurrence across all registered scalar columns.
- **Given** a batch rewrite for a scalar column, **when** it runs, **then** it executes `SET col = replace(col,'conn:A:','conn:B:') WHERE col LIKE 'conn:A:%'` (value-checked) and reports the affected count.

### AC-10-06 — StorageKeyLocation registry (JSON-embedded callback) [BE][T]
- **Given** a JSON-embedded location (`form_submissions.answers_json`, template block-docs in `templates` / `notification_specs.doc_json` / workflow `email.send config.doc`), **when** registered with a `rewrite_json` callback `(db, from_id, to_id, tenant_scope) -> count`, **then** enumeration prefilters rows whose serialized JSON contains `conn:A:` and the callback walks + rewrites the nested keys in-Python.
- **Given** a JSON rewrite, **then** the callback **reassigns a fresh dict** to the column (`json.loads(json.dumps(...))`) — never an in-place mutation of the same object (the documented SQLAlchemy JSON tracking gotcha), verified by a test that asserts the change persists after commit.

### AC-10-07 — drift test: every `*_key` column is registered [T]
- **Given** the model metadata, **when** the drift test runs, **then** it FAILS (hard CI gate) if any SQLAlchemy column matching `*_key`/known-storage-key shape has no `StorageKeyLocation` registration (mirrors the importable-columns ⊆ writable-whitelist drift test). A new storage-key location that forgets to register breaks the build, not a silent future migration.

---

## Slice 2 — Storage migration engine (copy · rewrite · cutover · job control)

### AC-10-08 — `is_active` on `connections` + relaxed unique index [BE][T]
- **Given** the migration ran, **then** `connections` has an `is_active` boolean (default `true`); **every pre-existing row is backfilled to `true`** (not merely default-on-insert).
- **Given** the partial unique index, **then** it is `unique WHERE type != 'payment' AND is_active` — an inactive storage row + an active storage row for the same tenant coexist WITHOUT violating it.
- **Given** `resolve_for_type(tenant, 'storage')`, **then** it returns only an `is_active=true` connection; **given** `resolve` by a `conn:<id>:` KEY, **then** it resolves the connection by id **regardless of `is_active`** (a retired A still serves its blobs).

### AC-10-09 — start migration: atomic create-B + flip-write-target + retire-A [BE][T]
- **Given** an active storage connection A and a valid, tested new-bucket config, **when** a migration starts, **then** in ONE transaction: connection B is created (active), the tenant's storage **write-target becomes B**, and **A is set `is_active=false`**; a `background_jobs` row (`type='storage_migration'`, `payload={fromConnectionId:A, toConnectionId:B}`) is created.
- **Given** the write-target is resolved at the write-selection point (`_write_connection`) reading fresh state, **then** a new `save()`/`put()` after start writes to B (`conn:B:`), never A.

### AC-10-10 — copy: enumerate → path-preserving → idempotent → continue-on-bad [BE][T]
- **Given** a started migration, **when** the copy runs, **then** it enumerates the DISTINCT `conn:A:<raw>` blobs (from all registered locations), sets `progress_total`, and copies each via `put_raw` at the SAME `raw` into B.
- **Given** a blob already present in B (re-run/resume), **then** it is SKIPPED (idempotent), `progress_done` advances.
- **Given** a source blob missing/unreadable in A, **then** it is recorded in `result_json.failures` with a reason, `progress_failed` advances, and the copy **continues** (never aborts the job).

### AC-10-11 — batch rewrite = only successfully-copied keys, value-checked [BE][T]
- **Given** copy finished with some failures, **when** the rewrite runs, **then** it rewrites `conn:A:`→`conn:B:` **only for keys whose blob copied successfully**; failed keys keep `conn:A:` and keep serving from A.
- **Given** a row re-pointed to B mid-run (now `conn:B:`), **then** the value-checked rewrite (`LIKE 'conn:A:%'`) leaves it untouched (no clobber).

### AC-10-12 — cutover: auto-on-clean, manual-hold-on-failure [BE][FE][T]
- **Given** copy completed with **zero failures**, **then** the engine AUTO-cutovers: batch-rewrite all keys → mark job `done` (A already inactive from start).
- **Given** copy completed with **≥1 failure**, **then** the job HOLDS at a `needs_review` status; assets still serve (A active-by-key / B); the user must explicitly **Complete** (accept dropping/keeping failures) or **Retry** — never a silent partial cutover, never silent stranding.

### AC-10-13 — retire A leaves the bucket physically intact [BE][T]
- **Given** a completed migration, **then** A is `is_active=false` (kept for audit + straggler serving); **no delete/purge call is ever issued against bucket A's contents** (a test asserts the copy/cutover path makes zero destructive calls on the source adapter).

### AC-10-14 — job control: one-active, locked connection, abort, retry [BE][FE][T]
- **Given** an active `storage_migration` for a connection, **when** a second start is attempted for the same connection, **then** **409** (one active per connection).
- **Given** a running migration, **then** connections A and B cannot be edited/deleted/disconnected (guarded 409 in the connection service).
- **Given** a running migration, **when** the user **aborts**, **then** copy stops, NO keys are rewritten, B is KEPT (its new uploads are live data), A is restored as the active write-target, and the job is `aborted` (safe partial — assets keep serving).
- **Given** a `failed`/`needs_review` migration, **when** the user **retries**, **then** the copy re-runs idempotently over remaining/failed blobs, then cutover applies when clean.

### AC-10-15 — tenant-own scope vs platform cross-tenant sweep [BE][T]
- **Given** a tenant-own storage connection A, **when** enumeration/rewrite runs, **then** only that tenant's rows carry `conn:A:` keys and are swept (isolation is natural, no cross-tenant leak).
- **Given** the PLATFORM storage connection (`connection.tenant_id == PLATFORM_TENANT_ID`), **when** migration runs, **then** enumeration/rewrite sweeps `conn:A:` keys across **ALL tenants** that fell back to platform storage, and flipping the platform write-target to B routes every fallback tenant's new uploads to B; tenants with their own connection are untouched.

### AC-10-16 — permission `integrations.migrate_storage` + grant sweep [BE][T]
- **Given** the core permissions CSV, **then** `integrations.migrate_storage` exists (grep-checked for no collision with existing keys) and is granted to the tenant Admin role.
- **Given** tenants provisioned BEFORE this plan, **then** a **grant sweep** (migration or `tenant_admin_grant` re-run) adds the new key to their Admin roles — the action is not silently 403/invisible for existing tenants.
- **Given** the platform storage connection, **then** migrating it is only reachable by the platform tenant (which holds that connection row) with the same key — the platform double-lock is inherent.

---

## Slice 3 — Frontend (wizard · Jobs drawer) + omnichannel legacy backfill + E2E

### AC-10-17 — frontend-first: mock service before real wiring [FE][T]
- **Given** the frontend phase, **then** `storage-migration-service.{ts,mock,real}` exists; the wizard + Jobs drawer are built + verified against the **mock** (tunable copying/failed/done/needs_review states) BEFORE the real backend is wired; the mock→real swap is a one-line change at the service boundary. (No mock reaches the final QA pass — DoD gate.)

### AC-10-18 — Migrate wizard, test-gated Start [FE][E2E]
- **Given** the storage connection detail page, **when** the user opens the `…` menu, **then** a **"Migrate storage"** action appears only with `integrations.migrate_storage`.
- **Given** the wizard, **then** step 1 collects the new-bucket config via the SAME `fields()`-driven form as the connect wizard; step 2 runs a live connection **Test** (`head_bucket` + round-trip probe) and **Start is disabled until the test passes** (foolproof-UI); step 3 is a typed-confirm showing blob count + total size.
- **Given** a failing test, **then** Start never enables and the failure reason is shown.

### AC-10-19 — generalized "Jobs" drawer + job list + detail [FE][E2E]
- **Given** the header, **then** a **"Jobs"** activity drawer (generic, `type`-aware — NOT migration-specific) shows background jobs with type + status + progress (total/done/failed).
- **Given** `/jobs`, **then** a full history list (Resource shell) with a **Type** column; `/jobs/[id]` shows detail + `result_json.failures` for a migration.
- **Given** a running migration, **then** progress updates are visible in the drawer; on completion the storefront reflects B as the sole active storage connection.
- Responsive: drawer + pages usable at ~375px AND ~1280px (no horizontal scroll).

### AC-10-20 — omnichannel `media_key` registration + legacy `media_url` backfill [BE][T]
- **Given** omnichannel installed, **then** it registers its `conversation_messages.media_key` StorageKeyLocation at install (module `register_engine_entities`), so its media rides the generic migration automatically.
- **Given** legacy pre-plan-12 `media_url` rows, **when** the one-time backfill runs, **then** each is converted to a `media_key` (fetch old URL/disk bytes → `save()` → set `media_key`, clear `media_url`); after it, no `media_url`-only rows remain and ALL omnichannel media is key-based.
- **Given** a migration on a connection referenced by omnichannel media, **then** those `media_key` blobs copy + rewrite like any other location (no special-casing).

### AC-10-21 — assets never break across the migration [BE][E2E]
- **Given** existing assets on A and a migration in progress (pre-cutover), **when** they are requested, **then** they resolve from A (unchanged keys) — zero 404s.
- **Given** a completed clean migration, **when** the same assets are requested, **then** they resolve from B (rewritten keys); a NEW upload made during the migration resolves from B; the sum of copied blobs in B ⊇ the referenced key set.

### AC-10-22 — E2E real-click journey (dedicated tenant) [E2E]
- **Given** a **dedicated** provisioned tenant (spec-isolation rule — migration mutates shared storage state), **when** the E2E drives: connect an offline-deterministic storage connection → open Migrate wizard → configure + test B → confirm + start → job completes in the Jobs drawer, **then** a previously-uploaded asset still resolves and a post-migration upload lands on B — all via real clicks (no URL shortcuts).

---

## Deferred to backlog (logged in the plan)
- **BL-###:** move `import_jobs` / `document_download_jobs` / `workflow_runs` / `email_outbox` onto the centralized `background_jobs` table (fold their drawers into the Jobs drawer).
- **BL-###:** scheduled orphan-GC sweep of bucket B (reclaim blobs orphaned by mid-run replace/delete — grill Q6).
- **CLAUDE.md lesson:** the centralized `background_jobs` pattern + the `conn:<id>:` key-rewrite / `put_raw` path-preserving migration mechanics.

## Definition-of-Done gate (must all pass before "done")
1. Mock swapped to real + verified with REAL data (AC-10-17).
2. Backfills shipped, not seed-if-absent: `is_active`→true (AC-10-08), legacy `media_url`→`media_key` (AC-10-20), Admin grant sweep for `integrations.migrate_storage` (AC-10-16).
3. `integrations.migrate_storage` reaches existing tenants' Admin (AC-10-16).
4. Drift test green (AC-10-07); backend + frontend suites green; status-engine + tenant-lifecycle suites untouched.
5. Verified end-to-end at 375px AND 1280px on a freshly REBUILT frontend against correctly-owned ports (3001 FE, 8001 BE).
