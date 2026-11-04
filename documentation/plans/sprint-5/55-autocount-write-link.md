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

## 7. Test report for AutoCount

`documentation/integrations/autocount/test-report-<date>.md`, one section per test id: purpose,
preconditions, before GET (relevant rows), request (method, path, body), response (status, body),
after GET, expected vs observed, PASS / FAIL. Sanitised: no keys, no customer names beyond doc numbers.
