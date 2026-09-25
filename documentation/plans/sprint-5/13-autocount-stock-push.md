# 13 - AutoCount stock balance auto-push (plan 10 slice S7, BL-SS-207)

UAC: `13-autocount-stock-push-acceptance-criteria.md` (the contract; this file is how we meet it).
Lane `sprint-5/13-autocount-stock-push`, worktree `.claude/worktrees/s51` off `origin/main`
4ddc50e2 (module 0.11.0, module Alembic head `0022_autocount_preview_job`). Backend :8013,
frontend :3013, DB `foundryx_service_s51`, Redis db 13. Size: 1-2 days, four thin slices.

## 0. Owner rulings (2026-09-25)

R1 Route B (same Push | Pull toggle as products, owner flips per book and entity; products
flippable too). R2 no Stock List xlsx on the push path. R3 cadence on the Schedule tab, owner sets
5 minutes. R4 inactive-warehouse pairs ship, Sorento answers `updated` + `warehouse_inactive` and
writes nothing. Full text in the UAC.

Owner answers to the planning questions (2026-09-25), locked:

- **R5 (Q1) - `EXCLUDED_NONZERO` blocks the whole book, accepted.** One unresolved UOM rate with a
  nonzero balance stops that book's stock push until the ERP row is fixed (D7 stands). Reason:
  Sorento carries one unit only, so a quantity that cannot be converted to base UOM must never
  land. The per-pair hold stays a deferred Low (BL-SS-270).
- **R6 (Q2) - the owner decides the flip order.** He flips products and stock himself, per book,
  in whatever order he chooses. The runbook states the dependency (stock pairs for items Sorento
  lacks stay `retryable` until products push) as a note, not a mandated order.
- **R7 (Q3) - push writes `quantity_on_hand` ONLY, confirmed.** Reserved and damaged quantities
  (and reorder point / zone) are never touched by push (D16, Appendix A3 step 3).
- **R8 (Q4) - wrapper load accepted.** Roughly 13k wrapper requests per book per day at a
  5-minute cadence is acceptable.
- **R9 (Q5) - skip rows accepted for now.** The `RUN_MODE_SKIPPED` rows the overlap guard writes
  at a 5-minute cadence stay as they are; coalescing them is a deferred Low (BL-SS-266).
- **R10 (2026-09-25) - SR5b skipped.** Sorento keeps the stock Pull button and the manual stock
  Excel import visible for every company. The owner simply does not use them on a book whose stock
  is pushed. This is owner discipline, not a system guard (BL-SS-265, Low).

## 1. Why this is small, and the four things that are not

Most of S7 already exists. The canonical row and its `sink_payload()` are the wire shape
(`canonical/masters.py:339-389`), the sink already calls `payload()` for any non-document record
(`sinks_sorento.py:519-546`), the backend push gate already refuses below 2.5
(`company_service.py:1055-1137`, used by `set_delivery_mode` and `activate_task`), and a
watermark-less HTTP task is already a full hash diff on EVERY run (`http_source/source.py:1025`),
so the "always reconcile" question in R3 is answered by the code as it stands.

What is genuinely missing, found while reading the code:

1. **No path.** `_ENTITY_PATH` has no stock entry (`sinks_sorento.py:94-113`).
2. **The frontend gate is hardcoded.** `AC_PULL_ONLY_ENTITY_TYPES = ['stock_balance']`
   (`autocount-meta.ts:238`) - the Push segment would never appear even at contract 2.5.
3. **BL-SS-238 would make a 5-minute stock push useless.** `_stage_documents` stages every mapped
   record every run (`sync.py:1037-1209`); with the 5,000-row offer cap
   (`autocount_repository.py:599`) roughly 12k unchanged pairs would be re-offered in a permanent
   5,000-per-run rotation, so a real change could wait three runs behind noise.
4. **No baseline.** The pull build never writes `ac_row_hash` (plan 10 D6), so the first push run
   knows nothing and emits no deletes: a pair positive at the last Confirm and zero by the first
   push run would stay positive on Sorento forever.

And one owner-visible blocker: the no-watermark floor is 15 minutes
(`services/etl_service.py:180`), so "5 minutes" is a 422 today.

## 2. Design

### 2.1 Sink (D2, D3, D4, D12, D14)

- `_ENTITY_PATH[ENTITY_STOCK_BALANCE] = "stock_balances"`.
- Contract-gated entities become one small table in `sinks_sorento.py`:
  `{ENTITY_BRAND: (2.3, "brands"), ENTITY_STOCK_BALANCE: (2.5, "stock_balances")}`.
  `sorento_supports_entity`, `sorento_supported_entities_label` and `sink_for_company`'s
  live-probe branch (`company_service.py:859`, `:884-896`) read it instead of naming `ENTITY_BRAND`.
  Brand behaviour is byte-identical. This is the brand gate generalised, not a second mechanism.
- `sink_for_company` keeps brand's logging fallback for stock when the gate is shut (so a
  PULL-mode stock preview is unchanged), and `SyncService.auto_push` adds one guard before
  `list_pending_for_entity`: `entity_type == stock_balance`, company `sink_impl == sorento`, sink
  resolved to logging -> summary error + `errorCode = "CONTRACT_GATE"`, return. Brand's fallback
  is right for brand (the plan-08 "deliverability" story); for stock it would mark rows PUSHED
  while nothing landed, and with changed-only staging (2.2) those pairs would never be re-offered.
