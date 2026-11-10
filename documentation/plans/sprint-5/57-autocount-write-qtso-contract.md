# AutoCount write layer gateway (cross-repo contract, later CRM lanes)

Status: FINAL for the shipped wire, 2026-11-04, lane AC-WRITE-QTSO, plan `57-autocount-write-qtso.md`
section 5.6, UAC AC-57-60..63. Extends `55-autocount-write-link-contract.md`: auth (`X-API-Key` with the
`write_back` scope), company resolution (`companyCode`), the flat error body (its section 6), `no-store`
and the size cap are unchanged and not repeated here. Names below are quoted from the shipped code.

## Changes

- 2026-11-10 (plan 61, AutoCount write API v2, db3 probes F1..F15): delete line, cancel, whole-row link,
  unlink and relink are switched ON for quotations, sales orders and purchase orders (SPO stays off).
  Delete line = one PUT with the row marked `FullTransferOption "D"` (removing the last line is allowed:
  the document then reads back with no lines). Cancel = AutoCount's `DELETE /Cancel<Doc>bydocno?DocNo=`.
  Whole-row link, unlink and relink = ONE PUT that deletes the row and adds its replacement (all or
  nothing), then a second write puts the new row's location and delivery date back. Answer shape,
  statuses and `replacedLines` are unchanged; `DOC_HAS_TRANSFERS`, `DOC_CANCELLED` and
  `ROW_HAS_TRANSFERS` can now also come from AutoCount's own refusal (section 5).
- 2026-11-05: `GET /write-capabilities` adds top-level `book`, the AutoCount book SS writes to for
  the company (`null` when writes are off). Additive; refuse writes on documents keyed to another book.
- 2026-11-04 (final review round): field names in `message` and `warnings` are the caller's camelCase
  (`FIELD_IGNORED`, `QT_ROW_VALUES_INHERITED`). `QTY_INVALID` and `PRICE_INVALID` are `422`, checked before
  any read. `/po-links`, `/po-links/unlink` and `/spo-links/unlink` accept optional `docDate`. A split link
  on a PO whose date is unknown is `409 DOC_DATE_REQUIRED`. `write-capabilities` uses the URL slugs as
  `kind` and lists `split_link`. An operation that passes its deadline ends `pending_verification`
  (resumable).
- 2026-11-04: first complete version. Describes the routes, bodies, answer, statuses and codes as
  shipped. `GET /write-capabilities` is built (no longer proposed). The plan 55 routes
  `/po-links`, `/po-links/unlink` and `/spo-links/unlink` now run through the operation layer: optional
  `Idempotency-Key`, and when an operation answers, the body also carries `operationId`, `message`,
  `warnings`, `docKey`, `docNo` and `replacedLines`. `/po-links` takes optional `soDocDate`.

## 1. What it adds

| Route | Level | Does |
|---|---|---|
| `POST /api/v1/autocount/documents/{kind}` | primitive | Create a document |
| `PATCH /api/v1/autocount/documents/{kind}/{docKey}` | primitive | Edit header fields and existing lines |
| `POST /api/v1/autocount/documents/{kind}/{docKey}/lines` | primitive | Add one line |
| `POST /api/v1/autocount/documents/{kind}/{docKey}/lines/{dtlKey}/delete` | primitive | Delete one line (quotations, sales orders, purchase orders) |
| `POST /api/v1/autocount/documents/{kind}/{docKey}/cancel` | primitive | Cancel the document (quotations, sales orders, purchase orders) |
| `POST /api/v1/autocount/po-links` | operation | Plan 55 body. Part of a row: split link. Whole row: one replace PUT (row deleted, linked row added) + move |
| `POST /api/v1/autocount/po-links/unlink` | operation | Plan 55 body; one replace PUT (linked row deleted, normal row added) |
| `POST /api/v1/autocount/po-links/relink` | operation | New: move a PO row's link to another SO row |
| `POST /api/v1/autocount/spo-links` | operation | New: link an SPO row to a PO row |
| `POST /api/v1/autocount/spo-links/unlink` | operation | Plan 55 body; switched off (`VENDOR_UNSUPPORTED`): no SPO write is proven |
| `POST /api/v1/autocount/spo-links/relink` | operation | New: move an SPO row's link to another PO row |
| `GET /api/v1/autocount/write-operations/{operationId}?companyCode=` | read | One operation's state and answer |
| `POST /api/v1/autocount/write-operations/{operationId}/resume` | operation | Resume a `needs_attention` or `pending_verification` operation |
| `GET /api/v1/autocount/write-capabilities?companyCode=` | read | Which primitives and operations are available, and why not (section 7) |
| `GET /api/v1/autocount/documents/{kind}/{docKey}?companyCode=&docDate=` | read | The document as AutoCount holds it now (section 1a) |

