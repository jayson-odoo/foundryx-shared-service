# Plan 61: AutoCount write API v2 (vendor update 10 Nov 2026)

Lane SS-AC-WRITE-V2, branch `crew/ss-ac-write-v2`, size M, backend only. UAC: `61-autocount-write-v2-acceptance-criteria.md`.
Builds on plan 55 (`55-autocount-write-link*.md`) and plan 57 (`57-autocount-write-qtso*.md`).

## 1. Why

The AutoCount vendor changed the hapi write API on 10 Nov 2026 (condensed spec, PII-free:
`crew/state/inbox/autocount-api-10nov.md`, outside the repo):

- One PUT can delete a row (`FullTransferOption "D"` on its DtlKey) and add a new row (DtlKey 0) with or without
  `FromDocType / FromDocNo / FromDocDtlKey`. A row's link can never change in place, so unlink, link of a whole row,
  relink / move and delete line all become ONE PUT.
- Cancel is `DELETE /Cancel<Doc>bydocno?DocNo=<no>` (no body).
- One document is read with `GET /<Doc>bydocno?DocNo=<no>`.
- Owner answers 10 Nov: a PUT that omits existing rows KEEPS them; "D" on a transferred row returns the qty to the
  source document. Every other API question is answered by db3 probes in this lane (section 3), never the owner.

## 2. Gap map (origin/main ba13b207, wb = `service_backend/modules/autocount/write_back/`)

- Paths: `wb/doc_kinds.py:37-51`, `wb/constants.py:5-11`. Delete line / delete doc use placeholder DELETE paths marked
  UNVERIFIED AQ23 (`wb/doc_kinds.py:4-5,33-34`). No bydocno GET. No RQ kind.
- Unlink PUTs the row with link fields blanked (`wb/payloads.py:153-156,302-312`); db3 ignored it, refused at
  `wb/service.py:455-460`, `wb/capabilities.py:16-19`. Whole-row link refused VENDOR_UNSUPPORTED (`wb/service.py:541-543,610-611`).
  Relink = delete_line + add_line + location move (`wb/operations.py:594-708`), refused (`:375-377`).
- Cancel = PUT header `Cancelled "T"` (`wb/payloads.py:573-581`), ignored by db3, switched off; gateway answers
  VENDOR_UNSUPPORTED (`write_v1.py:411`). `wb/client.py:37` rejects a `?` in the path; `wb/client.py:85` always sends a JSON body.
- Every write is wrapped by a by-date day-list read filtered on DocKey (`wb/operations.py:422-432`,
  `wb/primitives.py:428-448,549-565`).
- Edits send only changed rows (`wb/payloads.py:517-555`); QT rows never set `FullTransferOption` (`wb/payloads.py:425-435`).

## 3. db3 probes (before any code; results drive section 4 and the capability table)

Run 10 Nov 2026, tags `FXT-1110a-` .. `FXT-1110e-` (a: credit-limit stop, b: script stop, c/d/e: full runs), own
documents only, db3 only, nothing deleted. Exact requests and responses:
`crew/state/files/autocount-api/db3-requests-10nov-run{1..5}.json` (outside the repo). Sanitised summary:
`documentation/integrations/autocount/test-report-2026-11-10.md`.

### 3a. Results (the facts the design rests on)