- `stock_balance` joins `_DEPENDENT_ENTITIES`; `_result_for`'s dependency sentence gains a stock
  branch ("its product has not synced yet").
- `pairs_from_refs(refs, key_fields)` beside `codes_from_refs`: guard
  `tuple(key_fields) == ("item_code", "location_code")` (the preset's `groupBy`,
  `presets.py:971`), split the ref once on `:`, the suffix must split on `|` into exactly two
  non-empty parts, else that ref is omitted. `delete_batch` / `_run_delete_chunk` gain an optional
  `pairs` kwarg restricted per chunk exactly like `codes`; `_auto_push_deletes`
  (`sync_service.py:976-1007`) passes it for stock. No contract probe needed: stock deletes only
  exist once the gate opened. Sorento keeps no stock refs, so the pair is the only way to find the
  row; deriving it from the ref needs no column (same argument as plan 10 D21).
- Payload: nothing. `qty` is an `int` field, so it is a JSON integer; the prices-as-strings note in
  plan 10 A4 does not apply. The parity test pins it against the fixture.

### 2.2 Run semantics (D5, D6, D7, D8)

All in the NON-paged branch of `run_autocount_sync` (`sync.py:459-1034`), which is the only branch
an `autocount_http` task takes.

- **Always a full diff (D5).** No code. `test_s13_stock_reconcile_delete.py` pins that an
  `incremental`-mode run stages the delete for a pair gone to zero. Scheduled `reconcile` runs are
  the same diff; the daily reconcile setting stays as an operator field with no extra meaning.
- **Changed-only staging (D6, closes BL-SS-238).** `FetchResult` gains
  `changed_refs: Optional[Set[str]] = None`; `HttpApiSource.fetch_changes` fills it with the refs
  it counted as `added` or `updated` (`source.py:1141-1144`); every other source leaves `None`,
  which keeps today's stage-everything behaviour (SQL paths untouched). `_stage_documents` gains
  `changed_refs` and `ref_fn`: after `map_document` succeeds, a record whose ref is NOT in
  `changed_refs` AND whose `compute_diff(last_pushed.canonical_json, canonical)` is empty AND which
  has no open STAGED row is skipped (no write, no commit, counted as `unchangedSkipped`). The OR
  with the last-pushed canonical is what makes it safe: hashes are persisted inside
  `fetch_changes` (`source.py:1169-1177`) BEFORE staging, so a hash-only rule would lose any change
  whose run died between fetch and stage; the canonical check also makes a mapping edit propagate
  without Re-push, and Re-push (hashes cleared) still re-stages everything because every ref then
  reads as `added`. `run.fetched_count` stays the full delivered set.
- **Unresolved quantity fails closed (D7).** Right after a successful fetch, when
  `profile_for(entity_type).pull_metadata_map` has `excludedNonzeroCountAs` and
  `apply_pull_metadata_map(result.combine_metadata, map)` reports a count > 0, `_fail(...,
  error_code="EXCLUDED_NONZERO")` before staging. This is the consumer's own pull Confirm guard
  (plan 10 A5) moved to the one place that can still enforce it once nobody presses Confirm. Live
  db1 has 5 exclusions, all qty 0, so it does not fire today.
- **Truncation never deletes (D8).** Extract the snapshot's completeness rule
  (`sync.py:2778-2792`: main walk verified against the echoed total, every lookup verified) into
  `extract_is_complete(result)`; the snapshot path calls it unchanged. On a push run where it is
  `False`, `result.delete_refs` is replaced by `[]` before `_stage_deletes`, upserts still stage,
  `run.truncated = True`, one `record_activity` note names the unverified endpoints. The missing
  refs keep their hashes, so the next complete walk re-derives the deletes. This also neutralises
  BL-SS-255 (empty page read as end of scan) for deletes.
- Excluded and dropped rows: confirmed already never staged - combine exclusions and drops never
  become `SourceRecord`s (`source.py:1053-1067`), and a dropped pair that was known becomes a
  delete intent through the normal diff. Pinned, no code.

### 2.3 Cadence (D11)

`MIN_INCREMENTAL_MINUTES_NO_WATERMARK` 15 -> 5 in `services/etl_service.py:180` and
`lib/autocount-etl.ts:308` together (every no-watermark task, not a stock special case: one
constant, and the overlap guard already stops a slow walk from stacking). The overlap guard
(`scheduler.py:243-328`) skips a tick while a run is in flight and writes one `RUN_MODE_SKIPPED`
row; the due time advances by 5 minutes regardless. So a 6-minute SRT walk runs every 10 minutes
and writes a skip row in between; MCH (0.2 s per row on the wrapper, plan 10 BL-SS-219) runs as
often as its walk allows. That is what "5 minutes" means and the runbook says so. Load: each walk
is 69 + 12 + 12 wrapper requests (plan 10 A7), roughly 13k requests per book per day at this
cadence (accepted by the owner, R8). The skip rows are accepted as-is for now (R9, BL-SS-266).

### 2.4 The flip: gate, prerequisite, baseline (D9, D10, D18)

