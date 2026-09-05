# 03 - AutoCount bulk document load: paged extraction, change-only staging, reconcile over pages

> **UAC:** `03-autocount-bulk-document-load-acceptance-criteria.md` (AC-03-01..24). **Branch:**
> `sprint-5/03-autocount-bulk-document-load`. **Backend only** (one FE label). No migration, no
> new permission, no Sorento change.

## 1. Why (facts from the 2026-09-05 live session against the real AutoCount DB)

- The real company has 306k SO headers / 1.47M SO lines; the business wants the last three years
  in Sorento: fromDate 2023-09-01 = 148,068 SO / 621,074 lines, 4,675 PO, 3,287 SPO.
- `SqlDbSource._read` reads the whole window in one statement and then runs ONE line query per
  header; `MAX_DOCUMENT_HEADERS_PER_RUN = 2000` fails the run above that. A reconcile pass reads
  lines for EVERY header in the window, every pass.
- `sync.run_autocount_sync` stages and pushes every fetched row; `ac_row_hash` is only used to
  count added/updated and to compute deletes. Product: 4 manual runs re-staged 11,774 rows each.
- The watermark advances only when `failed_count == 0`; 10 permanently bad products held it
  forever, so every run was a full re-extract.
- Header `LastModified` moved for only 19% of fulfilled June-2026 SOs: fulfilment is a line fact
  and reaches us only through a full pass whose header hash changes.

## 2. Design

### 2.1 Paged extraction (`sql_source/source.py`)

- New module-level settings read from `app.config.Settings`: `autocount_page_size` (env
  `AUTOCOUNT_PAGE_SIZE`, default 2000, min 100) and `autocount_run_time_budget_seconds`
  (env `AUTOCOUNT_RUN_TIME_BUDGET_SECONDS`, default 600, min 30). Pydantic validators refuse
  lower values at startup. `MAX_DOCUMENT_HEADERS_PER_RUN` and its `SqlDocumentCapExceeded` are
  removed; `MAX_DOCUMENT_LINES_PER_HEADER` and `MAX_EXTRACT_ROWS` stay (the latter now guards
  only unpaged reads and a single page).
- `build_paged_wrap(query, quoted_watermark, quoted_date_column | None, mark, *, dialect,
  page_size)`: same derived-table shape as today plus a page limit: `SELECT TOP (:page_size) *
  FROM (...) AS t WHERE <predicates> ORDER BY t.<wm>` for `mssql`, `... ORDER BY t.<wm> LIMIT
  :page_size` otherwise. Predicate on the mark is `>=` (not `>`) so a page boundary inside a tie
  group loses nothing; the caller passes `exclude_refs` (refs already taken at exactly that mark)
  and the source drops them after the read (AC-03-02). The first page of a pass has no mark
  predicate. Documents keep the from-date floor; watermarked masters use the same wrap without
  it (today `build_incremental_wrap`); non-watermarked masters stay on the verbatim statement.
- `SqlDbSource.fetch_page(cursor: PageCursor) -> PageResult` replaces the monolithic
  `fetch_changes` body for watermarked tasks. `PageCursor = {mark, tie_refs, pass_kind,
  pass_started_at, pages_done}`; `PageResult = {records (changed only, with lines for documents),
  unchanged_refs, failed_filter_refs (filtered out), hashes (ref -> hash for every fetched row),
  last_mark, tie_refs, rows_scanned, added, updated, complete: bool}` where `complete =
  rows_scanned < page_size`. `fetch_changes(since)` remains as a thin wrapper for
  non-watermarked masters and the API path (unchanged behaviour, one page = everything).
- Hash diff BEFORE lines: for each fetched header compute `row_hash(raw, compared_columns)`;
  `known = RowHashRepository.hashes_for(refs of this page)`; a header whose hash equals the known
  one is `unchanged` (no line read, not in `records`). Only changed/new headers get `_read_lines`.
- The filter formula still runs before the hash diff (a filtered header is neither changed nor
  unchanged; its stale hash is dropped as today).
