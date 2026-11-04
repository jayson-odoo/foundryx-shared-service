# Plan 57 acceptance criteria: AutoCount write layer (primitives + operations), QT / SO phase 2

4 Nov 2026. Owner scope change (17:35): AutoCount says a line's link can never be edited after the line
exists; the way is delete the line and add a new one. AutoCount is preparing a delete API. Card 1 rulings and the owner's alignment notes (4 Nov: unknown receipts are AutoCount's to refuse; available-operations feed yes; location rule yes)
folded in: Q1 (a) SS only; Q2 (a) (owner, 4 Nov) with (b) as a one-line switch, default (a);
Q3 (a); Q4 (a); Q5 (a). Rows tagged [probe] are adjusted by the recorded db3 probes
(`57-autocount-write-qtso.md` section 4); rows tagged [AQn] wait for AutoCount
(`documentation/integrations/autocount/write-api-questions-2026-11-04.md`). Plan 55 criteria stay in
force unless a row here replaces one.

## A. Safety

| AC | Rule |
|---|---|
| AC-57-01 | [BE] Every AutoCount write (POST, PUT, DELETE) goes through `AutoCountWriteClient`; the db3 guard runs on every request, including the new DELETE verb; no other code path sends a non-GET request to the wrapper |
| AC-57-02 | [BE] Delete-line, delete-document and cancel requests aimed at any book other than `db3` (db1, db2, look-alikes) are refused before any network call (failing transport) |
| AC-57-03 | [BE] Capability flags are read at call time; a primitive or operation whose flag is off is refused `VENDOR_UNSUPPORTED` before any HTTP request. Shipped state (db3 probes 4 Nov): `delete_line` and `delete_doc` off for every kind [AQ23]; `cancel_doc` off for every kind (header `Cancelled "T"` answered 200 and changed nothing on both edit doors) [AQ2]; `create_doc`, `edit_doc`, `add_line` on for QT, SO, PO; SPO `create_doc` and `add_line` off (plan 55: refused or rows dropped) |
| AC-57-04 | [BE] Delete-document exists as a primitive only: no gateway route and no operation can reach it (route table test + operation step table test); cancel is the only way a document ends |
| AC-57-05 | [BE] Nothing retries a write by itself; a timeout leaves the action `pending_verification` |

## B. Primitives (PO, SPO, SO, QT)

Each primitive = guard -> capability -> busy check -> fresh GET (not for create) -> stale check -> pure
builder -> ONE vendor write -> GET back -> verify -> one `ac_write_action` row -> answer = read-back.

