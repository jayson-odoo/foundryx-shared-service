# AutoCount document feeds: Delivery Orders and Goods Receive Notes

Scope: the `autocount` module's HTTP-source feeds that push vendor documents (open REST API,
`hapi` books) to the Sorento CRM. Plan and decisions: `documentation/plans/sprint-5/14-*`
(D1..D22). **Contract of record: section 13 of the CRM's
`documentation/plans/autocount/PLAN-autocount-cross-repo-contract.md`** (Sorento repo). A wire
change here without the matching change there is a review finding. Engine-wide rules (layering,
tenancy, Resource shell) are in `AGENTS.md`.

Code: `service_backend/modules/autocount/doc_feed/` (`runner.py`, `vendor.py`, `scheduler.py`,
`jobs.py`, `constants.py`), `services/doc_feed_service.py`, `routers/doc_feeds.py` (mounted at
`/autocount/doc-feeds`, existing keys `autocount.companies.read|manage`, `autocount.sync.read|run`,
no new permission), models `AcDocFeed*` and module migration `0023_autocount_doc_feed`;
`service_frontend/app/(protected)/autocount/companies/components/doc-feed*`.

## 0. Branches are NOT a feed (plan 14 section 11, D23-D28)

`branches` started life as a third doc feed and became the regular HTTP master entity **`branch`**
(owner ruling after the hand test: "it is a master data though with pagination, it is just like
product"). It is wired exactly like `brand` (plan 08) and paged like `product`: an Add-entity task
on an open (`http`) company, `HTTP_PRESETS["branch"]` (path `/branchbypage`, key fields `AccNo` +
`BranchCode`, mapping rows `AccNo -> acc_no` and `BranchCode -> code` required, `BranchName -> name`),
sync modes, first-run window, Runs and health all from the ETL framework. Facts a maintainer needs:

- **Wire (D24):** `CanonicalBranch.sink_payload()` is the **raw vendor row** with the mapped
  `AccNo` / `BranchCode` / `BranchName` written over it (the CRM stores the row and reads only those
  three); no canonical keys reach the wire. The raw row rides in `source_record`, filled by the
  mapping engine (`EntityProfile.raw_record_field`), never a mapping target.
- **Identity (D25):** `source_ref` = `{book}:BR:{AccNo}:{BranchCode}` verbatim, the CRM's own
  derivation (the ETL matches verdicts by the string it sent). `book` comes from the task
  connection's base URL (`http_source/book.py`, `derive_book` / `identity_scope`); every other
  entity keeps `{database_name}:{key}`.
- **Sink (D26):** `_ENTITY_PATH["branch"] = "branches"`, `CONTRACT_GATED_ENTITIES["branch"] = (2.7,
  "branches")`, one row in `CompanyService._CONTRACT_GATE_REQUIRED_VERSIONS` (the generic
  `contractGate` banner, never a brand-style method). `sink_for_company` passes `book` (from the
  company's own HTTP source connection) for a branch only, so the ingest body carries the
  top-level `book` the CRM requires; other entities' bodies are unchanged.
- **No deletions (D27):** `NO_DELETION_ENTITY_TYPES = {branch}`. The full-extract reconcile stages
  no delete for a vanished branch, counts it as the run summary key `vanished` ("known but absent from this full extract": recounted on every full run, not a running total), the delete guard
  has nothing to guard, and `sync_service` never calls `delete_batch` for it (the CRM has no
  branches deletions door and DOs reference branches).
- **Removed from the doc feed (D28):** the branches feed key, its vendor door, the branch-pull
  runner and run kind, the daily branch schedule, the backfill's branch step and its column
  (edited out of the unmerged migration `0023`; a dev DB that already ran it keeps a stray
  nullable column, harmless), the matching field on the backfill wire, and the third feeds row. A
  `branches` feed path answers 404.

## 1. Feeds and modes

One `ac_doc_feed` row per (tenant, company, feed); a never-configured feed reads `off`.

| Feed | Vendor doors | Kinds |
|---|---|---|
| `delivery_orders`, `goods_receive_notes` | `.../<doc>byLastModified` (poll), `.../<doc>bydocdate` (sweep, backfill) | poll, sweep, backfill |

Modes: `off` | `dry_run` | `push`. A feed carries its own open (no-auth) `autocount` connection;
the **book** is the last path segment of that connection's base URL
(`^[A-Za-z0-9_-]{1,20}$`). Turning a feed on (dry run or push) is refused unless the company's
Sorento sink is ready and the CRM contract is **>= 2.7 and lists the entity** (probed at config
time AND at the start of every run, fail closed). Explicit `connectionId: null` clears the
connection; an omitted key keeps it.

## 2. Cursor rule (poll)

Per (book, entity) the cursor is the first MYT day still to re-read. A tick reads
`min(cursor, today - pollLookbackDays) .. today` (MYT is fixed UTC+8, no DST; lookback default 1 =
yesterday), from the `byLastModified` door or, when the feed's `pollBasis` is `doc_date`, the
`bydocdate` door (DOC-FEED-WINDOW, §4a), capped at **31 days per tick**
(catch-up). The whole window is read BEFORE anything is pushed; any day failing = nothing pushed
and nothing advanced. One copy per DocKey (greatest `LastModified`), pushed oldest first. The
cursor advances **only on a fully successful live tick**; a dry run never advances it, never
writes the ledger and never writes issue rows. A record with no integer DocKey is `skippedNoKey`, never sent.

## 3. Verdicts, ledger, issues, D9 re-send

Verdicts match by `source_ref` (`{book}:DO|GRN:{DocKey}`).
`created | updated | unchanged` are delivered (**global sink change: `unchanged` counts as
delivered for every entity**); `unchanged` + warning `stale_ignored` never overwrites the ledger.
The ledger (what the CRM holds) is written only from delivered live verdicts. `retryable` and
unknown verdicts become a `retryable` issue row that keeps the **stored vendor record**
(capped at 64 KB; an over-cap document is stored without its record and is a `failed` row with a
named error, since it cannot be re-sent); each live poll re-sends retryable rows the fresh read
did not supersede (D9). `failed` is never re-sent and is cleared by a later delivery.

## 4. Re-check (content re-push + deletion sweep)

Daily per document feed (run kind `sweep`, shown as **Re-check**): read every day of the
`recheckDays` doc-date window (default **45**; all days must read). **Content step first
(DOC-FEED-WINDOW):** every document whose `content_digest` (sha256 of the canonical JSON of the
whole record, header + `Details`, `records.content_digest`) differs from the ledger's - or whose
ledger row has no digest yet, or has no ledger row - is pushed through the normal ingest path
(same verdict/ledger/issue rules as the poll; summary `rechecked` = documents read, `changed` =
documents pushed). A delivered verdict stores the record's digest on the ledger (poll and backfill
do the same), so after the first re-check only real edits re-push. This catches a line edit that
did not bump the header `LastModified` (unverified AutoCount behaviour, BL-SS-036): the CRM's
stale guard is strict `incoming < stored`, so an equal `LastModified` with changed lines answers
`updated`. A document whose open issue row already holds this exact content is skipped (`failed`
is never re-sent until it changes; `retryable` is the poll's D9 re-send). A `stale_ignored`
verdict records the digest without touching the rest of the ledger row (the CRM has seen it).
Keyless records count as `skippedNoKey`. A content-push sink error fails the run before any
deletion; a `DELETE_GUARD` refusal still FAILS the run, but the content pushes before it are
committed and their counters kept. The deletions endpoint's own `failed`/`total` are stored as
`deleteFailed`/`deleteTotal` (never added into the content step's `failed`). **Then deletions:**
union the DocKeys, and every ledger row in the window with no vendor copy is a candidate. A
candidate count over **max(50, 20% of the window's ledger rows)** refuses the sweep
(`DELETE_GUARD`). Otherwise the candidates go to the CRM deletions endpoint; a `deactivated` /
`not_found` verdict stamps `vanished_at`.

## 4a. Read window settings (DOC-FEED-WINDOW)

`ac_doc_feed.window_config` (JSON, module Alembic 0027; NULL = the defaults, i.e. the
pre-window behaviour): `pollBasis` `last_modified` (default) | `doc_date`; `pollLookbackDays`
0..30 (default 1); `recheckDays` 1..180 (default 45). Validated before any write
(`doc_feed/window.py validate_doc_feed_window`, per-field 422); omitted on a PUT = kept; a window
change never re-arms the schedule. Edited in the Configure dialog inside the same cadence cards
(Poll card: Read by + Look back; Re-check card: Window). Load: `recheckDays` vendor GETs per
re-check run, `pollLookbackDays + 1` per poll tick while the cursor is current (catch-up after an
outage still reads up to 31 days); never a write to AutoCount. Lookback 0 is safe: the cursor is
the previous tick's MYT day, so the first tick after midnight still re-reads the day before.
**DocDate basis trade-off:** the poll only sees documents dated inside its window - an edit to an
older document, or a document dated in the future, is picked up by the Re-check (or not at all
beyond `recheckDays`).

## 5. Backfill

A durable `ac_doc_feed_backfill` record: day by day, sequential, resumable, at most one OPEN
(`running|stopping|stopped`) per feed (partial unique index; a lost Start race is a 409
`BACKFILL_OPEN`). The day loop reads `bydocdate` per day and pushes it. Range floor `2023-01-01`
(a `fromDay` below it is a 422); `toDay` <= MYT today. Live needs the feed in `push`; Start is
refused (422) on an `off` feed even for a dry run. **Run-once guard:** a live range starting on
or before the floor 409s `BACKFILL_ALREADY_DONE` once `full_backfill_done_at` is set (a later
live range is allowed).

**Delivery accounting is by identity.** A chunk whose transient retries ran out is reported to
`on_chunk(error)` and is NOT credited while later chunks are; credited `source_ref`s are
tracked across 429 waits so a credited chunk is never re-sent and a failed one is never
dropped. A day with an uncredited failed chunk ends as a `SINK_ERROR` stop (the day is not
marked done). 429s wait up to 10 times per day, heartbeating the job and checking the orphan
fence before every sleep.

**Stop conditions** (backfill ends `stopped`, resumable, with a named `error_code`): operator
Stop (`stopping` -> `stopped` at the next day boundary); `JOB_ORPHANED`; `FEED_GONE`;
`FEED_OFF`; `FEED_NOT_PUSH` (live backfill, feed left push); `TENANT_INACTIVE` (tenant
suspended/archived or the module no longer active, the same predicate the beat uses); a vendor
day that cannot be read; a sink error. These are re-checked at the top of every day, because a
suspended tenant 403s every route and nobody can press Stop. Resume 409s `BACKFILL_JOB_LIVE`
while the previous job is still live and re-checks the Push rule. The orphan hook flips only
`running|stopping` backfills to `stopped` (never a `done` one) and closes any open run row by
`job_id` for both job types.

## 6. Failure text

A sink failure is stored on `run.error` / `backfill.error` through
`describe_consumer_failure(exc, sink=...)` (status + captured body, URL removed, API key
redacted, capped), never `str(exc)`.

A run row carries a summary dict from creation; a failed run keeps the counters of the steps that committed before the failure; the frontend still tolerates a null summary for legacy rows.

## 7. Scheduler and jobs

A 60 s beat tick claims due feeds with a guarded UPDATE (two beats never both enqueue) and
enqueues the SAME `autocount_doc_feed_run` job "Run now" uses; a busy feed is skipped, not
re-armed.

**Per-feed schedule (sprint-5/19).** `ac_doc_feed.schedule_config` (JSON, module Alembic 0026)
holds the cadence in the Entities task-schedule shape: `incrementalMinutes` = the poll (floor
1 minute, the with-watermark floor, since the poll reads `byLastModified`), `reconcileMode`
`interval` (`reconcileHours` >= 1) | `dailyAt` (`reconcileAt` `HH:MM`, UTC) = the deletion sweep.
NULL = poll every 60 minutes, sweep every 24 hours (the pre-19 hard-coded cadence).
`doc_feed/schedule.py` reuses `etl_service.validate_schedule` and `EtlService.next_run_times`.
The beat re-arms the claimed half from the feed's schedule. A PUT that carries `schedule` is
validated before any write; on an armed feed only the CHANGED half re-arms from now (editing the
poll never delays a sweep). An `off` feed stores it unarmed; arming from off sets
`next_poll_at = now` and `next_sweep_at` from the stored rule. Edited in the Configure dialog
with the same cadence cards as the Entities Schedule tab (`ScheduleCadenceCards`). The predicate is `active_tenant_service_join`
(`modules/autocount/scheduler.py`). Job types `autocount_doc_feed_run` and
`autocount_doc_feed_backfill` both heartbeat; the worker must import `modules.autocount.sync`
(which imports the handlers) or every doc-feed job stays Pending.

## 8. Wire (frontend contract)

A `DocFeedItem` carries `schedule` (`{incrementalMinutes, reconcileMode, reconcileHours,
reconcileAt}`, always resolved, never null) and `nextPollAt` / `nextSweepAt`. The PUT body is
`{connectionId?, mode, schedule?}`; omitting `schedule` keeps the stored one.

Lists answer the house envelope `{data, total, page}` and take `page`, `page_size` (the same as
`companies.py`). A `DocFeedIssue` row carries `id` (`<feed>:<book>:<docKey>`), `book`, `docKey`,
`docNo`, `docDate`, `sourceModifiedAt`, `kind`, `errors`, `warnings`, `attempts`, `firstAt`,
`lastAt`. A 422 is `{detail: {fieldErrors: {field: message}}, message}`; a 409 is
`{detail: {code, message}}`.

## 9. Sink changes (global, not feed-scoped)

`SorentoSink` gained: `book` (sent as a body key when set, absent otherwise, so every older
caller is byte-identical), `dry_run` on `write_batch` (`?dry_run=true` on every chunk),
`delete_doc_keys`, `errors` on `WriteResult`, and `unchanged` in the delivered set.

## 10. Migration and indexes

`0023_autocount_doc_feed` creates five new tables (no backfill needed: rows appear on first
configure). The models declare the migration's own index names explicitly (never
`index=True`, which auto-names `ix_app_autocount_...` and would double up on a create_all-first
host).

## 11. Delivery-orders pull snapshot (plan 16, BL-SS-286)

The CRM's "Pull from AutoCount" on Delivery Orders is NOT a run-now of this feed: it is a
third `entity` (`delivery_orders`) on the public pull gateway (`/api/v1/autocount/snapshots`,
plan 10 Appendix A), built by the same `autocount_pull_snapshot` job, stored in the same
`ac_pull_snapshot` / `ac_pull_snapshot_row` tables, pruned / expired / audited the same way.
**Contract of record: `documentation/plans/sprint-5/16-autocount-do-pull-snapshot-contract.md`.**
Facts a maintainer needs:

- **Scope:** flat `fromDay` / `toDay` / `docNo` on the build body (MYT doc-date days, 31-day
  cap, floor 2023-01-01, `toDay` <= MYT today; `docNo` alone = the 31 days ending today, filter
  only, the vendor has no by-DocNo door). Stored in `metadata_json` from creation and echoed on
  every response for this entity.
- **Source:** this feed's own `ac_doc_feed` row for `delivery_orders` (its connection and book)
  and the `bydocdate` door via `DocFeedVendor`, one GET per day. `doc_feed/runner.py`'s
  `resolve_vendor` is the shared vendor-side resolution (`_resolve` = `resolve_vendor` + the
  sink / contract-gate half). The feed's `mode` never gates a pull; the pull never touches the
  cursor, ledger, issue rows or the sink.
- **Rows:** the raw vendor DO dict verbatim (D18), one per `DocKey` (greatest `LastModified`),
  ordered `DocDate` asc / `DocKey` asc, `source_ref` column `{book}:DO:{DocKey}`; `book` on the
  header. No `EMPTY_EXTRACT` guard (a scoped range may be empty); any failed day =
  `SOURCE_PAGE_FAILED`, nothing partial; over 10,000 documents = `ROW_LIMIT`.
- **Lifecycle:** same-scope re-attach; a different scope while one is building = 409
  `BUILD_IN_FLIGHT`; the 60 s cooldown applies to the same scope only. The DO build body is
  `doc_feed/snapshot.py`, dispatched from `sync._run_pull_snapshot`.

### 11.1 Goods-received-notes pull snapshot (GRN mirror, lane GRN-PULL-SS)

`goods_receive_notes` is a fourth gateway `entity` built by the SAME code. The snapshot path is
generic over the doc feed: `pull_gateway_service.DOC_FEED_SNAPSHOT_ENTITIES` +
`is_doc_feed_entity`, `parse_doc_scope`, and `doc_feed/snapshot.build_doc_feed_snapshot`, which
reads `feed_row.feed`. Do not add a second builder. The differences from DO: the gate is the
company's `goods_receive_notes` feed row, the door is `/goodsreceivenotebydocdate`, and
`source_ref` is `{book}:GRN:{DocKey}`. **Operator reads** (`/autocount/pull/snapshots*`, session
auth) of a GRN snapshot also need `autocount.sync.read`
(`pull_service.SNAPSHOT_ENTITY_READ_PERMISSION`). Without it, the list hides GRN snapshots and
the header and rows read as an unknown id. Supplier and cost data never widens to
`autocount.pull.read` alone, the same rule as the doc finder's GRN type. The gateway itself is
key + company scoped, like DO, so `autocount.pull.manage` (who can issue a key) can still read
GRN through it (accepted with option (a); a per-key entity allowlist is the fix if needed). Contract: section 8 of the plan 16 contract.
