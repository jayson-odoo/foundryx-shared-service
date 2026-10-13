# 30 - AutoCount cancel / consignment pull - acceptance criteria

Lane AC-CANCEL-PULL (CRM side: lane AC-CANCEL-CRM, contract 2.8).

The `sql_db` source pulls four more AutoCount document types for a book (first: SORENTO) the same way
SO/PO/SPO are pulled, and pushes them to the CRM behind contract 2.8:

| Entity | AutoCount tables | Party | CRM ingest path |
|---|---|---|---|
| `cancel_sales_order` | `XS` / `XSDTL` | Debtor | `cancel_sales_orders` |
| `cancel_purchase_order` | `XP` / `XPDTL` | Creditor | `cancel_purchase_orders` |
| `consignment` | `Consignment` / `ConsignmentDTL` (CG-, no source doc) | Debtor | `consignments` |
| `consignment_return` | `ConsignmentReturn` / `ConsignmentReturnDTL` (FromDocType `CG`) | Debtor | `consignment_returns` |

Schema facts: read live, read-only, on 2026-10-13 (column names and counts only). All four headers have
`LastModified datetime NOT NULL`, so that is the incremental cursor, as for SO/PO. Mocha shares the
same column names but is out of scope here (API-only).

Tests: `service_backend/tests/test_autocount_linked_documents.py` (T).

## Slice 1 - registration + wire shape

Rework 2026-10-13 (crew audit at 336df54d, CRM #1623): the wire is the DO/GRN doc-feed shape the CRM already
ingests, not a snake_case canonical one. The typed canonical fields remain the MAPPING layer only (Mapping tab,
required fields, mapping errors).

- **AC-30-01 [BE][T]** Given the module loads, the four entity types are document entities
  (`DOCUMENT_ENTITY_TYPES`), and are registered in:
  - `ETL_ENTITY_TYPES`;
  - `ENTITY_PROFILES` (nested `_lines`, raw row kept in `source_record`);
  - `CANONICAL_MODELS`;
  - `DOCUMENT_PRESETS`.

  SO/PO/SPO are unchanged.
- **AC-30-02 [BE][T]** Each record's `source_ref` is the CRM's own derivation `{book}:{XS|XP|CSGN|CSGR}:{DocKey}`, where
  `book` is the book of the company's own Delivery Orders (else Goods Receive Notes) feed. `SqlDbSource` row hashes
  and delete intents key on the same string. A company with no doc-feed book is a named identity error at mapping
  and a named error at push, never a guess.
- **AC-30-03 [BE][T]** Each wire record is the AutoCount header row under its own PascalCase column names, with its
  lines under `Details` (always present, `[]` when there are none):
  - the ESB-internal join and fingerprint columns (`*AutoKey`, `LineCount`, `QtySum`, ...) are stripped;
  - decimals are JSON numbers;
  - datetimes are the vendor's naive MYT `YYYY-MM-DDTHH:MM:SS.fff`;
  - `Note` is cut at 4000 chars.

  The body is `{companyCode, book, records}`.
- **AC-30-04 [BE][T]** Every line carries `DocKey`, `DtlKey`, `ItemCode`, `Location`, `Qty` and the link columns
  `FromDocType`/`FromDocNo`/`FromDocDtlKey` (the CRM's match key when `FromDocDtlKey` is empty).
- **AC-30-05 [BE][T]** `status` stays in the five-word vocabulary. Duplicate line refs reject the document.
- **AC-30-06 [BE][T]** Given a document deleted in AutoCount (a reconcile delete intent), it is sent to
  `/ingest/<path>/deletions` as `{doc_date_from, doc_date_to, doc_keys}`:
  - the window is the task `fromDate` (else `2023-01-01`) to MYT today;
  - a `deleted`/`deactivated`/`not_found` verdict marks it handled.

  Owner ruling: a deleted cancel document must lower the CRM's cancelled qty.

## Slice 2 - mapping catalogue + presets

- **AC-30-10 [BE][T]** Header catalogue = the model's wire fields minus the minted `source_ref`; `doc_no`
  required. Line catalogue = the line wire fields; `source_ref`, `product_code`, `qty` required
  (`product_ref` optional, so an unsynced item master never quarantines a line the CRM can match by code).
- **AC-30-11 [BE][T]** Each preset reads only its own tables (`{database}.dbo.<Header>` / `<Line>`),
  keys on `DocKey`, cursors on `LastModified`, floors on `DocDate`, binds `:doc_key` on the line query and
  `:from_date` on the fingerprint sweep. It applies the SAME `ItemCode IS NOT NULL AND Qty IS NOT NULL` cut in the
  header `LineCount` aggregate and the line fetch, and selects `FromDocType`/`FromDocNo`/`FromDocDtlKey`.
- **AC-30-12 [BE][T]** XS / Consignment / ConsignmentReturn read the Debtor columns, XP the Creditor
  columns; every preset row targets a catalogue field and covers every required field.
- **AC-30-13 [BE][T]** Fake rows map end to end through the real engine:
  - Cancel SO maps to `open` under `{book}:XS:{DocKey}`, and its wire record equals the golden record;
  - a voided (`Cancelled='T'`) Cancel PO maps to `cancelled`;
  - a CG consignment has no `from_*`;
  - a return points at `CG` + its CG number;
  - a line without `ItemCode` is a named mapping error.

## Slice 3 - delivery behind contract 2.8

- **AC-30-20 [BE][T]** Each entity posts the doc-feed envelope to its own plural `/ingest/<path>`, and is accepted only when
  the consumer advertises contract >= 2.8 AND the path name in `entities`. Without that, the company sink
  falls back to logging, and the entities are absent from the operator "supported entities" sentence.
- **AC-30-21 [BE][T]** Given a Sorento company whose consumer is below 2.8, `auto_push` AND `approve()` refuse the run
  with `errorCode CONTRACT_GATE` and every row stays STAGED. It never "delivers" through the logging
  fallback, which would mark rows pushed and lose them.
- **AC-30-22 [BE][T]** The task view's contract banner knows the 2.8 requirement; missing customer/supplier/
  product masters raise the same prerequisite warning as SO/PO.

## Slice 4 - frontend entity lists

- **AC-30-30 [FE][T]** A database company's Add-entity picker offers the four new entities
  (`AC_SQL_DB_ENTITY_TYPES`, parity-pinned to the backend). `isDocumentEntity` routes them to the
  header+line task editor. The mock service carries the same presets/prerequisites.

## Out of scope

- Mocha (API-only, no endpoints for these documents).
- The CRM ingest (lane AC-CANCEL-CRM).
- A per-book TLS 1.0 connection option (Mocha login): needs its own lane on the `sql_database` provider.
- Filtering XSDTL package-parent lines (`DtlType='P'`): not filtered, matching the SO preset; an
  operator can add the cut per task.