- **`pushGate` on the task view.** `EtlService._task_view` (`etl_service.py:1160-1230`) adds
  `push_gate`, computed for `stock_balance` only: the existing `stock_push_gate_error` dict when
  shut; else `{"reason": "no_snapshot"}` when the task is in `pull` and no READY unexpired snapshot
  exists; else `None`. `schemas.py` adds `pushGate` beside `contractGate` (`:918`). The frontend
  reads nothing else to decide whether Push is offered, which finally makes AC-10-15's "opens with
  no code change" true.
- **Prerequisite.** `set_delivery_mode(stock, push)` refuses 422 on either shut state (contract
  check is already there, `etl_service.py:2930-2935`; `no_snapshot` is added after it).
- **Baseline seed (D9).** In `set_delivery_mode`, on `pull -> push` for any pull-capable entity,
  when `RowHashRepository` holds zero rows for the (tenant, company, entity): collect the distinct
  `source_ref`s of every READY, unexpired snapshot of that triple (new repo read
  `PullSnapshotRepository.ready_source_refs(tenant_id, company_id, entity_type, now)`, tenant-scoped,
  `ac_pull_snapshot_row.source_ref`) and `upsert_many` them with `row_hash = f"seed:{snapshot_id}"`
  in the same commit as the mode change. The first push run then reads every current ref as
  changed (staged) and every seeded ref missing from the extract as a delete (qty 0). Taken as
  (a) + (b): the runbook's "last Pull + Confirm, then flip immediately" keeps the union close to
  what Sorento holds, and the seed closes the window between that Confirm and the first push walk.
  The union (at most 3 snapshots, 24 h TTL) is a superset of the confirmed set; a seeded ref
  Sorento never held answers `not_found`, which is harmless. (c) a Sorento-side run-scoped sweep
  marker was rejected: it rebuilds the destructive "zero everything absent" import on the consumer,
  the exact failure mode per-row upsert/delete exists to avoid.
- **`push -> pull` clears the hashes (D10)** with the same `RowHashRepository.clear_all` Re-push
  uses. Otherwise a later re-flip would diff against pre-pull hashes: a pair the pull period zeroed
  and that came back at the same qty would read as unchanged and never be re-sent.

### 2.5 Operator surfaces (D18, D19)

Nothing new is built; three existing components change.

- `schedule-tab.tsx:93-130`: `pushGateShut = task.pushGate != null`; the shut branch renders the
  existing `StatusBadge` with the CURRENT `deliveryMode` plus one `Alert` (warning, light, same
  pattern as `activate-tab.tsx:270-298`) whose title is the prerequisite line (AC-13-40). The
  cadence controls already hide in pull and reappear in push. Remove `AC_PULL_ONLY_ENTITY_TYPES`
  and `isPullOnly` from `autocount-meta.ts:228-246` and the mock's `PULL_ONLY_ENTITY_TYPES`
  (`autocount-service.mock.ts:620-628`); the mock seeds a new stock task in `pull` and exposes a
  `setMockPushGate(companyId, state)` test seam like `setMockRepushInFlight`.
- `activate-tab.tsx`: `pullOnlyEntity` -> `task.pushGate != null`; `isDatabaseTask` -> `sourceImpl`
  in (`sql_db`, `autocount_http`) so Re-push is offered for the stock and product HTTP tasks (the
  backend already accepts it, `etl_service.py:3133-3136`). Banner copy unchanged.
- `lib/autocount-etl.ts:308`: 15 -> 5.
- Entities list Delivery column: already reads `deliveryMode` (`use-entities-list-config.tsx:
  334-341`); verified by E2E only.

Layering is the house one: `types/autocount.ts` (`pushGate?: AutocountPushGate | null`) ->
`services/autocount-service.{ts,mock,real}.ts` -> existing `use-autocount-*` hooks -> UI. The
real service needs no change beyond the type (the field arrives on the task payload).

### 2.6 Decision log

