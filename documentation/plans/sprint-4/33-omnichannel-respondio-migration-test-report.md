# Sprint 4 · Plan 33 - Omnichannel respond.io Migration Tool · Test Execution Report

**Branch:** `sprint-4/33-respondio-migration` (worktree `.claude/worktrees/s33`)
**Slice under test:** S6 "Wire + E2E + runbook" (AC-MIG-56..61), with a re-spot-check of
AC-MIG-01..10 now that the real routes replace the S0 mock.
**Environment:** backend `:8012` (Postgres `foundryx_service_s33`, `ENVIRONMENT=development`,
`CELERY_TASK_ALWAYS_EAGER=true`, `CORS_ORIGIN_REGEX` widened for tenant subdomains on `:3010`),
frontend `:3010` (prod build, `rm -rf .next && npm run build` then `npx next start -p 3010`).
**Tester (this coder, S6):** `python -m pytest -q` (targeted, migration files only - the tester
agent runs the full suite next) + `npx vitest run` (migration files) + `agent-browser`
(sessions `s33c2`/`s33c3`/`s33c4`, real clicks, no Playwright).

## Result summary

| Gate | Result |
|---|---|
| Targeted backend suite (`-k "respondio_migration"`) | **95 passed**, 0 failed (S1: 19, S2+S6: 25, S3: 17, S4: 15, S5: 19) |
| Targeted frontend suite (migration files) | **61 tests passed**, 10 files |
| `npx eslint` (every touched/new file) | **0 errors** (3 pre-existing-pattern a11y warnings on the new upload dropzone, identical to `import-modal.tsx`'s own unfixed warnings) |
| `npx tsc --noEmit` | **0 NEW errors** (4 pre-existing errors elsewhere in the repo, unrelated to this slice, unchanged before/after) |
| `[E2E]` AC-MIG-59 (CSV-mode full journey) | **PASS** - `33-evidence/S6/01`-`09`, `19`-`20` |
| `[E2E]` AC-MIG-60 (re-run/abort/RBAC/isolation) | **PASS** - `33-evidence/S6/09`-`16` |
| Responsive 375px + 1280px | **PASS** - `05`, `17`, `18` at 375px; every other screenshot at 1280px |
| White-label | **FAIL found + FIXED this slice** - see AC-MIG-10 below |

**Two genuine gaps this slice's own re-check and live run caught (not previously flagged, both
fixed in this commit):**
1. **White-label hard-fail** - the S0 setup-form subtitle read "...onto a **Foundryx**
   workspace"; the live run against a real tenant is what surfaced it (a mock-only QA pass
   never renders literal "Foundryx" copy on a branded page the way a real page does). Fixed
   in `migration-form-view.tsx`; re-verified live post-fix (`19-whitelabel-fix-verified-1280.png`).
2. **AC-MIG-08's milestone log was never wired end to end** - `JobService.log()` had written
   `background_jobs.logs_json` since S2, but neither the schema nor the detail page ever
   surfaced it. Added `MigrationJobItem.logs` (detail-read only) + a `Logs` card (verbatim
   `jobs/[id]/page.tsx` clone); pinned by a new pytest
   (`test_get_job_surfaces_milestone_log_list_does_not`) and live-verified
   (`20-logs-card-1280.png`).

Also found and closed this slice: **AC-MIG-02's server-side search/sort/filter had never
actually been wired** (S2 shipped pagination + the status segment only) - a search box and
sortable columns that silently no-op against the real backend would have been a foolproof-UI
violation this slice's own live run would have caught. `MigrationService.list_jobs` now
resolves search/sort/the Filter popover in Python over the tenant's job set (bounded;
`MAX_LIST_SCAN_JOBS`), pinned by `test_list_jobs_search_sort_and_filter`. Backlogged for a
real DB-level implementation if job volume ever grows: **BL-SS-130**.

## Per-AC results (`33-omnichannel-respondio-migration-acceptance-criteria.md`)

