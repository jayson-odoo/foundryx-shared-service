# 01 - AutoCount DB-only company onboarding - Test Execution Report (slice S3)

Keyed to `01-autocount-db-company-acceptance-criteria.md` (AC-01-01..24). Executed 2026-09-04 on
branch `sprint-5/autocount-db-company`, worktree `.claude/worktrees/autocount-db-company`, against
branch HEAD `6964b29` (S1 frontend `5876cc2`, S2 backend + mock→real swap `ed53174`, the
`uq_connection_tenant_type` carve-out fix `322a02e`).

## Environment

- Backend: FastAPI on **:8002** from this worktree (`.venv/bin/uvicorn app.main:app --port 8002`,
  no `--reload`), native Postgres `foundryx_service` (shared with the main checkout's `main`
  servers on :3001/:8001, which were left untouched). Live `alembic_version` =
  `conn_erp_llm_s501` (this branch's core migration is applied).
- Frontend: **prod build on :3002** from this worktree (`rm -rf .next && npm run build` with
  `NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8002` baked in at build time - it is a
  `NEXT_PUBLIC_` value, so setting it only at `next start` would still have pointed the browser at
  :8001 - then `next start -p 3002`). Port ownership confirmed via `lsof` (cwd = this worktree).
- Unit/integration: `.venv/bin/python -m pytest -q` (in-memory SQLite, `schema_translate_map`),
  `npx vitest run` (jsdom).
- E2E: **headless Chromium only**. A temporary, uncommitted `playwright.wt3002.tmp.config.ts`
  (`baseURL http://localhost:3002`, no `webServer`, `workers: 1`) drove the new spec with
  `E2E_API_URL=http://localhost:8002`; deleted before commit. `playwright.config.ts` is unchanged
  and remains the deliverable.
- Pre-existing spec regression check: the three `e2e/autocount*.spec.ts` files hardcode
  `:8001`/`:3001`, so port-rewritten COPIES (`sed 8001→8002, 3001→3002`, nothing else) were run
  from a temporary `e2e-wt3002-tmp/` dir against the same :3002/:8002 stack, then deleted. The
  one failure (below) was cross-checked by running the ORIGINAL spec against the main checkout's
  `main` stack on :3001/:8001 (standard config, `reuseExistingServer`), where it passes.

## AC-01-24 - the new E2E spec

`service_frontend/e2e/autocount-db-company.spec.ts` - one test, real clicks throughout after the
single sign-in `goto`: sidebar AutoCount → Companies → **Connect company** → Source toggle
**SQL database** (asserted `data-state="on"`; Create asserted disabled before a pick) → SQL
database connection `SearchSelect` → Label → **Create** → Overview (h1 = label, `foundryx_service`
discovered, Integration row **"SQL database"** + "Open connection") → **Entities** tab → **Add
entity** picker (exactly 9 options; Customer, Supplier, Product present; Goods received note
absent) → Customer → Configure → task editor → Edit → Query tab (**locked-connection row** with
`name · database`, NO Connection combobox, NO "No SQL database connection yet." warning) → schema
tree search `etl_demo_customers` → Insert SELECT * → **Test query** (preview badge + `<tbody>`
rows > 0, `acc_no` column) → Key columns = `acc_no` → **Save** (read mode still locked) → sidebar
Companies → company row → Entities (Customer row present; row "…" offers "Configure database
query", NOT "Change source" / "Edit first-run window"; Add-entity now 8 options, Customer gone) →
**375×812 viewport, no horizontal overflow on the Entities tab** → back to 1280 → Companies →
Connect company → SQL database → banner "Every SQL database connection is already registered as a
company." + picker and Create disabled.

**Fixture/isolation.** The spec provisions its own timestamped tenant (`e2e-dbco-<stamp>`) via
the operator API, installs `autocount`, creates the `sql_database` connection through
`POST /integrations/connections` as that tenant's admin (setup only; the company flow is clicks),
runs plan 22's `python -m scripts.seed_etl_demo_source` (no args - idempotent, creates only the
`public.etl_demo_*` dev tables, nothing tenant-scoped) so the schema tree lists a real table, and
in `finally` archives + purges the tenant through `GET .../transitions` → `POST .../transition` →
`POST .../purge {confirmSlug}` (best effort, logged if it cannot). Both `PLAYWRIGHT` base URL and
the API URL are parameterized (`baseURL` fixture + `E2E_API_URL`) so the spec runs unchanged on
the standard :3001/:8001 stack.

**Live result (2 consecutive clean runs, fresh tenant each):**

```
✓ AC-01-24 DB company: connect from a SQL database -> add Customer -> locked connection -> preview rows  (6.8s)
1 passed (8.4s)
✓ AC-01-24 DB company: connect from a SQL database -> add Customer -> locked connection -> preview rows  (6.3s)
1 passed (6.7s)
```

Backend log for one run confirms the real path was exercised, not a stub: `POST
/autocount/companies` → **201** (no vendor call; the identity probe ran against the real
Postgres), `GET /autocount/sql/connections/{id}/schema` 200, `POST /autocount/sql/preview` 200,
`PUT /autocount/companies/{id}/entities/customer/etl-task` **200**, then `POST
/platform/tenants/{id}/transition` 200 + `POST /platform/tenants/{id}/purge` **204**. `SELECT
count(*) FROM tenants WHERE slug LIKE 'e2e-dbco-%'` = **0** after the run (no residue).

### Findings from building/running the spec

1. **No product bug surfaced by the new journey.** Every step behaved per the UAC on the first
   run; no selector workaround (`dispatchEvent`) was needed - Playwright's `click()` fired every
   Next/Radix handler.
2. **`GET .../entities/customer/mapping` → 404** appears in the backend log when the task editor
   opens for a not-yet-born entity (the Mapping tab probes for rows that do not exist yet). The
   editor handles it (no error surfaced, the save succeeded) and it predates this slice (plan 22
   S4 "Add entity" behaviour) - noted, not a finding against this plan.
3. **Pre-existing `autocount-db-etl.spec.ts` was broken BY this branch's semantics** - see the
   regression section below; reconciled in test-owned files on the coordinator's instruction
   (spec + dev seed rig), no product code touched. It also surfaced a pre-existing plan-22 S4
   product gap (stale Mapping tab after a born row) that is recorded there, not fixed.

## Results by AC id

| AC | Tag | Result | Evidence |
|----|-----|--------|----------|
| AC-01-01 | BE | PASS | `tests/test_autocount_db_company.py`: `test_create_from_a_sql_connection_derives_identity_from_the_config_database`, `test_an_autocount_connection_still_runs_the_api_flow`, `test_another_provider_or_another_tenants_connection_is_a_uniform_404`, `test_create_requires_companies_manage`; **live**: `POST /autocount/companies` 201 from a `sql_database` connection with no vendor call (E2E step "Create") |
| AC-01-02 | BE | PASS | `test_create_from_a_sql_connection_derives_identity_from_the_config_database`, `test_a_probe_mismatch_is_a_422_on_connectionId_and_creates_nothing`, `test_a_connect_failure_is_a_422_with_a_sanitized_message`, `test_a_failing_probe_statement_is_a_422_not_a_500`; **live**: the create-time `current_database()` probe ran against the real Postgres and matched `config.database` - Overview shows `foundryx_service` as the discovered database |
| AC-01-03 | BE | PASS | `test_the_profile_company_name_is_read_when_available`, `test_an_absent_profile_table_leaves_company_name_blank_and_still_creates`; **live**: Postgres has no `dbo.Profile`, create still succeeded silently (Overview "Company name" = "-") |
| AC-01-04 | BE | PASS | `test_the_same_database_held_by_an_api_company_is_a_409`, `test_a_sql_connection_already_bound_to_a_company_is_a_409`; **live**: the second Connect-company attempt shows the all-bound banner and withholds the bound connection (the UI never lets the 409 be reached without a second connection - foolproof-UI; the 409 itself is backend-pinned) |
| AC-01-05 | BE | PASS | `test_a_db_company_seeds_no_entity_configs_or_mappings` (+ API regression pin inside `test_an_autocount_connection_still_runs_the_api_flow`); **live**: the fresh DB company's Entities list is empty and all 9 entities are addable |
| AC-01-06 | BE | PASS | `test_create_records_a_discover_company_activity_row`, `test_a_probe_mismatch_records_an_error_activity_row` |
| AC-01-07 | BE | PASS | `test_source_kind_is_derived_on_list_and_detail`, `test_the_list_resolves_connections_in_one_batched_query` (query-count assertion), `test_a_deleted_connection_reports_api_and_never_500s`; **live** on the shared dev DB: `GET /autocount/companies` → `V Soft Trading` = `api`, `ETL Demo Co` = `db` (see regression finding) |
| AC-01-08 | BE | PASS | `test_client_for_refuses_a_db_company_with_a_named_error`, `test_switching_an_entity_to_autocount_read_on_a_db_company_is_a_409` |
| AC-01-09 | BE | PASS | `test_an_omitted_task_connection_is_filled_and_the_row_is_born_sql_db`, `test_a_different_connection_on_a_db_company_is_a_422`, `test_an_api_company_keeps_the_free_picker`; **live**: `PUT .../etl-task` 200 against the locked company connection |
| AC-01-10 | BE | PASS | `test_an_omitted_task_connection_is_filled_and_the_row_is_born_sql_db` (customer born `sql_db`), `test_goods_received_note_is_not_available_on_a_db_company`; **live**: after Save the Customer row lists on Entities and drops out of the Add-entity picker (8 left) |
| AC-01-11 | BE | PASS | `test_document_prerequisites_are_empty_without_a_document_entity`, `test_document_prerequisites_report_missing_masters`, `test_document_prerequisites_report_inactive_masters`, `test_document_prerequisites_are_clear_when_all_masters_are_active`, `test_document_prerequisites_apply_to_an_api_company_too`; **live**: the DB company detail carries `documentPrerequisites: []` |
| AC-01-12 | FE | PASS | `connect-company-view.test.tsx`: "offers AutoCount API \| SQL database and defaults to API when both have a connection", "defaults to SQL database when only it has an unbound connection", "the SQL picker lists the source's (already-filtered) connections only", "switching source clears the picked connection"; `use-autocount-connections.test.ts` default matrix; **live**: toggle click → `data-state="on"`, picker filtered to the SQL connection |
| AC-01-13 | FE | PASS | `connect-company-view.test.tsx`: "SQL source with no connection at all: banner + link to Integrations", "SQL source with every connection bound: the all-bound banner", "the API source keeps today's two banners (regression pin)", "Create is disabled until a connection is picked"; **live**: Create disabled before the pick; all-bound banner + disabled picker/Create on the second attempt |
| AC-01-14 | FE | PASS | `connect-company-view.test.tsx`: "renders a 422 on connectionId inline under the picker", "renders a 409 inline naming the existing company"; **live**: Create → `createCompany` → routed to the new company's Overview |
| AC-01-15 | FE | PASS | **live E2E** `expectNoPageScroll` on the Connect-company form at **1280×900 AND 375×812** (`connect company @375`, review follow-up): after `setViewportSize(375, 812)` the Source toggle, the `SQL database connection` picker, the Label input and Create are all still visible, no horizontal page scroll; viewport restored to 1280 before Create |
| AC-01-16 | FE | PASS | `company-detail-view.test.tsx`: "an API company's Integration row reads \"AutoCount API\" and still links the connection", "a DB company's Integration row reads \"SQL database\""; **live**: `company-source-kind` = "SQL database" + "Open connection" link |
| AC-01-17 | FE | PASS | `add-entity-control.test.tsx`: "a DB company offers all nine sql_db entities incl. customer + supplier, never GRN", "an API company keeps today's seven - customer/supplier are API-seeded, never added", "a DB company's list drops the entities already configured"; `autocount-meta.test.ts` nine-entity pin; **live**: exactly 9 options, Customer/Supplier/Product present, GRN absent |
| AC-01-18 | FE | PASS | `entities-list-config.test.tsx`: "never offers \"Edit first-run window\" nor \"Change source\" on a DB company", "keeps configure-task, sync-now, configure-mapping and refetch-history on a DB company", "an API company's rows are unchanged (regression pin)"; **live**: Customer row "…" has "Configure database query", no "Change source", no "Edit first-run window" |
| AC-01-19 | FE | PASS | `query-tab.test.tsx`: "replaces the Connection picker with a read-only row on a DB company", "an API company keeps the searchable Connection picker", "never patches connectionId on mount - the editor seeds it into the baseline (review fix)", "an API company with no SQL connection still gets the warning (regression pin)"; **`task-editor-view.locked-connection.test.tsx`** (review follow-up, real `ResourceForm` shell): "mounts clean: locked row shown, config.connectionId pre-set, no picker", "Edit -> Cancel on an untouched editor never asks \"Discard changes?\"", "control: a real edit then Cancel DOES ask \"Discard changes?\" (the guard is live)", "an API company keeps the null draft as-is (picker present, nothing seeded)" - the Edit -> Cancel case was confirmed to FAIL against the pre-fix code (git-stash mutation check); **live**: `locked-connection` row (`<name> · foundryx_service`), zero `Connection` comboboxes, zero `no-sql-connection` alerts, in edit AND read mode |
| AC-01-20 | FE | PASS | `document-prerequisite-card.test.tsx` (3) + `company-detail-view.test.tsx`: "is absent when every prerequisite is active", "renders above the Entities list, one line per blocked document, with Add for the missing master", "also warns on an API company with a configured document entity"; **live**: absent case only (the E2E company configures no document entity) |
| AC-01-21 | FE | PASS | **live E2E**: no horizontal overflow at 1280 on the Query tab and Entities tab, and at **375×812** on BOTH the task editor Query tab (`task editor / query tab @375`, review follow-up: locked row + preview badge still visible after Test query) and the Entities tab (`company / entities tab @375`, Customer row still visible); Overview at 375 verified in the S1 browser pass |
| AC-01-22 | T | PASS | `tests/test_autocount_db_company.py` (29) + `tests/test_connection_index_drift.py` (1) + `tests/test_autocount_entity_parity.py` (2) = **33 passed**; full `tests/test_autocount*` (15 files) = **808 passed, 0 failed** (4m58s) |
| AC-01-23 | T | PASS | `npx vitest run` = **176 files, 1484 tests, all passing** (43s, review follow-up run) - the S1 files listed in the evidence above (`connect-company-view`, `company-detail-view`, `add-entity-control`, `document-prerequisite-card`, `entities-list-config`, `query-tab`, `use-autocount-connections`, `autocount-service.mock`, `autocount-meta`) all green, plus the new `task-editor-view.locked-connection.test.tsx` (4) |
| AC-01-24 | E2E | **PASS** | `e2e/autocount-db-company.spec.ts` - real clicks, dedicated timestamped tenant, live, 2 consecutive green runs (6.8s / 6.3s), tenant purged after each |

**Totals: 24 PASS, 0 FAIL, 0 DEFERRED.**

## Suite totals

- Backend S2 files: `pytest -q tests/test_autocount_db_company.py tests/test_connection_index_drift.py
  tests/test_autocount_entity_parity.py` = **33 passed, 0 failed** (45s).
- Backend `pytest -q tests/test_autocount*` = **808 passed, 0 failed** (4m58s).
- Frontend `npx vitest run` = **176 files, 1484 tests, all passing** (43s, after the review follow-up).
- New E2E spec: **1/1 passing**, 2 consecutive runs (re-run 2 more times after the review follow-up, both green).

## Responsive verification (375px / 1280px)

`expectNoPageScroll` (`documentElement.scrollWidth <= max(clientWidth, innerWidth) + 1`):

- **1280×900**: Connect-company form (after the pick), task editor Query tab (after Test query),
  company Entities tab - all passed.
- **375×812** (three surfaces, each via `setViewportSize` then restored to 1280 so the rest of
  the journey is unaffected): the Connect-company form (toggle, picker, Label, Create visible -
  AC-01-15), the task editor Query tab after Test query (locked row + preview badge visible -
  AC-01-21), the company Entities tab (Customer row visible - AC-01-21). All passed.
- Overview at 375 was verified in S1's agent-browser pass (S1 report).

## Regression check - pre-existing autocount E2E specs (same :3002/:8002 stack)

| Spec | Result | Notes |
|------|--------|-------|
| `autocount.spec.ts` | **2/2 PASS** | Both GRN journeys (~10s each). Note: plan 22's report recorded this spec failing on the "Sync now" `.first()` selector; it passes on this stack. |
| `autocount-mapping.spec.ts` | **2/2 PASS** | Both mapping/formula journeys. |
| `autocount-db-etl.spec.ts` | **2/2 PASS after the test-owned reconciliation below** (initially FAIL on this branch / PASS on `main`) | Fresh-rig run 14.5s / 4.0s, immediate re-run 11.6s / 4.0s; the new spec re-run green afterwards (6.3s) - no interference. |

### Finding (resolved in test-owned files): `autocount-db-etl.spec.ts` AC-22-31 failed on this branch at "Change source"

- **Repro (before the fix)**: `npx playwright test e2e/autocount-db-etl.spec.ts` against this
  branch's stack → `locator.click: Timeout 3000ms exceeded. waiting for getByRole('menuitem', {
  name: /change source/i })` inside `switchCustomerToDatabase`. The ORIGINAL spec against the
  main checkout's `main` stack (:3001/:8001, same shared Postgres) passed **2/2 (33.9s / 10.4s)**
  - branch-induced, not environment.
- **Root cause**: plan 22's dev rig (`scripts/seed_etl_demo_source.py --company`,
  `ensure_demo_company`) built the `ETL Demo Co` company DIRECTLY via the ORM on a
  `sql_database` connection (`foundryx_service`) and then called
  `CompanyService.seed_company_defaults`, seeding the API-shaped
  `goods_received_note/supplier/customer` rows (`source_impl='autocount_read'`), because on
  `main` a company could only be created from an `autocount` connection and the S2 live-verify
  reached the DB path through "Change source". Under this plan `sourceKind` is DERIVED from the
  connection's provider (AC-01-07), so that company reports `sourceKind: 'db'` (confirmed: `GET
  /autocount/companies` → `ETL Demo Co | foundryx_service | db`), and AC-01-18 correctly hides
  `change-source` on a DB company. The fixture was a hybrid the product can no longer create: a
  DB company carrying API-seeded rows (contrary to AC-01-05), including a GRN row a DB company
  cannot use (AC-01-10).
- **Blast radius**: dev fixture only. No product-created company can be in this state - on
  `main` the create path never accepted a `sql_database` connection, and every product-created
  company on the shared dev DB reports `api` (`V Soft Trading`).
- **Fix applied (test-owned files only, no product code)**, on the coordinator's instruction:
  1. `service_frontend/e2e/autocount-db-etl.spec.ts` - `switchCustomerToDatabase` became
     `openCustomerTaskEditor`: no Customer row → **Add entity → Customer → Configure** (the
     product path on a DB company); row present → "…" → "Change source" ONLY when offered
     (legacy API-seeded row), else straight to "Configure database query". `configureQuery`
     honours the **locked connection row** (AC-01-19; the spec-created `sql_database`
     connection is still exercised as a connection, AC-22-01/02/04, just not picked) and
     addresses the key/compared pickers by offset instead of hardcoded indices.
     `configureMapping` handles a born `sql_db` row with **no mapping rows** (Add field ×4:
     code/name/email/is_active ← the flat preview columns) as well as the legacy re-point path.
     **New assertion**: after Activate, `GET /autocount/companies/{id}` must report the Customer
     entity `sourceImpl === 'sql_db'` regardless of which path was taken ("Activation IS the
     switch to the DB path", `EtlService.activate_task`).
  2. `service_backend/scripts/seed_etl_demo_source.py` - `--company` no longer calls
     `seed_company_defaults` (docstring note added: a `sql_database`-connected company IS a DB
     company and must never carry `autocount_read` seeds, AC-01-05/10). Verified on a throwaway
     tenant: first run prints `Created company '…' … with no entity configs.` (0
     `ac_entity_config` rows), second run prints `Company '…' already exists`; tenant archived +
     purged afterwards (0 leftover connections). Not imported by any pytest module, so the
     backend suite was not re-run for it.
  3. The spec's `beforeAll` parse now accepts BOTH output forms (`/[Cc]ompany '([^']+)'/`) - on a
     DB with no demo company yet it used to die in `beforeAll` before anything ran (hit on the
     very first attempt here; pre-existing).