| # | Decision | Why |
|---|---|---|
| D1 | Route B: stock gets the product toggle, opened by the backend gate, flipped by the owner per book (R1) | Owner ruling; one mechanism for every pull-capable entity |
| D2 | No serializer work; `CanonicalStockBalance.sink_payload()` IS the SR5 row | Verified `masters.py:339-389` + `_to_records`; `qty` is an int field |
| D3 | Stock is contract-gated inside `sorento_supports_entity` via a two-row table shared with brand | Generalise the existing brand gate instead of cloning it (plan 10 AC-10-69 precedent) |
| D4 | Push-time refusal (`CONTRACT_GATE`) instead of brand's logging fallback, for stock only | A logging "delivery" marks rows PUSHED while nothing lands; with changed-only staging they would never be re-offered |
| D5 | "Always reconcile" needs no code: watermark-less HTTP runs are full diffs by construction (`source.py:1025`) | R3's question answered by the code; pinned by test |
| D6 | Stage only records that changed at source OR differ from the last pushed canonical; all `autocount_http` tasks; SQL untouched (closes BL-SS-238) | Without it a 5-minute stock push is a 5,000-row rotation of noise; the canonical OR keeps it safe against hash-before-stage and makes mapping edits propagate |
| D7 (owner ruling R5) | `excludedNonzeroCount > 0` fails the push run (`EXCLUDED_NONZERO`), before staging, blocking the whole book | Sorento carries one unit only, so an unconvertible quantity must never land. The consumer's pull Confirm guard has no human to enforce it on push; an unresolved rate under-counts real inventory. Per-pair hold backlogged (BL-SS-270) |
| D8 | An unverified walk stages no deletes (upserts proceed), `run.truncated = True`; one completeness helper shared with the snapshot | Upserts from a partial walk are still true values; deletes from one zero real stock |
| D9 | Baseline = runbook (last Pull + Confirm, flip at once) + seed `ac_row_hash` from the union of READY snapshots at flip; stock refuses the flip without one | Closes the Confirm-to-first-walk window with no Sorento sweep; superset is harmless (`not_found`) |
| D10 | `push -> pull` clears the task's row hashes | Stale hashes would mask pairs the pull period zeroed |
| D11 (owner rulings R8, R9) | No-watermark floor 15 -> 5 for every task; overlap guard unchanged; effective cadence documented; wrapper load and skip rows accepted | Owner sets 5 (R3); one constant; the guard already prevents stacking |
| D12 | Stock deletions carry `pairs` derived from the ref, guarded like `codes` | Sorento stores no stock refs; no column, no migration |
| D13 | Inactive or unknown warehouse = `updated` + `warehouse_inactive` / `warehouse_unresolved`, nothing written; recovery after activating a warehouse = Re-push | R4; `failed` would quarantine and `retryable` would keep the task red forever for the 7 missing locations (BL-SS-217) |
| D14 (owner ruling R6) | Missing product = `retryable`, stays STAGED; stock joins `_DEPENDENT_ENTITIES`; flip order is the owner's choice | Drains by itself once the product lands (products flip); the runbook notes the dependency without mandating an order |
| D15 | No Stock List xlsx on push (R2); the row keeps `item_description` and `uom_code` (ignored by Sorento) | One row shape for pull and push; zero Foundryx work |
| D16 (owner ruling R7) | Push upsert writes `quantity_on_hand` ONLY; reserved / damaged / reorder point / zone never touched | The spec agreed in BL-SS-041, confirmed by the owner; unlike the pull import, which resets them (plan 10 A10) |
| D17 | Products flip needs no code (prod 2.4, `codes` shipped); section 2.9 items 4 / 5 are runbook owner decisions; the seed applies to products too | Verified `sinks_sorento.py:165`, `sync_service.py:986-998`, `set_delivery_mode` has no product gate |
| D18 | The frontend decides Push from a backend `pushGate`, never an entity list | The hardcoded list is why AC-10-15's promise was false on the frontend |
| D19 | Re-push offered for `autocount_http` tasks | Backend already allows it; D13's recovery path needs it |
| D20 | No migration, permission, job type or manifest change | Every new fact fits existing columns (`ac_row_hash.row_hash` is unbounded `String`, `run.truncated` exists) |

## 3. Files

Backend (`service_backend/modules/autocount/`): `sinks_sorento.py` (path, gated-entity table,
`pairs_from_refs`, `pairs` kwarg, dependent set, stock retryable text), `sources.py`
(`FetchResult.changed_refs`), `http_source/source.py` (fill `changed_refs`), `sync.py`
(`extract_is_complete`, `EXCLUDED_NONZERO`, delete suppression, changed-only `_stage_documents`,
`unchangedSkipped`), `services/sync_service.py` (`CONTRACT_GATE` guard, `pairs` for stock
deletes), `services/company_service.py` (`sink_for_company` reads the gated table),
`services/etl_service.py` (floor 5, `push_gate` on the view, `no_snapshot` refusal, seed on
`pull -> push`, `clear_all` on `push -> pull`), `schemas.py` (`pushGate`),
`repositories/autocount_repository.py` (`ready_source_refs`).
Tests: `tests/test_s13_stock_push_contract_gate.py`, `test_s13_stock_sink_payload_parity.py`,
`test_s13_stock_reconcile_delete.py`, `test_s13_http_stage_changed_only.py`,
`test_s13_flip_baseline_seed.py`, `test_s13_schedule_floor_overlap.py`; edit
`test_s10_s5b_registration.py` (three inversions, `:235/:240/:250`, plus a rig fix to
`test_switching_a_stock_task_to_push_is_allowed_once_the_contract_reports_2_5`, `:319`).
Frontend (`service_frontend/`): `types/autocount.ts`, `services/autocount-service.{mock,real}.ts`,
`app/(protected)/autocount/components/autocount-meta.ts`, `.../[entityType]/components/
{schedule-tab,activate-tab}.tsx`, `lib/autocount-etl.ts`, tests beside each.
Docs: this pair, the test report, `13-fixtures/`, `13-evidence/`, backlog rows,
`documentation/engineering/process-lessons.md` (AutoCount: changed-only staging, seed, floor).

## 4. Slices

| Slice | Scope | UAC |
|---|---|---|
| S0 | Lane + docs commit. Appendix A sent to the Sorento peer. Fixtures recorded into `13-fixtures/` (A7). Tester writes the red tests for S2/S3 (the six `test_s13_*` files, the three inversions and the fourth plan-10 rig fix) and the vitest cases | AC-13-60, red tests for 01-34 |
| S1 FE mock | `pushGate` type, mock states, Schedule / Activate tab changes, floor mirror, Re-push for HTTP; agent-browser against the mock | AC-13-40..45, 50 |
| S2 BE | Sink + verdicts + `pairs`; changed-only staging; `EXCLUDED_NONZERO`; truncation-safe deletes; `CONTRACT_GATE`; floor 5 | AC-13-01..06, 10..16, 20, 21 |
| S3 BE + FE real | `pushGate` on the view, `no_snapshot`, seed, `push -> pull` clear; swap mock to real, prod build, live evidence of the shut state | AC-13-30..34, 44, 51 |
| S4 | Live replay both books through the LOGGING sink (lane-DB harness flip, documented SQL on `foundryx_service_s51` only, to measure walk time, `unchangedSkipped`, deletes per run); joint run on the Sorento clone with SR5 deployed, `SRT` then `MCH`; test report; **STOP for the owner before prod** | AC-13-52, 61..63, 70..72 |