### Slice S0 - re-spot-checked now that the real routes replace the mock

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-01 | [FE] | PASS | Menu entry present in all 3 arrays, gated `module:'omnichannel'` + `permission:'omnichannel_migration.read'` (unchanged from S0, `config/menu.config.tsx`); live-confirmed present for the read-only RBAC probe user (`14-readonly-user-list-1280.png`) and for the tenant-A admin. Absence-for-no-module/no-key unchanged from S0's own evidence (this slice did not touch menu gating). |
| AC-MIG-02 | [FE] | PASS | Resource shell clone of Users, exact column set (Source/Target workspace/Mode/Status/Progress/Contacts/Messages/Failures/Started/Finished) - `02-list-empty-1280.png`, `17-list-375.png`. Search/sort/Filter-popover WIRED THIS SLICE (see gap note above) - `test_list_jobs_search_sort_and_filter`. `viewKey: 'omnichannel.migration.list'` unchanged from S0. |
| AC-MIG-03 | [FE] | PASS | `ResourceForm`, ordered sections Source/Target/(Channels/People/Lifecycle when API mode has data)/(Scope, API mode only)/Review; shell's global Edit toggle + dirty-guard AlertDialog inherited, unchanged from S0. Live: `03`-`09`. |
| AC-MIG-04 | [FE] | PASS | `channel-map-row.tsx` unchanged from S0/S1; forced "Skip this channel" logic unit-verified by the mock's own seeded scenario (`respondio-migration-service.mock.test.ts` "preflight() surfaces at least one source channel with no compatible target"); not independently re-clicked live this slice (API-mode preflight against a rejected token returns zero source channels, so there was nothing to map live - see the deferred note below). |
| AC-MIG-05 | [FE] | PASS | `user-map-row.tsx` unchanged from S0/S1; email-match prefill logic unit-covered by the mock test suite. |
| AC-MIG-06 | [FE] | PASS | `lifecycle-map-row.tsx` unchanged from S0/S1; "never offers to create a stage" - the options list is built ONLY from `preflight.targetStages`, no create affordance exists in the component. |
| AC-MIG-07 | [FE] | PASS | Live-verified repeatedly this run: `Start migration` stays disabled until the EXACT current mapping has a fresh `done` dry run (`04`->`06`: disabled->enabled the instant the dry run settles); re-locks immediately on a changed upload (`09`, a re-uploaded file with a different key). |
| AC-MIG-08 | [FE] | PASS (gap fixed this slice - see above) | Progress bar + Details + counts-report `DataGrid` + failure `DataGrid` + Download + Actions-menu-gated-Abort + Logs card, all live: `07`, `10`-`13`, `20`. |
| AC-MIG-09 | [FE] | PASS | Mock still tunes every state (`respondio-migration-service.mock.test.ts`, 13 tests: pending/running/needs_review/done/failed/aborted, the `dry_run_required`/`migration_in_progress` ledger) - survives as the frontend test fixture per AC-MIG-56's own instruction, no longer the shipped binding. |
| AC-MIG-10 | [FE] | PASS (after the white-label fix) | 375px non-clipped (`05`, `17`, `18`); every dropdown is `SearchSelect` (Method, connection, workspace, channel/user/team/lifecycle rows, CSV header-map rows); no instructional copy added this slice; "Foundryx" leak found + fixed (see above), re-verified `document.body.innerText.includes('Foundryx') === false`. |

### Slices S1-S5 - unchanged this slice, targeted suite re-run green

