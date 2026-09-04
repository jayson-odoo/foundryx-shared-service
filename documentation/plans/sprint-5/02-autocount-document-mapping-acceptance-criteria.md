# 02 - AutoCount document mapping to Sorento import parity (SO / PO / SPO) - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-5/02-autocount-document-mapping.md`
> **Builds on:** `sprint-4/22-autocount-db-etl.md` (sql_db tasks, fixed line convention, documents
> skip deletes), `sprint-5/01-autocount-db-company.md` (DB companies, prerequisite card),
> `sprint-4/22-autocount-db-etl-autocount-sql.md` (the SO/PO SQL pack).
> **Target:** an SO/PO/SPO synced from AutoCount's DB lands in Sorento with the SAME result as
> Sorento's xlsx "outstanding" import (`scm/outstanding_import_service.py` on Sorento origin/main
> b9150f49), then keeps it current (create / update / delete, header AND line).
> **Cross-repo:** the Sorento-side changes are a separate addendum
> (`02-autocount-document-mapping-sorento-addendum.md`) built by the Sorento session. ACs that
> depend on it are tagged `[XR]` and are DEFERRED until Sorento lands them.
> **Source of decisions:** grill 2026-09-04/05 (Q1-Q15, §Decision Log).

## Scope

**In (this repo):** operator-editable LINE mapping (persisted `scope='line'` rows) with its own
source-column list; SO/PO/SPO mapping presets seeded from the SQL pack; configurable header
`status` formula with line aggregates; `shipping_order` as its own entity (own query, filter
formula, mapping, sink `shipping_orders`); Simulate over real header + lines; document delete
propagation via Sorento `/deletions`; code+name fallback fields on every document so Sorento can
back-create masters; migration of the three Query-tab line pickers into line rows; the AutoCount
preset queries on the Query tab.

**Out:** Sorento-side changes (addendum). GRN. Stock. Write-back to AutoCount (BL-SS-042).

## Definitions

- **Header row / line row** - an `ac_field_mapping` row with `scope='header'` / `scope='line'`.
- **Line source columns** - the result columns of the task's saved `lineQuery`, persisted on the
  task as `line_result_columns` (like `result_columns` for the header).
- **Line aggregates** - per-header facts computed from the mapped lines, available to header
  formulas: `lines.count`, `lines.open_count` (lines whose `qty_outstanding` > 0),
  `lines.ordered_sum`, `lines.fulfilled_sum`, `lines.outstanding_sum`.
- **Filter formula** - a per-task boolean formula over header columns; a header evaluating false
  is skipped (never staged, never counted as a delete).
- **Family** - `purchase_order` vs `shipping_order`, decided by each task's filter formula;
  default mirrors Sorento's `doc_family` (`DocNo` upper-trimmed startswith `SPO-`).
- **Fallback fields** - code+name columns Sorento may use to back-create a master when the
  `*_ref` does not resolve: header `customer_code`, `customer_name`, `supplier_code`,
  `supplier_name`, `agent_code`; line `product_code`, `product_name`, `warehouse_code`.

---

## Group A - Line mapping is operator-editable `[BE]`

### AC-02-01 `[BE]` Line rows persist with scope
**Given** `PUT /companies/{id}/entities/{entity}/mapping` for a document entity
**When** rows carry `scope: 'line'`
**Then** they persist as `ac_field_mapping.scope='line'`, distinct from header rows with the same
`canonical_field` (e.g. `currency` on PO header and PO line)
**And** `delete_by_canonical` / `delete_unknown` are scope-aware (a header re-map never deletes a
line row).

### AC-02-02 `[BE]` Line accepted-field catalog
**Given** `GET .../mapping` for `sales_order` / `purchase_order` / `shipping_order`
**Then** the response carries `lineSorentoFields` (canonical line fields incl. `source_ref`
required, `product_ref` required, `warehouse_ref`, quantities, money, dates, `uom`, the fallback
fields) and `lineAcFields` = the task's persisted `line_result_columns`
**And** `sorentoFields` (header) gains the header fallback fields.

