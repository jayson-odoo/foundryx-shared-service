# 13 - AutoCount stock balance auto-push (plan 10 slice S7, BL-SS-207) - User Acceptance Criteria

Plan: `13-autocount-stock-push.md`. Lane `sprint-5/13-autocount-stock-push`, worktree
`.claude/worktrees/s51` off `origin/main` 4ddc50e2 (module 0.11.0, module Alembic head
`0022_autocount_preview_job`). Lane ports backend :8013 / frontend :3013, DB
`foundryx_service_s51`, Redis db 13.

Owner intent (2026-09-25): stock balance leaves the human-checked pull period and gets the SAME
"Push | Pull on request" choice every other pull-capable entity has. The owner flips it himself,
per company book (`SRT`, `MCH`) and per entity, on the Schedule tab, and sets a 5-minute cadence.
Products must be flippable by the owner too. Sorento ships the `stock_balances` ingest entity as
contract 2.5 (their SR5, Appendix A of the plan).

## Owner rulings (locked, 2026-09-25)

- **R1 - Route B.** Stock balance gets the same Push | Pull-on-request toggle as products, opened
  by the consumer contract (>= 2.5 with `stock_balances` advertised), flipped by the owner per book.
  Products are flippable by the owner as well; if nothing blocks that today it is a runbook step.
- **R2 - no "Stock List" xlsx on the push path.** n8n / chatbot read Sorento's stock table
  directly. The pull path is unchanged.
- **R3 - cadence is operator-configured on the Schedule tab** (`incrementalMinutes` +
  reconcile); the owner sets 5 minutes. The balance endpoint has no watermark, so every run is a
  full walk and the overlap guard skips a tick while one is in flight.
- **R4 - pairs in Sorento-INACTIVE warehouses keep shipping** (plan 10 R7). Sorento answers
  `updated` + warning `warehouse_inactive` and writes nothing; never `failed`.
- **R5 - a nonzero unresolved-UOM exclusion blocks the whole book's stock push** (`EXCLUDED_NONZERO`,
  AC-13-12). Sorento carries one unit only. Per-pair hold deferred (BL-SS-270, Low).
- **R6 - the owner flips products and stock himself and chooses the order.** The runbook notes the
  dependency (stock pairs for items Sorento lacks stay `retryable` until products push) without
  mandating an order.
- **R7 - push writes `quantity_on_hand` ONLY**; reserved and damaged are never touched by push
  (Appendix A3 of the plan).
- **R8 - ~13k wrapper requests per book per day at 5 minutes is accepted.**
- **R9 - the overlap guard's skipped Runs rows at 5 minutes are accepted for now** (BL-SS-266, Low).
- **R10 - SR5b skipped.** Sorento keeps the stock Pull button and manual stock Excel import visible
  for every company; the owner avoids them on pushed books (owner discipline, BL-SS-265, Low).

## Verified baseline (planner, 2026-09-25, cite when testing)

- `sinks_sorento._ENTITY_PATH` (`sinks_sorento.py:94-113`) has no `stock_balance` entry, so
  `SorentoSink.__init__` raises (`:473-477`) and `sorento_supports_entity` answers `False` at any
  contract (`:202-203`). Three plan-10 tests pin that and are inverted by this plan on purpose:
  `tests/test_s10_s5b_registration.py:235`, `:240`, `:250`. A fourth,
  `test_switching_a_stock_task_to_push_is_allowed_once_the_contract_reports_2_5` (`:319`), keeps its
  assertion but its rig must add a READY snapshot, because AC-13-31's `no_snapshot` gate now
  refuses the flip without one.
- `CanonicalStockBalance.sink_payload()` (`canonical/masters.py:339-389`) already emits exactly
  `source_ref, item_code, item_description, location_code, uom_code, qty` with `qty` a JSON
  integer and `None` omitted; `SorentoSink._to_records` (`sinks_sorento.py:519-546`) calls it with
  no arguments for any non-document record. No serializer work is needed.
