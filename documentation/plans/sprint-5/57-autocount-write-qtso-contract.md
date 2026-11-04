# AutoCount write layer gateway (cross-repo contract, later CRM lanes)

Status: DRAFT, 2026-11-04, lane AC-WRITE-QTSO, plan `57-autocount-write-qtso.md` section 5.6, UAC
AC-57-60..63. Extends `55-autocount-write-link-contract.md`: auth (`X-API-Key` with the `write_back`
scope), company resolution (`companyCode`), the flat error body, `no-store` and the size cap are
unchanged and not repeated here. Pending the owner's alignment on
`57-autocount-alignment.html`; the guide-writer finalises this file after review.

## 1. What it adds

| Route | Level | Does |
|---|---|---|
| `POST /api/v1/autocount/documents/{kind}` | primitive | Create a document |
| `PATCH /api/v1/autocount/documents/{kind}/{docKey}` | primitive | Edit header fields and existing lines |
| `POST /api/v1/autocount/documents/{kind}/{docKey}/lines` | primitive | Add one line |
| `POST /api/v1/autocount/documents/{kind}/{docKey}/lines/{dtlKey}/delete` | primitive | Delete one line (switched off until AutoCount ships delete) |
| `POST /api/v1/autocount/documents/{kind}/{docKey}/cancel` | primitive | Cancel the document (switched off, AQ2) |
| `POST /api/v1/autocount/po-links` | operation | Unchanged body. Part of a row: split link (works). Whole row: delete + add (waits for delete) |
| `POST /api/v1/autocount/po-links/unlink` | operation | Unchanged body; now delete + add unlinked |
| `POST /api/v1/autocount/po-links/relink` | operation | New: move a PO row's link to another SO row |
| `POST /api/v1/autocount/spo-links` | operation | New: link an SPO row to a PO row |
| `POST /api/v1/autocount/spo-links/unlink` | operation | Unchanged body; now delete + add unlinked |
| `POST /api/v1/autocount/spo-links/relink` | operation | New: move an SPO row's link to another PO row |
| `GET /api/v1/autocount/write-operations/{operationId}?companyCode=` | read | One operation's state and answer |
| `POST /api/v1/autocount/write-operations/{operationId}/resume` | operation | Resume a `needs_attention` or `pending_verification` operation |
| `GET /api/v1/autocount/write-capabilities?companyCode=` | read | PROPOSED (alignment point ii): which operations are available and why not |

`{kind}`: `quotations`, `sales-orders`, `purchase-orders`, `shipping-purchase-orders`. There is no
route that deletes a document: cancel is the only way a document ends.

## 2. Idempotency

Header `Idempotency-Key: <1..128 printable chars>`, scoped to the API key and company.

- Required on every new route above; optional on the plan 55 routes (absent = not idempotent, as before).
- Same key, same body: the stored answer comes back (same `operationId` / `actionId`, same status), and
  nothing is sent to AutoCount.
- Same key, different route or body: `409 IDEMPOTENCY_CONFLICT`. Same key while that call still runs:
  `409 OPERATION_IN_PROGRESS`.
- Use a new key per user intent; reuse it only to retry the same intent after a timeout.

## 3. Bodies (camelCase on the wire, mapped to AutoCount field names by an allowlist)

Every body carries `companyCode`. Calls on an existing document also take optional `docDate`
(`YYYY-MM-DD`; AutoCount reads documents by date, AC-57-20) and optional `expectedLastModified` (the
document version the user acted on; differs = `409 DOC_STALE`).

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

`debtorCode` for quotations and sales orders, `creditorCode` for purchase orders. `fromQuotation` only
on sales-order lines. Missing required field: `422 FIELD_REQUIRED` with `field`.

### 3.2 Edit

```json
{ "companyCode": "SRT", "docDate": "2026-11-04", "expectedLastModified": "2026-11-04T17:40:01.120",
  "header": { "ref": "new ref", "remark1": "..." },
  "lines": [ { "dtlKey": 12061, "qty": 2, "unitPrice": 850.00, "discount": "5%", "location": "HQ" } ] }
```

