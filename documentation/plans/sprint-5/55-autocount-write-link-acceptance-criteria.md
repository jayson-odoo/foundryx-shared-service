# Plan 55 acceptance criteria: AutoCount PO line link / unlink write-back (phase 1)

4 Nov 2026. Owner rulings Q1-Q5 (4 Nov, all option (a)) are folded in. Rows marked AQn depend on
AutoCount's reply (`documentation/integrations/autocount/write-api-questions-2026-11-04.md`) and are
proven or adjusted by the db3 runs. Phase 2 (QT / SO create, edit, cancel) gets its own criteria.

## Safety

| AC | Rule |
|---|---|
| AC-55-01 | [BE] Every AutoCount write (POST or PUT) goes through one write client; no other code path sends a non-GET request to the AutoCount wrapper |
| AC-55-02 | [BE] The write client refuses, before any network call, a connection whose base URL book (last path segment) is not on the hardcoded test allowlist (`db3`); db1, db2, a missing segment, a trailing slash variant, a case variant (`DB1`), and look-alikes (`db3x`, `db31`, `db3/../db1`, `db3?x`, query or fragment) are all refused or normalised safely; the allowlist is not configurable at runtime |
| AC-55-03 | [BE] A refused write records an error naming the refused book and makes no HTTP request (asserted with a transport that fails the test on any call) |
| AC-55-04 | [BE] No credential or key value appears in logs, errors, run records or the test report |
| AC-55-05 | [BE] The write client never retries a POST or PUT by itself (a `DtlKey 0` row would be added twice); a timeout or dropped connection is handed to AC-55-23 |

## Payload builder (pure functions, no I/O)

| AC | Rule |
|---|---|
| AC-55-10 | [BE] Link in place: given the current PO document (as read back) and one PO row DtlKey plus one SO row (DocNo, DtlKey), the PUT body carries the PO DocKey, the header as read, and that row with its DtlKey and `FromDocType "SO"`, `FromDocNo`, `FromDocDtlKey`; all other row fields are copied from the read-back row |
| AC-55-11 | [BE] Split: PO row qty Q, link qty q with 0 < q < Q, target location M: the body edits the row to Q - q (link fields unchanged) and adds one row with `DtlKey 0`, same item, UOM, unit price, discount, tax code, delivery date and description, `Location M`, `Qty q` and the SO From* fields; Q - q + q == Q exactly (decimal, no float) |
| AC-55-12 | [BE] (gated by capability, AC-55-60) Unlink: the body edits the linked row with `FromDocType ""`, `FromDocNo ""`, `FromDocDtlKey 0`, qty and location unchanged (AQ8) |
| AC-55-13 | [BE] Refusals with a stable error code and no body built: item code differs; UOM differs; q <= 0; q > PO row free qty (Q2: refuse; the user links a second PO row for the rest); q > SO row outstanding (derived); PO cancelled; PO row already linked (relink must be explicit); the document is an SPO when a PO is required, or a PO when an SPO is required |
| AC-55-14 | [BE] Same qty, different location (Q1): q == Q and the SO row location differs: no split; the one row is edited to the SO row location and linked |
| AC-55-15 | [BE] (gated by capability, AC-55-60) SPO precondition: a PO row that an SPO row points at (`FromDocType "PO"`, `FromDocDtlKey` = that row) cannot be linked, unlinked or relinked while that SPO row points at it (Q4): refused with a stable error naming the SPO DocNo and row; a separate explicit action unlinks the SPO row (`FromDocType ""`, `FromDocNo ""`, `FromDocDtlKey 0` on the SPO document, AQ13) |
| AC-55-16 | [BE] (gated by capability, AC-55-60) Unlink of a split row (Q3): the row stays its own row with its qty and location; no merge, no row removal |

## Write flow and fetch-back

| AC | Rule |
|---|---|
| AC-55-20 | [BE] Each action: guard -> fresh GET of the document -> build body from that GET -> PUT -> GET again -> store only what the second GET returned |
| AC-55-21 | [BE] Stale guard: if the fresh GET's `LastModified` differs from the version the caller acted on, the action is refused with a stale-document error and no PUT is sent |
| AC-55-22 | [BE] Fetch-back check: after the PUT, the action succeeds only if the read-back rows show the intended state (link: `FromSODtlKey` == SO DtlKey on the right row; split: both rows with the expected qty and location; unlink: `FromSODtlKey 0`) AND every row not in the body reads back unchanged (qty, location, `FromSODtlKey`, `FromDocType` / `FromDocDtlKey`); otherwise it is reported as a mismatch with both the sent body and the read-back rows |
| AC-55-23 | [BE] PUT accepted but the read-back GET fails (or the PUT times out): the action is recorded `pending_verification`, never reported as done; nothing retries in the background; the next action on that document starts from a fresh GET, and a `pending_verification` younger than the busy window counts as busy (AC-55-26) |
| AC-55-24 | [BE] A vendor error (non-2xx, or an error body) is recorded with status and body (sanitised) and nothing on our side changes |
| AC-55-25 | [BE] After a confirmed write, the refreshed PO (and SPO) goes out through the existing Sorento sink with the same canonical line shape as the SQL path (`from_so_line_ref`, `from_so_numbers`, `from_po_line_ref`) |
| AC-55-26 | [BE] One action at a time per AutoCount document (company + DocKey): a second action on the same document while one is open is refused `DOC_BUSY`, never queued |
| AC-55-27 | [BE] No AutoCount HTTP call runs while a database transaction or pooled connection is held; the action row is committed before the PUT and updated after the read-back |
| AC-55-28 | [BE] Every action is recorded in `ac_write_action` (tenant, company, action, doc type, DocKey, DtlKey, sanitised request body, response status and body, before and after rows, outcome, error code, key id, timestamps); reads are tenant-scoped |

