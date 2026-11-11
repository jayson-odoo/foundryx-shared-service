# AutoCount write-link gateway (cross-repo contract, Sorento CRM lane)

Status: DRAFT for the CRM lane, 2026-11-04. Shared-service lane AC-WRITE-LINK, branch
`crew/ac-write-link`, plan `55-autocount-write-link.md` section 6b, UAC AC-55-40..45. This file is the
contract of record for the three write routes. Auth, company identity, the flat error body and
`no-store` are the pull gateway's (`16-autocount-do-pull-snapshot-contract.md` and the contract it
inherits from); this file restates only what a write caller needs.

2026-11-10 (plan 61, `61-autocount-write-v2.md`): a whole-row link and `po-links/unlink` are done (no
longer `VENDOR_UNSUPPORTED`): each is ONE PUT that deletes the row and adds its replacement, and a
whole-row link then moves the new row to the SO row's location (sections 4.1, 4.2). `spo-links/unlink`
stays `VENDOR_UNSUPPORTED`. Bodies, statuses and `replacedLines` are unchanged.

2026-11-11 (plan 62, `62-autocount-po-link-batch.md`): new `POST /api/v1/autocount/po-links/batch` links one PO
row to 1 to 20 SO rows in ONE call (section 4.1a); `po-links/unlink` joins the freed quantity to a matching
free PO row instead of adding a new one when it can (section 4.2); the retry rule of every operation route
changed: a key whose first call provably changed nothing is released for a resend (section 4.0). Existing
bodies and statuses are unchanged.

## 1. What it is

Four routes on the existing public gateway (`/api/v1/autocount/*`) that change the link between a
purchase order row and a sales order row in the customer's AutoCount book:

| Route | Does |
|---|---|
| `POST /api/v1/autocount/po-links` | Link a quantity of one PO row to one SO row (in place, or by splitting the PO row) |
| `POST /api/v1/autocount/po-links/batch` | Link one PO row to 1 to 20 SO rows in one call; a bad line is skipped and named, the rest are linked (section 4.1a) |
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
object, or a field of the wrong type: `422 INVALID_REQUEST` (flat error, section 6).

### 4.0 Idempotency and retry (plan 62, every operation route and every document primitive)

`Idempotency-Key` is REQUIRED on `po-links/batch` (missing: `422 IDEMPOTENCY_KEY_REQUIRED`; over 128 or unprintable characters: `422 IDEMPOTENCY_KEY_INVALID`) and as stated by plan 57
on the other operation routes. The key names one intended change; the stored first outcome decides what a
resend does:

| Stored outcome of the first call | A resend with the same key |
|---|---|
| `refused` (any code), or `vendor_error` with `errorCode` `VENDOR_REFUSED` (AutoCount itself said no) | Nothing reached AutoCount, so the key is released: the resend runs fresh, with the same or a corrected body |
| `recovered` with `errorCode` `OPERATION_NOT_APPLIED` (a resume found the write never landed) | The key is released, like the first row: the resend runs fresh |
| `pending_verification` and the same body | Reconciles: the server re-reads the document. If the first call landed, it is finished and answered (`done`); if it provably never landed, the key is released and the resend runs fresh. Never a second write |
| `done` | Locked: the stored answer is replayed (same `operationId`), nothing is written again |
| `mismatch`, any other `recovered`, `needs_attention`, or any other `vendor_error` (no `VENDOR_REFUSED`; the write may have landed) | Locked: the stored answer is replayed |
| any stored outcome, but a DIFFERENT body or route | `409 IDEMPOTENCY_CONFLICT` (`outcome` `refused`) unless the stored outcome released the key (first two rows) |
| first call still running | `409 OPERATION_IN_PROGRESS` |

A call that ended `pending_verification` is still never blind-resent with a NEW key.

`POST /write-operations/{id}/resume` only exists for the link, unlink, relink and batch operations. On a document
primitive (a create) it answers `409 OPERATION_NOT_RESUMABLE` and changes nothing; resend the create with the same key instead.

