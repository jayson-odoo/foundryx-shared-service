# 08 - AutoCount open REST API source (multi-company, per-entity API / Database) - Test Execution Report

Keyed to `08-autocount-http-source-acceptance-criteria.md` (AC-08-01..40). Executed 2026-09-12
on branch `sprint-5/08-autocount-http-source`, worktree `.claude/worktrees/s37`. Lane DB
`foundryx_service_s37`, backend `:8007`, frontend `:3007`.

Backend was tested across THREE HEADs as review-round fix commits landed mid-pass (coordinator
instruction); every AC-by-AC verdict below states the HEAD it was last verified against, and
every backend re-check the coordinator asked for was independently re-run:

- `1181e5df` - S5 close (Source tab save gate, brand contract banner). Initial pytest/vitest
  baseline + the AC-08-11/AC-08-21 agent-browser evidence runs.
- `69ca640f` - review round 2 (B-A empty-compared-set 422, B-B HttpSourceError->422 never 500,
  SF-1..5, `process-lessons.md` AutoCount section added).
- `da5c82d3` - review round 3 (activate-gate message now 409 with the real reason, page-guard
  reorder so a clamped-last-page-with-empty-Data terminates cleanly, brand-gate memo key fix).
  **Final HEAD; the report's PASS/FAIL verdicts and suite counts below are all as of `da5c82d3`
  unless a line says otherwise.**

Backend restarted from HEAD after each fix commit (`kill` only the pid whose `cwd` was
`s37/service_backend`, confirmed via `lsof` before every restart - never a bare `pkill`).
Frontend was NOT rebuilt between commits: `git show <sha> --stat` for both fix commits touched
ONLY `.test.tsx`/`.ts` test files under `service_frontend/`, zero app code, so the `.next`
build already made from `1181e5df` stayed valid and current throughout.

## Environment

- Backend: `.venv/bin/python -m uvicorn app.main:app --port 8007` from `service_backend/`,
  native Postgres `foundryx_service_s37`.
- Frontend: `rm -rf .next && npm run build` then `npx next start -p 3007` (never `npm start`,
  which pins 3001), from a clean rebuild against `1181e5df` (see above - still current at
  `da5c82d3`).
- Browser verification: `agent-browser --session s37-tester`, headless, real sidebar clicks
  from `/`, screenshots at ~375px and ~1280px. No Playwright anywhere in this pass.
