# 14 - AutoCount DO / GRN / branch HTTP source, cursors, CRM sink (S1, S4)

UAC: `14-autocount-do-grn-http-source-acceptance-criteria.md` (the contract; this file is how we
meet it). Lane `.claude/worktrees/s60`, branch `feat/autocount-do-grn-http-source` off
`origin/main` 307de7b4 (module 0.11.0, module Alembic head `0022_autocount_preview_job`).
Backend :8014, frontend :3014, DB `foundryx_service_s60` (ports checked free 29 Sep; nobody
starts servers until S1). One PR, six thin slices (section 6). Size: 3-4 days.

Contract of record: the Sorento CRM cross-repo contract section 13 (contract 2.7, built on the
CRM side in sorento-crm PR #1356, plan `PLAN-autocount-grn-do-ingest-29sep.md`). This lane is the
shared-service half the CRM calls "S1 and S4" (13.12). Nothing here changes the CRM.

## 0. Owner rulings (29 Sep 2026, issue #1354, not reopened)

V1/Q12 hourly `byLastModified` poll per book for YESTERDAY and TODAY in Malaysia time. V5 JustNow
unused. V2 no pagination on the document endpoints (plain arrays); branches paged (pageSize max
1000, trust the echoed `TotalPages`). Q6 backfill by DocDate from 2023-01-01, one DocDate per
call, once, resumable, with a progress record; branch pull daily AND before any backfill. V4 SO /
PO stay on the DB transfer (out of scope). Q1 records go unmapped, exactly as returned, `Details`
included. Q5 the shared service holds the per-entity switch. V9 book `db1` = Sorento, company
code `SRT`. Scout Q9 deletion sweep over a trailing 45-day DocDate window. Link fields
(`FromDocType/FromDocNo/FromDocDtlKey`) pass through when present, never awaited. Verdicts:
`retryable` re-sent next tick, `failed` logged with the CRM errors (no auto retry), `unchanged` and
`stale_ignored` counted, never re-mapped; batches <= 1000 (deletions `doc_keys` <= 1000). Dry run
calls the doors with `?dry_run=true` and never advances cursors or ledgers.

## 1. Vendor and CRM surfaces (quoted exactly)

Vendor (open REST wrapper, the feed connection's base URL already ends in the book, plan 08 D2 -
`https://hapi.sorento.cc.cd/api/db1`). Casing differs per door; these strings are constants in
`doc_feed/constants.py` and pinned by a test:

| Use | GET (relative to base URL) |
|---|---|
| DO poll | `/deliveryorderbyLastModified?lastModified=yyyyMMdd` |
| DO backfill / sweep | `/deliveryorderbydocdate?DocDate=yyyyMMdd` |
| GRN poll | `/goodsreceivenotebyLastModified?lastModified=yyyyMMdd` |
| GRN backfill / sweep | `/goodsreceivenotebydocdate?DocDate=yyyyMMdd` |
| Branches | `/branchbypage?page=N&pageSize=1000` (answers `{TotalCount, Page, PageSize, TotalPages, Data}`) |

Live payload facts (#1354 orchestrator inspection): `LastModified` is a full naive MYT timestamp
(`2026-07-27T15:37:53.367`); the document doors answer bare arrays; no `FromDoc*` on any line;
`RefDocNo` empty, `OurPONo` null, `YourPONo` empty, `BranchCode` empty on all samples.

CRM (the company's Sorento connection: `baseUrl` + write-only `apiKey`, header `X-API-Key`):
`POST /api/v1/external/ingest/{delivery_orders|goods_receive_notes|branches}` body
`{companyCode, book, records}`; `POST /api/v1/external/ingest/{delivery_orders|
goods_receive_notes}/deletions` body `{companyCode, book, doc_date_from, doc_date_to, doc_keys}`;
`?dry_run=true` on all; `GET /api/v1/external/contract` must answer `version >= 2.7` and list the
entity. Verdicts always 200 `{dry_run, summary, records[{source_ref, outcome, entity_id, errors?,
warnings?, lines?}]}`; `source_ref` = `{book}:DO:{DocKey}`, `{book}:GRN:{DocKey}`,
`{book}:BR:{AccNo}:{BranchCode}`.

## 2. Fit: a dedicated document feed beside the ETL task framework (D1)

The existing ETL task framework (`ac_entity_config` + `HttpApiSource` + `sync.py` staging) was
read end to end and it fights this feed in four places:

1. **It is mapping-first.** Every record goes through `map_document` into a canonical class with
   an allow-listed `sink_payload()`, staged as `canonical_json` with a diff. Q1 forbids mapping.
2. **Its delete detection is a whole-population hash diff.** `HttpApiSource.fetch_changes` walks
   a full list and treats every known ref missing from it as deleted. A day-window read (yesterday
   and today) would mark every older document deleted - the phantom-delete trap plan 08 D8 exists
   to prevent.
3. **The deletions door is different.** `SorentoSink.delete_batch` posts `source_refs`; contract
   13.10 wants `doc_date_from/doc_date_to/doc_keys` and answers for the swept days only.
4. **The backfill unit is a day GET, resumable across hours.** The ETL paged-pass state
   (`ac_watermark.cursor_json`) tracks page walks of one endpoint, not a 1,368-day date loop.

So the feed is its own small package, `modules/autocount/doc_feed/`, and REUSES rather than
copies: `HttpApiClient` (SSRF re-check per request, pinned User-Agent, `CallRecord` with counters
only), `envelope.parse_page`, `HttpSourceError`, the retry constants of `http_source/source.py`,
`connection_sizing`, the `autocount` open connections and the company's Sorento connection
(Fernet key), `AcCompany` (`sink_impl`, `sink_connection_id`, `sorento_company_code`,
`is_active`), `SorentoSink` (extended with props, section 3.4), `CONTRACT_GATED_ENTITIES`, the
stock refusal gate (generalised, 3.5), the delete-guard constants, `background_jobs` +
`register_job_handler` + `JobService` heartbeat / cooperative cancel, the beat host, the module
orphan hook, `record_activity` / `record_client_calls`, and on the frontend the company detail
`ResourceForm` tabs, `ResourceList`, `StatusBadge`, `ActionMenu`, `SearchSelect`,
`DateRangePicker`, `JobProgress`, `ClampedText`, `useCan`, `useDatetime`.

## 3. Design

### 3.1 Data model (module migration `0023_autocount_doc_feed`, 23 chars, `app_autocount`)

Postgres-only existence-checked `create_table` (0022 convention), downgrade drops; `models.py`
declares them so `create_all` covers pytest. New tables only: no existing row gains a column, so
no backfill migration is needed (DoD 2); rows are created on first configure.

- **`ac_doc_feed`** - one row per (tenant, company, feed). `id`, `tenant_id` (idx), `company_id`
  (idx), `feed` (`delivery_orders|goods_receive_notes|branches`), `connection_id` (null),
  `book` (null, `String(20)`), `mode` (`off|dry_run|push`, default `off`), `cursor_day` (`Date`,
  null), `next_poll_at`, `next_sweep_at` (`UTCDateTime`, null, idx), `last_poll_at`,
  `last_poll_ok_at`, `last_sweep_ok_at`, `full_backfill_done_at` (`UTCDateTime`, null),
  `last_error` (`Text`), `last_error_code`, `created_at`, `updated_at`. Unique
  `(tenant_id, company_id, feed)`.
- **`ac_doc_feed_ledger`** - what the CRM holds from us. PK `(tenant_id, company_id, feed, book,
  doc_key BigInteger)`; `doc_no`, `doc_date` (`Date`), `source_modified_at` (`UTCDateTime`, the
  naive MYT `LastModified` converted), `last_outcome`, `pushed_at`, `vanished_at` (null). Index
  `(tenant_id, company_id, feed, book, doc_date)`.
- **`ac_doc_feed_issue`** - documents the CRM did not take. PK as the ledger; `kind`
  (`retryable|failed`), `doc_no`, `doc_date`, `source_modified_at`, `record_json` (the record as
  pulled, JSON), `errors_json`, `warnings_json`, `attempts`, `first_at`, `last_at`, `last_run_id`.
- **`ac_doc_feed_run`** - one row per job. `id`, `tenant_id` (idx), `company_id` (idx),
  `feed_id`, `feed`, `kind` (`poll|sweep|branch|backfill`), `dry_run`, `job_id` (idx),
  `day_from`, `day_to` (`Date`), `requests`, `fetched_count`, `summary_json`, `outcome`
  (`SUCCESS|FAILED|ABORTED`, the module's `RUN_*` constants), `error`, `error_code`,
  `started_at`, `finished_at`, `duration_ms`.
- **`ac_doc_feed_backfill`** - the durable progress record. `id`, `tenant_id`, `company_id`,
  `feed_id`, `feed`, `book`, `dry_run`, `from_day`, `to_day`, `next_day` (`Date`), `status`
  (`running|stopping|stopped|done`), `job_id`, `days_total`, `days_done`, `branch_step`
  (`done|skipped|null`), `summary_json`, `error`, `error_code`, `started_by` (actor user id),
  `started_at`, `finished_at`, `updated_at`. Partial unique index `(tenant_id, feed_id)` where
  `status <> 'done'` (postgresql_where + sqlite_where, the `AcPullSnapshot` precedent) = one open
  backfill per feed.

Summary JSON (runs and backfills): `{created, updated, unchanged, staleIgnored, failed, retryable,
resent, skippedNoKey, deactivated, notFound, candidates, warnings: {code: n}, failedRefs:
[first 20 {docKey|sourceRef, errors}]}`; keys absent read as 0.

### 3.2 Configuration and view (D2)

`services/doc_feed_service.py` `DocFeedService` (tenant from the JWT, company via
`CompanyService.get(tenant_id, company_id)` = 404 cross-tenant):

- `view(tenant, company_id)` -> three `DocFeedItem` (a missing row renders as `off`), plus
  `eligibleConnections`: `EtlService.list_http_connections(tenant)` filtered to
  `auth_mode == "none"` and a base URL whose last non-empty path segment matches
  `^[A-Za-z0-9_-]{1,20}$` (the CRM's `book` rule, 13.2); each item `{id, name, book}`. Each feed
  carries `contractGate` (3.5, one probe per request, memoised), `retryableCount`, `failedCount`,
  its open or last backfill, and the last run.
- `update(tenant, company_id, feed, {connectionId, mode})` -> upsert. `connectionId` must be one of
  the eligible ids (422 `fieldErrors.connectionId`); `book` is derived from it, never typed.
  `mode` in (`dry_run`, `push`) needs a connection, `company.sink_impl == "sorento"` with a Sorento
  connection, a non-blank `sorento_company_code`, and an open gate (422 `fieldErrors.mode`,
  message names the missing piece). `off -> on` arms `next_poll_at = now`, and for documents
  `next_sweep_at = now + 24h`; `-> off` clears both.
- No new permission keys (D2): read `autocount.companies.read`, configure
  `autocount.companies.manage`, actions `autocount.sync.run`, history `autocount.sync.read`. So no
  grant sweep is needed (DoD 4).

Router `routers/doc_feeds.py`, manifest entry `{"name": "doc_feeds", "prefix":
"/autocount/doc-feeds"}` (HTTP + Pydantic only):

| Method + path | Key | Body / answer |
|---|---|---|
| `GET /{company_id}` | companies.read | `DocFeedsView` |
| `PUT /{company_id}/{feed}` | companies.manage | `{connectionId, mode}` -> `DocFeedItem` / 422 |
| `POST /{company_id}/{feed}/run` | sync.run | `{kind: "poll"|"sweep"}` -> 202 `{jobId}`; 409 `RUN_IN_FLIGHT`; 422 mode off, or sweep on `branches` |
| `POST /{company_id}/{feed}/backfill` | sync.run | `{dryRun, fromDay?, toDay?}` -> 202; 409 `BACKFILL_OPEN` / `BACKFILL_ALREADY_DONE`; 422 |
| `POST /{company_id}/{feed}/backfill/{stop|resume|discard}` | sync.run | -> `DocFeedBackfillItem` |
| `GET /{company_id}/runs?feed=&page=&pageSize=` | sync.read | `{items, total}` newest first |
| `GET /{company_id}/issues?feed=&kind=&search=&page=&pageSize=` | sync.read | `{items, total}` |

Schemas in `schemas.py` (new section), `ApiModel` + camelCase `validation_alias`; dates on the
wire as ISO `yyyy-MM-dd`. Manifest version 0.12.0 and `http_source/client.py` `USER_AGENT` bumped
together (its comment requires it).

### 3.3 Vendor reads (`doc_feed/vendor.py`, D7, D8, D18, D19)

`DocFeedVendor(client: HttpApiClient)`: `day_by_last_modified(feed, day)`,
`day_by_doc_date(feed, day)`, `branches()`. Each GET uses the connection's
`connection_sizing(...).request_timeout_seconds`, the same ladder as `HttpApiSource._fetch_page`
(timeout once more after 1s, connect error / 5xx / 524 up to `TRANSPORT_RETRY_BACKOFFS_SECONDS`),
then `parse_page`. A document door answering a paged envelope with `TotalPages > 1` raises
`VENDOR_PAGED` (never a silent first page). Error codes: `VENDOR_TRANSPORT` (incl. SSRF block),
`VENDOR_HTTP`, `VENDOR_NOT_JSON`, `VENDOR_SHAPE`, `VENDOR_PAGED`. The branch walk loops pages from
1 until `Page >= TotalPages` (echoed) or empty `Data`, cap 100 pages.

`doc_feed/records.py`: `doc_key(record) -> Optional[int]` (int or integer string), records without
one are not sent (`skippedNoKey`, D19); likewise a branch record with a blank `BranchCode` is not
sent (the CRM would answer `failed` with `source_ref: null`, which no record could be matched to); `dedupe_latest(records)` keeps one record per DocKey, the
greatest `LastModified` string (the vendor's one fixed ISO format sorts lexically, plan 08 D7);
push order = `LastModified` ascending; `source_ref(feed, book, record)` exactly as 13.3 derives it;
`doc_date(record)` parses ISO date / datetime / `yyyyMMdd` (None when unparseable - such a record
is still sent; the CRM fails it and no ledger row appears); `vendor_modified_at(record)` = naive
`LastModified` read as MYT, converted to aware UTC.

Records are parsed with the standard JSON parser and posted with the standard encoder: key order,
unknown keys, `Details` and future `FromDoc*` fields survive; numbers stay JSON numbers of equal
value (D18). The fixture test asserts `json.loads(request_body)["records"][i] ==
vendor_fixture[i]`.

### 3.4 CRM sink: extend `SorentoSink`, never a second client (D3, D22)

`sinks_sorento.py`:

- `_ENTITY_PATH` += `delivery_orders`, `goods_receive_notes`, `branches` (the feed keys ARE the
  door names; they cannot collide with the legacy canonical `goods_received_note`, which keeps no
  path and still routes to the logging sink - AC-14-80).
- `DOC_FEED_CONTRACT_VERSION = 2.7`; `CONTRACT_GATED_ENTITIES` += the three rows
  `(2.7, "<door>")`.
- `_DEPENDENT_ENTITIES` += `delivery_orders`, `goods_receive_notes` (a `retryable` for an
  unresolved ItemCode / Location is expected and self-resolving); `_result_for`'s dependency
  sentence gains "its product or warehouse".
- `_OUTCOME_DELIVERED` += `unchanged` (contract 2.6/2.7 verdict; today it would fall through to
  "unrecognised outcome" -> retryable, which is wrong for every entity). Pinned for a master too.
- `WriteResult` (`sinks.py`) gains `errors: Optional[Dict[str, Any]] = None`, filled on `failed`
  and `retryable` so the issue row keeps the CRM's own map; warnings are carried on every verdict
  that has them (today delivered only).
- `SorentoSink.__init__(..., book: Optional[str] = None)`; `_body` adds `"book"` right after
  `companyCode` when set (one helper for ingest and deletions, unchanged when `None`).
- `write_batch(..., dry_run: bool = False)` passes through to `_post_with_retry` (today hard-coded
  `False`). Chunking, `on_chunk` per-chunk commit, 429 `Retry-After`, 502/503/504 retry and
  concurrency are all reused unchanged.
- `delete_doc_keys(doc_keys, *, doc_date_from, doc_date_to, dry_run, on_chunk=None)` -> posts
  `ingest/{segment}/deletions` with `{doc_date_from, doc_date_to, doc_keys: chunk}` via
  `_post_with_retry`, chunked at `batch_size`; merged `{summary, records}`. Verdict matching per
  the CRM code (C1, section 10): each record echoes ONLY `source_ref` = `{book}:DO:{DocKey}` /
  `{book}:GRN:{DocKey}` (no `doc_key` field); the sink parses the DocKey as the integer after the
  last `:` and matches it to the key it sent. Outcomes: `deactivated` (`entity_id`), `not_found`,
  `failed` (`errors.doc_date`, `entity_id`). A non-integer key would answer `failed` with
  `errors.doc_key` and `source_ref` = the raw value; we never send one (D19), so such a verdict is
  counted as `failed` in `summary.failedRefs` and matched to no ledger row. A key with no verdict
  reads as `failed` (`no verdict`) and is re-evaluated by the next sweep. The CRM rolls a dry run
  back, so its verdicts are real predictions.
- `RawVendorRecord(CanonicalRecord)` in `doc_feed/records.py`: `raw: Dict[str, Any]`,
  `entity_type = feed`, `source_ref` = 13.3's derivation, `sink_payload()` returns `raw` - so
  `_to_records` / `_chunk_results` match verdicts with no change.
- Batch size = `settings.autocount_sink_batch_size` (default 200) clamped by the existing
  `SORENTO_MAX_BATCH` (1000). No new setting.
- The feed sink is built by `sorento_sink_from_connection(..., entity_type=feed,
  company_code=company.sorento_company_code, book=feed.book)` (new passthrough kwarg).

### 3.5 Contract gate (D4)

`CompanyService.stock_push_gate_error` is refactored into a private
`_contract_refusal(tenant_id, company, required_version, entity_name, cache_key)` that both
`stock_push_gate_error` (behaviour byte-identical, its tests stay green) and the new
`doc_feed_gate_error(tenant_id, company, feed)` call. Refusal semantics: no Sorento connection,
config fault (`reason: config_error`), unreachable probe, version < 2.7, or the door name missing
from `entities` all refuse. Checked at `update` (mode on) and again at the start of every run
(`CONTRACT_GATE`, AC-14-26).

### 3.6 Poll, cursor and retry (D5, D6, D7, D9, D10, D11)

`doc_feed/clock.py`: `MYT = timezone(timedelta(hours=8), "MYT")` (fixed offset, Malaysia has no
DST, no tzdata dependency on the slim image), `myt_date(utc)`, `yyyymmdd(date)`.

`doc_feed/runner.py` (service layer; repositories do every query) `run_poll(db, feed_row, *,
dry_run, now, vendor_transport=None, sink_transport=None)`:

1. Resolve and refuse: company active (`COMPANY_INACTIVE`); feed connection tenant- and
   provider-scoped, open auth, book still equal to the stored book (`NO_CONNECTION`,
   `BOOK_MISMATCH`); Sorento sink + company code (`SINK_NOT_READY`); gate (`CONTRACT_GATE`).
2. Window: `today = myt_date(tick_started_at)`, `start = today - 1` if `cursor_day` is None else
   `min(cursor_day, today - 1)`, `end = today`; when the span exceeds 31 days, `end = start + 30`
   (capped).
3. Read every day of the window; any failure -> run `FAILED` with the vendor code, nothing posted.
4. `dedupe_latest` over the read. Live only: add every `retryable` issue row of (feed, book) whose
   DocKey was not read this tick (`resent`), from its stored `record_json`; a DocKey that WAS read
   uses the fresh copy (supersede).
5. `sink.write_batch(RawVendorRecord..., dry_run=dry_run, on_chunk=...)`; per chunk (live), in one
   commit: delivered -> ledger upsert (`vanished_at = NULL`; on `stale_ignored` insert-if-absent
   only, never overwrite `doc_date` / `source_modified_at`, AC-14-56) and delete the issue row;
   `retryable` -> issue upsert kind `retryable`, `attempts + 1`, record + errors; `failed` -> issue
   upsert kind `failed`, errors. Counters and warning tally in both modes. Ledger / issue upserts
   are `INSERT .. ON CONFLICT DO UPDATE` (poll and backfill may overlap on one DocKey).
6. A chunk error (transient exhausted) or a raised sink error -> run `FAILED`, cursor unchanged
   (chunks already committed keep their effects; the next tick re-sends and the CRM answers
   `unchanged`).
7. Success, live only: `cursor_day = end + 1` when capped, else `myt_date(tick_started_at)`;
   `last_poll_ok_at = now`. Dry run never writes cursor, ledger or issues (AC-14-27, 32).

Why the cursor is a DAY and not a timestamp: the vendor filter is a day; a tick at 10:00 has read
all of today up to 10:00, so the next tick must re-read today; storing the first day still to
re-read makes catch-up after an outage a plain range walk. Yesterday stays in every window per the
ruling (it catches a 23:50 edit read at 00:10).

Retry store = the stored record, not a refetch (D9): there is no by-DocKey vendor door, and a
refetch by the stored DocDate would cost a day GET per waiting document. The CRM stale guard makes
re-sending an older copy harmless. `failed` rows are never re-sent: the next vendor edit brings the
document back through the poll by itself (ruling: no auto retry).

No local "unchanged" skip (D10): every record read is sent and the CRM's `unchanged` is the
authority. Cost measured: about 300 documents a day x 2 days x 24 polls = 14k record-posts a day in
roughly 72 POSTs a day per feed at batch 200 - far inside the 600 req/min key limit. Skip-by-hash
is backlogged with that trigger (BL-SS-287).

Branch pull `run_branch_pull(...)`: walk all pages, `write_batch` every record with a non-blank
`BranchCode` (matched on `{book}:BR:{AccNo or ''}:{BranchCode}`, so `db1:BR::HQ` when `AccNo` is
absent, C2), counters, failed
refs into `summary.failedRefs`; no ledger, no issue rows (the CRM has no branch deletions door;
the next daily pull re-sends everything).

### 3.7 Deletion sweep (D12)

`run_sweep(...)`, daily per document feed (and on demand), in the feed's mode:

1. Window `from = today - 44`, `to = today` (45 MYT days).
2. Read `bydocdate` for every day; any failure -> `FAILED`, no POST (only speak for days read).
3. `seen` = union of DocKeys over all 45 days (a DocDate moved inside the window is not vanished).
4. `candidates` = ledger rows of (feed, book) with `doc_date` in the window, `vanished_at IS NULL`,
   DocKey not in `seen`.
5. Guard: `len(candidates) > max(DELETE_GUARD_MIN_ABSOLUTE, DELETE_GUARD_RATIO x window ledger
   rows)` -> `FAILED` `DELETE_GUARD` (the shared 50 / 20% constants; an outage answering `[]` for
   several days cannot mass-cancel).
6. `sink.delete_doc_keys(candidates, doc_date_from=from, doc_date_to=to, dry_run=...)`. Live:
   `deactivated` / `not_found` -> `vanished_at = now`; per-key `failed` (e.g. `errors.doc_date`)
   -> `summary.failedRefs`, ledger untouched so the next sweep re-evaluates it.
7. Live success -> `last_sweep_ok_at`. A later delivered push clears `vanished_at` (the CRM
   answers `restored`).

Known race, self-healing: a document whose DocDate is edited out of the window between the last
poll and the sweep is posted as vanished; the next poll pushes it and the CRM restores it
(13.10). Running the sweep after a same-hour poll keeps the window small; no extra machinery.

### 3.8 Backfill (D13)

Job `autocount_doc_feed_backfill`, payload `{backfillId}`; `run_backfill(...)`:

1. Start (service): refuse `branches` (422), a second open backfill (409 `BACKFILL_OPEN`), a live
   backfill when the feed is not in `push` (422 `mode` - the hourly push must already run, so no
   edit between "backfill read that day" and "poll started" can be lost), `fromDay > toDay` or
   `toDay > today` (422). Run-once guard: live AND `fromDay <= 2023-01-01` AND
   `full_backfill_done_at` set -> 409 `BACKFILL_ALREADY_DONE`. Defaults `fromDay = 2023-01-01`
   (`DOC_FEED_BACKFILL_FROM`), `toDay = today` (MYT, fixed at start). Row status `running`,
   `next_day = from_day`, then enqueue.
2. Branch step (first run of the backfill only): when the company's `branches` feed is not `off`
   and is on the same book, run the branch pull in the backfill's own dry-run-ness
   (`branch_step: done`), else `skipped`.
3. Loop `day` from `next_day` to `to_day`, sequential: GET bydocdate, dedupe, push (same verdict
   handling as 3.6 step 5, live or dry), then in one commit `next_day = day + 1`, `days_done`,
   summary; heartbeat; re-read the backfill status and the job's `fresh_status`; `stopping` or
   aborted -> `stopped`, finish the job.
4. Vendor failure or batch-level push failure -> `stopped` with `error`/`error_code`, resumable at
   that day. `SorentoRateLimited` -> sleep `retry_after`, retry the same day, max 10 consecutive,
   then `stopped`.
5. Past `to_day` -> `done`; live and `from_day <= 2023-01-01` -> `feed.full_backfill_done_at =
   now`.

Resume sets `running` and enqueues a new job from `next_day`; Discard closes a `stopped` backfill
(status `done`, `error_code = DISCARDED`, full-history flag untouched). Every job segment writes
one `ac_doc_feed_run` row (kind `backfill`). Rate: strictly sequential, one vendor GET per day plus
one CRM POST per non-empty day per 200 records - about 1,368 GETs per feed for the full range; no
artificial pause (the vendor answered 13k requests a day without complaint, plan 13 R8; the CRM
429 path is handled).

Ranged live backfills stay allowed after the full one: they are the "re-pull these days" tool the
scout asked for and what the owner's 3-day hand test needs; the CRM makes a repeat idempotent.

### 3.9 Schedule, jobs, orphan hook (D14, D15)

- Beat: `"autocount-doc-feed-sweep": {"task": "autocount.doc_feed_sweep", "schedule": 60.0}` in
  `app/workflow_engine/worker.py`, task body calls `doc_feed/scheduler.sweep_doc_feeds(db)`,
  failure-isolated like `autocount.etl_sweep`.
- `sweep_doc_feeds`: feeds with `mode != off` joined through the SAME tenant / service-active
  predicate `sweep_etl_tasks` uses (extract it into one helper in `scheduler.py`, both callers use
  it; `sweep_etl_tasks` behaviour unchanged), company `is_active`. Per feed: skip (no claim) if an
  `autocount_doc_feed_run` job for that feed is unfinished (so a busy feed is simply picked up the
  next minute - no lost tick, no skip rows); else claim with a guarded `UPDATE` (the
  `_sweep_one` pattern) and enqueue ONE of: documents `poll` (due `next_poll_at <= now`, re-arm
  +60 min) else `sweep` (due `next_sweep_at <= now`, re-arm +24 h); branches `branch` (due
  `next_poll_at`, re-arm +24 h). Stuck jobs are cleared by core's orphan / undispatched sweeps
  (heartbeats).
- Jobs: `autocount_doc_feed_run` (payload `{feedId, kind}`, dry-run-ness read from the feed's mode
  at run start) and `autocount_doc_feed_backfill`, both `heartbeats=True`, defined in
  `doc_feed/jobs.py` and registered from the tail of `sync.py` (the worker import footgun
  `register_autocount_sync_handler` documents); `tests/test_worker_module_boot.py` extended.
- `bootstrap.on_job_orphaned`: an orphaned feed job closes its open run row (`FAILED`,
  "Interrupted"); an orphaned backfill job sets its backfill `stopped` with the same error.
- Eager dev (`CELERY_TASK_ALWAYS_EAGER=true`, no beat): nothing runs on a schedule; Run now and
  Backfill run inline in the request. The runner takes `vendor_transport` / `sink_transport`
  (test-only, `None` in production); `DocFeedService` threads the router's `get_http_transport`
  value through when eager, the `preview_job` precedent.

### 3.10 Frontend (D17)

One new tab on the existing company detail `ResourceForm` (`company-detail-view.tsx`): id `feeds`,
label "Document feeds", icon `FileStack`. No new route, no menu change.

- `doc-feeds-tab.tsx` stacks three embedded `ResourceList`s (`embeddedListConfig`), full width,
  stacking naturally at 375px:
  1. `use-doc-feeds-list-config.tsx` - rows = the three feeds. Columns: Feed, Book, Mode
     (`StatusBadge`, registry `AC_DOC_FEED_MODE_REGISTRY`: Off / Dry run / Push), Covered through
     (`cursorDay`), Last run (`useDatetime` + outcome badge), Waiting, Failed, Backfill
     (`JobProgress` with `unit="days"` while running; badge Stopped / Done otherwise).
     `rowHref: '#'`. Row `ActionMenu` (each gated by `useCan`, only valid ones listed): Configure,
     Run now, Run sweep now (documents, mode on), Backfill (documents, no open backfill), Stop /
     Resume / Discard (by backfill state).
  2. `use-doc-feed-runs-list-config.tsx` - kind, dry-run badge, day range, fetched, created /
     updated / unchanged / stale / failed / retryable, deactivated / not found, outcome, error
     (`ClampedText`), duration. Feed filter as a `SearchSelect` segment.
  3. `use-doc-feed-issues-list-config.tsx` - feed, DocNo, DocDate, kind badge (Waiting / Failed),
     errors (`ClampedText`, `field: message` pairs), attempts, last attempt. Kind and feed filters,
     DocNo search (`ListSearchInput` via the shell).
- `doc-feed-config-dialog.tsx` (the `EntityLookbackDialog` pattern): Connection `SearchSelect`
  over `eligibleConnections` (label "name - book"), Mode `SearchSelect` whose options are Off, plus
  Dry run and Push only when a connection is chosen and `contractGate` is `null`; a shut gate
  renders a warning `Alert` titled with the consumer version vs 2.7 (state, not instructions).
- `doc-feed-backfill-dialog.tsx`: Dry run `Switch`, `DateRangePicker` defaulting to 2023-01-01 ..
  today, Start.
- `JobProgress` gains an optional `unit` prop (`'pages'` default, `'days'`); existing call sites
  unchanged.
- Layering: `types/autocount.ts` (feed types) -> `services/autocount-service.{ts,mock,real}.ts`
  (`getDocFeeds`, `updateDocFeed`, `runDocFeed`, `startDocFeedBackfill`, `stopDocFeedBackfill`,
  `resumeDocFeedBackfill`, `discardDocFeedBackfill`, `listDocFeedRuns`, `listDocFeedIssues`) ->
  `hooks/use-autocount-doc-feeds.ts` (polls every 5 s while a run or backfill is in flight) -> UI.
  `autocount-meta.ts` gains the feed labels and the mode / run-kind / issue-kind registries.
- Frontend-first: S1 binds the doc-feed methods through a scoped `withPhase1DocFeedMock(...)`
  overlay tagged `PHASE 1 MOCK` in `autocount-service.ts` (the plan-13 `withPhase1PushGateMock`
  precedent); S5 deletes the overlay (one line) so every method is real.
- Copy: labels and values only; tenant-facing text never names the platform.

## 4. Decision log

| # | Decision | Why |
|---|---|---|
| D1 | Dedicated `doc_feed` package beside the ETL task framework; heavy reuse of its transports, connections, sink, gate, jobs, beat | The task framework is mapping-first, deletes by whole-population diff, and has no day-loop state (section 2) |
| D2 | Feed row per (company, entity) with mode `off / dry_run / push`, own connection, book derived from the base URL; no new permission keys | Q5 per-entity switch; book = the vendor path segment (13.2); existing keys cover read / manage / run |
| D3 | Extend `SorentoSink` (book prop, `dry_run` on `write_batch`, `delete_doc_keys`, `unchanged` delivered, `errors` on `WriteResult`) + `RawVendorRecord` | One CRM client: 429, transient retry, per-chunk commit, concurrency stay single-sourced |
| D4 | Refusal gate 2.7 + entity listed, generalised from the stock gate, checked on mode-on and at every run | 13.1 contract version; never guess a contract we cannot see |
| D5 | Cursor = first MYT day still to re-read; window `min(cursor, yesterday) .. today`, catch-up capped at 31 days a tick; advances only on a fully successful live tick | Day-filtered source; outage catch-up is a range walk; dry run never advances |
| D6 | MYT as fixed UTC+8 | Malaysia has no DST; no tzdata dependency |
| D7 | Read the whole window first, then push; any day failing = nothing pushed | A partial read must never advance anything |
| D8 | One copy per DocKey (greatest `LastModified`), pushed oldest first | Stale guard friendly; no duplicate verdicts |
| D9 | Issue table: `retryable` re-sent from the stored record each live poll, superseded by a fresher read; `failed` never re-sent, cleared by a later delivery | Rulings; no by-DocKey vendor door |
| D10 | No local unchanged-skip | Simplest; measured load is small; BL-SS-287 holds the trigger |
| D11 | Ledger only from delivered live verdicts; `stale_ignored` never overwrites | The sweep must compare with what the CRM holds |
| D12 | Daily 45-day sweep, union of keys, all days must read, 50 / 20% guard, window bounds as the range, `vanished_at` | 13.10 "only speak for days read"; outage safety |
| D13 | Durable backfill record, day by day, sequential, branch step first, stop / resume / discard, run-once on the full-history range only, live needs the feed in push | Q6 once + resumable; the owner's 3-day test; no gap between backfill and poll |
| D14 | New 60 s beat tick; poll hourly, sweep and branches daily; a busy feed is not claimed | Rulings; no lost ticks, no skip-row noise |
| D15 | Two heartbeating job types + orphan hook | House job pattern; crash leaves a resumable backfill |
| D16 | Own run table, not `ac_sync_run` | Its rows link to the staged-review surface and carry staging counters |
| D17 | One new company tab, three shell lists, two dialogs, `JobProgress unit` prop, mock overlay then swap | Minimum new UI; resource shell; frontend-first |
| D18 | Records re-sent as parsed JSON; numbers stay JSON numbers of equal value | Q1 unmapped; fixture-pinned equality |
| D19 | A record with no integer DocKey, or a branch with a blank `BranchCode`, is not sent (`skippedNoKey`) | The CRM would answer `failed` with a raw or null `source_ref` that no record or ledger key could be matched to (C1, C2) |
| D20 | Legacy `goods_received_note` untouched (no path, logging sink) | No double push; parity-pinned |
| D21 | Tests named `test_s14_*`; `tests/conftest.py` `_LIVE_NETWORK_BLOCK_FILE_RE` gains `s14_` | The autouse no-network guard must cover the new files |
| D22 | Batch = existing `autocount_sink_batch_size` clamped to 1000 | Ruling <= 1000; no new knob |

## 5. Files

Backend (`service_backend/modules/autocount/`): new `doc_feed/{__init__,constants,clock,vendor,
records,runner,jobs,scheduler}.py`, `repositories/doc_feed_repository.py` (feeds, ledger, issues,
runs, backfills; every query tenant-scoped), `services/doc_feed_service.py`, `routers/doc_feeds.py`,
`alembic/versions/0023_autocount_doc_feed.py`; edited `models.py` (5 models + constants),
`schemas.py`, `sinks.py` (`WriteResult.errors`), `sinks_sorento.py` (3.4),
`services/company_service.py` (`_contract_refusal`, `doc_feed_gate_error`), `scheduler.py`
(shared predicate helper), `sync.py` (tail registration import), `bootstrap.py`
(`on_job_orphaned`), `manifest.json` (0.12.0, router), `http_source/client.py` (`USER_AGENT`).
Core: `app/workflow_engine/worker.py` (beat entry + task). Tests: `tests/conftest.py` (regex).

Frontend (`service_frontend/`): `types/autocount.ts`, `services/autocount-service.{ts,mock,real}.ts`,
`hooks/use-autocount-doc-feeds.ts`, `app/(protected)/autocount/components/autocount-meta.ts`,
`app/(protected)/autocount/companies/components/{company-detail-view,doc-feeds-tab,
use-doc-feeds-list-config,use-doc-feed-runs-list-config,use-doc-feed-issues-list-config,
doc-feed-config-dialog,doc-feed-backfill-dialog}.tsx`, `components/platform/autocount/
job-progress.tsx` (`unit`); tests beside each.

Docs: this pair, `14-fixtures/` (+ README provenance), `14-evidence/`, the test report,
`docs/reference/` AutoCount section (feed table, cursor rule, sweep guard), backlog rows
(section 8) appended to `documentation/backlogs/backlog.md` in S0 by the coordinator.

## 6. Slices (one PR)

| Slice | Scope | UAC |
|---|---|---|
| S0 | Docs commit (this). Fixtures `14-fixtures/`: vendor DO and GRN day arrays and a two-page `branchbypage` (live field lists from #1354, values anonymised), CRM `contract` 2.7, ingest responses covering every verdict and warning, a deletions response, 429 / 502 responses. Tester writes the red pytest files and Vitest cases | red for all `[BE]` / `[FE]` |
| S1 FE mock | Types, overlay mock with every state (unconfigured, gate shut, dry run with runs, push with cursor and issues, backfill running / stopped / done, no permission), hook, meta, tab, lists, dialogs, `JobProgress unit`; agent-browser 375 / 1280 against the mock | AC-14-90..95, E1 |
| S2 BE config | Migration + models + repositories, `DocFeedService.view/update`, eligible connections, gate refactor, router, schemas, manifest | AC-14-01..06, 80..82 |
| S3 BE poll + branches (owner S1) | Vendor, records, sink extension, `run_poll`, `run_branch_pull`, issues, ledger, cursor, jobs, beat, scheduler, orphan hook, Run now, runs / issues lists | AC-14-10..13, 20..27, 30..33, 40, 41, 56, 70..72, 83 |
| S4 BE sweep + backfill (owner S4) | `run_sweep`, `delete_doc_keys`, backfill service + runner + actions | AC-14-42, 50..55, 60..65 |
| S5 wire + evidence | Delete the mock overlay, prod build, agent-browser on the lane stack (live vendor `db1`, CRM copy :8107 dry run), test report keyed to UAC ids; reviewer (Opus) on S2..S4, codex second opinion on `doc_feed/` + sink diff; owner hand test (section 9) | AC-14-E2, E3 |

Rules: S1 before any backend code; S2..S4 red-green (tester first); one coder at a time on the
branch; every brief embeds the PRINCIPLES design mandates, DoD gate and hard-fail list.

## 7. Tests (TDD order, tester writes red first)

Backend (pytest, SQLite `create_all`, every HTTP call through `httpx.MockTransport`; files match
the no-network guard after D21):

1. `test_s14_doc_feed_clock_records.py` - MYT day at 15:59Z / 16:00Z, `yyyymmdd`, `doc_key`
   (int / string / missing / bool), `dedupe_latest`, sort, `source_ref` for DO / GRN / branch
   (empty AccNo), DocDate parse forms, `LastModified` -> UTC. Vendor path constants (AC-14-10).
2. `test_s14_doc_feed_cursor.py` (owner: cursor) - no cursor = yesterday + today; advance to tick
   day; 3-day catch-up in one run; 40-day catch-up capped at 31 then continued; vendor failure and
   batch failure keep the cursor; dry run never moves it (AC-14-11, 30..32).
3. `test_s14_doc_feed_batching.py` (owner: batching) - 2,500 records -> no body over 1000 with the
   setting at 5000; 200 by default; deletions 1,500 keys -> chunks <= 1000; body order
   `companyCode, book, records`; fixture JSON equality incl. `Details` and an unknown key
   (AC-14-20, 21).
4. `test_s14_doc_feed_verdicts.py` (owner: verdicts) - `unchanged` delivered (plus a master
   control); `stale_ignored` counted, ledger not overwritten; `retryable` -> issue with record +
   errors, re-sent next live poll outside the window, superseded by a fresher read, cleared on
   delivery; `failed` -> issue with errors, not re-sent, cleared on a later delivery; unknown word
   and missing verdict -> retryable; warning tally (AC-14-22..24, 56).
5. `test_s14_doc_feed_config.py` - view defaults, eligible connections (auth, segment rule, tenant
   B), PUT 422s per field, mode gate: no sink / blank code / 2.6 / entity missing / unreachable /
   config error; arming and disarming; 403 per key; 404 cross-tenant; stock gate unchanged
   (AC-14-01..06).
6. `test_s14_doc_feed_poll.py` - vendor error codes (paged, not JSON, 5xx after ladder, SSRF
   block) push nothing; 429 wait; 502 retried; chunk failure keeps committed chunk effects;
   `CONTRACT_GATE` at run time; dry run writes nothing; branch walk to echoed `TotalPages`
   (pageSize clamp echo) and verdict matching; activity records counters only, key masked
   (AC-14-12, 13, 25..27, 40, 41, 72).
7. `test_s14_doc_feed_scheduler.py` - due poll hourly, sweep and branch daily, busy feed not
   claimed, off / inactive company / inactive module / suspended tenant excluded, guarded claim
   under two sweeps; job registration; orphan hook (AC-14-33, 83).
8. `test_s14_doc_feed_sweep.py` - 45 GETs with the window dates; union rule (moved DocDate);
   one failed day -> no POST; guard at 51 of 100 vs 50 floor; `deactivated` / `not_found` set
   `vanished_at`; later push clears it; per-key `failed errors.doc_date` counted and re-evaluated;
   dry run writes nothing; deletions verdicts matched by the `source_ref` DocKey suffix, an
   unparseable `source_ref` and a missing verdict counted as failed (AC-14-42, 50..55).
9. `test_s14_doc_feed_backfill.py` (owner: backfill resume) - branch step then day loop order;
   interrupt after day 3 of 7 (orphan) -> `stopped`, Resume starts at day 4 and no day 1..3 GET is
   repeated; Stop at a day boundary; Discard; run-once 409 on full history, ranged live allowed,
   dry run unguarded; 409 open; 422 mode / branches / range; 429 ten waits then stopped; dry run
   writes nothing (AC-14-60..65).
10. `test_s14_doc_feed_integration.py` (owner: integration) - one stubbed vendor + one stubbed CRM
    (`MockTransport` routers keyed by path): live poll -> ledger + issues + cursor; 3-day live
    backfill -> ledger; sweep after the stub vendor "deletes" one DocKey -> exactly that key posted
    with the window dates, `vanished_at` set; route-level Run now through `get_http_transport`
    override (AC-14-E2 backend half, T5).
11. `test_s14_doc_feed_structure.py` - parity: feed keys disjoint from `ETL_ENTITY_TYPES`, in
    `_ENTITY_PATH` and `CONTRACT_GATED_ENTITIES`; `goods_received_note` has no path and resolves to
    the logging sink; manifest router; runs / issues lists tenant-scoped + filters; migration
    revision length and single head (AC-14-70, 71, 80..82). Live-Postgres migration check
    (`alembic upgrade` / downgrade on `foundryx_service_s60`) is a S2 manual gate, logged in the
    report.

Frontend (Vitest / RTL): `doc-feeds-tab.test.tsx` (three rows, states, actions by permission),
`doc-feed-config-dialog.test.tsx` (only eligible connections; Dry run / Push absent with no
connection or shut gate; warning alert), `doc-feed-backfill-dialog.test.tsx` (defaults, dry run),
`use-doc-feed-runs-list-config.test.tsx`, `use-doc-feed-issues-list-config.test.tsx`,
`job-progress.test.tsx` (`unit` days, pages default unchanged),
`services/autocount-service.mock.doc-feeds.test.ts`, `hooks/use-autocount-doc-feeds.test.ts`
(polling only while in flight).

E2E (agent-browser only, never Playwright): E1 on the mock build, E2 / E3 on the lane stack; real
clicks from the sidebar; 375 and 1280 screenshots and a README run log under `14-evidence/<slice>/`;
timestamped names; `--session` per lane.

## 8. Backlog (append to `documentation/backlogs/backlog.md`)

| ID | Title | Source plan | Priority | Status |
|---|---|---|---|---|
| BL-SS-286 | DO / GRN pull gateway for the CRM verification screen (a shared-service snapshot by day, the products / stock pull pattern) if CRM S3 needs more than the dry-run counters (Q1, decided by default: Dry run mode is the verification step) | [sprint-5/14](../plans/sprint-5/14-autocount-do-grn-http-source.md) | Medium | Open |
| BL-SS-287 | Skip re-sending a document whose raw record hash equals the last delivered one (the hourly poll re-sends yesterday + today); trigger: CRM ingest load or 429s from the feed | sprint-5/14 | Low | Open |
| BL-SS-288 | Byte-bounded chunking for document batches (200 DOs near the 2,000-line / 1 MB record cap is a very large body); trigger: a 413 or proxy timeout on a feed POST | sprint-5/14 | Low | Open |
| BL-SS-289 | `SorentoSink.fetch_contract_detail` parses the version as a float, so a future "2.10" reads below "2.7" and would shut every 2.x gate; compare (major, minor) integers | sprint-5/14 | Medium | Open |
| BL-SS-290 | Retention for `ac_doc_feed_run` (about 50 rows a day per company) and cleared issue history; extends BL-SS-267 | sprint-5/14 | Low | Open |
| BL-SS-291 | Branch deletions: no CRM door yet; trigger: a branch deleted in AutoCount that must disappear from the CRM (cross-repo) | sprint-5/14 | Low | Open |
| BL-SS-292 | A second book (db2 / Mocha) on the DO / GRN feed: works by configuration, but the CRM security review (their Q11) requires `FromDocNo` or a book-to-database map before a second book links lines; revisit with the vendor answer on `FromDoc*` | sprint-5/14 | Low | Open |
| BL-SS-293 | Retry-store ceiling: a `retryable` document whose product never arrives is re-sent every hour forever; add an attempts or age cut-off once one is observed | sprint-5/14 | Low | Open |

## 9. Owner hand test (CRM copy on :8107, never prod)

Pre-flight (owner):

1. The CRM copy on `http://localhost:8107` runs the #1356 build: `curl -s -H "X-API-Key: <key>"
   http://localhost:8107/api/v1/external/contract` shows `"version": "2.7"` and `delivery_orders`,
   `goods_receive_notes`, `branches` in `entities`.
2. The key's integration role holds `order_management.orders.{view,edit,delete}`,
   `procurement.grn.{view,edit,delete}`, `order_management.branches.edit` (CRM plan Q5: granted
   by hand), and the CRM copy has company `SRT`.
3. Lane stack: backend `:8014` from `.claude/worktrees/s60/service_backend` with
   `ENVIRONMENT=development`, `CELERY_TASK_ALWAYS_EAGER=true`, `FERNET_KEY` set,
   `DATABASE_URL=.../foundryx_service_s60`, after `python -m scripts.bootstrap_db` (module head
   `0023_autocount_doc_feed`); frontend `:3014` prod build (`npx next start -p 3014`). Eager means
   no hourly beat: every run below is a button.

Steps (log in as the tenant Admin on `localhost:3014`):

1. Settings > Integrations > the Sorento connection (or add one): Base URL
   `http://localhost:8107`, API key = the supplied key, Save, Test = passes.
2. Settings > Integrations: an AutoCount connection with Auth = No auth and Base URL
   `https://hapi.sorento.cc.cd/api/db1` exists (add it if not).
3. AutoCount > Companies > the Sorento company > Overview > Edit: push target = the :8107
   connection, company code `SRT`, Save.
4. Document feeds tab > Branches > Configure: that AutoCount connection (book `db1`), Mode Dry run,
   Save. Run now. Expect one Branch run row, Dry run, Success, counters. Then Configure > Push,
   Run now; the CRM copy's branch table has the rows (`created`), a second Run now answers
   `unchanged`.
5. Delivery orders > Configure: same connection, Dry run, Save. Run now. Expect one Poll run row
   (yesterday and today), Dry run, fetched and counters; the CRM copy is unchanged; Covered through
   stays empty.
6. One-day live push: Configure > Push, Save, Run now. Expect `created` counts, Covered through =
   today, the CRM copy's `orders` rows with `source_book = 'db1'`; any `retryable` (product or
   warehouse not in the copy) or `failed` shows under the issues list with the CRM errors. Run now
   again: all `unchanged`, Waiting items re-sent.
7. 3-day backfill: Backfill > Dry run on, range today-10 .. today-8, Start: progress to Done, a
   Backfill run row. Then Backfill > Dry run off, same range, Start: Done; the CRM copy holds those
   DocDates. Repeat 5-7 for Goods receive notes if wanted.
8. Sweep (lane DB only, never prod): insert a ledger row the vendor does not know -
   `INSERT INTO app_autocount.ac_doc_feed_ledger (tenant_id, company_id, feed, book, doc_key,
   doc_no, doc_date, last_outcome, pushed_at) SELECT tenant_id, company_id, feed, book,
   999999999, 'HANDTEST-SWEEP', (now() AT TIME ZONE 'Asia/Kuala_Lumpur')::date - 3, 'created',
   now() FROM app_autocount.ac_doc_feed WHERE feed = 'delivery_orders' LIMIT 1;` - then Delivery
   orders > Run sweep now. Expect a Sweep run row with 45 days read, candidates 1, `notFound 1`,
   and the ledger row's `vanished_at` set; a second Run sweep now has candidates 0.
9. Rollback: Configure > Off on each feed. Nothing else changes.

Report per step: run row counters, the CRM copy row counts, and any issue rows.

## 10. Questions

Owner, decided by default (the owner may overrule on the PR):

- **Q1 - Verification before the push goes live. DECIDED BY DEFAULT: the per-feed Dry run mode is
  the verification step.** The original ask had a CRM "pull from AutoCount for verification"
  before the automated push; contract 13.8 says the CRM's S3 screen reads the dry-run counters.
  Each feed has a Dry run mode (hourly, same reads, the CRM answers `?dry_run=true`, nothing
  written) plus run counters and the issue list on our side. No products-style pull gateway is
  built; if CRM S3 wants a day-by-day snapshot it can open itself, that is BL-SS-286.

Cross-repo facts, answered from the CRM code (`autocount_doc_ingest_service.py`, branch
`claude/autocount-grn-do-ingest-yi1w42`); the sink is built to these, pinned by fixtures:

- **C1 (answered)** A `/deletions` verdict echoes ONLY `source_ref` = `{book}:DO:{DocKey}` or
  `{book}:GRN:{DocKey}`; there is no `doc_key` field. A non-integer key answers `failed` with
  `errors.doc_key` and `source_ref` = the raw value. Outcomes: `not_found`; `failed` with
  `errors.doc_date` and `entity_id`; `deactivated` with `entity_id`. A dry run rolls back.
- **C2 (answered)** A branch `source_ref` is `{book}:BR:{AccNo or ''}:{BranchCode}`, so
  `db1:BR::HQ` when there is no `AccNo`; a record with no `BranchCode` answers `failed` with
  `source_ref: null`.
