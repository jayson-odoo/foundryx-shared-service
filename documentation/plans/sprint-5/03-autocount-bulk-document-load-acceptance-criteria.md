# 03 - AutoCount bulk document load (paged extraction, change-only staging) - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-5/03-autocount-bulk-document-load.md`
> **Builds on:** `sprint-4/22-autocount-db-etl.md` (sql_db tasks, watermark, reconcile, row hashes),
> `sprint-5/02-autocount-document-mapping.md` (document line rows, presets, filter formula, deletes),
> `sprint-4/22-autocount-db-etl-autocount-sql.md` (the SO/PO SQL pack).
> **Target:** the real company's `sales_order` / `purchase_order` / `shipping_order` tasks load
> the last three years of AutoCount documents (fromDate 2023-09-01: about 148k SO / 621k lines,
> 4.7k PO, 3.3k SPO) unattended, then stay current through the watermark and the reconcile pass,
> without re-reading every document's lines on every pass and without re-pushing unchanged rows.
> **Source of decisions:** live config session 2026-09-05 (§Decision Log).

## Scope

**In (this repo, backend):** paged extraction for every `sql_db` task that has a watermark column
(initial load, incremental, reconcile alike); a per-run time budget with automatic continuation on
the next sweep tick; change-only staging (a row whose compared columns did not change is neither
staged nor pushed) for masters AND documents; watermark advance independent of mapping failures;
document header presets and the SQL pack gain a line fingerprint so line-only edits stay visible;
the run row and the task view expose "continues" state. Config on the real company (fromDate +
fingerprint queries) is part of the live verification, not code.

**Out:** batched line fetch (one `IN` query per page of DocKeys - BL, the N+1 stays but is now
bounded per page); an operator "reset baseline" button (BL - psql `delete from ac_row_hash`
for now); raising the 5,000-per-run push cap; Sorento-side changes (none needed).

## Definitions

- **Page** - up to `AUTOCOUNT_PAGE_SIZE` (default 2,000) header rows read in one statement,
  ordered by the watermark column, continuing from the previous page's last watermark value.
- **Run budget** - `AUTOCOUNT_RUN_TIME_BUDGET_SECONDS` (default 600). A run stops starting new
  pages once it is exceeded, finishes the page in flight, and marks itself `continues`.
- **Pass** - one logical extract: an initial load (no stored mark), an incremental (from the
  stored mark) or a reconcile (from the beginning, deletes computed at the end). A pass may span
  several runs when the budget cuts it; a pass is **complete** when a page returns fewer rows
  than the page size.
- **Changed row** - a fetched row whose ref is unknown to `ac_row_hash`, or whose compared-column
  hash differs from the stored one. Only changed rows are staged and pushed.
- **Line fingerprint** - header-query columns computed from the document's lines
  (`LineCount`, `QtySum`, `TransferedSum`, `SubTotalSum`, `MaxDtlKey`) so a line-only edit changes
  the header hash. Part of the presets and of the SQL pack; the engine itself has no special
  knowledge of them.
- **Seen stamp** - `ac_row_hash.seen_at`, touched for every fetched row (changed or not) on every
  page; a completed reconcile derives its delete intents from rows whose seen stamp predates the
  pass start.

## Slices

- **S1** Paged extraction + run budget + continuation (source + sync + scheduler).
- **S2** Change-only staging + watermark advance despite failures + failed rows lose their hash.
- **S3** Reconcile over pages: seen stamps, deletes at pass completion, delete guard unchanged.
- **S4** Presets / SQL pack line fingerprint, run/task wire fields, live load on the real company.

---

## S1 - Paged extraction, budget, continuation

**AC-03-01 [BE] Pages, not one statement.**
Given a document task with 4,500 headers in scope and page size 2,000,
When a run executes,
Then the source reads three pages (2,000 / 2,000 / 500), each page's lines are fetched and staged
and committed before the next page is read, and the run does not fail on the former
2,000-headers cap (the cap error text no longer exists).

**AC-03-02 [BE] Page boundary ties lose no row and duplicate none.**
Given six headers sharing the same watermark value straddling a page boundary,
When the pass runs,
Then every one of them is staged exactly once (the next page starts at `>=` the last mark and
skips the refs already taken at that mark).

