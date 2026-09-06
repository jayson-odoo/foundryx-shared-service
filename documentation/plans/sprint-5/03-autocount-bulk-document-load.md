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

**Review round 2 amendments (security review + follow-up):**
- **F1 (preview one page).** `EtlService._extract_and_map`/`preview_task` no longer call the
  unpaged `fetch_changes` for a watermarked task - they call `source.fetch_page(PageCursor())`
  once (`persist_hashes=False`, nothing written) and report that ONE page's records. `preview_
  task`'s payload gains `warnings.pagedPreview: true` when the page is not `complete` (AC-03-14).
  A non-watermarked master is unaffected (still `fetch_changes`, one page = everything).
- **F5/F6 (tie-group bound, row cap) - SUPERSEDED by round 3's composite seek ordering below**
  (round 2's `skip`/`OFFSET` internal-retry design turned out to be unsafe under a concurrent
  delete between statements, R2-B1). Kept here only as history; see the round 3 section.
- **F2 (abort between pages) - investigated, no code change.** The security review's literal fix
  (roll back a just-staged page's hashes/cursor on a post-stage abort, discard that page's rows)
  was NOT implemented: the tester's own real-entry-point test for this scenario
  (`test_an_abort_between_pages_delivers_page_one_exactly_once_via_the_scheduler`) already passes
  UNCHANGED, because an ACTIVE task's auto-push pulls STAGED rows ACROSS jobs
  (`list_pending_for_entity`), so an aborted job's already-committed page still gets delivered
  exactly once on a later successful run. Implementing the literal fix (discarding that page's
  staged rows on abort) would instead BREAK the pre-existing, still-required-green
  `test_an_abort_stops_after_the_page_in_flight`, which asserts the opposite (a page staged
  before an abort landed stays staged, not discarded). The gap the finding names is real ONLY for
  a DRAFT/paused task run manually past an abort (its rows are job-scoped and never reach a
  review batch) - flagged to the backlog (§6), not fixed here, since no red test demands it and
  the two existing tests actively disagree about which behaviour is correct.

**Review round 3 amendments (R2-B1 blocker + follow-up S1/S2 + NIT):**
- **R2-B1 (composite `(watermark, key)` seek ordering) - REPLACES round 2's `skip`/`OFFSET`
  design entirely.** Round 2's internal retry loop assumed the database returns a same-mark tie
  group in a STABLE relative order across separate statements within one call - no engine
  actually guarantees that for an `ORDER BY` on a column with duplicate values, so a row could be
  silently skipped (or misread as a phantom delete on a reconcile). `build_paged_wrap` gained
  `quoted_key`/`last_key` keywords (both optional, defaulting to the byte-identical OLD
  watermark-only shape for any caller that omits them): given, it orders `ORDER BY t.<wm>,
  t.<key>` (`key` = `key_columns[0]`, checked/quoted the same way as the watermark) with a
  strict SEEK predicate `(t.<wm> > :mark) OR (t.<wm> = :mark AND t.<key> > :last_key)`, ANDed
  with the document from-date floor inside its OWN parens (AND binds tighter than OR - an
  ungrouped seek predicate ANDed with the date floor would silently drop the floor off the
  second branch). `PageCursor`/`PageResult` gain `last_key: Any` REPLACING `tie_refs`/`tie_refs`
  entirely; `cursor_json` gains a top-level `lastKey` (replacing `tieRefs`) and
  `pass.lastKey`/`pass.mark` (replacing `pass.tieRefs`). `fetch_page` is exactly ONE statement
  per page now - no internal retry loop, no `max_iterations` valve, no `exclude_refs` set;
  `sync._advance_mark_and_key` replaces `_advance_mark_and_ties` (same monotonic-never-backwards
  contract, now carrying a scalar `lastKey` instead of a tie-ref set).
- **Exact-multiple pages: bind `page_size + 1`, one statement, no trailing confirmation page.**
  `fetch_page` asks for one row MORE than `page_size` and trims it back off - `len(raw_rows) <=
  page_size` means this page is genuinely the last one (whether short or an exact multiple),
  `> page_size` means one more row exists beyond it (dropped, re-read as the first row of the
  NEXT page via the normal seek). This is what makes a same-mark tie group of `n` rows cost
  EXACTLY `ceil(n/page_size)` real statements (T1(b)) - the old `rows_scanned < page_size`
  heuristic needed a whole extra all-empty page to confirm completion whenever a population
  landed on an exact multiple of `page_size`.
- **A pass with a stored `mark` but no `lastKey` is NOT resumable (documented per the brief).**
  Only a LANE database mid-migration between review rounds can carry this shape (round 2's
  `PageCursor.from_watermark_row` stored `mark`/`tieRefs` but never a `lastKey`) - the real
  company has never run under either round yet. Both the resume branch and the fresh-pass branch
  of `PageCursor.from_watermark_row` treat this as equivalent to no stored position at all and
  restart the pass from scratch; this is a ONE-TIME, LOCAL-only cost, never a production
  migration concern.
- **R2-S1 (preview reports the page's real row count).** `PageResult` gained `preview_records`
  (every candidate on the page regardless of changed/unchanged status, built AFTER a document's
  changed-header lines are attached) alongside the existing change-only `records`.
  `EtlService._extract_and_map`'s preview path now maps `preview_records`; the run loop
  (`sync.py`) is UNCHANGED (`records`, still change-only). A preview run immediately after a real
  run (source unchanged, everything hashed) used to report `total: 0` for a task that plainly has
  rows - a known, ACCEPTED simplification stays: an UNCHANGED document row's `preview_records`
  entry does not carry lines (lines are only ever fetched for changed/new headers, by design) -
  no test exercises this combination today. `preview_task`'s `warnings.pagedPreview` (F1) note
  applies to the FIRST page only, same as before - a sibling-overlap warning computed from
  `current_refs` is therefore also scoped to that one page, not the whole population.
- **R2-S2 (monotone `last_modified_at`).** `watermark_row.last_modified_at` (and therefore
  `run.watermark_advanced_to`, assigned from it one line later) is now stamped from the
  MONOTONIC `top_mark`, never the pass's own `pass_mark` - a RECONCILE pass always restarts its
  OWN position from scratch, ascending, so `pass_mark` legitimately sits BELOW whatever a
  previous successful run already advanced the public watermark to for as long as this pass has
  not yet caught back up; stamping the public field from it regressed the ONE value an operator
  (and staleness monitoring) reads to ask "how fresh is this entity".
- **NIT (scheduler never records `mode='manual'`).** `_sweep_one`'s open-pass override (round 2
  F3) now clamps a continued pass's `kind` to `incremental`/`reconcile` - a continued MANUAL pass
  (an operator-triggered initial load truncated by the budget) is swept as `incremental`, never
  the operator's own `manual` verbatim (a scheduler-fired job literally recording `manual` is a
  contradiction). `build_paged_wrap`'s two `assert`s are now `SqlSourceError` guards (a caller
  fault reads as a NAMED source error, never an `AssertionError` a test/production trace would
  have to decode).
- **Known test conflicts from this round's design, reported not fixed (do not edit tests):**
  four PRE-EXISTING tests round 3 did not touch still construct `PageCursor(tie_refs=...)`/read
  `PageResult.tie_refs` directly (`test_a_pass_reads_pages_of_page_size_and_stages_each_before_
  the_next`, `test_a_filtered_out_header_is_never_a_delete_candidate_after_paging` in
  `test_autocount_sql_db_source.py`, and round 2's OWN F5 test
  `test_a_tie_group_larger_than_3x_page_size_stays_bounded_per_page` in
  `test_autocount_bulk_load_review.py`) and now raise `AttributeError` - the field no longer
  exists, per the brief's explicit "remove tieRefs ... entirely". Two round-3 `build_paged_wrap`
  unit tests (`test_build_paged_wrap_first_page_orders_by_watermark_then_key`,
  `test_build_paged_wrap_later_page_is_a_seek_predicate`) assert the SQL text
  `.rstrip().endswith("ORDER BY t.<wm>, t.<key>")` for EVERY dialect including postgresql/mysql/
  sqlite - those dialects have no `TOP`-style prefix bound, so `LIMIT :page_size` must trail
  `ORDER BY` (standard SQL syntax; `LIMIT` cannot precede `ORDER BY`), which the assertion does
  not account for (5 of the parametrized cases fail; only `mssql`, whose `TOP` is a PREFIX
  clause, passes). Two further tests regress from the page_size+1 fix's own correctness gain (an
  exact-multiple population now completes ONE PAGE SOONER than before, since it no longer needs
  a trailing all-empty confirmation page): `test_deletes_are_staged_only_when_the_reconcile_
  pass_completes` (`test_autocount_bulk_load.py`) hardcodes "2 full pages of 2, still
  incomplete" for a 4-row population at page_size 2, which now completes after page 2, not 3;
  `test_a_later_pages_empty_read_completes_normally_not_a_guard_trip` similarly assumed a
  2nd read of exactly `page_size` rows stays open, so its 3rd call becomes a FRESH pass (not a
  continuation) that legitimately trips the zero-rows guard - correct per R-NIT's own control
  case, just reached one call earlier than the test expected. An abort landing on the SAME
  statement count now lands on the pass's own FINAL (completing) page instead of a middle one
  in some fixtures - REFUTED as a gap (round 3b/4): the very next ordinary incremental tick's
  unconditional `auto_push` (it runs on every run of an ACTIVE task, new rows or not) drains
  and pushes the stranded final-page rows exactly once, the same mechanism BL-SS-095 already
  relies on for a draft/paused task once it goes active - proven by
  `test_an_abort_on_the_final_page_still_gets_pushed_by_the_next_ordinary_tick`.

**Review round 4 amendments (URGENT live-load fix + LineCount guard + S1/S2/S3/NIT):**
- **URGENT - a paged document run's `raw_json` never carried `_lines`.** A live load staged
  6,000 sales-order headers whose `raw_json` had no `_lines` key and whose canonical `lines`
  were `[]`, even though every header had lines at source. Root cause: `fetch_page` built a
  changed header's `SourceRecord.raw` via `json_safe(header)` - a dict-comprehension SNAPSHOT,
  not a live reference - INSIDE the hash-diff loop, BEFORE the separate `if self.is_document and
  changed_headers: ... header[SQL_DOC_LINES_KEY] = self._read_lines(...)` loop mutated the SAME
  `header` dict. The snapshot taken into `records` never saw the lines attached after it. Fixed
  by deferring a changed header's `SourceRecord` construction to a THIRD loop, run after the
  lines-attach loop, so its `json_safe` snapshot carries `_lines`.
- **LineCount fingerprint mismatch guard (new).** A header row carrying a `LineCount` column
  (`presets.LINE_COUNT_FINGERPRINT_COLUMN` - a plain column-name CONVENTION documented next to
  the preset queries in `presets.py`, never an engine concept: both SO/PO presets already select
  this aggregate for change detection) with a value greater than zero, whose own `lineQuery`
  fetch came back with ZERO rows, is staged FAILED (`"LineCount {n} but 0 lines fetched for
  DocKey {key}"`, D13's no-canonical-payload rule, counted in `failed_count`, never pushed) -
  never silently accepted as a valid zero-line document. `LineCount` absent, or reporting zero,
  keeps today's behaviour untouched - a real zero-line document is still valid (AC-13's rule).
  Implemented as a NEW optional `SourceRecord.error` field: when set, `_stage_documents` stages
  it FAILED WITHOUT ever calling `MappingEngine.map_document` - a pre-mapping fault the source
  itself already named, one layer earlier than a mapping-time failure, same fail-safe contract.
