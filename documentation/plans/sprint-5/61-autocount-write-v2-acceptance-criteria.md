# Plan 61 UAC: AutoCount write API v2

Plan: `61-autocount-write-v2.md` (facts F1..F15 in section 3a). Backend only; no screen changes. Every AC is a pytest
against the fake vendor (`tests/autocount_write_back_fake_vendor.py`, taught the 10 Nov behaviour) unless marked [db3]
(runner rerun on the db3 test book, recorded in the test report).

## Client and reads
- AC-61-01 Cancel sends `DELETE /Cancel<Doc>bydocno?DocNo=<DocNo>` with NO request body, the DocNo URL-encoded
  (`/`, space, `&`, `#`, `?` cannot change the path or add a parameter). Any other caller passing `?` in a path is still
  refused `ValueError` (`client._check_path`). The allowlist guard still runs before the request.
- AC-61-02 Single-doc read = `GET /Quotationbydocno`, `/SalesOrderbydocno`, `/PurchaseOrderbydocno` `?DocNo=` (exact
  spelling; never `Quotaton`). `[]` = `DOC_NOT_FOUND`. A doc whose DocKey differs from the expected DocKey is never
  used as the read-back (`DOC_KIND_MISMATCH` or `DOC_NOT_FOUND`, never a silent pass).
- AC-61-03 Every write's before/after read uses bydocno when a DocNo is known; the by-date day-list is used only when
  the bydocno GET fails (transport error / non-2xx) or no DocNo is known. A test proves the day-list is NOT called on
  the happy path.
- AC-61-04 A new row's DtlKey after any write = the key present after and absent before, from the bydocno read.

## Row replace ("D" + DtlKey 0 in one PUT)
- AC-61-10 One builder makes `Details [old row as read + FullTransferOption "D", new row DtlKey 0]` on the kind's edit
  door; the new row carries the full vendor row shape with `FullTransferOption " "`, and `FromDocType/FromDocNo/FromDocDtlKey`
  only when linking.
- AC-61-11 PO unlink through the `/po-links/unlink` route AND through the `unlink_row` operation sends exactly ONE PUT
  (no blank-link PUT, no DELETE): linked row "D" + a normal row with the same item, qty, unit price, UOM, Location and
  DeliveryDate. Read-back: old DtlKey gone, one new row, `FromSODtlKey 0`. Answer `done`, new DtlKey returned.
- AC-61-12 PO link of a whole normal row (`link_row` and the service's whole-row link) = ONE PUT [normal row "D", new
  row linked to the SO row]; no longer `VENDOR_UNSUPPORTED`. When the old row was not at HQ or had a DeliveryDate, a second
  PUT moves the new row's Location + DeliveryDate; if that move fails the answer carries warning `LOCATION_NOT_MOVED`
  and the link stays (F5).
- AC-61-13 Relink (`relink_row`) = ONE PUT [linked row "D", new row linked to the target SO row] + the move of AC-61-12.
  No `delete_line` + `add_line` sequence, no DELETE request.
- AC-61-14 Partial link (split) = ONE PUT [original row with the cut qty, new linked row DtlKey 0] + the move.
- AC-61-15 Atomic refusal (F8): the vendor answers 500 to a replace PUT; the answer is `VENDOR_REFUSED` (vendor text
  carried), nothing is reported as applied, and no second PUT (move) is sent.
- AC-61-16 Every row SS sends on any door (create, edit, add, replace, QT included) has `FullTransferOption " "`
  unless it is a "D" row, and `FullTransferFromDocList ""`.

## Delete line
- AC-61-20 `delete_line` (QT, SO, PO) = PUT on the edit door with `[row "D"]` only. No DELETE request. Read-back: the
  row is gone, every other row unchanged, else `LINE_NOT_DELETED`.
- AC-61-21 Vendor refusal of a "D" on a row transferred onward (500, `UnableToDelete...TransferredItemException`) ->
  `ROW_HAS_TRANSFERS`. Today's pre-send guards (`ROW_RECEIVED`, receipt split) still run first.
- AC-61-22 Removing the LAST remaining row of a QT, SO or PO (any delete_line whose read shows one row) is refused
  `ROW_LAST_LINE` with no write request (crew decision Q2, 10 Nov). The gateway maps it like the other row refusals
  (409) and the contract doc lists it.

## Cancel
- AC-61-30 `cancel_doc` (QT, SO, PO) = AC-61-01 request, then a bydocno read: `Cancelled "T"` -> `done`; otherwise
  `CANCEL_IGNORED`. No PUT with header `Cancelled`.
- AC-61-31 Vendor 400 containing `transfered` -> `DOC_HAS_TRANSFERS`; 400 containing `(Void)` -> `DOC_CANCELLED`; other
  4xx/5xx -> `VENDOR_REFUSED` with the vendor text.
- AC-61-32 The gateway `POST /documents/{kind}/{docKey}/cancel` answers `done` for QT/SO/PO when the switches are on;
  SPO stays `VENDOR_UNSUPPORTED`.

## Capabilities
- AC-61-40 Capability table: ON PO unlink / link_existing_row / delete_line / cancel_doc; SO and QT delete_line /
  cancel_doc; OFF SPO (all but edit_doc), `spo_unlink`, `delete_doc` (all kinds). `/write-capabilities` and the
  operations capability report reflect it (`unlink_row` enabled for PO, the reason CRM #2168 reads).
- AC-61-41 The placeholder DELETE paths (`Delete*bydtlkey`, `Delete*bydockey`) are gone from the code; `delete_doc`
  answers `VENDOR_UNSUPPORTED` without a request.
- AC-61-42 CRM's admin switch is untouched (no SS default flips a CRM setting).

## Evidence
- AC-61-50 [db3] Runner rerun with the switches on: unlink, whole-row link, relink, delete line (QT/SO/PO), cancel
  (QT/SO/PO plain + with transfers) through `WriteBackService` / `OperationService`; report
  `documentation/integrations/autocount/test-report-2026-11-10.md`.
- AC-61-51 Vendor spec Answers section filled (`crew/state/inbox/autocount-api-10nov.md`).