| AC | Rule |
|---|---|
| AC-57-10 | [BE] Create QT / SO / PO: refused `FIELD_REQUIRED` (naming the field) with no HTTP when the header lacks DebtorCode (CreditorCode for PO), DocDate, DisplayTerm, CurrencyCode or CurrencyRate, or there is no line, or a line lacks ItemCode, UOM, Qty > 0, UnitPrice >= 0 or Location. Dates before 1753 are never sent |
| AC-57-11 | [BE] Create SO lines may carry `FromDocType "QT"`, `FromDocNo`, `FromDocDtlKey`; they are sent as given and verified by `FromDocType` + `FromDocNo` (AutoCount reads `FromDocDtlKey` back as 0 and the QT shows no back-link, probe P-SO0, AQ15 / AQ31): a 0 read-back adds warning `QT_ROW_LINK_UNCONFIRMED`, never a failure |
| AC-57-12 | [BE] Create read-back: DocKey and DocNo are parsed from the 2xx answer text (`DocNo=<no> ,DocKey=<key> ... Created Successful.`); the document is then read by DocDate and that DocKey, exactly one match, else `pending_verification` (an unparseable 2xx falls back to DocDate + DocNo when the caller sent the DocNo); every sent line must read back (item, UOM, qty, unit price, location) and the line count must match; a 2xx with dropped lines is `mismatch` / `ROWS_DROPPED`, never done. The answer carries DocKey, DocNo and each line's DtlKey |
| AC-57-13 | [BE] DocNo: optional; when absent the body sends `"<<New>>"` and AutoCount assigns the next number (probe P-DOC2: 200, `DocNo=QT-000001`); a body never omits DocNo (probe P-DOC1b: 500 `DocNo` not null). The `auto_docno` capability (on) gates the sentinel; off = `DOCNO_REQUIRED` |
| AC-57-14 | [BE] Edit document: header changes only from an allowlist (Ref, Description, Remark1-4, DisplayTerm, SalesAgent, YourPONo, delivery / invoice address fields); line changes by DtlKey only for Qty, UnitPrice, Discount, Location, Description, DeliveryDate. Body = full header from the fresh GET with the changes, plus only the changed rows. Every sent change must read back as sent and every untouched header field and row unchanged; a field AutoCount ignored makes the outcome `mismatch` naming that field |
| AC-57-15 | [BE] Add line: one `DtlKey 0` row; exactly one new row reads back; the answer carries its DtlKey |
| AC-57-16 | [BE] Delete line (flag): method, path and body come from ONE vendor-shape entry per kind [AQ23]; read-back shows the row gone and every other row and the header unchanged |
| AC-57-17 | [BE] Cancel document (flag): the edit door with the full header and `Cancelled "T"` [probe][AQ2]; read-back `Cancelled "T"`, else `mismatch` |
| AC-57-18 | [BE] Refused before any HTTP, stable codes: edit / add / delete / cancel on a cancelled document `DOC_CANCELLED`; cancel of a QT whose header names a target document (`ToDocType`) or of an SO with PO lines linked to it or delivered lines `DOC_HAS_TRANSFERS`; delete of an SO line that PO lines link to `ROW_HAS_TRANSFERS`; SO line qty edited below its linked qty `QTY_BELOW_TRANSFERRED`; `DOC_STALE`; `DOC_BUSY`; `ROW_NOT_FOUND`; `DOC_KIND_MISMATCH` |
| AC-57-19 | [BE] Every vendor call is recorded on its action row exactly: method, path (no host), request body, response status and body, before and after documents; no host, key or credential anywhere in the row, logs or answer |
| AC-57-20 | [BE] Finding a document by DocKey (the wrapper reads by date only): the caller's optional `docDate`, else the staged record's DocDate, else the DocDate of our last confirmed read-back of that document (action log); none known = `DOC_DATE_REQUIRED` before any HTTP; a GET that misses the DocKey on that date = `DOC_NOT_FOUND` (staff may have changed the date in AutoCount) |

## C. Operations (CRM picks which; SS owns how)

