# 03 - AutoCount bulk document load (paged extraction, change-only staging) - Test Execution Report

Keyed to `03-autocount-bulk-document-load-acceptance-criteria.md` (AC-03-01..24). Executed
2026-09-05/06 on branch `sprint-5/03-autocount-bulk-document-load`, worktree
`.claude/worktrees/autocount-bulk-document-load`, against the REAL company (AutoCount
`AED_SORENTO` over MSSQL, Sorento company `SRT`) plus the `ac_sim` simulator company (Postgres
fixture, Sorento company `SIM`). Report written at branch HEAD `40d5cb2`.

## Suite totals (HEAD 40d5cb2)

- Backend: `.venv/bin/python -m pytest -q tests/test_autocount*.py` (24 files) -> **948 passed**,
  0 failed, 217 warnings, 343 s. In-memory SQLite + `schema_translate_map`; migrations invisible
  to the suite (none were added by this plan - D7, no schema change).
- The live verification below is the user-perspective proof the suite cannot give.

## Environment

- Backend: lane worktree FastAPI on **:8003** (eager Celery, no beat; `.env` symlinked from the
  main checkout). The process that served the whole load, the reconcile and every check below was
  started at lane commit `59270de` (`backend8003_59270de.log`, still the live process at report
  time). Commits `91b7096..40d5cb2` landed afterwards: preset fixes (`90052a7` NULL-Qty
  pseudo-lines, `c434a1d` ItemCode filter on the line presets - the SAME predicates that were
  applied by hand to the real company's tasks during the load, see Findings 1 and 2), pool
  headroom (`91b7096`), docs and tests. Load-time env: `AUTOCOUNT_LINE_FETCH_WORKERS=4`,
  `AUTOCOUNT_SINK_CONCURRENCY=3`, `AUTOCOUNT_RUN_TIME_BUDGET_SECONDS=300` (drivers),
  `AUTOCOUNT_PAGE_SIZE` default 2,000, push cap 5,000 per run.
- Frontend: prod build on **:3003** from this worktree (`NEXT_PUBLIC_BACKEND_API_URL=http://
  localhost:8003` baked in). Browser verification = `agent-browser` headless, real clicks
  (`demo@example.com`, tenant `default`), at 1600 px and 375 px.
- Ticks: local dev has no Celery beat, so the sweep was driven with `scheduler._sweep_one` from
  the lane backend (plan §2.4), one tick per run, by three scripts kept in the session
  scratchpads: `overnight_driver.py` (initial load, SO -> PO -> SPO), `reconcile_driver.py`
  (one RECONCILE pass per entity, `next_reconcile_at` made due), `ac_sim_reconcile_tick.py`
  (AC-03-23). `Run now` clicks in the UI were used for every single manual run named below.
- Source: AutoCount `AED_SORENTO` (MSSQL, ZeroTier relay). Source counts were read through the
  ESB's own read-only `POST /autocount/sql/preview` (100-row cap; `COUNT` queries and a keyset
  walk on `DocKey` for the audit CSVs) - no direct MSSQL credential in the tester's hands.
- Sink: local Sorento stack, DB `sorento_ingest_v4`
  (`postgresql://tehjayson@localhost:5432/sorento_ingest_v4`), companies `SRT` (real) and `SIM`
  (`ac_sim`). Sorento-side counts were read with psql; Sorento's own UI on :3042 was NOT
  screenshotted - **DEFERRED (no approved Sorento login)**.
- Real-company config applied during the lane (config only, no code): all three document tasks
  re-saved with the fingerprint header queries (`LineCount`, `QtySum`, `TransferedSum`,
  `SubTotalSum`, `MaxDtlKey` over an `OUTER APPLY` filtered to `ItemCode IS NOT NULL AND Qty IS
  NOT NULL`), line queries filtered to `ItemCode IS NOT NULL AND Qty IS NOT NULL`, `fromDate`
  2023-09-01 (D4), previewed, activated. The `ac_sim` `sales_order` header query was given the
  Postgres form of the same fingerprint (`LEFT JOIN LATERAL ... ON true`) for AC-03-23.

## Timings (from the two driver logs)