Creating a document (`POST /documents/{kind}`) follows the same table with one difference, because a failed
create may still have saved the document. A create AutoCount refused before saving (credit limit, unknown item,
unknown debtor) or SS refused is released at once. Any other failure or an unfinished create is not re-run
blindly: SS first looks the document up in AutoCount (by `docNo` when the body names one, otherwise among the
documents created within ten minutes before or after the first attempt, for the same debtor or creditor, with the same
lines; the ten minutes allow for AutoCount's server clock being off ours). A document that another completed create
of the same company already owns (created within that window) is never taken. One match:
the call is `done` with that document and the key is locked. No match: the key is released and the create runs
once. More than one match: `needs_attention` (`CREATE_AMBIGUOUS`), locked, nothing is created.

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
row) is never linked in place (AutoCount does not change the link of an existing row): one PUT deletes
the row and adds a new linked row with the same values (a new `DtlKey`, listed in `replacedLines` when
the operation layer answers), then a second write puts the new row at the SO row's location and back on
its unit price and delivery date (AutoCount forces HQ, sets the unit price to 0 and clears the date on a
new linked row; db3 10-11 Nov, plan 61 F5). The location comes
from the SO row; the caller does not send one.

### 4.1a `POST /api/v1/autocount/po-links/batch`

Links one PO row to several SO rows (plan 62). Header `Idempotency-Key` required (section 4.0).

```json
{ "companyCode": "SRT", "poDocKey": 12008, "poDtlKey": 12017, "docDate": "2026-11-02",
  "expectedLastModified": "2026-11-03T09:14:22",
  "links": [ { "soDocKey": 11988, "soDtlKey": 11989, "qty": 4, "soDocDate": "2026-10-30" },
             { "soDocKey": 12101, "soDtlKey": 12102, "qty": 3 } ] }
```

| Field | Type | Rule |
|---|---|---|
| `companyCode`, `poDocKey`, `poDtlKey`, `expectedLastModified` | | as section 4.1 |
| `docDate` | string, optional | `YYYY-MM-DD`; the PO's document date, a hint for the read |
| `links` | array, required | 1 to 20 entries, each an object. Not an array, empty, over 20, an entry not an object, an SO row (`soDtlKey`) listed twice, or a `qty` that is not a JSON number: `422 INVALID_REQUEST` (nothing is stored, the key stays free) |
| `links[].soDocKey`, `links[].soDtlKey` | integer | as `soDocKey`, `soDtlKey` in section 4.1 (a missing or non-integer key: `422 INVALID_REQUEST`) |
| `links[].qty` | number | a JSON number (anything else: `422 INVALID_REQUEST`); a number that is zero, negative, above 1,000,000,000 or has more than 8 decimal places skips that line (`QTY_INVALID`) |
| `links[].soDocDate` | string, optional | `YYYY-MM-DD`; the SO's date, a hint for the read |

**One bad line never fails the batch** (owner rule, 12 Nov 2026). The checks that concern the PO row refuse the
whole request and nothing is written: `ROW_ALREADY_LINKED`, `ROW_ON_SPO`, `ROW_HAS_OTHER_TRANSFER`, `ROW_RECEIVED`,
`DOC_CANCELLED` (the PO), `ROW_NOT_FOUND` (the PO row), `DOC_STALE`, `DOC_BUSY`, `VENDOR_UNSUPPORTED`. Every other
check is made line by line, in request order, and a line that fails is skipped: it is not sent, the other lines are
linked. The reasons are `ROW_NOT_FOUND` (the SO row), `ITEM_MISMATCH`, `UOM_MISMATCH`, `DOC_CANCELLED` (its sales
order), `QTY_ABOVE_OUTSTANDING`, `QTY_INVALID`, and `QTY_ABOVE_FREE` (the running total of the lines linked so
far plus this one would pass the PO row quantity; a later, smaller line that still fits is linked). The answer
names every skipped line in `skipped`: `[{ "soDocKey": 11988, "soDtlKey": 11989, "code": "QTY_ABOVE_OUTSTANDING" }]`,
`[]` when none. `skipped` is on every answer of this route that reads the body (done, refused, vendor_error, pending, the replay and the request-shape 422s, which carry `links: []`, `skipped: []`, `freeLine: null`). Errors raised before the body is read (401, 403, `IDEMPOTENCY_KEY_REQUIRED`, `IDEMPOTENCY_KEY_INVALID`) are the gateway's flat error and carry none of the three. A reconcile that settles as needs_attention or recovered answers `skipped: []`. When every line is
skipped nothing is written and the answer is `refused` with `errorCode` `ALL_LINKS_SKIPPED` (HTTP 409) and all the
lines in `skipped`; the key is released, so a corrected resend under the same key runs. AutoCount itself refusing
the write (`vendor_error`, `VENDOR_REFUSED`) is still the whole request: nothing is linked, `skipped` lists only
the lines skipped before the write, and the key is released.