- Unit/integration: `.venv/bin/python -m pytest -q` (native Postgres via the lane's own
  `DATABASE_URL`, NOT in-memory SQLite - this module's tests use the real dialect throughout);
  `npx vitest run <files>` (jsdom, `vitest.config.mts`), never the whole-repo suite.
- S1 mock evidence (`08-evidence/s1-mock/`) already exists from the frontend-first phase and is
  CITED, not redone (per the tester brief).
- **Tooling note (read before the agent-browser evidence dirs):** this session's headless
  Chrome did not register plain CDP mouse click/down/up dispatch as a "real" pointer event for
  several Radix-based controls (sidebar accordion triggers, DropdownMenu items,
  RadioGroup/ToggleGroup items, tab triggers) - the click silently did nothing even though
  `elementFromPoint` resolved the correct element. `element.click()` (a real DOM method,
  dispatching the SAME synthetic `click` event through the actual React `onClick` handlers)
  worked reliably everywhere CDP's mouse sequence did not, and was used throughout - it still
  drives the real component tree and the real router, never a URL shortcut, so "simulate real
  clicks, never navigate by URL" is satisfied. Flagged to the parent agent as an environment/
  tooling quirk, not a product defect (plain buttons/links/`<a>` navigation all worked with
  BOTH methods; only click-open-a-portal controls needed the fallback).

## Suite totals (final, at `da5c82d3`)

- Backend, full `tests/test_autocount_*.py` glob (run in full TWICE - once at `1181e5df`,
  once at `da5c82d3` per the coordinator's correction to re-run the whole glob, not a
  shortlist): **1360 passed, 1 failed** (523.89s at `da5c82d3`; 1359 passed/1 failed at
  `69ca640f`; 1347 passed/1 failed at `1181e5df` - the failure count is CONSTANT across all
  three HEADs, see Defect 1 below - it is unrelated to any of the three fix commits).
- Backend, the coordinator's named HTTP-source file set at `da5c82d3`:
  `tests/test_autocount_http_*.py tests/test_autocount_open_company.py
  tests/test_autocount_brand.py tests/test_autocount_entity_parity.py
  tests/test_autocount_reconcile_push.py` = **129 passed, 0 failed** (69.28s). Same set at
  `69ca640f` (before `test_autocount_reconcile_push.py` was added to the list) = **114 passed,
  0 failed** (60.59s), matching the coder's own reported count for that commit.
- Backend, targeted re-checks of the round-3 fix (independently re-run, not just cited):
  `pytest -q tests/test_autocount_http_source.py -k "clamped_last_page or
  ignores_page_fails_fast"` -> **2 passed**.
- Frontend, scoped vitest (33 files covering every AutoCount/connection/column-picker
  surface touched by this plan's diff vs `1028bda2`, never the whole-repo suite): **545
  passed, 0 failed** (5 "Unhandled Rejection" `URLSearchParams`/undici console noise entries
  from `task-editor-view.*.test.tsx` files not in this run's assertions - pre-existing mock
  teardown timing, all of those files' own tests still pass, not filed as a new defect; the
  round-3 fix commit's own diff (`19 test_autocount_http_lifecycle.py` lines,
  `1 test-helpers.ts` new file) specifically targeted this exact noise for other files, per its
  commit message).
- Frontend `npx eslint` on the diff (`git diff --name-only --diff-filter=d 1028bda2 -- .`,
  44 files): **0 errors**, 2 pre-existing `jsx-a11y` warnings on
  `use-entities-list-config.tsx`'s row action-menu wrapper `<div onClick=...>` - the SAME
  pattern Terminology/Connections/Workflows list configs already use (the file's own comment
  says so); not a new hard-fail.
- `rm -rf .next && npm run build`: clean, exit 0. Widespread pre-existing `jsx-a11y` warnings
  across unrelated files (not this plan's diff) - not new, not blocking.

## Results by AC id

| ID | Tag | Status | Evidence |
|----|-----|--------|----------|
| AC-08-01 | BE | PASS | Live at `1181e5df`+: Settings -> Integrations -> Connect -> Provider "AutoCount" -> `Auth` select renders exactly `"Basic auth (AppId + user + password)"` / `"No auth"`, no default selected. `tests/test_autocount_http_provider.py` (in the 129-passed run). |
| AC-08-02 | BE | PASS | Live: "No auth" + `https://hapi.sorento.cc.cd/api/db2` -> row Action "Test connection" -> toast **"Reachable - 21 row(s) returned from /location."** (real network call). `test_autocount_http_provider.py`. |
| AC-08-03 | BE | PASS | `test_autocount_http_provider.py` (base-URL scheme/trailing-slash rules), in the 129-passed run. |
| AC-08-04 | FE | PASS | Live: picking "No auth" hid AppId/User ID/Password instantly; picking "Basic auth" would restore them (not re-toggled live, but `connection-schema.test.ts` + `connection-form-fields.test.tsx` cover the round trip, both passing in the 545). |
| AC-08-05 | T | PASS | `documentation/engineering/integrations-email.md` line 8 documents `showWhen` next to `defaultsFrom` as a `ProviderField` key, naming this plan's `auth` select as the example. |
| AC-08-06 | BE | PASS | Live: Connect company -> API -> the no-auth connection -> Create -> company detail shows Integration "API (no auth)", Status Active, "discover company" activity implied by successful creation. `test_autocount_open_company.py`. |
| AC-08-07 | BE | PASS | Live: prefix pre-filled `MOCHA_REST_20260912T004004Z` from the connection label, editable, unique (a SECOND company on the SAME connection was correctly refused - the picker excluded the already-bound connection entirely rather than letting a duplicate reach save). `test_autocount_open_company.py` (blank/format/409/ignored-for-vendor cases). |
| AC-08-08 | BE | PASS | Live: `sourceKind` surfaced as "API (no auth)" (not "API" or "Database"); `test_autocount_open_company.py` (`CompanyNotApiBacked`, `update_entity_config` 422, GRN 422 on an open company). |
| AC-08-09 | FE | PASS | Live: picker showed exactly the ONE unbound connection with badge "(No auth)"; reference-prefix field appeared with the exact helper text `"Prefixes every record reference sent to the consumer. Cannot be changed later."`; Create disabled until valid (not separately re-triggered live, but `connect-company-view.test.tsx` covers the disabled-state matrix, passing). |
| AC-08-10 | FE | PASS | Live: company detail Integration row read "API (no auth)"; `company-detail-view.test.tsx` covers the `edit-lookback`/`change-source`/GRN-hidden predicate for `http`, passing. |
| AC-08-11 | E2E | PASS | `08-evidence/open-company/README.md` + screenshots `00`-`04` (1280 and 375). Real connection created + tested live, real company created, real "API (no auth)" badge. |
| AC-08-12 | BE | PASS | `test_autocount_http_task_config.py` (`autocount_http` accepted on open/DB/vendor companies for the six HTTP entities, 422 naming the entity for GRN/supplier/sales_agent/SO/PO/SPO) - in the 129-passed run. |
| AC-08-13 | BE | PASS | `test_autocount_http_task_config.py` (connectionId must be an open `autocount` connection, path rules, `distinctOf` requires `keyFields == ["value"]`) PLUS live on a real DB company (`08-evidence/sorento-mixed/`): toggling to API showed BOTH tenant open connections FREE, proving the DB-lock narrows to `sql_db` only. |
| AC-08-14 | BE | PASS, RE-VERIFIED at `da5c82d3` | `POST /autocount/http/preview` live-verified for all six entities against the real wrapper (see `08-evidence/live-replay-T/README.md` table: product 3,438/paged, customer 2,508/paged, warehouse 12 cols/list, product_category 4 cols/list (28 rows), brand 0 rows/list, unit_of_measure distinct UNIT/DZ/SET). Round-3 re-check: activating a task whose preview returned 0 rows (empty `comparedFields` AND empty `resultColumns`) is now a **409** (was 422 before round 2/3) with the exact message `"Test the endpoint again so a real preview can confirm which fields to watch for changes before activating."` - reproduced live via curl on the `brand` task. |
| AC-08-15 | BE | PASS | Live: the Source tab's connection picker showed both auths (`Mocha REST 20260912T004004Z (No auth)` selectable, `Mocha REST (Basic auth capable but not offered for non-vendor entities)` correctly excluded where not applicable). `test_autocount_http_task_config.py`. |
| AC-08-16 | BE | PASS | Live: Product's Mapping tab matched the AC's table byte-for-byte (`ItemCode->Code, Description->Name, Desc2->Description, ItemGroup->Category code, ItemBrand->Brand code, BaseUOM->Uom code, IsActive->Is active, Discontinued->Is discontinued (Provenance/not delivered)`). `test_autocount_http_task_config.py` for the other five entities' presets. |
| AC-08-17 | BE | PASS | `tests/test_autocount_entity_parity.py` (in the 129-passed run) - `HTTP_PRESETS.keys() == HTTP_ENTITY_TYPES`, frontend `AC_HTTP_ENTITY_TYPES` parity, every preset field exists on its canonical class. |
| AC-08-18 | FE | PASS | Live: "Add entity" offered exactly the six HTTP entities on the open Mocha company. `autocount-meta.test.ts` (9 tests, passing) pins `AC_HTTP_ENTITY_TYPES`/`entitiesForSourceKind('http')`; `entity-source-dialog.tsx` and `AC_SOURCE_IMPL_OPTIONS` are confirmed deleted (`git show 1028bda2..HEAD --stat` shows `entity-source-dialog.tsx` / `.test.tsx` both removed, `-119`/`-99` lines). |
| AC-08-19 | FE | PASS | Live, extensively: Mocha Product/Brand/UOM tasks (API-only, locked connection) AND the substitute Sorento DB-company `product_category` task (Database default, real schema tree, toggle to a FREE API picker, shared `ColumnPickers`). `source-tab.test.tsx` (286 lines of new/changed assertions) passing. |
| AC-08-20 | FE | PASS | Live: Save disabled until Test succeeded after the connection/path was set (never independently defeated); dirty-guard AlertDialog covered by `task-editor-view.locked-connection.test.tsx`; no-connection/loading/error states covered by `source-tab.test.tsx` + `task-editor-view.http-save-gate.test.tsx`, all passing. |
| AC-08-21 | E2E | PASS | `08-evidence/http-task/README.md` + screenshots `01`-`09` (1280 and 375). Product (paged, 3,438 real total, saved, preset mapping verbatim, born "Open API") and Unit of measure (`distinctOf`, real UNIT/DZ/SET) fully proven; Brand's live total is genuinely 0 (verified independently against the raw wrapper - not a defect). |
| AC-08-22 | BE | PASS | `tests/test_autocount_http_source.py` (26 tests: page walk, echoed-size-trusted, page-past-end, dedup-with-warning, `distinctOf` projection, `rows_scanned`) - in the 129-passed run. Live corroboration: product/UOM's "N pages of 1000" badges matched the echoed `TotalPages` exactly. |
| AC-08-23 | BE | PASS, RE-VERIFIED at `da5c82d3` | `test_page_error_fails_run_and_touches_nothing`, `test_timeout_fails_the_run`, `test_non_json_body_fails_the_run`, `test_envelope_shape_change_mid_walk_fails` (all in the 129-passed run). Round-3 re-check independently re-run: `test_clamped_last_page_empty_data_terminates_cleanly` + `test_a_server_that_ignores_page_fails_fast_never_spins` -> **2 passed** (`pytest -k "clamped_last_page or ignores_page_fails_fast"`). |
| AC-08-24 | BE | PASS | `tests/test_autocount_http_source.py` (`MAX_EXTRACT_ROWS` shared cap, `drain_activity` one `CallRecord` per page) - in the 129-passed run. |
| AC-08-25 | BE | PASS | `tests/test_autocount_http_lifecycle.py` + `tests/test_autocount_reconcile_push.py` (manual/incremental/reconcile parity with `sql_db`) - in the 129-passed run. Live-equivalent proof: `08-evidence/live-replay-T/ac08-39-ref-parity-script.py` runs a REAL reconcile pass against the real Postgres lane DB. |
| AC-08-26 | BE | PASS | `tests/test_autocount_http_source.py` (`IsActive == "F"` upserts, never a delete intent) - in the 129-passed run. |
| AC-08-27 | BE | PASS | `test_ref_company_qualified_same_scheme_as_sql`, `test_multi_key_joined_with_pipe` PLUS my own independent script (`08-evidence/live-replay-T/ac08-39-ref-parity-script.py`): `source_ref({"ItemCode":"SRT-01"}) == "AC0839_20260912T004004Z:SRT-01"` against the REAL Postgres lane DB. |
| AC-08-28 | BE | PASS | Live: the substitute Sorento DB company's `product_category` task switched `sql_db` (Database default) -> `autocount_http` (API toggle) and required an explicit Save, landing `draft` (its first save); `tests/test_autocount_http_lifecycle.py` (AC-08-28 block) proves the ACTIVE-task demotion-to-draft case explicitly. |
| AC-08-29 | BE | PASS | `tests/test_autocount_scheduler.py` (in the full 1360-passed glob; `autocount_http` tasks selected by the same due-query as `sql_db`, one sweep enqueues both). |
| AC-08-30 | BE | PASS | `tests/test_autocount_http_lifecycle.py` (round-trip, no-SQL-engine-for-HTTP spy, `repush_task` widened guard) - in the 129-passed run. |
| AC-08-31 | BE | PASS | `tests/test_autocount_brand.py` (in the 129-passed run: `ENTITY_BRAND`, `CanonicalBrand` code<=50/name<=150, registered in `ENTITY_PROFILES`/`HTTP_ENTITY_TYPES`/`AC_SQL_DB_ENTITY_TYPES`). |
| AC-08-32 | BE | PASS | `tests/test_autocount_brand.py` (`sinks_sorento._ENTITY_PATH["brand"] = "brands"`, `product.brand_code` dependency ordering, logging-sink no-op). |
| AC-08-33 | BE | PASS | `tests/test_autocount_brand.py` (contract-version gate, `>= 2.3` AND `"brands"` in entities); live: the S1 mock evidence + this plan's own Review & Activate banner text confirmed unchanged in the real router response shape (`brandContractGate` field present on the task view - see Defect 1 below for the ONE stale test this field broke). |
| AC-08-34 | T | PASS | Plan `08-autocount-http-source.md` Appendix A delivered to the `autocount` peer session; the peer's corrections are recorded IN the plan itself, dated 2026-09-12 ("Sorento-side status 2026-09-12: plan + UAC drafted in sorento_crm... awaiting the OWNER's approval there before code" + the numbered "peer correction 2026-09-12" on adoption needing no code) - this IS the round-trip acknowledgement the AC asks for (a reply with corrective facts, not a rubber-stamp). |
| AC-08-35 | BE | PASS | Existing `SorentoSink` 429/`Retry-After` handling, unchanged by this plan per the plan's own text; covered by the pre-existing push-chunk test suite (`test_autocount_push_marks_per_chunk.py`, in the full glob). |
| AC-08-36 | E2E | **PARTIAL / DEFERRED** | `08-evidence/sorento-mixed/README.md` - see the environment-gap note there: no real `AED_SORENTO`/MSSQL tunnel is reachable from this lane (`nc -zv localhost 59773` refused; no `ac_company` row for it in `foundryx_service_s37`). The NEW mechanic the AC exists to prove (DB company defaults to Database with a real schema tree, toggles to a FREE API connection picker, Test shows the real page-count badge, Save persists the switch) was fully verified live on a substitute (but genuinely real, currently-running) SQL Database connection + the real Mocha wrapper. The specific "existing SQL PO task's Runs tab stays unchanged" sub-clause could not be checked (no pre-existing SQL task exists to compare, and typing into the CodeMirror SQL editor did not register via this session's `agent-browser` tooling - see the README for the exact methods tried). |
| AC-08-37 | T | **FAIL / BLOCKED (root-caused, not a code defect under this plan)** | `08-evidence/live-replay-T/README.md`. Test succeeded live for all six entities against the real wrapper. Activate -> Run now is UNREACHABLE for a genuinely-`logging`-sink company: `CompanyService.set_sink_target` (`services/company_service.py`) unconditionally clears `sorento_company_code` when `sinkImpl == 'logging'`, and `EtlService.activate_task` (`services/etl_service.py`) unconditionally requires that code before ANY task activates - confirmed live via curl (409) AND on the frontend (`lib/autocount-etl.ts:118` `activatePrerequisites` disables the Activate button whenever `company.sinkImpl !== 'sorento'`, screenshot-verified `disabled: true` even after a full page reload). This is pre-existing since plan 22 (`80d648eb`), not introduced by sprint-5/08 - the AC's own precondition describes a state the product has never made reachable. The reconcile logic itself (what the idempotent-second-run / flip-a-field assertion is actually testing) IS proven, via the pytest suite and an independent tester script producing 0 added / 0 deleted / N updated on a real reconcile pass. |
| AC-08-38 | T | PASS | `08-evidence/live-replay-T/README.md`. `/autocount/http/preview` caps to page 1 by design (independently confirmed via a `get_http_transport`-dependency-override script - a page-3 stub never reaches it, 200 not 422). The actual multi-page walk failure IS proven via `test_preview_task_maps_http_source_failure_to_422_naming_page_and_status`, `test_preview_route_maps_http_source_failure_to_422_never_a_bare_500`, `test_run_autocount_sync_http_status_failure_sets_error_code_and_names_page` (error_code `HTTP_STATUS`, "page 3" named, NO stack trace logged) - all re-run green at `da5c82d3`. |
| AC-08-39 | T | PASS | `08-evidence/live-replay-T/ac08-39-ref-parity-script.py` + `ac08-39-output.txt`. Run against the REAL Postgres lane DB using the production `HttpApiSource.fetch_changes`/`RowHashRepository`/`row_hash` code: `added_count=0, updated_count=5, delete_refs=[], rows_scanned=20` on a `sql_db`-hashed-state -> `autocount_http` switch with 5 of 20 keys carrying a changed field. Ref-parity: `AC0839_...:SRT-01`. Script cleans up its own rows on exit (verified 0 residue via psql). |
| AC-08-40 | T | **PASS with ONE cited defect** | This report. Backend `tests/test_autocount_*.py`: 1360 passed / 1 failed (Defect 1, pre-existing across all three HEADs tested, unrelated to any round-2/3 change). Frontend vitest: 545 passed / 0 failed. Lint: 0 errors on the diff. Prod build: clean. `documentation/engineering/process-lessons.md` gains the AutoCount reference section (source-impl table, HTTP preset table, run-mode table, the `pageSize`-clamp gotcha) - added by commit `69ca640f` (SF-3), verified present. Backlog rows BL-SS-201/202/203/204/205 present; BL-SS-081 correctly marked "Superseded (sprint-5/08)". |

## Defects found this pass

**Defect 1 - `tests/test_autocount_etl_routes.py::test_get_etl_task_returns_draft_defaults_for_a_configured_entity` fails on an exact-dict `==` comparison missing the new `brandContractGate` key.**

- File/line: `service_backend/tests/test_autocount_etl_routes.py:411` (the `assert response.json()
  == {...}` block for a `customer` entity's never-configured task).
- Root cause: `EtlTaskView`/`EtlTaskResponse` gained `brandContractGate: Optional[BrandContractGate]
  = None` in this plan's S4 (`schemas.py:782`, `routers/companies.py:486`), but this ONE
  pre-existing test (in a file this plan otherwise edited, `bf553e08` "S3 fixups") was never
  updated to include `"brandContractGate": None` in its expected literal. Every OTHER test in
  the same file that reads specific keys (rather than `==` on the whole dict) is unaffected.
- Reproduced fresh, isolated: `pytest tests/test_autocount_etl_routes.py::test_get_etl_task_returns_draft_defaults_for_a_configured_entity -x` -> `AssertionError`, diff shows `Left contains 1
  more item: {'brandContractGate': None}`.
- Constant across all three HEADs tested (`1181e5df`, `69ca640f`, `da5c82d3`) - confirms it is
  NOT a regression from either review-round fix, it has been broken since S4 landed.
- This is a TEST FIXTURE fix, not a product-code fix: add `"brandContractGate": None,` to the
  expected dict at line ~436 (right after `"initialLoad": None,`). Per my brief I do not
  patch product code or test files myself - reporting for the coder to fix in a follow-up
  commit, and it should be included in the "pytest green" gate before this plan's final merge.
- This is the "one `F`" the coordinator's stray sweep saw - confirmed by test name and
  assertion; unrelated to the round-2/3 empty-compared-set / `_stamp_previewed` / HTTP-error
  changes named in the coordinator's message.

## Findings from this tester pass (not filed as defects)

1. **Radix control clicks needed `element.click()` instead of CDP mouse dispatch this
   session** (see the Environment section above). Affects tester tooling only, not the
   product; every affected control (sidebar accordion, dropdown menus, tab triggers,
   radio/toggle groups) worked correctly once clicked via the real DOM method - the
   component tree, router and permission checks all behaved exactly as a real click would
   drive them.
2. **CodeMirror SQL editor could not be typed into via this session's `agent-browser`**
   (`keyboard type`, `keyboard inserttext`, and `document.execCommand('insertText', ...)`
   after a confirmed `.focus()` all left the editor empty). This blocked completing a NEW,
   real SQL task on the substitute DB company used for AC-08-36, which is why that AC's
   "existing SQL task stays untouched" sub-clause is unverifiable this pass (see AC-08-36
   above). Not investigated further given the time budget; worth a follow-up note in
   `docs/reference/process-lessons.md`'s agent-browser section if another lane hits the same
   wall.
3. **The Database/API `RadioGroup` on a saved task's Source tab is `disabled` until "Edit" is
   clicked**, even though the SQL editor's own Test button is interactive in view mode - a
   minor asymmetry (view mode lets you re-run Test but not switch source kind), noted for
   awareness, not filed as a hard-fail (arguably correct: switching source kind is a
   structural edit, testing the CURRENT config is not).
4. Two pre-existing "Unhandled Rejection" vitest console entries (`URLSearchParams`/undici
   quirk) surfaced again in this run's scoped vitest pass - not new, all affected files' own
   tests still pass, matches the note in sprint-5/07's own test report for the same files.

## Docs / backlog verification

- `documentation/engineering/process-lessons.md` lines 64-108: AutoCount reference section
  present (source-impl table, `autocount_http` preset table, run-mode table, `pageSize`-clamp
  gotcha) - added by `69ca640f` (SF-3). AC-08-05's `showWhen` doc line confirmed at line 8 of
  `documentation/engineering/integrations-email.md`.
- `documentation/backlogs/backlog.md`: BL-SS-201 (item lookups no Sorento home), BL-SS-202
  (API-key header), BL-SS-203 (batch-2 endpoints), BL-SS-204 (server-side LastModified
  filter), BL-SS-205 (loopback/private-range denylist, added by `69ca640f` SF-4) all present
  and linked to this plan; BL-SS-081 correctly reads "Superseded (sprint-5/08)".

## Servers left running

- Backend `:8007` (uvicorn, `app.main:app`) at HEAD `da5c82d3`, cwd `s37/service_backend`.
- Frontend `:3007` (`npx next start -p 3007`) serving the `1181e5df` prod build (still current
  - no frontend app-code changes across the two fix commits).
- `agent-browser --session s37-tester` closed at the end of this pass.

## Evidence directories

- `08-evidence/s1-mock/` - existing S1 frontend-mock evidence, cited per the brief, not redone.
- `08-evidence/open-company/` - AC-08-11 (E2E), README + `00`-`04` screenshots.
- `08-evidence/http-task/` - AC-08-21 (E2E), README + `01`-`09` screenshots.
- `08-evidence/sorento-mixed/` - AC-08-36 (E2E, partial/deferred), README + `01`-`04` screenshots.
- `08-evidence/live-replay-T/` - AC-08-37/38/39 (T), README + two standalone scripts + captured
  output logs.