- **S1 (key values ride the seek bind AS-IS, never through `_decode_mark`).** `_decode_mark`
  exists to turn an ISO-looking STRING back into a real `datetime` for a WATERMARK bind - correct
  there because a watermark column genuinely is a timestamp. A KEY column is a business
  identifier that can happen to hold date-shaped TEXT (`'2026-08-01'`) which must stay exactly
  that text; reusing the mark decoder on `last_key` silently mangled it into a `datetime` a TEXT
  column could never compare against, losing the second half of a tie group. `fetch_page` now
  binds every key value verbatim (no decode step at all) - the simplest of the two options the
  review offered, since a paged task's key column is virtually always a business code/string,
  never a type `_encode_mark` would have needed to reverse to correctly compare.
- **S2 (lexicographic multi-key seek - supersedes R2-B1's `key_columns[0]`-only design).**
  `SqlDbSource._quoted_keys()` (renamed from `_quoted_key`) now returns EVERY key column, checked
  and quoted the same way as the watermark. `build_paged_wrap`'s `quoted_key`/`last_key` accept
  either a single column (unchanged, byte-identical text) or a list: `ORDER BY t.<wm>, t.<k0>,
  t.<k1>, ...` with a RECURSIVE lexicographic predicate `t.<k0> > :last_key0 OR (t.<k0> =
  :last_key0 AND (t.<k1> > :last_key1 OR ...))`, degenerating to today's exact single-key text
  (`t.<k> > :last_key`, unindexed bind name) when there is only one key column - a single-key
  task's generated SQL is unchanged byte-for-byte. `PageCursor`/`PageResult`'s `last_key` (and
  `cursor_json`'s `lastKey`, both top-level and `pass`-scoped) stays a SCALAR for a single-key
  task, becomes a LIST (one per `key_columns`, same order) for a multi-key one - pure JSON
  passthrough needed no changes elsewhere. `sync._advance_mark_and_key`'s exact-tie compare now
  uses a plain Python `>` on the raw `last_key` values instead of `decode_mark(...)` (S1's
  concern applies here too, and Python already compares two same-length lists element-by-element
  for the multi-key case, giving the right lexicographic order for free).
- **S3 (a NULL watermark or key on a page's tail row fails loudly, never loops).** The tail row
  is the one the NEXT page's seek resumes from; the old code only advanced `last_mark`/`last_key`
  "if not None", silently leaving them at the PREVIOUS page's value otherwise - the next page
  then re-runs the EXACT SAME statement forever (a livelock, not a crash: nothing ever raised,
  the run just never progressed). `fetch_page` now raises a named `SqlSourceError` naming the
  offending column (`"The watermark column '<col>' is NULL on the last row of this page..."` /
  the same for a key column) the moment it finds one NULL on the kept tail row - one statement,
  a FAILED run, the public cursor untouched (same contract as every other pre-hash-write guard
  in this file).
- **NIT (`preview_records` built only on a preview).** A real run (`persist_hashes=True`) has no
  reader for `preview_records` (R2-S1's field exists for a PREVIEW's own row count) and must not
  pay to build a second, throwaway copy of every row on every page - now gated behind `if not
  self.persist_hashes`.
- **Mid-pass-abort candidate REFUTED, removed from the backlog and this plan's round-3 amendment** (draft row BL-SS-061 on this lane, never published; BL-SS-061 on main is plan 23's frame-trace row) (folded into
  the round-3b abort-on-final-page bullet above) - the next ordinary incremental tick's
  unconditional `auto_push` drains an aborted job's stranded final page across jobs; there is no
  gap to track.

**Review round 5 amendments (sink timeout + a `keyColumns` reshape is an identity change):**
- **Sink timeout from settings.** `SorentoSink` hard-coded `timeout: float = 30.0` - a 1,000-
  record document batch with lines genuinely takes Sorento longer than 30s to ingest, so the
  ESB recorded a push FAILURE while Sorento was still processing a perfectly good batch. New
  `Settings.autocount_sink_timeout_seconds` (env `AUTOCOUNT_SINK_TIMEOUT_SECONDS`, default 300,
  floored at 30 - same pattern as `autocount_page_size`/`autocount_run_time_budget_seconds`).
  `sorento_sink_from_connection` reads it at CALL time and passes it through; `SorentoSink`
  builds an `httpx.Timeout` with a short, fixed `SINK_CONNECT_TIMEOUT_SECONDS` (10s - a dead
  endpoint should fail fast) and the setting on read/write/pool (the phases that actually wait
  for a slow-but-alive Sorento).
- **A `keyColumns` reshape is an IDENTITY change, not just a resumability question.**
  `source_ref`'s own scheme is built from `key_columns` - a reshape (grown, shrunk, or a
  same-count rename) makes every EXISTING `ac_row_hash` ref read as "not seen this pass" under
  the NEW scheme, so an ordinary reconcile staged a PHANTOM DELETE for every one of them (proven
  by a real reconcile run in `test_a_key_columns_reshape_never_resumes_a_stale_top_level_
  position`, parametrized grow/shrink/rename). Two halves, mirroring the existing watermark-
  column SAVE-time/RUN-time pair:
  - **SAVE-time (`EtlService.update_task`).** A `keyColumns` change now clears the entity's
    `ac_row_hash` rows for EVERY entity type (previously document-only, via the F1 narrowed-
    population check, which never covered a master at all). The existing pass-clearing block
    also now clears the TOP-LEVEL `sqlWatermark`/`lastKey` (not only `cursor_json["pass"]`)
    whenever `keyColumns` OR `watermarkColumn` changes - a schedule-only or narrower-scope-only
    edit still clears `pass` alone, since it does not change what the same column/key means.
  - **RUN-time (`sync.py`'s `_run_paged_sql_db`, for a `source_config` edited directly,
    bypassing `update_task`).** A new `CURSOR_KEY_COLUMNS` (`sqlKeyColumns`) fingerprint is
    written into `cursor_json` alongside `sqlWatermarkColumn` on every write. At the top of every
    run, a stored fingerprint that does not match the task's CURRENT `key_columns` clears the
    entity's hashes and resets the whole cursor (`sqlWatermark`/`lastKey`/`pass`, and
    `AcWatermark.last_modified_at` itself, all `None`, so the public "watermark at" surface never
    reads ahead of a pass that has not actually re-verified anything yet) for a genuinely fresh,
    adds-only pass. A `None` stored fingerprint (a row that has never run under this check) is
    treated as "unknown, assume unchanged" - never a spurious reset for an untouched task, and a
    harmless one-time bootstrap cost for a task that genuinely did reshape before this code
    shipped. One consequence of that bootstrap rule is worth calling out explicitly: a task whose
    `keyColumns` changed BEFORE this release carries no fingerprint at all, so the very first run
    after upgrade cannot tell "always been this shape" apart from "just reshaped" - both ref
    schemes' hashes sit in `ac_row_hash` at once, and the next reconcile fails LOUDLY on the
    delete-guard threshold (never a silent phantom-delete wave) until the task is re-saved once
    (via `update_task`, which clears unconditionally on any `keyColumns` diff regardless of
    fingerprint history) to re-baseline cleanly. Separately, a reshape's reset is ADDS-ONLY by
    design (S2's own point: the old scheme's rows are not evidence of deletion, just of a
    different identity) - rows already pushed to Sorento under the OLD ref scheme are never
    retracted or re-pushed under the new one, so a reshaped task's Sorento-side history keeps
    both schemes' entries side by side; this is operator-visible and expected, not a bug.
  - **S2-a (second line of defence, `PageCursor.from_watermark_row`).** A stored `lastKey` whose
    SHAPE does not match `len(key_columns)` (scalar vs list, or a list of the wrong length) is
    treated as no stored position, in both the resume and fresh-pass branches - never threaded
    through a `list()` call that would slice a stored STRING into individual characters. This
    guards the case the identity reset does not (a same-count rename that a fingerprint mismatch
    already catches independently, and any residual bad bind if the reset were somehow
    bypassed).
