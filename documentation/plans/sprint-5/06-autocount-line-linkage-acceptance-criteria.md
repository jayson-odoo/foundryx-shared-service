# 06 - AutoCount document line linkage (PO/SPO line -> SO line, SPO line -> PO line) - User Acceptance Criteria

Plan: `06-autocount-line-linkage.md`. Lane `sprint-5/06-autocount-line-linkage`
(worktree `.claude/worktrees/s35`, off `origin/main` 23ad4cc4).

Consumer: Sorento CRM (`order_link_service.claim_book_pairing`). Wire shape frozen with the
Sorento owner on 2026-09-08 (session `sorento-crm-2b`): per PO / SPO line the ESB emits
`from_so_line_ref`, `from_so_external`, `from_so_numbers`, `from_po_line_ref`, `from_po_number`,
with `product_code` beside them; comma lists are split on the ESB side; the ESB resolves nothing
into Sorento ids; no FOC fields. Sorento declares the four new names under contract **2.2**
(`extra="forbid"` on their side: an undeclared name rejects the whole record).

Live facts the criteria rest on (probe against AED_SORENTO, 2026-09-08, read-only):
`PODTL.FromSODtlKey` is populated on 20,802 of 37,692 PO lines since 2025 (`FromSODocList`
on the same rows; `UDF_SOList` on none; ICB UDFs on 19 lines all-time); 106,283 SPO lines carry
`FromDocType='PO'` + `FromDocDtlKey` resolving to the source PO line; `PODTL.Location` is
never NULL.

Tags: `[BE]` backend pytest, `[FE]` frontend vitest, `[E2E]` recorded agent-browser run,
`[T]` tester-owned proof (mutation / live replay / docs).

## Definitions

- **input field** - an operator-mappable canonical line field that feeds ref minting and is
  NEVER sent on the wire: `from_so_doc_key`, `from_so_line_key`, `from_so_external_db`,
  `from_so_external_doc_key`, `from_so_external_doc_no`, `from_so_external_line_key`,
  `from_po_doc_key`, `from_po_line_key`.
- **wire field** - sent to Sorento at contract major >= 2 (the `FALLBACK_FIELDS` gate):
  `from_so_line_ref`, `from_so_external`, `from_so_numbers`, `from_po_line_ref`,
  `from_po_number`. The first two and the fourth are **engine-minted** from input fields;
  `from_so_numbers` and `from_po_number` are operator-mapped directly.
- **line ref format** - `{database}:{DocKey}:{DtlKey}`, identical to the line's own
  `source_ref` composition (`mapping.MappingEngine.map_document`, plan 22 Appendix A6).
- **preset text** - `presets._PO_HEADER_QUERY` / `_PO_LINE_QUERY` / `_PO_FINGERPRINT_QUERY`,
  shared by `PO_PRESET` and `SPO_PRESET`, `{database}` substituted per company.

## Group A - transform and canonical model (`[BE]`)

