# UAC: AutoCount pull gateway `delivery_orders` snapshot (sprint-5/16, BL-SS-286)

Contract of record: `16-autocount-do-pull-snapshot-contract.md`. Products / stock behaviour
(plan 10 Appendix A) is byte-identical unless an AC below says otherwise.

## Build route (`POST /api/v1/autocount/snapshots`)

- AC-16-01 `entity: "delivery_orders"` with `fromDay`+`toDay` on a company whose `delivery_orders`
  feed row has an AutoCount connection answers 202 `{snapshotId, status, entity, companyCode,
  fromDay, toDay, docNo: null}`; a snapshot row exists with `entity_type = delivery_orders`,
  `requested_via = gateway`, `company_code` copied from the company.
- AC-16-02 `fromDay` alone -> `toDay` defaults to `fromDay` (echoed on the 202 and header).
- AC-16-03 `docNo` alone -> range defaults to the 31 MYT days ending today (`toDay` = MYT today,
  `fromDay` = today minus 30 days), echoed on the 202.
- AC-16-04 422 `INVALID_REQUEST` (flat envelope, `message` names the field) for each of: neither
  `fromDay` nor `docNo`; `toDay` without `fromDay`; a non-`YYYY-MM-DD` day; `fromDay > toDay`;
  a range over 31 days; `toDay` after MYT today; `fromDay` before 2023-01-01; `docNo` not a
  string / empty after trim / over 64 chars.
- AC-16-05 A scope key (`fromDay`, `toDay` or `docNo`) on `entity: products` or `stock_balances`
  is 422 `INVALID_REQUEST`; without scope keys those entities behave exactly as before (existing
  s10 tests stay green).
- AC-16-06 `UNKNOWN_ENTITY`'s message lists `delivery_orders, products, stock_balances`.
- AC-16-07 409 `PULL_NOT_ENABLED` when the company has no `delivery_orders` feed row, or the row
  has no connection; the feed's `mode` (`off` / `dry_run` / `push`) never gates the build.
  `PUSH_ACTIVE` is never raised for `delivery_orders`.
- AC-16-08 The ac_entity_config table is not consulted for `delivery_orders` (a company with NO
  entity configs at all can still build a DO snapshot).
- AC-16-09 Re-attach: a second POST with the SAME normalised scope while a DO build is `building`
  returns the same `snapshotId`, no second job.
- AC-16-10 409 `BUILD_IN_FLIGHT` when a DO build with a DIFFERENT scope is `building` for the
  same company; the in-flight snapshot is untouched.
- AC-16-11 Cooldown: a second build with the same scope within 60 s of the previous build's end
  is 429 `TOO_MANY_BUILDS` + `Retry-After`; a different scope within 60 s is allowed (202).
- AC-16-12 Existing codes reachable as today: 401 `INVALID_API_KEY`, 403 `SERVICE_NOT_ENABLED`,
  403 `COMPANY_NOT_ALLOWED`, 404 `UNKNOWN_COMPANY`, 409 `AMBIGUOUS_COMPANY`; every error body
  echoes `entity: "delivery_orders"` and the sanitised `companyCode`.
- AC-16-13 The build audit row (`ac_pull_audit`) carries `entity_type = delivery_orders`,
  `action = build`, the key id, company id and snapshot id.

## Build job (the `autocount_pull_snapshot` handler, `delivery_orders` branch)

- AC-16-20 The build reads `/deliveryorderbydocdate?DocDate=yyyyMMdd` once per day in the range
  (inclusive), through the feed connection's base URL (`HttpApiClient` + `DocFeedVendor`), never
  `byLastModified`; no request is made to the Sorento sink, the CRM contract probe, or any
  lookup.
- AC-16-21 One row per `DocKey` (greatest `LastModified` wins across days and duplicates);
  rows ordered `DocDate` asc then `DocKey` asc; `row_index` follows that order.
- AC-16-22 `payload_json` is the raw vendor dict verbatim (every key incl. `Details`, unknown
  keys kept, no re-typing); the stored `source_ref` is `{book}:DO:{DocKey}`.
- AC-16-23 `docNo` filter: trimmed, case-insensitive match on `DocNo`; non-matching records are
  dropped silently (not excluded rows); no match -> `ready`, `recordCount 0`.
- AC-16-24 A record with no integer `DocKey` is an `excludedRows[]` entry
  `{source_ref: null, code: <DocNo or null>, reason: "missing_doc_key", message}` and counted in
  `excludedCount`; it is never stored as a row.
