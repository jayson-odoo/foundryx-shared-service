# 02 - AutoCount document mapping to Sorento import parity (SO / PO / SPO)

> **Status:** DRAFT - fulfils `02-autocount-document-mapping-acceptance-criteria.md` (AC-02-01..26).
> **Branch:** `sprint-5/autocount-document-mapping`.
> **Cross-repo:** `02-autocount-document-mapping-sorento-addendum.md` (Sorento session builds it).
> **Backlog:** closes BL-SS-080 (presets); adds BL-SS-084..051 (below).

## 1. Problem

An operator configuring an AutoCount SO/PO task sees seven header targets and no line mapping
at all: line fields ride a hidden exact-column-alias convention (`document_line_rows`), nothing
is seeded, the free-form picker allows wrong pairings (`DebtorCode → customer_ref` retries
forever), Simulate never runs lines, and documents never propagate deletes. Meanwhile Sorento's
xlsx outstanding import already produces the desired result; the ESB must match it from the DB
and then keep it current. Sorento's ingest already accepts everything the xlsx import writes
except a small delta (debtor code, demand classification, `FromSODocList` pairing, shipping
orders, CNY default, back-create, post-write hooks) - that delta is the addendum.

## 2. Design

### 2.1 Line rows are first-class (AC-02-01..06)
- `AcFieldMapping.scope` already exists and is in the unique key. Add `scope` to
  `MappingUpdateRow` / `MappingWriteRow` (default `header`).
- `FieldMappingRepository.delete_by_canonical(...)` / `delete_unknown(...)` gain a `scope`
  parameter; `replace_mapping` runs the guard set per scope.
- `mapping_catalog.SORENTO_LINE_FIELDS[entity]` = `<Line>.SINK_FIELDS` with required
  `{source_ref, product_ref, qty_ordered}`; `FIELD_REF_TRANSFORMS` gains `product_ref →
  ref_product`, `warehouse_ref → ref_warehouse` (line scope). `MappingViewResponse` +=
  `lineSorentoFields`, `lineAcFields`.
- `AcEntityConfig.line_result_columns` (JSON, nullable; module migration 0010). `EtlService.
  update_task` stores the line preview's columns when the line query is saved; save-time
  validation of line rows' `source_path` against it.
- `document_line_rows()` deleted; `build_mapping_rows_for_run` = header rows + persisted line
  rows. The `line_ref_prefix` composition (`{header_ref}:{DtlKey}`) stays in `MappingEngine`.
- Migration 0010 also converts `lineKeyColumn/lineProductColumn/lineWarehouseColumn` into three
  line rows per existing document task and strips the keys (idempotent: skip when a
  `scope='line', canonical_field='source_ref'` row exists).

### 2.2 Line aggregates + status formula (AC-02-07..09, 15)
- `MappingEngine.project_document`: after mapping lines, compute
  `lines.count/open_count/ordered_sum/fulfilled_sum/outstanding_sum` (fulfilled column by
  entity: `qty_delivered` SO, `qty_received` PO/SPO) and inject them into the header formula
  scope under the `lines` namespace. Header formulas are evaluated AFTER lines (reorder the two
  passes; today header runs first).
- `formula.py`: add `startswith`, `coalesce`, `not`; FE catalog mirror (`lib/autocount-formula-
  catalog` / builder). Formula catalog endpoint lists the aggregates as variables for document
  entities (`scope: "aggregate"`).
- Default status formula seeded by the preset:
  `if(Cancelled == "T", "cancelled", if(lines.count == 0, "open", if(lines.open_count == 0, "closed", "open")))`. Save-time:
  string literals in a `status` formula must be in the vocabulary (422).