`/po-links/relocate` (plan 55) is unchanged. `{kind}`: `quotations`, `sales-orders`, `purchase-orders`,
`shipping-purchase-orders`; any other value is `404 UNKNOWN_KIND` (flat body). `{docKey}` and `{dtlKey}`
are integers in 1..9223372036854775807, else `422 INVALID_REQUEST`. There is no route that deletes a
document: cancel is the only way a document ends. Today the switched-on primitives are create, edit, add
line, delete line and cancel for quotations, sales orders and purchase orders, and edit for shipping
purchase orders.

### 1a. Read a document

`GET /api/v1/autocount/documents/{kind}/{docKey}?companyCode=SRT[&docDate=YYYY-MM-DD]` reads the document
fresh from AutoCount (never the staged copy) so a caller can take `LastModified` (for
`expectedLastModified`) and the row keys before an edit. `{kind}` also accepts `qt`, `so`, `po`, `spo` on
this route. Same key, `write_back` scope, company resolution and write guard as the write routes; it
never writes, records no action and stages nothing. `docDate` follows the edit rule: needed when the
document is not staged and SS never wrote it (always for a quotation SS did not create), else `409
DOC_DATE_REQUIRED`. The answer is the primitive shape (section 4) with `outcome: "done"`, `operationId`
and `actionId` null and `document` = AutoCount's fields as read (`DocKey`, `DocNo`, `DocDate`,
`LastModified`, `Details[].DtlKey`, ...). A refusal uses the same shape and status mapping:
`403 WRITE_DISABLED` / `WRITE_NOT_ALLOWED`, `409 DOC_DATE_REQUIRED`, `DOC_NOT_FOUND`, `DOC_AMBIGUOUS`,
`DOC_KIND_MISMATCH`, `READ_FAILED`. A cancelled document is returned (`Cancelled "T"`), not refused.

## 2. Idempotency

Header `Idempotency-Key: <1..128 printable ASCII characters, space to tilde>`, scoped to the API key and
company.

- Required on every route above that writes and is new in plan 57 (the five `documents` routes,
  `po-links/relink`, `spo-links`, `spo-links/relink`): absent = `422 IDEMPOTENCY_KEY_REQUIRED`.
- Optional on `/po-links`, `/po-links/unlink`, `/spo-links/unlink` (absent = not idempotent, as in plan 55).
  Ignored on the two GET routes and on resume.
- Blank, longer than 128 or containing a non-printable or non-ASCII character: `422
  IDEMPOTENCY_KEY_INVALID`. The header is checked before the body.
- Same key, same body: the stored answer comes back (same `operationId` / `actionId`, same status), and
  nothing is sent to AutoCount.
- Same key, different route or body: `409 IDEMPOTENCY_CONFLICT`. Same key while that call still runs:
  `409 OPERATION_IN_PROGRESS`. Both are answer-shaped (section 4), `outcome: refused`.
- On `/po-links` a stored key keeps its first operation (split or whole row), even if the row changed since.
- Use a new key per user intent; reuse it only to retry the same intent after a timeout.

## 3. Bodies (camelCase on the wire, mapped to AutoCount field names by an allowlist)

Every body carries `companyCode` (the two GET routes take it as a query parameter). Calls on an existing
document take optional `docDate` (`YYYY-MM-DD`; AutoCount reads documents by date) and optional
`expectedLastModified` (the document version the user acted on; differs = `409 DOC_STALE`). A malformed
`docDate`, or one that is not a plain date, is `422 INVALID_REQUEST`. Without `docDate` the service uses
the date it staged or last read back; if it has none: `409 DOC_DATE_REQUIRED` (the other code of this kind
is `DOC_KIND_MISMATCH`, a PO key sent as an SPO or the reverse). A date that AutoCount has no document for:
`409 DOC_NOT_FOUND`. Unknown keys inside `header`, `line` and `lines[]` of a create or add line are
`422 INVALID_REQUEST` (`header.x is not a known field`).

