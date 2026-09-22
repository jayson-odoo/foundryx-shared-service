# 12 - AutoCount mapping: multi-column formulas for masters + Reset to preset: acceptance criteria

Companion to `12-autocount-mapping-preset-reset.md`. Ids are `AC-12-nn`, tagged `[BE]` (backend),
`[FE]` (frontend), `[E2E]` (a recorded `agent-browser` run, real clicks, 375 AND 1280) and `[T]`
(a measured/ops proof). The Test Execution Report keys PASS / FAIL / DEFERRED back to these ids.

Scope reminder (non-goals, pinned so a reviewer can reject drift): no change to the formula
language, to any transform, to the mapping engine's evaluation order, to `source_config` (lookups
stay on the Source tab), to the Sorento wire shape, or to what first-save seeding creates. No new
permission, no migration.

## 0. Baseline this plan is measured against (recorded 2026-09-22)

- Production `SRT` product task (Sorento Open API app) carries a mapping seeded BEFORE
  sprint-5/10 AC-10-73/74 landed: `ItemCode -> name` (preset: `Description`), `Description ->
  description` as plain Text (preset: the Desc2 join formula), `BaseUOM -> uom_code` ENABLED
  (preset: disabled), `ListPrice -> list_price` (a column `/itembypage` does not return; preset:
  `BaseUOMPrice` from the `uom` lookup, clamped `<= 0 -> 0`), and no `Discontinued ->
  is_discontinued` row. Sorento's compare shows 177 description differences (every item with a
  `Desc2`) and its Excel view derives "Desc 2" by stripping the NAME prefix from `description`,
  which reads as junk while `name = ItemCode`.
- `seed_http_preset_mapping` / `seed_document_mapping` are seed-if-absent: they run once, on the
  first clean save of an empty mapping. There is no action that re-applies a preset to an existing
  mapping for a master entity; the mapping editor's "Use preset" (`GET /autocount/presets/{entity}`)
  returns rows for DOCUMENT entities only.
- The backend already evaluates a master-entity formula against the whole raw row:
  `map_document` passes `facts=self._header_facts(raw, lines)` and `_header_facts` returns
  `dict(raw)` for a non-document entity (AC-10-73). The save gate accepts any name in
  `effective_result_columns(config.result_columns, lookups) | LINE_AGGREGATE_NAMES`
  (`services/company_service.py` ~1841).
- The frontend formula builder receives variable groups ONLY for document entities:
  `mapping-editor-body.tsx` `builderVariables` returns `[]` when `!isDocument`, so for a master
  entity the builder offers `value` alone and `validateFormula(draft, [])` rejects `Description` /
  `Desc2` with "Unknown name" before the server is reached. The server would accept it.
- `_seed_rows` never omits a preset row: a row whose source column is not in `available_columns`
  is created `is_enabled=false` (AC-02-16); `available_columns=None` (never previewed) seeds every
  row enabled.

## Group A - multi-column formula variables for master entities (`[FE]` / `[BE]`)

- **AC-12-01 [FE]** **The formula builder offers the previewed source columns on a master
  entity.** Given a non-document entity whose mapping view carries a non-empty `acFields`
  (= `effective_result_columns`: the task's previewed columns plus its lookups' aliases), when
  the operator opens the formula builder on any header row, then the variable panel shows ONE
  group labelled "Source columns" listing every `acFields` entry as a pickable token, and the
  client-side validator (`validateFormula(draft, knownVariableTokens)`) accepts a formula that
  names them - e.g. `trim(if(default(Desc2, "") != "", concat(Description, " ", Desc2),
  Description))` validates clean. Document entities keep their existing "Header columns" /
  "Line columns" / "Line aggregates" groups byte-identically (Vitest pins both).
- **AC-12-02 [FE]** **No previewed columns, no group - and no hint copy.** Given a master entity
  whose `acFields` is empty (the Source tab has never previewed clean), the builder falls back to
  its single-`value` model exactly as today: no "Source columns" group, no instructional text
  explaining why. A formula naming a column still fails the client validator with the existing
  "Unknown name" message, and the server 422 (unchanged) names the field if it gets that far.
- **AC-12-03 [BE]** **The save gate accepts a master formula naming a previewed column or a lookup
  alias (already true - pinned).** Given a product HTTP task with `result_columns` containing
  `Description` and `Desc2` and a `uom` lookup exposing `BaseUOMPrice`, when the mapping is PUT with
  a `description` row carrying the join formula and a `list_price` row carrying
  `if(number(value) <= 0, 0, number(value))` sourced from `BaseUOMPrice`, then 200. A formula
  naming `Desc3` (not previewed) 422s naming the row and the unknown name. Test.
