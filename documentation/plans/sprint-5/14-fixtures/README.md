# Plan sprint-5/14 S0 - DO / GRN / branch HTTP source fixtures

Companion to `14-autocount-do-grn-http-source.md` section 1 (vendor and CRM
surfaces, quoted exactly) and the CRM cross-repo contract section 13
(`/private/tmp/.../scratchpad/contract.md` at the time of writing, folded
into the plan). Consumed by `service_backend/tests/test_s14_doc_feed_*.py`
through `httpx.MockTransport` - no live network. No live gateway exists yet
for `delivery_orders`/`goods_receive_notes`/`branches` ingest or deletions
(contract 2.7, sorento-crm PR #1356), so every CRM-side response fixture is
CONSTRUCTED to the contract's stated shape (same discipline plan 13's
`13-fixtures/README.md` used for its SR5 fixtures), never captured from a
real answer. The vendor-side (DO/GRN/branch) field lists and one shape fact
(document doors answer bare arrays, no pagination) ARE grounded in the live
orchestrator inspection quoted in issue #1354 (29 Sep 2026 00:1x MYT); every
value in these fixtures is anonymised (no real `DebtorCode`/`CreditorCode`/
address/contact data), the field NAMES and shapes are real.

## Vendor fixtures (bare arrays / paged envelope, per plan section 1)

- **`do-vendor-day.json`** - `deliveryorderbyLastModified`/`...bydocdate`
  answer shape: a bare JSON array, two DO header records. `DocKey` 55120/
  55121, `book` = `db1`. Record 1's `Details` carries a normal line
  (`ItemCode` set) AND a description-only line (`ItemCode: ""`, the
  `line_without_item`/`skippedNoKey`-adjacent case, AC-13.7/D19 - this row
  has no line-level identity but the DOCUMENT itself still has an integer
  `DocKey` so the whole record is sent). Record 2's line carries
  `FromDocType`/`FromDocNo`/`FromDocDtlKey` (13.8's exact link fields) -
  the live inspection found NONE of these on any real sample, so this row
  is a FORWARD-LOOKING case: the pass-through-when-present rule (AC-14-41
  parity: "link fields pass through when present, never awaited") needs a
  fixture that actually carries them. Every other field on both records is
  the live-inspected field LIST (`DeliverAddr1-4`, `DeliverFax1`,
  `InvAddr1-4`, `CreatedUserID`, `LastModifiedUserID`, etc.) with
  anonymised values. Pins AC-14-20 (fixture JSON equality, `Details` and an
  unknown key survive byte-for-byte) and AC-14-13 (same-DocKey-twice-in-one-
  read is NOT exercised by this file alone - the cursor test constructs that
  case inline, since it needs two DIFFERENT day fixtures for the same key).

- **`grn-vendor-day.json`** - the GRN equivalent: `CreditorCode`/
  `CreditorName`/`SupplierDONo`/`PurchaseAgent` on the header,
  `OurPONo`/`OurPODate` on the line; record 2's line carries `OurPONo` AND
  the three `FromDoc*` fields together (a GRN -> PO exact link).

- **`do-vendor-day-paged-envelope.json`** - a DOCUMENT endpoint answering
  the PAGED envelope shape (`{Data, Page, PageSize, TotalPages: 2, ...}`)
  instead of the plain array V2 promises - `VENDOR_PAGED` (AC-14-12): a
  document door must never silently read only the first page.

- **`branch-page-1.json`** / **`branch-page-2.json`** - `branchbypage`
  two-page walk, `pageSize` 2 so the sample stays small, `TotalPages: 2`
  echoed on both. Page 1: two ordinary branches (`AccNo` + `BranchCode`
  both set). Page 2: one branch with a BLANK `AccNo` (source_ref
  `db1:BR::HQ`, C2's "no AccNo" rule) and one with a BLANK `BranchCode`
  (the `skippedNoKey` case, AC-14-41 - never sent, the CRM would answer
  `failed` with `source_ref: null` for it).

## CRM fixtures (constructed to contract 2.7's stated shape)

- **`crm-contract-2.7.json`** - `GET /external/contract`: version `"2.7"`,
  `entities` lists every entity contract 2.7 ships including the three new
  doors. Pins the doc-feed gate opening (AC-14-04, `contractGate: null`).

- **`crm-contract-2.6-no-doc-feed.json`** - a pre-2.7 consumer: version
  `"2.6"`, `entities` omits `delivery_orders`/`goods_receive_notes`/
  `branches` entirely. Pins the gate SHUT (AC-14-04, `contractGate:
  {version: 2.6, requiredVersion: 2.7}`).

- **`crm-ingest-delivery-orders-response.json`** - `POST
  /ingest/delivery_orders` verdicts for 8 records covering the FULL
  vocabulary AC-14-22 names: `created`, `updated` + warning
  `adopted_by_doc_no` + `branch_unresolved`, `updated` + warning
  `so_line_unresolved` + `sales_order_unresolved`, `unchanged` (plain),
  `unchanged` + warning `stale_ignored`, `retryable` (`Details.0.ItemCode`
  unresolved), `retryable` (`Details.0.Location` unresolved), `failed`
  (`DocNo` clash). `summary` totals match record-for-record.

- **`crm-ingest-goods-receive-notes-response.json`** - the GRN equivalent,
  covering the warnings `crm-ingest-delivery-orders-response.json` does
  not: `po_line_unresolved`, `line_without_item`,
  `purchase_order_unresolved`, `legacy_links_released` + `restored`
  (together, since a restore is itself a kind of link event), plain
  `unchanged`, one `retryable`.

- **`crm-ingest-branches-response.json`** - `created` x2 (`AccNo` set),
  `updated` for the no-`AccNo` `db1:BR::HQ` ref (C2).

- **`crm-deletions-delivery-orders-response.json`** - `POST
  /ingest/delivery_orders/deletions` per C1: every record echoes ONLY
  `source_ref` (no `doc_key` field at all). `deactivated` (`entity_id`
  set), `not_found` (no `entity_id`), `failed` with `errors.doc_date` +
  `entity_id` (the "DocDate moved outside the swept window" case), and a
  MALFORMED `source_ref` (`db1:DO:ABC`, a non-integer suffix) answering
  `failed` with `errors.doc_key` - the sink never SENDS such a key (D19),
  but the parser must still classify an unparseable echo as `failed`
  rather than crash or silently drop it (AC-14-42). A sweep test also
  sends a DocKey this fixture carries NO record for at all (a `no verdict`
  case), constructed by asserting against a doc_keys list wider than this
  file's own records - itself the AC-14-42 "counted as failed" rule.

- **`crm-error-429-rate-limited.json`** / **`crm-error-502-bad-gateway.json`**
  - BODY only (mirrors plan 10's `error-429-too-many-builds.json` and plan
  13's error fixtures - the HTTP status and, for 429, the `Retry-After`
  header are not JSON-representable and are set directly in the test's
  `httpx.MockTransport` handler, documented here: 429 carries
  `Retry-After: 2`; 502 carries no special header, exercising the sink's
  existing transient-retry ladder (`_TRANSIENT_HTTP_STATUS`)).

## Known gaps

Every CRM-side fixture is CONSTRUCTED to contract 2.7's stated shape
(section 13 of the cross-repo contract), not captured from a live gateway -
sorento-crm PR #1356 had not been run against this lane as of 29 Sep 2026.
Re-verify against the real CRM copy once S5's lane-stack run and the owner's
hand test (plan section 9) exercise it for real, the same discipline plan
10's and plan 13's fixture READMEs both flag for their own pre-build
fixtures.