| AC range | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-11..17 (S1) | [BE]/[T] | PASS | `tests/test_omnichannel_respondio_migration.py`, 19 tests - unchanged, re-run green this slice. Live-reconfirmed this slice: `test_connection_test_401_reports_token_rejected_no_token_leak`'s exact assertion is what the REAL vendor call reproduced live (`01-integration-test-401-1280.png`, `03-api-mode-preflight-blocker-1280.png`). |
| AC-MIG-18..29 (S2) | [BE]/[T] | PASS | `tests/test_omnichannel_respondio_migration_jobs.py`, 25 tests (24 from S2 + 1 new this slice, `test_gateway_contract_files_carry_no_migration_trace` moved here as the AC-MIG-55 home) - unchanged core logic, re-run green. Live-reconfirmed this slice: contacts-only dry run then real run (`06`, `07`), `migration_in_progress`/`dry_run_required` implicitly exercised by the Start-disabled-until-dry-run gate holding throughout. |
| AC-MIG-30..38 (S3) | [BE]/[T] | PASS | `tests/test_omnichannel_respondio_migration_s3.py`, 17 tests - unchanged, re-run green. Not live-reconfirmed this slice (no valid respond.io token on this machine - identities/messages never run for a real API-mode job here; CSV mode does not exercise this phase at all, AC-MIG-48's own point). |
| AC-MIG-39..45 (S4) | [BE]/[T] | PASS | `tests/test_omnichannel_respondio_migration_s4.py`, 15 tests - unchanged, re-run green. Same live-reconfirmation gap as S3 (no valid token). |
| AC-MIG-46..49 (S5) | [BE]/[T] | PASS | `tests/test_omnichannel_respondio_migration_s5.py`, 19 tests - unchanged, re-run green. Live-reconfirmed THIS slice end to end: CSV upload (`04`), header map + alias fallback (`04` explicit map, `09` alias-fallback run), the three CSV-mode blockers stated up front on both the dry run and the real run (`06`, `07`), CSV-mode idempotent re-run (`09`). |

### Cross-cutting - security, tenancy, permissions

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-50 | [BE] | PASS | `omnichannel_migration.read`/`.manage` CSV rows (S1), reads gated `.read` writes gated `.manage` throughout the router (unchanged); manifest version bump delivers the grant sweep to already-provisioned tenants (unchanged, S1). Live-reconfirmed this slice: the RBAC probe role/user (only `.read`) can list but gets `403` on create (`14`, `15`, plus a direct API probe: `GET /jobs` 200, `POST /jobs` 403). |
| AC-MIG-51 | [BE] | PASS | Every route/service method resolves tenant from the JWT (never client input); `channelMap`/`userMap`/lifecycle re-validated at USE time (`_resolve_channel_map`/`_resolve_user_map`/`_validate_mapping`, unchanged S2). |
| AC-MIG-52 | [BE] | PASS | `test_connection_resolution_is_tenant_scoped`, `test_preflight_unknown_connection_id_is_uniform_404` (S1, unchanged); live-reconfirmed this slice: tenant B (fresh, unrelated) never sees tenant A's connection or jobs (`16-tenant-b-empty-list-1280.png`). |
| AC-MIG-53 | [BE] | PASS | `test_failures_csv_download_authed_private_no_store` (S2, unchanged) + S5's storage-backed version; live-reconfirmed this slice: `Download CSV` fires a real authed `GET .../failures.csv` (`200`), never a bare `<a href>` (`11-failures-download-clicked-1280.png`). |
| AC-MIG-54 | [BE] | PASS | Not independently re-verified this slice (no module uninstall exercised in this lane's E2E run) - covered by the module's existing `uninstall_tenant` test suite (unchanged, out of this slice's touched-file set). |
| AC-MIG-55 | [BE]/[T] | PASS | **New guard test this slice** - `test_gateway_contract_files_carry_no_migration_trace` (a content guard over `routers/api_v1.py` + the consumer guide, not a `git diff`, which would be flaky across a rebase/merge). `git diff` for this slice touches neither file (confirmed by inspection of the diff this coder produced). |

### Slice S6 - wire, evidence, runbook, report

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-56 | [FE] | PASS | Every mock call swapped to the real `api-client` call at the service boundary (`respondio-migration-service.ts` now binds `realRespondioMigrationService`); `uploadCsv`/`cancelJob` added to the interface + real impl; the mock survives ONLY as `*.mock.test.ts`'s fixture, imported by no page. `grep -rn "S0 MOCK"` is empty (the one remaining hit, a stale doc comment in `types/integration.ts`, was cleaned up too). |
| AC-MIG-57 | [FE] | PASS | Detail page polls every 3s while `MIGRATION_JOB_IN_FLIGHT`, stops on a terminal status (unchanged `[jobId]/page.tsx` logic); Abort offered ONLY while in flight (`use-migration-actions.tsx isVisible`), takes effect immediately - the dedicated cancel route is a synchronous commit, confirmed live within the SAME poll cycle (`12`->`13`). |
| AC-MIG-58 | [T] | PASS | Setup form schema (`migration-schema.test.ts`, 9 tests: required workspace, conditional connection/contactsCsvKey by source, channel-map completeness, hash stability INCLUDING the new CSV fields); Start-disabled-until-dry-run (`use-migration-form.test.tsx`, 10 tests, incl. the CSV-mapping-hash-changes-on-reupload case); status badge registry (`migration-status.test.ts`, unchanged, 2 tests); failure-table renderer (`migration-failures-table.test.tsx`, unchanged, 2 tests); `useCan` gating of Start/Abort (`use-migration-actions.test.tsx`, 7 NEW tests - permission tag, visibility matrix, no-deferred/no-confirm assertion, real cancel-route call + 409 mapping) + every mock service state (`respondio-migration-service.mock.test.ts`, 13 tests, unchanged). New this slice: `csv-upload-field.test.tsx` (4), `csv-header-map-section.test.tsx` (3), `respondio-migration-service.real.test.ts` (7, pins the exact routes/verbs incl. the dedicated cancel route), `migration-report-card.test.tsx` +1 (the `messagesSkippedBeforeFloor` note). **61 tests total, 10 files, all passing.** |
| AC-MIG-59 | [E2E] | PASS | Recorded `agent-browser --session s33c2` run, real clicks from `/` (one documented exception: the initial tenant-subdomain login URL, the same S0-evidence-README convention), 1280 AND 375, dedicated timestamped tenant (`p33-mig-20260907t042326z`): sidebar to Omnichannel to Migration, New migration, respond.io connection with a dummy token, Test (real vendor 401), API-mode preflight blocker + Start disabled, switch to CSV mode, upload a 3-row CSV (`s33-contacts-20260907t042326z.csv`), map one column explicitly, Run dry run, counts report + 3 CSV blockers, Start migration (enabled only after the dry run), progress to Done, Contacts list shows the 3 migrated rows (also confirmed via a tenant-scoped API read: `total: 3`). Evidence `33-evidence/S6/01`-`09`, `19`-`20`, README with every setup call verbatim. **DEFERRED (stated, not silently missing):** the API-mode "migrated thread in the Inbox, no unread badge" clause needs a valid respond.io token this machine does not have - covered by S3/S4 pytest instead (cited above). |
| AC-MIG-60 | [E2E] | PASS | Same run: re-running the identical CSV mapping reports `3 fetched / 0 would create / 3 would update` (`09`) and the persisted contact count stayed `3` after the matching real run (API-verified, not just the report); Abort on a fresh in-flight job (a hand-inserted `running` probe row, disclosed - this lane's `CELERY_TASK_ALWAYS_EAGER=true` makes a real job finish before the creating request even returns, so there is no naturally-observable in-flight window) leaves it `Aborted` with `40/100 processed` intact (`12`->`13`); a role holding only `omnichannel_migration.read` sees no Start control (no "New migration" button, no Actions column) and the API independently refuses `POST .../jobs` with `403` (`14`, `15`); a second freshly-provisioned tenant (`p33-migb-20260907t045000z`) sees `No data available` (`16`). **DEFERRED (stated):** genuine cursor-resume-after-a-crash-mid-flight is structurally unobservable under eager-mode execution from a browser click; covered by `test_cooperative_abort_stops_before_next_page_and_resume_continues`. |
| AC-MIG-61 | [T] | PASS | This report; `documentation/omnichannel/respondio-cutover-runbook.md` shipped this slice (prerequisites, the WABA number move, dry-run-then-run procedure, CSV-mode limits, rollback notes); deferred items registered in `documentation/backlogs/backlog.md` as **BL-SS-129** (no real backend route for Retry/Complete-anyway on this job type - both dropped from the UI this slice rather than wired to the wrong backend) and **BL-SS-130** (list search/sort/filter is in-memory, bounded but not SQL-level). |

## Decisions this slice took where the plan/UAC were silent (also inline as code comments)

- **Abort is a plain immediate `run`, not a `DeferredActionButton`.** The S0 registry had
  wired Abort to the generic `deferred: {actionKey:'jobs.abort'}` seam; that backend handler
  (`app/deferred_actions/handlers.py _jobs_abort`) hardcodes `StorageMigrationService(db)
  .abort(...)` - a DIFFERENT job type entirely, and every generic core `/jobs/{id}/{abort,
  retry,complete}` route (`app/api/v1/jobs.py`) is the same way. Abort now calls the
  DEDICATED `POST /omnichannel/migration/jobs/{id}/cancel` route directly via a plain `run`
  handler (no confirm dialog either - not one of PRINCIPLES.md's named typed-confirm
  carve-outs, and the dedicated route is a direct, no-undo commit, so a grace-window
  `DeferredActionButton` would falsely promise a window that does not exist). Retry and
  Complete-anyway are DROPPED entirely (no backend route exists for either on this job type;
  `needs_review` is structurally unreachable from the real handler) - **BL-SS-129**.
- **`MigrationService.list_jobs` gained search/sort/the Filter popover this slice** (S2 had
  shipped pagination + the status segment only) - resolved in Python over the tenant's job
  set rather than a SQL clause, because `spaceLabel`/`workspaceName`/`mode` live inside
  `payload_json` with no native column, and a portable cross-dialect JSON-path clause (this
  suite runs on in-memory SQLite, production on Postgres) was not worth building for a list
  bounded by `migration_in_progress`'s own one-non-terminal-job-per-workspace guard -
  **BL-SS-130** if that assumption ever breaks.
- **CSV mode's Source card now surfaces `preflight.warnings` inline** (a genuine S0/S1 gap:
  the field existed on the wire since S1 but nothing rendered it) - a `Blocked`/`Notice`
  badge list under the connection picker, visible the moment preflight resolves
  `apiAvailable:false` or returns any warning.
- **The white-label subtitle fix** ("...onto a Foundryx workspace" -> "...onto a workspace")
  is a one-line string change with no behavioural effect - included in this commit because
  this slice's own live E2E run is what caught it.
- **The milestone-log wiring** (`MigrationJobLogEntry` schema, `MigrationJobItem.logs`,
  the detail page's `Logs` card) closes AC-MIG-08's own "the milestone log" clause, which had
  never been implemented past `JobService.log()` writing `logs_json` - a straight omission
  from S0 through S5, not a regression this slice introduced.
- **CSV-mode header-map keys left "Not mapped" fall back to the backend's own
  case-insensitive alias guess** (`_HEADER_ALIASES`) - the setup form does not pre-fill an
  alias guess client-side (kept simple: what the operator sees mapped is exactly what they
  chose; the backend's own fallback still applies underneath, exercised live in the re-run
  scenario, AC-MIG-60's evidence item 7).

## Deferred items (registered in `documentation/backlogs/backlog.md`)

| ID | Title | Priority |
|---|---|---|
| BL-SS-129 | Migration Retry/Complete-anyway have no real backend route for this job type; build a dedicated `POST .../jobs/{id}/retry` if in-place retry is needed | Medium |
| BL-SS-130 | Migration list search/sort/filter runs in Python, not SQL - revisit if job volume grows (ties to BL-SS-121, incremental top-up runs) | Low |

Both ids continue from this branch's `backlog.md` current max (`BL-SS-128`); the plan
document's own §8 table reserved `BL-SS-120..129`, which had already collided with plans
28/29's use of the same range in the merged `main` history - **flag both ids for renumbering
at merge** per the plan's own merge-renumber convention.

## Full-suite runs (NOT run by this coder - the tester's next step per the brief)

This slice ran ONLY the targeted backend suite (`-k "respondio_migration"`, 95 passed) and the
targeted frontend suite (migration files, 61 passed), per the S6 brief's explicit instruction
("No full backend suite - the tester runs it next"). The full `pytest -q` / `npx vitest run`
sweep, plus any residual cross-file interaction this coder's targeted runs cannot see, is the
tester's own gate.
