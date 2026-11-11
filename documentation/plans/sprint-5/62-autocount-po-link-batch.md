# Plan 62: AutoCount PO link batch (one PO row -> many SO rows in one edit), retryable writes

Lane PO-LINK-BATCH (crew), branch `crew/po-link-batch`. Backend only; no screen. UAC: `62-autocount-po-link-batch-acceptance-criteria.md`.
Book: db3 (test book) ONLY for every vendor call; never db1/db2. Every AutoCount call is logged (`ac_api_call_log`, plan 61 R3).

## 1. Why (owner 11 Nov ~22:55)
"I think we should do that also to speed up the processing time, otherwise it is heavy for AutoCount."

Today (crew-verified, cited in the brief): the CRM link (sorento PR #2332, `stock_debt_po_link_service.py:517-585`) calls
SS once PER SO line. Each SS call = a split (PUT 1 cut + linked row, PUT 2 restore Location/UnitPrice/DeliveryDate;
`write_back/payloads.py:197-246` `build_link`, `write_back/operations.py:604-632` `_steps_run`) or a whole-row replace
(`operations.py:634-654` `_replace_run`). 3 SO lines = 3 calls / 6 PUTs / ~7-17 s, and a partial success is possible.

## 2. Facts this plan rests on
- F-A One AutoCount PO row links ONE SO row (`FromSODtlKey`); N SO lines => N linked rows + at most 1 free row (keep).
- F-B A PUT is all or nothing (plan 61 F8): a bad new row = 500 and nothing lands.
- F-C A NEW SO-linked PO row is forced to HQ / UnitPrice 0 / DeliveryDate 0001-01-01; a 2nd PUT restores all three and
  keeps the link (plan 61 F5).
- F-D A refused operation is stored under its key and replayed forever: `OperationService.run` -> `_replay`
  (`operations.py:252-253, 346-351`); `_replace_run` stores `VENDOR_ERROR` only for `VENDOR_REFUSED` = nothing landed
  (`operations.py:641-645`). So a retry after fixing the cause replays the old refusal (breaks the owner rule).
- F-E Unlink = one PUT [linked row "D", new free row] (`operations.py:634-654`); it never merges back, so free rows pile
  up (FXT-HT-PO-B rows 12320/12332/12370).
- F-F The over-link check `_so_linked_qty` (`service.py:635-650`, and the operation path `primitives.py:539` called from
  `operations.py:522`) walks every staged PO of the company per link, and `StagedRepository.for_entity`
  (`repository.py:220-233`) returns ALL staged copies (sync keeps history, `sync.py:1406`), so an older copy of the
  same PO is counted again (over-count = a false `QTY_ABOVE_OUTSTANDING`).
- F-I AutoCount does NOT refuse an over-link: db3 run 1111B linked 8 against an SO row of 5 (S5). The over-link guard
  is SS-only (`_so_linked_qty` + `ac_po_so_link`), so it must stay on every link path.
- F-H `run_primitive` replays a stored refused / vendor_error answer as is (`operations.py:911-917`); only refused
  `DOC_BUSY` is not stored (`operations.py:948-949`).
- F-G PROVEN on db3 11 Nov (S0, PR #232 crew-note; evidence `crew/state/files/autocount-api/db3-requests-11nov-po-link-batch.json`):
  one PUT cuts row X + adds 2 rows linked to 2 rows of one SO (200); one PUT "D"s row Y + adds 3 rows linked across 2 SOs
  (200); one PUT "D"s a linked row + raises a free row's Qty (200, SO linked qty freed); a bad new row = 500 and the
  whole PO is unchanged. F-C holds for every new linked row; one restore PUT on all of them keeps the links. PUT 0.5-1.0 s.

## 3. Decisions
- D1 New route `POST /po-links/batch` beside `/po-links` (same auth, scope `write_back`, `companyCode`, gateway frame
  `pull_v1.py:_write_route`). `Idempotency-Key` header REQUIRED (one key for the whole batch). Body:
  `{companyCode, poDocKey, poDtlKey, docDate?, expectedLastModified?, links: [{soDocKey, soDtlKey, qty, soDocDate?}, ...]}`.
  1 <= len(links) <= 20; no duplicate `soDtlKey`; every qty > 0 (same `validate_qty`).
- D2 New operation `link_batch` in `OperationService` (row in `ac_write_operation`, one key). Pre-checks before any write
  (all or nothing): PO not cancelled, row exists, row not linked / not transferred onward / not partly received (same
  refusals as `build_link`), every SO row exists, same ItemCode + UOM as the PO row, SO not cancelled, sum(qty) <= row
  Qty (`QTY_ABOVE_FREE`), each qty <= that SO row's outstanding minus its already-linked qty (`QTY_ABOVE_OUTSTANDING`,
  answer names the `soDtlKey`). Any refusal = nothing sent.
- D3 PUT 1 (edit door, one PUT): sum == row Qty -> [row X "D", N new linked rows]; sum < row Qty -> [row X with
  Qty = rest (stays the free row), N new linked rows]. Each new row = the row's full vendor shape, `DtlKey 0`,
  `FromDocType SO`, `FromDocNo` = its own SO DocNo, `FromDocDtlKey` = its SO row, Qty, Location = that SO row's.
  New DtlKeys = keys present after and absent before, matched to links by `FromSODtlKey` (AC-61-04 rule).
- D4 PUT 2 (one PUT, only when a read-back drifts): restore each new row's Location (its SO row's / the old row's per
  `_move` rule), UnitPrice and DeliveryDate = the old row's (`payloads.transfer_restore`). A failed PUT 2 = warning
  `LOCATION_NOT_MOVED` (+ `ROW_VALUES_NOT_KEPT`), links stay (plan 61 rule). PUT 2 is skipped past the deadline.