- The backend push gate already exists and is a REFUSAL:
  `CompanyService.stock_push_gate_error` (`services/company_service.py:1055-1137`, version >= 2.5
  AND `stock_balances` in `entities`) guards `EtlService.set_delivery_mode`
  (`services/etl_service.py:2905-2966`) and `activate_task` (`:2862-2876`).
- The frontend gate is NOT backend-driven: `schedule-tab.tsx:93` reads the hardcoded
  `AC_PULL_ONLY_ENTITY_TYPES = ['stock_balance']` (`autocount-meta.ts:238`), so AC-10-15's "opens
  with no code change" is false on the frontend today.
- A watermark-less HTTP task is ALREADY a full diff on every run regardless of `mode`:
  `full_extract = self.mode == RUN_MODE_RECONCILE or not self.watermark_field`
  (`http_source/source.py:1025`), so `known` = every stored hash and `delete_refs` is computed on
  every run (`:1105-1167`).
- The reconcile state table is `ac_row_hash` (`models.py:304-325`); there is no
  `ac_reconcile_state`. The pull build writes none (`persist_hashes=False`, plan 10 D6), so a stock
  task flipped today would start with zero known refs.
- BL-SS-238 is live: `_stage_documents` (`sync.py:1037-1209`) stages every mapped record on every
  run, and `list_pending_for_entity` caps a push at 5,000 rows
  (`repositories/autocount_repository.py:592-661`). At a 5-minute stock cadence that re-offers
  ~5,000 unchanged pairs per run, forever.
- The no-watermark incremental floor is 15 minutes (`services/etl_service.py:179-180`, `:1653-1663`;
  frontend mirror `lib/autocount-etl.ts:306-318`), so the owner's 5 minutes is refused today.
- The Activate tab offers Re-push only for `sourceImpl === 'sql_db'`
  (`activate-tab.tsx` ~`:135-142`) although `EtlService.repush_task` accepts `autocount_http`
  (`services/etl_service.py:3133-3136`).
- Product push is possible on prod today: Sorento prod contract is 2.4
  (`PRODUCT_CODE_WINS_CONTRACT_VERSION = 2.4`, `sinks_sorento.py:165`), product deletions carry
  `codes` when the probe confirms >= 2.4 (`services/sync_service.py:986-998`), and
  `set_delivery_mode` accepts `product -> push` with no extra gate.

## Group A - sink and contract (`[BE]`)

- **AC-13-01 [BE]** `_ENTITY_PATH[ENTITY_STOCK_BALANCE] == "stock_balances"`. A `SorentoSink`
  for `stock_balance` constructs and POSTs to `/api/v1/external/ingest/stock_balances`
  (deletions to `/ingest/stock_balances/deletions`), carrying `companyCode` first like every entity.
- **AC-13-02 [BE]** `sorento_supports_entity("stock_balance", ...)` is contract-gated exactly like
  `brand`: `True` only when `contract_version >= 2.5` AND `"stock_balances"` is in
  `contract_entities`; either unknown reads `False`. `brand` behaviour is byte-identical (its
  existing tests stay green). `sorento_supported_entities_label()` excludes every contract-gated
  entity (brand AND stock balance).
- **AC-13-03 [BE]** Payload parity: for the S0 fixture records, `SorentoSink._to_records` output
  equals `13-fixtures/stock_balances-ingest-request.json` `records` byte for byte (sorted-key JSON
  compare): exactly the six `SINK_FIELDS`, `qty` a JSON integer (never a string, never a float),
  `None` keys omitted, `source_ref` = `{databaseName}:{item_code}|{location_code}`.
- **AC-13-04 [BE]** Verdicts: `stock_balance` joins `_DEPENDENT_ENTITIES`; a `retryable` verdict
  stays STAGED and its message names the product ("its product has not synced yet"), not "category
  or unit of measure". `updated` + `warnings: ["warehouse_inactive"]` or `["warehouse_unresolved"]`
  is DELIVERED and counted in the run summary's `warningCounts`. `failed` quarantines (existing
  rule). Driven by `13-fixtures/stock_balances-ingest-response.json`.
