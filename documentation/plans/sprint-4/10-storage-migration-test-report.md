# Sprint 4 · Plan 10 - Storage Provider Migration + Centralized Background Jobs · Test Execution Report

**Feature branch:** `sprint-4/10-storage-migration` @ `e91a8aa` (all 3 slices built)
**Tester:** automated QA agent · **Date:** 2026-07-11
**Plan:** `10-storage-migration.md` · **UAC:** `10-storage-migration-acceptance-criteria.md`

## Environment / stack bringup
- Backend FastAPI on **:8001** (foundryx-shared-service; a squatting `dreamz_ems` uvicorn was killed off 8001 first). Seeded via `python -m scripts.init_db`, then **`alembic upgrade head`** (see Env Finding #1) - `ENVIRONMENT=development` so the demo inbox seed ran.
- Frontend Next on **:3001**, FRESH build (`rm -rf .next && npm run build && npm start`); a squatting `dreamz_ems` next-server was killed off 3001 first. Confirmed `:3001` cwd = `service_frontend`.
- Offline-deterministic storage: a local **moto** S3 server on `:5050` (`python -m moto.server`) with pre-created buckets `mig-source` / `mig-target` stands in for a real bucket, so a genuine A→B copy + cutover runs and presigned reads resolve - no cloud creds, no network. The failing-probe path uses a CLOSED port (`localhost:9`) like `integrations.spec.ts`.
- `auth_throttle` cleared between runs (local shared 127.0.0.1 bucket).

## Suite results (regression gate)
| Suite | Command | Result |
|---|---|---|
| Backend | `python -m pytest -q` | **1042 passed**, 181 warnings, 638s |
| Backend (feature subset) | `pytest tests/test_background_jobs.py tests/test_storage_migration.py tests/test_storage_migration_registry.py tests/test_cluster_d_slice3_migration.py -q` | **42 passed** |
| Frontend unit | `npx vitest run` | **725 passed** (92 files) |
| E2E (this plan) | `npx playwright test storage-migration.spec.ts --workers=1` (MOTO_ENDPOINT set) | **3 passed** |

Status-engine + tenant-lifecycle suites are inside the 1042 and stayed green.
Revision-id lengths (DoD gate, ≤32 chars): `bgjobs_1a2b3c4d5e6f`(19), `conn_is_active_s410`(19), `migrate_storage_perm410`(23) - all pass.

---

## E2E scenarios (real clicks, live stack)

Spec: `service_frontend/e2e/storage-migration.spec.ts` (completed from the coder's `test.fixme` stub). Every tenant is dedicated + timestamped (`e2e-mig-<tag>-<Date.now()>`). Fixture: `service_frontend/e2e/fixtures/avatar.png` (committed 96×96 PNG - no committed image existed in the repo).

### Scenario 1 - Wizard: test-gated Start (AC-10-18) · **PASS**
- **User story:** As a tenant Admin I open "Migrate storage" from a storage connection and cannot start until the new bucket verifies.
- **Precondition:** dedicated tenant, signed in via the real login form; a storage connection A exists.
- **Steps:** Settings → Integrations → Connect S3 (A) → connection detail "…" Actions → **Migrate storage** → configure bucket B (endpoint = closed port `localhost:9`) → **Test bucket**.
- **Expected:** the "Migrate storage" action is visible (holds `integrations.migrate_storage`); on the Test step **Next stays disabled** before and after a FAILING probe; the honest transport error is shown; wizard usable at 375px (step strip "New bucket"/"Confirm" visible) and 1280px.
- **Actual:** exactly as expected - the action appeared, the probe failed with `Could not access bucket …`, **Next remained disabled**, step strip rendered at both widths.
- **Remarks:** foolproof-UI gate confirmed - a failing test never enables advancement.

### Scenario 2 - Jobs surfaces reachable (AC-10-19) · **PASS**
- **User story:** As a user I can reach my background jobs from the header drawer and the `/jobs` history list.
- **Precondition:** dedicated tenant, signed in.
- **Steps:** header **Jobs** activity trigger (icon button) → drawer opens; sidebar **Jobs** link → `/jobs`.
- **Expected:** generic type-aware "Jobs" drawer opens; `/jobs` Resource list shows **Type** + **Status** columns and N-way status **segments** (the "View segment" SearchSelect lists "Needs review"); usable at 375px + 1280px.
- **Actual:** drawer opened (title "Jobs"), `/jobs` rendered Type/Status columns, the segment SearchSelect exposed "Needs review"; columns visible at both widths.
- **Remarks:** the `/jobs/[id]` detail surface is asserted in Scenario 3.

### Scenario 3 - Full migration A→B → job done → assets resolve (AC-10-21 / AC-10-22, moto-backed) · **PASS**
- **User story:** As a tenant Admin I migrate my storage bucket and every existing asset keeps resolving; new uploads land on the new bucket.
- **Precondition:** dedicated tenant; moto S3 reachable at `:5050` with `mig-source`/`mig-target` (else the test SKIPS - never a false PASS).
- **Steps:** connect S3 A (`mig-source` @ moto) → upload an avatar on /account (lands on A) → assert it resolves (HTTP 200) → open **Migrate storage** on A → configure B (`mig-target` @ moto) → **Test bucket** (passes) → Next → typed-confirm the target name (Start enables only then) → **Start migration** → Jobs drawer shows "Storage migration" → open `/jobs/[id]`.
- **Expected:** the job reaches **Done** with **no failures**; the PRE-EXISTING avatar still resolves (now from B) - zero 404; a NEW post-migration upload also resolves (lands on B).
- **Actual:** all as expected - job **Done**, no "Failed assets" table, pre-existing avatar URL returned 200 after cutover, and a fresh post-migration upload returned 200.
- **Remarks:** this drove the real copy (`put_raw` path-preserving) + value-checked `conn:A:`→`conn:B:` rewrite + auto-cutover-on-clean end-to-end through the UI against a live S3 endpoint. Start is atomic (B created active, A retired) - proven by the write-target flip (new uploads → B).

Responsive mandate: verified in-spec at **375px AND 1280px** for the wizard (Scenario 1) and the `/jobs` list (Scenario 2); no horizontal scroll / clipped controls observed.

---

## Backend AC coverage (smoked via UI where drivable, else backend suite)

| AC | What | Evidence | Verdict |
|---|---|---|---|
| AC-10-01 | `background_jobs` table + ApiModel wire | `test_background_jobs.py` | **PASS** (T) |
| AC-10-02 | job-type handler registry + eager dispatch + atomic claim | `test_background_jobs.py` | **PASS** (T) |
| AC-10-03 | resumability + retention prune | `test_background_jobs.py` | **PASS** (T) |
| AC-10-04 | `put_raw` path-preserving on every adapter | `test_storage_migration.py`; exercised live in Scenario 3 | **PASS** |
| AC-10-05 | StorageKeyLocation scalar registry + value-checked rewrite | `test_storage_migration_registry.py` | **PASS** (T) |
| AC-10-06 | JSON-embedded rewrite (fresh-dict reassign) | `test_storage_migration_registry.py` | **PASS** (T) |
| AC-10-07 | drift test: every `*_key` column registered | `test_storage_migration_registry.py` | **PASS** (T) |
| AC-10-08 | `connections.is_active` + relaxed unique index + resolve filter | migration applied + backfill verified; Scenario 3 (new uploads→B, old resolve by key) | **PASS** (see Env Finding #1) |
| AC-10-09 | start atomic (create-B + flip + retire-A) | Scenario 3 + `test_storage_migration.py` | **PASS** |
| AC-10-10 | copy: enumerate → path-preserve → idempotent → continue-on-bad | `test_storage_migration.py`; clean-copy path in Scenario 3 | **PASS** |
| AC-10-11 | batch rewrite only copied keys, value-checked | `test_storage_migration.py`; Scenario 3 rewrite | **PASS** |
| AC-10-12 | auto-cutover on clean; needs_review hold on failure | clean path in Scenario 3; failure/hold in `test_storage_migration.py` | **PASS** (needs_review UI Complete/Retry - see Deferred) |
| AC-10-13 | retire A leaves bucket physically intact (no destructive calls) | `test_storage_migration.py` (no-delete spy) | **PASS** (T) |
| AC-10-14 | one-active 409, connection lock, abort, retry | `test_storage_migration.py` | **PASS** (T) - not driven E2E (see Deferred) |
| AC-10-15 | tenant-own vs platform cross-tenant sweep | `test_storage_migration.py` | **PASS** (T) |
| AC-10-16 | `integrations.migrate_storage` perm + grant sweep for existing tenants | catalog has the key; pre-existing `default` tenant's Admin holds it (SQL-verified); action visible in Scenario 1 | **PASS** |
| AC-10-17 | frontend-first mock→real swap | `storage-migration-service.{mock,real}` present; `.real` posts `/storage/migrations(/test)`; E2E ran against the REAL backend | **PASS** |
| AC-10-18 | wizard test-gated Start | Scenario 1 | **PASS** |
| AC-10-19 | Jobs drawer + `/jobs` list + `/jobs/[id]` | Scenarios 2 + 3 | **PASS** |
| AC-10-20 | omnichannel `media_key` registration + legacy `media_url` backfill | `test_cluster_d_slice3_migration.py` / registry | **PASS** (T) - not driven E2E (no legacy media on a fresh tenant) |
| AC-10-21 | assets never break across the migration | Scenario 3 (200 before + after + new upload) | **PASS** |
| AC-10-22 | E2E real-click journey, dedicated tenant | Scenario 3 | **PASS** |

---

## Environment findings (NOT product bugs - for the deployer)

**Env Finding #1 - `connections.is_active` absent after `init_db` (create_all).**
On first bringup, `POST /connections` 500'd with `column connections.is_active does not exist`, and the connect form never navigated (both the new spec AND the pre-existing `integrations.spec.ts` create test failed identically - so it was environmental, not a spec bug). Root cause: the live Postgres `connections` table pre-existed from an earlier seed, and `scripts.init_db` uses `create_all`, which **creates missing tables but never adds a column to an existing table** - so the Slice-2 migration `conn_is_active_s410` (add column + explicit backfill + relaxed indexes) was never applied. This is the documented `create_all` limitation (CLAUDE.md: "conftest uses create_all, so a broken/absent migration passes the suite yet breaks a real reset"). **Fix applied:** `alembic stamp bgjobs_1a2b3c4d5e6f` (the `background_jobs` table was already made by create_all) then `alembic upgrade head` - the migrations applied cleanly (column added + backfilled to `true` + grant sweep). The migration itself is CORRECT; a real deploy via `bootstrap_db` (which runs alembic) is unaffected. **Recommendation:** reset this feature's DB with `python -m scripts.bootstrap_db`, not `init_db`.

**Env Finding #2 - no committed image fixture.** `avatar.spec.ts` references `public/media/foundryx/foundryx-logo.png`, which does not exist on this branch (`public/media` is gitignored). The new E2E therefore ships its own committed fixture `e2e/fixtures/avatar.png`. (Aside: `avatar.spec.ts` would currently fail for the same missing-file reason - outside this plan's scope, worth a follow-up.)

## Deferred (offline / scope - explicitly not a false PASS)
- **AC-10-12 needs_review Complete/Retry via the UI** and **AC-10-14 abort/one-active-409/connection-lock via the UI** - the `/jobs/[id]` state-aware actions exist and the behaviors are covered by `test_storage_migration.py`, but were not driven through real clicks (they need an induced-failure or a concurrent-start harness). Deferred to unit coverage; UI action wiring visually present on the detail page.
- **AC-10-20 legacy `media_url`→`media_key` backfill** - verified at the backend-test level; not E2E-driven because a freshly-provisioned tenant has no legacy omnichannel media rows.
- **Real cloud (AWS/R2) round-trip** - intentionally not exercised; moto is the offline-deterministic stand-in (the plan's `integrations.spec.ts` precedent). The `S3CompatibleAdapter` code path is identical for moto and real S3.

## Verdict
All write-path ACs for Slices 1-3 are satisfied (E2E for the user-facing surfaces, backend suite for the engine internals). The one blocker encountered was an environment migration-application gap (Env Finding #1), fixed by running alembic; the feature works end-to-end with real data once the migration is applied. **No product bugs found.**