| Pass | Entity | Runs (ticks) | Pages | Rows scanned | Staged | Pushed | Failed | Wall time |
|---|---|---|---|---|---|---|---|---|
| Initial (16:46Z-17:51Z) | sales_order | 18 | 35 | 68,068 | 68,068 | 72,500 | 0 | 3,498 s |
| Initial | purchase_order | 1 | 4 | 7,962 | 4,674 | 4,674 | 1 | 258 s |
| Initial | shipping_order | 1 | 4 | 7,962 | 3,004 | 3,004 | 283 | 141 s |
| **Initial total** | | 20 | 43 | | | | | **3,897 s** |
| Reconcile (17:55Z-19:12Z) | sales_order | 20 | 75 | 148,068 | 80,000 | 80,000 | 0 | 4,220 s |
| Reconcile | purchase_order | 1 | 4 | 7,962 | 4,675 | 4,675 | 0 | 227 s |
| Reconcile | shipping_order | 1 | 4 | 7,962 | 3,287 | 3,287 | 0 | 160 s |
| **Reconcile total** | | 22 | 83 | | | | | **4,608 s** |

- Budget cut every SO run at 5 pages (10,000 headers + their lines in about 400 s, i.e. about 80 s
  per 2,000-header page including the per-document line fetch); each run also drained 5,000
  pending rows (about 100 s per 5,000 pushes once extraction was complete). The initial SO pass
  scanned only 68,068 of the 148,068 headers because the query re-save kept the old watermark
  (Finding 3, BL-SS-097); the reconcile pass re-baselined all 148,068 and staged/pushed the
  80,000 that had no hash, then scanned the 68,068 hashed rows with 0 staged (AC-03-09 at scale).
- All 39 SO runs of the load window (00:46-03:14 local, 14 of them truncated) total: 216,136
  rows scanned, 148,068 staged, 152,500 pushed, 0 failed.

## Step 5 - counts versus source (psql on both sides, 2026-09-06 03:15 local)

Source counts through `sql/preview` (`DocDate >= '2023-09-01'`); ESB side = the newest PUSHED
staged record per `source_ref` (company `8bc3496b`); Sorento side = `sorento_ingest_v4` rows for
company `SRT` whose `source_ref` starts with `AED_SORENTO:` (the 64 `SIM` headers / 455 lines
from `ac_sim` are excluded).

| Object | Source | ESB pushed | Sorento | Result |
|---|---|---|---|---|
| SO headers | 148,068 | 148,067 (+1 STAGED) | 148,067 | match; the 1 missing = doc key 45274227, retryable at Sorento (product key 6, Finding 6) |
| SO lines | 673,918 total = 602,431 real + 52,844 ItemCode NULL + 18,643 Qty NULL | 602,430 | 602,430 | match = 602,431 real lines minus the 1 line of the pending document |
| PO headers | 4,675 | 4,675 | 4,675 | exact |
| PO lines | 68,919 total = 65,026 real + 3,893 ItemCode NULL | 65,026 | 65,026 | exact |
| SPO headers | 3,287 | 3,287 | 3,287 | exact |
| SPO lines (`spo_allocations`) | 68,805 total = 68,519 real + 286 ItemCode NULL | 68,519 | 68,519 | exact |