**AC-03-03 [BE] Budget cuts a run, the pass continues.**
Given a run whose budget elapses after page 1 of 3,
When the run ends,
Then the run row carries `outcome=SUCCESS`, `truncated=true` and a message naming the page
reached, the stored cursor points at the last mark taken, the task's `next_incremental_at` is
set to now, and the next sweep tick starts a new run that resumes at that cursor without
re-reading page 1.

**AC-03-04 [BE] Completion is observable.**
Given the last page of a pass returns fewer rows than the page size,
When the run ends,
Then `truncated=false`, the cursor marks the pass complete, and the next tick runs an ordinary
incremental from the watermark.

**AC-03-05 [BE] Masters without a watermark still read in one statement.**
Given `warehouse` (no watermark column),
When it runs,
Then it is read unpaged exactly as before, and the existing row-limit guard still protects it.

**AC-03-06 [BE] Settings, not constants.**
Given `AUTOCOUNT_PAGE_SIZE=500` and `AUTOCOUNT_RUN_TIME_BUDGET_SECONDS=1` in the environment,
When a run executes,
Then pages are 500 rows and the budget check uses 1 second; defaults are 2,000 and 600; values
below 100 rows / 30 seconds are refused at startup with a clear message.

**AC-03-07 [BE] MSSQL and Postgres/SQLite paging statements.**
Given the header wrap for a document task,
When the paged statement is built for `mssql`,
Then it uses `SELECT TOP (:page_size) * FROM (...) AS t WHERE ... ORDER BY t.<watermark>`;
for every other dialect it uses `... ORDER BY t.<watermark> LIMIT :page_size`; the from-date
floor and the mark predicate are unchanged; the user's inner SQL is never re-parsed.

**AC-03-08 [BE] Abort still stops at a page boundary.**
Given an operator aborts the job during page 2,
When the page in flight finishes,
Then no further page is read, rows staged so far stay staged, and the run is marked aborted as
today.

## S2 - Change-only staging, watermark independent of failures

**AC-03-09 [BE] Unchanged rows are neither staged nor pushed.**
Given a master with 100 known rows of which 3 changed since the stored hashes,
When any run (manual, incremental or reconcile) fetches all 100,
Then exactly 3 staged records are written and offered to the sink, the run row reports
`rows_scanned=100`, `updated_count=3`, `added_count=0`, and the job log states
"97 unchanged, skipped".

**AC-03-10 [BE] A new ref is staged as an add.**
Given a fetched row whose ref has no stored hash,
When the run stages it,
Then it counts as `added_count` and is pushed as today.

**AC-03-11 [BE] Watermark advances despite mapping failures.**
Given a page of 50 rows where 2 fail mapping (required field empty),
When the run ends,
Then the watermark and cursor advance to the max watermark value seen on the page, the run row
has `failed_count=2`, the two failed rows are persisted as FAILED staged records with their error
text, and `ac_watermark.last_error` reads "2 record(s) failed to map; see staged records" (never
"watermark held").

**AC-03-12 [BE] A failed row keeps no hash, so it is retried by the next full pass.**
Given the 2 failed rows above,
When the next reconcile pass runs and the source data is unchanged,
Then both rows are fetched, treated as new (no stored hash), mapped again and fail again with a
fresh FAILED staged record; a row whose source data was fixed maps and is pushed.

**AC-03-13 [BE] A row that Sorento answered `retryable` is re-offered without a re-fetch.**
Given a staged row the sink marked retryable in run N,
When run N+1 fetches nothing new for that ref (unchanged hash),
Then the pending staged row is still offered to the sink by run N+1 (existing across-jobs
pending rule holds; change-only staging never hides a pending row).

**AC-03-14 [BE] Preview (dry run) writes no hashes and stages nothing, as before.**
Given `POST .../etl-task/preview` on a paged task,
When it runs,
Then it reads at most one page, persists no hash and no staged record, and reports the counts of
that page with a note that the population is paged.

## S3 - Reconcile over pages

**AC-03-15 [BE] Seen stamps are touched for every fetched row.**
Given a reconcile pass over 3 pages,
When each page completes,
Then every fetched ref on that page (changed or unchanged) has `ac_row_hash.seen_at` >= the pass
start, and unchanged refs keep their existing hash value.