Rules: S1 before any UI-facing backend; S2/S3 red-green (tester first); one coder per lane,
sequential; reviewer (Opus) once after S3 and at the merge gate; every brief embeds the PRINCIPLES
design mandates, DoD gate and hard-fail list.

### 4.1 Tests named for the tester (red first)

- Contract gate (`test_s13_stock_push_contract_gate.py`): supports-entity table incl. brand
  control; label excludes gated entities; `sink_for_company` open vs shut; `auto_push`
  `CONTRACT_GATE` refusal leaves rows STAGED; `pushGate` three states + non-stock `null`;
  `set_delivery_mode` `no_snapshot` 422 and contract-before-snapshot ordering.
- Payload parity (`test_s13_stock_sink_payload_parity.py`): `_to_records` == fixture request rows;
  deletions body == fixture (with `pairs`, chunk-restricted, guard misses omitted); response
  fixture parsed: `warningCounts`, retryable stays STAGED with the product sentence, failed
  quarantined.
- Reconcile delete-on-zero (`test_s13_stock_reconcile_delete.py`): incremental-mode delete intent;
  negative drop -> delete; excluded / dropped never staged; `EXCLUDED_NONZERO` + zero-measure
  control; unverified main walk and unverified lookup -> no deletes, upserts staged,
  `truncated=True`; delete guard unchanged.
- Changed-only staging (`test_s13_http_stage_changed_only.py`): AC-13-11 (a)-(f).
- Baseline (`test_s13_flip_baseline_seed.py`): union seed, sentinel value, never overwrites,
  products optional, first-run staging + deletes, `push -> pull` clears, round trip keeps mapping
  byte-identical.
- Overlap guard at 5 minutes (`test_s13_schedule_floor_overlap.py`): floor 4 -> 422 / 5 ok,
  `next_run_times` clamp, skip row + re-arm while in flight, fire after finish.
- Plan-10 test updates in `tests/test_s10_s5b_registration.py`: invert `:235`, `:240`, `:250`
  (stock now has a path and is contract-gated), and give
  `test_switching_a_stock_task_to_push_is_allowed_once_the_contract_reports_2_5` (`:319`) a READY,
  unexpired stock snapshot in its rig (found by the tester: AC-13-31's `no_snapshot` gate would
  otherwise refuse the flip it asserts is allowed). Its assertion is unchanged.
- `tests/test_worker_module_boot.py`: no change (no new job handler) - reviewer confirms.
- Vitest: `schedule-tab.test.tsx` (toggle vs badge + warning by `pushGate`, floor 5),
  `activate-tab.test.tsx` (Re-push for `autocount_http`, preview-unavailable by `pushGate`),
  `lib/autocount-etl` floor, `services/autocount-service.test.ts` (mock gate states).

## 5. Risks and answers

- **A stock-take legitimately zeroes a whole warehouse** (> 20% of pairs): the existing
  `DELETE_GUARD` stops the run. Intended; the operator sees the named error.
- **A manual Excel stock import on Sorento after the flip** zeroes absent pairs and Foundryx will
  not re-send unchanged ones (a stock Pull + Confirm does the same). Sorento keeps both visible
  (R10, SR5b declined): the owner does not use them on a pushed book; if one is used by mistake,
  the recovery is a Re-push of that book's stock task (BL-SS-265).
- **Warehouse activated in Sorento later**: its pairs were delivered as `warehouse_inactive` and
  are unchanged, so nothing re-sends them. Runbook: Re-push the stock task after activating or
  creating a warehouse. Plan 10's consignment note still applies before `CON` / `HQ` / `DISPLAY`
  are activated.
- **Items Sorento lacks** stay `retryable` and the task shows the dependency error until products
  flip; the owner chooses the flip order (R6).
- **Growth**: run rows (plus a skip row per skipped tick, accepted for now, R9) and pushed staged rows accumulate at this
  cadence with no retention sweep (BL-SS-266, BL-SS-267).

## 6. Owner runbook (prod)

Order: the owner flips products and stock himself, per book, in the order he chooses (R6). Note
the dependency: a stock pair whose item Sorento does not hold stays `retryable` (the stock task
shows the dependency error) until that product is pushed; it then drains by itself. Steps 2-5
(stock) and step 6 (products) may run in either order.

Pre-flight: Sorento SR5 (contract 2.5, `stock_balances` in `GET /external/contract`) deployed and
the `foundryx-esb` integration granted `inventory.stock.edit` + `inventory.stock.delete` (SR5a ships
the grant migration; the role has no `inventory.stock.*` grant today); Foundryx
plan 13 deployed after it; `ac_company.sorento_company_code` is `SRT` / `MCH` (plan 10 A2).

1. Deploy Sorento 2.5, then Foundryx. Reload the SRT stock task: the Schedule tab now shows the
   toggle (or names what is missing).
