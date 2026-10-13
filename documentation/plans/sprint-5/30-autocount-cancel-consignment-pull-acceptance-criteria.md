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

## Slice 1 - registration + canonical shape

- **AC-30-01 [BE][T]** Given the module loads, the four entity types are document entities
  (`DOCUMENT_ENTITY_TYPES`), in `ETL_ENTITY_TYPES`, `ENTITY_PROFILES` (nested `_lines`, line refs
  `{db}:{DocKey}:{DtlKey}`, no fulfilment aggregate), `CANONICAL_MODELS` and `DOCUMENT_PRESETS`. SO/PO/SPO
  are unchanged.
- **AC-30-02 [BE][T]** Given a linked document, its wire payload is exactly the agreed shape:
  - **header:** `source_ref`, `doc_no`, `doc_date`, `status`, `customer_*` or `supplier_*`, `agent_code`, `ref`, `note`, `lines`;
  - **line:** `source_ref`, `line_number`, `product_ref`/`product_code`/`product_name`, `warehouse_ref`/`warehouse_code`, `qty`, `uom`, `unit_price`, `line_total`, `from_doc_type`, `from_doc_no`, `from_doc_line_key`.
- **AC-30-03 [BE][T]** Given an optional field that is `None`, `""` or `[]`, it is omitted from the payload, never sent as `null`. A
  real `0` is kept. The payload is the same at every connection `contract_version`.
- **AC-30-04 [BE][T]** Given `FromDocDtlKey` is empty, `from_doc_line_key` is absent while `from_doc_no`,
  `product_code`, `warehouse_code` and `qty` are still on the line (the CRM's match key).
- **AC-30-05 [BE][T]** `status` stays in the five-word vocabulary; duplicate line refs reject the document.

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
  - Cancel SO maps to `open` with prefixed refs;
  - a voided (`Cancelled='T'`) Cancel PO maps to `cancelled`;
  - a CG consignment has no `from_*`;
  - a return points at `CG` + its CG number;
  - a line without `ItemCode` is a named mapping error.

## Slice 3 - delivery behind contract 2.8

- **AC-30-20 [BE][T]** Each entity posts to its own plural `/ingest/<path>`, and is accepted only when
  the consumer advertises contract >= 2.8 AND the path name in `entities`. Without that, the company sink
  falls back to logging, and the entities are absent from the operator "supported entities" sentence.
- **AC-30-21 [BE][T]** Given a Sorento company whose consumer is below 2.8, `auto_push` refuses the run
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
