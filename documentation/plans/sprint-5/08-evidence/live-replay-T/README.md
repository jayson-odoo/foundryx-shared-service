# AC-08-37 / AC-08-38 / AC-08-39 - tester-owned [T] proofs

Lane s37, backend :8007, DB `foundryx_service_s37`, tested against HEAD `da5c82d3`
(sprint-5/08 review round 3). Run date 2026-09-12 (UTC). See the Test Execution Report
(`08-autocount-http-source-test-report.md`) for the full verdicts; this folder holds the
scripts and captured output the report cites.

## AC-08-37 - live replay against `https://hapi.sorento.cc.cd/api/db2` (Mocha)

**Test succeeded live for all six entities** (real network calls, `POST
/autocount/http/preview`, no Sorento push - the Mocha company's sink stayed `logging`
throughout):

| Entity | Envelope | Total / columns |
|---|---|---|
| product | paged | 3,438 total, 12 pages (echoed) |
| customer | paged | 2,508 total, 22 columns |
| warehouse | list | 12 columns, one request |
| product_category | list | 4 columns, one request (28 rows live) |
| brand | list | 0 columns/rows (Mocha genuinely has no `ItemBrand` rows - verified independently against the raw wrapper) |
| unit_of_measure | paged (`/itembypage`, `distinctOf`) | 3,438 rows scanned, UNIT/DZ/SET distinct values |

**Activate -> Run now could NOT be completed** - root-caused, not worked around:
`EtlService.activate_task` (`modules/autocount/services/etl_service.py`) unconditionally
requires `company.sorento_company_code` to be non-blank before ANY task activates, and
`CompanyService.set_sink_target` (`modules/autocount/services/company_service.py`, the
`sink_impl == SINK_IMPL_LOGGING` branch) unconditionally CLEARS `sorento_company_code` when a
company's sink is `logging`. Net effect: a company whose sink is genuinely `logging` (no
Sorento push target - exactly what AC-08-37 asks for) can never satisfy the activate gate
through the real API/UI. Confirmed on the frontend too: `activatePrerequisites`
(`service_frontend/lib/autocount-etl.ts:118`) treats `company.sinkImpl !== 'sorento'` as a
blocking prerequisite, so the **Activate button renders `disabled`** the whole time (own
screenshot check: `document.querySelector('button').disabled === true` even after a full page
reload, right below the visible "This company has no delivery target (logging only)."
banner). This is BY DESIGN, pre-existing since plan 22 (`80d648eb`, before sprint-5/08), not a
regression introduced by this plan - the AC's own precondition ("Run now with the LOGGING
sink") describes a state the product has never made reachable. Repro via curl:

```
POST /autocount/companies/<id>/entities/brand/etl-task/activate
-> 409 {"detail":"Test the endpoint again so a real preview can confirm which fields to watch
         for changes before activating."}
```
(this is the CORRECT/expected 409 for a genuinely-never-previewed compared set, round-3 fix -
but even a task WITH a passed preview - `product`, `Preview passed 12 Sept 2026, 09:16` shown
live - hits the SEPARATE `sorento_company_code` 409:
`"Set the Sorento company code on this company before activating - every push is anchored to
it."`)

Given the ceremony is unreachable, the RECONCILE LOGIC ITSELF (what AC-08-37's idempotent
second-run / flip-a-field assertion is actually testing) is proven instead via:
- The full pytest suite (1360 passed / 1 pre-existing unrelated failure, see the report) -
  `test_reconcile_classifies_added_updated_deleted_via_row_hash`,
  `test_empty_compared_columns_falls_back_to_row_own_fields_for_hashing`,
  `test_reconcile_delete_guard_fires_on_mass_disappearance` in
  `tests/test_autocount_http_source.py`.
- `ac08-39-ref-parity-script.py` (below) - the SAME assertion AC-08-37 wants (0 added, 0
  deleted, N updated on a second pass with one field changed), run independently by the
  tester against the real Postgres lane DB using the production `HttpApiSource.fetch_changes`
  + `RowHashRepository` code path.

**Verdict: FAIL/BLOCKED for the literal "Activate -> Run now with the logging sink" scenario
- an AC/product precondition mismatch, not a code defect to fix under this plan.** The
Test-endpoint half and the reconcile-logic half are both independently proven.

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
