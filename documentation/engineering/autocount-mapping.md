# AutoCount mapping: presets, "Reset to preset", formula variables

Scope: the `autocount` module's field-mapping surface - what a preset is, how a mapping gets
seeded, how an operator re-adopts an improved preset, which variables the formula builder
offers, and the Enabled flag. Engine-wide rules (layering, tenancy, Resource shell) are in
`AGENTS.md` and `PRINCIPLES.md`; the per-slice contracts are the sprint plans
(`documentation/plans/sprint-4/22-*`, `sprint-5/01-*`, `02-*`, `08-*`, `10-*`, `12-*`).

Code: `service_backend/modules/autocount/presets.py`,
`services/company_service.py`, `routers/companies.py`;
`service_frontend/app/(protected)/autocount/companies/[id]/entities/[entityType]/mapping/`.

## 1. Presets and first-save seeding

A **preset** is a registered list of `PresetField`s (source column, canonical Sorento field,
transform, optional formula, `required`, `enabled`) for one (entity, source type). There are
exactly two registries and `resolve_preset_rows(config)` is the ONE function that picks between
them:

| Task | Registry | Entities |
|---|---|---|
| `source_impl == autocount_http` | `HTTP_PRESETS[entity].rows` | product, customer, warehouse, product_category, brand, unit_of_measure, stock_balance |
| anything else (a `sql_database` task) | `DOCUMENT_PRESETS[entity].header` | sales_order, purchase_order, shipping_order - **header scope only** |

Anything else answers `None`. Deliberately NOT a preset: `company_service`'s own
`DEFAULT_MAPPINGS` starter rows for a legacy `autocount_read` company - they have no registry
entry, so such a task reads `hasPreset=false` and a hand-posted reset 422s. That is the safe
direction.

Seeding is **seed-if-absent and one-shot**: `seed_http_preset_mapping` / `seed_document_mapping`
run on the first clean save of an EMPTY mapping (a document also needs a successful header
preview, so the rows never reference a query that has not proven it runs). A preset row whose
source column is not in `available_columns` is created `is_enabled=false`, never omitted.

`plan_rows(...)` is the pure row planner split out of `_seed_rows`, so the seed, the reset
preview and the reset apply cannot drift: one enable rule, one `is_required` rule, one place.

**`is_required` comes from the mapping CATALOG, not from `PresetField.required`**
(`planned_is_required`, falling back to the preset flag only when the catalog has no entry for
that entity/scope). This is what `replace_mapping` already wrote on every ordinary Save, so
seed == save == reset; before it, a plain Save silently rewrote the flag and the reset preview
reported phantom `changed` rows forever.

## 2. "Reset to preset"

`POST /autocount/companies/{companyId}/entities/{entityType}/mapping/reset-preset`
`{dryRun: bool}`, permission `autocount.companies.manage` (no new permission, no migration).

- **The resolver is the first-save seed's own rule** (section 1). One registry, never a second
  list of rows to keep in step.
- **Header scope only.** A document entity's line rows are not read, not diffed and not written
   - a reset is `DELETE header rows` + `_seed_rows(header)` in ONE transaction. Line-scope rows
  are byte-identical before and after, operator customisations included.
- **`dryRun: true` writes nothing** and returns `{label, rows[], removed[]}` where each row
  carries `change` = `added` / `changed` / `unchanged` and, when it will land disabled, a
  `disabledReason` naming the ACTUAL cause:
  - `"column not returned by the source"` - the preset row's source column is absent from
    `available_columns` (= `effective_result_columns(result_columns, lookups)`, `None` when the
    task has never previewed, in which case every row lands enabled).
  - `"withheld by the preset"` - `PresetField.enabled=False`, e.g. `uom_code` per AC-10-74.

  Never one string for both: telling an operator a column is missing when it is not sends them
  to add a lookup that would change nothing.
- **It never touches `source_config`.** Lookups live on the Source tab and editing them re-arms
  the Test/Activate gate; a reset that silently edited them would hide a prerequisite. An
  un-previewed column lands disabled and is NAMED in the preview instead (BL-SS-258 tracks
  lookup reset as separate work).
- **Nothing else on `ac_entity_config` is written** - `status`, `last_preview_at`,
  `activated_at`, `preview_job_id`, `result_columns` and the lookups are identical before and
  after. A reset has exactly the side effects of saving the mapping, no more.