**Two writes.** The first write is ONE edit of the PO: the PO row is kept with the quantity
that is left (or removed when the links take all of it) and one new linked row is added per linked line. AutoCount
accepts or rejects that edit as a whole, so either every valid line is linked or none is. Each new row arrives at
the default location (HQ), unit price 0 and no delivery date; a second write, only if a read-back shows
that, puts all the new rows at their SO row's location and back on the PO row's unit price and delivery
date, in one edit. If that second write does not land, the answer is still `done` and `warnings` carries
`LOCATION_NOT_MOVED` (and `ROW_VALUES_NOT_KEPT` when unit price or delivery date were involved); the links
stand. Use `po-links/relocate` for a row left at the default location.

Answer (HTTP 200, `outcome` `done`):

```json
{ "operationId": "5b0c...", "actionId": null, "outcome": "done", "errorCode": null, "message": "",
  "warnings": [], "docKey": 12008, "docNo": "202602-S0007", "replacedLines": [],
  "links": [ { "soDocKey": 11988, "soDtlKey": 11989, "qty": "4", "poDtlKey": 12031 },
             { "soDocKey": 12101, "soDtlKey": 12102, "qty": "3", "poDtlKey": 12032 } ],
  "skipped": [],
  "freeLine": { "poDtlKey": 12017, "qty": "3" },
  "document": { "...": "the PO as read back" } }
```

`links[]` has one entry per linked line (a skipped line has none): the `poDtlKey` of the new PO row that carries that link. `qty`
there, and in `freeLine`, is a decimal STRING. `freeLine` is the PO row that stays with the unlinked
remainder (`poDtlKey` is the original `poDtlKey`), or `null` when the links took the whole row. The other
fields are those of section 4.5, with `actionId` null on this route. Other outcomes (`pending_verification`
202, `mismatch` 502, `vendor_error` 502, `refused`) carry the same body without `links` content
(`links` `[]`, `freeLine` null). A `pending_verification` is reconciled by resending with the same key and
the same body (section 4.0).

### 4.2 `POST /api/v1/autocount/po-links/unlink`

```json
{ "companyCode": "SRT", "poDocKey": 12008, "poDtlKey": 12017, "expectedLastModified": null }
```

`poDocKey`, `poDtlKey` integer, required; `expectedLastModified` optional as above. One PUT deletes the
linked row and adds a normal row with the same item, qty, unit price, UOM, location and delivery date
(a new `DtlKey`, in `replacedLines`): AutoCount never clears a link in place.

**Merge into a free row (plan 62).** When the PO has another row that is free (not linked, nothing received,
no SPO row pointing at it, not transferred from another document) and equals the unlinked row in item,
unit of measure, location, unit price and delivery date, the PUT deletes the linked row and raises that free
row's quantity by the freed quantity instead of adding a new row; the first such row in row order is used.
No location move follows. The answer then has `replacedLines` `[{"oldDtlKey": <the unlinked row>,
"newDtlKey": <the free row that took the quantity>}]`: `newDtlKey` is the EXISTING free row's `DtlKey`, not a
new one. With no matching free row, or a free row with a known received quantity above zero, the behaviour above
applies unchanged (a new row). A received quantity AutoCount does not expose (unknown) does not stop the merge. No request field and no new answer field: read `replacedLines`.

### 4.3 `POST /api/v1/autocount/spo-links/unlink`

```json
{ "companyCode": "SRT", "spoDocKey": 46179001, "spoDtlKey": 46179075 }
```

`spoDocKey`, `spoDtlKey` integer, required (an SPO is a PO document marked as shipping); `expectedLastModified`
optional. Would clear the SPO row's link to its PO row; switched off (`409 VENDOR_UNSUPPORTED`, nothing
sent): no SPO write is proven on the test book.

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

Plan 57 (`57-autocount-write-qtso-contract.md`) rewired `po-links`, `po-links/unlink` and `spo-links/unlink`: an optional `Idempotency-Key`, `soDocDate` on `po-links`, and extra body fields (`operationId`, `message`, `warnings`, `docKey`, `docNo`, `replacedLines`) when an operation answers.
Plan 61 adds the optional `X-Request-ID` header on these routes (57 contract section 2a): stored on SS's
log of every AutoCount call made for the request, else the `Idempotency-Key` is used; ignored when invalid.
Plan 63 adds the optional `X-Acting-User-Id` and `X-Acting-User-Name` headers on these routes: format and
rules in 57 contract sections 2a.1 and 8. Absent or invalid = stored empty, never a refusal.

