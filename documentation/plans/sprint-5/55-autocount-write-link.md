# 55 - AutoCount write-back: PO line link / unlink (SO, SPO), then QT / SO create, edit, cancel

Lane AC-WRITE-LINK, size L. Status: STEP 1 (study + use-case card). No write calls made yet; every
fact below comes from the AutoCount write-API notes of 4 Nov 2026 (crew files
`autocount-api/Sorento_API_Test_Records-4nov.txt`, not in the repo) or from read-only GETs against the
`db3` test database on 4 Nov 2026. UAC (`55-autocount-write-link-acceptance-criteria.md`) is written
after the owner answers the Step 1 card.

## 1. Priority (owner, 4 Nov)

1. Phase 1: link a PO line to an SO line, and unlink it; PO line <-> SPO line unlink before relink.
   Driven from the CRM Stock Debt snapshot (like Reserve). Split rule below. Fetch back after every write.
2. Phase 2: Quotation and Sales Order create / edit / cancel (never delete) from the CRM project sales module.

One db3 test report and one AutoCount question list cover both phases.

## 2. Vendor surface (hapi wrapper, base URL `.../api/<db>`)

| Door | Method | Path | Source | Verified |
|---|---|---|---|---|
| New quotation | POST | `/NewQuotation` | vendor notes | db3 docs QT-004193 (DocKey 11982), QT-004194 (11984) exist |
| Edit quotation | PUT | `/EditQuotationbydockey` | vendor notes | QT-004194 LastModified 13:16 after create 00:45 |
| New sales order | POST | `/NewSalesOrder` | vendor notes | SO389293 (11988), SO390188 (12005) exist |
| Edit sales order | PUT | `/EditSalesOrderbydockey` | UNVERIFIED (name by analogy) | - |
| New request quotation | POST | `/NewRequestQuotation` | vendor notes | RQ-000001 (11997) exists |
| New purchase order | POST | `/NewPurchaseOrder` | vendor notes | 202602-S0007 (12008) exists |
| Edit purchase order (also SPO) | PUT | `/EditPurchaseOrderbydockey` | UNVERIFIED (name by analogy) | - |
| Cancel QT / SO / PO | ? | ? | not in notes | AutoCount question |
| Read by doc date | GET | `/{quotation,salesorder,purchaseorder}bydocdate?DocDate=YYYYMMDD` | probed db3 | 200 |
| Read by last modified | GET | `/{quotation,salesorder,purchaseorder,requestquotation}byLastModified?lastModified=YYYYMMDD` | probed db3 | 200 |
| Read one doc | GET | `/purchaseorderbydockey`, `/salesorderbydocno` ... | probed db3 | 404 (no such route) |

Write rules (vendor notes): POST = new document, no DocKey / DtlKey. PUT = edit by DocKey; detail
`DtlKey=0` adds a row, `DtlKey>0` edits that row. A transferred row carries `FromDocType`,
`FromDocNo`, `FromDocDtlKey`, `FullTransferOption`, `FullTransferFromDocList`.

## 3. Where the links live (read back from db3 / db1, 4 Nov)

- **PO line -> SO line.** Written as `FromDocType "SO"`, `FromDocNo <SO DocNo>`, `FromDocDtlKey <SO DtlKey>`.
  Read back on the PO line as `FromSODtlKey <SO DtlKey>` + `FromSODocList <SO DocNo>`, with
  `FromDocType ""` and `FromDocDtlKey 0`. Evidence: db3 PO 202602-S0007 DtlKey 12011 -> FromSODtlKey
  11990 / FromSODocList SO389293 (SO389293 DtlKey 11990, item SRTKS7090, qty 10).
- **SPO line -> PO line.** SPO = a PO document with header `ShippingPO "T"`. Its line carries
  `FromDocType "PO"`, `FromDocNo <PO DocNo>`, `FromDocDtlKey <PO DtlKey>`; `FromSODtlKey` stays 0.
  Evidence (read-only GET, db1, DocDate 2026-11-02): SPO-2026/11-0001 DtlKey 46179075 -> PO
  202610-S0024 DtlKey 45981239. So "unlink PO from SPO" is an edit of the SPO line, not the PO line.
- **QT line -> SO line.** SO390188 DtlKey 12006 reads `FromDocType QT`, `FromDocNo QT-004193`,
  `FromDocDtlKey 0`; QT-004193 header reads `ToDocType SO`, `ToDocKey 12005`.