- **Docstring nits.** `_line_count_mismatch` now notes why it deliberately ignores a PARTIAL
  mismatch (the `LineCount` aggregate is `ItemCode IS NOT NULL`-filtered; an operator's own
  `lineQuery` is not, so a skew in either direction is expected and not a broken join - only
  `expected > 0` with `fetched == 0` is unambiguous). The S1 key-bind comment now notes the
  accepted non-str/int asymmetry: a stored key already went through `_encode_mark` for JSON-
  safety (`Decimal` -> str, `bytes` -> hex) and rides back out AS-IS, so a non-str/int key column
  binds as that stringified/hex text, not its native type - accepted because a paged task's key
  column is virtually always a business code or a plain int.

**Review round 6 amendments (S5 performance - concurrent line fetch + sink push concurrency):**
- **S5 (concurrent line fetch).** A live pass over ZeroTier (~25ms RTT) spent ~60s per page on
  2,000 sequential line queries - one `_read_lines` call per changed header, always waiting for
  the previous one's round trip before starting the next. `SqlDbSource._attach_lines` (called
  from the same "LINES ONLY FOR CHANGED/NEW HEADERS" spot in `fetch_page`) now fetches up to
  `settings.autocount_line_fetch_workers` (env `AUTOCOUNT_LINE_FETCH_WORKERS`, default 4, bounds
  1..8) headers' lines CONCURRENTLY, each worker opening its OWN `open_readonly` connection off
  `self._engine` (`_read_lines_own_connection`) - never the page's own shared connection, which
  is a single DB-API object and unsafe across threads. Results are attached back onto each
  header in the SAME order `changed_headers` already has, so the page's `records`/`hashes` stay
  byte-identical to the sequential path regardless of finish order - only wall-clock time
  changes (`test_workers_one_matches_workers_four_byte_for_byte`). One header's line query
  failing still fails the WHOLE page exactly like before (whatever `_read_lines` raises bubbles
  straight out of `fetch_page` - nothing staged, the top-level cursor untouched); any other
  header's future still queued (not yet started) is cancelled rather than left to make a wasted
  call. `workers <= 1` OR a single-connection pool (`StaticPool` - the in-memory SQLite rig every
  other test in this suite uses) both fall back to the OLD sequential loop over the page's own
  connection - a second `open_readonly` against a `StaticPool` engine while the first is still
  open would deadlock or corrupt the shared cursor, never run genuinely in parallel.
  `runtime.py`'s `engine_for` bumps `pool_size` to `max(2, workers)` (read at engine-construction
  time, same as `query_timeout`) so a high worker count can never starve the pool waiting for a
  connection the header page's own read already holds. `MAX_DOCUMENT_LINES_PER_HEADER` is
  unchanged (still enforced per header, inside `_read_lines` itself, worker or not).
  `BL-SS-090` (batched line fetch - one `IN` query per page of DocKeys) stays open as the
  alternative approach this round did not take (fewer round trips per page rather than more
  connections in flight) - either can land later without conflicting with the other.
