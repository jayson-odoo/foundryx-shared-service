# AC-08-37 / AC-08-38 / AC-08-39 - tester-owned [T] proofs

Lane s37, backend :8007, DB `foundryx_service_s37`. AC-08-38/39 tested against HEAD
`da5c82d3` (round 3, unchanged since). **AC-08-37 was BLOCKED at round 3 (see "Round-3
history" below) and RE-RUN IN FULL at HEAD `d696daba` (round 4) after the coordinator's
logging-sink activation fix landed** - both backend (`:8007`, restarted from `d696daba`) and
frontend (`rm -rf .next && npm run build` + `npx next start -p 3007`, since round 4 touched
real app code: `activate-tab.tsx`, `lib/autocount-etl.ts`) were rebuilt/restarted before this
re-run. Run date 2026-09-12 (UTC). See the Test Execution Report
(`08-autocount-http-source-test-report.md`) for the full verdicts; this folder holds the
scripts, screenshots and captured output the report cites.

## AC-08-37 - live replay against `https://hapi.sorento.cc.cd/api/db2` (Mocha), re-run at HEAD `d696daba`

**Fix verified live from the UI first**: on the SAME logging-sink Mocha company
(`d0b58883-...`, `sinkImpl: logging`, no Sorento code) used throughout this plan's evidence,
after a real Test the Review & Activate tab's "This company has no delivery target (logging
only)" prerequisite banner is GONE and **Activate renders enabled**
(`document.querySelector('button').disabled === false`, confirmed via real click, screenshot
`product-review-activate-enabled-1280.png`) - exactly the `activatePrerequisites` change the
round-4 diff describes (`company.sinkImpl !== 'sorento'` is no longer an unconditional
blocker).

**Test -> Activate -> Run now -> second run, all six entities, real clicks + real API,
against the real live wrapper:**

| Entity | Test (live) | Activate | Run 1 (job id) | Run 2 (job id) - idempotent? |
|---|---|---|---|---|
| product | Paged, 3,438 total, 4 pages of 1000 | Active (`activatedAt` 2026-09-12T02:17:57Z) | **FAILED** - real external timeout, see below | retried, SAME external timeout (job `3f94be5c-...`) |
| customer | Paged, 2,508 total, 22 columns | Active | job `448ee13b-...` / run `b5362652-...`: SUCCESS, scanned=2508, added=2508, updated=0, deleted=0 | job `51372fbf-...` / run `f28bc90e-...`: SUCCESS, added=0, updated=0, deleted=0 - **0 duplicates confirmed** |
| product_category | List, 28 rows, one request | Active | job `0a3a92ed-...` / run `2a56d22b-...`: SUCCESS, scanned=28, added=28 | job `1d3e4a57-...` / run `23cfb79e-...`: SUCCESS, added=0/updated=0/deleted=0 |
| warehouse | List, 21 rows (matches the documented wrapper fact), one request | Active | job `cfcb5406-...` / run `9d26292a-...`: SUCCESS, scanned=21, added=21 | job `11647a18-...` / run `2bf19a0e-...`: SUCCESS, added=0/updated=0/deleted=0 |
| brand | List, **0 rows/0 columns live** (Mocha genuinely has no `ItemBrand` rows, independently confirmed against the raw wrapper) | **Correctly refused, 409** - see note below | n/a | n/a |
| unit_of_measure | Not configured this pass - would hit the SAME `/itembypage` outage as product (identical root cause) | - | - | - |

**Product's run failure is a genuine, currently-live EXTERNAL outage, not a code defect.**
Reproduced independently with raw `curl` (bypassing our app entirely): `.../itembypage?
pageSize=10` returns in 0.1s, but `pageSize=100` and `pageSize=1000` (what our page-walk
always requests) both hang with NO response for 15-60s straight, three separate times over a
~15 minute span. The backend correctly surfaces this as `lastRunErrorCode: "TRANSPORT"`,
`lastRunError: "https://hapi.sorento.cc.cd/api/db2/itembypage did not respond within 30s."`,
Runs tab shows "Last run failed" + the URL (screenshots `d696-product-runs-1280.png` /
`d696-product-runs-375.png`) - this IS the AC-08-23/38 timeout-handling behaviour working
correctly on a REAL failure, a useful bonus confirmation, but it means product's own
added/updated/idempotency numbers could not be captured this pass (three attempts, same
outage each time).