- **Not exposed by any GET:** SO line transferred-to-PO qty, PO line transferred qty (to SPO / GRN),
  document lock state. Outstanding checks must be derived (sum of PO lines' FromSODtlKey qty) until
  AutoCount exposes them.
- Observation to confirm: the vendor's PO POST body sent `Location BRW-AM` on the three SO-transferred
  lines; db3 reads them back as `HQ` (create time == last modified, so no later edit). The split rule
  needs the line to keep the SO line's location.

## 3a. What the shared service has today (paths under `service_backend/modules/autocount/`)

- No write path to AutoCount anywhere; write-back is backlog BL-SS-042 (`documentation/backlogs/backlog.md:186`).
- hapi reads: `HttpApiClient` (`http_source/client.py:176`, URL = `base_url + path` at `:188`, `:261`);
  doc-feed `DocFeedVendor` (`doc_feed/vendor.py:45`, `DocDate` / `lastModified` params at `:56`, `:60`).
  HTTP presets cover items, UOM, debtors, locations, item group / brand / class, branches, batch
  balance (`presets.py:1420-1706`) and DO / GRN feeds (`doc_feed/constants.py:17-20`). Other entities
  are refused for HTTP tasks (`services/etl_service.py:1846`).
- PO / SPO / SO are pulled over SQL only (`presets.py:335-378`, `PO_PRESET` `:405`, `SPO_PRESET` `:471`;
  SPO split by DocNo prefix `SPO-` at `:403`, `:469`). So db3 PO / SO need a new HTTP doc pull
  (the `...byLastModified` doors) that maps to the same canonical PO / SO lines.
- Canonical PO line linkage fields: `canonical/documents.py:287-332` (`from_so_line_ref`,
  `from_so_numbers`, `from_po_line_ref`); refs minted `{db}:{DocKey}:{DtlKey}` (`mapping.py:1657-1675`).
  The hapi PO line carries `FromSODtlKey` + `FromSODocList` but no SO DocKey, so the ref needs an SO
  DtlKey -> DocKey lookup (or AutoCount adds `FromSODocKey`).
- Connection: provider `autocount` (`provider.py:46`), `auth none` + `baseUrl` (`provider.py:139-222`);
  book = last URL segment (`http_source/book.py:18-21`). No db allowlist exists; guards are SSRF
  (`provider.py:299-303`) and the path rule (`http_source/preview.py:30-46`).
- db1 = live Sorento company `AED_SORENTO` (`08-autocount-http-source-acceptance-criteria.md:8`),
  db2 = Mocha (`backlog.md:361`). db3 is new: masters are a Sorento copy (4 Nov: 11,980 items,
  4,274 debtors, 1,088 creditors); documents are only AutoCount's 4 Nov test set (DocKeys from 11982).

## 3b. CRM side today (sorento-crm origin/main 9c6b581e6, read only; CRM UI is a later lane)

- Stock Debt snapshot: one row per product; each row's `lines` = SO demand lines carrying
  `sales_order_line_id` (core UUID) and `assigned_from[]` (po / spo), but no AutoCount DocKey / DtlKey
  (`services/scm/stock_debt_service.py:642-669` drops `source_ref`); supply rows live only in the live
  drill (`schemas/stock_debt.py:266-310`). A link action must resolve `sales_order_lines.source_ref`.
- Reserve today is CRM-only (decision columns, or "Request CS to reserve" -> `OrderInquiryLink`); no
  call to FoundryX or AutoCount. CRM's manual Link dialog writes `scm.order_link_claim` source `manual`;
  AutoCount ingest writes source `autocount` from `from_so_line_ref` (`order_link_service.py:526-612`).
- CRM -> SS client to reuse: `FoundryxAutocountClient` (`services/foundryx_autocount_client.py:73-131`,
  `X-API-Key`, generic `_request`). Ingest never writes back (`document_ingest_service.py:53-54`), so a
  fetch-back push cannot loop.
- Phase 2 hooks: project quotations (`api/v1/projects/quotations.py:160,192`) and project SO publish
  (`services/project_so_draft_service.py:2668-2767`, "the ESB call replaces this transport in stage 2").

## 4. Use cases

Phase 1 (build first):

- **UC-1 Link in place.** PO line (unlinked, item X, qty Q, location L) and SO line (item X, needs q = Q,
  location L). PUT `EditPurchaseOrderbydockey` {DocKey, header, Details: [{DtlKey: po_dtl, line fields,
  FromDocType "SO", FromDocNo, FromDocDtlKey: so_dtl}]}. Fetch back: PO line FromSODtlKey == so_dtl.
- **UC-2 Link with split.** PO line qty Q at HQ, SO line needs q < Q at location M. One PUT:
  [{DtlKey: po_dtl, Qty: Q - q}, {DtlKey: 0, same item / UOM / price / delivery date, Location M,
  Qty q, FromDocType "SO", FromDocNo, FromDocDtlKey: so_dtl}]. Fetch back: original line Q - q, new
  line q at M linked to so_dtl, PO total unchanged.
- **UC-3 Unlink.** PUT the linked PO line with FromDocType "", FromDocNo "", FromDocDtlKey 0. Fetch
  back: FromSODtlKey 0. (Semantics UNVERIFIED: AutoCount question.)
- **UC-4 Unlink SPO.** PO line already shipped on an SPO line: PUT the SPO (its own DocKey) clearing the
  SPO line's From* fields (or removing the line: AutoCount question). Precondition for UC-5.
- **UC-5 Relink.** PO line linked to SO A, move to SO B: UC-4 if on an SPO, UC-3, then UC-1 / UC-2.
- Guards before any PUT: target db on the write allowlist (db3 only); item codes equal; q <= PO line
  unlinked qty; q <= SO line outstanding (derived); PO not cancelled; PO line not already linked
  (relink = explicit UC-5); fresh GET immediately before the PUT so the body carries AutoCount's current rows.

Phase 2 (next):

- **UC-6 Create QT** POST `NewQuotation` from a CRM project quotation; fetch back by DocDate, store DocKey/DtlKeys.
- **UC-7 Edit QT** PUT `EditQuotationbydockey` (rows by DtlKey, DtlKey 0 adds).
- **UC-8 Cancel QT** endpoint / field = AutoCount question; never delete.
- **UC-9 Create SO** POST `NewSalesOrder`, optionally from QT lines (FromDocType "QT").
- **UC-10 Edit SO** PUT `EditSalesOrderbydockey` (UNVERIFIED name).
- **UC-11 Cancel SO** = AutoCount question; never delete.
- Listed, no owner ask yet: POST `NewRequestQuotation`, POST `NewPurchaseOrder`.

## 5. Proposed flow and local setup

CRM Stock Debt UI action -> CRM API -> SS write endpoint (API-key gateway, per tenant + AutoCount
company) -> write service: allowlist guard -> GET current doc -> build payload (pure function: link,
split, unlink) -> PUT -> GET back -> reconcile our snapshot -> push the refreshed PO through the
existing Sorento sink -> return the refreshed lines to CRM. AutoCount stays the source of truth: our
side only ever stores what the fetch-back returned.

Local: lane SS DB, one "db3 test" connection (`.../api/db3`, auth none) and one AutoCount company for
db3; masters (items, debtors, creditors, locations) pulled through the existing HTTP tasks; PO / SO
docs pulled by `...byLastModified`. Local CRM with a fresh DB pointed at the lane SS. Never a prod copy.

## 6. Safety

- Code-level write allowlist: the write client refuses any request whose base URL db segment is not on
  a hardcoded test allowlist (`db3`), with a test for db1, db2, a missing segment and look-alike paths.
  Opening a live db needs a code change and review, never config.
- Writes only through one client class; reads keep using the existing client.

## 6a. Owner rulings (4 Nov, Step 1 card, all option (a))

Q1 same qty, other location = edit the row's location, no split. Q2 q above the PO row's free qty =
refuse (link a second PO row). Q3 an unlinked split row stays its own row, no merge. Q4 refuse any
link change on a PO row an SPO row points at until the SPO row is unlinked explicitly. Q5 gateway
routes + scripted db3 runner + test report; no SS screen; CRM Stock Debt is the entry (later lane).

## 6b. Design (phase 1)

New package `service_backend/modules/autocount/write_back/`:

- `guard.py`: `WRITE_ALLOWED_BOOKS = frozenset({"db3"})`, `assert_write_allowed(base_url) -> book`.
  Strict parse: https only, no query / fragment / params / encoded or dot segments; the last path
  segment must equal an allowlisted book exactly. Called on EVERY write request, not only at init.
- `client.py`: `AutoCountWriteClient` (POST / PUT only, JSON body, reuses the SSRF guard and redirect
  ban of `http_client.py:74-85`). Never retries a write (a `DtlKey 0` row would be added twice).
- `reader.py`: one-document GET by DocKey through `<doc>bydocdate?DocDate=` (filter by DocKey, refuse
  0 or 2+ matches); `Details` -> `_lines` so the existing PO / SO mapping profiles read it
  (`mapping.py:1222`, `:1234`). SPO = header `ShippingPO "T"`.
- `payloads.py`: pure builders `build_link`, `build_unlink`, `build_spo_unlink` + `so_outstanding`;
  `Decimal` math; stable refusal codes (`ITEM_MISMATCH`, `UOM_MISMATCH`, `QTY_INVALID`,
  `QTY_ABOVE_FREE`, `QTY_ABOVE_OUTSTANDING`, `ROW_ALREADY_LINKED`, `ROW_NOT_LINKED`, `ROW_ON_SPO`,
  `DOC_CANCELLED`, `DOC_KIND_MISMATCH`, `ROW_NOT_FOUND`).
- `service.py`: `WriteBackService.link / unlink / spo_unlink`: company -> write connection -> guard ->
  per-document busy check -> fresh GET (outside any DB transaction) -> stale check -> build -> PUT ->
  GET back -> verify -> stage the read-back document in `ac_staged_record` through the company's PO /
  SPO mapping (`sync.py:1213` `_stage_documents`) -> push through the Sorento sink. SO outstanding is
  derived from the company's staged PO rows whose `FromSODtlKey` equals the SO row (db3 scale; live
  scale is a follow-up unless AutoCount exposes transferred qty, AQ11).