- **AC-06-01 [BE]** `mapping.TRANSFORMS` gains `string_list`: `"SO1, SO2,,SO1 "` ->
  `["SO1", "SO2"]` (split on `,`, strip, drop blanks, dedupe preserving first occurrence);
  `None` / `""` -> `None`; a non-string raises `TransformError` naming the value. The list is
  capped at 50 entries (Sorento's `max_length=50`), extra entries dropped with a WARNING
  naming the source ref.
- **AC-06-02 [BE]** `CanonicalPurchaseOrderLine` and `CanonicalShippingOrderLine` declare the
  eight input fields (`Optional[int]` for keys, `Optional[str]` max 100 for db / doc_no) and
  the wire fields `from_so_line_ref: Optional[str]` (max 255), `from_so_external:
  Optional[FromSoExternal]` (`db`, `doc_key`, `doc_no`, `dtl_key`, all optional, `db`
  required when the object is present), `from_po_line_ref: Optional[str]` (max 255),
  `from_po_number: Optional[str]` (max 100); `from_so_numbers` keeps its existing type.
  `CanonicalSalesOrderLine` gains none of them.
- **AC-06-03 [BE]** `sink_payload(contract_version=1)` on a PO / SPO line omits every wire
  field and every input field. `sink_payload(contract_version=2)` carries each wire field
  when set and OMITS the key when its value is `None` or an empty list (never `null`, never
  `[]`); input fields are never present at any version. A `CanonicalSalesOrderLine` payload
  never carries any of them at any version.
- **AC-06-04 [BE]** The golden A6 PO / SPO payload tests (`test_autocount_documents.py`) still
  pass byte-for-byte for a line with no linkage set at contract 1 and at contract 2.

## Group B - engine minting (`[BE]`)

- **AC-06-05 [BE]** Given mapped `from_so_doc_key=45700100` and `from_so_line_key=45700148`
  on a company whose `database_name` is `AED_SORENTO`, the mapped line carries
  `from_so_line_ref == "AED_SORENTO:45700100:45700148"`. When either key is `None` the ref is
  `None`. Same rule mints `from_po_line_ref` from `from_po_doc_key` / `from_po_line_key`.
- **AC-06-06 [BE]** Given mapped `from_so_external_db="AED_VSOFT"`, `_doc_key=12`,
  `_doc_no="SO000012"`, `_line_key=99`, the line carries `from_so_external == {"db":
  "AED_VSOFT", "doc_key": 12, "doc_no": "SO000012", "dtl_key": 99}`. When `_db` is `None`
  the object is `None` even if the other three are set (a key that does not resolve in this
  book never travels as a same-book ref).
- **AC-06-07 [BE]** Minting runs AFTER operator mapping and BEFORE model construction, inside
  the same per-line block that composes the line's own `source_ref`; an operator row that
  targets a wire-minted field (`from_so_line_ref`, `from_so_external`, `from_po_line_ref`)
  is refused at save time with a 422 naming the field (the catalog does not offer them).
- **AC-06-08 [BE]** A line whose `FromSODocList` maps to `from_so_numbers` via `string_list`
  and whose `from_so_line_ref` is `None` (doclist-only line) is sent with `from_so_numbers`
  alone - no ref invented.
- **AC-06-09 [BE]** `product_code` (already mapped from `ItemCode`) is present on the same
  contract-2 line payload as the linkage fields when the mapping row exists.

## Group C - catalog and presets (`[BE]`)

- **AC-06-10 [BE]** The LINE catalog for `purchase_order` and `shipping_order` offers the eight
  input fields + `from_so_numbers` + `from_po_number` as optional targets; `sales_order`
  offers none of them. `sorento_field_for(entity, name, "line")` resolves each; the header
  scope refuses them. The parity pin
  `test_line_catalog_equals_the_canonical_line_wire_set_minus_engine_derived` is rewritten as
  `catalog == (SINK | FALLBACK | INPUT) - MINTED`, with `MINTED = {from_so_line_ref,
  from_so_external, from_po_line_ref}` and `INPUT` = the eight input fields; `from_so_numbers`
  leaves the engine-derived set.
- **AC-06-11 [BE]** Save-time validation: an input key field accepts transforms `int` and
  `string` only; `from_so_numbers` accepts `string_list` only; a formula row may not target a
  list field (422 naming the field).
- **AC-06-12 [BE]** `_PO_LINE_QUERY` (shared PO/SPO) selects, in addition to today's columns:
  `d.FromSODtlKey AS FromSODtlKey`, `so.DocKey AS FromSODocKey`, `so.DocNo AS FromSODocNo`,
  `d.FromSODocList AS FromSODocList`, `CASE WHEN d.FromDocType = 'PO' THEN d.FromDocDtlKey END
  AS FromPODtlKey`, `sh.DocKey AS FromPODocKey`, `sh.DocNo AS FromPODocNo`, via `LEFT JOIN
  {database}.dbo.SODTL AS sd ON sd.DtlKey = d.FromSODtlKey`, `LEFT JOIN {database}.dbo.SO AS so
  ON so.DocKey = sd.DocKey`, `LEFT JOIN {database}.dbo.PODTL AS src ON src.DtlKey =
  d.FromDocDtlKey AND d.FromDocType = 'PO'`, `LEFT JOIN {database}.dbo.PO AS sh ON sh.DocKey =
  src.DocKey`. The `WHERE` cut (`:doc_key`, `ItemCode IS NOT NULL`, `Qty IS NOT NULL`) is
  unchanged. No `UDF_*` column appears in any preset text (per-company UDFs are operator
  additions - see AC-06-24).
- **AC-06-13 [BE]** `_PO_HEADER_QUERY`'s `OUTER APPLY` and `_PO_FINGERPRINT_QUERY` both gain
  `SUM(CASE WHEN d.FromSODtlKey IS NOT NULL THEN 1 ELSE 0 END) AS LinkedSOCount`,
  `SUM(d.FromSODtlKey) AS FromSOKeySum`, `SUM(CASE WHEN d.FromDocType = 'PO' AND
  d.FromDocDtlKey IS NOT NULL THEN 1 ELSE 0 END) AS LinkedPOCount`, `SUM(CASE WHEN
  d.FromDocType = 'PO' THEN d.FromDocDtlKey END) AS FromPOKeySum`, under the same line
  filter; the header query exposes them as `l.LinkedSOCount` ... so they enter
  `result_columns` (change detection) and the fingerprint row (sweep).
- **AC-06-14 [BE]** `PO_PRESET.line` and `SPO_PRESET.line` gain enabled, not-required rows:
  `FromSODocKey -> from_so_doc_key (int)`, `FromSODtlKey -> from_so_line_key (int)`,
  `FromSODocList -> from_so_numbers (string_list)`, `FromPODocKey -> from_po_doc_key (int)`,
  `FromPODtlKey -> from_po_line_key (int)`, `FromPODocNo -> from_po_number (string)`.
  `SO_PRESET` is unchanged. No preset row targets a `from_so_external_*` field.
- **AC-06-15 [BE]** Re-offer: a document whose ONLY change between two runs is a newly
  populated `FromSODtlKey` on one line (SQLite source table gains the value; header
  `LastModified` untouched; the header aggregate `LinkedSOCount` therefore changes) is
  re-staged as an update (`op = upsert`, `updated_count >= 1`, `added_count == 0`) and its
  canonical line carries the minted `from_so_line_ref`.

## Group D - backfill for existing tasks (`[BE]`)

- **AC-06-16 [BE]** `backfill.backfill_document_line_linkage(bind)` adds the six preset line
  rows of AC-06-14 (enabled) to every existing `purchase_order` and `shipping_order`
  `ac_entity_config` across every tenant when a row for that target is not already there
  (an operator's own row for the same target, in any state, is left alone); a
  `sales_order` task gets nothing; idempotent (second pass adds 0).
- **AC-06-17 [BE]** When the task's stored `query` / `lineQuery` / `fingerprintQuery` is
  byte-identical to the OLD preset text with the task's own company `database_name`
  substituted, it is replaced by the NEW text and the four header aggregate names of AC-06-13
  are appended to `result_columns`; a customised statement is left untouched with a WARNING
  naming the config id (the mapping rows of AC-06-16 still land, independently); a statement
  matching a SIBLING company's substitution counts as customised; every other `source_config`
  key is untouched.
- **AC-06-18 [BE]** Schema-tolerant: a bind without `ac_field_mapping` / `source_config`
  / any module table returns 0 cleanly.
- **AC-06-19 [BE]** Module Alembic `0018_autocount_line_linkage` chains onto
  `0017_autocount_fingerprint`, revision id <= 32 chars, single head, calls the helper;
  `update_tenant` runs the same helper; `manifest.json` bumps 0.7.0 -> 0.8.0.
- **AC-06-20 [T]** Live Postgres replay: `alembic upgrade head` on the module history reaches
  `0018` as the single head; on a real PO task with the old preset text the helper rewrites
  the three statements, appends the four names to `result_columns`, inserts the six rows.

## Group E - frontend (`[FE]` / `[E2E]`)

- **AC-06-21 [FE]** The transform picker (`autocount-meta.ts`) offers `string_list` labelled
  "Comma-separated list" and the formula type map treats it as a list output (a formula row
  cannot target it - the server 422 of AC-06-11 is surfaced as the row's field error).
  The mock service's PO and SPO line catalogs carry the ten new targets so the Mapping tab
  renders them without the backend; vitest covers the picker offering the transform and the
  catalog listing the targets for PO/SPO and not for SO.
- **AC-06-22 [E2E]** Recorded agent-browser run (sidebar clicks from `/`, never a deep URL):
  AutoCount -> company -> PO task -> Mapping tab -> line scope shows the six preset rows with
  their transforms; the target picker of a new line row lists `from_so_external_db`; the SO
  task's line picker does not. Screenshots at 375px and 1280px under
  `documentation/plans/sprint-5/06-evidence/mapping/`, README run log.

## Group F - Sorento contract, docs, live proof (`[T]`)

- **AC-06-23 [T]** Deploy-order proof recorded in the addendum change log: before the ESB
  deploy, `GET /api/v1/external/contract` on Sorento prod lists `from_so_line_ref`,
  `from_so_external`, `from_po_line_ref`, `from_po_number` under
  `fields_added.purchase_orders` and `fields_added.shipping_orders` (contract 2.2), with the
  UTC time and Sorento build SHA. Until then the ESB is NOT deployed (every re-staged
  document would 422 under `extra="forbid"`).
- **AC-06-24 [T]** Docs: addendum section 4 rewritten to the frozen shape (five wire fields,
  input fields, minting rule, ICB `from_so_external` semantics, "we resolve nothing");
  section 12 change-log entry; `22-autocount-db-etl-autocount-sql.md` sections 3 and 4
  carry the new preset text plus an AED_SORENTO-only note showing the `UDF_ICB_*` columns an
  operator adds to the line query and maps to `from_so_external_*` (never in the preset);
  a backfill runbook (fromDate 2023-09-01 on the PO and SPO tasks, reconcile until caught up,
  restore fromDate) in the plan.
- **AC-06-25 [T]** Live verification on the lane (backend :8005, DB `foundryx_service_s35`)
  against AED_SORENTO through the operator's tunnel (`localhost:59773`, read-only login):
  a PO task with fromDate 2026-09-01 previews the new line columns, a dry run stages
  PO-2026/09-0015 with line MSP124 carrying `from_so_line_ref = "AED_SORENTO:<SO
  DocKey>:45737853"` and `from_so_numbers = ["SO420374"]`; an SPO task stages
  SPO-2026/09-0038 line 45737810 with `from_po_line_ref = "AED_SORENTO:44909094:45021331"`
  and `from_po_number = "202606-S0018"`. Nothing is pushed to Sorento prod (sink = preview
  only). Canonical JSON excerpts recorded in the test report.
- **AC-06-26 [T]** Mutation proof: with minting removed the AC-06-05/06 tests go red; with
  `from_so_line_ref` moved from `FALLBACK_FIELDS` to `SINK_FIELDS` the v1-omits test goes
  red; with the PO filter widened to `sales_order` in the backfill the SO-untouched pin goes
  red.
- **AC-06-27 [T]** Regression: the full autocount pytest surface and the frontend vitest
  suite pass on the lane HEAD; `npx eslint` clean on touched FE files.
