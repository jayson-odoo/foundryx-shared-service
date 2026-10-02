# AutoCount pull gateway: `delivery_orders` snapshot (cross-repo contract, CRM lane DO-PULL-CRM)

Status: DRAFT for the CRM lane, 2026-09-30. Backlog BL-SS-286. Shared-service lane DO-PULL-SS,
branch `crew/do-pull-snapshot`. This file is the contract of record for the delivery-orders
snapshot; everything not restated here is inherited unchanged from the products / stock
snapshot contract (`documentation/plans/sprint-5/10-autocount-pull-review.md`, Appendix A:
auth, company identity, immutability, TTL, retention, paging, error ladder, `no-store`).

## 1. What it is

A third `entity` on the EXISTING public pull gateway (`/api/v1/autocount/*`, `X-API-Key`):
a frozen, immutable snapshot of AutoCount **delivery order headers with their lines**
(`Details[]`) for one book, scoped by a **MYT doc-date range** and / or **one DO number**.
Same three routes, same job / freeze / paging / limits as products and stock. The vendor
reads use the SAME open HTTP source the DO doc feed uses (plan 14, PR #97): the company's
`delivery_orders` feed connection and its `/deliveryorderbydocdate?DocDate=yyyyMMdd` door.
The snapshot never pushes anything to the CRM and never touches the feed's cursor, ledger or
issue rows: it is a read for the CRM's own "Pull from AutoCount" review + confirm flow.

## 2. Build: `POST /api/v1/autocount/snapshots`

```json
{ "companyCode": "SRT", "entity": "delivery_orders",
  "fromDay": "2026-09-29", "toDay": "2026-09-30", "docNo": "DO-2609/0201" }
```

| Field | Rule |
|---|---|
| `companyCode` | as today (A2): trimmed, case-insensitive, within the key's tenant |
| `entity` | `delivery_orders` (the only new value; `products` / `stock_balances` unchanged) |
| `fromDay` | optional `YYYY-MM-DD`, an MYT calendar day (the vendor's `DocDate`) |
| `toDay` | optional `YYYY-MM-DD`; defaults to `fromDay` when only `fromDay` is given |
| `docNo` | optional, a single DO number, matched TRIMMED and case-insensitively against the vendor's `DocNo`; at most 64 characters, no control characters (else 422 `INVALID_REQUEST`); echoed back with the caller's own casing |

Scope rules (each violation is a flat `422 INVALID_REQUEST` naming the field):

- At least one of `fromDay` / `docNo` must be given. `toDay` without `fromDay` is a 422.
- `docNo` alone: the range defaults to the **31 MYT days ending today** (today and the 30
  days before it); the vendor has no by-DocNo door, so the number is a filter over that range.
- `fromDay <= toDay`; the range is at most **31 days** inclusive (the feed's own catch-up cap);
  `toDay` <= MYT today; `fromDay` >= `2023-01-01` (the feed's backfill floor).
- `docNo` with a range: the range is read and only records whose `DocNo` matches are kept.
  No match = a `ready` snapshot with `recordCount: 0` (never an error).
- `fromDay` / `toDay` / `docNo` are ignored (and must be absent, else 422 `INVALID_REQUEST`)
  for `products` / `stock_balances`.

Response `202`:
```json
{ "snapshotId": "8f1e...", "status": "building", "entity": "delivery_orders",
  "companyCode": "SRT", "fromDay": "2026-09-29", "toDay": "2026-09-30", "docNo": null }
```
The three scope keys are echoed on EVERY `delivery_orders` response (build, header) with
`null` for an absent `docNo`; they are absent on products / stock responses (byte-identical
to today).

Re-attach and cooldown (A3 / A5, adjusted for scope):

- A build already `building` for the same (company, `delivery_orders`) with the **same
  scope** (same `fromDay`, `toDay`, and `docNo` compared trimmed and case-insensitively) returns
  THAT id, no second extraction.
- A build already `building` for the same company but a **different scope** is
  `409 BUILD_IN_FLIGHT` (additive code): one DO build per company at a time. Poll the one in
  flight (its id is not returned; the CRM side holds it from its own earlier build call) or
  wait for it to finish.
- The 60 s cooldown (`429 TOO_MANY_BUILDS` + `Retry-After`) applies only when the previous
  build had the **same scope**; a different range or DO number within 60 s is allowed.

Gating: `409 PULL_NOT_ENABLED` when the company has no `delivery_orders` feed row, or the row's
AutoCount connection no longer resolves in this tenant (deleted, or not an open `autocount`
connection). The feed's mode may be `off`, `dry_run` or `push`: the mode gates the hourly push,
never this read. `409 PUSH_ACTIVE` is never raised for `delivery_orders`.
`404 UNKNOWN_COMPANY`, `403 COMPANY_NOT_ALLOWED`, `409 AMBIGUOUS_COMPANY`, the throttles and the
auth codes are as today.

## 3. Header: `GET /api/v1/autocount/snapshots/{snapshotId}`

```json
{
  "snapshotId": "8f1e...", "entity": "delivery_orders", "companyCode": "SRT",
  "status": "ready",
  "fromDay": "2026-09-29", "toDay": "2026-09-30", "docNo": null, "book": "db1",
  "extractedAt": "2026-09-30T08:14:02Z", "expiresAt": "2026-10-01T08:14:02Z",
  "recordCount": 41, "complete": true, "contentHash": "3b0c...",
  "sourcePageSize": null,
  "daysRead": 2, "fetchedCount": 43, "lineCount": 188,
  "excludedCount": 1,
  "excludedRows": [
    { "source_ref": null, "code": "DO-2609/0199", "reason": "missing_doc_key",
      "message": "DocKey is missing or not an integer; the record cannot be identified." }
  ]
}
```

- `book` is the feed connection's book (last path segment of its base URL, e.g. `db1`), the
  same top-level `book` the DO feed sends on ingest. Present on every DO header, any status.
- `recordCount` = delivered DO documents (one row per DocKey, after dedupe and the `docNo`
  filter). `lineCount` = sum of `len(Details)` over the delivered rows. `fetchedCount` = raw
  records the vendor returned across all days, before dedupe. `daysRead` = days in the range.
- `complete` is `true` on every `ready` DO snapshot: any day that fails to read fails the
  whole build (nothing partial is ever served), exactly like the feed's "only speak for days
  read" rule. `sourcePageSize` is `null` (the DO doors are plain arrays, not paged).
- `excludedRows` (shape `{source_ref, code, reason, message}`, A6's no-combine shape) lists
  records with no usable `DocKey` (`reason: "missing_doc_key"`, `code` = the vendor `DocNo`,
  `source_ref: null`) and records whose JSON is over 1 MB (`reason: "too_large"`, `source_ref`
  = `{book}:DO:{DocKey}`; the CRM's own ingest record cap is 1 MB / 2,000 lines, so such a
  document could never be confirmed anyway).
  As with products, exclusions do NOT block Confirm; the CRM's own ingest rules decide what
  to do with what it receives.
- A zero-row DO snapshot is a normal `ready` snapshot (a day range with no DOs, or a `docNo`
  that did not match). The products / stock `EMPTY_EXTRACT` zero-row guard does not apply
  to a scoped range.
- `building` carries `{snapshotId, entity, companyCode, status, fromDay, toDay, docNo, book}`
  plus the optional `progress` hint (`stage: "source"`, `pagesDone` / `pagesTotal` = days
  read / days in range; `stage: "storing"` while rows are inserted).
- `failed` carries `error: {code, message}`; codes for DO: `SOURCE_PAGE_FAILED` (a vendor
  day could not be read: transport, HTTP, not-JSON, wrong shape, paged envelope, after the
  feed's own retry ladder), `ROW_LIMIT` (over 10,000 documents in the range), `BUILD_ABANDONED`
  (orphaned worker). `EMPTY_EXTRACT`, `ENRICH_FAILED`, `COMBINE_RULE_FAILED` are never stamped
  on a DO snapshot. `message` is fixed prose per code (A6), branch on `code`.

## 4. Rows: `GET /api/v1/autocount/snapshots/{snapshotId}/rows?page=1&pageSize=1000`

Unchanged envelope `{snapshotId, page, pageSize, totalPages, recordCount, rows}`. Each row is
**the raw vendor delivery order exactly as the DO doc feed pushes it** (plan 14 D18: no field
renamed, dropped or re-typed; `Details[]` included; unknown vendor keys included), e.g.

```json
{ "DocKey": 55120, "DocNo": "DO-2609/0201", "DocDate": "2026-09-28T00:00:00",
  "DocStatus": "C", "Cancelled": "F", "BranchCode": "", "DebtorCode": "300-R009",
  "DebtorName": "Anon Trading Sdn Bhd", "SalesAgent": "SEAN I", "Ref": "Anon iP-001207",
  "Total": 250.0, "NetTotal": 250.0, "LastModified": "2026-09-28T15:37:53.367",
  "Details": [
    { "DocKey": 55120, "DtlKey": 900301, "Seq": 1, "ItemCode": "ACC-CB8001",
      "Qty": 10, "UOM": "PCS", "UnitPrice": 25.0, "SubTotal": 250.0, "Location": "MWH",
      "DeliveryDate": "2026-09-28T00:00:00", "YourPONo": "" }
  ] }
```

- The row carries every vendor field, so the CRM's Excel compare needs no extra request:
  `CreatedTimeStamp`, `LastModified`, `Cancelled`, `DocStatus`, `DebtorCode` / `DebtorName`,
  `SalesAgent`, `Total` / `Tax` / `NetTotal` / `LocalNetTotal`, and per line `Location`,
  `UnitPrice`, `Discount` / `DiscountAmt`, `SubTotal`, `Qty` / `UOM`. A field the vendor does
  not return cannot be added here; raise it via crew report.
- Owner ruling 2026-09-30: the DO feed stays pull-on-request (no `push` switch until the CRM
  compare + approve flow is proven). `goods_receive_notes` got the same snapshot as a follow-on
  (section 8, 2026-10-02).
- Identity: `source_ref` is NOT inside the row (the feed does not send it either); derive it as
  `{book}:DO:{DocKey}` with `book` from the header, the same derivation the CRM's DO ingest
  already uses (`13.3 / C2`). The stored row's `source_ref` column holds that string for the
  audit / operator views.
- One row per `DocKey` (the copy with the greatest `LastModified`, the feed's D8 rule).
- Ordering is stable: `DocDate` ascending, then `DocKey` ascending.
- `contentHash` is computed over these row dicts exactly as A5 states.
- Numbers are JSON numbers as the vendor returned them (no Decimal-as-string here: the row is
  the raw vendor JSON, never a pydantic dump). `LastModified` / `DocDate` are the vendor's naive
  MYT strings, unchanged.

## 5. Limits and sizing

- Range cap 31 days; document cap 10,000 per snapshot (`ROW_LIMIT`, checked on the raw count
  after every day read, so an over-cap range stops early); per-document cap 1 MB (excluded,
  see section 3); `pageSize` max 1000 as today.
- The 60 s cooldown is per scope (section 2), so a caller can start a new range as soon as the
  previous build ends; the one-build-in-flight rule and the per-key request throttle are the
  limits that apply across scopes. `BUILD_IN_FLIGHT` can only be held by a key of the SAME tenant
  and company, and only for as long as that build is alive. A 31-day SRT range is on the order of a few thousand DOs; expect a build of a few
  seconds per day read (one vendor GET per day, plain array) plus row storage.
- TTL 24 h from `extractedAt`; newest 3 ready snapshots kept per (company, entity) as today.

## 6. Error ladder additions (additive, A6 otherwise unchanged)

| Status | code | Meaning |
|---|---|---|
| 409 | `BUILD_IN_FLIGHT` | A `delivery_orders` build with a DIFFERENT scope is still building for this company; wait for it |
| 422 | `INVALID_REQUEST` | (existing code) now also: a bad / missing DO scope, a scope key on a non-DO entity; `message` names the field |
| 422 | `UNKNOWN_ENTITY` | (existing) `message` now lists `delivery_orders, products, stock_balances` |

## 7. What the CRM side needs to change (for the DO-PULL-CRM lane)

- `FoundryxAutocountClient.build()` gains optional `from_day` / `to_day` / `doc_no` kwargs that
  land as `fromDay` / `toDay` / `docNo` in the JSON body (omitted when `None`).
- `POST /api/v1/autocount/pulls` accepts `entity: "delivery_orders"` with the same three
  optional scope fields; the review compares each row against `orders` / `order_lines` with
  the DO ingest's own rules, keyed by `DocKey` / `DtlKey`, `source_ref = {book}:DO:{DocKey}`.
- Confirm applies via the existing DO ingest code path (no second writer).

## 8. `goods_receive_notes` (GRN mirror, 2026-10-02, lane GRN-PULL-SS, for CRM lane GRN-PULL-CRM)

A fourth `entity` on the same gateway. **Everything in sections 2-6 applies unchanged**: the
same three routes, the same scope keys and rules (flat optional `fromDay` / `toDay` / `docNo`,
at least one of `fromDay` / `docNo`, `docNo` alone = the 31 MYT days ending today), the same
202 echo, the same header keys (`book`, `contentHash`, `daysRead`, `fetchedCount`, `lineCount`,
`excludedRows`, ...), the same re-attach / `409 BUILD_IN_FLIGHT` / per-scope cooldown, the same
10,000-document cap (`ROW_LIMIT`), the 1 MB per-document exclusion and the same failed codes.
Only these differ:

| | `delivery_orders` | `goods_receive_notes` |
|---|---|---|
| Wire `entity` | `delivery_orders` | `goods_receive_notes` |
| Vendor door | `/deliveryorderbydocdate?DocDate=yyyyMMdd` | `/goodsreceivenotebydocdate?DocDate=yyyyMMdd` |
| Gate (`409 PULL_NOT_ENABLED` when missing / no connection) | the company's `delivery_orders` feed row | the company's `goods_receive_notes` feed row |
| `source_ref` (stored column; derive it the same way on the CRM side) | `{book}:DO:{DocKey}` | `{book}:GRN:{DocKey}` |
| `too_large` message | "Delivery order exceeds 1 MB ..." | "Goods received note exceeds 1 MB and cannot be stored in a snapshot." |

- **Scope with no keys:** `fromDay` or `docNo` is required (422 `INVALID_REQUEST`, "fromDay or
  docNo is required."), exactly as for DO. There is no implicit "last 31 days" for a bare build:
  send `docNo` alone for the 31-day window, or send `fromDay` / `toDay` (today minus 30 to
  today).
- **Rows:** the raw vendor GRN dict verbatim, with `Details[]` intact (header `Cancelled`,
  `LastModified`, `CreditorCode` / `CreditorName`, `SupplierDONo`, totals; lines `DtlKey`,
  `ItemCode`, `Qty`, `UOM`, `UnitPrice`, `Location`, `OurPONo`, and the vendor's
  `FromDocType` / `FromDocNo` / `FromDocDtlKey` when it returns them). Nothing is renamed or
  added. One row per `DocKey` (greatest `LastModified`), ordered `DocDate` asc then `DocKey` asc.
- The GRN feed's `mode` never gates the read, and the build never touches the feed's cursor,
  ledger, issue rows or the sink. The feed stays pull-on-request (no Push switch is involved).
- `BUILD_IN_FLIGHT` is per (company, entity): a DO build in flight never blocks a GRN build,
  and the reverse holds too.
- `UNKNOWN_ENTITY`'s message now lists
  `delivery_orders, goods_receive_notes, products, stock_balances`. A scope key on
  `products` / `stock_balances` is still a 422 (the message names both document entities).
- **Who may read it:** the gateway key is company-scoped exactly as for DO. No new key scope
  exists; the enable switch is the operator configuring the company's GRN feed. On the
  operator (session) routes, a GRN snapshot also needs `autocount.sync.read` on top of
  `autocount.pull.read`; without it the snapshot is hidden from the list and reads as an
  unknown id (404). The operator build route refuses `goods_receive_notes` with a 422, as it
  does `delivery_orders`.
