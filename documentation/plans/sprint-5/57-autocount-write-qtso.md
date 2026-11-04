# 57 - AutoCount write-back phase 2: Quotation and Sales Order create, edit, cancel

Lane AC-WRITE-QTSO, size L, LEAD pattern. Status: card 1 answered (4 Nov), db3 probes recorded, design below.
Rescoped by the owner (4 Nov 17:35) from QT / SO only to the whole SS AutoCount write layer. Builds on plan 55 (phase 1, PR #183: `service_backend/modules/autocount/write_back/`). UAC
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


## 3. Owner rulings (card 1, 4 Nov)

Q1 (a) SS only in this lane; CRM buttons and trigger points belong to later CRM lanes' cards. Q2 (a)
(owner, 4 Nov): fully received `ROW_RECEIVED`; partially received = cut the row to the
received qty and add the open remainder as the new row; unknown received qty: changed by the alignment notes below;
(b) "refuse any receipt" kept as a one-line switch. Q3 (a) old -> new DtlKey in the answer AND
`replacesLineRef` on the Sorento sink line. Q4 (a) delete-document primitive flag-off, no route or
operation uses it; cancel is the only way a document ends. Q5 (a) `needs_attention` + snapshot +
alert email naming the line + a resume that re-reads AutoCount and re-creates only if still absent.

Alignment notes (owner, Lavish, 4 Nov): (1) unknown received qty is NOT refused by us: "the refusal
should come from AutoCount, not us"; the delete path runs with warning `TRANSFER_STATE_UNKNOWN` and an
AutoCount refusal comes back as `VENDOR_REFUSED` with AutoCount's message; known received qty keeps rule
(a). (2) Build the available-operations feed (`GET /write-capabilities`). (3) link_row moves the new row
to the SO row's location; unlink keeps the row where it was. (4) Workflow engine question: answered in
the alignment page v2, section 8.

## 4. db3 probes (4 Nov, 15 writes, all recorded exact in crew files `autocount-api/db3-requests-qtso-4nov.json`)

| Probe | Call | Result |
|---|---|---|
| P-QT1 | POST /NewQuotation FXT-1104q-QT1 | 200, DocKey 12060, rows 12061 (HQ) / 12062 (BRW-AM) as sent; GET shows `Cancelled F`, `DocStatus A`, `ToDocType ""` |
| P-QT2 | PUT /EditQuotationbydockey | 200, ALL applied: Ref / Description / Remark1, qty, unit price, discount "5%", location, new `DtlKey 0` row 12063 |
| P-QT3 | PUT one row Qty 0 (FXT-1104q-QT4, 12064) | 200, Qty 0 stored; omitted row kept |
| P-DOC1b | POST DocNo omitted | 500 "Column 'DocNo' does not allow nulls" |
| P-DOC2 | POST DocNo `"<<New>>"` | 200, answer text `DocNo=QT-000001 ,DocKey=12069 ... Created Successful.` |
| P-DOC1 | POST (script bug: template DocNo) | created a QUOTATION numbered SO390188 (DocKey 12067); clean-up asked of AutoCount (AQ34); the real SO390188 untouched |
| P-SO0 | POST /NewSalesOrder FXT-1104q-SO1 from QT row 12061 (vendor shape incl. FullTransfer*) | 200, DocKey 12072; row `FromDocType QT`, `FromDocNo` kept, `FromDocDtlKey 0`; QT shows no back-link (AQ31) |
| P-SO1 | PUT /EditSalesOrderbydockey | door EXISTS: 200, qty / price / discount applied, new row 12075 |
| P-CX1..3 | header `Cancelled "T"` / "F" on both edit doors (FXT-1104q-QT3 12076, FXT-1104q-SO2 12078) | 200, nothing changes (AQ2, AQ32) |

The POST answer text carries the new DocNo and DocKey, so create read-back is by DocKey.

## 5. Design

Two levels. The CRM picks WHICH operation (business intent); SS owns HOW (steps, guards, recovery).
Everything stays in `service_backend/modules/autocount/write_back/`.

### 5.1 Kinds, capabilities, client

- `doc_kinds.py`: one frozen `DocKind` per kind `QT`, `SO`, `PO`, `SPO` (SPO = PO doors + header
  `ShippingPO "T"`): `new_path`, `edit_path`, `by_date_path`, `by_modified_path`, `party_field`
  (`DebtorCode` / `CreditorCode`), `delete_line` and `delete_doc` vendor shapes. The delete shapes are
  ONE placeholder entry per kind (method `DELETE`, path `/Delete<Doc>Detailbydtlkey` /
  `/Delete<Doc>bydockey`, body `{DocKey, DtlKey}`), marked UNVERIFIED (AQ23): plugging AutoCount's real
  shape in = edit this one table.
- `capabilities.py`: `CAPABILITIES[(kind, primitive)]` for primitives `create_doc`, `edit_doc`,
  `add_line`, `delete_line`, `delete_doc`, `cancel_doc`; `capable(kind, primitive)` reads the module
  table at call time. Shipped: create / edit / add on for QT, SO, PO; SPO edit on, SPO create / add off;
  delete_line, delete_doc, cancel_doc off everywhere. `AUTO_DOCNO = True` (`"<<New>>"`),
  `PARTIAL_RECEIPT_SPLIT = True` (Q2 switch). Plan 55 `link_new_row` stays; `link_existing_row`,
  `unlink`, `spo_unlink`, `ZERO_QTY_EMULATION` retire (AutoCount: a link never changes in place), their
  routes now run the operations below.
- `client.py`: `delete(path, body)` beside `post` / `put`; same guard per request, same no-retry rule.

### 5.2 Primitives (level 1)

`payloads.py` gains pure builders returning `VendorRequest(method, path, body)` or raising
`WriteRefusal(code)`: `build_create(kind, header, lines)`, `build_edit(kind, doc, header_changes,
line_changes)`, `build_add_line(kind, doc, line)`, `build_delete_line(kind, doc, dtl_key)`,
`build_delete_doc(kind, doc)`, `build_cancel(kind, doc)`; plus `parse_create_answer(text) -> (doc_no,
doc_key) | None` and verifiers `verify_create`, `verify_edit` (returns the ignored fields),
`verify_delete_line`, `verify_cancel`. Header allowlist and line field list as AC-57-14.

`primitives.py`: `PrimitiveService(db, tenant_id, company)` with `create_doc`, `edit_doc`, `add_line`,
`delete_line`, `delete_doc`, `cancel_doc`. Each = the plan 55 frame generalised from the PO door to the
kind table (`service.py:327-675`): guard -> capability -> busy -> fresh GET (reader extended to QT) ->
stale (`DOC_STALE`) -> guards (AC-57-18) -> build -> commit the action row -> ONE vendor call -> GET back
-> verify -> finish -> stage + push (PO / SPO / SO; QT answered only). Transfer facts for the guards:
SO rows linked by PO rows = staged PO rows' `FromSODtlKey` (`service.py:603`); delivered / received qty
= AutoCount `TransferedQty`, which the hapi GET does not return (AQ11) and which only SQL-sourced
companies stage (`presets.py:275,439,509`), so for hapi documents it is UNKNOWN.

### 5.3 Operations (level 2)

`operations.py`: `OperationService.run(op, params, idempotency_key, key_id)`; ops `link_row`,
`unlink_row`, `relink_row` (PO rows -> SO rows), `spo_link_row`, `spo_unlink_row`, `spo_relink_row`
(SPO rows -> PO rows), and plan 55 `split_link` wrapped with an idempotency key. One step table per op:

1. guards (AC-57-32, AC-57-33), all before any write;
2. snapshot = the row from the fresh GET (every field) + document LastModified, stored on the operation;
3. `delete_line` (primitive) -> read-back shows it gone;
4. `add_line` with the snapshot fields + the new link (or none) -> exactly one new row;
5. location move when the read-back location differs from the target: the SO row's location for link /
   relink, the snapshot location for unlink and for every recovery re-add (db3 forces HQ on a new linked row).

Partially received (switch on): step 3 becomes an `edit_doc` cutting the row to the received qty, and
step 4 adds the remainder (no delete needed). Recovery when step 4 fails after step 3 landed: add the
snapshot back with its old link (+ move) -> `recovered`; when that fails too -> `needs_attention`, alert
mail via `alerts.alert_recipients` (`alerts.py:400`) + outbox `enqueue_raw` (`alerts.py:550`) naming the
line, no retry. `resume(operation_id)` re-reads AutoCount and re-creates only if neither the snapshot row
nor the intended new row is present. Answer: `{operationId, outcome, errorCode, warnings,
replacedLines: [{oldDtlKey, newDtlKey}], document}`.

### 5.4 Schema (module migration `0040_autocount_write_ops`, schema `app_autocount`)

- `ac_write_operation`: id (uuid), tenant_id, company_id, key_id, idempotency_key, request_hash, op,
  doc_type, doc_key, dtl_key, status (`in_progress`, `done`, `refused`, `recovered`, `needs_attention`,
  `pending_verification`), error_code, snapshot_json, steps_json, result_json, created_at, updated_at
  (UTCDateTime). Unique (tenant_id, company_id, key_id, idempotency_key); partial unique one
  `in_progress` per (company_id, doc_type, doc_key) = the cross-step busy lock.
- `ac_write_action` + `operation_id` (nullable), `step` (nullable), `request_method`, `request_path`.
  Existing rows keep nulls (no backfill needed: nullable, read as plan 55 actions).

### 5.5 Sink

Canonical PO / SPO / SO lines gain optional `replaces_line_ref` (`{db}:{DocKey}:{DtlKey}` of the deleted
row), injected in `_premap_line` (`doc_mapping.py:126-138`) from the operation's replaced map, mapped in
the WRAPPER_* presets (`presets.py:1824-1840`), in `OMIT_WHEN_EMPTY_FIELDS`, and sent only when the
connection's advertised contract is >= `REPLACES_LINE_REF_CONTRACT_VERSION = ContractVersion(2, 12)`
(Sorento ingest uses `extra="forbid"`; CRM is at 2.11, `external/ingest.py:344`). The 2.12 number is
claimed here; renumber if another lane lands one first. Sorento consumption = a later CRM lane.

### 5.6 Gateway (`routers/pull_v1.py`, X-API-Key `write_back` scope)

`POST /documents/{kind}` create, `PATCH /documents/{kind}/{docKey}` edit, `POST
/documents/{kind}/{docKey}/lines` add line, `POST /documents/{kind}/{docKey}/lines/{dtlKey}/delete` delete
line, `POST /documents/{kind}/{docKey}/cancel` cancel (`kind` in `quotations`, `sales-orders`,
`purchase-orders`, `shipping-purchase-orders`); `POST /po-links/relink`, `POST /spo-links`,
`POST /spo-links/relink`; existing `/po-links`, `/po-links/unlink`, `/spo-links/unlink` run the
operations; `GET /write-operations/{id}`, `POST /write-operations/{id}/resume`, proposed `GET /write-capabilities`
(alignment point ii); `Idempotency-Key` header. No delete-document route. Contract doc `57-autocount-write-qtso-contract.md` (guide-writer after review).

### 5.7 Fake vendor and runner

`tests/autocount_write_back/fake_vendor.py` (test helper): an httpx MockTransport holding documents in
memory, honouring the known db3 behaviour (link only on new rows, forced HQ on new linked rows, omitted
rows kept, ignored link edits, `Cancelled` ignored, POST answer text) and the placeholder delete shape.
Every operation test runs against it. `runner.py` gains QT / SO cases; delete / cancel cases assert the
refusal with no HTTP until their flags flip.

Readiness note: turning delete on needs the flag flip + one live db3 run. Without AutoCount's
`TransferedQty` on the GET (AQ11) a hapi document's received qty is unknown, so AutoCount's own delete
refusal (AQ25) is the receipt check there (owner alignment note 1).

## 6. Slices (LEAD: tester red first, one coder continued by message, reviewer + security-reviewer)

| Slice | Scope | ACs |
|---|---|---|
| S1 | kinds, capabilities, client DELETE | AC-57-01..05 |
| S2 | pure builders, answer parser, verifiers | AC-57-10..18 (builder side) |
| S3 | migration 0040, QT reader, primitive service, exact action recording | AC-57-10..19 (flow), 73 |
| S4 | operations, idempotency, recovery, needs_attention, resume, receipt rule, fake vendor | AC-57-30..40, 71 |
| S5 | sink `replacesLineRef` + contract gate | AC-57-50..52 |
| S6 | gateway routes + contract doc | AC-57-60..63 |
| S7 | db3 runner + test report | AC-57-70, 72 |

Local resources: targeted pytest only, `-n 2` max; global guards `tests/test_schema_uuid_id_principle.py`
and `tests/test_list_pagination_limit.py` if present (plan 55 found them absent).