`ac_row_hash` holds exactly one row per source header: 148,068 / 4,675 / 3,287. FAILED staged
rows in the final state: SO 0 new (570 residue from the pre-fix query, see Finding 3), PO 1 and
SPO 283 residue from the pre-fix line query (all 284 documents re-staged and pushed by the
reconcile with 0 failures after Finding 2's fix). 1,000 `DISCARDED` SO rows dated 20:41 local are
the discarded needs-review batch from the pre-load drill, not part of the load.

## Step 6 - manual `Run now` on sales_order proves change-only

UI: real company -> Sales order -> Actions -> Run now (03:14:39 local). Run `57996afc`,
`mode=manual`, `SUCCESS`, `rows_scanned 0`, `fetched 0`, `staged 0`, `failed 0`, `pushed 0`,
duration 629 ms; `pushFailures` names exactly one row, `AED_SORENTO:45274227` retryable (the
pending STAGED row re-offered without a re-fetch - AC-03-13). Nothing was re-staged and nothing
unchanged was re-pushed.

## Step 7 - AC-03-23 fulfilment through reconcile (`ac_sim`, Sorento company `SIM`)

1. `ac_sim` `sales_order` header query re-saved with the LATERAL fingerprint (Test query: 64
   rows, PUT 200). The save cleared the task's hashes (BL-SS-097 behaviour) and kept the watermark.
2. Baseline reconcile (`ac_sim_reconcile_tick.py`): run `3c831721` `mode=reconcile`, scanned 64,
   added 64, staged 64, pushed 64, complete. Sorento `ac_sim:1:1`: `qty_ordered 40`,
   `qty_delivered 1`, `line_status open`, order `open`.
3. Given: `update dbo.sodtl set transferedqty = qty where dockey = 1 and dtlkey = 1` (1 -> 40);
   header `so.lastmodified` unchanged at `2026-09-05 03:10:18.598304+08` (verified before/after).
4. Incremental: UI Actions -> Run now, run `8ad8311c` `mode=manual`: rows_scanned 2 (the
   tie-group at the stored mark, re-read with `>=`), added 0, updated 0, **staged 0**, pushed 0.
5. Reconcile: run `ff8b8191` `mode=reconcile`: rows_scanned 64, added 0, **updated 1, staged 1,
   pushed 1**; job log "Page 1: scanned 64, changed 1 (0 new, 1 updated), 63 unchanged,
   skipped, 0 failed." The staged record for `ac_sim:1` carries `raw.TransferedSum 40`, header
   status formula `closed`, line `qty_delivered 40`.
6. Sorento `ac_sim:1:1`: `qty_delivered 40.0000`, `line_status closed`, order status `closed`,
   both `updated_at 2026-09-05 19:23:29Z`. **PASS.**

Audit CSVs (scratchpad, built by `pseudo_line_audit.py` through `sql/preview`):
`pseudo_line_documents_sales_order.csv` - 37,433 SO documents carrying at least one pseudo-line
(52,844 ItemCode-NULL + 18,643 Qty-NULL lines, exactly the source totals; 252,368 real lines
alongside; top pseudo descriptions: blank 14,279, "PROMOTION PACKAGE" 12,658, "PACKAGE ITEM:"
1,375, "ITEM PACKAGE" 423, "DISPLAY UNIT" 126); `pseudo_line_documents_po_spo.csv` - 1,207 PO/SPO
documents (4,179 ItemCode-NULL lines; "CURRENCY ROUNDING DIFFERENCE" 266, "EXTRA LOADING" 27).
Exactly one SO (`SO364670`, 4 pseudo-lines, 0 real) and one PO (`PO-2026/01-0013`) consist of
pseudo-lines only; they and the headers with no detail rows at all were pushed as headers with an
empty line list (ESB final state: 47 SO / 56 PO / 2 SPO zero-line documents, 42 / 25 / 2 of them
`Cancelled`).

## AC results

| AC | Result | Evidence |
|---|---|---|
| AC-03-01 pages, not one statement | PASS | Suite; live: every SO run read 2,000-header pages ("Page 1..5" per run), 35 + 75 pages over the two passes, no 2,000-cap error anywhere in 39 runs. |
| AC-03-02 page boundary ties | PASS | Suite (straddling group + group larger than a page); live: `ac_sim` incremental re-read the 2-row tie group at the mark and staged 0 (no duplicate); `ac_row_hash` = exactly 148,068 / 4,675 / 3,287 rows. |
| AC-03-03 budget cuts a run, pass continues | PASS | Live: 14 SO runs ended `SUCCESS`, `truncated=true`, "Budget reached after page N; continues on the next tick.", the next tick resumed at the cursor (pages 5, 10, 15 ... in the driver logs, no page re-read). |
| AC-03-04 completion observable | PASS | Live: tick 7 (initial) and tick 9 (reconcile) returned `complete=True`, `truncated=false`; the following ticks were ordinary incrementals with `rows_scanned 0`. |
| AC-03-05 masters without a watermark unpaged | PASS | Suite (`warehouse`); not exercised live (the real masters all carry `LastModified`). |
| AC-03-06 settings, not constants | PASS | Suite (floor refusal); live budget run at `AUTOCOUNT_RUN_TIME_BUDGET_SECONDS=300` cut runs at about 400 s (page in flight finished). |
| AC-03-07 MSSQL and Postgres paging statements | PASS | Suite; live: MSSQL (`TOP (:page_size)`) on the real company and Postgres (`LIMIT`) on `ac_sim`, same inner SQL untouched. |
| AC-03-08 abort stops at a page boundary | PASS | Suite; not exercised live. |
| AC-03-09 unchanged rows neither staged nor pushed | PASS | Live: reconcile tick 9 scanned 68,068 hashed SO headers, staged 0; `ac_sim` reconcile "63 unchanged, skipped"; product manual run scanned 11,784, updated 95, staged 95. |
| AC-03-10 new ref staged as an add | PASS | Live: `ac_sim` baseline reconcile `added 64`; SO reconcile staged the 80,000 unhashed headers as adds and pushed them. |
| AC-03-11 watermark advances despite mapping failures | PASS | Live: SPO initial run `failed 283`, PO `failed 1`, both `complete=True`, watermark advanced, FAILED staged records persisted with the field text ("field 'product_ref' (ItemAutoKey) - required ... empty"); suite covers the `last_error` wording. |
| AC-03-12 failed row keeps no hash, retried by the next full pass | PASS | Live: after the line-query fix the reconcile re-fetched the 284 failed PO/SPO documents as unhashed, mapped and pushed them (0 failed). Observation (Finding 6): product rows that FAILED under a PRE-D1 build still carried hashes and were skipped until the operator dropped them. |
| AC-03-13 retryable row re-offered without a re-fetch | PASS | Live: `AED_SORENTO:45274227` re-offered by every SO run including the manual run with `rows_scanned 0` (step 6). |
| AC-03-14 preview writes no hashes, stages nothing | PASS | Suite; live Test-query previews on all four tasks left `ac_row_hash`/`ac_staged_record` counts unchanged. |
| AC-03-15 seen stamps touched for every fetched row | PASS | Suite; live: reconcile completed with 0 delete intents over 148,068 known refs (every ref touched across the 9 continuation runs). |
| AC-03-16 deletes only when the pass completes | PASS | Suite; live: no delete intent staged by any truncated run (`deleted_count 0` throughout), pass completed with 0 stale refs. |
| AC-03-17 pass start survives continuation | PASS | Live: one reconcile pass spanned 9 runs (8 truncated); rows seen by run 1 were not mis-read as unseen at completion (0 deletes). |
| AC-03-18 filtered-out headers never delete candidates | PASS | Live: PO and SPO read the same `PO` table (7,962 headers each); the `startswith(... "SPO-")` filter dropped 4,675 / 3,287 rows every page and neither pass staged a delete. |
| AC-03-19 delete guard leaves state consistent | PASS | Suite; not exercised live (no guard trip). |
| AC-03-20 presets carry the line fingerprint | PASS | Suite (preset + pack grep); live: the real tasks run the fingerprint queries; `raw.LineCount`/`TransferedSum` present on every staged header. |
| AC-03-21 wire and FE label | PASS | Live: Runs tab of the real company's Sales order shows "Partial, continues" + "Budget reached after page 40; continues on the next tick." on each truncated run, at 1600 px and 375 px (16 labels rendered, no horizontal page scroll); `initialLoad` reported `complete=false, pagesDone n` during the pass, `null` after. |
| AC-03-22 live load on the real company | PASS | Step 5 table: Sorento SRT = source for PO/SPO headers and lines exactly; SO 148,067 of 148,068 headers with the one remainder named and retryable (Finding 6); 602,430 lines = real lines minus that document's single line; every mapping failure listed (Findings 1, 2, 6); the manual run after the load scanned 0 and staged 0 (step 6). |
| AC-03-23 fulfilment reaches Sorento through reconcile | PASS | Step 7. |
| AC-03-24 kill test | DEFERRED | Reviewer-owned (plan §3); not re-run by the tester in this report. |

**Tally: 23 PASS, 0 FAIL, 1 DEFERRED (AC-03-24, reviewer's kill test).** Sorento UI screenshots
on :3042: DEFERRED (no approved Sorento login); Sorento state was verified with psql instead.

## Live findings

1. **Qty-NULL pseudo-lines (SO).** 18,643 `SODTL` rows in scope carry an `ItemCode` but `Qty
   NULL` ("PROMOTION PACKAGE", "PACKAGE ITEM:", package/display headers). Under the plan's
   original line query they mapped as lines and failed `qty_ordered` required-but-empty: 570
   SO documents FAILED (22:11-00:17 local) before the line queries and the header fingerprint
   were re-saved with `AND d.Qty IS NOT NULL`. Preset fix landed as `90052a7`. Audit CSV above.
2. **ItemCode-NULL lines (PO/SPO).** 3,893 PO + 286 SPO `PODTL` rows have no `ItemCode`
   ("CURRENCY ROUNDING DIFFERENCE", "EXTRA LOADING", free text). The header fingerprint already
   excluded them, the PO/SPO LINE queries did not, so 1 PO + 283 SPO documents FAILED on
   `product_ref` (`ItemAutoKey`) in the initial pass. Fixed by re-saving both line queries with
   `AND d.ItemCode IS NOT NULL`; the reconcile then loaded 4,675 / 3,287 with 0 failures. Preset
   fix landed as `c434a1d`.
3. **BL-SS-097** - a query re-save clears the hashes and the open pass but keeps `sqlWatermark`,
   so the next tick runs an INCREMENTAL from the old mark: the initial SO pass read only the
   68,068 headers past the mark, left 80,000 already-pushed headers unhashed, and the 570 FAILED
   rows were not retried until a reconcile was forced by hand. Correct by design; the operator
   gets no signal.
4. **BL-SS-098** - Sorento's `retryable` verdict names the unresolved reference in `errors`;
   `SorentoSink` folds it into a generic message and the STAGED row keeps `error`/`errors_json`
   NULL. Doc 45274227 stayed STAGED across every push with nothing on our side saying WHICH
   master was missing (it was product key 6, Finding 6).
5. **BL-SS-099 / BL-SS-100** - product `name`: ten items have an empty `Description` (AutoKeys 6,
   8, 11, 292, 6650, 8196, 10868, 10887, 10898, 11161), so 50 product staged rows FAILED on
   required `name`. The formula builder refuses source columns on a master entity (BL-SS-099,
   `builderVariables = []`), and `MappingRow.coerce` short-circuits a blank source before the
   row's formula can run (BL-SS-100). Workaround applied by config: the `name` row re-sourced from
   `ItemCode` with `if(trim(coalesce(Description, "")) == "", ItemCode, Description)` (PUT 200,
   simulate on the real key-6 record -> `name "1861"`); the following product runs reported 0
   failures.
6. **Product retry needs a full scan.** The ten FAILED product refs still carried `ac_row_hash`
   rows written by a pre-D1 run (a D1 build keeps no hash for a failed row); dropping the ten
   rows was not enough either, because the product watermark (`LastModified` 2026-09-05
   21:22Z) puts those 2024-modified items outside every incremental window. Re-fetch history
   (watermark reset) + one run is pending on the coordinator's side; until then SO doc 45274227
   stays retryable at Sorento. Ten manual product runs (02:24-02:30 local, all `SUCCESS`, 0
   failed) drained the 33,979-row STAGED product backlog to the 10 rows below.
7. **Retryable product rows.** `AED_SORENTO:1043` and `AED_SORENTO:10081` (5 duplicate STAGED
   rows each from the 14:08-14:15 runs) are answered `retryable - its category or unit of
   measure has not synced yet` on every push and are re-offered every run (each duplicate takes
   a slot in the 5,000 batch - pushed counts 4,995, 4,994, ... 4,991).
8. **Observation - naive `LastModified` read as UTC.** AutoCount stores local (UTC+8) naive
   timestamps; the ESB treats them as UTC, so the product watermark shows as `05:22+08` for a run
   that ended at `02:30+08` (about 8 h in the future) and the task list's "Synced up to" column
   inherits the skew. Display-level today; worth a look at whether a row modified inside that
   8 h window can be skipped by the mark.
9. **Zero-line documents** are pushed as headers with an empty line list (47 SO / 56 PO / 2
   SPO, mostly cancelled) - consistent with the source, noted for Sorento's awareness.

## Definition of Done gate (tester's view)

1. No mock on this lane (backend-only plus one FE label); every surface used above is the real
   `.real.ts` service against :8003.
2. Backfill: no schema change (D7); the fingerprint is config on the tasks (real company and
   `ac_sim` re-saved by hand, presets updated for new tasks).
3. No hardcoded editable key touched by this plan.
4. No new permission.
5. User-perspective verification: real clicks on :3003 (Test query, Save, Run now, Runs tab) at
   1600 px and 375 px against the lane's own :8003; Sorento verified with psql (UI screenshots
   DEFERRED as above).