- Hash persistence moves OUT of the source (see 2.2); `persist_hashes=False` (preview) reads
  one page and returns it, nothing written.

### 2.2 Run loop, change-only staging, watermark (`sync.py`)

`run_autocount_sync`, sql_db branch with a watermark column:

```
cursor = PageCursor.from_watermark_row(watermark_row, mode)   # resumes an unfinished pass
while True:
    page = source.fetch_page(cursor)
    staged, failed, failed_refs = _stage_documents(page.records ...)          # per-record commit as today
    RowHashRepository.upsert_many(hashes for page.hashes minus failed_refs, seen_at=now)
    RowHashRepository.touch_seen(page.unchanged_refs, seen_at=now)            # new repo method
    RowHashRepository.delete_many(failed_refs + stale filtered refs)
    advance watermark_row.last_modified_at / cursor_json to page.last_mark, tie_refs, pages_done
    commit; accumulate run counters (rows_scanned, added, updated, staged, failed, unchanged)
    if page.complete: mark pass complete in cursor_json; break
    if aborted: break (run aborted as today)
    if budget exceeded: run.truncated = True; config.next_incremental_at = now; break
if pass complete and mode == reconcile: _stage_deletes(refs = known with seen_at < pass_started_at, minus filtered)  # guard applies
auto_push as today (pending across jobs, 5000 cap unchanged)
```

- The watermark advances per page to `page.last_mark` regardless of `failed`. `watermark_row.
  last_error` = "N record(s) failed to map; see staged records" when N > 0, else None;
  `consecutive_failures` increments only on a run-level failure (exception), no longer on mapping
  failures.