- **Shared-DB reconciliation**: the existing `ETL Demo Co` row's legacy fixture rows (its
  `autocount_read` GRN/supplier configs, the customer config + 41 mapping rows) were deleted
  (`app_autocount.ac_entity_config` / `ac_field_mapping` for that company id only - dev-fixture
  rows the rig documents as droppable) so the shared demo company matches the fixture's new
  shape AND so the fresh-rig path could be exercised for real. Row hashes/watermarks were left;
  the spec re-baselines them itself.
- **Verification**: fresh path (no Customer row, no mapping rows) **2/2 PASS (14.5s / 4.0s)**,
  then an immediate re-run against the born row + 4 mapping rows **2/2 PASS (11.6s / 4.0s)**,
  then `autocount-db-company.spec.ts` once more **1/1 PASS (6.3s)**.

### Finding (pre-existing, product code, NOT fixed): Mapping tab is stale after a born row

While driving the fresh path: the task editor fetches the mapping when it mounts, i.e. BEFORE
"Add entity → first query save" births the row (`GET .../entities/customer/mapping` → 404), and
`task-editor-view.tsx`'s `onSave` never calls `mapping.reload()` afterwards - so the Mapping tab
keeps showing "The mapping could not be loaded." (`task-mapping-error`, its `Add field` button
disabled because no Sorento targets were loaded) until the page is refreshed. Plan 22 S4's "Add
entity" flow has had this since it shipped; this plan makes the path the DEFAULT for every DB
company, so it is worth a backlog item (candidate: `onSave` → `mapping.reload()` after a
successful task save when `mapping.notFound`). The spec does what an operator does (refreshes
when that alert is showing) and documents the gap in a comment. The new
`autocount-db-company.spec.ts` never opens the Mapping tab, so it was unaffected.

