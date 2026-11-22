# 72 AutoCount project registrations feed (lane AUTOCOUNT-PROJECT-SYNC-SS, S0)

Status: built and pushed (branch `claude/autocount-project-sync-s0-qwcoic`); waiting on
(1) a draft PR opened by crew (this session cannot create PRs on the moved repo) and
(2) the CRM contract + UAC text (the CRM repo is not readable from this session), to key
the S0-1..S0-14 report and settle the open points below.

Verification so far: 19 new backend tests green; doc-feed / sink / contract subset 930
passed; full backend suite 14642 passed (the 8 failed + 171 errors are network-socket
tests that fail identically on plain main in this sandbox); frontend AutoCount vitest
569 passed. Not yet done: agent-browser run of the Doc Feeds tab at 375px and 1280px.
S0 of the CRM plan AUTOCOUNT-PROJECT-SYNC (sorento-crm PR #2676). The contract
(`CONTRACT-autocount-project-sync-ss-22nov.md`, contract 2.15) and UAC (S0-1..S0-14)
live in the CRM repo, which this session cannot read; this plan is built from the lane
brief and the existing doc feed. Write-side sibling: plan 71 (`project-registrations`
gateway, branch `claude/autocount-projreg-routes-ho124v`, CRM #2648), which confirmed the
AutoCount field names from a db1 record.

## What it is

A third kind on the existing doc feed (`modules/autocount/doc_feed/`), beside delivery
orders and goods receive notes. AutoCount is the truth: the feed reads registrations
and the CRM mirrors them.

| | Delivery orders / GRN | Project registrations |
|---|---|---|
| Feed key / ingest path | `delivery_orders` / `goods_receive_notes` | `project_registrations` -> `POST /api/v1/external/ingest/project_registrations` |
| AutoCount door | by LastModified + by DocDate | `GET /ProjectRegbyDate?Date=yyyymmdd` only |
| Poll basis | per-feed setting | always by date (setting forced, a save of LastModified = 422) |
| Identity | `DocKey` (int) | `ProjNo` (text, trimmed, case-insensitive) |
| `source_ref` | `{book}:DO:{DocKey}` | `{book}:PROJREG:{ProjNo}` |
| Contract gate | 2.7 + feed advertised | 2.15 + `project_registrations` advertised |
| Re-check (sweep) | content re-check + deletions | content re-check only (no deletions door) |
| Backfill floor | 2019-01-01 | 2006-01-01 |
| Books | any | `AUTOCOUNT_PROJECT_REGISTRATIONS_FEED_BOOKS` (default `db3`) |

Records go out exactly as AutoCount returned them (the feed's D18 rule), with the
company code and `book` on the envelope; a backfill push carries `backfill: true`.

## Design notes

- **ProjNo as the ledger key.** The ledger and issue tables key on a BIGINT `doc_key`.
  A registration's key is the first 63 bits of sha256 over `ProjNo.strip().casefold()`
  (`records._proj_no_key`), so no migration is needed and the ledger's `doc_no` column
  holds the ProjNo. Every identity call in the runner passes the feed
  (`doc_key(record, feed)`); delivery orders keep `DocKey` even though AutoCount
  documents also carry a `ProjNo` field (pinned by a test).
- **Run rules (DO-HISTORY S3, `PLAN-do-history-backfill-13oct.md:190-196`).**
  - one day per AutoCount call, oldest first: the existing backfill day loop;
  - at most 1,000 records per push: the sink chunks at `settings.autocount_sink_batch_size`,
    clamped to `SORENTO_MAX_BATCH` (<= 1,000, pinned by a test);
  - its own cursor: `ac_doc_feed_backfill.next_day`, committed per finished day; Stop / Resume
    as today, a resumed segment never re-reads a finished day and keeps the month counts;
  - one call in flight per book: starting a registrations backfill while any backfill on
    the same book is open = `409 BOOK_BUSY`; the scheduled poll / re-check (and Run now,
    `409 BACKFILL_RUNNING`) wait while the feed's backfill reads;
  - dry run first: the dry-run backfill summary carries `byMonth: {"YYYY-MM": n}`;
    a live backfill needs a finished dry run over the same days (`409 DRY_RUN_FIRST`).
- **Gating.** Mode switch and every run check the CRM contract (2.15, feed advertised);
  until the CRM reports 2.15 (S1, after #2648 merges) the feed cannot leave Off and a run
  refuses with `CONTRACT_GATE`. Tests use a fake CRM.
- **Books.** Configure refuses a connection whose book is outside the list; a run
  refuses `BOOK_NOT_ALLOWED` before any AutoCount call. Owner rule: db3 only while the
  feed is proven, never db1 / db2.
- **Scheduled tasks.** No new job type: it rides `autocount_doc_feed_run` /
  `autocount_doc_feed_backfill`, so it shows on the doc feed's run history like the
  other feeds. The Doc Feeds view lists it with its own floor and window.

## Open points (to confirm against the contract)

1. `source_ref` shape `{book}:PROJREG:{ProjNo}` and whether the CRM derives it from the
   raw record (as for DO / GRN) or wants it on the record.
2. Whether contract 2.15 accepts `backfill: true` on this door (a strict schema would 422).
3. Edits to an old registration: the poll reads the last `pollLookbackDays` days by
   registration date and the re-check `recheckDays` (max 180); an edit to a registration
   older than that reaches the CRM only on a re-run backfill. Is a periodic full re-read
   wanted (AutoCount has no LastModified door)?
4. Deleted registrations: no deletions door, so none are sent.
5. "Logged reader": the feed's AutoCount reads are logged through the doc feed's own
   integration activity (`record_client_calls`), not `ac_api_call_log` (that log belongs
   to the write connection, plan 71).

## Tests

`service_backend/tests/test_autocount_project_registrations_feed.py` (19): door / floor
constants, ProjNo identity, DO identity untouched, poll read-and-push verbatim, contract
gate below 2.15 and not advertised, book allowlist (run and configure), forced date basis,
re-check with no deletion step, dry-run month counts with no writes, resume from cursor,
floor, dry-run-first, one backfill per book, scheduler wait, view.