| # | Probe | Result |
|---|---|---|
| F1 | GET `/Quotationbydocno`, `/SalesOrderbydocno`, `/PurchaseOrderbydocno`, `/RequestQuotationbydocno` `?DocNo=` | 200, a JSON list with the doc (header + `Details`); unknown DocNo = `[]`. The vendor spelling `Quotaton` / `RequestQuotaton` = 404. Path case does not matter (GET and PUT `ByDocKey`). |
| F2 | QT->SO full transfer, then a second SO from the same QT row (P-T1) | 500 `item already full transferred`: AutoCount enforces the outstanding qty. |
| F3 | PUT SO with the QT-transferred row + `FullTransferOption "D"` (P-D1), then a new SO from the QT row (P-T2) | row removed; the new full-qty SO is accepted: "D" returns the qty to the QT (owner answer 2 confirmed). |
| F4 | PO unlink: ONE PUT = linked row "D" + new normal row DtlKey 0 (P-U1, P-U4) | applied: linked row gone, new normal row keeps item/qty/price and the Location + DeliveryDate sent in the same PUT; the SO row's qty is freed (P-U0 cut refused before, P-U2 accepted after). |
| F5 | PO link of a whole normal row: ONE PUT = normal row "D" + new row DtlKey 0 `FromDocType SO` (P-L1); relink to another SO row the same way (P-R1); a linked add on its own (P-L4) | applied; the new linked row is still forced to `Location HQ` and `DeliveryDate 0001-01-01` whatever was sent. A second PUT on the new row moves Location + DeliveryDate and keeps the link (P-L2). A PO row reads its link as `FromSODtlKey` (`FromDocType` reads ""). |
| F6 | Delete line: PUT with only `{DtlKey, FullTransferOption "D"}` (P-DL1) and with the full row shape (P-DL4 QT, P-DL5 SO) | applied on PO, QT and SO. "D" on the last row leaves a document with no rows (P-DL6). |
| F7 | "D" on a row that was transferred onward: SO row linked from a PO (P-DL2), QT row transferred into an SO (P-DL3) | refused 500 `UnableToDeleteTransferredItemException` / `UnableToDeletePartialTransferredItemException`; nothing changed. |
| F8 | Atomic: "D" + an invalid new row (unknown item P-AT1, missing SO row P-AT2) | 500 (`NotExistItemCodeException`, `InvalidTransferItemException`); the "D" did NOT land. One PUT is all or nothing. |
| F9 | DELETE `/Cancel<Doc>bydocno?DocNo=` on a plain QT, SO, PO (P-C1, P-C5, P-C6) | 200 `... was cancelled.`; GET reads `Cancelled "T"`, `DocStatus "V"`. |
| F10 | Cancel again (P-C1b) / edit a cancelled doc (P-C1c) / unknown DocNo (P-C7) | 400 `Unable to (Cancel Document) ... (Void).` / 500 `not allowed to edit expired or void document` / 400 `... failed to cancel.` |
| F11 | Cancel a QT transferred into an SO (P-C2), an SO transferred into a PO (P-C3) | 400 `The document was transfered to other document, so it is not allow to cancel.` / `The Sales Order was transfered to Purchase Order ...`; nothing changed. |
| F12 | Cancel a PO linked to an SO (P-C4), an SO taken from a QT (P-C9) | 200 cancelled; the SO row's qty is freed (P-C8) and the QT qty returns (P-C9b). |
| F13 | PUT with `Details []` and a header change (P-CASE) | header applied, every row kept (owner answer 1). |
| F14 | SPO create: POST `/NewPurchaseOrder` `ShippingPO "T"`, full body, plain row (P-SPO1) | 200 but reads back `ShippingPO "F"`: a plain PO. db3 still cannot make an SPO, so no SPO probe can run. |
| F15 | "D" on a partly received PO row | NOT TESTABLE on db3: there is no GRN write door. UNVERIFIED; our own receipt guard stays. |

## 4. Design

### 4.1 One row-replace builder (`wb/payloads.py`)
`build_row_replace(kind, doc, old_row, new_row)` = header + `Details [old row as read with FullTransferOption "D", new
row DtlKey 0]`. The new row is a full vendor row (`_vendor_line`, `FullTransferOption " "`), with or without
`FromDocType / FromDocNo / FromDocDtlKey`. `build_delete_line` = header + `[old row "D"]` on the edit door.
Every row we send (create, edit, add, replace, QT too) defaults `FullTransferOption " "` and `FullTransferFromDocList ""`.
The old `_unlinked` blank-link PUT (`build_unlink`, `build_spo_unlink`) and the placeholder DELETE shapes go.