- **S5b (sink push concurrency).** `SorentoSink.write_batch` chunked its POSTs at
  `SORENTO_MAX_BATCH` SEQUENTIALLY, always waiting for one chunk's response before starting the
  next. `settings.autocount_sink_concurrency` (env `AUTOCOUNT_SINK_CONCURRENCY`, default 1,
  bounds 1..4) lets up to N chunk POSTs run with real overlap via a small `ThreadPoolExecutor` -
  the sink holds no DB session at all (a pure HTTP client wrapper), so this never crosses a
  SQLAlchemy session across threads; each worker only performs the HTTP call and returns the
  parsed body, the calling thread still builds every `WriteResult`. The ALL-OR-NOTHING contract
  is UNCHANGED at every concurrency level (a deliberate ruling, superseding an earlier "keep
  already-succeeded chunks' verdicts" framing that would have changed `write_batch`'s own
  return contract): `write_batch` returns verdicts ONLY once every chunk has succeeded, in
  submission order - one chunk failing (a transport error, a 5xx, a rate-limit exhaustion) never
  applies a verdict to ANY row, even one from an already-completed sibling chunk, and propagates
  the exact same exception a purely sequential loop always raised;
  `SyncService._auto_push_upserts`'s existing generic `except Exception` handler (`"The push
  failed before the consumer resolved it"`) needed no changes at all. Concurrency 1 is
  byte-identical to before this round (same request order, one POST in flight). Ops note:
  default stays 1 - an operator raises `AUTOCOUNT_SINK_CONCURRENCY` only once the RECEIVING side
  has confirmed it can take concurrent batches (a per-connection-serialised commit or an
  aggressive rate limit on their end would turn "faster" into "more 429s/5xxs", the opposite of
  the intent).