2. On Sorento, Pull + Confirm SRT stock once more. Within the same session (well inside 24 h):
3. Foundryx > AutoCount > Companies > SRT > Stock balance > Schedule: Push, incremental 5 minutes,
   Save. Expect the first run within a minute.
4. Watch three runs on the Runs tab: run 1 stages ~12k plus a handful of deletes and needs up to 3
   runs to drain under the 5,000 cap; afterwards `unchangedSkipped` is roughly the whole set,
   staged is a few dozen, no `failed` (any `retryable` count = pairs whose item Sorento lacks, see
   the order note). An `EXCLUDED_NONZERO` failure means an ERP UOM rate row needs fixing; that book's
   stock push stays stopped until it is (R5). `warehouse_inactive` counts land in the job result. Spot
   check five pairs in Sorento stock. A 6-minute walk means one run every 10 minutes with a skip
   row between.
5. Repeat 2-4 for MCH (slower walk; expect less frequent runs).
6. Products (no code, D17): decide section 2.9 item 4 - enable the `uom_code` row on the Mapping
   tab (per-row Enabled switch, plan 12 R6) or keep it withheld; item 5 - `cost_price` stays
   unmapped (no source, BL-SS-213). Then Pull + Confirm products, flip the product task to Push.
   With the seed, the first run re-sends every product. If the product task had pushed before
   (non-empty history), enabling `uom_code` still reaches every product through D6's canonical
   check - no Re-push needed.
7. Any time a Sorento warehouse is activated or created: Re-push the stock task for that book.
8. After flipping a book to Push, do not use Sorento's stock Pull or manual stock import for that
   book (R10; both stay visible). If either is used by mistake, Re-push that book's stock task.
9. A sink-target switch (review round 2 S3) - changing a company's push connection or flipping
   `logging` <-> `sorento` - auto-invalidates every `autocount_http` task's row hashes for that
   company, so the very next run re-offers everything to the new target. A CONTRACT UPGRADE alone
   (no sink-target change - e.g. Sorento deploys 2.3 and a brand task held below it by the logging
   fallback now opens) is NOT auto-detected: Re-push the affected task (brand, or any
   contract-gated entity) once its consumer starts accepting it, or its accumulated changes never
   re-offer on their own (BL-SS-272).
10. Trap (review round 2 S5): the baseline seed (D9) is a snapshot union, which can be LARGER than
    the current live extract (e.g. items deleted at source since the last Pull). If the seed
    overcounts by more than the delete guard's threshold (20% of known, floor 50), EVERY run after
    the flip trips `DELETE_GUARD` and stages nothing. Recovery is the same as any stale-hash
    problem: Re-push the task (invalidates and lets the next full walk re-derive a correct
    population).

Rollback: flip the book back to Pull (hashes cleared, D10), Sorento Pull works again at once.

## 7. Backlog

- BL-SS-207 -> In progress (this plan). BL-SS-238 -> closed by D6 at merge. BL-SS-041 / BL-SS-203
  notes updated at merge.
- BL-SS-265 Owner-discipline risk: Sorento's stock Pull and manual stock import stay visible on a
  push-fed book; using either zeroes pairs Foundryx will not re-send until they change. SR5b
  declined by owner (R10); recovery is Re-push (Low).
- BL-SS-266 Coalesce scheduler skip rows into one per skipped streak (Low; skip rows accepted as-is
  for now, owner ruling R9).
- BL-SS-267 Retention sweep for `ac_sync_run` and pushed `ac_staged_record` rows (Medium).
- BL-SS-268 `set_delivery_mode(product, push)` lacks the >= 2.4 check `activate_task` has (Low).
- BL-SS-269 `scheduler._sweep_one` re-arms with the raw `source_config`, so an HTTP task WITH a
  `watermarkField` gets the no-watermark floor (`scheduler.py:205-207`; use
  `EtlService._schedule_source_config`) (Low).
