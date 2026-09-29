# 14 - AutoCount DO / GRN / branch HTTP source, cursors, CRM sink (S1, S4) - acceptance criteria

Plan: `14-autocount-do-grn-http-source.md` (how these are met). Contract of record: the Sorento CRM
cross-repo contract section 13 (contract 2.7, copied from the CRM plan
`PLAN-autocount-grn-do-ingest-29sep.md` section 1). Issue: sorento-crm #1354 (owner rulings
29 Sep 2026). Lane `.claude/worktrees/s60`, branch `feat/autocount-do-grn-http-source`.

Tags: `[BE]` backend pytest, `[FE]` Vitest/RTL, `[E2E]` recorded agent-browser run (real clicks
from the sidebar, 375px AND 1280px, evidence under `14-evidence/<slice>/`), `[T]` structural /
parity / migration test.

Glossary. **Feed** = one of `delivery_orders`, `goods_receive_notes`, `branches` for one AutoCount
company. **Book** = the last path segment of the feed's open REST connection base URL (`db1`).
**MYT** = Malaysia time, UTC+8, no daylight saving. **Live** = mode `push`; **dry run** = mode
`dry_run` (every CRM call carries `?dry_run=true`). **Ledger** = what we pushed and the CRM
holds, per (feed, book, DocKey). **Issue** = a document the CRM answered `retryable` or `failed`.

Owner rulings that bind (not reopened): hourly byLastModified poll for yesterday and today in MYT
(V1, Q12); JustNow unused (V5); no pagination on document endpoints (V2); branches paged,
pageSize max 1000; backfill by DocDate from 2023-01-01, one day per call, once, resumable (Q6);
branches daily and before any backfill; SO and PO stay on the DB transfer (V4); records go
unmapped with `Details` (Q1); the shared service holds the per-entity switch (Q5); `db1` =
Sorento, company code `SRT` (V9); 45-day deletion sweep (scout Q9); link fields pass through
when present; retryable re-sent next tick, failed logged with the CRM errors and not auto
retried; batches <= 1000; dry run never advances cursors or ledgers.

## A. Configuration and gate

- **AC-14-01** `[BE]` Given a company of tenant A that never configured a feed, When
  `GET /autocount/doc-feeds/{companyId}` is called by a user holding `autocount.companies.read`,
  Then it answers the three feeds (`delivery_orders`, `goods_receive_notes`, `branches`) each with
  `mode: "off"`, no connection, no cursor, zero issue counts. The same call for a company id of
  tenant B answers 404.
- **AC-14-02** `[BE]` Given tenant connections of provider `autocount` with auth `none` whose
  base URL ends in `/api/db1`, one with auth `basic`, one whose base URL ends in a segment
  outside `[A-Za-z0-9_-]{1,20}`, and one belonging to tenant B, When the view is read, Then
  `eligibleConnections` lists only the first, with `book: "db1"`.
- **AC-14-03** `[BE]` Given an eligible connection, When `PUT /autocount/doc-feeds/{companyId}/
  delivery_orders` sets `{connectionId, mode: "off"}`, Then the feed row stores the connection
  and the derived book `db1`. A basic-auth, ineligible, unknown or other-tenant connection id
  answers 422 with `fieldErrors.connectionId` and stores nothing.
- **AC-14-04** `[BE]` Given a stored connection, When `mode` is set to `dry_run` or `push`, Then
  the call answers 422 with `fieldErrors.mode` when ANY of these holds: the company push target is
  not `sorento` or has no Sorento connection; the company code is blank; the CRM
  `GET /api/v1/external/contract` answers a version below 2.7, omits this feed's entity name from
  `entities`, or cannot be reached. The view carries `contractGate: {version, requiredVersion:
  2.7}` for that feed while the gate is shut and `null` when open. `mode: "off"` is always
  accepted.
- **AC-14-05** `[BE]` Permissions reuse the module CSV (no new key): the view needs
  `autocount.companies.read`; `PUT` needs `autocount.companies.manage`; run now, sweep now and
  every backfill action need `autocount.sync.run`; the runs and issues lists need
  `autocount.sync.read`. A user lacking the key gets 403.
- **AC-14-06** `[BE]` Given a delivery-order feed switched from `off` to `dry_run` or `push`,
  Then `next_poll_at` is armed to now (the first poll fires on the next beat minute) and
  `next_sweep_at` to now + 24 h. Switching to `off` stops every scheduled run for the feed.

## B. Vendor reads