### AC-02-03 `[BE]` Line ref pairing + required guard
**Given** a save with line rows
**Then** `product_ref` ↔ `ref_product`, `warehouse_ref` ↔ `ref_warehouse` are a locked pair (422
otherwise), `source_ref` (line key) and `product_ref` and `qty_ordered` are required when any
line row is saved (422 naming the missing field), and only fields in `lineSorentoFields` are
accepted (422 otherwise).

### AC-02-04 `[BE]` Runs use the persisted line rows
**Given** a document task with saved line rows
**When** an extract / activation preview / push runs
**Then** `build_mapping_rows_for_run` = header rows + persisted line rows (the fixed
`document_line_rows` convention is GONE) and the line key row composes
`{header_source_ref}:{DtlKey}` exactly as before.

### AC-02-05 `[BE]` Migration of the three pickers
**Given** an existing document task whose `source_config` carries `lineKeyColumn` /
`lineProductColumn` / `lineWarehouseColumn`
**When** the module migration runs
**Then** three line rows are created (`→source_ref` string, `→product_ref` ref_product,
`→warehouse_ref` ref_warehouse) once, idempotently, and the three keys are removed from
`source_config`
**And** `validate_source_config` no longer requires them.

### AC-02-06 `[BE]` `line_result_columns` persisted on the task
**Given** a successful line-query preview at save time
**Then** the task stores `line_result_columns` (name + type) alongside `result_columns`
**And** line rows' source columns are validated against it on save (422 "Test the line query
first" when absent).

## Group B - Status formula + line aggregates `[BE]`

### AC-02-07 `[BE]` Line aggregates available to header formulas
**Given** a header row with a formula referencing `lines.count`, `lines.open_count`,
`lines.ordered_sum`, `lines.fulfilled_sum`, `lines.outstanding_sum`
**When** the engine maps a document
**Then** the aggregates are computed from the mapped lines of THAT header (outstanding =
`qty_ordered - qty_delivered|qty_received`, floor 0) and substituted
**And** the formula catalog (`GET .../mapping/functions`) lists them as variables for document
entities.

### AC-02-08 `[BE]` Default status formula
**Given** a document task born from the preset
**Then** its `status` row carries the formula
`if(Cancelled == "T", "cancelled", if(lines.open_count == 0, "closed", "open"))`
**And** the output vocabulary stays `open|partial|fulfilled|closed|cancelled` (422 at save for a
literal outside it; runtime = record failed).

### AC-02-09 `[BE]` Formula functions
**Then** the formula engine provides `startswith(text, prefix)`, `upper`, `trim`, `coalesce`
(add any missing) with parity in the frontend catalog.

## Group C - Shipping orders `[BE]`

### AC-02-10 `[BE]` `shipping_order` entity
**Given** the autocount module
**Then** `ENTITY_SHIPPING_ORDER = "shipping_order"` exists: `sql_db`-only, document profile,
canonical `CanonicalShippingOrder` (+ line) per the Sorento addendum's `shipping_orders` schema,
sink path `shipping_orders`, in `_DEPENDENT_ENTITIES`, in the DB company add-entity set (ten),
parity test updated.

### AC-02-11 `[BE]` Filter formula per document task
**Given** a document task's `source_config.filterFormula`
**When** an extract runs
**Then** headers evaluating false are skipped before line fetch, never staged, never delete
candidates, and the run summary counts them (`skipped_by_filter`)
**And** the preset seeds PO with `not(startswith(upper(trim(DocNo)), "SPO-"))` and SPO with
`startswith(upper(trim(DocNo)), "SPO-")`.

### AC-02-12 `[BE]` Overlap warning
**Given** a company with both `purchase_order` and `shipping_order` tasks
**When** the activation preview runs for either
**Then** a header whose `source_ref` was staged by the OTHER task in its last run is reported as a
warning (`overlapping_documents`), never blocking.