### 3.1 Create

```json
{ "companyCode": "SRT",
  "header": { "docNo": "optional, absent = AutoCount numbers it", "docDate": "2026-11-04",
              "debtorCode": "301-B018", "displayTerm": "30 DAYS", "currencyCode": "MYR",
              "currencyRate": 1, "salesAgent": "optional", "ref": "optional", "description": "optional",
              "remark1": "optional", "remark2": "", "remark3": "", "remark4": "" },
  "lines": [ { "itemCode": "SRTUB6213-BI", "uom": "UNIT", "qty": 1, "unitPrice": 900.00,
               "discount": "optional, e.g. 5%", "location": "HQ", "description": "optional",
               "deliveryDate": "optional", "fromQuotation": { "docNo": "QT-...", "dtlKey": 12061 } } ] }
```

Header names accepted: `docNo`, `docDate`, `debtorCode`, `creditorCode`, `displayTerm`, `currencyCode`,
`currencyRate`, `salesAgent`, `purchaseAgent`, `ref`, `description`, `remark1`..`remark4`, `yourPONo`,
`invAddr1`..`invAddr4`, `deliverAddr1`..`deliverAddr4`, `attention`, `phone1`, `fax1`, `branchCode`,
`deliverContact`, `deliverPhone1`, `deliverFax1`, `shipVia`, `shipInfo`, `refDocNo`, `inclusiveTax`.
Line names accepted: `itemCode`, `uom`, `qty`, `unitPrice`, `discount`, `location`, `description`,
`deliveryDate`, `taxCode`, `desc2`, `projNo`, `focQty`, and `fromQuotation` (sales-order lines only).
`docDate` and `deliveryDate` are `YYYY-MM-DD`.

Required: header `docDate`, `currencyCode`, `currencyRate`, and `debtorCode` (quotations,
sales orders) or `creditorCode` (purchase orders, shipping purchase orders); `displayTerm` for purchase
orders and shipping purchase orders; at least one line; per line
`itemCode`, `uom`, `qty` above zero, `unitPrice` not negative, `location`. A miss is `422 FIELD_REQUIRED`
and the field is named in `message` (`FIELD_REQUIRED: debtorCode`; a missing line list is `details`).
A numeric field outside its rule (qty not above zero, negative price) is also `FIELD_REQUIRED`, naming it.

`displayTerm` on quotations and sales orders (SS-QTSO-DISPLAYTERM) is optional. Sent and not blank: it is
sent to AutoCount as is. Absent, `null` or blank: the service reads the debtor from the same AutoCount
book (`GET /debtorbypage`, matched on `AccNo`, trimmed and case-insensitive) and sends that debtor's own
`DisplayTerm` code. A debtor with no term, or not in the book, is `422 DEBTOR_TERM_MISSING` with the
debtor code in `message` (`debtor 300-1001 has no credit term in AutoCount; send displayTerm`); a failed
debtor read is `409 READ_FAILED`. Nothing is written on either. Every other refusal above wins first,
so a bad request never costs a debtor read.
The vendor's full row shape (project, FOC quantity, tax, transfer fields and the like) is filled by the
service; callers send only the names above. Without `docNo`, AutoCount numbers the document (`docNo` in the
answer).

A sales-order line made `fromQuotation` inherits unit price and location from the quotation row: the
answer is `done` with warning `QT_ROW_VALUES_INHERITED` and `message` `taken from the quotation row:
unitPrice, location` (the fields that differed, camelCase). If AutoCount did not keep the
link to the quotation row the answer is `done` with warning `QT_ROW_LINK_UNCONFIRMED`.

### 3.2 Edit

```json
{ "companyCode": "SRT", "docDate": "2026-11-04", "expectedLastModified": "2026-11-04T17:40:01.120",
  "header": { "ref": "new ref", "remark1": "..." },
  "lines": [ { "dtlKey": 12061, "qty": 2, "unitPrice": 850.00, "discount": "5%", "location": "HQ" } ] }
```

