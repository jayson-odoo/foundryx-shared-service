# UAC: Find an AutoCount document by number (sprint-5/17, AC-DOC-FINDER)

Plan: `17-autocount-doc-finder.md`. Mockup: `documentation/mockups/ac-doc-finder/index.html`.
Tags: [BE] backend, [FE] frontend, [E2E] Playwright real clicks, [T] test-only guard.
Reference case used throughout: `PS202610-0004`, re-dated by AIN from 01/10/2026 to
05/10/2026, `LastModified 2026-10-01T07:39:22`.

## Registry (generic doc types)

- AC-17-01 [BE] `GET /autocount/doc-lookup/types` lists every registered doc type (`key, label,
  prefixes, hasLastModified, hasByDocNo`); v1 has `delivery_order` and `goods_receive_note`.
- AC-17-02 [T] Genericity proof: a test registers a fake `invoice` entry (its own paths, DocNo
  field and prefixes) and finds an invoice end to end with no change to the search code.
- AC-17-03 [T] Drift guard: every entry's `feed`, `snapshot_entity_type` and `ledger_feed`
  exists in the module's own feed and entity lists; a duplicate key fails loudly at boot.
- AC-17-04 [BE] With no type given, the type is detected by number prefix (`PS...` /
  `DO...` -> delivery_order); an unknown prefix falls back to delivery_order.
- AC-17-05 [BE] The existing DO/GRN feed query strings are unchanged (the pinned
  `test_s14_doc_feed_clock_records.py` stays green).

## Stored search (instant, zero vendor calls)

- AC-17-06 [BE] `GET /stored` finds the number (trim + case-insensitive) in ready snapshot rows
  of the same tenant and company, and returns each sighting with snapshot id, built-at, scope
  and the DocDate / LastModified / Cancelled it had then.
- AC-17-07 [BE] `GET /stored` also returns the doc feed ledger row (doc_date, modified,
  last_outcome, pushed_at, vanished_at) when the feed pushed it.
- AC-17-08 [BE] Another tenant's or another company's snapshot or ledger rows are never
  returned (tests seed both).
- AC-17-09 [T] `GET /stored` makes zero vendor calls (the transport mock records none).

## Live search (background job)

- AC-17-10 [BE] `POST /autocount/doc-lookup` answers 202 `{jobId}`, and the job's step plan is
  in this order: by-DocNo door (only if enabled for the type) -> hint days -> by-LastModified
  today back N days -> by-DocDate today forward M days, with no step repeated.
- AC-17-11 [BE] Re-date case: by-DocDate 01/10 is empty, by-LastModified 01/10 returns the doc
  with DocDate 05/10 -> `found:true`, `foundBy {door:by_last_modified, day:2026-10-01}`,
  `current.docDate 2026-10-05`, `lastModifiedBy AIN`, `redated {from:2026-10-01,
  to:2026-10-05}` (from the stored sighting).
- AC-17-12 [BE] A forward-dated doc that nobody touched in N days is found by by-DocDate on
  day today+k (k <= M).
- AC-17-13 [BE] The search stops at the first hit: no GET after the hit step (call count
  asserted).
- AC-17-14 [BE] A hit saves a location hint. The next lookup of the same number reads the hinted
  DocDate first and finds it in exactly 1 vendor GET, still returning the fresh live record.
- AC-17-15 [BE] A stale hint (the doc was re-dated again) misses, the scan continues, finds the
  doc and replaces the hint.
- AC-17-16 [BE] Not found -> `found:false`, every step listed `miss`, plus the searched windows.
  No hint is written for a miss.
- AC-17-17 [BE] A vendor error on one day marks that step `error` and the scan goes on. The job
  fails only when every step failed or the company has no connection (409 `NO_CONNECTION` at
  POST).
- AC-17-18 [BE] Re-attach: the same (company, type, number) while a job runs returns the same
  jobId. A second running lookup for the same company is 409 `LOOKUP_IN_FLIGHT`.
- AC-17-19 [BE] Stop: `POST /{jobId}/stop` ends the scan at the next step boundary with status
  stopped (cooperative abort, re-read from the DB).
- AC-17-20 [BE] The result returns the full header verbatim (lines field removed) plus `lines[]`
  verbatim. No field is renamed or retyped.
- AC-17-21 [BE] Windows N/M default to 7/14, can be set per company (`PUT /settings`,
  `autocount.companies.manage`), and are capped at 31 (422 above). `aroundDay` adds day +/-3 as
  hint steps.
- AC-17-22 [BE] Every vendor GET is written to the activity log (developer logs) with the
  company's external ref.

## Read-only and security

- AC-17-23 [T] Kill test: the transport mock fails the test on any non-GET vendor request (a POST
  is allowed only when it exactly matches an enabled `by_doc_no` door). Snapshot, ledger, feed,
  cursor and issue tables are unchanged after a lookup (row counts + `updated_at`).
- AC-17-24 [BE] Every route needs `autocount.pull.read` (403 otherwise). The routes answer 403
  "Module not installed" when autocount is inactive for the tenant.
- AC-17-25 [BE] Input: `docNo` is trimmed, 1..64 chars, with no control characters (422 naming
  the field, never echoing the value). An unknown `docType` is 422.
- AC-17-26 [BE] A job lookup by id is tenant-scoped: another tenant's jobId is 404.

## UI (`/autocount/find`)

- AC-17-27 [FE] "Find document" appears in the AutoCount menu (sidebar + both mega menus), gated
  `autocount.pull.read` + module.
- AC-17-28 [FE] The search shows stored sightings immediately, then live progress ("Checked 4
  of 23 days") with a Stop button.
- AC-17-29 [FE] A found doc shows a header card (DocNo, type, current DocDate, LastModified, by
  whom, Cancelled badge, found-by), the curated fields, a collapsible "All fields" table and a
  lines table.
- AC-17-30 [FE] Re-dated: a warning banner names the old and new DocDate, who changed it and
  when, and says a pull for the old date will not return it. Each history row shows the DocDate
  it had then and whether today's DocDate is inside that snapshot's range.
- AC-17-31 [FE] Not found: a plain message with the windows searched and an "Around date" field
  for searching a remembered date. No hint copy beyond that.
- AC-17-32 [FE] All timestamps go through `useDatetime`. Dropdowns are `SearchSelect`.
- AC-17-33 [E2E] Real clicks: menu -> Find document -> pick company -> type PS202610-0004 ->
  Find -> re-date banner + current DocDate 05/10/2026, at 1280 and 375 with no horizontal
  scroll.
