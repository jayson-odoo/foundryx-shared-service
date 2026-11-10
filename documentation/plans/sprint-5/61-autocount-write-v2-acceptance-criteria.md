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
  row linked to the SO row]; no longer `VENDOR_UNSUPPORTED`. When the read-back differs from the target, a second PUT on the
  new row sets Location = the operation's `moveTo` when given, else the old row's Location (today's `_move`,
  `wb/operations.py:614`), and DeliveryDate = the old row's DeliveryDate (skipped when that was empty / 0001-01-01); if that move fails the answer carries warning `LOCATION_NOT_MOVED`
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
- AC-61-22 Removing the LAST remaining row is passed through like any other delete_line (owner ruling R1, 10 Nov:
  never blocked); no `ROW_LAST_LINE` code exists.

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

## API call log (owner ruling R3)
- AC-61-60 Every HTTP call through the write layer writes ONE `ac_api_call_log` row: POST create, PUT edit, the
  replace PUT, the 2nd move PUT of a link (two PUT rows + their reads for one link), DELETE cancel (path with the
  encoded query), GET bydocno, GET day-list fallback, GET debtor term.
- AC-61-61 Row fields: tenant, company, created_at, actor, request_id (`X-Request-ID` when sent, else the
  Idempotency-Key), operation_id / action_id when known, book (`db3`), method, path (no host), doc_type, doc_no /
  doc_key when known, request_json (NULL for GET / DELETE), response_status, response_body cut at 32 KB with
  `response_truncated`, duration_ms >= 0, outcome, error_code.
- AC-61-62 Failed calls are logged: vendor 500 (`http_error`, body kept), timeout (`timeout`, no status), connect error
  (`connect_error`), allowlist refusal (`guard_refused`, no request sent).
- AC-61-63 Durable: the rows of a call survive a rollback of the caller's session; a log-write failure never fails
  the call.
- AC-61-64 No secret, header value or base URL host is ever stored (scan every column of every row in the tests).
- AC-61-65 Migration `0044` is additive (new table + indexes on tenant/company/created_at and doc_key only); the
  global guards `tests/test_schema_uuid_id_principle.py` and `tests/test_list_pagination_limit.py` pass.

## Evidence
- AC-61-50 [db3] Runner rerun with the switches on: unlink, whole-row link, relink, delete line (QT/SO/PO), cancel
  (QT/SO/PO plain + with transfers) through `WriteBackService` / `OperationService`; report
  `documentation/integrations/autocount/test-report-2026-11-10.md`.
- AC-61-51 Vendor spec Answers section filled (`crew/state/inbox/autocount-api-10nov.md`).