## db3 pull (local proof)

| AC | Rule |
|---|---|
| AC-55-30 | [BE] PO and SO documents can be pulled over the wrapper by `...byLastModified` / `...bydocdate` for one company, mapped to the same canonical PO / SPO / SO lines as the SQL path; SPO = header `ShippingPO "T"` |
| AC-55-31 | [BE] An SO line ref for a PO row is resolved from `FromSODtlKey` via the pulled SO rows (the wrapper gives no SO DocKey on the PO row, AQ12) |

## Gateway (Q5: routes only, no SS screen; CRM Stock Debt is the entry, separate lane)

| AC | Rule |
|---|---|
| AC-55-40 | [BE] API-key routes for link, unlink and SPO-row unlink, tenant- and company-scoped, scope-checked, returning the read-back rows; contract documented in the same change |
| AC-55-41 | [BE] Relink = unlink then link as two calls; there is no combined relink route (Q4) |
| AC-55-42 | [BE] A scripted db3 runner drives each use case through the same service layer and writes the test report rows (AC-55-50) |
| AC-55-43 | [BE] Write routes need an API key carrying the `write_back` scope: a pull-only key gets 403 and no AutoCount call; existing keys are backfilled to `["pull"]`; issuing a key with `write_back` needs `autocount.companies.manage` |
| AC-55-44 | [BE] Company resolution matches the pull routes (`companyCode`, the key's company set, 404 / 409 / 403); a DocKey is only ever read and written through the resolved company's write connection, never another tenant's or company's |
| AC-55-45 | [BE] A company writes only when `write_connection_id` is set (null = `WRITE_DISABLED`, the default for every existing company after the migration); the write connection is re-resolved with tenant_id at use time and still passes AC-55-02 |
| AC-55-60 | [BE] Capability gate: code constants `VENDOR_CAPABILITIES` (`link_new_row` on; `link_existing_row`, `unlink`, `spo_unlink` off) are read at call time; unlink and SPO unlink answer refused `VENDOR_UNSUPPORTED` with an action row and no request; a link of the whole PO row (q equal to the row qty) answers `VENDOR_UNSUPPORTED` after exactly one document read and no write; q above the row keeps `QTY_ABOVE_FREE`; flipping a flag restores the old path |
| AC-55-61 | [BE] Split link as two writes: PUT 1 is the split body and its read-back verification ignores the new row's location; when the new linked row's location differs from the SO row's, PUT 2 sends only that row (as read, location = the SO row's) and is read back; the outcome is `done`, and both bodies and responses are recorded as lists on the action row |
| AC-55-62 | [BE] `LOCATION_NOT_MOVED`: when PUT 2 fails, times out, is ignored or the location did not move, the outcome is `done` with `errorCode` `LOCATION_NOT_MOVED` (gateway 200), the link is not undone, and PUT 2 is never retried |
| AC-55-63 | [BE] Relocate: `WriteBackService.relocate` and `POST /api/v1/autocount/po-links/relocate` (`companyCode`, `poDocKey`, `poDtlKey`, optional `expectedLastModified`; `write_back` scope) move a linked PO row to the staged SO row's location; refused `ROW_NOT_LINKED`, `ROW_ALREADY_AT_LOCATION`, `DOC_STALE`, `DOC_BUSY`, `WRITE_NOT_ALLOWED`; same guards as link |
| AC-55-64 | [BE] Zero-qty switch: with `ZERO_QTY_EMULATION` on, a whole-row link is the original row to quantity 0 plus a new linked row, then the location move; off by default |

## Evidence

| AC | Rule |
|---|---|
| AC-55-50 | [E2E-server] Live db3 runs for each use case (link in place, split, unlink, over-link refused, stale refused, SPO precondition) recorded in `documentation/integrations/autocount/test-report-<date>.md`: request, response, before and after GET, expected vs observed, PASS / FAIL, sanitised |
| AC-55-51 | [E2E-server] No write request ever reaches a book other than db3 during the runs (request log shows db3 only) |

Migration: module `0036_autocount_write_back` (new `ac_write_action`; `ac_company.write_connection_id` backfilled null; `ac_pull_api_key.scopes` backfilled `["pull"]`). No new permission. No screen change (Q5); the key-issue route gains a `scopes` field. Wire change: three new public gateway routes, contract doc in the same change.