- **Residue note**: running the rig created `ETL Demo Co` + a `sql_database` connection in the
  `default` tenant and the `public.etl_demo_*` tables on the shared dev Postgres. That is the
  rig's designed, documented state (plan 22), left in place.

## DoD gate (PRINCIPLES.md)

1. **Mock swapped to real.** `service_frontend/services/autocount-service.ts:349` -
   `export const autocountService: AutocountService = realAutocountService;` - and the E2E above
   ran the whole journey against the real backend with real Postgres rows in the preview.
2. **Backfill.** No new columns on this plan (`sourceKind` is derived at read time). The one
   migration on the branch (`conn_erp_llm_s501`, the `uq_connection_tenant_type` carve-out) is
   applied on the live DB (`alembic_version` = `conn_erp_llm_s501`). Live derivation check:
   product-created companies report `api`; the single `db` row is plan 22's ORM-built dev fixture
   (finding above).
3. **No new permission.** `git diff main -- service_backend/modules/autocount/permissions/permissions.csv
   service_backend/app/permissions/permissions.csv` = empty; create rides
   `autocount.companies.manage`, exercised live by the tenant admin.
4. **375px + 1280px verified** - section above.
5. **Fresh build, correct ports.** Prod build rebuilt from scratch for this run; :3002/:8002 owned
   by this worktree (the brief's sanctioned deviation from :3001/:8001, which belong to the main
   checkout's `main` servers and were not touched). Both stopped after the run.

## Deferred / backlog

Already registered by the plan: **BL-SS-080** (AutoCount SQL presets in the task editor),
**BL-SS-081** (attach a second, API connection to a DB company), **BL-SS-082** (migration 0006
queries the live ORM model). New from this report, not yet backlogged: the task editor's Mapping
tab stays on its pre-birth 404 state after the first query save births the row (plan 22 S4 gap,
product code - see the regression section; one `mapping.reload()` after a successful save).

## Review follow-up (2026-09-04, after the S3 code review)

Two findings applied on this branch, small and surgical; no backend change.

1. **SHOULD-FIX - a fresh DB-company task editor was dirty on mount.** `query-tab.tsx` patched
   `config.connectionId` to the locked id in a `useEffect`, but the backend's default draft for a
   never-configured entity carries `connectionId: null` (`etl_service.default_source_config`), so
   `configDirty` was already true in read mode: Edit -> Cancel asked "Discard changes?" on an
   untouched editor, Discard reset to the null baseline and the effect re-dirtied it (perpetual),
   and `beforeunload` armed the moment Edit was clicked. **Fix (one place):** `task-editor-view.tsx`
   now seeds the locked connection into the BASELINE (`connectionId: saved.connectionId ??
   lockedConnection.id`) that feeds both the `setConfig` seed and `baselineKey`; the `useEffect` in
   `query-tab.tsx` is deleted. **Tests:** new
   `task-editor-view.locked-connection.test.tsx` (4 cases, renders the REAL `ResourceForm` shell so
   the Edit/Cancel/dirty-guard path is production code; includes a control that a real edit DOES
   raise the dialog, and an API-company case that nothing is seeded); the two effect-specific
   `query-tab.test.tsx` cases were replaced by one pin that the tab never patches on mount. The
   Edit -> Cancel case was verified to fail against the pre-fix code (git-stash mutation check)
   and pass after.
2. **DoD gate item 5 (375px) - E2E assertions widened.** `autocount-db-company.spec.ts` now
   asserts no horizontal page scroll at 375×812 on the Connect-company form (AC-01-15) and on the
   task editor Query tab (AC-01-21) in addition to the Entities tab, each followed by a restore to
   1280×900. Real clicks only; no new `page.goto`.

**Verification (isolated stack, headless only):** worktree backend `.venv/bin/uvicorn ... --port
8002`; frontend `rm -rf .next && npm run build` with `NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8002`
baked in, then `next start -p 3002` (port ownership confirmed via `lsof`, cwd = this worktree; the
main checkout's :3001/:8001 untouched). Same temporary, uncommitted rig as S3
(`playwright.wt3002.tmp.config.ts` + a `sed 8001->8002` copy of `autocount-db-etl.spec.ts` under
`e2e-wt3002-tmp/`), both deleted before commit.

- `npx vitest run`: **176 files, 1484 tests, all passing**.
- `npx eslint` on every changed file: clean; no em/en dashes.
- `e2e/autocount-db-company.spec.ts`: **1/1 passing**, 2 consecutive runs (8.9s, 8.4s), tenant
  purged after each.
- `e2e/autocount-db-etl.spec.ts` (touches the same task editor): **2/2 passing** (AC-22-31 12.0s,
  AC-22-32 4.1s).