### 2.3 Shipping orders (AC-02-10..12)
- `canonical/documents.py`: `ENTITY_SHIPPING_ORDER`, `CanonicalShippingOrder` /
  `CanonicalShippingOrderLine` (header `spo_number`*, `supplier_ref`, `issue_date`,
  `expected_date`, `currency`, `status`, fallbacks; Sorento stores it as a LINE-SET on
  `spo_allocations` with `source_doc_ref`=DocKey, header verdict `entity_id: null` - the sink's
  verdict parser must accept that; line `source_ref`*, `product_ref`*,
  `warehouse_ref`, `qty_ordered`*, `qty_received`, `unit_cost`, `uom`, `expected_date`,
  `from_so_numbers[]` `[XR]`, fallbacks) - exact shape per addendum §3. Profile, `_DEPENDENT_
  ENTITIES`, sink path `shipping_orders`, `ENTITY_PROFILES`, `AC_SQL_DB_ENTITY_TYPES` (ten),
  terminology + parity tests.
- `source_config.filterFormula` (optional) on every document task; `SqlDbSource._read` evaluates
  it per header BEFORE `_read_lines`; skipped headers excluded from the seen-set used by delete
  detection; `run.summary.skipped_by_filter`.
- Overlap warning: activation preview compares the task's staged header refs with the sibling
  task's `ac_row_hash` refs (same company, other family) → `warnings.overlapping_documents`.

### 2.4 Deletes + fallback fields (AC-02-13, 14)
- `sql_source/source.py`: remove the `not self.is_document` exclusion from the delete block;
  `sync._stage_deletes` stages document deletes; `SorentoSink.delete_batch` already posts
  `/ingest/{entity}/deletions`; Sorento serves it for `sales_orders`/`purchase_orders` today,
  `shipping_orders` is `[XR]` (a 404 `UNKNOWN_ENTITY` from `/deletions` maps to `retryable`,
  not `failed`).
- Canonical documents gain the fallback fields; the AUTHORITATIVE contract version is the
  consumer connection config `sorento_contract_version` (default `1`, operator-flipped).
  `GET /api/v1/external/contract` is ADVISORY only: `SorentoSink` reads it at construction and the
  activation preview reports `warnings.contract_version_mismatch` when Sorento advertises a higher
  version than the connection is set to (Sorento's endpoint advertised `2` while their v2 slices
  were still landing - flipping on the endpoint alone would have sent v2 fields to a half-built
  consumer). `sink_payload(contract_version)` drops
  `[XR]` fields (`customer_code/name`, `supplier_code/name`, `agent_code`, line
  `product_code/name`, `warehouse_code`, `from_so_numbers`, `line_number`) below version `2`.
  `line_number` (AutoCount `Seq`) exists so Sorento can adopt an xlsx-era ref-less line by
  position (AC-02-27; Sorento side = addendum §9). Flipping the
  connection to `2` when Sorento lands = slice B.

### 2.5 Presets (AC-02-16, 17)
- `modules/autocount/presets/autocount_documents.py`: header/line SQL (from the SQL pack,
  `{database}` placeholder, CASE status removed, aggregates helper columns removed - aggregates
  come from mapped lines), `source_config` defaults, header + line mapping rows incl. formula
  rows. `seed_document_mapping(db, company, entity)` called by `EtlService.update_task` on first
  save when the mapping is empty; rows whose source column is missing from `result_columns` /
  `line_result_columns` are saved `is_enabled=false`.
- `GET /autocount/presets/{entity}` (manage-gated) returns the queries with the company's
  `database_name` substituted; FE "Use preset" SearchSelect on the Query tab.

### 2.6 Frontend (AC-02-18..23)
- `mapping-editor-body.tsx` renders two `MappingTable`s for document entities (props
  `scope`, `sourceOptions`, `sorentoFields`); `use-mapping-draft.ts` keeps one draft with
  `scope` on each row; save sends both. Required-warning per scope.
- `query-tab.tsx`: remove the three pickers; add "Filter" formula field (reuses
  `AutocountFormulaBuilder` with header columns), "Use preset" SearchSelect.