- **AC-12-04 [BE]** **Simulate evaluates a master multi-column formula against the raw row.**
  `simulate_mapping` for a master entity with the join formula returns `description` =
  `"ECO SERIES  HIGH LEVEL"`-style RAW join for a row with `Desc2`, `Description` alone for a blank
  `Desc2`, and preserves an inner double space unchanged (`concat` never trims). Test on the
  service, plus the route's happy path.
- **AC-12-05 [FE]** **The builder's client-side sample Test stays hidden when variables are
  present** (existing rule: a single-`value` sample cannot evaluate a multi-column formula); the
  server-side "Test" (`onServerTest`) is the one offered. Vitest pins that for a master entity
  with `acFields` the sample Test control is absent and for one without it is present.

## Group B - Reset to preset (`[BE]` / `[FE]` / `[E2E]`)

- **AC-12-10 [BE]** **One route, one permission.** `POST
  /autocount/companies/{companyId}/entities/{entityType}/mapping/reset-preset` with body
  `{dryRun: bool}` requires `autocount.companies.manage`; another tenant's company id reads as a
  uniform 404; an entity with no registered preset for the task's source type answers 422
  `{"detail": "No preset is registered for this entity."}`. Test all three.
- **AC-12-11 [BE]** **The preset resolved is the one first-save seeding would create today.** The
  service resolves the preset rows by the SAME rule the first-save seed uses (`HTTP_PRESETS[entity]`
  for an `autocount_http` task, the SQL master/document seed for a DB-source task), header scope
  only, and computes `available_columns` from `effective_result_columns(config.result_columns,
  lookups)` (None when never previewed). No second preset registry, no duplicated row list.
  Test: the rows a reset produces on an EMPTY mapping equal, row for row, the rows
  `seed_http_preset_mapping` produces for the same task.
- **AC-12-12 [BE]** **Dry run returns the exact diff and writes nothing.** `dryRun=true` answers
  `{label, rows: [{canonicalField, sourcePath, transform, formula, enabled, isRequired, change}],
  removed: [{canonicalField, sourcePath, transform, formula}]}` where `change` is `added` (no
  current row for that canonical field), `changed` (a current row exists and any of source /
  transform / formula / enabled / required differs) or `unchanged`; `removed` lists current header
  rows whose canonical field the preset does not carry. Every `enabled=false` row carries a
  `disabledReason` that names the ACTUAL cause: `"column not returned by the source"` when the
  preset row's source column is absent from `available_columns`, or `"withheld by the preset"`
  when the preset itself seeds the row disabled (`PresetField.enabled=False`, e.g. `uom_code`
  per AC-10-74). Never one string for both - the dialog must not claim a column is missing when
  it is not (amended 2026-09-22 after the S2 tester flagged the single-string wording).
  Statement count pinned: no INSERT / UPDATE / DELETE on `ac_field_mapping`. Test with a
  mapping that has one of each kind, including one row per disabled reason.
- **AC-12-13 [BE]** **Apply replaces the header rows in one transaction.** `dryRun=false` deletes
  the entity's header-scope rows and re-seeds the preset rows via `_seed_rows` with the SAME
  `available_columns`, in ONE transaction (a failure mid-way leaves the previous rows intact -
  test with a forced error after the delete), returns the fresh `MappingViewResponse`, and leaves
  line-scope rows untouched (document entity test: line rows before == after).
- **AC-12-14 [BE]** **Same side effects as saving the mapping, no more.** A reset touches only
  `ac_field_mapping` rows for the entity: `source_config`, `result_columns`, lookups, `status`,
  `last_preview_at`, `last_preview_failed_count`, `activated_at` and `preview_job_id` on
  `ac_entity_config` are byte-identical before and after (test snapshots the row). Whatever
  `replace_mapping` does to the Activate gate today, a reset does the same and nothing else -
  pinned by a test asserting identical `ac_entity_config` deltas for PUT-with-preset-rows versus
  reset.
- **AC-12-15 [BE]** **Un-previewed columns land disabled, never dropped (AC-02-16 preserved).**
  On a task whose `result_columns` lacks `BaseUOMPrice` (no `uom` lookup configured), the reset
  creates the `list_price` row with `is_enabled=false`, and the dry run reports it under
  `enabled=false` with `disabledReason: "column not returned by the source"`. On a task never
  previewed (`result_columns` NULL) every row is enabled EXCEPT rows the preset itself withholds
  (`uom_code`, `disabledReason: "withheld by the preset"`). Test both.
- **AC-12-20 [FE]** **Mock first.** The dialog's every state - loading the dry run, a diff with
  added / changed / unchanged / removed rows and disabled rows, an empty diff (mapping already
  equals the preset), the "no preset" 422, apply in flight, apply success, apply failure - is
  built and tuned against `services/autocount-service.mock.ts` before the backend exists; the mock
  is swapped at the service boundary and no mock reaches the evidence run.