Header fields allowed: `ref`, `description`, `remark1`..`remark4`, `displayTerm`, `salesAgent`,
`purchaseAgent`, `yourPONo`, `invAddr1`..`invAddr4`, `deliverAddr1`..`deliverAddr4`. Line fields allowed
(each line needs an integer `dtlKey`): `qty`, `unitPrice`, `discount`, `location`, `description`,
`deliveryDate`. Anything else (including `itemCode`, `uom`, `docNo`, `docDate`, party codes): `422
FIELD_NOT_EDITABLE`, the name in `message`. `qty` not above zero (or over 8 decimal places): `422 QTY_INVALID`; negative `unitPrice`:
`422 PRICE_INVALID`. Both are checked before AutoCount is read. A change AutoCount accepts but does not apply: `502`, `outcome: mismatch`,
`errorCode: FIELD_IGNORED`, `message` `ignored: <names>` and the same names in `warnings`; the names are camelCase
(for example `ref`).
AutoCount copies `remark1` into `remark2`..`remark4` on an edit. When the edit sets `remark1`, a `remark2`..`remark4`
the caller did not send that reads back as the new `remark1` is that copy, not an ignored field (F13, db3 6 Nov). The previous `remark2`..`remark4` values are lost.
On a quotation or sales order, a `displayTerm` changed to blank (or a document that has none) takes the
debtor's own AutoCount term the same way as a create (`DEBTOR_TERM_MISSING` / `READ_FAILED` as there).

### 3.3 Add line, delete line, cancel

Add: `{ companyCode, docDate?, expectedLastModified?, line: { ...as a create line } }`. The new row number
is not a separate field: read it from `document.Details` (the row that was not there before).
Delete line (the row is the `{dtlKey}` in the path) and cancel: `{ companyCode, docDate?,
expectedLastModified? }`. Delete line sends one PUT with only that row, marked deleted; the read-back must
show the row gone and every other row unchanged (else `mismatch LINE_NOT_DELETED` / `COLLATERAL_CHANGE`).
The last remaining line may be deleted (the document then has no lines). A row AutoCount reports as
transferred onward (a sales order row taken into a purchase order, a quotation row taken into a sales
order) is refused `409 ROW_HAS_TRANSFERS` with AutoCount's text in `message`; SS's own receipt checks
(`ROW_RECEIVED`, `ROW_HAS_TRANSFERS` from the synced copy) still run first, with no request. Cancel asks
AutoCount to cancel the document by its number and reads it back: `Cancelled "T"` = `done`, otherwise
`mismatch CANCEL_IGNORED`. AutoCount refusing because the document was transferred onward =
`409 DOC_HAS_TRANSFERS`; because it is already void = `409 DOC_CANCELLED`; any other refusal =
`vendor_error VENDOR_REFUSED` with its text. Shipping purchase orders: both `409 VENDOR_UNSUPPORTED`.

### 3.4 Operations

All keys are integers (1..9223372036854775807).

- `po-links`: plan 55 body `{ companyCode, poDocKey, poDtlKey, soDocKey, soDtlKey, qty, docDate?, soDocDate?,
  expectedLastModified? }`. `soDocDate` (`YYYY-MM-DD`) is the date to read the sales order by when its date
  is not known to the service.
- `po-links/unlink`: `{ companyCode, poDocKey, poDtlKey, docDate?, expectedLastModified? }`.
- `spo-links/unlink`: `{ companyCode, spoDocKey, spoDtlKey, docDate?, expectedLastModified? }` (switched
  off: `409 VENDOR_UNSUPPORTED`, no request).
- `po-links/relink`: `{ companyCode, poDocKey, poDtlKey, soDocKey, soDtlKey, docDate?, soDocDate?,
  expectedLastModified? }` (`docDate` = the PO's date, `soDocDate` = the target sales order's date).
- `spo-links` and `spo-links/relink`: `{ companyCode, spoDocKey, spoDtlKey, poDocKey, poDtlKey, docDate?,
  poDocDate?, expectedLastModified? }` (`docDate` = the SPO's date, `poDocDate` = the target PO's date).

The plan 55 routes `po-links`, `po-links/unlink` and `spo-links/unlink` also take optional `docDate`
(the PO's or SPO's date; malformed = `422 INVALID_REQUEST`); `po-links` additionally takes `soDocDate`. A
split link on a PO whose date is not known is `409 DOC_DATE_REQUIRED`.

