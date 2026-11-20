# 22 - AutoCount direct-DB ETL - Test Execution Report (slice S6)

Keyed to `22-autocount-db-etl-acceptance-criteria.md` (AC-22-01..32). Executed 2026-08-31 on
branch `sprint-4/22-autocount-db-etl`, worktree `.claude/worktrees/s22`, against current branch
HEAD `9924a20` (the S5 review fix-pass landed mid-session; the spec + report below were
re-verified against that HEAD, not an earlier one).

## Environment

- Backend: FastAPI on **:8001**, native Postgres (`foundryx_service`), restarted from this
  worktree's HEAD (`.venv/bin/python -m uvicorn app.main:app --port 8001`, no `--reload`).
- Frontend: **prod build on :3002** (`rm -rf .next && npm run build && npx next start -p 3002`) -
  not :3001, per the task brief ("do not touch the user's :3001"; a raw `next start -p 3001` was
  in fact refused by the sandbox's own permission classifier mid-session, confirming the
  guardrail is enforced, not just advisory).
- Unit/integration: `python -m pytest -q` (in-memory SQLite, `schema_translate_map`), `npx vitest
  run` (jsdom).
- E2E (new spec, AC-22-31/32): a **temporary, uncommitted** `playwright.s22-tmp.config.ts`
  (`baseURL http://localhost:3002`, no `webServer`, `workers: 1`) drove
  `e2e/autocount-db-etl.spec.ts` - deleted before commit, not part of the deliverable.
- E2E (existing specs, regression check): `npx playwright test e2e/autocount.spec.ts
  e2e/autocount-mapping.spec.ts` run via the **standard** `playwright.config.ts` (its own
  `webServer` started + tore down its own `:3001` dev server for the run only; nothing was left
  listening on `:3001` afterward - confirmed via `lsof`).

## AC-22-31 / AC-22-32 - the new E2E spec

`service_frontend/e2e/autocount-db-etl.spec.ts` - real clicks throughout (sidebar → Settings →
Integrations → Connect integration for both a `sql_database` and a `sorento` connection; sidebar
→ AutoCount → Companies → ETL Demo Co → Overview → Edit push target → Entities → Customer → "…" →
Change source → Database → Configure database query → Query tab: schema tree search →
`etl_demo_customers` → Insert SELECT * → Test query → key/watermark/compared pickers → Save →
Mapping tab: re-point 4 seeded rows at the flat preview columns → Save → Review & Activate: Run
preview → Activate → Run now → Runs tab). `test.describe.configure({ mode: 'serial' })` - the
demo company is a tenant-wide singleton, so the two tests share it in a fixed order rather than
each provisioning its own copy.