- `pull_docs.py`: day-range pull of PO / SPO / SO from `...byLastModified` (and `bydocdate` for the
  first load) into `ac_staged_record` + sink, so a local SS and CRM hold db3 documents.

Schema (module migration `0036_autocount_write_back`, schema `app_autocount`):
- `ac_write_action`: id (uuid), tenant_id, company_id, action, doc_type, doc_key, dtl_key, outcome
  (`done`, `refused`, `mismatch`, `pending_verification`, `vendor_error`), error_code, request_json
  (sanitised body), response_status, response_json, before_json, after_json, key_id, created_at,
  updated_at. Doubles as the test report source and the busy lock (one open action per document).
- `ac_company.write_connection_id` nullable (null = writes disabled; backfill: null for every company).
- `ac_pull_api_key.scopes` JSON (backfill `["pull"]` for every existing key; write routes need
  `"write_back"`; issuing that scope needs `autocount.companies.manage`, so no new permission).

Gateway (`routers/pull_v1.py`, public, `X-API-Key`, same company resolution as `/snapshots`):
`POST /api/v1/autocount/po-links` (link), `POST /api/v1/autocount/po-links/unlink`,
`POST /api/v1/autocount/spo-links/unlink`. Body carries `companyCode`, DocKey / DtlKey ids, qty,
location, optional `expectedLastModified`; answer = outcome + read-back rows. Contract doc
`55-autocount-write-link-contract.md` ships in the same change (guide-writer after review).

