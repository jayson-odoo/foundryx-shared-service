# 72 AutoCount project registrations feed (lane AUTOCOUNT-PROJECT-SYNC-SS, S0)

Status: built, checked against contract 2.15 and UAC S0-1..S0-14 (texts in Appendix A
and B, copied from sorento-crm@bb96fbfd). Branch `claude/autocount-project-sync-ss-6u77mu`
(carries every commit of the earlier session's `claude/autocount-project-sync-s0-qwcoic`),
draft PR #336. Pushes start only once the CRM reports 2.15 (S1, after #2648 merges); until
then every test runs against a fake CRM. AutoCount reads: db3 only.

S0 of the CRM plan AUTOCOUNT-PROJECT-SYNC (sorento-crm PR #2676). Write-side sibling: plan 71
(`project-registrations` gateway, branch `claude/autocount-projreg-routes-ho124v`, CRM #2648),
which confirmed the AutoCount field names.

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

Records go out with every value as AutoCount returned it (no trim, no case change), plus
`source_ref`, with `Date` as `yyyy-mm-dd` (contract section 3; an unparseable `Date` is
sent as read and the CRM refuses that record). The envelope carries the company code and
`book`; a backfill push carries `backfill: true`, a poll push never does. At most 1,000
records a push (the CRM's MAX_BATCH; DO / GRN keep `autocount_sink_batch_size`).

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

## Settled against the contract

1. `source_ref` = `{book}:PROJREG:{ProjNo}`, sent ON each record (contract section 3).
2. Contract 2.15 takes `backfill: true` on this door (section 3).
3. Edits to old registrations: the poll reads the feed's recent-day window, the re-check
   `recheckDays`; older edits arrive on a re-run backfill (AutoCount has no LastModified
   door). Not asked for in the contract; left as is.
4. No deletions door (section 3: a vanished number is not a deletion).
5. Logged reader: every registration read writes one `ac_api_call_log` row
   (`DocFeedVendor.attach_call_log` -> `write_back.call_log.CallLog`), one row per HTTP
   attempt: path + query as sent, status, capped body, never the host or a header. Only
   this feed writes those rows; DO / GRN reads are unchanged.
6. CRM answers (section 4): `created` / `updated` / `unchanged` = delivered (ledger row);
   `failed` (incl. `needs_review`) = a failed issue row, never retried; `skipped` = final,
   nothing stored; `skipped` with code `switched_off` = the run stops with
   `CRM_SWITCHED_OFF` "CRM project sync is switched off", the poll cursor / backfill cursor
   stay where they were; `retryable` = re-sent from the issue row, as every feed. A 4xx /
   5xx / time-out stops the day: the cursor stays and the next run re-sends it.
7. Pause between backfill days: `AUTOCOUNT_PROJECT_REGISTRATIONS_DAY_PAUSE_SECONDS`
   (default 1.0 s; about 2 hours over 20 years of days).
8. A book without a feed row (S0-13): for each tenant running this feed, an allowed book
   (`AUTOCOUNT_PROJECT_REGISTRATIONS_FEED_BOOKS`) with an open AutoCount connection but no
   feed row logs an error every beat tick (`sweep_doc_feeds` -> `missingFeedBooks`); the
   configured books keep running.
9. Kept beyond the UAC (lane brief / contract section 2 "a first pass with dry run, then
   the real pass"): a live registrations backfill needs a finished dry run over the same
   days (`409 DRY_RUN_FIRST`), and one backfill per book is open at a time (`409 BOOK_BUSY`).
10. Real passes on db1 / db2 need crew + owner go; the floor 2006-01-01 is one constant
    (`constants.BACKFILL_FLOOR_BY_FEED`), to be confirmed by crew before the real pass.

## UAC report (S0-1..S0-14)

| UAC | Result | Evidence (`service_backend/tests/`) |
|---|---|---|
| S0-1 | PASS | `..._feed_uac.py::test_s0_1_each_day_read_is_one_api_call_log_row`, `test_s0_1_a_failed_day_read_is_logged_too`, `test_s0_1_delivery_order_feed_reads_are_not_moved_onto_the_call_log` |
| S0-2 | PASS | `test_s0_2_an_empty_day_pushes_nothing_and_advances_the_cursor` |
| S0-3 | PASS | `test_s0_3_records_pass_through_with_source_ref_and_a_day_date`, `test_s0_3_an_unparseable_date_is_sent_as_read`, `..._feed.py::test_poll_reads_by_date_and_pushes_verbatim` |
| S0-4 | PASS | `test_s0_4_a_day_of_1001_records_goes_out_as_two_pushes` |
| S0-5 | PASS | `..._feed.py::test_dry_run_backfill_counts_by_month_and_writes_nothing` (oldest first, one day a call), `test_backfill_start_floor_is_2006`, `test_one_backfill_per_book_at_a_time`, `test_scheduler_leaves_a_feed_alone_while_its_backfill_runs`, `test_s0_5_backfill_pauses_between_days` |
| S0-6 | PASS | `..._feed.py::test_backfill_resumes_from_its_own_cursor` (cursor committed per finished day) |
| S0-7 | PASS | `test_s0_7_a_vendor_timeout_on_day_n_keeps_the_cursor_on_n`, `..._feed.py::test_backfill_resumes_from_its_own_cursor` (HTTP error) |
| S0-8 | PASS | `test_s0_8_a_crm_error_keeps_the_cursor_and_resends_the_same_batch[400,422,500]`, `test_s0_8_a_crm_timeout_keeps_the_cursor` |
| S0-9 | PASS | `test_s0_9_switched_off_keeps_the_backfill_cursor`, `test_s0_9_switched_off_is_the_polls_last_error`, `test_s0_9_other_skips_and_needs_review_are_final_not_retried` |
| S0-10 | PASS | `test_s0_10_dry_run_marks_every_push_and_the_real_pass_starts_at_the_floor`, `test_s0_9_other_skips_...` (month counts) |
| S0-11 | PASS | `test_s0_4_...` (backfill), `test_s0_11_poll_pushes_never_carry_backfill` |
| S0-12 | PASS | `test_s0_12_the_scheduled_poll_fires_the_feed`; the feed is on the Doc Feeds tab with last run, last error and Run now like DO / GRN |
| S0-13 | PASS | `test_s0_13_an_allowed_book_without_a_feed_row_fails_loudly_and_others_run` |
| S0-14 | PASS | `..._feed.py::test_poll_refused_when_crm_contract_is_below_2_15`, `test_poll_refused_when_crm_does_not_advertise_the_feed` |

## Tests

`service_backend/tests/test_autocount_project_registrations_feed.py` (19): door / floor
constants, ProjNo identity, DO identity untouched, poll read-and-push verbatim, contract
gate below 2.15 and not advertised, book allowlist (run and configure), forced date basis,
re-check with no deletion step, dry-run month counts with no writes, resume from cursor,
floor, dry-run-first, one backfill per book, scheduler wait, view.

`service_backend/tests/test_autocount_project_registrations_feed_uac.py` (21): one test (or
more) per UAC id, named `test_s0_<n>_...`, AutoCount and the CRM faked.

## Appendix A - CRM contract 2.15 (verbatim, sorento-crm@bb96fbfd)

Source: `documentation/plans/autocount/CONTRACT-autocount-project-sync-ss-22nov.md`
(apostrophes shown as ’). The SS paths in it are crew's read of SS main 812dac2b; the
current paths are the ones in this plan.

> # CONTRACT: AutoCount project registrations feed, Shared Service -> CRM (contract 2.15)
> SS paths are crew’s read of SS main 812dac2b (PLAN-do-history-backfill-13oct.md:169-197); re-read current SS main and correct any path before coding.
>
> ## 1. What the SS reads from AutoCount
> - GET /api/<book>/ProjectRegbyDate?Date=yyyymmdd : the only enumerating door; one call per day; a JSON list (empty list = nothing that day)
> - GET /api/<book>/ProjectRegbyProjNo?ProjNo=<no> : not used by the feed (#2648 lookup uses it)
> Record fields as AutoCount answers (db3 probe run 2, PR #2648 evidence README): ProjNo, ProjectTitle, DistributorName, SalesAgent, CustomerName, Date, TypeofBuilding, State, Mukim, Developer, Architect, MainContractor, Status. No key field; ProjNo is the key. Titles may hold \r\n. The SS passes every value through as read: no trimming, no case change, no merging.
> Every read goes through the SS reader that writes ac_api_call_log (as #2648 contract requires), with the SS pinned agent (plain Python agents get Cloudflare 403, #2648 probe run 1).
>
> ## 2. The feed
> - New doc-feed kind project_registrations, read by Date, on the existing doc-feed machinery (doc_feed/snapshot.py:143-165, vendor.py:58-60 pattern: one vendor function day_by_date).
> - One feed config row per book (pull_gateway_service.py:65-68); a book without one fails loudly.
> - Start floor (doc_feed/constants.py:48 pattern): 2006-01-01 (owner: about 20 years back), one constant, confirmed by crew before the real pass.
> - Scheduled poll: the feed’s own schedule and recent-day window, exactly as the DO / GRN feeds; listed with the SS’s other scheduled jobs (last run, last error, run now).
> - Backfill: DO-HISTORY S3 run rules (PLAN-do-history-backfill-13oct.md:190-196): one day per call, oldest first, at most 1,000 records per push, the SS’s own cursor (resumes from the last finished day), one call in flight per book with a pause between days, a first pass with ?dry_run=true with counts aggregated by month, then the real pass. Sorento (db1) first, then Mocha (db2). (Build + test against db3 only; db1/db2 real passes need crew + owner go.)
>
> ## 3. The push
> POST /api/v1/external/ingest/project_registrations[?dry_run=true], X-API-Key (the SS integration key), the 2.7 vendor-shape envelope:
> {"company_code": "<as every other SS push>", "book": "db1", "backfill": true, "records": [{"source_ref": "db1:PROJREG:PPF06030001", "ProjNo": "PPF06030001", "ProjectTitle": "PROJECT 001 ...\r\nUNTUK TETUAN COMPANY 001 SDN. BHD.", "DistributorName": "COMPANY 001 SDN. BHD.", "SalesAgent": "AGENT01", "CustomerName": "CUSTOMER 001", "Date": "2006-03-14", "TypeofBuilding": "RESIDENTIAL", "State": "SELANGOR", "Mukim": "MUKIM 001", "Developer": "", "Architect": "", "MainContractor": "", "Status": "Pending"}]}
> - source_ref = {book}:PROJREG:{ProjNo}; Date = yyyy-mm-dd (the SS normalises AutoCount’s date value to a day; nothing else is normalised).
> - backfill: true only on backfill pushes, never on the poll (the DO rule, CRM ingest.py:889-893).
> - At most 1,000 records per push (CRM ingest.py:228 MAX_BATCH; 413 above it).
> - No /deletions door for this entity (AutoCount has no delete; a vanished number is not a deletion).
>
> ## 4. The CRM answer (built in S1)
> The usual ingest result (master_ingest_service.py IngestResult.as_dict): summary counts and one entry per record with source_ref, outcome and warnings. Outcomes:
> - created: a new CRM project, linked -> SS: none
> - updated: AutoCount values written onto the linked CRM project -> none
> - unchanged: nothing to write -> none
> - failed with code needs_review / skipped: listed for a person in the CRM (Import jobs run) -> none; NOT retried
> - retryable: a transient CRM-side condition -> re-drain, as every entity
> - skipped with switched_off: the CRM switch "AutoCount project sync" is OFF -> the SS does NOT advance the backfill cursor past this batch (UAC S0-9)
> A 200 means the batch was processed (per-record outcomes inside). A 4xx / 5xx / time-out means nothing was applied: the cursor stays and the batch is re-sent; the CRM per-(company, ProjNo) upsert makes a re-send harmless.
> GET /external/contract reports 2.15 with project_registrations in entities once S1 is deployed; the SS gates its pushes on it, as for every additive entity.

## Appendix B - UAC S0-1..S0-14 (verbatim, sorento-crm@bb96fbfd)

Source: `documentation/plans/autocount/autocount-project-sync-22nov-acceptance-criteria.md`.
Tests in the SS repo, AutoCount and the CRM faked, all data fake.

> - S0-1 A day read calls ProjectRegbyDate?Date=yyyymmdd for that day and book only, through the logged reader; one ac_api_call_log row per call.
> - S0-2 An empty list for a day pushes nothing and still advances the cursor past that day.
> - S0-3 Records are passed through as read (title \r\n kept, case kept, 14-char ProjNo kept); Date is sent as yyyy-mm-dd; source_ref = {book}:PROJREG:{ProjNo}.
> - S0-4 A push never holds more than 1,000 records; a day with 1,001 records goes out as two pushes.
> - S0-5 Backfill walks oldest first from the floor (2006-01-01) to today, one call in flight per book.
> - S0-6 Stopped after day N (process killed), a restart begins at day N+1; no day is read twice and none is skipped.
> - S0-7 An AutoCount error or time-out on day N stops the run at N; the cursor stays on N; the next run retries N.
> - S0-8 A CRM 4xx / 5xx / time-out on a push keeps the cursor on that batch’s first day; the batch is re-sent unchanged on the next run.
> - S0-9 A CRM answer of skipped: switched_off keeps the backfill cursor where it was (the history is not "done" while the CRM ignored it); the poll logs it as its last error "CRM project sync is switched off".
> - S0-10 A first pass with dry run sends ?dry_run=true on every push and writes no cursor that a real pass reads (the real pass starts from the floor); its summary is counts by month (created, updated, unchanged, needs review, skipped).
> - S0-11 Backfill pushes carry "backfill": true; poll pushes never do.
> - S0-12 The scheduled poll reads the feed’s recent-day window and pushes; it is listed with the SS’s other jobs with last run, last error and run now.
> - S0-13 A book without a feed config row fails loudly for that book, and the other book still runs.
> - S0-14 Before the CRM reports contract 2.15 with project_registrations, the SS pushes nothing for this feed (gated as every additive entity).
>
> Context only (CRM S1, not the SS): CRM creates/updates projects per ProjNo, needs_review on clashes, switch "AutoCount project sync" OFF by default answers skipped: switched_off, dry_run leaves DB as was, /external/contract reports 2.15 after S1 deploys.