- **AC-14-10** `[BE]` The poll GETs, on the feed connection base URL, exactly
  `/deliveryorderbyLastModified?lastModified=yyyyMMdd` (GRN: `/goodsreceivenotebyLastModified?
  lastModified=yyyyMMdd`), one GET per MYT day in the window. The sweep and the backfill GET
  `/deliveryorderbydocdate?DocDate=yyyyMMdd` (GRN: `/goodsreceivenotebydocdate?DocDate=
  yyyyMMdd`). The branch pull GETs `/branchbypage?page=N&pageSize=1000` from page 1 until the
  echoed `TotalPages` (an empty `Data` also ends the walk).
- **AC-14-11** `[BE]` Given `now = 2026-09-29T16:30:00Z` (00:30 MYT on 30 Sep) and no cursor,
  When a live poll runs, Then the days read are `20260929` and `20260930`.
- **AC-14-12** `[BE]` Given a document endpoint that answers a paged envelope with
  `TotalPages > 1`, a non-JSON body, a non-2xx status after the existing retry ladder, or a base
  URL the SSRF guard blocks, When a poll runs, Then the run is `FAILED` with a named
  `errorCode` (`VENDOR_PAGED`, `VENDOR_NOT_JSON`, `VENDOR_HTTP`, `VENDOR_TRANSPORT`), nothing is
  posted to the CRM and the cursor is unchanged.
- **AC-14-13** `[BE]` Given the same DocKey returned on two days of one read, When the poll
  pushes, Then it is sent once, the copy with the greater `LastModified`.

## C. Push to the CRM

- **AC-14-20** `[BE]` Every ingest POST goes to `{crmBase}/api/v1/external/ingest/
  delivery_orders` (or `goods_receive_notes`, `branches`) with header `X-API-Key` and body
  `{"companyCode": "SRT", "book": "db1", "records": [...]}`; each record is JSON-equal to the
  vendor record as returned, `Details` and unknown keys included (fixture equality); records are
  ordered by `LastModified` ascending.
- **AC-14-21** `[BE]` Given 2,500 records and the batch setting at its maximum, Then no ingest
  POST carries more than 1000 records, and no deletions POST more than 1000 `doc_keys`.
- **AC-14-22** `[BE]` Given CRM verdicts `created`, `updated`, `unchanged`, `unchanged` +
  warning `stale_ignored`, `failed`, `retryable`, Then `created`/`updated`/`unchanged` count as
  delivered, the run summary holds `{created, updated, unchanged, staleIgnored, failed,
  retryable}` and a `warnings` tally per code (`adopted_by_doc_no`, `branch_unresolved`, ...).
  An outcome word outside the vocabulary, or no verdict for a record, reads as `retryable`.
- **AC-14-23** `[BE]` Given a live record answered `retryable` with `errors`, Then an issue row
  (kind `retryable`) stores the record as pulled and the errors; the next live poll re-sends it
  even when its day is outside the window; when a newer vendor copy of the same DocKey is read,
  that copy is sent instead and replaces the stored one; a later delivered verdict removes the
  issue row.
- **AC-14-24** `[BE]` Given a live record answered `failed`, Then an issue row (kind `failed`)
  keeps the CRM errors; later polls do not re-send it unless the vendor returns that DocKey again;
  a later delivered verdict removes the row.
- **AC-14-25** `[BE]` A 429 with `Retry-After` is waited out (the existing sink rule), a
  502/503/504 is retried per chunk; a chunk that still fails, or any other non-200, fails the run
  and keeps the cursor. Chunks already answered keep their ledger and issue effects; the next tick
  re-reads the same window and re-sends (the CRM answers `unchanged`).
- **AC-14-26** `[BE]` Given the CRM contract drops below 2.7 (or stops listing the entity) after
  the mode was set, When a run starts, Then it is `FAILED` with `CONTRACT_GATE` and posts nothing.
- **AC-14-27** `[BE]` Given mode `dry_run`, Then every CRM POST carries `?dry_run=true`, and the
  cursor, ledger and issue rows are untouched; the run row has `dryRun: true` and the counters.

## D. Cursor and schedule

- **AC-14-30** `[BE]` Given no cursor, When a live poll succeeds, Then it read yesterday and today
  (MYT) and `cursorDay` becomes the MYT date of the tick start.
- **AC-14-31** `[BE]` Given `cursorDay` 3 days before today, When a live poll runs, Then it reads
  `cursorDay` through today (4 days) in one run. Given `cursorDay` 40 days back, Then it reads the
  oldest 31 days, sets `cursorDay` to the day after the last one read, and the next poll carries on.
- **AC-14-32** `[BE]` A poll that fails on any vendor day or on a batch-level push leaves
  `cursorDay` unchanged; a dry-run poll never changes it.
