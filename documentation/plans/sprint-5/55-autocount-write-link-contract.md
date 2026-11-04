# AutoCount write-link gateway (cross-repo contract, Sorento CRM lane)

Status: DRAFT for the CRM lane, 2026-11-04. Shared-service lane AC-WRITE-LINK, branch
`crew/ac-write-link`, plan `55-autocount-write-link.md` section 6b, UAC AC-55-40..45. This file is the
contract of record for the three write routes. Auth, company identity, the flat error body and
`no-store` are the pull gateway's (`16-autocount-do-pull-snapshot-contract.md` and the contract it
inherits from); this file restates only what a write caller needs.

## 1. What it is

Three routes on the existing public gateway (`/api/v1/autocount/*`) that change the link between a
purchase order row and a sales order row in the customer's AutoCount book:

| Route | Does |
|---|---|
| `POST /api/v1/autocount/po-links` | Link a quantity of one PO row to one SO row (in place, or by splitting the PO row) |
| `POST /api/v1/autocount/po-links/unlink` | Clear the SO link of one PO row |
| `POST /api/v1/autocount/spo-links/unlink` | Clear the PO link of one shipping purchase order (SPO) row |

There is no combined relink route. To move a link: unlink, then link, as two calls.

**Writes currently reach only the AutoCount test book.** A company whose write connection is not
the test book, or has no write connection at all, answers `403 WRITE_DISABLED` or
`403 WRITE_NOT_ALLOWED` (section 5). No live book is written until the shared-service side opens
one; the CRM must treat these two codes as "feature not available for this company", not as a
fault.

## 2. Auth

`X-API-Key: <key>`, exactly as the pull routes. The key must carry the **`write_back` scope**.

- A key without it answers `403 SCOPE_REQUIRED` before anything else runs; no AutoCount call is made.
  All existing keys are `["pull"]`; a pull key never writes.
- A key gets the scope when it is issued: the operator key-issue call
  (`POST /autocount/pull/keys`, bearer session, not the gateway) takes
  `"scopes": ["pull", "write_back"]` (allowed values `pull`, `write_back`; absent = `["pull"]`).
  Issuing a key with `write_back` needs the issuing user to hold `autocount.companies.manage` on top
  of `autocount.pull.manage`; without it the issue call answers `403`. The scope cannot be added
  to an existing key: issue a new one and revoke the old.
- The read routes (`POST /snapshots`, `GET /snapshots/{id}`, `GET /snapshots/{id}/rows`) need the
  **`pull` scope** the same way: a key without it answers `403 SCOPE_REQUIRED` before any other answer.
  A `write_back`-only key does not read. A key can carry both.
- Unknown, malformed or revoked key: `401 INVALID_API_KEY`. Module not enabled or tenant suspended:
  `403 SERVICE_NOT_ENABLED`. Throttled: `429 TOO_MANY_REQUESTS` with `Retry-After`.

## 3. Company resolution

Every body carries `companyCode` (string, required; trimmed, case-insensitive, within the key's
tenant). Missing or blank: `422 INVALID_REQUEST`. Resolution is the pull gateway's:

| Status | code | Meaning |
|---|---|---|
| 404 | `UNKNOWN_COMPANY` | No company with that code for this key |
| 409 | `AMBIGUOUS_COMPANY` | More than one company in the tenant shares that code |
| 403 | `COMPANY_NOT_ALLOWED` | The company is not in this key's allowed set |

Every document key is read and written only through the resolved company; a key from another
company or tenant is never reachable.

## 4. Requests and responses

All bodies are JSON objects, camelCase. Body over the size cap: `413 PAYLOAD_TOO_LARGE`. Not a JSON
object, or a field of the wrong type: `422 INVALID_REQUEST` (flat error, section 6). The routes are
not idempotent: do not blind-retry a call that ended `pending_verification`.

### 4.1 `POST /api/v1/autocount/po-links`

```json
{ "companyCode": "SRT",
  "poDocKey": 12008, "poDtlKey": 12009,
  "soDocKey": 11988, "soDtlKey": 11990,
  "qty": 1,
  "expectedLastModified": "2026-11-03T09:14:22" }
```