## Group D - Deletes + fallback fields `[BE]`

### AC-02-13 `[BE]` Document deletes propagate
**Given** a reconcile run for a document task
**When** a previously-seen header `source_ref` is absent from the extract (and not filtered out)
**Then** a delete intent is staged and pushed to `POST /ingest/{entity}/deletions` (the
plan-22 "documents skip deletes" branch is removed); the delete guard (`> max(20% known, 50)` →
run fails) applies
**And** a header still present with `Cancelled='T'` is a status update, not a delete.

### AC-02-14 `[BE]` Fallback fields on the wire
**Then** `CanonicalSalesOrder/PurchaseOrder/ShippingOrder` SINK_FIELDS include the header
fallback fields and their lines include the line fallback fields; the preset maps them
(`DebtorCode→customer_code`, `DebtorName→customer_name`, `CreditorCode/Name`, `SalesAgent /
PurchaseAgent → agent_code`, line `ItemCode→product_code`, `Description→product_name`,
`Location→warehouse_code`)
**And** `[XR]` Sorento accepts them (addendum) - until then the sink OMITS them from the payload
behind a per-sink capability flag (`sorento_contract_version`), so nothing 422s today.

### AC-02-15 `[BE]` Never emit `partial` by default
**Then** the default status formula never yields `partial`; `partial`/`fulfilled` remain valid
outputs for operators who opt in (documented in the formula catalog description).

## Group E - Presets `[BE]`/`[FE]`

### AC-02-16 `[BE]` Preset seed on entity birth
**Given** a DB company and a first task save for `sales_order` / `purchase_order` /
`shipping_order` with an empty mapping
**Then** header + line rows are seeded from the AutoCount preset (SQL pack): SO header
`DocNo→so_number`, `DebtorAutoKey→customer_ref (ref_customer)`, `SalesAgent→sales_agent_ref`,
`DocDate→doc_date (date)`, `RequestedDeliveryDate→requested_delivery_date (date)`,
`Note→internal_note`, `status (formula)`, fallback fields; SO lines `DtlKey→source_ref`,
`ItemAutoKey→product_ref`, `LocationAutoKey→warehouse_ref`, `Qty→qty_ordered`,
`TransferedQty→qty_delivered`, `UnitPrice→unit_price`, `DiscountAmt→discount`,
`SubTotal→line_total`, `UOM→uom`, `DeliveryDate→required_date`, fallback fields; PO/SPO
analogues (`unit_cost`, `qty_received`, `currency` with `coalesce(UDF_Currency, CurrencyCode,
"CNY")`, `FromSODocList→from_so_numbers` `[XR]`)
**And** seeded rows are ordinary editable rows (delete/re-map allowed)
**And** a row whose source column is absent from the saved query is seeded DISABLED (visible,
greyed, "column not in query").

### AC-02-17 `[FE]` Query-tab presets
**Given** the Query tab of a document task on a DB company
**When** the operator opens "Use preset"
**Then** a `SearchSelect` offers "AutoCount SO", "AutoCount PO", "AutoCount SPO" (per entity)
and inserting one fills header query + line query + `keyColumns/watermark/docDate/fromDate`
defaults, replacing `AED_SORENTO` with the company's `database_name`
**And** the preset header query includes the `l.*` aggregates only as helper columns; status is a
formula, not SQL (the CASE from the SQL pack is dropped).

## Group F - Mapping tab UI `[FE]`

### AC-02-18 `[FE]` Two sections
**Given** the Mapping tab for a document task
**Then** it renders "Header fields" and "Line fields" sections, each the existing
`MappingTable` (Source column · Transform · f · Sorento field · delete, Add field), lines fed by
`lineAcFields` / `lineSorentoFields`
**And** a master/GRN task shows the single section unchanged.

### AC-02-19 `[FE]` Line pickers leave the Query tab
**Then** the Query tab's Line key / Line product / Line warehouse pickers are removed; the line
block keeps Line query + Test line query + preview grid + a "Filter" formula field (with `f`
builder) for the family filter.