- **AC-13-05 [BE]** Deletions carry `pairs`: `{ref: {"item_code", "location_code"}}` derived from
  the ref (split once on the first `:`, the suffix must split on `|` into exactly two non-empty
  parts), only when the task's `keyFields` are exactly `("item_code", "location_code")`, restricted
  per chunk to that chunk's refs, omitted when empty (mirrors `codes_from_refs`,
  `sinks_sorento.py:242-267`). `deleted` / `not_found` mark the intent PUSHED and drop its row hash
  (existing `sync_service.py:943-955`). Body parity with `13-fixtures/stock_balances-deletions-request.json`.
- **AC-13-06 [BE]** `CompanyService.sink_for_company` builds a `SorentoSink` for stock only when
  the live contract probe passes (same branch shape as brand, `company_service.py:884-896`);
  otherwise it returns the logging sink, so a PULL-mode stock task's preview is unchanged. BUT
  `SyncService.auto_push` refuses to deliver `stock_balance` through that logging fallback when the
  company's `sink_impl` is `sorento`: summary `errorCode = "CONTRACT_GATE"`, a named error on the
  task, every row stays STAGED, nothing is marked PUSHED.

## Group B - push run semantics (`[BE]`)

- **AC-13-10 [BE]** Every stock push run is a full hash-vs-hash diff whatever its `mode`: an
  `incremental`-mode run in which one previously-delivered pair has dropped to zero (or negative)
  stages exactly ONE `op='delete'` intent for it. No code change - pinned by test against
  `http_source/source.py:1025`.
- **AC-13-11 [BE]** Changed-only staging (closes BL-SS-238) for EVERY `autocount_http` task: a
  mapped record is staged only when its ref is in the source's changed set (added or hash-changed
  this run) OR its canonical differs from the last PUSHED canonical for that ref (or it has none).
  Pinned cases: (a) an unchanged, already-delivered pair is not staged and costs no sink request;
  (b) a qty-only change stages exactly one record; (c) after Re-push (hashes cleared) every record
  stages; (d) a change whose run failed after the fetch (hashes already written, nothing staged) is
  staged on the next run; (e) enabling a mapping row that changes the canonical re-stages the
  affected records with no Re-push; (f) control: a `sql_db` task's staging is byte-identical to
  before (its source reports no changed set).
- **AC-13-12 [BE]** Fail closed on unresolved quantity: when the entity profile carries
  `excludedNonzeroCountAs` (stock only) and the run's combine exclusions yield
  `excludedNonzeroCount > 0` (`apply_pull_metadata_map`, `http_source/combine.py:903-946`), the push
  run fails BEFORE staging with `error_code = "EXCLUDED_NONZERO"` naming the count and the first
  reason; nothing is staged, nothing is pushed. Control: exclusions whose `measure` is exactly `0`
  (the live db1 case, 5 rows) never block. The whole-book block is the owner's ruling (R5), not a
  per-pair hold.
- **AC-13-13 [BE]** Truncation never deletes: on a full-extract run whose walk is not verified
  complete (main `rows_scanned != reported_total` on a paged endpoint, or any lookup
  `verified == False`) NO delete intent is staged; upserts still stage; `run.truncated = True` and
  one activity note names the unverified endpoint(s). The completeness rule is ONE helper shared
  with `_run_pull_snapshot` (`sync.py:2778-2792`), whose snapshot `complete` value is unchanged.
- **AC-13-14 [BE]** The existing delete guard applies unchanged: a stock run that would delete
  more than `max(20% of known, 50)` pairs fails `DELETE_GUARD` with nothing staged
  (`http_source/source.py:1146-1167`).
- **AC-13-15 [BE]** Excluded and dropped rows are never staged: a combine `require` exclusion and a
  `zero` / `negative` drop never produce an `ac_staged_record`; a dropped pair that was previously
  known produces a delete intent (Sorento sets qty 0).
- **AC-13-16 [BE]** Run history needs no new column and no migration: `fetched_count` = the full
  delivered set of the walk, `added_count` / `updated_count` from the hash diff, `staged_count` =
  changed records + delete intents, `pushed_count` / `deleted_count` / `failed_count` as today, and
  the job result carries `unchangedSkipped` (count) beside the existing `warningCounts`.

## Group C - cadence (`[BE]`)