- `cursor_json` shape (no migration, and no key rename): `{"sqlWatermarkColumn": wm,
  "sqlWatermark": <encoded>, "tieRefs": [...], "pass": {"kind": "initial|incremental|reconcile",
  "startedAt": iso, "pagesDone": n, "complete": bool}}` - the existing `CURSOR_COLUMN`/
  `CURSOR_MARK` keys are kept VERBATIM (live rows on the real company already carry them; a
  rename would orphan every task's stored mark and force a full re-read); `tieRefs` and `pass`
  are the only ADDED keys. `PageCursor.from_watermark_row` resumes when `pass.complete` is false
  and `pass.kind` matches the run mode (a reconcile tick while an initial pass is unfinished
  continues the initial pass first; the reconcile is re-armed by `next_run_times`); a legacy row
  with no `pass` key at all (or one from before this plan) resumes as a plain incremental from
  its stored `sqlWatermark`, exactly as before. A completed reconcile resets `startedAt`; a guard
  failure (AC-03-19) clears the pass so the next reconcile starts fresh.
- Job log lines per page: "Page n: scanned S, changed C (A new, U updated), unchanged X skipped,
  failed F." Run row: `rows_scanned`, `added_count`, `updated_count`, `staged_count`,
  `failed_count`, `truncated`, `error` (continuation message "Budget reached after page n;
  continues on the next tick") - all existing columns.

### 2.3 Reconcile over pages (`sync.py` + repository)

- `RowHashRepository.touch_seen(tenant, company, entity, refs, seen_at)` (UPDATE ... WHERE ref IN)
  and `stale_refs(tenant, company, entity, before: datetime) -> List[str]` (refs with `seen_at <
  before`). Delete intents = `stale_refs(pass_started_at)` minus filtered refs recorded during the
  pass (kept in `cursor_json.pass.filteredRefsDropped` is NOT needed: filtered refs have their
  hash deleted on the page they were filtered, so they are never stale). The existing delete
  guard (`DELETE_GUARD_RATIO`, `DELETE_GUARD_MIN_ABSOLUTE`) and the zero-rows guard apply to the
  completed pass (`known` = hash count at pass end).
- `_stage_deletes` unchanged; `current_refs` for its stale-intent discard = refs seen this run.

### 2.4 Scheduler (`scheduler.py`, `etl_service.py`)

- `_sweep_one` unchanged except: a task whose `cursor_json.pass.complete` is false is due
  immediately (`next_incremental_at` already set to now by the run); `EtlService.next_run_times`
  unchanged. `activate_task` arms `next_incremental_at = now` so the initial pass starts on the
  first tick after activation (today it waits `incrementalMinutes`).
- Local dev has no beat: the tester drives ticks with `_sweep_one` from the lane backend (as in
  the drill); documented in the test report.

### 2.5 Presets and SQL pack (`presets.py`, `sprint-4/22-autocount-db-etl-autocount-sql.md`)

SO header query gains an `OUTER APPLY` (PO/SPO already have one) and all three select:

```sql
l.LineCount AS LineCount, l.QtySum AS QtySum, l.TransferedSum AS TransferedSum,
l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey
-- OUTER APPLY (SELECT COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, SUM(d.TransferedQty) AS TransferedSum,
--   SUM(d.SubTotal) AS SubTotalSum, MAX(d.DtlKey) AS MaxDtlKey, MIN(d.DeliveryDate) AS FirstDeliveryDate
--   FROM {database}.dbo.SODTL AS d WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL) AS l
```

The fingerprint columns are plain result columns: they enter `compared_columns` automatically
(empty configured set = every result column minus keys), so no engine knowledge. `seed_document_
mapping` ignores them (no mapping row). The pack documents them under §1/§3 with the 19% finding.
`fromDate` in the presets stays `2026-01-01` (a preset is a starting point); the real company's
tasks are saved with `2023-09-01` during live verification.

### 2.6 Wire (`schemas.py`, `etl_service._task_view`, FE label)

- `EtlTaskResponse.initialLoad: Optional[{complete: bool, pagesDone: int, lastMark: str|null,
  kind: str}]` derived from `cursor_json.pass` (null when no pass is open).
- `SyncRunItem` already carries `truncated` + `error`; the FE run list (`autocount` task runs
  table) renders `truncated` as the status label "Partial, continues" (one component change,
  inline, no mock phase - trivial).

### 2.7 Files

- `service_backend/app/config.py` (+2 settings, validators)
- `service_backend/modules/autocount/sql_source/source.py` (paged wrap, `fetch_page`, hash diff
  before lines, cap removal), `sql_source/errors.py` (drop `SqlDocumentCapExceeded`)
- `service_backend/modules/autocount/sync.py` (page loop, change-only staging, watermark rule,
  seen stamps, deletes at completion)
- `service_backend/modules/autocount/repositories/autocount_repository.py` (`touch_seen`,
  `stale_refs`)
- `service_backend/modules/autocount/scheduler.py` (continuation due), `services/etl_service.py`
  (`activate_task` arms now, `_task_view.initialLoad`, preview reads one page)
- `service_backend/modules/autocount/presets.py`, `documentation/plans/sprint-4/22-autocount-db-etl-autocount-sql.md`
- `service_backend/modules/autocount/schemas.py`
- `service_frontend/.../autocount` runs table label
- Tests: `tests/test_autocount_sql_db_source.py` (paging, ties, hash-before-lines, preview),
  `tests/test_autocount_reconcile_push.py` (seen stamps, deletes at completion, guard),
  `tests/test_autocount_pipeline.py` or new `tests/test_autocount_bulk_load.py` (run loop,
  budget, continuation, watermark despite failures, change-only staging), `tests/test_autocount_
  scheduler.py` (continuation due), `tests/test_autocount_etl_task_routes.py` (wire),
  preset text test.

## 3. Test list for the tester (one line per AC)

- AC-03-01 `test_a_pass_reads_pages_of_page_size_and_stages_each_before_the_next` - 4,500 headers,
  page 2,000: three activity records, staged rows exist after page 1 commit.
- AC-03-02 `test_a_tie_group_across_a_page_boundary_is_staged_exactly_once`.
- AC-03-03 `test_the_budget_cuts_a_run_and_the_next_run_resumes_at_the_cursor` - budget 0.001 s
  via settings override; run 1 truncated, `next_incremental_at <= now`; run 2 starts at page 2.
- AC-03-04 `test_a_short_last_page_completes_the_pass_and_the_next_run_is_incremental`.
- AC-03-05 `test_a_master_without_a_watermark_still_reads_in_one_statement`.
- AC-03-06 `test_page_size_and_budget_come_from_settings_and_refuse_low_values`.
- AC-03-07 `test_paged_wrap_uses_TOP_for_mssql_and_LIMIT_otherwise` (text assertions, both
  branches, mark and no-mark, with and without the from-date floor).
- AC-03-08 `test_an_abort_stops_after_the_page_in_flight`.
- AC-03-09 `test_unchanged_rows_are_not_staged_and_the_log_counts_them`.
- AC-03-10 `test_a_new_ref_is_staged_as_an_add`.
- AC-03-11 `test_the_watermark_advances_past_mapping_failures`.
- AC-03-12 `test_a_failed_row_keeps_no_hash_and_is_retried_by_the_next_full_pass`.
- AC-03-13 `test_a_retryable_pending_row_is_offered_again_without_a_refetch`.
- AC-03-14 `test_preview_reads_one_page_and_writes_nothing`.
- AC-03-15 `test_seen_at_is_touched_for_unchanged_rows_and_their_hash_is_kept`.
- AC-03-16 `test_deletes_are_staged_only_when_the_reconcile_pass_completes`.
- AC-03-17 `test_the_pass_start_is_read_from_the_cursor_on_continuation`.
- AC-03-18 `test_a_filtered_out_header_is_never_a_delete_candidate_after_paging`.
- AC-03-19 `test_a_delete_guard_failure_clears_the_pass_for_the_next_reconcile`.
- AC-03-20 `test_document_presets_select_the_line_fingerprint_columns` (+ pack grep test).
- AC-03-21 `test_task_view_and_run_item_expose_continuation`.
- AC-03-24 kill test by the reviewer.

## 4. Slices and order

S1 (paging, budget, continuation, settings, wrap) -> S2 (change-only staging, watermark rule,
failed-row hash) -> S3 (seen stamps, deletes at completion) -> S4 (presets, pack, wire, FE
label). Tester writes red tests for S1-S4 from this plan first; one coder makes them green in
that order; reviewer + security-reviewer (SQL source is a trigger path) + tester live load in
parallel at the end. Live load = AC-03-22/23 on the real company and `ac_sim`.

## 5. Risks and answers

- **Inner query cost per page on MSSQL.** Each page re-evaluates the derived table (OUTER APPLY
  over SODTL for 306k SOs) then takes TOP N ordered by `LastModified`. Measured live during the
  lane on the real DB; if a page exceeds ~60 s, the fallback is an index hint note in the pack
  (`SO.LastModified` is indexed in stock AutoCount) - no engine change.
- **Ties on `LastModified`.** Bulk-imported documents may share one timestamp across more than a
  page; `exclude_refs` handles a tie group of any size because the next page repeats the mark
  with `>=` and drops the taken refs, and a tie group larger than the page size still advances
  (the page returns page_size rows all at the mark; excluded refs grow until the group is
  exhausted). Test AC-03-02 covers a group straddling the boundary; a second test covers a group
  larger than the page.
- **Push cap 5,000 per run vs pages.** Unchanged: pending rows drain across runs; with
  continuation ticks firing immediately, the drain keeps pace with extraction.
- **Local eager mode.** `Run now` executes inline in the HTTP request; with a 600 s budget the
  request can exceed the proxy timeout. The tester drives the load through `_sweep_one` ticks
  (background job path) and sets `AUTOCOUNT_RUN_TIME_BUDGET_SECONDS=120` in the lane `.env`.

## 6. Backlog entries (register in `documentation/backlogs/backlog.md`)

- BL-SS-055 Batched line fetch (one `IN` query per page of DocKeys) - N+1 bounded per page today.
- BL-SS-056 Operator "reset baseline" action (clear `ac_row_hash` for one task) - psql today.
- BL-SS-057 Push cap per run as a setting (5,000 today).
- BL-SS-058 Sink drops the consumer `warnings` key (tester BL-D).
- BL-SS-059 Preview does not count mapping-failed rows (tester BL-B/BL-C).