## 6c. Slices (LEAD pattern: tester red first, one coder continued by message)

| Slice | Scope | ACs |
|---|---|---|
| S1 | guard + write client | AC-55-01..05 |
| S2 | payload builders + outstanding (pure) | AC-55-10..16 |
| S3 | migration 0036, reader, service flow, action log, busy + stale, staging + push | AC-55-20..28 |
| S4 | doc pull (db3 local load) + SO ref resolution | AC-55-30, 31 |
| S5 | gateway routes + key scopes + company write connection | AC-55-40..45 |
| S6 | db3 runner, live runs, AutoCount test report | AC-55-42, 50, 51 |

Build log (4 Nov):
- S1+S2: red 17dad883, fix 55ae7b8f, kill-proof K1-K3 (PR #183 comments).
- S3: red dbfe7fb6, fix 4cae05c8, kill-proof K4-K6. Lead re-slice 0d746427: the wrapper read-back has
  no AutoKeys / TransferedQty / FromSODocKey, so it cannot go through the SQL PO mapping
  (`presets.py:335-378`); S3 stages the raw read-back (STAGED, canonical None) and the push moves to S4.
  Migration 0036 applied on lane Postgres `foundryx_service_acwl` from 0035.
- S4 design: in-memory WRAPPER_PO / WRAPPER_SPO / WRAPPER_SO preset fields (code-keyed refs like the
  HTTP masters, not registered in `HTTP_PRESETS`, no DB seeding) mapped by the unchanged
  `MappingEngine.map_document`; pre-map resolves `FromSODocKey` from staged SO rows by DtlKey and the
  SPO's PO refs from staged PO rows; companies whose PO entity is SQL-sourced skip the push (SQL re-pull
  follow-up). Pull loads SO days before PO days.
- S5: key scopes ship as module migration 0037 (`ac_pull_api_key.scopes`, backfill `["pull"]`).
- The global guard tests named in the crew brief (`test_schema_uuid_id_principle.py`,
  `test_list_pagination_limit.py`) do not exist in this repo: n/a.
- Open for later lanes: an SS key-issue screen toggle for `write_back` (the route accepts `scopes`
  now); live-company refresh through SQL re-pull; SO outstanding at live scale (AQ11).

Local resources: targeted pytest only (`-n 2` max); global guards `tests/test_schema_uuid_id_principle.py`
and `tests/test_list_pagination_limit.py` after S3 and S5. Migration checked on a lane Postgres copy.

## 7. Test report for AutoCount

`documentation/integrations/autocount/test-report-<date>.md`, one section per test id: purpose,
preconditions, before GET (relevant rows), request (method, path, body), response (status, body),
after GET, expected vs observed, PASS / FAIL. Sanitised: no keys, no customer names beyond doc numbers.