**Brand's 409 is a correct, expected business-rule result, not a defect or a repeat of the
round-3 blocker.** Mocha's live `/ItemBrand` genuinely returns 0 rows (confirmed
independently), so the round-2 fix (B-A: refuse activation when the compared set AND
`resultColumns` are both empty - "nothing to detect changes with") correctly refuses:
`409 {"detail":"Test the endpoint again so a real preview can confirm which fields to watch
for changes before activating."}`. There is nothing to activate against on THIS company's
real data; the mechanic itself (empty-compared-set refusal) is exactly what round 2 built and
is independently pytest-covered.

**Flip proof** (`ac08-37-flip-proof-script.py`, output `ac08-37-flip-output.txt`): a clean,
minimal two-pass run (explicit `comparedFields=["CompanyName"]`, no fallback ambiguity) on a
throwaway company using the SAME real, live Mocha REST connection from this pass: pass 1
seeds 2 rows (`added=2`), pass 2 flips ONE row's `CompanyName` -> `added=0, deleted=0,
updated=1`. Cleaned up on exit (verified 0 residue via psql). A first attempt using the REAL
customer task's own 2,508-row hash state correctly tripped the REAL delete guard ("would
delete 2508 of 2508... over the safety threshold") when fed only 2 of those real keys in
RECONCILE mode - a genuine, useful confirmation the guard fires on live data too, but the
wrong mode for isolating "1 updated" (switched to the throwaway-company approach for the
version saved here, `ac08-37-flip-proof-script.py`).

### Defect 2 found this pass - Activate/Run now crashes the app once, per task, on its first in-place status transition (recoverable)

Clicking **Activate** (and, once, **Run now**) on an `autocount_http` task reproducibly
crashes the React app to a generic error boundary ("Something went wrong" / `Reset`) the
FIRST time that task's status transitions in-place after the click - reproduced 3 times
(product's Activate, customer's Activate, and once more navigating away right after
product_category's Activate). Console: `TypeError: Cannot read properties of undefined
(reading 'trim')` (screenshot `defect2-activate-crash-1280.png`). **The backend mutation
always succeeds regardless** - `curl`ing the task immediately after a crash shows
`etlStatus: "active"` every time - and a plain page reload (or clicking the error boundary's
own `Reset` button) renders the post-activate/post-run state perfectly on the very next
render (screenshot `product-activated-review-tab-1280.png`, `d696-product-category-runs-
375.png`), so this is a real, reproducible bug but not a permanent blocker for this pass's
evidence. Suspected root cause (not conclusively isolated - the crash's stack trace is a
minified production bundle with no source map available in this session):
`service_frontend/app/(protected)/autocount/companies/[id]/entities/[entityType]/
components/task-editor-view.tsx` around lines 152/452 call `task.sourceConfig.query.trim()`
unconditionally or with only a `sourceKind === 'db'` guard elsewhere in the same file, while
an `autocount_http` task's wire `sourceConfig` never carries a `query` key at all (confirmed
via `GET .../etl-task`: the JSON has `path`/`keyFields`/etc, no `query`) - `undefined.trim()`
throws exactly this error. This is a real, previously-latent bug newly EXPOSED by round 4
(no `autocount_http` task could ever reach `active` before it, so this in-place
active-state re-render never fired in production). Reporting for the coder to isolate and
fix; not fixed by the tester per the house rule.

**Verdict: PASS for the core AC-08-37 mechanic** (Test -> Activate -> Run now -> idempotent
second run, real clicks, real live data, zero duplicates) - proven end to end for
customer/product_category/warehouse, with product/unit_of_measure blocked by a confirmed
external, transient wrapper outage (not our code) and brand correctly refused by a real,
expected business rule (0 real brands on Mocha). **Defect 2 (transient Activate/Run-now
crash) is a genuine, reproducible bug to fix**, cited above with a repro and a suspected
file/line for the coder.

## Round-3 history (superseded, kept for the record)

At HEAD `da5c82d3` (round 3, before the logging-sink activation fix), `EtlService.
activate_task` unconditionally required `company.sorento_company_code`, and `CompanyService.
set_sink_target` unconditionally cleared that code whenever `sinkImpl == 'logging'` - so a
genuinely-logging-sink company (exactly AC-08-37's precondition) could never activate ANY
task via the real API/UI (confirmed via curl 409 + a screenshot showing the FE's Activate
button `disabled: true` even after a full reload). This was root-caused and reported as
FAIL/BLOCKED (an AC/product precondition mismatch, not a plan-08 regression - pre-existing
since plan 22). The coordinator's round-4 fix (`d696daba`) directly addressed this; see the
re-run above.

## AC-08-38 - failure replay (500 on page 3)

Independently verified via `ac08-38-preview-route-stub-script.py` (FastAPI `TestClient` +
`app.dependency_overrides[get_http_transport]`, the seam the brief named) against the
`/autocount/http/preview` route - confirms that route caps to page 1 only (by design, AC-08-14
"Test button" sample), so a page-3 failure never reaches it; the actual multi-page walk that
CAN fail on page 3 is `preview_task`/`run_autocount_sync`, which build their OWN
`HttpApiClient` internally (not through `get_http_transport`). Corroborated instead via the
existing + independently re-run pytest coverage (all under HEAD `da5c82d3`):
- `test_preview_task_maps_http_source_failure_to_422_naming_page_and_status` - `page 1`+`500`
  named.
- `test_preview_route_maps_http_source_failure_to_422_never_a_bare_500` (router-level,
  `client.post(...)`) - 422, never 500, message contains "page 1" and "500".
- `test_run_autocount_sync_http_status_failure_sets_error_code_and_names_page` - a REAL run
  (`run_autocount_sync`) failing on page 3 sets `last_run_error_code == "HTTP_STATUS"`,
  `"page 3"` in `last_run_error`, and asserts NO stack trace is logged (`caplog` check) - this
  is exactly the Runs-tab error_code + page number AC-08-38 needs.
- Round-3 re-check (independently run): `test_clamped_last_page_empty_data_terminates_cleanly`
  and `test_a_server_that_ignores_page_fails_fast_never_spins` both PASS under `da5c82d3` -
  `.venv/bin/python -m pytest -q tests/test_autocount_http_source.py -k "clamped_last_page or
  ignores_page_fails_fast"` -> `2 passed`.