**AC-03-16 [BE] Deletes are computed only when the pass completes.**
Given a reconcile pass cut by the budget after page 1,
When that run ends,
Then no delete intent is staged; when the continuation run completes the pass, delete intents
are staged for exactly the known refs whose seen stamp predates the pass start and that are not
filtered-out refs, and the existing delete guard (ratio and absolute floor) applies to that set.

**AC-03-17 [BE] The pass start survives continuation.**
Given the reconcile pass above,
When the continuation run starts,
Then it reads the pass start from the stored cursor (never from the clock), so rows seen by the
first run are not mis-read as unseen.

**AC-03-18 [BE] Filtered-out headers are still never delete candidates.**
Given a header the task's filter formula skips on every page,
When the pass completes,
Then it is not staged, not a delete intent, and its stale hash (if any) is dropped.

**AC-03-19 [BE] The delete guard failing the pass leaves hashes and stamps consistent.**
Given a completed reconcile whose delete set exceeds the guard,
When the guard fires,
Then no delete intent is staged, the run is marked failed with the guard text, and the next
reconcile pass starts a fresh pass start (it does not inherit the failed one).

## S4 - Presets, wire, live load

**AC-03-20 [BE] Document presets carry the line fingerprint.**
Given `GET /autocount/presets/{sales_order|purchase_order|shipping_order}`,
When the header query is returned,
Then it selects `LineCount`, `QtySum`, `TransferedSum`, `SubTotalSum` and `MaxDtlKey` from an
`OUTER APPLY` over the line table filtered to `ItemCode IS NOT NULL`, and the SQL pack document
(`sprint-4/22-autocount-db-etl-autocount-sql.md`) shows the same columns with a note on why.

**AC-03-21 [BE] Wire: run and task expose continuation.**
Given a run cut by the budget,
When `GET .../etl-task/runs` and `GET .../etl-task` are read,
Then the run item shows `truncated=true` with its message, and the task shows
`initialLoad: {"complete": false, "pagesDone": n, "lastMark": "..."}` (null once complete);
the existing FE run list renders the truncated run with the label "Partial, continues".

**AC-03-22 [E2E] Live load on the real company (config only, tester with real clicks).**
Given the real company's three document tasks re-saved with the fingerprint header queries and
fromDate 2023-09-01, previewed, activated and run,
When the sweep is driven until each pass reports complete,
Then Sorento `sorento_ingest_v4` holds for company SRT the same counts as the read-only source
counts (SO headers 148,068 minus mapping failures, PO 4,675, SPO 3,287), every mapping failure is
listed with its text, and a subsequent manual run stages only changed rows (rows_scanned high,
staged low).

**AC-03-23 [E2E] Fulfilment reaches Sorento through reconcile.**
Given an `ac_sim` SO whose line `TransferedQty` is raised to `Qty` without touching the header
`LastModified`,
When an incremental run and then a reconcile run execute,
Then the incremental stages nothing for it, the reconcile stages it as an update (fingerprint
changed), and Sorento shows the line fulfilled.

**AC-03-24 [T] Kill test.**
Given the implementing branches for AC-03-02 (tie skip), AC-03-11 (advance despite failures) and
AC-03-16 (deletes only on completion) are each disabled in turn,
When the suite runs,
Then at least one test goes red for each.

---

## Decision Log (2026-09-05)

| # | Decision | Why |
|---|---|---|
| D1 | Watermark advances past failed rows; failed rows lose their hash | One permanently bad document must never force a full re-extract every run (product task held its watermark on 10 bad items). Reconcile retries them. |
| D2 | Change-only staging for all entities | Reconcile becomes cheap everywhere; no more re-push of unchanged rows. Reset-baseline is an operator action (BL). |
| D3 | Continuous initial load with a time budget, continuation on the next tick | 148k SOs finish in hours unattended in prod; one page per 15-minute tick would take 18 hours. |
| D4 | fromDate 2023-09-01 for SO, PO, SPO | Three years of history required by the business; permanent boundary. |
| D5 | Line fingerprint in the header query, not engine magic | Header `LastModified` moves for only 19% of fulfilled SOs on real data; the engine hashes only header columns; a fingerprint keeps line edits visible without reading lines. |
| D6 | Deletes derived from `seen_at` at pass completion | A reconcile may span runs; refs cannot be held in memory across them. |
| D7 | No schema change | Continuation state in `ac_watermark.cursor_json`; seen stamps already exist. |