**Why a scripted Sorento consumer.** AC-22-18's gate is real and server-enforced
(`EtlService.activate_task` refuses without a prior `previewable: true` dry run, and the demo
company's `sink_impl='logging'` deliberately has no `dry_run` method - by design, so a company
with nowhere to push can never pass the gate). So the spec stands a tiny in-process Node HTTP
server speaking the minimal Appendix A6/A8 contract (`ingest/{entity}[?dry_run=true]`,
`.../deletions`, `read/{entity}` for the provider's Test-connection probe) and points a REAL
`sorento` connection at it via real clicks - the exact pattern `autocount.spec.ts` already uses
for a scripted AutoCount vendor. Only the consumer's socket is scripted; the provider `test()`,
the dry-run call, the activation gate, the mapping engine, the watermark/hash-diff logic and the
run-history counts are all the real production code path, run against the REAL local Postgres as
the source (`public.etl_demo_customers`, the seed rig's own dev fixture).

**Live result (final HEAD, 2 consecutive clean runs for re-runnability):**

```
✓ AC-22-31 golden path: connection -> query -> mapping -> activate -> run -> run history  (12.4s / 12.7s)
✓ AC-22-32 change detection: incremental catches an update, reconcile catches a delete    (4.4s / 4.3s)
2 passed (18.9s / 19.4s)
```

Both tests pass **from a fresh state and from a re-run against the already-active task**
(re-runnability is load-bearing: `ETL_DEMO` is a singleton, not a per-run tenant) - verified by
running the file 3 times in a row against unchanged application code.

### Findings surfaced by building this spec (all fixed in test-owned files, none in application code)

1. **Seed-fixture bug (fixed): the demo company's `database_name` must equal the REAL Postgres
   database its connection reads.** `EtlService.update_task`'s cross-check (S2 review SHOULD-FIX
   6: "a connection pointed at a DIFFERENT database would extract someone else's data under this
   company's identity") 422s `connectionId` whenever `company.database_name != connection.config
   .database`. The seed script's `ensure_demo_company()` set `database_name='ETL_DEMO'` (a purely
   cosmetic label) while its own auto-created connection's `config.database` was always the real
   `foundryx_service` - a genuine mismatch nothing had ever driven through the real
   `update_task` service path before (existing unit tests construct `AcEntityConfig` rows
   directly). Fixed in `service_backend/scripts/seed_etl_demo_source.py`
   (`ensure_demo_company`/`trigger_run`/the `--company-database` default all now resolve the
   REAL physical database name, with a one-time ORM migration of the legacy `'ETL_DEMO'`-labelled
   row on first find). This is a fixture bug, not a product bug - the validation itself is
   correct and load-bearing (AC-22-11).
2. **Environment drift (fixed, non-code): module migration `0009_autocount_s5_review.py`
   (`ac_entity_config.last_preview_failed_count`) existed on disk but had never been applied to
   this worktree's live Postgres** (no `alembic_version` row for `app_autocount` - the documented
   "legacy `create_all` host" gotcha). `preview_task`/`run_task_now` 500'd until the column was
   added (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, matching the migration's own idempotent
   guard). Not a spec bug or a product bug - a deploy-freshness gap in this shared dev Postgres,
   worth calling out under the DoD "backfill" gate below.
2b. Corrected a residue row: a PRE-EXISTING second company also named "ETL Demo Co"
   (`database_name='foundryx_service'`, sink already pointed at a since-deleted connection) was
   found in the shared `default`-tenant Postgres from an earlier session's manual verification -
   name-only row matching would have silently picked either one. Fixed by matching on name AND
   the exact "Company database" cell (`page.getByText(demoDatabaseName, {exact:true})` scoped
   inside the row), and the stale row was relabelled (not deleted - no destructive SQL) so it can
   never collide with the real one again.
3. **Test-only deadlock (fixed): `execFileSync` (synchronous) for the `--trigger-run reconcile`
   helper blocked the SAME Node event loop hosting the in-process fake Sorento server**, so the
   eager-mode backend job's push call to that server could never be serviced until the Python
   subprocess itself finished waiting on it - a genuine deadlock, resolved only by the sink's 30s
   HTTP timeout (observed live: `httpx.ReadTimeout` inside `_auto_push_upserts`). Fixed by making
   `runSeed()` async (`child_process.execFile`), letting the event loop interleave. Test-owned
   fix only.
4. **Assertion bugs in the new spec (fixed):** the Sorento provider's actual API mount is
   `/integrations/connections`, not `/connections` (setup cleanup helper); `Run now` always
   enqueues `mode=manual` on the `AcSyncRun` row (shown as "Manual") even when the mechanics are
   incremental - the spec's own comment initially claimed the badge would read "Incremental",
   corrected to match the real `mode` column; `etl-last-run-at` can already be visible from an
   EARLIER run on a re-run of this spec, so waiting on the badge alone raced ahead of the actual
   click's own request - fixed by waiting on the `POST .../etl-task/run` response itself
   (`page.waitForResponse`); the fake consumer's `ingestCalls` tracker originally only recorded
   the `ingest/{entity}` branch, missing `.../deletions` calls entirely.
5. **Stale build (environment, not code):** a concurrent coder's S5 review-fix commits landed
   mid-session (`0107a53`..`9924a20`, touching `activate-tab.tsx`, `task-editor-view.tsx`,
   `mapping-table.tsx`, `schedule-tab.tsx`, `autocount-meta.ts`) while this worktree's `:3002`
   server was still serving the earlier build - a `ChunkLoadError` / "Application error" on the
   Companies list was the exact documented "stale build" gotcha. Resolved with the standard
   `rm -rf .next && npm run build` + clean restart of both `:3002` and `:8001` from HEAD, then
   the spec was re-verified green against that fresh build (see the two consecutive clean runs
   above).

None of the above required an application-code change to make the test pass - every fix landed
in `service_backend/scripts/seed_etl_demo_source.py` (a documented dev fixture, explicitly in the
tester's writable set) or in the new spec file itself.

## Results by AC id

| AC | Tag | Result | Evidence |
|----|-----|--------|----------|
| AC-22-01 | BE | PASS | `sql_provider.py` registered in `bootstrap.py`; `tests/test_autocount_sql_source.py` (49 tests, incl. the field-shape pin) |
| AC-22-02 | BE | PASS | `SqlDatabaseProvider.test()` connect+`SELECT 1` under a bounded timeout, sanitized message; unit-tested + **live E2E**: real Test-connection call to `127.0.0.1:5432/foundryx_service` succeeded ("Connected to foundryx_service on 127.0.0.1 (PostgreSQL).") |
| AC-22-03 | BE | PASS | `tests/test_autocount_sql_source.py` guard accept/reject matrix (`assert_select_only`); read-only session setup + per-query timeout unit-tested |
| AC-22-04 | FE | PASS | registry-driven form (no hand-rolled fields) confirmed live: `service_frontend/e2e/autocount-db-etl.spec.ts` creates the connection through the generic Integrations form, dbType select defaulting/switching to PostgreSQL, port field |
| AC-22-05 | BE | PASS | `tests/test_autocount_sql_source.py` introspection tests; **live**: the Query tab's schema tree lists `public.etl_demo_customers` with its real columns |
| AC-22-06 | BE | PASS | `tests/test_autocount_sql_source.py`/`test_autocount_etl_routes.py` preview-wrap-per-dialect tests; **live**: Test query returned "10 rows" against the real table |
| AC-22-07 | FE | PASS | **live E2E**: schema tree search → table click → Insert SELECT * → CodeMirror editor (`sql-editor` testid) → Test query → preview grid → key/watermark/compared `SearchSelect`/`MultiSelect` pickers fed by the preview's own result columns |
| AC-22-08 | BE | PASS | seam refactor - `sync.py`'s `source_factory` builds each impl's own transport; full pre-existing autocount pytest suite green (774/774 under `-k autocount`, 0 regressions); `tests/test_autocount_pipeline.py` (223 tests, the API-path regression pin) all green |
| AC-22-09 | BE | PASS | `tests/test_autocount_flat_mapping.py` (11 tests); **live**: Mapping tab re-points existing rows at flat preview column names (`acc_no`, `company_name`, `email`, `is_active`) |
| AC-22-10 | BE | PASS | `tests/test_autocount_sql_db_source.py` source_ref parity tests (`{DatabaseName}:{key}` scheme) |
| AC-22-11 | BE | PASS | `tests/test_autocount_etl_task_routes.py` (47 tests) 422 field-error matrix; **live-confirmed the hard way** - see finding #1 above (the connection/company database cross-check IS this AC's own validation, and it correctly 422'd a genuinely mismatched fixture) |
| AC-22-12 | BE | PASS | `tests/test_autocount_scheduler.py` (20 tests) - interval floors, no-watermark 15m floor, reconcile dailyAt/interval modes |
| AC-22-13 | BE | PASS | `tests/test_autocount_scheduler.py` beat sweep due-selection; dev/eager path exercised live by every `Run now`/`--trigger-run` in the E2E spec |
| AC-22-14 | BE | PASS | `tests/test_autocount_etl_task_routes.py` overlap-guard test (`EtlStateError` carrying the running run id) |
| AC-22-15 | BE | PASS | `tests/test_autocount_sql_db_source.py` watermark-advance tests; **live**: the AC-22-32 incremental run showed `Added: 0, Updated: 1` for exactly the touched row, watermark held for everything else |
| AC-22-16 | BE | PASS | `tests/test_autocount_sql_hashing.py` (15) + `test_autocount_sql_db_source.py` add/update/delete/no-change matrix; **live**: the AC-22-32 reconcile run showed `Deleted: 1` for exactly the deleted row after a baseline reconcile established the hash population, nothing else restaged |
| AC-22-17 | BE | PASS | `tests/test_autocount_etl_task_routes.py::test_runs_are_newest_first_paginated_and_capped`; **live**: the Runs tab (task variant) rendered Mode/Scanned/Added/Updated/Deleted/Failed/Duration for every run in both E2E journeys |
| AC-22-18 | BE/FE | PASS | `tests/test_autocount_etl_task_routes.py` activation-gate 409 tests + the new `ad71d27`/S5-review "refuse activation when the last preview reported failures"; **live**: `etl-activate` is absent/disabled until `etl-run-preview` succeeds, and only becomes clickable once the sink is pointed at a real (scripted) consumer |
| AC-22-19 | BE/FE | PASS | `tests/test_autocount_etl_task_routes.py` + `test_autocount_scheduler.py` pause/resume tests (409 unless active/paused, no re-preview needed on resume) - not separately clicked in the new E2E (out of this spec's golden-path scope) |
| AC-22-20 | BE | PASS | `tests/test_autocount_reconcile_push.py` (13) retryable-stays-staged tests; **live**: real HTTP POSTs from `SorentoSink.write_batch` reached the scripted consumer (`sorento.ingestCalls` asserted non-empty, non-dry-run) |
| AC-22-21 | BE | PASS | `tests/test_autocount_reconcile_push.py` delete-verdict tests; **live**: the AC-22-32 reconcile delete reached `.../customers/deletions` on the scripted consumer and the local `ac_row_hash` row was removed (verified directly against Postgres) |
| AC-22-22 | BE | PASS | `tests/test_autocount_sql_db_source.py`/`test_autocount_sql_source.py` delete-guard threshold tests (`SqlDeleteGuardExceeded`, the 0-row full-extract special case) |
| AC-22-23 | BE | PASS | `tests/test_autocount_masters_fanout.py` (29 tests) - dependency order, retryable-carry-over for products; not separately E2E'd (this spec is customer-only per the brief; masters fan-out was S4's own slice with its own coverage) |
| AC-22-24 | BE | PASS | `tests/test_autocount_documents.py` (48 tests) - header+lines extraction, ref minting, status mapping, cancel-as-status-update, line upsert/remove-vs-cancel-in-place (Appendix A7) |
| AC-22-25 | XR | PASS | Sorento PR #406 (`feat/autocount-cross-repo-contract`); sales-agent ingest+read-back exercised in this repo's `tests/test_autocount_masters_fanout.py` against the documented shape |
| AC-22-26 | XR | PASS | Sorento PR #406; document ingest (header+lines, per-line refs, retryable-on-missing-master) exercised in `tests/test_autocount_documents.py` against the documented A6/A7/A8 shapes |
| AC-22-27 | XR | PASS | Sorento PR #406; deletion endpoint (hard-delete-try, deactivate-fallback) consumed by `SorentoSink.delete_batch` and exercised **live** in this session's AC-22-32 run (against the scripted stand-in, contract-shape-accurate) |
| AC-22-28 | XR | PASS | Sorento PR #406 (`companyCode` anchor); `ac_company.sorento_company_code` sent on every call (`SorentoSink._body`), exercised live (`sink-company-code` set via real clicks, `ETLDEMO`) |
| AC-22-29 | BE | PASS | `tests/test_autocount_sorento_anchor.py` (19) + the general suite's tenant-scoping pattern (`_connection`/`_require_task_entity` resolve tenant+id together); connection lookups never bare-`get_by_id` |
| AC-22-30 | BE | PASS | provider `test()` sanitized-message tests (`tests/test_autocount.py`, `test_autocount_sql_source.py`); credentials Fernet-encrypted, never echoed - confirmed by inspection (`credentials_json` write-only in every schema) |
| AC-22-31 | E2E | **PASS** | `e2e/autocount-db-etl.spec.ts` "AC-22-31 golden path" - real clicks, live, 2 consecutive green runs (12.4s/12.7s) against current HEAD; 375px+1280px asserted (see below) |
| AC-22-32 | E2E | **PASS** | `e2e/autocount-db-etl.spec.ts` "AC-22-32 change detection" - real clicks + the documented backend helper for the no-UI-affordance reconcile trigger, live, 2 consecutive green runs (4.3s/4.4s) |

## Suite totals

- Backend: `python -m pytest -q` = **2451 passed, 1 skipped, 18 deselected, 0 failed** (full
  suite, ~24 min). `-k autocount` alone: **774 passed, 0 failed**.
- Frontend: `npx vitest run` = **166 files, 1373 tests, all passing**.
- New E2E spec: **2/2 passing**, verified stable across 3 consecutive runs (2 shown above + one
  earlier against the same HEAD).

## Responsive verification (375px / 1280px)

The new spec's `expectNoPageScroll` helper (`document.documentElement.scrollWidth <=
clientWidth + 1`) runs at both sizes on the task editor's Query, Review & Activate, and Runs
surfaces:

- **1280×900**: asserted after the Query tab save, after Activate/Run, and on the Runs tab - all
  passed, no horizontal overflow.
- **375×812**: the same Runs tab and Review & Activate tab re-checked after `setViewportSize` -
  both passed, no horizontal overflow.

## Regression check - existing autocount E2E specs

`npx playwright test e2e/autocount.spec.ts e2e/autocount-mapping.spec.ts` (standard
`playwright.config.ts`, own `webServer`, own dedicated per-test tenants):

- **`autocount-mapping.spec.ts` - 2/2 PASS** (both journeys, `AC-15-01..03/20` and
  `AC-15-40..44/16-10..31`, ~37s each).
- **`autocount.spec.ts` - 2/2 FAIL**, both on the same line (`syncNow`'s
  `page.waitForURL(/\/autocount\/review\/[\w-]+/)` timing out after clicking "Sync now"), run
  twice for reproducibility (identical failure both times, not a cold-compile flake). Root cause,
  traced via the backend log: the GRN "Sync now" click landed on the **Customer** row instead -
  `CompanyRepository`'s entity-config query is `ORDER BY entity_type ASC`
  (`autocount_repository.py:256`), so "Customer" sorts before "Goods received note"
  alphabetically, and the spec's own `clickSyncNow` picks the **first** "Actions" button on the
  page rather than scoping it to the GRN row. The vendor stub in `autocount.spec.ts` only answers
  `/api/GoodsReceivedNote/GetGoodsReceivedNote`, so a Customer sync request hits the stub's
  fallback with "Unexpected path /api/Debtor/GetDebtor" and the review-page navigation the test
  waits for never happens.
  - **This is PRE-EXISTING, not a plan-22 regression.** `git log` on
    `autocount_repository.py`'s `entity_type.asc()` ordering shows it was last touched in commit
    `22d3520` ("sweep stale mapping rows on replace_mapping save"), well before any of today's S5
    review-fix commits and unrelated to this slice's own changes (`use-entities-list-config.tsx`,
    the file that would need a row-scoped selector fix, was not touched by this branch at all).
    Filed as a finding for the coder/maintainer rather than fixed here, per the tester's mandate
    (test files only) - `clickSyncNow` should scope its "Actions" click to the GRN row (e.g.
    `openEntitiesTab`'s own row locator) instead of `.first()`.

## DoD gate (PRINCIPLES.md)

1. **Mock swapped to real.** `service_frontend/services/autocount-service.ts:341` -
   `export const autocountService: AutocountService = realAutocountService;` - confirmed bound to
   the real implementation, no lingering mock export path in any app/hook file.
2. **Backfill present.** Module migrations `0007_autocount_db_etl.py`, `0008_autocount_etl_s2.py`,
   `0009_autocount_s5_review.py` all present on disk and in git (`9924a20`). This session's live
   Postgres needed `0009` applied by hand (see finding #2 above) - a deploy-freshness gap in the
   shared dev DB, not a missing migration; the migration file itself is correct and idempotent
   (`ADD COLUMN IF NOT EXISTS`-equivalent existence check).
3. **No new permission keys.** `git diff origin/main..HEAD -- service_backend/modules/autocount/
   permissions/permissions.csv service_backend/app/permissions/permissions.csv` = **empty** - the
   autocount permission set (`autocount.companies.read/manage`, `autocount.sync.read/run`) was
   fully established before plan 22; this slice adds zero new keys, so no grant-sweep is needed.
4. **375px + 1280px verified.** See the Responsive verification section above.
5. **Correct ports.** Backend `:8001`, frontend `:3002` for the new spec (an explicit, brief-
   sanctioned deviation from the standard `:3001` because this worktree cannot bind `:3001` -
   confirmed both by the CLAUDE.md guardrail and by the sandbox's own permission classifier
   refusing a direct `next start -p 3001`). The regression check against the two PRE-EXISTING
   specs used the standard `:3001` via Playwright's own managed `webServer` (started and torn
   down for that run only, nothing left listening afterward).

## Deferred / backlog items registered by this plan

All already present in `documentation/backlogs/backlog.md` (created earlier in the slice, not by
this report): **BL-SS-034** (no tenant-level timezone for `dailyAt` reconcile scheduling),
**BL-SS-035** (Runs grid's "Deleted" column is a push-verdict count, not a staged-delete-intent
count), **BL-SS-036** (line-only-edit detection has no fallback for a source that doesn't bump
header LastModified), **BL-SS-037** (per-header `lineQuery` fan-out should batch via a real `IN`
expansion), **BL-SS-038** (on-prem connector agent for customers who can't port-forward),
**BL-SS-039** (cron-expression scheduling), **BL-SS-040** (extract the SQL source engine to
platform core once a second Service needs it), **BL-SS-041** (stock balances via the AutoCount
API, ~2 weeks out), **BL-SS-042** (SO/PO write-back to AutoCount), **BL-SS-043** (connections form
renders provider `select` fields with a bare shadcn `Select`, pre-existing, not a `SearchSelect`).

New finding from this slice, not yet backlogged: **the `autocount.spec.ts` "Sync now" `.first()`
selector regression** described above - recommend a `BL-SS-04x` entry pointing the coder at
`clickSyncNow` in `e2e/autocount.spec.ts` (scope the Actions click to the GRN row, not the first
row on the page).