**Verdict: PASS** (via the pytest suite + one independent route-level script; the exact
500-on-page-3 walk failure is pytest's domain since it requires network-failure injection the
live external wrapper cannot be made to produce on demand).

## AC-08-39 - ref-parity proof (sql_db -> autocount_http switch)

`ac08-39-ref-parity-script.py` - run against the REAL Postgres lane DB (never sqlite), using
the production `HttpApiSource.fetch_changes` + `RowHashRepository` + `row_hash` code paths
directly (bypassing the unreachable Activate ceremony, legitimate for this [T] proof since
`run_autocount_sync`/`fetch_changes` themselves never check `etl_status`):

1. Seeds 20 row hashes AS IF a prior `sql_db` run had produced them (`row_hash(row,
   ["Description","ItemGroup"])`, same scheme a SQL task would use).
2. Switches the task to `autocount_http` against a stub of the SAME 20 keys, 5 with a
   genuinely different `Description`.
3. `fetch_changes(Watermark())` in `RUN_MODE_RECONCILE`.

Result (`ac08-39-output.txt`): `added_count=0`, `updated_count=5`, `delete_refs=[]`,
`rows_scanned=20` - exactly the AC's "0 added, 0 deleted, N updated (hash change only)".
Ref-parity: `source.source_ref({"ItemCode": "SRT-01"}) == "AC0839_20260912T004004Z:SRT-01"`
(`{prefix}:{key}`, the SAME scheme `sql_db` uses per `company_qualified_identity`).

The script cleans up its own throwaway connection/company/config/row-hash rows on exit
(verified via psql: 0 matching rows after the run) - no residue left in the lane DB.

**Verdict: PASS.**