- **AC-14-33** `[BE]` The beat sweep enqueues one poll per due feed every 60 minutes and one
  branch pull per branch feed every 24 hours; a feed with an unfinished feed run is not claimed
  that minute (no lost tick); a feed that is `off`, of an inactive company, of a tenant whose
  AutoCount service is inactive, or of a suspended tenant is never swept.

## E. Branches

- **AC-14-40** `[BE]` The branch pull walks every page, then posts every branch record verbatim to
  `/ingest/branches` in batches <= 1000; verdicts are counted; failed branches appear in the run
  summary (no issue row); the next daily pull re-sends everything.
- **AC-14-41** `[BE]` A branch verdict is matched on `{book}:BR:{AccNo or ''}:{BranchCode}`
  (`db1:BR::HQ` with no `AccNo`); a DO or GRN verdict on `{book}:DO:{DocKey}` /
  `{book}:GRN:{DocKey}`. A branch record with a blank `BranchCode` and a document with no integer
  DocKey are not sent and are counted as `skippedNoKey`.
- **AC-14-42** `[BE]` A `/deletions` verdict is matched to the DocKey sent by the integer after the
  last `:` of its `source_ref` (the CRM echoes no `doc_key` field); a verdict whose `source_ref`
  does not parse, or a key with no verdict, is counted as `failed` in `failedRefs` and touches no
  ledger row.

## F. Deletion sweep

- **AC-14-50** `[BE]` Given a live DO feed, When the daily sweep runs, Then it GETs bydocdate for
  each of the 45 MYT days ending today, takes the ledger rows of (feed, book) whose DocDate is in
  that window and are not vanished, and posts the DocKeys absent from every day read to
  `/ingest/delivery_orders/deletions` with `{companyCode, book, doc_date_from, doc_date_to,
  doc_keys}` where the dates are the window bounds (ISO `yyyy-MM-dd`).
- **AC-14-51** `[BE]` A DocKey whose DocDate moved to another day inside the window is not
  posted.
- **AC-14-52** `[BE]` Given any day of the window fails to read, Then the sweep is `FAILED`, no
  deletions POST is made, and the sweep stays due for the next beat hour.
- **AC-14-53** `[BE]` Given the vanished set is larger than max(50, 20% of the window's ledger
  rows), Then the sweep is `FAILED` with `DELETE_GUARD` and posts nothing.
- **AC-14-54** `[BE]` A `deactivated` or `not_found` verdict sets the ledger row's `vanished_at`
  and later sweeps skip it; a later delivered push of that DocKey clears it. A per-key `failed`
  (for example `errors.doc_date`) is counted in the run summary and the key is re-evaluated by the
  next sweep.
- **AC-14-55** `[BE]` A dry-run sweep posts with `?dry_run=true` and writes nothing.
- **AC-14-56** `[BE]` The ledger is written only from delivered verdicts of live pushes; a
  `stale_ignored` verdict creates a missing ledger row but never overwrites a stored DocDate or
  `LastModified`.

## G. Backfill

- **AC-14-60** `[BE]` Given a live DO feed, When a backfill starts with no range, Then it first
  runs a branch pull (when the company's branch feed is not `off` and is on the same book; else it
  records `branchStep: "skipped"`), then GETs bydocdate once per day from 2023-01-01 to today
  (MYT, fixed at start), pushing each non-empty day before reading the next.
- **AC-14-61** `[BE]` Progress is durable per day (`nextDay`, `daysDone`, `daysTotal`, counters).
  Stop is cooperative at the next day boundary (status `stopped`); Resume continues at `nextDay`;
  a worker crash (orphaned job) leaves the backfill `stopped` and resumable; Discard closes a
  stopped backfill.
- **AC-14-62** `[BE]` Given a completed live backfill whose `fromDay` <= 2023-01-01, When another
  live backfill starting <= 2023-01-01 is requested, Then 409 `BACKFILL_ALREADY_DONE`. A live
  backfill starting later, and any dry-run backfill, is allowed.
- **AC-14-63** `[BE]` Only one open (running, stopping or stopped) backfill per feed (409
  `BACKFILL_OPEN`); a live backfill needs the feed in `push` (422 `mode`); `branches` has no
  backfill (422); `toDay` after today or `fromDay` after `toDay` is 422.
- **AC-14-64** `[BE]` A dry-run backfill posts with `?dry_run=true` and writes no ledger, issue or
  cursor state.
- **AC-14-65** `[BE]` A day that cannot be read, or a batch-level push failure, stops the backfill
  at that day with the error (resumable from it). A 429 waits `Retry-After` and continues the same
  day, up to 10 consecutive waits, then stops.