- Builder = the ONLY formula input (lavish Q16). `AutocountFormulaBuilder` gains a Variables
  panel (header columns typed from `result_columns`, line columns for line rows, `lines.*`
  aggregates grouped, status literals when the target is `status`); the table cell and the
  Query-tab Filter field render the formula read-only (`ClampedText` chip + `f`). Live
  validation rejects unknown variables (PUT 422 backstop).
- `mapping-simulator.tsx`: header-row SearchSelect (preview rows by `keyColumns[0]`), calls
  `POST .../mapping/simulate` with `{docKey}`; backend `simulate_mapping` fetches lines through
  `SqlDbSource._read_lines`, uses `flat_profile`, runs aggregates + formulas, returns
  `headerFields`, `lineFields[]`, `status`, `payload` (the exact sink JSON at the current
  contract version).
- Mock service: fixtures for line rows, aggregates, presets, simulate-with-lines.

### 2.7 Reuse
`MappingTable`, `SearchSelect`, `AutocountFormulaBuilder`, `MappingSimulator`, `Alert`,
`FormRow`. No new primitive.

## 3. Slices (this repo)

1. **S1 FE-mock**: two-section Mapping tab, Query-tab filter + preset picker, builder
   aggregates, simulator with lines, disabled seeded rows - all states via mock. Browser verify
   375/1280 with `agent-browser`.
2. **S2 BE-TDD core**: scope on write, line catalog, guards, `line_result_columns`, migration
   0010 (pickers → rows), engine aggregates + pass order, formula functions, fixed convention
   removed, simulate with lines. Swap mock → real.
3. **S3 BE-TDD documents**: `shipping_order` entity, filter formula, overlap warning, document
   deletes, fallback fields + contract-version gate, presets + seed, preset endpoint.
4. **S4 E2E + report** (AC-02-26), `[XR]` DEFERRED with addendum refs.

## 4. Tests
`tests/test_autocount_document_mapping.py` (new): AC-02-24 matrix. Update `test_autocount_
documents.py` (fixed-convention tests → persisted rows), `test_autocount_entity_parity.py`
(ten), `test_autocount_sql_db_source.py` (filter, deletes), `test_autocount_masters_fanout.py`
(sink gating). FE: mapping tab, query tab, builder, simulator, presets. E2E
`e2e/autocount-document-mapping.spec.ts`.

## 5. Risks / notes
- Header-after-lines pass order changes `MappingEngine` internals; the GRN API path also goes
  through `project_document` - keep its tests green (aggregates are additive).
- Migration 0010 = module Alembic; MUST query a frozen table snapshot (`sa.table`), never the
  live ORM (BL-SS-082 lesson).
- `line_result_columns` for existing tasks = NULL until the operator re-saves the line query;
  the Mapping tab shows "Test the line query first" for the line section until then.
- Contract-version gate defaults to `1` so today's Sorento never receives unknown fields.
- E2E relies on the plan-22 Postgres rig; the SPO filter formula is exercised with a synthetic
  `SPO-` row added to the rig's PO fixture.

## 6. Backlog
- **BL-SS-084** Wire the `[XR]` fields (contract version 2) once the Sorento addendum lands;
  flip the consumer connection default; remove the gate.
- **BL-SS-085** Cutover playbook: first AutoCount push of a document previously loaded by xlsx
  must ADOPT its ref-less lines in place (Sorento `_sync_lines`, addendum §9) so the rows stay
  identical (same ids, allocations/claims intact); only lines absent in AutoCount are
  deleted/cancelled. Document the sequence (masters → SO/PO/SPO, reconcile off until first full
  load) + a dry-run report listing adopted / unmatched lines before go-live.
- **BL-SS-086** Overlap check as a hard activation gate (today: warning).
- **BL-SS-087** Refuse a watermark column inside `keyColumns` (proof finding: composite key ->
  refs carry the watermark -> document lines never hit the ref rung on Sorento).
- **BL-SS-080** → Closed by this plan.