- AC-16-25 `metadata_json` carries `fromDay`, `toDay`, `docNo`, `book`, `daysRead`,
  `fetchedCount`, `lineCount`, `excludedRows`, `excludedCount`, `sourcePageSize: null`.
- AC-16-26 `complete` is `true` on `ready`; `contentHash` = `compute_content_hash` over the
  stored payloads in `row_index` order; `extractedAt` = build end; `expiresAt` = +24 h.
- AC-16-27 A zero-row result (empty range, or `docNo` miss) is `ready` with `recordCount 0`,
  even when a previous ready DO snapshot for the company carried rows (no `EMPTY_EXTRACT`).
- AC-16-28 Any vendor day failing (transport after the retry ladder, HTTP >= 400, not JSON, wrong
  shape, paged envelope) stamps the snapshot `failed` with `error_code SOURCE_PAGE_FAILED`,
  no rows stored, the job `failed`, and the feed row's `cursor_day` / `last_poll_*` /
  `last_error*` untouched.
- AC-16-29 Over 10,000 delivered documents -> `failed`, `ROW_LIMIT`, no rows stored.
- AC-16-30 Progress: `beat_progress` is called per day read (`stage "source"`, done = days read,
  total = days in range) and every 200 stored rows (`stage "storing"`); the `building` header
  shows `progress` once a total is known.
- AC-16-31 Abandonment: when the snapshot is no longer `building` mid-build (orphan sweep), the
  handler stops, stores no further rows, never re-stamps, and finishes the job `failed`
  (existing `_BuildAbandoned` behaviour). The orphan hook stamps `BUILD_ABANDONED` for a DO
  snapshot exactly as for products (same job type).
- AC-16-32 The build writes no `ac_doc_feed_ledger`, `ac_doc_feed_issue`, `ac_doc_feed_run`,
  `ac_staged_record`, `ac_row_hash` or watermark rows; `ac_sync_run` gets one `snapshot`-mode
  run row as today.
- AC-16-33 The vendor calls are recorded in `integration_activity` (`record_client_calls`) as for
  products; the activity carries no record bodies.

## Header and rows routes

- AC-16-40 `GET /snapshots/{id}` for a DO snapshot: `building` -> `{snapshotId, entity,
  companyCode, status, fromDay, toDay, docNo, book}` (+ optional `progress`), no counts;
  `ready` -> the section 3 shape (`sourcePageSize: null`, `daysRead`, `fetchedCount`,
  `lineCount`, `excludedCount`, `excludedRows`, `complete`, `contentHash`, `recordCount`,
  `extractedAt`, `expiresAt`); `failed` -> `error: {code, message}` with the fixed prose from
  `GATEWAY_FAILED_MESSAGES`, plus the scope keys and `book`.
- AC-16-41 Products / stock headers carry none of `fromDay`, `toDay`, `docNo`, `book`,
  `daysRead`, `fetchedCount`, `lineCount` (byte-identical to today).
- AC-16-42 `GET /snapshots/{id}/rows` pages the raw DO dicts in `row_index` order with the
  unchanged envelope; `pageSize` clamps at 1000; a page past the end is an empty `rows`.
- AC-16-43 A DO snapshot outside the key's company set or tenant is 404 `UNKNOWN_SNAPSHOT`;
  an expired one is 410 `SNAPSHOT_EXPIRED` with `entity: "delivery_orders"`.
- AC-16-44 The operator routes (`/autocount/pull/snapshots`, session auth) list and show a DO
  snapshot without error (`entityType: "delivery_orders"`, the operator header's `metadata`
  extras visible), and the operator's build route refuses `delivery_orders` with a 422
  (scope-less operator build is not offered in this slice).

## Doc feed regression

- AC-16-50 Extracting the vendor-side resolution out of `doc_feed/runner.py::_resolve` (so the
  snapshot can reuse it without the sink / contract gate) keeps every `test_s14_*` test green;
  `_resolve`'s refusal codes and order are unchanged.

## Docs

- AC-16-60 `documentation/engineering/autocount-doc-feeds.md` gains a section pointing at the
  contract; `documentation/backlogs/backlog.md` BL-SS-286 is marked Done with the plan link;
  `CLAUDE.md`'s engine index row for AutoCount doc feeds mentions the DO pull snapshot.