| Field | Type | Rule |
|---|---|---|
| `companyCode` | string | required |
| `poDocKey`, `poDtlKey` | integer | the PO document and the PO row (AutoCount `DocKey`, `DtlKey`). Every key field is an integer from 1 to 9223372036854775807; anything else is `422 INVALID_REQUEST` |
| `soDocKey`, `soDtlKey` | integer | the SO document and the SO row to link to |
| `qty` | number | quantity to link; above zero and at most 1,000,000,000, with at most 8 decimal places (a value the server would have to round is refused `QTY_INVALID`, never rewritten), at most the PO row qty, at most the SO row outstanding. Sent as a JSON number; the server reads it as an exact decimal, never a binary float, so `3.3` stays `3.3`. Send decimals as plain numbers, not strings |
| `expectedLastModified` | string, optional | the `LastModified` of the PO as the CRM last read it; when given and the PO has changed since, the call is refused `DOC_STALE` |

`qty` must be BELOW the PO row qty: the PO row keeps `rowQty - qty` unlinked and a NEW PO row (new
`DtlKey`) carries the linked `qty` (two writes, section 5). A `qty` equal to the PO row qty (a whole
row) is not linked in place: AutoCount does not apply an edit of an existing row, so the call is
refused `409 VENDOR_UNSUPPORTED` after one document read. The location comes from the SO row; the
caller does not send one.

### 4.2 `POST /api/v1/autocount/po-links/unlink`

```json
{ "companyCode": "SRT", "poDocKey": 12008, "poDtlKey": 12017, "expectedLastModified": null }
```

`poDocKey`, `poDtlKey` integer, required; `expectedLastModified` optional as above. The row keeps
its own qty and location.

### 4.3 `POST /api/v1/autocount/spo-links/unlink`

```json
{ "companyCode": "SRT", "spoDocKey": 46179001, "spoDtlKey": 46179075 }
```

`spoDocKey`, `spoDtlKey` integer, required (an SPO is a PO document marked as shipping); `expectedLastModified`
optional. Clears the SPO row's link to its PO row.

### 4.4 `POST /api/v1/autocount/po-links/relocate`

```json
{ "companyCode": "SRT", "poDocKey": 12008, "poDtlKey": 12050, "expectedLastModified": "2026-11-05T09:00:03" }
```

`poDocKey`, `poDtlKey` integer, required; `expectedLastModified` optional. Moves one LINKED PO row to
the location of the SO row it is linked to; the caller never sends a location (the server takes it
from its synced copy of the SO). Refused `ROW_NOT_LINKED` when the row has no link and
`ROW_ALREADY_AT_LOCATION` when it is already there. Same auth, company resolution, stale, busy and
write guards as a link. Use it when a link ended `LOCATION_NOT_MOVED`.

### 4.5 Response (all four routes)

```json
{ "actionId": "c1a0...", "outcome": "done", "errorCode": null, "document": { "...": "..." } }
```

| Field | Type | Meaning |
|---|---|---|
| `actionId` | string or null | The id of the audit record for this call; quote it to support. Null only when the company could not be resolved to a write action |
| `outcome` | string | One of section 5 |
| `errorCode` | string or null | Null on `done`; else a code from section 5 |
| `document` | object or null | On `done` only: the whole document as AutoCount reads back after the write (PO, or SPO), in the vendor's field names (`DocKey`, `DocNo`, `LastModified`, `Details[]` with `DtlKey`, `ItemCode`, `Location`, `UOM`, `Qty`, `FromSODtlKey`, `FromDocDtlKey`, ...). Null otherwise |

The same JSON is returned for every outcome, with only the HTTP status differing. Responses are
`Cache-Control: no-store`.

## 5. Outcome, status and error codes

| outcome | HTTP | errorCode | Meaning |
|---|---|---|---|
| `done` | 200 | null, or `LOCATION_NOT_MOVED` | Written and verified: every sent row read back as sent and every other row unchanged |
| `pending_verification` | 202 | `WRITE_TIMEOUT`, `WRITE_CONNECT`, `DOC_NOT_FOUND`, `DOC_AMBIGUOUS`, `READ_FAILED`, `INTERNAL_ERROR`, `DEADLINE_EXCEEDED` | The write may or may not have happened; the server could not confirm it |
| `refused` | 403 | `WRITE_DISABLED` | This company has no write connection, or the company or its write connection is inactive |
| `refused` | 403 | `WRITE_NOT_ALLOWED` | The company's write target is not an allowed book |
| `refused` | 409 | any code below | Refused before anything was written |
| `mismatch` | 502 | `READBACK_MISMATCH` | AutoCount accepted the write but the document read back differently from what was sent |
| `vendor_error` | 502 | `VENDOR_ERROR` | AutoCount answered the write with an error; nothing is assumed written |

`refused` 409 codes (nothing was changed in AutoCount):