Frontend: `MappingViewResponse.hasPreset` is SERVER-derived, so the UI never guesses "does this
entity have a preset" from its entity type - an HTTP task and a DB task of the same entity can
legitimately differ. The `ActionMenu` item is gated on `hasPreset && can('autocount.companies.manage')`.
The dialog is a preview surface, not a `confirm` and not a `deferred` action (the value is
SEEING the diff; the apply stays reversible through the still-editable mapping). After the
apply the table re-renders from the `MappingViewResponse` the POST returned - there is no
second `GET .../mapping`, because a refetch would leave the pre-reset rows on screen for a
round trip.

**Two surfaces carry the action, one definition (sprint-5/12, AC-12-27):** the standalone
mapping page (`mapping/components/mapping-editor-view.tsx`, where `company-detail-view.tsx`
sends a non-`sql_db` entity) AND the task editor's Mapping tab
(`entities/[entityType]/components/task-editor-view.tsx`, where it sends a `sql_db` task - i.e.
every DOCUMENT entity, since `HTTP_PRESETS` carries no document). Both mount the same
`useMappingResetAction` (`mapping/components/mapping-reset-action.tsx`), which owns the action
descriptor AND the dialog - add a third surface by calling that hook, never by copying the
JSX. Adding a NEW mapping surface without it reintroduces the sprint-5/12 S3 gap (the action
existed but no document entity could click it).

## 3. Formula variables on a master entity

`map_document` passes `facts = dict(raw)` for a NON-document entity, so a master-entity formula
has always been evaluated against the whole raw row, and the save gate has always accepted any
name in `effective_result_columns(result_columns, lookups) | LINE_AGGREGATE_NAMES`.

The formula builder now matches that. `mapping-editor-body.tsx` builds ONE variable group for a
master entity, **"Source columns"**, from `view.acFields` - which the backend fills from that
same `effective_result_columns`. Three consumers (client validator, save gate, evaluator), one
function: the builder can never offer a name the server rejects, or the reverse.

- `acFields` empty (the Source tab has never previewed clean) -> **no group at all**, and no
  instructional copy explaining why (foolproof-UI). The builder falls back to its single-`value`
  model and a formula naming a column fails the client validator as before.
- Document entities keep their existing "Header columns" / "Line columns" / "Line aggregates"
  groups byte-identically.
- With variables present the client-side sample Test is hidden: a single-`value` sample cannot
  evaluate a multi-column formula, so the server-side Test is the one offered.

Worked example, the shipped product preset's `description` row:

```
trim(if(default(Desc2, "") != "", concat(Description, " ", Desc2), Description))
```

`concat` never trims, so an inner double space in the source data is preserved in the VALUE
(HTML collapses it for display - a browser rule, not a mapping-engine one).

Caveat, BL-SS-259: `default(X, "")` on a fact key ABSENT from the raw row returns `None` rather
than the default. Every live `/itembypage` row carries `Desc2`, so the shipped preset is
unaffected; a future formula over a genuinely optional column would not be.

## 4. The Enabled flag

`ac_field_mapping.is_enabled` decides whether a row is delivered. The mapping table renders it:
a disabled row is dimmed with a `StatusBadge` "Disabled" in read mode and carries a per-row
`Switch` in edit mode (the existing "Column not in query" badge stays for a stale column - both
may show).

**Save never auto-enables a row.** `use-mapping-draft.ts` `toWrite` sends `isEnabled` exactly as
stored. The earlier sprint-5/02 save-time revive (`isEnabled || acFields.includes(sourcePath)`)
is gone: with two distinct disabled causes it is an ambiguous auto-derived action, and it
silently re-enabled `uom_code`, which **AC-10-74 withholds on purpose**, on every single Save.
Re-picking a source column on a row (`onChangeRow`) may still enable that row - that is an
explicit operator action on that row, which is the line the foolproof-UI rule draws.

## 5. Production adoption

Re-adopting an improved preset on a live task is a written runbook, not an automatic migration
(D8 / BL-SS-257): Source tab (add or rename any lookup the preset's rows source, then Test) ->
Mapping -> Reset to preset -> read the diff -> Reset mapping -> Simulate -> Review and Activate
-> Run preview -> compare in Sorento. The `SRT` product task's exact sequence is
`documentation/plans/sprint-5/12-autocount-mapping-preset-reset.md` section 7.