```json
{ "actionId": "c1a0...", "outcome": "done", "errorCode": null, "document": { "...": "..." } }
```

| Field | Type | Meaning |
|---|---|---|
| `actionId` | string or null | The id of the audit record for this call; quote it to support. Null only when the company could not be resolved to a write action |
| `outcome` | string | One of section 5 |
| `errorCode` | string or null | Null on a clean `done`; `LOCATION_NOT_MOVED` on a `done` whose location move did not land (section 5); else a code from section 5 |
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
| `mismatch` | 502 | `ROW_VALUES_NOT_KEPT` | Split link: the link landed, but the new row's unit price or delivery date could not be put back to the PO row's values (section 5) |
| `vendor_error` | 502 | `VENDOR_ERROR` | AutoCount answered the write with an error; nothing is assumed written |
| `vendor_error` | 502 | `VENDOR_REFUSED` | AutoCount refused the write by its own rules; nothing was written and the key is released (section 4.0) |

`refused` 409 codes (nothing was changed in AutoCount):

| errorCode | Meaning | CRM action |
|---|---|---|
| `DOC_BUSY` | Another write on the same document is in flight, or ended `pending_verification` less than 10 minutes ago | Wait and retry; after 10 minutes an unfinished action no longer blocks |
| `DOC_UNKNOWN` | The document is not in the synced copy, so its date is unknown | Run or wait for the doc sync, then retry |
| `DOC_STALE` | `expectedLastModified` no longer matches: the document changed in AutoCount | Refresh the document, re-check the row, retry with the new `LastModified` |
| `DOC_NOT_FOUND` / `DOC_AMBIGUOUS` / `READ_FAILED` | (when raised before the write) the document could not be read exactly once | Retry later; if it persists, report with `actionId` |
| `VENDOR_UNSUPPORTED` | AutoCount does not apply this edit yet: SPO row unlink (and any switch a deployment turns off). Refused before anything is sent | Show 'not supported by AutoCount yet' |
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
| `ROW_RECEIVED` | The PO row has goods received against it | Handle it in AutoCount |
| `IDEMPOTENCY_CONFLICT` | The `Idempotency-Key` was used for a different body or route and its first call did not release it | Use a new key for a new change |
| `OPERATION_IN_PROGRESS` | The first call under this key is still running | Wait, then resend the same call |
| `QTY_ABOVE_OUTSTANDING` | `qty` is above what is still unlinked on the SO row | Lower `qty`, or unlink another PO row first |
| `ALL_LINKS_SKIPPED` | `po-links/batch`: every line failed its own check, so nothing was linked; `skipped` names each line and its code | Fix the lines and resend (same key is fine) |

**Split link is two writes.** Linking a quantity below the PO row edits the row down and adds a new
linked row. AutoCount stores that new row at its default location (HQ) with unit price 0 and no
delivery date, whatever the first write sent (db3, 4 and 6 Nov). The server then sends a second write
on the new row only: the SO row's location plus the PO row's unit price and delivery date, and reads
the document back. The call answers `done` once the link and those values are verified. If only the
location did not land, it still answers `done` (200) with `errorCode` `LOCATION_NOT_MOVED`: the link
stands, the row sits at the default location, and the CRM should offer "Move location" (the relocate
route above). If the unit price or delivery date did not land or could not be verified (second write
failed, skipped at the deadline, ignored, or written but not read back before the deadline), it answers `mismatch` (502) with `errorCode` `ROW_VALUES_NOT_KEPT`: the link
stands but the new row is mispriced; show "needs review" and fix the row in AutoCount. The second
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
- **Resend rule** (section 4.0): reuse the same `Idempotency-Key` to resend after a `refused` or
  `VENDOR_REFUSED` answer (the key is free again) and to reconcile a `pending_verification`; use a new key
  only for a deliberately new change.
- **Linking one PO row to many SO rows** = one `po-links/batch` call, not N sequential `po-links` calls.
- **Relink** = `po-links/relink` (plan 57 contract): one replace PUT, then the move.
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
200 { "actionId": "c1a0...", "outcome": "done", "errorCode": null, "document": { "...": "row 12009 gone, a new linked row" } }
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