## H. History, issues, observability

- **AC-14-70** `[BE]` Every poll, sweep, branch pull and backfill job writes one run row: feed,
  kind, `dryRun`, day range, vendor request count, fetched count, summary counters, outcome,
  error code, duration. `GET /autocount/doc-feeds/{companyId}/runs` lists them newest first,
  paginated, filterable by feed, tenant-scoped.
- **AC-14-71** `[BE]` `GET /autocount/doc-feeds/{companyId}/issues` lists issue rows filterable
  by feed and kind, searchable by DocNo, paginated, tenant-scoped.
- **AC-14-72** `[BE]` Vendor GETs and CRM POSTs are recorded in integration activity with counters
  only (status, row count), never record bodies; the API key never appears.

## I. Structure and isolation

- **AC-14-80** `[T]` The legacy canonical `goods_received_note` entity still has no Sorento ingest
  path (it can never reach `/ingest/goods_receive_notes`); the three feed keys are disjoint from
  `ETL_ENTITY_TYPES`; the SO/PO/SPO task paths are unchanged.
- **AC-14-81** `[BE]` A feed's stored connection id and the company's Sorento connection are
  resolved tenant-scoped and provider-scoped at every run; a connection deleted or moved out of
  reach fails the run with `NO_CONNECTION`, never reads another tenant's row.
- **AC-14-82** `[T]` Module migration `0023_autocount_doc_feed` creates the five tables on
  Postgres and drops them on downgrade; revision id <= 32 chars; one module head.
- **AC-14-83** `[T]` Both new job handlers are registered on worker boot; the orphan hook closes
  an interrupted feed run (`FAILED`, "Interrupted") and sets an interrupted backfill `stopped`.

## J. Frontend

- **AC-14-90** `[FE]` The company detail page has a "Document feeds" tab. It lists the three feeds
  with book, mode badge, covered-through day, last run (time + outcome), waiting and failed counts,
  and backfill state.
- **AC-14-91** `[FE]` Configure: the connection picker is a `SearchSelect` offering only
  `eligibleConnections` (name + book); the mode picker offers Off always and Dry run / Push only
  when a connection is chosen and `contractGate` is `null`; a shut gate shows a warning `Alert`
  naming the consumer's version and 2.7.
- **AC-14-92** `[FE]` Row actions come from `ActionMenu` gated by `useCan`: Run now; Run sweep now
  (documents only); Backfill (documents only, no open backfill); Stop, Resume, Discard by backfill
  state. A user without the key does not see the action.
- **AC-14-93** `[FE]` The backfill dialog has a Dry run switch and a from/to date range defaulting
  to 2023-01-01 and today; a running backfill shows `JobProgress` in days with Stop.
- **AC-14-94** `[FE]` The runs and issues lists render through `ResourceList`; errors use
  `ClampedText`; every timestamp goes through `useDatetime`.
- **AC-14-95** `[FE]` No instructional copy, no platform brand name, no bare `Select`, no raw
  table; the tab is usable and not clipped at 375px and 1280px.

## K. End to end

- **AC-14-E1** `[E2E]` Against the mock: sidebar -> AutoCount -> Companies -> company ->
  Document feeds; configure the DO feed (connection, Dry run), run now, see the run row; open a
  failed issue; start, stop and resume a backfill; 375px and 1280px.
- **AC-14-E2** `[E2E]` Against the lane stack (real backend, live vendor wrapper `db1`, the CRM
  copy on :8107 with an owner-supplied key): configure the DO feed Dry run, Run now; the run row
  shows the dry-run counters and the CRM copy is unchanged.
- **AC-14-E3** `[E2E]` Same stack: a 3-day dry-run backfill runs to Done with progress; then the
  owner hand test (plan section 9) covers the live one-day push, the 3-day live backfill and the
  sweep.

## L. Tests named by the owner

- **AC-14-T1** `[T]` Unit: cursor advance, catch-up, dry-run no-advance (AC-14-30..32).
- **AC-14-T2** `[T]` Unit: batching <= 1000 for records and doc_keys (AC-14-21).
- **AC-14-T3** `[T]` Unit: verdict handling - retryable queued and re-sent, failed logged with
  errors, stale_ignored counted, unchanged (AC-14-22..24).
- **AC-14-T4** `[T]` Unit: backfill resume after interrupt mid-range at the next day, run-once
  guard (AC-14-61, 62).
- **AC-14-T5** `[T]` Integration: a full tick, a backfill and a sweep against a stubbed CRM and a
  stubbed vendor (`httpx.MockTransport` through the existing seams), no network in pytest.