### AC-02-20 `[FE]` Status row formula builder knows aggregates
**Given** the `f` builder on a header row of a document task
**Then** the variable list includes the five `lines.*` aggregates (grouped "Line aggregates")
and the status vocabulary is offered as literals.

### AC-02-21 `[FE]` Disabled/seeded rows
**Then** a seeded row whose column is missing renders greyed with a source picker to fix it; a
row toggles enabled on pick; unmapped REQUIRED targets show the existing warning banner for
header and line separately.

### AC-02-22 `[FE]` Simulate over real data
**Given** "Simulate mapping" on a document task
**When** the header preview has rows
**Then** the simulator picks a header row (SearchSelect over preview rows by key), fetches its
lines via the line query bound `:doc_key`, runs header + line mapping + formulas (aggregates
included), and renders header fields, line rows, computed `status`, and the exact Sorento payload
JSON; errors per field as today.

### AC-02-23 `[FE]` Responsive
**Then** Mapping tab (both sections), Query tab, Simulate dialog usable at 375px and 1280px.

## Group G - Tests `[T]` / `[E2E]`

### AC-02-24 `[T]` Backend
Line rows persist/scope-aware delete; catalog incl. fallback fields; ref pairing + required
guards; runs use persisted rows (fixed convention removed); picker migration idempotent;
`line_result_columns`; aggregates matrix (0 lines, all open, all fulfilled, mixed, cancelled);
default formula outputs; `startswith/upper/trim/coalesce`; `shipping_order` registration + sink
path + parity; filter formula skip + counts; overlap warning; document delete staging + guard +
deletions push; SINK_FIELDS gated by contract flag; preset seed (all three entities, disabled
rows for missing columns); `partial` never default. Full `test_autocount*` green.

### AC-02-25 `[T]` Frontend
Two-section mapping tab; line pickers gone + filter field; aggregates in builder; disabled seeded
rows; simulate with lines; presets dialog. Vitest green.

### AC-02-26 `[E2E]` Real-click journey
DB company (plan-01 spec rig) → Add entity → Sales order → Query tab → Use preset → Test query +
Test line query → Save → Mapping tab shows seeded header + line rows → Simulate on a preview
header → status + lines rendered → Review & Activate preview passes. Dedicated tenant,
timestamped, purged.

## Group H - Definition of Done `[T]`

- No frontend mock left; real endpoints live-verified via `agent-browser` at 375/1280.
- Backfill: picker migration for existing document tasks (AC-02-05); existing masters/GRN
  untouched.
- No hardcoded tenant-editable key.
- No new permission.
- The Sorento addendum sent; `[XR]` ACs listed DEFERRED in the test report with the addendum
  item that unblocks each.

---

## Decision Log (grill 2026-09-04/05)

| # | Decision |
|---|---|
| Q1 | Line mapping operator-editable, persisted `scope='line'`. |
| Q2 | Presets (SQL pack) seed header + line rows and Query-tab queries. BL-SS-045 pulled in. |
| Q3→Q7 | Target = parity with Sorento's xlsx outstanding import, not raw tables; addendum for the delta. |
| Q4/Q9 | Header status = configurable formula with line aggregates; default cancelled/closed/open. |
| Q5 | Three Query-tab line pickers become line rows (one-time migration). |
| Q6 | Simulate runs header + lines from real preview data. |
| Q8/Q13 | Masters may be unreadable; documents carry code+name fallbacks; Sorento back-creates. |
| Q10/Q14 | `shipping_order` = separate entity, own query/filter/mapping/sink; default = `SPO-` prefix. |
| Q11/Q15 | Create/update/delete at header + line; AutoCount is truth; Sorento hard-deletes or cancels-in-place when referenced. |
| Q12 | Slice A (this), B (wire XR fields when Sorento lands), C (Sorento addendum). |