**Review round 7 amendments (reviewer polish, no blocker):**
- **Pool headroom for two concurrent paged tasks.** `runtime.py`'s `engine_for` now sizes
  `max_overflow` as `workers + 3` (was a flat `3`) alongside its existing `pool_size=max(2,
  workers)` - a real deployment runs more than one entity task at a time, and a flat overflow
  sized for ONE task's worker pool could starve a SECOND task sharing the same connection
  waiting for the first task's connections to come back.
- **`SingletonThreadPool` joins the single-connection fallback guard.** `SqlDbSource._attach_
  lines` already fell back to the old sequential loop for `StaticPool` (the in-memory SQLite
  test rig); it now also recognises `sqlalchemy.pool.SingletonThreadPool` (the pool a bare
  `sqlite://` URL defaults to without an explicit `poolclass`) - same one-connection-per-thread
  ceiling, same deadlock risk under a real worker pool, same fallback.
- **Ops notes next to the S5/S5b settings.** Changing `AUTOCOUNT_LINE_FETCH_WORKERS` needs a
  BACKEND RESTART to take effect on an already-running connection - `runtime.py`'s `engine_for`
  reads the setting once, at engine-CONSTRUCTION time, and a pool is not resizable after it is
  built (the engine cache only rebuilds on a credential/config fingerprint change, never on a
  bare settings edit). At `AUTOCOUNT_SINK_CONCURRENCY > 1`, Sorento's 429 retry budget
  (`_max_rate_limit_waits`) is PER CHUNK, with no GLOBAL backoff across the chunks in flight
  together - N concurrent chunks each independently retrying a 429 can still hit Sorento N times
  over the same window, never coordinated into one shared wait.