| errorCode | Meaning | CRM action |
|---|---|---|
| `DOC_BUSY` | Another write on the same document is in flight, or ended `pending_verification` less than 10 minutes ago | Wait and retry; after 10 minutes an unfinished action no longer blocks |
| `DOC_UNKNOWN` | The document is not in the synced copy, so its date is unknown | Run or wait for the doc sync, then retry |
| `DOC_STALE` | `expectedLastModified` no longer matches: the document changed in AutoCount | Refresh the document, re-check the row, retry with the new `LastModified` |
| `DOC_NOT_FOUND` / `DOC_AMBIGUOUS` / `READ_FAILED` | (when raised before the write) the document could not be read exactly once | Retry later; if it persists, report with `actionId` |
| `VENDOR_UNSUPPORTED` | AutoCount does not apply this edit yet: unlink, SPO row unlink, and a link of a WHOLE PO row (quantity equal to the row). Refused before anything is sent | Show 'not supported by AutoCount yet'; offer a split link (quantity below the row) instead |
| `ROW_HAS_OTHER_TRANSFER` | Unlink or link: the PO row was transferred from another document type (not an SO) | Nothing to do here; handle it in AutoCount |
| `SO_LOCATION_AMBIGUOUS` | Relocate: two equally recent synced copies of the SO disagree on the row's location | Re-run the doc sync, then retry |
| `ROW_ALREADY_AT_LOCATION` | Relocate: the row is already at its SO row's location | Nothing to do |
| `DOC_KIND_MISMATCH` | A PO key sent to the SPO route, or an SPO key sent to a PO route | Use the right route |
| `DOC_CANCELLED` | The PO, SPO or SO is cancelled | Show it as cancelled; no action |
| `ROW_NOT_FOUND` | No row with that `DtlKey` on the document | Refresh and re-pick |
| `ROW_ALREADY_LINKED` | The PO row already links to an SO row | Unlink first, then link |
| `ROW_NOT_LINKED` | The row to unlink has no link | Treat as already unlinked; refresh |
| `ROW_ON_SPO` | An active SPO row points at this PO row | Unlink the SPO row first (`/spo-links/unlink`), then retry |
| `ITEM_MISMATCH` | PO row and SO row have different items | Do not offer this pair |
| `UOM_MISMATCH` | Different units of measure | Do not offer this pair |
| `QTY_INVALID` | `qty` is zero or negative, above 1,000,000,000, or has more than 8 decimal places (checked before AutoCount is read) | Fix the input |
| `QTY_ABOVE_FREE` | `qty` is above the PO row qty | Lower `qty` |
| `QTY_ABOVE_OUTSTANDING` | `qty` is above what is still unlinked on the SO row | Lower `qty`, or unlink another PO row first |

**Split link is two writes.** Linking a quantity below the PO row edits the row down and adds a new
linked row. AutoCount places that new row at its default location, so the server then sends a second
write that moves only the new row to the SO row's location, and reads the document back. The call
answers `done` once the link is verified. If the second write fails or the location did not move, it
still answers `done` (200) with `errorCode` `LOCATION_NOT_MOVED`: the link stands, the row sits at the
default location, and the CRM should offer "Move location" (the relocate route above). The second
write is never retried.

`DEADLINE_EXCEEDED`: an action has an overall time budget (under 5 minutes). Past it before any write was
sent the call is refused `409 DEADLINE_EXCEEDED` (nothing changed); past it after a write was sent it
answers `202 pending_verification` with the same code, and no further call is made. `done` may
carry `errorCode` `LOCATION_NOT_MOVED` (section above).

`INTERNAL_ERROR` (202) means an unexpected server fault after the action started: the write may or
may not have happened, so treat it like any other `pending_verification` and check the document.

Note `DOC_NOT_FOUND`, `DOC_AMBIGUOUS` and `READ_FAILED` appear in both places by design: before
the write they come back as `refused` 409; after the write (the verification read) as
`pending_verification` 202.

### What the CRM shows and does per outcome

- **`done`**: show success; replace the stored document with `document`; the shared-service side
  has already staged it and pushed it once, so no extra pull is needed.
- **`pending_verification`**: show "link status unconfirmed". **Do not retry the link and do not
  send it again.** Wait, re-read the PO (a fresh pull, or the next doc sync) and decide from what
  AutoCount now holds. A repeat could double-link or split a second row.
- **`mismatch`**: show an error and "needs review"; do not retry. Re-read the document; the
  support team uses `actionId`.
- **`vendor_error`**: show the failure; nothing was assumed written, a retry is safe after the
  user re-checks the inputs.
