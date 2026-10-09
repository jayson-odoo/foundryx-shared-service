# 18 - AutoCount SO `Transferable` on the Sorento feed - User Acceptance Criteria

Lane `SS-SO-TRANSFERABLE`, partner of sorento-crm #1421 (lane SO-TRANSFERABLE), which reads
AutoCount's SO `Transferable` flag off the EXISTING SO push. SO stays push-only (no pull-gateway
work). Same shape as sprint-5/07 (`ref`, module Alembic 0019) - read that plan's UAC for the
backfill idiom this one copies.

Wire: the `sales_order` record gains an optional `transferable` (boolean, AutoCount `SO.Transferable`
`'T'`/`'F'` through the existing `bool` transform). Contract >= 2 only (a fallback field, like
`ref`). OMITTED from the payload when null - never sent as an explicit `null`; `false` IS sent
(a real value). Deploy order (owner decision 2026-10-01): Sorento ingest IGNORES unknown fields
(built in sorento #1421), so this change can ship before or after #1421 - before it, Sorento
simply drops `transferable`.

Tags: `[BE]` backend pytest, `[T]` tester / docs proof.

## Group A - preset, canonical model, wire

- **AC-18-01 [BE]** `presets._SO_HEADER_QUERY` selects `h.Transferable AS Transferable` right
  after `h.Ref AS Ref`, otherwise byte-identical to the 0019 (`Ref`) text; `SO_PRESET.header`
  carries `PresetField("Transferable", "transferable", "bool")` (not required). `_SO_LINE_QUERY`,
  `_SO_FINGERPRINT_QUERY`, `PO_PRESET`, `SPO_PRESET` are byte-unchanged.
- **AC-18-02 [BE]** `CanonicalSalesOrder.transferable: Optional[bool] = None`, in
  `FALLBACK_FIELDS`. `sink_payload(contract_version=2)` carries `transferable: true` / `false`
  when set and NO `transferable` key when `None`; `contract_version=1` never carries it.
- **AC-18-03 [BE]** PO / SPO have no `transferable` attribute and never emit the key.
- **AC-18-04 [BE]** The mapping catalog accepts `transferable` for `sales_order` only;
  `MappingEngine.map_document` maps `Transferable = 'T'` -> `True`, `'F'` -> `False`, NULL -> key
  omitted on the wire.

## Group B - backfill for existing tasks (module Alembic 0025 + `update_tenant`)

- **AC-18-05 [BE]** A `sales_order` task whose header query is byte-identical to the 0019 `Ref`
  preset text (own company's `database_name` substituted) is rewritten to the NEW text and
  `"Transferable"` is appended to `result_columns`; a `Transferable -> transferable` header row
  (`bool`, not required, source-owned, next `sort_order`) lands ENABLED.
- **AC-18-06 [BE]** A customised query (prod `AED_SORENTO` shape) is left byte-untouched,
  `result_columns` untouched, and the mapping row lands DISABLED with exactly one WARNING naming
  the config id. If the customised query already selects `Transferable` (in `result_columns`),
  the row lands ENABLED.
- **AC-18-07 [BE]** An existing `transferable` row (any state) is never duplicated or modified;
  a second pass changes nothing and does not re-warn.
- **AC-18-08 [BE]** Company resolved WITH the config's own `tenant_id` (no cross-tenant match);
  helper is a no-op (returns 0) on a schema that predates its tables.
- **AC-18-09 [BE]** Revision `0025_*` chains onto `0024_autocount_doc_lookup` (id <= 32 chars);
  `update_tenant` runs the helper; manifest version bumped; a pre-`Ref` (0018-era) preset task
  walks 0019 -> 0025 and ends on the NEW text with both `Ref` and `Transferable` in
  `result_columns` (0019's target text is frozen, never the live preset).
- **AC-18-10 [T]** PR body states the deploy order (either order is safe; before #1421 Sorento
  drops the field) and the prod operator step for `AED_SORENTO`.

## Operator step (prod `AED_SORENTO`, once sorento #1421 is live so the value is used)

1. Query tab of the production `Sorento` SO task: add `h.Transferable AS Transferable` to the
   header SELECT (next to `h.Ref`), save (the result columns re-derive and gain `Transferable`).
2. Mapping tab: enable the `Transferable -> transferable` row the migration created disabled.
3. Expect every SO to re-stage ONCE (new column enters the row hash) and re-push carrying
   `transferable` - same one-off cost as the 0019 `Ref` rollout.