- BL-SS-270 Per-pair hold instead of a whole-run `EXCLUDED_NONZERO` failure (Low, deferred; the
  whole-book block is the owner's ruling R5).
- BL-SS-271 Products flip owner decisions (plan 10 section 2.9 items 4 `uom_code` and 5
  `cost_price`), recorded at the flip; links BL-SS-213 (Medium).
- BL-SS-272 Review round 2 (S3 fix) - a sink-target switch invalidates `autocount_http` row hashes;
  a consumer CONTRACT UPGRADE alone is not auto-detected, so the recovery for a newly-opened
  contract-gated entity (e.g. brand crossing 2.3) is an explicit Re-push (runbook step 9) (Low).
- BL-SS-273 Review round 2 NIT - a product HTTP task's first clean save seeds the preset's
  `ItemUOM` lookup even when the caller's own PUT already carries an explicit `lookups: []` (Low).

## 8. Open questions for the owner

None. Q1-Q5 were answered by the owner on 2026-09-25 and are recorded as rulings R5-R9 in
section 0 (Q1 -> R5, Q2 -> R6, Q3 -> R7, Q4 -> R8, Q5 -> R9).

## Appendix A - SR5 brief for Sorento (contract 2.5)

Self-contained. This is the Foundryx side's proposal; correct anything that disagrees with
Sorento's code and reply with the corrections. Foundryx builds against this text and the fixtures
in A7.

### A1. What changes and why

Stock balance moves from human-checked pull (your SR4: Pull -> review -> Confirm ->
`process_stock_import`) to automatic push, per company, when the Foundryx owner flips it. Push is
per-row upsert and per-row delete through the existing `/external/ingest` surface - NEVER the
destructive full-company snapshot the import does (that zeroes every absent pair; a push batch is
a delta, not a set). The pull path stays exactly as it is for a company that has not flipped;
Foundryx answers `409 PUSH_ACTIVE` to a Pull for a company that has. No Stock List xlsx is produced
on the push path (owner ruling R2): n8n and the chatbot read your `stock` table directly.

### A2. Contract 2.5

- `CONTRACT_VERSION = "2.5"` (`app/api/v1/external/ingest.py:213`); `stock_balances` joins
  `SUPPORTED_ENTITIES` (`:191`) and therefore `GET /external/contract` `entities`
  (`contract.py:190`). Foundryx opens its Push toggle only when BOTH hold (version >= 2.5 AND
  `stock_balances` listed), and refuses the flip otherwise.
- `fields_added` for 2.5 names the new entity; `WARNINGS` (`contract.py:146-170`) gains
  `warehouse_inactive` (new) - `warehouse_unresolved` already exists and is reused.
- Permissions (your maps, `ingest.py:79-129`): ingest `inventory.stock.edit`, read
  `inventory.stock.view`, delete `inventory.stock.delete`. The `foundryx-esb` integration needs
  `.edit` and `.delete` granted before the first push.
- Unchanged: `X-API-Key`, top-level `companyCode` anchor, `MAX_BATCH = 1000` (Foundryx posts 200
  per request by default), per-key rate limit, `Retry-After` on 429, `?dry_run=true` semantics.

### A3. Upsert - `POST /api/v1/external/ingest/stock_balances`

```json
{ "companyCode": "SRT",
  "records": [
    { "source_ref": "AED_SORENTO:BRACD7455C|MBS", "item_code": "BRACD7455C",
      "item_description": "Widget 12mm", "location_code": "MBS",
      "uom_code": "UNIT", "qty": 37 } ] }
```

The row is plan 10 A4's `stock_balances` row unchanged (the same `sink_payload()` the pull
snapshot serves). `qty` is a JSON INTEGER in base UOM; Foundryx never sends 0 or negative (those
pairs are deletes), but accept `qty >= 0` and write 0 as 0. `item_description` and `uom_code` are
accepted and ignored (declare them, your models are `extra="forbid"`); an absent key is normal.
`source_ref` is ONLY the echo key for the per-record verdict - you do not need to store it.

Resolution per record, in this order, within the anchored company:

1. `location_code` -> `warehouses.warehouse_code`: your matcher trims and uppercases both sides
   (the one `classify_stock_rows` already uses, `autocount_pull_service.py:585`).
   - no such warehouse -> `updated`, `warnings: ["warehouse_unresolved"]`, write nothing;
   - warehouse exists but `is_active = false` -> `updated`, `warnings: ["warehouse_inactive"]`,
     write nothing (owner ruling R4 - never `failed`, which would quarantine it and re-fail it on
     every run).
2. `item_code` -> product by `product_code`, case-insensitive and scoped to the anchored company.
   Not found ->
   `retryable` (nothing written; Foundryx re-offers it after the product is pushed).
3. Upsert the `stock` row for (product, warehouse): set `quantity_on_hand = qty` ONLY. **Push
   NEVER touches `quantity_reserved` or the damaged quantity** (owner-confirmed 2026-09-25), nor
   reorder point or zone; `quantity_available` stays DB-generated. This deliberately differs from
   your stock import, which resets reserved / damaged to 0 when those columns are absent (plan 10
   A10). A newly created row takes your column defaults for everything but `quantity_on_hand`.
   `created` when no row existed, else `updated` (also when the value is unchanged). Push inherits
   your generic audit listeners only: no `stock_ledger` row and no extra audit.
4. Validation failure (missing `item_code` / `location_code`, non-integer or negative `qty`) ->
   `failed` with `errors`.

Verdict envelope: `{summary, records: [{source_ref, outcome, entity_id, diff?, errors?,
warnings?}]}`, one verdict per input record, every record echoing its `source_ref`.

**Agreed with the Sorento peer** (session stock-ingest, Sorento `origin/main` 3684a4b35,
2026-09-25). These replace the earlier draft wording:

- `entity_id` is ALWAYS present: the `stock` row UUID, `null` on a warning row, `retryable` or
  `failed`.
- `diff` appears on `dry_run=true` ONLY. A `created` row has no `diff`; an unchanged `updated` has
  `diff: {}`; a changed `updated` has `diff: {"qty": {"current": 12, "incoming": 37}}`.