Whole row versus part of a row on `po-links`: the service reads the PO row fresh and compares the caller's
`qty` with the row's own quantity at that moment. Equal = the whole row: ONE PUT deletes the row and adds
it back linked (a new row number, listed in `replacedLines`). AutoCount puts a new linked row at HQ with
no delivery date, so a second write moves it to the target sales order row's location and puts the old
delivery date back; if that second write fails the link stands, the answer is `done` with warning
`LOCATION_NOT_MOVED`. `po-links/unlink` and `po-links/relink` are the same single replace PUT (an unlinked
row keeps its own location and date, so unlink needs no second write). AutoCount applies the PUT all or
nothing: a refusal there is `vendor_error VENDOR_REFUSED` with nothing changed and no second write.
Different = part of the row: the plan 55 split link, no delete, no `replacedLines`. Without an
`Idempotency-Key` the split case answers in the plain plan 55 shape (`actionId`, no `operationId`); with a
key it is an operation and answers with `operationId`. `qty` must be above zero with at most 8 decimal
places, else `422 QTY_INVALID`. A partly received PO row is cut to the received quantity and the open
remainder added as a new linked row (no `replacedLines` for that case).

## 4. Answer

```json
{ "operationId": "uuid (operations) or null", "actionId": "uuid (primitives) or null",
  "outcome": "done | refused | mismatch | pending_verification | vendor_error | recovered | needs_attention",
  "errorCode": "null or a code from section 5",
  "message": "short text, see below",
  "warnings": ["LOCATION_NOT_MOVED", "QT_ROW_LINK_UNCONFIRMED"],
  "docKey": 12060, "docNo": "FXT-1104q-QT1",
  "replacedLines": [ { "oldDtlKey": 12044, "newDtlKey": 12080 } ],
  "document": { "...": "the document as AutoCount read it back (done only; operations also on recovered)" } }
```

`message` is a string, empty when there is nothing to say. It carries AutoCount's own refusal text for
`VENDOR_REFUSED` (first line only, control characters removed, capped at 300 characters, and cut at the
first internal detail such as a URL, host, address, account, drive or network path, with ` [redacted]`
appended), the field name for `FIELD_REQUIRED` / `FIELD_NOT_EDITABLE` (camelCase), the ignored names for
`FIELD_IGNORED`, and the `taken from the quotation row` note. Show it to a person; do not parse it. Branch
on `errorCode` and `outcome`. A primitive answers `operationId: null`; an operation answers `actionId: null`.
The plan 55 routes answer the plan 55 shape, plus `operationId`, `message`, `warnings`, `docKey`, `docNo`
and `replacedLines` whenever an operation answered.

`replacedLines` lists every row whose number changed (a replace PUT, or a recovery). Anything the CRM
pinned to an old row moves to the new one; the same fact also arrives on the sink (section 6).

Status mapping:

| outcome | errorCode | HTTP |
|---|---|---|
| `done` | null or none of section 5 (warnings may be set) | 200 |
| `pending_verification` | (a transport or read-back code, section 5) | 202 |
| `refused` | `FIELD_REQUIRED`, `FIELD_NOT_EDITABLE`, `INVALID_PARAMS`, `DOCNO_REQUIRED`, `QTY_INVALID`, `PRICE_INVALID`, `DEBTOR_TERM_MISSING` | 422 |
| `refused` | `WRITE_DISABLED`, `WRITE_NOT_ALLOWED` | 403 |
| `refused` | any other code of section 5 | 409 |
| `vendor_error`, `mismatch`, `recovered`, `needs_attention` | (section 5) | 502 |

`recovered` = the intent failed, the original line is back under a new row number. `needs_attention` =
the line is missing in AutoCount; an alert mail was sent; use resume. `GET /write-operations/{id}` always
answers 200 with the stored answer, whatever its outcome. `POST .../resume`: a resume that ends `done` or
`recovered` answers 200 (the line is safe again); every other resume outcome maps as in the table (still
`needs_attention` = 502, a resume while the operation runs = `409 OPERATION_IN_PROGRESS`, an operation
that is neither `needs_attention` nor `pending_verification` returns its stored answer unchanged). Resume
takes `{ "companyCode": "SRT" }` and no other field; `Idempotency-Key` is not used. An unknown or other
company's operation id is `404 UNKNOWN_OPERATION` (flat body).