- D5 Answer = operation shape (`operationId`, `outcome`, `errorCode`, `message`, `warnings`, `docKey`, `docNo`,
  `document`) plus `links: [{soDocKey, soDtlKey, qty, poDtlKey}]` (new PO DtlKey per SO row) and
  `freeLine: {poDtlKey, qty} | null`.
- D6 Retry rule (owner 11 Nov, every operation AND `run_primitive`, not only the batch): a stored operation whose outcome is a confirmed
  "nothing landed" (`refused`, `vendor_error`) RELEASES its key: a resend with the same key runs fresh (any body; the
  old row is kept for history, re-keyed so the unique key frees). `pending_verification` (unknown outcome) on resend
  with the same body = reconcile first (read the PO back, today's `resume` path): landed -> finish as `done`
  (+ PUT 2), not landed -> run fresh. `done` / `recovered` / `needs_attention` keep replaying (only a confirmed success
  locks; needs_attention stays for a person). `IDEMPOTENCY_CONFLICT` stays for a changed body on a `done` key.
- D7 Unlink merge: unlink of a linked row looks for a FREE row on the same PO with the same ItemCode, UOM, Location,
  UnitPrice and DeliveryDate (not linked, not transferred onward, no receipt). Found -> ONE PUT [linked row "D", free row
  Qty += freed qty]; answer carries the free row's DtlKey. None -> today's PUT (new free row). Applies to the
  `/po-links/unlink` route and the `unlink_row` operation. Relink is unchanged (its freed qty moves to the new SO row).
  Receipt: a free row with a KNOWN receipt > 0 is skipped; an UNKNOWN receipt (db3 never exposes `TransferedQty`) allows
  the merge, the same rule the unlink applies to the linked row itself (S5 finding, commit 8ed77585). Raising a free
  row's Qty leaves the PO's outstanding qty identical to adding a new free row, so the merge cannot over-open a PO.
- D8 Over-link index: new table `app_autocount.ac_po_so_link` (tenant_id, company_id, po_source_ref, po_dtl_key,
  so_dtl_key, qty) with index (tenant_id, company_id, so_dtl_key); rewritten for a PO whenever a PO staged record is
  written (sync `sync.py:1223 _stage_documents` + deletes `:2549`, write-back `staging.py:83 _stage_raw`), from that
  PO's NEWEST copy only; cancelled or deleted PO = no rows. Both `_so_linked_qty` (service + primitives) = fresh PO
  rows + indexed sum over OTHER POs (fixes the history double count, F-F). Migration 0045 + backfill from the newest staged copy of every PO. Plan-12 guard
  `test_s12_mapping_reset_route.py::test_ac_12_32` bumped.
- D9 Capability: the batch rides the existing `link_existing_row` flag + `delete_line/add_line/edit_doc` primitives
  (`_OP_FLAGS`), no new switch (owner rule: ERP writes behind an admin switch OFF by default = already true).
- D10 Contract: `55-autocount-write-link-contract.md` gains the batch section + the retry rule + the unlink merge in the
  same diff (contracts are part of the diff).

## 4. Slices
- S0 db3 proof (no SS code): scratch script through the SS AutoCount client (call-logged) on db3 only:
  (a) cut row X + 2 new rows linked to 2 rows of ONE SO; (b) "D" row X + 3 new rows linked across 2 SOs;
  (c) "D" a linked row + raise a free row's Qty in one PUT. Record request/response, post `crew-note`.
- S1 retry rule (D6), red tests first.
- S2 batch op + route + gateway answer (D1-D5), red tests first; fake vendor taught multi-row add.
- S3 unlink merge (D7), red tests first.
- S4 over-link index + migration + backfill (D8), red tests first.
- S5 db3 runner suite `--suite batch`: batches of 1/3/5 SO lines, timings, test report under
  `documentation/integrations/autocount/`.
- S6 contract doc (D10), reviewer + security-reviewer in parallel, PR.

## 5. Out of scope
CRM grouping per PO line (lane OI-PO-LINK, sorento PR #2350). Any screen. SPO batch.
