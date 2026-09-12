# 08 - AutoCount open REST API source (multi-company, per-entity API / Database) - Test Execution Report

Keyed to `08-autocount-http-source-acceptance-criteria.md` (AC-08-01..40). Executed 2026-09-12
on branch `sprint-5/08-autocount-http-source`, worktree `.claude/worktrees/s37`. Lane DB
`foundryx_service_s37`, backend `:8007`, frontend `:3007`.

Backend was tested across FOUR HEADs as review-round fix commits landed mid-pass (coordinator
instruction); every AC-by-AC verdict below states the HEAD it was last verified against, and
every backend re-check the coordinator asked for was independently re-run:

- `1181e5df` - S5 close (Source tab save gate, brand contract banner). Initial pytest/vitest
  baseline + the AC-08-11/AC-08-21 agent-browser evidence runs.
- `69ca640f` - review round 2 (B-A empty-compared-set 422, B-B HttpSourceError->422 never 500,
  SF-1..5, `process-lessons.md` AutoCount section added).
- `da5c82d3` - review round 3 (activate-gate message now 409 with the real reason, page-guard
  reorder so a clamped-last-page-with-empty-Data terminates cleanly, brand-gate memo key fix).
- `d696daba` - review round 4 (logging-sink activation unblocked: the anchor-code gate now
  scopes to `sink_impl == 'sorento'` only, on both the backend gate and the FE
  `activatePrerequisites` mirror; the stale `EtlTaskView` fixture - Defect 1 below - fixed).
- `3110490f` - review round 5 (Defect 2 fix: `activateEtlTask`/`pauseEtlTask`/`resumeEtlTask`/
  `runEtlTaskNow`/`previewEtlTask` now run their response through `normalizeEtlTask`, the same
  wire boundary `getEtlTask`/`updateEtlTask` already used; restored a non-blocking
  logging-sink warning on Review & Activate; `preview_task` comment reworded). **Final HEAD;
  the report's PASS/FAIL verdicts and suite counts below are all as of `3110490f` unless a
  line says otherwise.** Re-verified independently by a second tester pass (round-5 verify,
  `08-evidence/round5-verify/`), backend NOT restarted (already at `3110490f`), frontend NOT
  rebuilt (already serving a fresh `3110490f` prod build) - both confirmed via `git rev-parse
  HEAD` on the running pids' `cwd` before this pass.

Backend restarted from HEAD after each fix commit (`kill` only the pid whose `cwd` was
`s37/service_backend`, confirmed via `lsof` before every restart - never a bare `pkill`).
Frontend was NOT rebuilt between the round-2/round-3 commits (`git show <sha> --stat` for both
touched ONLY `.test.tsx`/`.ts` test files, zero app code) but WAS rebuilt for round 4
(`activate-tab.tsx`, `lib/autocount-etl.ts` changed): `rm -rf .next && npm run build` (clean)
then `npx next start -p 3007` restarted (kill only the pid whose `cwd` was
`s37/service_frontend`, confirmed via `lsof`).

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

## Suite totals (final, at `d696daba`)