| AC | Rule |
|---|---|
| AC-57-30 | [BE] `link_row` (PO row, unlinked, whole qty -> one SO row): delete the row, add a row copying every field of the snapshot (item, UOM, qty, unit price, discount, tax code, description, delivery date, location) plus the SO link, then move the location when the read-back differs from the snapshot. Answer `replacedLines [{oldDtlKey, newDtlKey}]` |
| AC-57-31 | [BE] `unlink_row` and `relink_row` (PO rows) and `spo_link_row`, `spo_unlink_row`, `spo_relink_row` (SPO rows pointing at PO rows) follow AC-57-30 on their own document |
| AC-57-32 | [BE] Guards before step 1, no HTTP write on refusal: delete_line flag off `VENDOR_UNSUPPORTED`; item or UOM differs `ITEM_MISMATCH` / `UOM_MISMATCH`; row qty above the SO row outstanding `QTY_ABOVE_OUTSTANDING`; PO row an SPO row points at `ROW_ON_SPO` (plan 55 Q4 kept); link_row on a linked row `ROW_ALREADY_LINKED`; unlink on an unlinked row `ROW_NOT_LINKED`; relink to the same SO row `NO_CHANGE` |
| AC-57-33 | [BE] Received / delivered lines (Q2 rec (a), switch `PARTIAL_RECEIPT_SPLIT`): fully received `ROW_RECEIVED`; partially received = no delete: edit the row to the received qty and add the open remainder as the new linked / unlinked row (then the move). Received qty NOT known (every hapi document today, AQ11): no refusal from us (owner, 4 Nov: "the refusal should come from AutoCount, not us"); the delete path runs with warning `TRANSFER_STATE_UNKNOWN`, and if AutoCount refuses the delete the outcome is `vendor_error` / `VENDOR_REFUSED` carrying AutoCount's message, with nothing else written. Switch off: any known receipt `ROW_RECEIVED` |
| AC-57-34 | [BE] Recovery: the delete landed and the add then failed (vendor error, mismatch, or no new row in the read-back): re-add the original from the snapshot with its original link (then the move); outcome `recovered` with the failed step's error code and the re-created row's new DtlKey |
| AC-57-35 | [BE] Recovery also fails: outcome `needs_attention`, snapshot kept on the operation, one alert email to the AutoCount alert recipients naming company, document, item, UOM, qty, location and link of the line to re-key; no automatic retry |
| AC-57-36 | [BE] Resume (`needs_attention` or `pending_verification`): re-read AutoCount; a row matching the snapshot (item, UOM, qty, location, link) or the intended new row present = resolve without a write; otherwise re-create from the snapshot (then the move) |
| AC-57-37 | [BE] Idempotency key (tenant + company + API key scope): same key and same body = the stored answer, no HTTP; same key, other body = 409 `IDEMPOTENCY_CONFLICT`; same key while running = 409 `OPERATION_IN_PROGRESS` |
| AC-57-38 | [BE] One operation at a time per document, held across all its steps (`DOC_BUSY`) |
| AC-57-39 | [BE] Location move fails after the link landed: outcome `done` with warning `LOCATION_NOT_MOVED` (plan 55 Q3) |
| AC-57-40 | [BE] Plan 55 split link keeps its behaviour and also accepts an idempotency key |

## D. Sink and CRM re-pointing

| AC | Rule |
|---|---|
| AC-57-50 | [BE] After a confirmed operation or primitive on PO, SPO or SO, the read-back document goes out through the Sorento sink; each line that replaced a deleted one carries `replacesLineRef` = the deleted line's ref; other lines carry none |
| AC-57-51 | [BE] The Sorento contract doc and its version are updated in the same change (additive optional field) |
| AC-57-52 | [BE] QT is answered, not pushed (no canonical quotation entity) |

## E. Gateway

| AC | Rule |
|---|---|
| AC-57-60 | [BE] Every new route needs `X-API-Key` with the `write_back` scope (403 `SCOPE_REQUIRED` otherwise); tenant and company come from the key and `companyCode`, never from other body fields |
| AC-57-61 | [BE] Routes: create / edit / add line / delete line / cancel per document kind; link / unlink / relink operations for PO and SPO rows; read and resume an operation. Status mapping as plan 55 (200 done, 202 pending, 403 / 409 refused, 502 vendor) |
| AC-57-62 | [BE] Plan 55 routes keep their request and answer shape; `idempotencyKey` optional there, required on new routes |
| AC-57-63 | [BE] Contract doc `57-autocount-write-qtso-contract.md` ships with the routes |

## F. Evidence and readiness

| AC | Rule |
|---|---|
| AC-57-70 | [BE] Every db3 probe and runner call is recorded exactly in the private evidence file; the repo test report carries the sanitised table |
| AC-57-71 | [BE] Fake-vendor contract suite (no network): link / unlink / relink / SPO variants / recovery / needs_attention / resume / idempotency / partial receipt run green against a fake wrapper that implements the expected delete shape and the known db3 behaviour (link only on new rows, forced HQ, omitted rows kept); turning delete on = flip the flag + one live db3 run |
| AC-57-72 | [BE] Live db3 runner: QT / SO create, edit, add line, cancel per capability; every flag-off operation refused with no HTTP |
| AC-57-73 | [BE] Module migration applied and checked on a lane Postgres copy; existing action rows keep working (new columns nullable) |