- **`BL-SS-096`** (new, `documentation/backlogs/backlog.md`) - `write_batch` opens a fresh
  `httpx.Client` per chunk (`_call`'s `with httpx.Client(...) as client:`), so a multi-chunk push
  pays a TLS handshake per chunk instead of reusing one connection-pooled client across the
  whole batch. Low priority, out of this round's scope (the concurrent path already parallelises
  the handshakes rather than serialising them, which is most of the win) - tracked for later.

**Prod fix (fix/push-marks-per-chunk, 2026-09-07) - supersedes round 6's S5b "unchanged
all-or-nothing" ruling:**
- **The ALL-OR-NOTHING contract that round 6 deliberately kept is the prod bug.** Sorento's
  `api_call_log` over 6h of the sales_order task: ~657 requests x 200 = ~131k offers for 23k
  distinct SOs (~5 offers per document) - a lone 502 from Sorento's OWN nginx (upstream
  momentarily unreachable, never reaching their app) on roughly 1 in 25 chunk POSTs discarded
  every OTHER chunk's already-delivered verdict too, so the next run re-offered rows Sorento had
  already accepted `created`/`updated`. `write_batch`/`delete_batch` now take an `on_chunk`
  callback invoked once per chunk as it resolves; `SyncService._auto_push_upserts`/`_auto_push_
  deletes` mark + COMMIT that chunk immediately, so a LATER chunk's fault can never undo an
  EARLIER chunk's delivery. A TRANSIENT 5xx (502/503/504 only, `settings.
  autocount_sink_retry_attempts`, default 3, bounded backoff via `time.sleep`) is retried in
  place; a chunk that still fails after exhausting its attempts fails ONLY that chunk and the
  loop continues to later chunks - a plain 500 (still a guard-rail error until the companion
  Sorento fix lands), a 4xx, an anchor error or a bare transport fault is NOT retried and stops
  the whole push immediately, unchanged from round 6's posture for those cases. The summary (and
  `ac_sync_run.requests`/`requests_failed`/`first_failure`, migration `0015`) now accounts for
  how many chunk POSTs a run made and which one failed first - the Runs list previously showed
  `pushed_count 0` / `error NULL` with no way to tell a chunk-level fault had even happened.
  `ac_staged_record.last_offered_at` (same migration) + `list_pending_for_entity`'s `last_offered_at`
  NULLS-FIRST ordering guard against a permanently-`retryable` head of the oldest-first queue
  starving fresh rows behind it forever, now that a partial-batch outcome is common rather than
  rare. **Merge order: fix/job-lease-orphan-sweep (adds its OWN `write_batch(on_chunk=)` for a
  liveness heartbeat, in review, not yet merged at the time of this fix) must merge FIRST** - the
  two `on_chunk` shapes need folding into one signature (this lane's carries `(chunk_records,
  chunk_results_or_None, error_or_None)`; job-lease's is a zero-arg heartbeat tick) with the
  heartbeat folded into the richer callback, not the other way round.

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

**Review round 2 amendments:**
- **F3 (reconcile continuation + monotone top-level mark).** The TOP-LEVEL `sqlWatermark`/
  `tieRefs` pair (the public, cross-mode resume position a plain incremental/manual pass reuses)
  now advances per page for a manual/incremental pass exactly as before, but for a RECONCILE
  pass it is frozen until the WHOLE pass completes, then advances ONCE via a monotonic
  max-or-merge (`sync._merge_pass_completion_into_top_mark` - never backwards; an exact tie
  between the frozen position and the just-finished pass's own frontier merges their tie-ref
  sets rather than one silently replacing the other). The pass's OWN live per-page position now
  lives ONLY in `cursor_json.pass.mark`/`pass.tieRefs`/`pass.rowsScanned` (new, pass-scoped keys)
  - `PageCursor.from_watermark_row`'s RESUME branch reads from there, never from the top-level
  pair. `scheduler._sweep_one` also gained an open-pass override: an incomplete pass's own
  `kind` wins over whichever schedule field (`next_incremental_at`/`next_reconcile_at`) is
  actually due this tick, so a reconcile mid-pass is continued as a reconcile even on a tick the
  incremental cadence woke. A truncation still re-arms `next_incremental_at` to now regardless
  of which mode truncated (unchanged from the original design - the shorter cadence wakes the
  next tick; the scheduler's open-pass override is what makes that tick run the CORRECT mode).
- **F4 (resume after a watermark-column/population change).** `PageCursor.from_watermark_row`'s
  RESUME branch now applies the SAME `cursor[CURSOR_COLUMN] == watermark_column` check the
  fresh-pass branch already had - a stored pass whose column no longer matches starts fresh
  rather than resuming with a stale, cross-column mark. `EtlService.update_task` also clears
  `cursor_json.pass` outright (save-time backstop, ANY `sql_db` entity, not just documents) when
  `watermarkColumn` or any `POPULATION_DEFINING_KEYS` field changes.
- **R-S1 (stale delete-intent cancellation on every page).** `StagedRecordRepository.
  discard_stale_deletes` now runs on EVERY page of EVERY mode (using that page's own fetched
  refs), not only once at reconcile completion - an incremental run that reads a reappeared ref
  cancels its stale parked delete intent immediately.
- **R-S4 (no full-population snapshot for the guard rollback).** `RowHashRepository.upsert_many`
  now returns the refs it genuinely INSERTED (a lookup already scoped to just that page's
  refs, free); the run loop accumulates these into `new_this_run` instead of diffing against a
  `all_hashes()` snapshot of the WHOLE population taken at the start of every run.
- **R-S7 (progress total before staging).** `JobService.set_total` is now called with the
  RUNNING total before each page's `_stage_documents` call, not once after the whole (possibly
  many-page) run.
- **R-NIT (zero-rows guard, pass-cumulative).** The zero-rows delete guard moved OUT of
  `fetch_page` (which used to re-check it on every page, misfiring on a normal LATER page whose
  own read empties out near the end of a pass) and into the run loop's post-loop
  reconcile-completion check, keyed on `cursor_json.pass.rowsScanned` accumulated ACROSS every
  run of the pass (not just this run) - it only fires when a COMPLETED pass scanned zero rows in
  total while a known population exists.
- **NITs.** `db.query(AcStagedRecord)...delete()` in the guard-rollback path now goes through
  `StagedRecordRepository.discard_for_job`; `SqlDbSource._source_ref` is now the public
  `source_ref`; `_decode_mark` gained the public alias `decode_mark` (`sync.py` imports that,
  not the underscored name); `EtlTaskResponse.initialLoad` is now the typed
  `InitialLoadProgress` model instead of a bare dict; the paged branch now writes
  `ACTIVITY_SUCCESS`/`ACTIVITY_ERROR` rows exactly like the legacy branch (F7).

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

A preset SQL change (like the `ItemCode IS NOT NULL` fix above) does NOT reach an already-
configured live task on its own - `presets.py` only seeds a NEW task's `source_config`. An
operator with an existing task must re-apply "Use preset" (or hand-edit `query`/`lineQuery`) per
task to pick it up; either path is a population-defining edit, which clears every row's stored
hash (BL-SS-097) and so defers the fresh baseline to the NEXT reconcile pass rather than the
current run - a forced reconcile should follow the edit, not be assumed automatic. Tonight's
instance: the real company's SO/PO/SPO `lineQuery` were hand-edited to the same
`ItemCode IS NOT NULL AND Qty IS NOT NULL` filter and a reconcile pass driven for each.

### 2.6 Wire (`schemas.py`, `etl_service._task_view`, FE label)

- `EtlTaskResponse.initialLoad: Optional[{complete: bool, pagesDone: int, lastMark: str|null,
  kind: str}]` derived from `cursor_json.pass` (null when no pass is open).
- `SyncRunItem` already carries `truncated` + `error`; the FE run list (`autocount` task runs
  table) renders `truncated` as the status label "Partial, continues" (one component change,
  inline, no mock phase - trivial).

### 2.7 Files

- `service_backend/app/config.py` (+5 settings, validators - `autocount_page_size`,
  `autocount_run_time_budget_seconds`, round 5's `autocount_sink_timeout_seconds`, and the S5
  performance round's `autocount_line_fetch_workers`/`autocount_sink_concurrency`)
- `service_backend/modules/autocount/sql_source/source.py` (paged wrap, `fetch_page`, hash diff
  before lines, cap removal, S5's `_attach_lines`/`_read_lines_own_connection` concurrent line
  fetch), `sql_source/errors.py` (drop `SqlDocumentCapExceeded`), `sql_source/runtime.py` (S5 -
  `engine_for`'s pool size fits the configured worker count)
- `service_backend/modules/autocount/sync.py` (page loop, change-only staging, watermark rule,
  seen stamps, deletes at completion, round 5's keyColumns-reshape identity reset)
- `service_backend/modules/autocount/sinks_sorento.py` (round 5 - `SorentoSink`'s HTTP client
  timeout follows `settings.autocount_sink_timeout_seconds`, connect phase stays short; ops
  note: a slow-but-alive Sorento ingesting a large document batch used to record a push FAILURE
  at the old hard-coded 30s even though the batch itself was fine - retune
  `AUTOCOUNT_SINK_TIMEOUT_SECONDS` (default 300s, floor 30s) instead of changing code. S5b -
  `write_batch` sends up to `settings.autocount_sink_concurrency` chunk POSTs with real overlap,
  same all-or-nothing contract at every concurrency level; ops note: default stays 1
  (byte-identical to the old fully sequential loop) - raise `AUTOCOUNT_SINK_CONCURRENCY` (max 4)
  only once the RECEIVING side has confirmed it can take concurrent batches, since a rate limit
  or per-connection-serialised commit on their end would turn "faster" into "more 429s/5xxs".
  `fix/sorento-batch-size` (2026-09-06) - records per ingest POST are now
  `AUTOCOUNT_SINK_BATCH_SIZE` (default 200, bounded 1..1000 = Sorento's per-request ceiling,
  read at call time), after a 1,000-record purchase_order batch with per-record supplier
  back-create ran past Sorento production nginx's 60s proxy timeout and came back 504; ops
  note: lower it further for a slow consumer before touching the timeout, raise it only with
  Sorento's agreement - the 1,000 ceiling is theirs. A smaller batch means MORE chunks per push,
  and two costs are per chunk: a fresh `httpx.Client` + TLS handshake each (BL-SS-096, now Medium -
  5x the chunk count at the new default) and the 429 retry budget `_max_rate_limit_waits`
  (per chunk, uncoordinated across chunks in flight, see the S5b ops note above) - so at the
  200 default expect roughly five times the handshakes and five times the independent 429
  retries of the old 1,000-record chunking for the same population)
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

- BL-SS-090 Batched line fetch (one `IN` query per page of DocKeys) - N+1 bounded per page today.
- BL-SS-091 Operator "reset baseline" action (clear `ac_row_hash` for one task) - psql today.
- BL-SS-092 Push cap per run as a setting (5,000 today).
- BL-SS-093 Sink drops the consumer `warnings` key (tester BL-D).
- BL-SS-094 Preview does not count mapping-failed rows (tester BL-B/BL-C).
- BL-SS-095 A DRAFT/paused paged task's page-in-flight abort can strand staged rows forever
  (security review round 2, F2 - investigated, not fixed; see the 2.1 amendment above).
- BL-SS-096 `SorentoSink.write_batch` opens a fresh `httpx.Client` per chunk - a TLS handshake
  per chunk instead of one connection-pooled client reused across the whole batch (review round
  7 polish; see the round 7 amendment above).
- BL-SS-129 `test_auto_push_one_failing_chunk_keeps_the_other_chunks_verdicts_at_any_concurrency`
  (round6b) flakes ~30-40% under concurrency 3 - the shared fixture's 30 staged rows share one
  `created_at` (SQLite second resolution), so the "second chunk" assumption depends on an
  effectively-random UUID tie-break. Reported, not fixed (tests are the tester's) - see the fix
  above's amendment.
- BL-SS-130 Fixed by this lane (fix/push-marks-per-chunk) - see `documentation/backlogs/
  backlog.md` for the full prod-numbers writeup; superseded round 6's "unchanged all-or-nothing"
  ruling.