### 4.2 Flows that switch to the builder
- PO unlink (`/po-links/unlink` route via `WriteBackService.unlink`, and the `unlink_row` operation): ONE PUT
  [linked row "D", normal row with the same item / qty / price / UOM / Location / DeliveryDate / description]. Done in one
  write (F4). Verify: old DtlKey gone, exactly one new row, `FromSODtlKey 0`, values kept.
- PO link of a whole normal row (`link_row` op, and the service whole-row link that answered VENDOR_UNSUPPORTED): ONE PUT
  [normal row "D", new row linked to the SO row]; then, when the old row was not at HQ or had a DeliveryDate, the
  existing move PUT on the new row (F5). Move failure = row stays linked at HQ, warning `LOCATION_NOT_MOVED`.
- Relink / move (`relink_row`): ONE PUT [linked row "D", new row linked to the new SO row] + the same move.
  The old 3-step flow (delete_line + add_line + move, with stray removal) shrinks to 2 writes; `_remove_strays` is no
  longer needed for step 1 (F8: atomic) but resume after a failed move stays.
- Partial link (split) keeps today's shape but in ONE PUT: [original row with the cut qty, new linked row DtlKey 0].
- delete_line: PUT [row "D"]. Today's pre-send guards stay (`ROW_RECEIVED`, `ROW_HAS_TRANSFERS` where our data shows
  it). AutoCount's own refusal (F7, exception type `UnableToDelete*TransferredItemException`) maps to
  `ROW_HAS_TRANSFERS`; any other vendor 500 stays `VENDOR_REFUSED`. Last row: passed through like any other row
  (owner ruling R1 below; AutoCount leaves a document without rows, F6).

### 4.3 Cancel (`cancel_doc`)
`DELETE /Cancel{Quotation|SalesOrder|PurchaseOrder}bydocno?DocNo=<url-encoded DocNo>`, no body. `client.py` allows a
query string only through a dedicated `delete_query(path, params)` that encodes the value (the general `?` ban in
`_check_path` stays for every other call). Verify with GET bydocno: `Cancelled "T"` (else `CANCEL_IGNORED`).
Answer mapping: 400 `transfered` -> `DOC_HAS_TRANSFERS`; 400 `(Void)` -> `DOC_CANCELLED`; other 4xx/5xx -> `VENDOR_REFUSED`.
Header `Cancelled "T"` PUT goes. `delete_doc` has no vendor door: its path is removed and it stays refused `VENDOR_UNSUPPORTED`.

### 4.4 Read-back
`AutoCountDocReader.get_by_doc_no(kind, doc_no)` = GET `/<Doc>bydocno?DocNo=` (paths in `DocKind.by_doc_no_path`:
`/Quotationbydocno`, `/SalesOrderbydocno`, `/PurchaseOrderbydocno`). Must match the expected DocKey (else
`DOC_KIND_MISMATCH` / `DOC_NOT_FOUND`). DocNo comes from the caller, the staged copy, or the last confirmed action (same
sources as `find_date`). The by-date day-list stays only as fallback when the bydocno GET fails (transport error, non-2xx,
or no DocNo known). New row DtlKeys come from this read (after-keys minus before-keys).

### 4.5 Capabilities (`wb/capabilities.py`), all still behind CRM's admin switch (default OFF)
ON from probes: PO `unlink`, `link_existing_row`, `delete_line`, `cancel_doc`; SO `delete_line`, `cancel_doc`;
QT `delete_line`, `cancel_doc`. OFF: SPO everything except today's `edit_doc` (F14), `spo_unlink`, `delete_doc` (no door).
`ZERO_QTY_EMULATION` goes (the replace builder supersedes it). RQ: GET door exists (F1); no kind added (no caller).