- Backend, full `tests/test_autocount_*.py` glob (run in full at EVERY HEAD per the
  coordinator's correction to re-run the whole glob, not a shortlist): **1363 passed, 0
  failed** (520.07s at `d696daba` - Defect 1 fixed, confirmed); 1360 passed/1 failed at
  `da5c82d3`; 1359 passed/1 failed at `69ca640f`; 1347 passed/1 failed at `1181e5df` (Defect 1
  constant across the first three HEADs, unrelated to any of those fix commits, fixed only in
  round 4).
- Backend, the coordinator's named HTTP-source file set: at `d696daba`,
  `tests/test_autocount_http_*.py tests/test_autocount_open_company.py
  tests/test_autocount_brand.py tests/test_autocount_entity_parity.py
  tests/test_autocount_reconcile_push.py tests/test_autocount_etl_routes.py` = **158 passed, 0
  failed** (100.24s). At `da5c82d3` (before `test_autocount_etl_routes.py` was added to the
  list) = **129 passed, 0 failed** (69.28s). At `69ca640f` (before
  `test_autocount_reconcile_push.py` was added) = **114 passed, 0 failed** (60.59s), matching
  the coder's own reported count for that commit.
- Backend, targeted re-checks of the round-3 fix (independently re-run, not just cited):
  `pytest -q tests/test_autocount_http_source.py -k "clamped_last_page or
  ignores_page_fails_fast"` -> **2 passed**.
- Frontend, scoped vitest (33 files covering every AutoCount/connection/column-picker
  surface touched by this plan's diff vs `1028bda2`, never the whole-repo suite): **545
  passed, 0 failed**, re-run and confirmed still green at `d696daba` (round 4 touched
  `lib/autocount-etl.test.ts` too) - 5 "Unhandled Rejection" `URLSearchParams`/undici console
  noise entries from `task-editor-view.*.test.tsx` files not in this run's assertions -
  pre-existing mock teardown timing, all of those files' own tests still pass, not filed as a
  new defect; the round-3 fix commit's own diff (`19 test_autocount_http_lifecycle.py` lines,
  `1 test-helpers.ts` new file) specifically targeted this exact noise for other files, per its
  commit message.
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
| AC-08-14 | BE | PASS, RE-VERIFIED at `da5c82d3`, AND AGAIN at `3110490f` | `POST /autocount/http/preview` live-verified for all six entities against the real wrapper (see `08-evidence/live-replay-T/README.md` table: product 3,438/paged, customer 2,508/paged, warehouse 12 cols/list, product_category 4 cols/list (28 rows), brand 0 rows/list, unit_of_measure distinct UNIT/DZ/SET). Round-3 re-check: activating a task whose preview returned 0 rows (empty `comparedFields` AND empty `resultColumns`) is now a **409** (was 422 before round 2/3) with the exact message `"Test the endpoint again so a real preview can confirm which fields to watch for changes before activating."` - reproduced live via curl on the `brand` task. Round-5 re-verify (`08-evidence/round5-verify/README.md`): a brand-new `unit_of_measure` task's `/autocount/http/preview` (distinct-of `/itembypage`) was Tested live TWICE in the same session (before and after Save) - both preview calls succeeded and both advanced `last_preview_at` (confirmed via `psql`), matching the AC's preview contract unchanged by round 5. |
| AC-08-15 | BE | PASS | Live: the Source tab's connection picker showed both auths (`Mocha REST 20260912T004004Z (No auth)` selectable, `Mocha REST (Basic auth capable but not offered for non-vendor entities)` correctly excluded where not applicable). `test_autocount_http_task_config.py`. |
| AC-08-16 | BE | PASS | Live: Product's Mapping tab matched the AC's table byte-for-byte (`ItemCode->Code, Description->Name, Desc2->Description, ItemGroup->Category code, ItemBrand->Brand code, BaseUOM->Uom code, IsActive->Is active, Discontinued->Is discontinued (Provenance/not delivered)`). `test_autocount_http_task_config.py` for the other five entities' presets. |
| AC-08-17 | BE | PASS | `tests/test_autocount_entity_parity.py` (in the 129-passed run) - `HTTP_PRESETS.keys() == HTTP_ENTITY_TYPES`, frontend `AC_HTTP_ENTITY_TYPES` parity, every preset field exists on its canonical class. |
| AC-08-18 | FE | PASS | Live: "Add entity" offered exactly the six HTTP entities on the open Mocha company. `autocount-meta.test.ts` (9 tests, passing) pins `AC_HTTP_ENTITY_TYPES`/`entitiesForSourceKind('http')`; `entity-source-dialog.tsx` and `AC_SOURCE_IMPL_OPTIONS` are confirmed deleted (`git show 1028bda2..HEAD --stat` shows `entity-source-dialog.tsx` / `.test.tsx` both removed, `-119`/`-99` lines). |
| AC-08-19 | FE | PASS | Live, extensively: Mocha Product/Brand/UOM tasks (API-only, locked connection) AND the substitute Sorento DB-company `product_category` task (Database default, real schema tree, toggle to a FREE API picker, shared `ColumnPickers`). `source-tab.test.tsx` (286 lines of new/changed assertions) passing. |
| AC-08-20 | FE | PASS, RE-VERIFIED at `3110490f` (see the round-5 staleness probe below) | Live: Save disabled until Test succeeded after the connection/path was set (never independently defeated); dirty-guard AlertDialog covered by `task-editor-view.locked-connection.test.tsx`; no-connection/loading/error states covered by `source-tab.test.tsx` + `task-editor-view.http-save-gate.test.tsx`, all passing. **Round-5 finding (not this AC's own gate, a NEIGHBOURING one on the Review & Activate tab, recorded per the coordinator's request, not filed as a defect on this AC):** Source-tab Test -> Save -> Test again -> Review & Activate WITHOUT leaving the task editor's mounted component shows `Activate` DISABLED even though the second Test succeeded server-side (`last_preview_at` advanced, confirmed via `psql`); leaving and re-entering the SAME task (fresh mount/refetch) shows it correctly ENABLED. Screenshots `08-evidence/round5-verify/07-staleness-probe-activate-disabled-{1280,375}.png` (disabled, same mount) and `08-evidence/round5-verify/08-staleness-probe-activate-enabled-after-remount-1280.png` (enabled, fresh mount). No crash, no console error - a staleness/UX bug in the Review & Activate tab's local state, not this AC's Source-tab Save gate. Reported for the coder, not fixed by the tester. |
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
| AC-08-37 | T | **PASS at `d696daba`** (was FAIL/BLOCKED at `da5c82d3`, root-caused and fixed by round 4) | `08-evidence/live-replay-T/README.md` (full re-run section + round-3 history kept below it). Live, real clicks + real API against the real `db2` wrapper on the SAME logging-sink Mocha company throughout: Activate now renders enabled (`disabled: false`, screenshot `product-review-activate-enabled-1280.png`) after the round-4 fix scoped the anchor-code gate to `sink_impl == 'sorento'` only. Test -> Activate -> Run now -> idempotent second run proven end to end for **customer** (job `448ee13b`/`51372fbf`: 2508 added then 0/0/0), **product_category** (job `0a3a92ed`/`1d3e4a57`: 28 added then 0/0/0) and **warehouse** (job `cfcb5406`/`11647a18`: 21 added then 0/0/0, 21 matching the documented wrapper fact). **product**'s Run now hit a confirmed, currently-live EXTERNAL timeout on `/itembypage` (independently reproduced with raw `curl`: `pageSize>=100` hangs 15-60s, `pageSize=10` is instant) - `TRANSPORT` error code surfaced correctly, not a code defect. **brand** correctly 409s (0 real rows on Mocha, the round-2 empty-compared-set gate). Flip proof (`ac08-37-flip-proof-script.py`): 0 added, 0 deleted, **1 updated**. **Defect 2 found and reported** (below): Activate/Run now transiently crashes the app once per task (recoverable via Reset/reload, backend always succeeds) - a real, newly-exposed bug from round 4, cited with a repro and a suspected file/line. **Round-5 re-verify (`08-evidence/round5-verify/README.md`): Defect 2 is CLOSED at `3110490f`.** On the SAME logging-sink Mocha company's `warehouse` task (already active): Pause -> Resume -> Run now, each a real click via the SAME in-place status-transition path that crashed every time at `d696daba`, produced **zero crashes and zero console errors** (`agent-browser errors`/`console` both empty after each click, screenshots `02`-`05`); a new `ac_sync_run` row was written (`job_id 69deffb0-...`, `rows_scanned 21`, `added/updated/deleted 0`, idempotent) and the Runs tab shows it. The restored logging-sink warning (`data-testid="activate-logging-sink-warning"`, exact text `"Runs on this company are logged only - no records are delivered until a Sorento target is set."`) is visible at 1280 and 375 (`06-warehouse-review-activate-warning-*.png`) and never blocks Activate/Run now; no company's sink was switched to `sorento`. |
| AC-08-38 | T | PASS | `08-evidence/live-replay-T/README.md`. `/autocount/http/preview` caps to page 1 by design (independently confirmed via a `get_http_transport`-dependency-override script - a page-3 stub never reaches it, 200 not 422). The actual multi-page walk failure IS proven via `test_preview_task_maps_http_source_failure_to_422_naming_page_and_status`, `test_preview_route_maps_http_source_failure_to_422_never_a_bare_500`, `test_run_autocount_sync_http_status_failure_sets_error_code_and_names_page` (error_code `HTTP_STATUS`, "page 3" named, NO stack trace logged) - all re-run green at `da5c82d3`. |
| AC-08-39 | T | PASS | `08-evidence/live-replay-T/ac08-39-ref-parity-script.py` + `ac08-39-output.txt`. Run against the REAL Postgres lane DB using the production `HttpApiSource.fetch_changes`/`RowHashRepository`/`row_hash` code: `added_count=0, updated_count=5, delete_refs=[], rows_scanned=20` on a `sql_db`-hashed-state -> `autocount_http` switch with 5 of 20 keys carrying a changed field. Ref-parity: `AC0839_...:SRT-01`. Script cleans up its own rows on exit (verified 0 residue via psql). |
| AC-08-40 | T | **PASS, both prior defects resolved/recorded** | This report. Backend `tests/test_autocount_*.py` at `d696daba`: **1363 passed / 0 failed** (Defect 1 - the stale `EtlTaskView` fixture - fixed in round 4, confirmed by name and assertion). Frontend vitest: 545 passed / 0 failed, re-confirmed at `d696daba`. Lint: 0 errors on the diff. Prod build: clean (rebuilt for round 4). `documentation/engineering/process-lessons.md` gains the AutoCount reference section (source-impl table, HTTP preset table, run-mode table, the `pageSize`-clamp gotcha) - added by commit `69ca640f` (SF-3), verified present. Backlog rows BL-SS-201/202/203/204/205 present; BL-SS-081 correctly marked "Superseded (sprint-5/08)". **Re-run at `3110490f` (round-5 verify pass):** backend `tests/test_autocount_*.py` full glob **1363 passed / 0 failed** (515.58s), unchanged count from `d696daba` (round 5 touched no test file's assertions, only production code + 2 new test cases in `activate-tab.test.tsx`/`autocount-service.real.test.ts`/`autocount-etl.test.ts` which are counted in the frontend total below); frontend scoped vitest on the round-5 diff's own test files (`services/autocount-service.real.test.ts`, `lib/autocount-etl.test.ts`, `activate-tab.test.tsx`) **99 passed / 0 failed**; `npm run lint` **0 errors** (239 pre-existing `jsx-a11y` warnings on unrelated files, same class as round 4's note, not new). **Defect 2 (transient Activate/Run-now crash) is now CLOSED at `3110490f`** - re-verified live (see AC-08-37 above and `08-evidence/round5-verify/`). **One new, OPEN staleness finding recorded against AC-08-20's neighbourhood** (Review & Activate's `Activate` gate doesn't refresh within the same task-editor mount after Save + a second Test - see AC-08-20 above and Defect 3 below), found while investigating the coordinator's round-5 staleness probe request; not fixed by the tester. |

## Defects found this pass

**Defect 1 - FIXED at `d696daba`.** `tests/test_autocount_etl_routes.py::test_get_etl_task_returns_draft_defaults_for_a_configured_entity` failed on an exact-dict `==` comparison
missing the (then-new, S4) `brandContractGate` key - constant across `1181e5df`/`69ca640f`/
`da5c82d3` (1 failed each time), confirmed fixed at `d696daba` (`test_autocount_etl_routes.py`
gained `+2` lines per `git show d696daba --stat`; the full glob is 1363 passed / 0 failed at
this HEAD, and the file's own test was independently re-run to confirm). This was the "one
`F`" the coordinator's stray sweep saw. No further action needed.

**Defect 2 - FIXED at `3110490f` (round 5).** Activate/Run now transiently crashed the app on
an `autocount_http` task's first in-place status transition (recoverable via Reset/reload,
backend always unaffected) - root cause was exactly as this report's round-4 suspicion named
it: `activateEtlTask`/`pauseEtlTask`/`resumeEtlTask`/`runEtlTaskNow`/`previewEtlTask` answered
the same real-backend shape as `getEtlTask` (an `autocount_http` task's `sourceConfig` omits
the SQL-shape keys entirely, so it has no `query` field), but only `getEtlTask`/`updateEtlTask`
ran the response through `normalizeEtlTask` - the round-5 fix (`3110490f`,
`service_frontend/services/autocount-service.real.ts`) normalizes every endpoint that returns
or embeds an `AutocountEtlTask`, at the same wire boundary as the loader.

**Independently re-verified this pass** (`08-evidence/round5-verify/README.md`, backend and
frontend NOT restarted/rebuilt - both already serving `3110490f`): on the same logging-sink
Mocha company's real, already-active `warehouse` task, a live sequence of **Pause -> Resume
-> Run now** (the exact in-place status-transition path that crashed every single time at
`d696daba`) produced **zero crashes and zero console errors** across all three transitions
(`agent-browser errors`/`console` both empty after each click); the Runs tab correctly shows
the new run (`job_id 69deffb0-...`, `rows_scanned 21`, idempotent `added/updated/deleted 0`).
Screenshots `02-warehouse-paused-1280.png`, `03-warehouse-resumed-active-1280.png`,
`04-warehouse-after-run-now-1280.png`, `05-warehouse-runs-tab-new-run-{1280,375}.png`.

**Also verified: the restored logging-sink warning** (part of the same round-5 commit).
`data-testid="activate-logging-sink-warning"`, exact text `"Runs on this company are logged
only - no records are delivered until a Sorento target is set."`, visible on the Review &
Activate tab at both 1280 and 375 (`06-warehouse-review-activate-warning-{1280,375}.png`);
`Activate`/`Run now` stayed enabled throughout - the warning is correctly non-blocking. No
company's sink was switched to Sorento in this pass (Sorento pushes stay forbidden from this
lane).

**Defect 3 (OPEN, round-5) - the Review & Activate tab's `Activate` gate does not refresh
within the SAME task-editor mount after Save + a second Test; only a fresh mount picks up the
correct state.** Found while investigating a coordinator-requested staleness probe, not part
of the original round-5 fix scope.

- Repro (`08-evidence/round5-verify/README.md`, "Staleness probe" section): on a brand-new
  `autocount_http` task (`unit_of_measure` on the Mocha company, `/itembypage` `distinctOf`
  preset) - Source tab **Test** (succeeds) -> **Edit** -> **Save task** (succeeds, "Task
  saved." toast) -> **Test** again on the same still-mounted Source tab (succeeds; confirmed
  via `psql`: `last_preview_at` advanced to a new timestamp, `etl_status` still `draft`) ->
  click the **Review & Activate** tab directly, WITHOUT navigating away from the task editor
  or reloading the page: **`Activate` renders DISABLED**
  (`08-evidence/round5-verify/07-staleness-probe-activate-disabled-{1280,375}.png`) even
  though the server-side preview state is fresh and valid.
- Leaving the task editor (back to the company's Entities tab) and re-entering the SAME task
  (a fresh route mount, same `unit_of_measure` task, no new Test) shows `Activate` correctly
  **ENABLED** (`08-evidence/round5-verify/08-staleness-probe-activate-enabled-after-remount-
  1280.png`) - identical server state, only the component remount differs.
- No crash, no console error accompanies this - a pure staleness/UX bug: the gate reads a
  piece of local component state (most likely `task.lastPreviewAt`, per the coordinator's own
  suspicion of `onHttpPreviewSuccess` never reloading the task after Save) that is not
  refreshed by the Save-then-Test-again sequence within the same mount, even though the
  underlying data the gate should be reading IS fresh on the server. Reporting for the coder
  to isolate/fix; not fixed by the tester per the house rule.

- Repro: on any `autocount_http` task, after a real click on **Activate** (Review & Activate
  tab) - or once, on **Run now** - the whole app renders the generic error boundary
  ("Something went wrong" / `Reset`), console `TypeError: Cannot read properties of undefined
  (reading 'trim')`. Reproduced 3 times this pass (product's Activate, customer's Activate,
  and once navigating away right after product_category's Activate). Screenshot:
  `08-evidence/live-replay-T/defect2-activate-crash-1280.png`.
- **The backend mutation always succeeds** - `GET .../etl-task` immediately after a crash
  shows `etlStatus: "active"` every time - and clicking the error boundary's own `Reset`, or a
  plain page reload, renders the correct post-mutation state perfectly on the very next
  render (`08-evidence/live-replay-T/product-activated-review-tab-1280.png`,
  `d696-product-category-runs-375.png`). Not a permanent blocker; did not stop this pass's
  evidence collection.
- Newly EXPOSED by round 4, not introduced by it: no `autocount_http` task could ever reach
  `etl_status = 'active'` before this round's fix (the anchor-code gate blocked it
  unconditionally), so this in-place active-state re-render path never fired in this plan
  before now.
- Suspected root cause (not conclusively isolated - the crash's stack trace is a minified
  production bundle chunk with no source map in this session):
  `service_frontend/app/(protected)/autocount/companies/[id]/entities/[entityType]/
  components/task-editor-view.tsx` around lines 152 and 452 call `task.sourceConfig.query.
  trim()` - the second one (`querySaved`, in the `resourceConfig` memo) runs UNCONDITIONALLY,
  never gated on `sourceKind`/`sourceImpl` - while an `autocount_http` task's wire
  `sourceConfig` never carries a `query` key at all (confirmed via `GET .../etl-task`: only
  `path`/`keyFields`/etc.), so `task.sourceConfig.query` is `undefined` and `.trim()` throws.
  Reporting for the coder to isolate/fix; not fixed by the tester per the house rule (tester
  writes tests, never patches product or test-fixture code).

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

- Backend `:8007` (uvicorn, `app.main:app`) at HEAD `3110490f` (pid 81585, cwd
  `s37/service_backend`, NOT restarted for the round-5 verify pass - already current).
- Frontend `:3007` (`npx next start -p 3007`, pid 98460) serving a fresh `3110490f` prod build
  (NOT rebuilt for the round-5 verify pass - already current).
- `agent-browser --session s37-verify` closed at the end of the round-5 verify pass.

## Evidence directories

- `08-evidence/s1-mock/` - existing S1 frontend-mock evidence, cited per the brief, not redone.
- `08-evidence/open-company/` - AC-08-11 (E2E), README + `00`-`04` screenshots.
- `08-evidence/http-task/` - AC-08-21 (E2E), README + `01`-`09` screenshots.
- `08-evidence/sorento-mixed/` - AC-08-36 (E2E, partial/deferred), README + `01`-`04` screenshots.
- `08-evidence/live-replay-T/` - AC-08-37/38/39 (T), README (round-4 re-run + round-3 history)
  + standalone scripts + captured output logs + screenshots (Activate-enabled, the Defect 2
  crash, post-recovery Active/Runs states at 1280 and 375).
- `08-evidence/round5-verify/` - round-5 verify pass at HEAD `3110490f` (Defect 2 closure,
  the restored logging-sink warning, the AC-08-40 suite re-run, and the coordinator-requested
  staleness probe that surfaced Defect 3), README + `01`-`08` screenshots at 1280 and 375.