- Ingest `summary` is exactly `{total, created, updated, failed, retryable}` (warning counts are
  Foundryx's own run summary, never in this object).
- A duplicate pair in one batch is processed in order and the last value wins (first `created`,
  second `updated`, same `entity_id`).
- Idempotent: the same record in a later batch is `updated` (`diff: {}` on a dry run).
- The warehouse matcher trims and uppercases; the product resolver matches `product_code`
  case-insensitively within the anchored company.
- Push inherits the generic audit listeners, with no `stock_ledger` row and no extra audit.
- The `foundryx-esb` role has no `inventory.stock.*` grant today; SR5a adds a grant migration.

### A4. Delete - `POST /api/v1/external/ingest/stock_balances/deletions`

```json
{ "companyCode": "SRT",
  "source_refs": ["AED_SORENTO:BRACD7455C|MBS"],
  "pairs": { "AED_SORENTO:BRACD7455C|MBS": { "item_code": "BRACD7455C", "location_code": "MBS" } } }
```

A delete means "this pair's balance is now zero at source" (it dropped to zero or went negative,
or the item/location vanished). `pairs` is keyed by `source_ref`, honoured for `stock_balances`
only, same cap as `source_refs` (mirror your 2.4 `codes` handling, `ingest.py:807-900`). Per ref:

- pair resolves (same matcher as A3) in an ACTIVE warehouse and a stock row exists -> set
  `quantity_on_hand = 0` (reserved and damaged untouched, as in A3), KEEP the row, outcome
  `deleted`;
- no `pairs` entry, product / warehouse / stock row missing, or warehouse inactive (nothing
  written; add `warnings: ["warehouse_inactive"]` in that case) -> `not_found`;
- a single malformed `pairs` entry (for example missing `location_code`) -> `failed` with
  `errors` for that ref only; the other refs still resolve.

A `pairs` BODY that is not an object at all is a batch-level `422 INVALID_BODY`
(`{code, message, detail: null}`) and nothing is deleted. A `pairs` object over `MAX_BATCH` (1000)
entries is `413 BATCH_TOO_LARGE` - the SAME over-cap response `source_refs`/`codes` already get
(`ingest.py:807-900`), never a second 422 shape for the identical failure mode. Deletions `summary`
is
exactly `{total, deleted, deactivated, not_found, failed}` (agreed with the Sorento peer, same
session as A3). Never hard-delete a `stock` row and never use `deactivated` (it stays in the
summary at 0). Idempotent: zeroing an already-zero row is `deleted` again.

### A5. Read-back

`POST /external/read/stock_balances` may exist because `SUPPORTED_ENTITIES` drives all three
routes; Foundryx does not call it. If you implement it, key it by `source_ref` via the same pair
split and return `{records: [{source_ref, qty}], not_found}`.

### A6. Your side (SR5 slice list)

- SR5a BE: the entity spec, the two routes above, contract 2.5, warnings, permission rows, the
  grant migration giving the `foundryx-esb` role `inventory.stock.edit` + `inventory.stock.delete`;
  pytest against the A7 fixtures (every outcome row in the response fixtures).
- No UI change on your side: the stock Pull button and manual stock Excel import stay visible for
  every company (owner ruling R10, SR5b declined). The owner does not use them on a pushed book.
- Joint run on your clone (Foundryx S4): SRT first, then MCH. Exit criterion: after the first
  drained run, `quantity_on_hand` for every (product, ACTIVE warehouse) pair equals the Foundryx
  delivered set, pairs absent from it are 0, inactive / unknown-warehouse pairs are untouched.
- Deploy order: yours first (2.5 live), then Foundryx.

### A7. Fixtures (`documentation/plans/sprint-5/13-fixtures/`)

Recorded in S0: request rows come from the real `CanonicalStockBalance.sink_payload()` over plan-10
db1 capture values; response verdicts are built to A3/A4 as corrected by the Sorento peer (no live
SR5 existed yet). `README.md` holds provenance, per-row cases and the correction log. The 12
fixture files:

| File | Content |
|---|---|
| `contract-2.5.json` | `GET /external/contract` as Foundryx expects it (`version: "2.5"`, `stock_balances` in `entities`, `warehouse_inactive` in `warnings`) |
| `stock_balances-ingest-request.json` | 10 records: active-warehouse pairs, an inactive warehouse (`CON`), an unknown location (`BRW-VAR`), a trimmed location (`MBS`), an item code with spaces and a quote, an item Sorento lacks |
| `stock_balances-ingest-response.json` | Verdict per record (`created`, `updated`, `updated` + `warehouse_inactive`, `updated` + `warehouse_unresolved`, `retryable`), `entity_id` always present, summary `{total, created, updated, failed, retryable}` |
| `stock_balances-ingest-dry-run-response.json` | Same batch under `?dry_run=true`: no `diff` on `created`, `{}` on unchanged `updated`, `qty` diff on changed `updated` |
| `stock_balances-ingest-duplicate-pair-request.json` | The same pair twice in one batch with different `qty` |
| `stock_balances-ingest-duplicate-pair-response.json` | In order, last wins: `created` then `updated`, same `entity_id` |
| `stock_balances-deletions-request.json` | 5 refs with `pairs`, one ref deliberately without a `pairs` entry |
| `stock_balances-deletions-response.json` | `deleted`, `not_found` (inactive warehouse with warning, unsynced item, missing pair entry), summary `{total, deleted, deactivated, not_found, failed}` |
| `stock_balances-deletions-malformed-entry-request.json` | One clean ref beside one whose `pairs` entry lacks `location_code` |
| `stock_balances-deletions-malformed-entry-response.json` | The malformed entry `failed` with `errors`, the clean ref `deleted` |
| `stock_balances-deletions-error-422-invalid-body.json` | Batch-level `422 INVALID_BODY` when `pairs` is not an object at all |
| `stock_balances-deletions-error-413-batch-too-large.json` | Batch-level `413 BATCH_TOO_LARGE` when `pairs` is an object over `MAX_BATCH` (1000) entries - same over-cap response `source_refs`/`codes` already get |