### 4.6 Crew decisions 10 Nov 2026 (behaviour card; owner: "verify ourselves", crew decides obvious defaults)
- Rules (1)-(7) of the card accepted as written (SPO stays OFF, `ROW_RECEIVED` guard kept, every capability behind
  CRM's admin switch, default OFF).
- Q1 = (a): link / relink = the D+add PUT, then a 2nd PUT moves Location + DeliveryDate back; if that fails the row
  stays linked at HQ and SS answers with warning `LOCATION_NOT_MOVED` (CRM shows it).
- Q2 = (b) `ROW_LAST_LINE`: SUPERSEDED by owner ruling R1 below (no new code).

### 4.7 Owner rulings 10 Nov 2026 22:5x (verbatim: "i do not think we should block removing the last line of a
document, I am okay with linking a row then changing its location, make sure all API call is logged yeah for traceability")
- R1 (overrides crew Q2): removing the last line is NOT blocked. delete_line passes it through; no `ROW_LAST_LINE`.
- R2 (confirms Q1 (a)): link / relink = the D+add PUT, then a 2nd PUT moves Location + DeliveryDate.
- R3 NEW: every AutoCount hapi call SS makes through the write layer is logged durably for traceability.

### 4.8 API call log (R3)
New module table `app_autocount.ac_api_call_log` (additive module migration `0044`, no change to existing tables;
`ac_write_action` stays one row per write action, this table is one row per HTTP call). Columns: `id` (uuid),
`tenant_id`, `company_id`, `created_at` (UTC, call start), `actor` (API key id for gateway calls, `runner` for the db3
runner, `system` otherwise), `request_id` (CRM's optional `X-Request-ID` header, else the `Idempotency-Key`),
`operation_id`, `action_id`, `book` (the base URL's last path segment, e.g. `db3`; never the full URL), `method`,
`path` (vendor path incl. query, no host), `doc_type`, `doc_no`, `doc_key`, `request_json` (body as sent, NULL for
GET / DELETE), `response_status` (NULL when no answer), `response_body` (text, cut at 32 KB) + `response_truncated`,
`duration_ms`, `outcome` (`ok` 2xx | `http_error` | `timeout` | `connect_error` | `guard_refused`), `error_code`.
- Written from ONE seam: `AutoCountWriteClient._send` / `delete_query` and `AutoCountDocReader`'s GETs (writes,
  read-backs, bydocno, day-list fallback, debtor term, cancel), so no call path can skip it. A call refused by the
  allowlist guard before sending is logged with `guard_refused` (no request made).
- Durable: the log row is committed on its own short session, so it survives a rollback of the business transaction
  (a failed write still leaves its call rows). A failure to write the log never breaks the call (logged to the app
  logger as a code only).
- Never stored: API keys, auth headers, the base URL host. Bodies are AutoCount document data already held in
  `ac_write_action.request_json`.
- Scope: the write layer's client and reader (write-back, read-backs, runner, `pull_docs` on the write connection).
  The master / doc-feed SYNC GETs (`http_source`) are out of scope: thousands of paged reads per run with large bodies,
  already traced by run history. Asked to crew as a follow-up option, not built here.
- Retention: none in this lane (write-layer volume is small); listed as an open item.
- Crew test copy: `crew/state/migrations/SS-AC-WRITE-V2.sql` (idempotent `CREATE TABLE IF NOT EXISTS`).

## 5. Slices (red tests first for each, tester then coder)
- S1 client + reader: `delete_query`, bydocno GET, fallback; fake vendor learns bydocno, cancel DELETE, "D" rows,
  forced HQ on linked add, atomic refusal, transferred-row "D" refusal.
- S2 builder + FullTransferOption default + delete_line + cancel primitives + capability table.
- S3 operations / service flows: unlink (route + op), whole-row link, relink, split in one PUT; gateway answers.
- S4 db3 runner rerun of C01..C12 + QT/SO cases with the switches on; test report; docs.

## 6. CRM follow-ups (separate lanes; filled at the end)
