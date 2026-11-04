# 57 - AutoCount write-back phase 2: Quotation and Sales Order create, edit, cancel

Lane AC-WRITE-QTSO, size L, LEAD pattern. Status: STEP 1 (study + behaviour card). No write call made
yet. Builds on plan 55 (phase 1, PR #183: `service_backend/modules/autocount/write_back/`). UAC
(`57-autocount-write-qtso-acceptance-criteria.md`) is written after the owner answers the card.

Owner rules carried from phase 1 (4 Nov): writes reach `db3` only (code guard `write_back/guard.py:15`);
never delete an AutoCount document, cancel instead; every write = guard -> fresh GET -> pure payload
builder -> POST / PUT -> GET back -> result = what AutoCount returned; a capability flag for anything
AutoCount does not support (`write_back/capabilities.py:17`); every db3 probe recorded exactly
(request / response / before / after) in the AutoCount test report; real customer data never in the repo.

## 1. Vendor surface for QT / SO (hapi wrapper, base `.../api/<db>`)

| Door | Method | Path | Source | State on db3 |
|---|---|---|---|---|
| New quotation | POST | `/NewQuotation` | vendor notes | vendor test docs QT-004193 / QT-004194 exist; we have not called it |
| Edit quotation | PUT | `/EditQuotationbydockey` | vendor notes | vendor edited QT-004194; we have not called it |
| New sales order | POST | `/NewSalesOrder` | vendor notes | ours: FXT-1104d-SO (DocKey 12038), FXT-1104e-SO (12049), 200, rows read back as sent |
| Edit sales order | PUT | `/EditSalesOrderbydockey` | NOT in vendor notes (name by analogy) | UNVERIFIED |
| Cancel QT / SO | ? | ? | NOT in vendor notes (AQ2) | UNVERIFIED |
| Read QT | GET | `/quotationbydocdate`, `/quotationbyLastModified` | plan 55 section 2 | 200; no reader in code yet (`write_back/reader.py:33-38` covers PO / SO only) |
| Read SO | GET | `/salesorderbydocdate`, `/salesorderbyLastModified` | `write_back/constants.py:9,11` | 200 |

Known behaviour (phase 1 test report `documentation/integrations/autocount/test-report-2026-11-04.md`):
- A create body needs the full header (`DisplayTerm`, `CurrencyCode`, `CurrencyRate`); a short body can
  answer 200 and drop the rows (report lines 86, 118, 613).
- A PUT keeps rows it does not list (QT-004194 kept 3 rows after a 1-row edit; P6 on a PO); no known way
  to remove a row. Some fields on existing rows are ignored (link fields); qty and location apply (P4).
- Dates before 1753 must be omitted (500 SqlDateTime overflow).
- The SO GET header carries `Cancelled` ("T" / "F") and `DocStatus` (fixture
  `tests/fixtures/autocount_write_back/so_SO389293.json:5`). A QT GET sample does not exist yet.
- AutoCount's own Web API (a different wrapper, `documentation/api/autocount/SL AutoCount API.postman_collection.json`)
  cancels with `POST /api/Quotation/CancelQuotation` and `/api/SalesOrder/CancelSalesOrder`, body
  `{"DocNo": [...], "Cancelled": true}`. So the AutoCount engine cancels a whole document by its header
  `Cancelled` flag; whether the hapi edit PUT passes that flag through is the probe below.
- Sorento also cancels SO outstanding qty with separate Cancel SO (XS) documents, which the CRM ingests
  (`sorento_crm_backend/app/services/autocount_cancel_ingest_service.py:1-30`, origin/main 13231ee308).
  The hapi has no door to create one.

## 2. CRM project sales today (sorento-crm origin/main 13231ee308, read only)

- QT: `projects.quotation_documents` (Document -> priced scope -> Version -> Line,
  `app/models/projects.py:1169,1760,1818,1864`), CRM numbering `QT-2026-0001`; no AutoCount field, no
  ingest. Lines carry product code, uom, qty, unit price, an `is_discounted` flag only (no discount
  amount, no location). No cancel action: Lost outcome (`api/v1/projects/quotations.py:213`) or hard
  delete before issue (`quotation_documents.py:291`).
- SO: `ProjectSalesOrder` (`app/models/project_so.py:441`), statuses draft..published..adopted
  (`:406-421`); publish today returns a CSV import file (`project_so_draft_service.py:2668-2759`, "the
  ESB call replaces this transport in stage 2"); after publish, edits are amendments
  (`api/v1/projects/sales_orders.py:833,874`, producing an "AutoCount change list" xlsx at `:949`).
  `autocount_doc_no` is set only when an ingested AutoCount SO is adopted
  (`project_so_adoption_service.py:390`). No cancel action (DELETE refuses published, `:386`).
- CRM -> SS client: `app/services/foundryx_autocount_client.py` (X-API-Key, read-only routes today).

## 3. Use cases (to confirm on the card)

- UC-6 Create QT: POST `/NewQuotation` -> read back by DocDate (filter DocKey) -> return DocKey / DocNo /
  DtlKeys.
- UC-7 Edit QT: PUT `/EditQuotationbydockey`, full header + rows by DtlKey (0 adds).
- UC-8 Cancel QT: PUT `/EditQuotationbydockey` header `Cancelled "T"` IF the db3 probe shows it applies;
  else capability flag off, refused `VENDOR_UNSUPPORTED`, AutoCount question.
- UC-9 Create SO: POST `/NewSalesOrder`, rows optionally `FromDocType "QT"` + QT DtlKey.
- UC-10 Edit SO: PUT `/EditSalesOrderbydockey` IF the db3 probe shows the door exists and applies.
- UC-11 Cancel SO: as UC-8 on the SO door.
- Never: delete; uncancel unless the owner asks.

## 4. db3 probes (before any code; each recorded exactly)

Only on documents this lane creates (DocNo prefix `FXT-`), never on AutoCount's test set.
P-QT1 create QT full body; P-QT2 edit header fields + one row price/qty + add a row; P-QT3 PUT a row
not listed (kept?) and qty 0 (accepted?); P-QT4 `Cancelled "T"` on the edit PUT; P-SO1 PUT
`/EditSalesOrderbydockey` (exists?); P-SO2 SO edit header + row; P-SO3 `Cancelled "T"` on the SO;
P-SO4 cancel an SO whose row a PO links to (refused?); P-DOC DocNo omitted / `<<New>>` (AutoCount
numbering?).

## 5. Steps

Card (crew `--ask`) -> owner answers -> UAC + section 6 design -> db3 probes -> tester red tests ->
coder -> reviewer + security-reviewer -> live db3 suite -> test report + AutoCount questions -> PR.
