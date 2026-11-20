# Plan 62 UAC: AutoCount PO link batch, retryable writes, unlink merge, over-link index

Plan: `62-autocount-po-link-batch.md`. Backend only; no screen. Every AC is a pytest against the fake vendor
(`tests/autocount_write_back_fake_vendor.py`) unless marked [db3] (runner on the db3 test book, recorded in the test
report). Every vendor call in every AC is a row in `ac_api_call_log`.

## Batch link (route `POST /po-links/batch`, operation `link_batch`)
- AC-62-01 3 links, sum < row Qty: exactly ONE edit PUT 1 = [row X with Qty = rest, 3 new rows DtlKey 0 each with
  its own `FromDocNo`/`FromDocDtlKey`, full vendor row shape, `FullTransferOption " "`]; then at most ONE PUT 2 restoring
  Location/UnitPrice/DeliveryDate on all 3 new rows. Answer `done`, `links[]` carries each SO row's new PO DtlKey,
  `freeLine` = row X with the rest.
- AC-62-02 sum == row Qty: PUT 1 = [row X "D", N new rows]; `freeLine` null.
- AC-62-03 Links across 2 different SOs in one batch work (each row its own FromDocNo).
- AC-62-04 Pre-check refusals send NO PUT: unknown SO row, item or UOM differs, SO cancelled, PO cancelled, row already
  linked / transferred onward / received, sum > row Qty (`QTY_ABOVE_FREE`), one link above its SO row outstanding
  (`QTY_ABOVE_OUTSTANDING`, message names that soDtlKey), duplicate soDtlKey, empty links, > 20 links, qty <= 0,
  missing `Idempotency-Key` (422).
- AC-62-05 Vendor refuses PUT 1 (500): answer `vendor_error` / `VENDOR_REFUSED` with the vendor text, no PUT 2, no row
  reported linked.
- AC-62-06 PUT 2 fails: answer `done` + warning `LOCATION_NOT_MOVED` (and `ROW_VALUES_NOT_KEPT`), links kept.
- AC-62-07 Same key + same body after `done` = stored answer, no vendor call. Same key + other body after `done` =
  `IDEMPOTENCY_CONFLICT`, no vendor call.
- AC-62-08 Auth/scope/tenant: no key 401, key without `write_back` 403, a company of another tenant is never resolved;
  the PO/SO keys are resolved through the caller's tenant + company only.
- AC-62-09 [db3] Batches of 1, 3 and 5 SO lines land; read-back shows N linked rows (FromSODtlKey each) + the free row;
  timings recorded per batch size next to today's per-line flow.

## Retry rule (every operation)
- AC-62-20 A stored `vendor_error` (VENDOR_REFUSED) or `refused` operation: resend with the same key runs FRESH (vendor
  called again); with a corrected body it runs the corrected body (no `IDEMPOTENCY_CONFLICT`). The old row is kept.
- AC-62-21 A stored `pending_verification` operation: resend with the same key + body reads the PO back first; landed ->
  answer `done` with the new DtlKeys and NO second PUT 1; not landed -> PUT 1 sent once.
- AC-62-22 `done` locks: resend = stored answer, no vendor call (kill test: release `done` too and a test fails).
- AC-62-23 `needs_attention` is not auto-rerun on resend (stored answer; `resume` stays the way).

## Unlink merge
- AC-62-30 PO holds a free row with the same ItemCode/UOM/Location/UnitPrice/DeliveryDate: unlink = ONE PUT [linked row
  "D", free row Qty + freed qty]; no new row; answer names the free row's DtlKey.
- AC-62-31 No matching free row (any of the five differs, or the free row is linked / received): today's one PUT
  [linked row "D", new free row].
- AC-62-32 [db3] Merge PUT proven on db3 (S0 case c) and rerun in the runner.

## Over-link index
- AC-62-40 `_so_linked_qty` reads `ac_po_so_link` (indexed by so_dtl_key) for OTHER POs, never iterates every staged PO
  (test: a spy proves no full staged-PO scan).
- AC-62-41 Staging a PO (sync pull and write-back) rewrites its rows in `ac_po_so_link`; a cancelled PO leaves none; a
  newer copy replaces the older one (no double count).
- AC-62-42 Migration 0045 creates the table + index and backfills from the newest staged copy of every PO (verified on
  live Postgres with `run_module_migrations`); `test_ac_12_32` bumped.

## Contract
- AC-62-50 `55-autocount-write-link-contract.md` documents `/po-links/batch` (request, answer, codes), the retry rule
  and the unlink merge, matching the shipped wire.