Errors outside the answer shape use the plan 55 flat body (`code`, `message`, `companyCode`, `entity`):
`401 INVALID_API_KEY`, `403 SCOPE_REQUIRED`, `403 SERVICE_NOT_ENABLED`, `403 COMPANY_NOT_ALLOWED`, `404
UNKNOWN_COMPANY`, `404 UNKNOWN_KIND`, `404 UNKNOWN_OPERATION`, `409 AMBIGUOUS_COMPANY`, `413
PAYLOAD_TOO_LARGE`, `422 INVALID_REQUEST` (missing `companyCode`, body not a JSON object, a key not an
integer, a wrong type, an unknown field name, a bad date), `422 IDEMPOTENCY_KEY_REQUIRED`, `422
IDEMPOTENCY_KEY_INVALID`, `429 TOO_MANY_REQUESTS`, `500` internal.

## 5. Codes

Refusals (`outcome: refused`, no AutoCount write was made). 403: `WRITE_DISABLED` (no active write
connection for the company), `WRITE_NOT_ALLOWED` (the connection is not the test book). 422: `FIELD_REQUIRED`,
`FIELD_NOT_EDITABLE`, `INVALID_PARAMS`, `DOCNO_REQUIRED`, `QTY_INVALID`, `PRICE_INVALID`, `DEBTOR_TERM_MISSING`
(quotation / sales order without `displayTerm` whose debtor has no AutoCount term, section 3.1). All the rest are 409:

- Switched off: `VENDOR_UNSUPPORTED` (every shipping purchase order write except edit: SPO create, add
  line, delete line, cancel, and the SPO link / unlink / relink operations; delete of a whole document;
  any switch a deployment turns off).
- Company: `WRITE_COMPANY_NOT_TEST` (the company now has SQL source data, so it is not a test book).
- Document: `DOC_BUSY`, `DOC_STALE`, `DOC_CANCELLED`, `DOC_NOT_FOUND`, `DOC_DATE_REQUIRED`,
  `DOC_KIND_MISMATCH`, `DOC_AMBIGUOUS`, `DOC_UNKNOWN` (the linked sales order row is not in the synced
  copy), `DOC_HAS_TRANSFERS` (also AutoCount refusing a cancel of a document transferred onward),
  `DEADLINE_EXCEEDED`, `READ_FAILED` (the document, or the debtor for a
  missing `displayTerm`, could not be read before writing), `DOC_KIND_UNKNOWN`.
- Row and quantity: `ROW_NOT_FOUND`, `ROW_HAS_TRANSFERS` (also AutoCount refusing to delete a row
  transferred onward), `QTY_BELOW_TRANSFERRED`, `ROW_RECEIVED`,
  `ROW_ON_SPO`, `ROW_ALREADY_LINKED`, `ROW_NOT_LINKED`, `ROW_HAS_OTHER_TRANSFER`, `NO_CHANGE`,
  `ITEM_MISMATCH`, `UOM_MISMATCH`, `QTY_ABOVE_OUTSTANDING`, `QTY_ABOVE_FREE`,
  `ROW_ALREADY_AT_LOCATION`, `SO_LOCATION_AMBIGUOUS`.
- Idempotency and operations: `IDEMPOTENCY_CONFLICT`, `OPERATION_IN_PROGRESS`, `UNKNOWN_OPERATION` (an
  operation name the service does not run; the 404 above is for an id), `OPERATION_NOT_APPLIED` (a resume found the line unchanged, nothing was written: `recovered` and
  200 for a whole-row operation, `refused` 409 for a part-row one).

Other outcomes:

- `pending_verification` (202): `WRITE_TIMEOUT`, `WRITE_CONNECT` (the request may or may not have
  landed), `ANSWER_UNPARSEABLE`, `READ_FAILED` (the read-back failed after a write), `DOC_AMBIGUOUS`,
  `INTERNAL_ERROR`, `DEADLINE_EXCEEDED` (an operation that ran past its overall deadline; for a
  primitive it stays a 409 refusal). For an operation, resume reads AutoCount and decides.
- `vendor_error` (502): `VENDOR_REFUSED` (AutoCount refused the write, for example a replace PUT whose
  new row it rejects, or a delete of a received line; nothing was applied; its text is in `message`),
  `VENDOR_ERROR` (a bare failure; no text is passed on; inside an operation it is `pending_verification`
  because the write may have landed).