- **AC-13-20 [BE]** `MIN_INCREMENTAL_MINUTES_NO_WATERMARK = 5` (was 15), backend
  (`services/etl_service.py:180`) and frontend mirror (`lib/autocount-etl.ts:308`) together:
  saving 4 minutes on a no-watermark task 422s `incrementalMinutes` naming 5; 5 saves;
  `next_run_times` clamps to 5.
- **AC-13-21 [BE]** Overlap guard at 5 minutes (existing AC-22-14 mechanics, pinned for this
  cadence): with a run in flight at the next due tick, the sweep writes one `RUN_MODE_SKIPPED` row
  and advances `next_incremental_at` by 5 minutes; the first due tick after the run finishes fires.
  The effective cadence of a 6-minute walk is therefore 10 minutes, and that is stated in the
  runbook, not changed. The skip rows and the resulting wrapper load are accepted (R8, R9).

## Group D - the flip and its baseline (`[BE]`)

- **AC-13-30 [BE]** The task view gains `pushGate` (camelCase, `schemas.py` beside `contractGate`):
  `null` = Push may be chosen; `{"version", "requiredVersion": 2.5}` when the contract gate is shut
  (the existing `stock_push_gate_error` dict, `reason: "config_error"` kept when present);
  `{"reason": "no_snapshot"}` when the contract passes, the task is in `pull`, and no READY,
  unexpired snapshot exists for (company, stock_balance). Always `null` for every other entity.
- **AC-13-31 [BE]** `set_delivery_mode(stock_balance, push)` refuses with 422 `deliveryMode`
  naming the missing prerequisite when `pushGate` is non-null (contract first, then
  `no_snapshot`). Nothing changes on refusal.
- **AC-13-32 [BE]** Baseline seed (revised in review round 2, coordinator ruling, latest snapshot
  only): a `pull -> push` flip, for ANY pull-capable entity, whose task holds ZERO `ac_row_hash`
  rows seeds one row per distinct `source_ref` found in the SINGLE latest-`extracted_at` READY,
  unexpired snapshot of that (company, entity) triple (never the union of every ready snapshot),
  `row_hash = "seed:<snapshot_id>"`, in the same commit as the mode change. A task that already
  holds hash rows is never seeded or overwritten. Stock requires at least one such snapshot
  (AC-13-31); products seed when one exists and flip without one otherwise.
- **AC-13-33 [BE]** First run after a seeded flip: every current ref is staged (seeded refs read as
  changed), every seeded ref absent from the extract stages a delete intent, and the delete guard
  still applies. Drains across runs under the existing 5,000-row offer cap.
- **AC-13-34 [BE]** A `push -> pull` flip clears the task's `ac_row_hash` rows (the SAME
  `RowHashRepository.clear_all` Re-push uses) so a later re-flip re-seeds from snapshots rather
  than diffing against hashes the pull period made stale. Mapping rows, `source_config` and
  `result_columns` stay byte-identical (AC-10-14 unchanged).

## Group E - operator surfaces (`[FE]`)

- **AC-13-40 [FE]** Schedule tab: the Delivery `ToggleGroup` renders when `task.pushGate` is
  `null`. When it is non-null, a read-only `StatusBadge` shows the CURRENT delivery mode and one
  warning line names the missing prerequisite ("Consumer contract 2.4 - stock push needs 2.5." /
  "Push needs a stock snapshot from the last 24 hours."). No entity list is hardcoded:
  `AC_PULL_ONLY_ENTITY_TYPES` / `isPullOnly` are removed and every caller reads `pushGate`.
- **AC-13-41 [FE]** Choosing Push reveals the cadence controls with their saved values; the
  no-watermark floor mirror is 5 (4 shows the inline error, 5 is accepted). Dirty guard is the
  shell's AlertDialog (existing).
- **AC-13-42 [FE]** Review & Activate tab: the banner keeps its per-mode copy (AC-10-17); the
  stock "preview unavailable" state keys off `pushGate` instead of `isPullOnly`; Re-push is offered
  for an active or paused `autocount_http` task exactly as for `sql_db`.
