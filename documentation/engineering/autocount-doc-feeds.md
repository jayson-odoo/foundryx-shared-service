# AutoCount document feeds: Delivery Orders, Goods Receive Notes, Branches

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

## 1. Feeds and modes

One `ac_doc_feed` row per (tenant, company, feed); a never-configured feed reads `off`.

| Feed | Vendor doors | Kinds |
|---|---|---|
| `delivery_orders`, `goods_receive_notes` | `.../<doc>byLastModified` (poll), `.../<doc>bydocdate` (sweep, backfill) | poll, sweep, backfill |
| `branches` | `.../branchbypage` (paged, `pageSize` 1000) | branch pull only (no ledger, no issues, no sweep, no backfill) |

Modes: `off` | `dry_run` | `push`. A feed carries its own open (no-auth) `autocount` connection;
the **book** is the last path segment of that connection's base URL
(`^[A-Za-z0-9_-]{1,20}$`). Turning a feed on (dry run or push) is refused unless the company's
Sorento sink is ready and the CRM contract is **>= 2.7 and lists the entity** (probed at config
time AND at the start of every run, fail closed). Explicit `connectionId: null` clears the
connection; an omitted key keeps it.

## 2. Cursor rule (poll)

Per (book, entity) the cursor is the first MYT day still to re-read. A tick reads
`min(cursor, yesterday) .. today` (MYT is fixed UTC+8, no DST), capped at **31 days per tick**
(catch-up). The whole window is read BEFORE anything is pushed; any day failing = nothing pushed
and nothing advanced. One copy per DocKey (greatest `LastModified`), pushed oldest first. The
cursor advances **only on a fully successful live tick**; a dry run never advances it, never
writes the ledger and never writes issue rows. A record with no integer DocKey (or a branch with
a blank `BranchCode`) is `skippedNoKey`, never sent.

## 3. Verdicts, ledger, issues, D9 re-send

Verdicts match by `source_ref` (`{book}:DO|GRN:{DocKey}`, `{book}:BR:{AccNo}:{BranchCode}`).
`created | updated | unchanged` are delivered (**global sink change: `unchanged` counts as
delivered for every entity**); `unchanged` + warning `stale_ignored` never overwrites the ledger.
The ledger (what the CRM holds) is written only from delivered live verdicts. `retryable` and
unknown verdicts become a `retryable` issue row that keeps the **stored vendor record**
(capped at 64 KB; an over-cap document is stored without its record and is a `failed` row with a
named error, since it cannot be re-sent); each live poll re-sends retryable rows the fresh read
did not supersede (D9). `failed` is never re-sent and is cleared by a later delivery.

## 4. Deletion sweep

Daily per document feed: read every day of the **45-day** doc-date window (all days must read),
union the DocKeys, and every ledger row in the window with no vendor copy is a candidate. A
candidate count over **max(50, 20% of the window's ledger rows)** refuses the sweep
(`DELETE_GUARD`). Otherwise the candidates go to the CRM deletions endpoint; a `deactivated` /
`not_found` verdict stamps `vanished_at`.

## 5. Backfill

A durable `ac_doc_feed_backfill` record: day by day, sequential, resumable, at most one OPEN
(`running|stopping|stopped`) per feed (partial unique index; a lost Start race is a 409
`BACKFILL_OPEN`). The first segment runs the branch pull (when the branches feed is on for the
same book), then the day loop reads `bydocdate` per day and pushes it. Range floor `2023-01-01`
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

## 7. Scheduler and jobs

A 60 s beat tick claims due feeds with a guarded UPDATE (two beats never both enqueue) and
enqueues the SAME `autocount_doc_feed_run` job "Run now" uses: poll hourly, sweep and branch
daily; a busy feed is skipped, not re-armed. The predicate is `active_tenant_service_join`
(`modules/autocount/scheduler.py`). Job types `autocount_doc_feed_run` and
`autocount_doc_feed_backfill` both heartbeat; the worker must import `modules.autocount.sync`
(which imports the handlers) or every doc-feed job stays Pending.

## 8. Wire (frontend contract)

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