- `mismatch` (502; the write was accepted, the read-back differs): `FIELD_IGNORED`, `ROW_MISMATCH`,
  `LINK_MISMATCH`, `ROWS_DROPPED`, `ROWS_UNEXPECTED`, `LINE_NOT_DELETED`, `DOC_NOT_DELETED`,
  `CANCEL_IGNORED`, `COLLATERAL_CHANGE`, `READBACK_MISMATCH` (plan 55 flows). Inside an operation a
  replace PUT that landed wrong is recovered from the snapshot (`recovered`, or `needs_attention` when the
  recovery fails too).
- `needs_attention` (502): `errorCode` is the code of the step that failed before the line went missing.
For a part-row operation the alert mail names the cut quantity and the remainder quantity.

Warnings (in `warnings`, on `done` or `recovered`; they do not fail the call): `LOCATION_NOT_MOVED` (the
link stands but AutoCount left the new row at its default location; use relocate),
`TRANSFER_STATE_UNKNOWN` (the received quantity could not be read, so AutoCount decided),
`QT_ROW_VALUES_INHERITED`, `QT_ROW_LINK_UNCONFIRMED` (section 3.1). On `done` of an operation the
`LOCATION_NOT_MOVED` warning is the only place the failed move shows (`errorCode` stays null).

## 6. Sink addition (Sorento contract 2.12, claimed here)

Purchase order, SPO and sales order lines pushed after a write may carry `replaces_line_ref`
(`{db}:{DocKey}:{DtlKey}` of the deleted row, at most 255 characters). The code constant is
`REPLACES_LINE_REF_CONTRACT_VERSION` = 2.12 (`ContractVersion`, compared as major and minor). Sent only
when the connection advertises contract >= 2.12 (Sorento ingest forbids unknown fields); absent or below =
the field is left out. Absent = no replacement. The CRM ingest moves its line state (reservations, link
claims, notes) from the old line to the new one. Renumber if another lane lands 2.12 first.

## 7. `GET /api/v1/autocount/write-capabilities?companyCode=`

Reads the switches now; no AutoCount call. Always `200`:

```json
{ "book": "db3",
  "capabilities": [ { "op": "create_doc", "kind": "quotations", "enabled": true, "reasonCode": null },
                    { "op": "delete_line", "kind": "shipping-purchase-orders", "enabled": false, "reasonCode": "VENDOR_UNSUPPORTED" } ] }
```

`book` is the AutoCount book (database) SS writes to for this company: the `<book>` of the write
connection's `/api/<book>` URL (`db3` in the test period; a live book later). It is `null` when there is
no usable write connection (every entry then reads `WRITE_DISABLED` or `WRITE_NOT_ALLOWED`; a book off the
write allowlist is never named). A `DocKey` is only unique inside its book: a consumer that keys documents
`{book}:{DocKey}` (e.g. `db1:12008`) must refuse an edit, add line, delete line or cancel when its book is
not this `book` (or `book` is `null`), else the `DocKey` would address an unrelated document in the book
SS writes to. Read it fresh before a write; it changes when the company's write connection changes.
A non-null `book` does not promise a write succeeds: write-time checks can still refuse it.

One entry per primitive (`create_doc`, `edit_doc`, `add_line`, `delete_line`, `cancel_doc`) for each
`kind` in `quotations`, `sales-orders`, `purchase-orders`, `shipping-purchase-orders` (the URL slugs), plus
one `split_link` on `purchase-orders` and one per operation (`link_row`, `unlink_row`, `relink_row` on
`purchase-orders`; `spo_link_row`, `spo_unlink_row`, `spo_relink_row` on `shipping-purchase-orders`).
`reasonCode` is null when enabled, else `WRITE_DISABLED` or `WRITE_NOT_ALLOWED` (no usable write
connection: every entry is off with that reason) or `VENDOR_UNSUPPORTED`. `split_link` (a part-row link on
`po-links`) is enabled when purchase-order edit and add line and the vendor's link on a new row are on.
The other operation entries are enabled only when delete line, add line and edit are all on for their kind
(the replace PUT deletes and adds in one write), and for `link_row` / `relink_row` / `unlink_row` the
vendor's whole-row link / unlink switch too: today the purchase-order operations read on and the
shipping-purchase-order operations off.