- **`refused` 409**: show the plain reason from the table and the CRM action; nothing changed.
- **`refused` 403** (`WRITE_DISABLED`, `WRITE_NOT_ALLOWED`): hide or disable the link action for
  that company.

## 6. Errors outside the outcome body

Auth, scope, company and parse failures use the pull gateway's flat body, no `outcome`:

```json
{ "code": "SCOPE_REQUIRED", "message": "This key is not allowed to write.",
  "companyCode": "SRT", "entity": null }
```

| Status | code | Meaning |
|---|---|---|
| 401 | `INVALID_API_KEY` | Missing, malformed, unknown or revoked key |
| 403 | `SCOPE_REQUIRED` | Key lacks `write_back` (write routes) or `pull` (read routes) |
| 403 | `SERVICE_NOT_ENABLED` | Module not enabled for the tenant |
| 403 | `COMPANY_NOT_ALLOWED` | Section 3 |
| 404 | `UNKNOWN_COMPANY` | Section 3 |
| 409 | `AMBIGUOUS_COMPANY` | Section 3 |
| 413 | `PAYLOAD_TOO_LARGE` | Body over the cap |
| 422 | `INVALID_REQUEST` | Missing `companyCode`, not a JSON object, a key not an integer in 1..9223372036854775807, `qty` not a number |
| 429 | `TOO_MANY_REQUESTS` | `Retry-After` seconds |
| 500 | (internal error body) | Unexpected failure; no write is assumed |

Tell the two 403 shapes apart by the body: a flat body has `code`; a write refusal has `outcome`.

## 7. Rules for the caller

- **One action per document at a time.** The server refuses a second write on a document while one
  is open (`DOC_BUSY`). The CRM should serialise its own calls per PO (and per SPO) and wait for each
  answer before the next. Linking two rows of one PO means two sequential calls.
- **Quantities are exact decimals.** Send `qty` as a JSON number with as many places as the item
  needs; do not round or convert through a float on your side.
- **Send `expectedLastModified`** whenever the CRM shows a document the user has been looking at,
  so an edit made in AutoCount in the meantime is caught (`DOC_STALE`) instead of overwritten.
- **Relink** = `po-links/unlink`, then `po-links`, as two calls; if the second fails the first stands.
- **Rows on a shipping PO:** a PO row that an SPO row points at cannot be linked or unlinked until
  that SPO row is unlinked (`ROW_ON_SPO`).

## 8. Examples (test book, real document numbers)

PO `202602-S0007` (DocKey 12008) has row 12009 (item `SRTKS7090`, qty 1) and row 12017 (item
`SRTKT38SS`, qty 10). SO `SO389293` (DocKey 11988) has row 11990 (item `SRTKS7090`, qty 10) and
row 11989 (item `SRTKT38SS`).

Link the whole 12009 row to SO row 11990 (qty equals the row qty):

```json
POST /api/v1/autocount/po-links
{ "companyCode": "SRT", "poDocKey": 12008, "poDtlKey": 12009,
  "soDocKey": 11988, "soDtlKey": 11990, "qty": 1 }
```
```json
409 { "actionId": "c1a0...", "outcome": "refused", "errorCode": "VENDOR_UNSUPPORTED", "document": null }
```

Link 4 of the 10 on row 12017 (split): row 12017 keeps 6 unlinked, a new row carries 4 linked to 11989.

```json
POST /api/v1/autocount/po-links
{ "companyCode": "SRT", "poDocKey": 12008, "poDtlKey": 12017,
  "soDocKey": 11988, "soDtlKey": 11989, "qty": 4 }
```

Wrong pair (row 12017 is `SRTKT38SS`, SO row 11990 is `SRTKS7090`):

```json
409 { "actionId": "9b2e...", "outcome": "refused", "errorCode": "ITEM_MISMATCH", "document": null }
```

Stale edit:

```json
409 { "actionId": "4d7c...", "outcome": "refused", "errorCode": "DOC_STALE", "document": null }
```

Unconfirmed write (timeout after sending):

```json
202 { "actionId": "7f31...", "outcome": "pending_verification", "errorCode": "WRITE_TIMEOUT", "document": null }
```

Row still on a shipping PO:

```json
409 { "actionId": "e08a...", "outcome": "refused", "errorCode": "ROW_ON_SPO", "document": null }
```

Pull-only key:

```json
403 { "code": "SCOPE_REQUIRED", "message": "This key is not allowed to write.", "companyCode": "SRT", "entity": null }
```