- **AC-13-43 [FE]** Companies > Entities list: the existing Delivery column
  (`use-entities-list-config.tsx:334-341`) shows "Push" for a flipped stock task. No code change;
  pinned by the E2E run.
- **AC-13-44 [FE]** Layering: `types/autocount.ts` (`pushGate`) -> `services/autocount-service.
  {ts,mock,real}.ts` -> existing hooks -> UI. The mock (tagged `PHASE 1 MOCK`) serves all three
  gate states (open / contract / no_snapshot) and is swapped to real in S3.
- **AC-13-45 [FE]** Every touched surface is usable and unclipped at ~375px and ~1280px.

## Group F - browser evidence (`[E2E]`, agent-browser only, real clicks from the sidebar)

- **AC-13-50 [E2E]** Mock run, 375 and 1280: AutoCount > Companies > SRT > Stock balance >
  Schedule: gate-shut badge + warning line; gate-open toggle; Push reveals cadence; 4 minutes shows
  the error, 5 saves; Activate tab shows Re-push. Evidence `13-evidence/s1-mock/`.
- **AC-13-51 [E2E]** Live lane run, 375 and 1280, against the real backend with a logging-sink
  company: the contract-shut state renders from the real `pushGate`. Evidence `13-evidence/s3-real/`.
- **AC-13-52 [E2E]** Joint run on the Sorento clone (their SR5 lane): flip `SRT` stock to Push at
  5 minutes by real clicks, the Entities list shows Push, three consecutive runs complete, then
  `MCH`. Evidence `13-evidence/s4-joint/` with the run log.

## Group G - cross-repo and runbook (`[T]`)

- **AC-13-59 [T]** Appendix A3 states explicitly that push writes `quantity_on_hand` only and never
  touches reserved or damaged (R7); the SR5 pytest pins it on Sorento's side. Appendix A3/A4
  record the Sorento peer's agreed corrections (Sorento `origin/main` 3684a4b35).
- **AC-13-60 [T]** Appendix A (SR5 brief) is delivered verbatim to the Sorento peer before S2
  closes; `documentation/plans/sprint-5/13-fixtures/` holds the 11 fixture files Appendix A7 lists (plus `README.md`),
  recorded from the existing stock snapshot builder, and the AC-13-03/04/05 parity tests load them.
- **AC-13-61 [T]** Joint-run exit criteria per book: after the first run that drains (<= 3 runs),
  Sorento `stock.quantity_on_hand` for every (product, ACTIVE warehouse) pair equals the Foundryx
  delivered set (0 mismatches; pairs absent from the set are 0); inactive- and unknown-warehouse
  pairs are untouched; `retryable` count equals pairs whose product Sorento lacks; the next two runs
  push only changed pairs (`unchangedSkipped` ~ delivered set).
- **AC-13-62 [T]** Owner runbook (plan section 6) exists, names the deploy order (Sorento 2.5
  first), the pre-flight checks, the last Pull + Confirm immediately before each stock flip, the
  products / stock dependency as a NOTE with the flip order left to the owner (R6), the watch criteria, the products flip with plan-10 section 2.9 items 4 and 5 as
  recorded owner decisions, and the warehouse-activation Re-push step, and the R10 step "after flipping a book to Push, do not use
  Sorento's stock Pull or manual stock import for that book". No code for products.
- **AC-13-63 [T]** STOP gate: nothing is flipped on prod until the owner reviews the S4 joint-run
  report.

## Group H - cross-cutting

- **AC-13-70 [BE]** No migration (module head stays `0022_autocount_preview_job`), no new
  permission row, no new job type, no manifest change. `tests/test_worker_module_boot.py` needs no
  new pin (no new `register_job_handler`); the reviewer confirms that.
- **AC-13-71 [T]** Full backend suite (`-n auto --dist loadfile`) and vitest green; the three
  inverted plan-10 tests (baseline list above) are the ONLY deliberate assertion reversals; the
  fourth (`:319`) changes its rig only.
- **AC-13-72 [T]** Test Execution Report `13-autocount-stock-push-test-report.md` keyed to these
  ids (PASS / FAIL / DEFERRED), citing the evidence run per `[E2E]` id; backlog rows written.