- **AC-12-21 [FE]** **The action lives on the Mapping tab's existing action surface.** "Reset to
  preset" appears in the mapping page's `ActionMenu` only when the operator holds
  `autocount.companies.manage` AND the entity has a preset (the mapping view gains a boolean
  `hasPreset`, derived server-side by the AC-12-11 rule - the UI never guesses from the entity
  type). With unsaved edits the shell's dirty-guard AlertDialog fires first, exactly as switching
  tabs does. No entity without a preset ever sees the item (foolproof-UI).
- **AC-12-22 [FE]** **The preview dialog shows exactly what will change.** Clicking the action
  opens a `Dialog` (the same lightbox spring `MappingSimulator` uses - no new primitive) that
  fetches the dry run and renders the preset label, one row per preset row with a `StatusBadge`
  for `added` / `changed` / `unchanged`, the source column, the transform or the formula as a
  `ClampedText` chip, a "Disabled - column not returned by the source" line where
  `enabled=false`, and a "Removed" section for current rows the preset drops. The primary button
  reads "Reset mapping"; it is disabled while loading and when the diff is empty (then the
  dialog says "This mapping already matches the preset."). Non-clipped at 375 and 1280; the row
  list scrolls internally.
- **AC-12-23 [FE]** **Apply, reload, confirm.** "Reset mapping" calls the route with
  `dryRun=false`, the mapping table re-renders from the returned view (the Description row now
  shows the formula chip, the `list_price` row shows its enabled/disabled state honestly), a toast
  "Mapping reset to preset." fires via `lib/toast`, and the dialog closes. A failure keeps the
  dialog open with the server message in place of the primary button's row. The action is NOT
  a `ResourceAction.confirm` and NOT a `deferred` action: it is a preview surface whose apply is
  reversible through the still-editable mapping - stated in the plan (D6) so the T5 carve-out
  inventory is not touched.
- **AC-12-24 [E2E]** Recorded `agent-browser` run at 375 AND 1280, evidence under
  `documentation/plans/sprint-5/12-evidence/reset-preset/`: AutoCount -> Companies -> a company
  -> the product HTTP entity (seeded with a deliberately OLD-style mapping: `ItemCode -> name`,
  plain `Description -> description`, no `is_discontinued`) -> Mapping tab -> Reset to preset ->
  the dialog lists `name` changed, `description` changed, `is_discontinued` added, `uom_code`
  changed (enabled -> disabled), `list_price` changed -> Reset mapping -> toast -> rows match the
  preset -> open the Description row's formula builder -> "Source columns" lists `Desc2` -> Cancel
  -> Simulate -> the simulated `description` is the joined text. README run log, both widths.

## Group C - cross-cutting

- **AC-12-30 [BE]** **No new permission.** The route reuses `autocount.companies.manage`; the
  mapping view read stays on `autocount.companies.read`. Pinned by the permissions parity test.
- **AC-12-31 [BE]** **Tenant scoping.** Company and entity resolve WITH the tenant from the JWT;
  a cross-tenant company id is a uniform 404 for both `dryRun` values. Test.
- **AC-12-32 [BE]** **No migration.** No schema change; `hasPreset` is derived at read time.
  Stated in the plan; a reviewer grepping `alembic/versions` finds nothing new.
- **AC-12-33 [FE]** **Responsive and shell-compliant.** Every surface touched is verified
  non-clipped and usable at 375 AND 1280; the dialog reuses `Dialog` / `StatusBadge` /
  `ClampedText` / `lib/toast`; no raw CSS, no bare `<Select>`, no instructional copy, no new
  motion (the dialog rides the existing lightbox spring - the explicit no-motion list for this
  plan).
- **AC-12-34 [T]** **Green suites.** `python -m pytest -q` (targeted globs during the lane, full
  suite on CI) and `npm test` pass; `npx eslint` on every changed frontend file passes before a
  fresh `rm -rf .next && npm run build`.
- **AC-12-35 [T]** **Production adoption is a written runbook, then evidence.** The plan's §7
  records the exact prod sequence for the `SRT` product task: Source tab -> add the `uom` lookup
  if absent (`/itemuombypage`, `on ItemCode + BaseUOM~UOM`, field `Price as BaseUOMPrice`) ->
  Test -> Mapping -> Reset to preset -> review the diff -> Reset mapping -> Simulate -> Review
  and Activate -> Run preview -> Sorento compare shows the 177 `Desc2` items matching and the
  Excel view's "Desc 2" reading as AutoCount's `Desc2`. The owner runs it; the outcome (row
  counts before/after from Sorento's compare) is appended to the test report.