Header fields allowed: `ref`, `description`, `remark1`..`remark4`, `displayTerm`, `salesAgent`, `yourPONo`,
invoice and delivery address fields. Line fields allowed: `qty`, `unitPrice`, `discount`, `location`,
`description`, `deliveryDate`. Anything else: `422 FIELD_NOT_EDITABLE`. A change AutoCount ignores:
`502` with `outcome: mismatch` naming the field.

### 3.3 Add line, delete line, cancel

Add: `{ companyCode, docDate?, expectedLastModified?, line: { ...as a create line } }`.
Delete line and cancel: `{ companyCode, docDate?, expectedLastModified? }`.

### 3.4 Operations

- `po-links`, `po-links/unlink`, `spo-links/unlink`: plan 55 bodies.
- `po-links/relink`: `{ companyCode, poDocKey, poDtlKey, soDocKey, soDtlKey, docDate?, expectedLastModified? }`.
- `spo-links` and `spo-links/relink`: `{ companyCode, spoDocKey, spoDtlKey, poDocKey, poDtlKey, docDate?, expectedLastModified? }`.

## 4. Answer

```json
{ "operationId": "uuid (operations) or null", "actionId": "uuid (primitives) or null",
  "outcome": "done | refused | mismatch | pending_verification | vendor_error | recovered | needs_attention",
  "errorCode": "null or a code from section 5",
  "warnings": ["LOCATION_NOT_MOVED", "QT_ROW_LINK_UNCONFIRMED"],
  "docKey": 12060, "docNo": "FXT-1104q-QT1",
  "replacedLines": [ { "oldDtlKey": 12044, "newDtlKey": 12080 } ],
  "document": { "...": "the document as AutoCount read it back" } }
```

`replacedLines` lists every row whose number changed (delete + add, or a recovery). Anything the CRM
pinned to an old row moves to the new one; the same fact also arrives on the sink (section 6).

Status: `200` done; `202` pending_verification; `403` / `409` refused (section 5); `502`
vendor_error, mismatch, recovered (the intent failed, the original line is back under a new row
number), needs_attention (the line is missing in AutoCount; alert mail sent; use resume).
`GET /write-operations/{id}` always answers 200 with the stored answer. A resume that ends `done` or
`recovered` answers 200 (the line is safe again); other resume outcomes map as above.

## 5. Refusal codes (no AutoCount write was made)

`VENDOR_UNSUPPORTED` (switched off: delete line, cancel, whole-row link, unlink, relink, SPO create / add
line), `WRITE_DISABLED`, `WRITE_NOT_ALLOWED`, `DOC_BUSY`, `DOC_STALE`, `DOC_CANCELLED`,
`DOC_HAS_TRANSFERS`, `ROW_HAS_TRANSFERS`, `QTY_BELOW_TRANSFERRED`, `ROW_RECEIVED`,
`ROW_ON_SPO`, `ROW_ALREADY_LINKED`, `ROW_NOT_LINKED`, `NO_CHANGE`,
`ITEM_MISMATCH`, `UOM_MISMATCH`, `QTY_ABOVE_OUTSTANDING`, `ROW_NOT_FOUND`, `DOC_NOT_FOUND`,
`DOC_DATE_REQUIRED`, `DOC_KIND_MISMATCH`, `DOCNO_REQUIRED`, `FIELD_REQUIRED`, `FIELD_NOT_EDITABLE`,
`IDEMPOTENCY_CONFLICT`, `OPERATION_IN_PROGRESS`.

AutoCount refused the write (for example a delete of a received line): `502`, outcome `vendor_error`,
`errorCode: VENDOR_REFUSED`, AutoCount's message in `message`. Warning `TRANSFER_STATE_UNKNOWN`: the
received qty could not be read, so AutoCount decided.

## 6. Sink addition (Sorento contract 2.12, claimed here)

Purchase order, SPO and sales order lines pushed after a write may carry `replaces_line_ref`
(`{db}:{DocKey}:{DtlKey}` of the deleted row). Sent only when the connection advertises contract
>= 2.12 (Sorento ingest forbids unknown fields). Absent = no replacement. The CRM ingest moves its
line state (reservations, link claims, notes) from the old line to the new one. Renumber if another
lane lands 2.12 first.
