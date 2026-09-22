# 12 - AutoCount mapping: multi-column formulas for masters + Reset to preset

UAC: `12-autocount-mapping-preset-reset-acceptance-criteria.md` (the contract; this file is how
we meet it). Builds on `sprint-5/02` (mapping editor, formula builder, "Use preset" for
documents), `sprint-5/08` (HTTP presets, `seed_http_preset_mapping`) and `sprint-5/10`
(AC-10-73/74: the Desc2 join and the withheld `uom_code`). Branch
`sprint-5/12-mapping-master-formula-variables`, worktree `.claude/worktrees/s50`.

## 0. Owner rulings (2026-09-22)

1. **R1 - fix properly, no DB edit.** The prod row is not hand-patched; the operator re-adopts the
   preset through the product.
2. **R2 - Reset to preset, whole mapping.** One action replaces every header row with the current
   preset after a preview of exactly what changes. Per-row "restore preset" is backlog
   (BL-SS-256).
3. **R3 - variables for ALL master entities**, not HTTP-source only: the backend already passes
   `dict(raw)` facts for every non-document entity, and one code path is simpler than a gate on
   `sourceType`.

## 1. Why

Production's `SRT` product mapping predates sprint-5/10 and deviates from the shipped preset in
five of eight rows (UAC §0). The visible symptom is 177 description differences on Sorento's
compare (every item with a `Desc2`) and a junk "Desc 2" column in its Excel view (Sorento strips
the NAME prefix off `description`; with `name = ItemCode` the remainder is nonsense). Two product
gaps let it happen and keep the operator from fixing it himself:

1. **Seeding is one-shot.** A preset improvement never reaches a mapping that already exists, and
   nothing in the UI re-applies it for a master entity.
2. **The formula builder hides the columns the server already accepts.** `builderVariables`
   returns `[]` for a non-document entity, so the client validator rejects `Desc2` as an unknown
   name even though `map_document` evaluates master formulas against the whole raw row and the
   save gate accepts every previewed column.

## 2. Design

### 2.1 Source columns in the builder (AC-12-01..05)

`mapping-editor-body.tsx` builds ONE more variable group for master entities:

```ts
if (!isDocument) {
  const columns = sourceOptions ?? draft.header.acFields;   // = view.acFields = effective_result_columns
  return columns.length > 0 ? [{ label: 'Source columns', items: columns.map(c => ({ label: c, token: c })) }] : [];
}
```

`acFields` is already the right set: `company_service.py` ~1720 fills it from
`effective_result_columns(config.result_columns, lookups)`, which is the SAME set the save gate
uses for `known_vars` (~1841) - so the client can never accept a name the server rejects, or the
reverse. Empty set -> no group -> the builder's existing single-`value` model (AC-12-02). The
document branch is untouched. Nothing changes server-side for Group A; AC-12-03/04 only PIN what
is already true (save gate + `simulate_mapping` -> `engine.project_document` -> `_header_facts`
= `dict(raw)`), so a future refactor cannot silently break it.

### 2.2 Reset to preset (AC-12-10..24)

**Backend** - `MappingService`/`CompanyService.reset_mapping_to_preset(tenant_id, company_id,
entity_type, *, dry_run)`:

1. Resolve the entity config (tenant-scoped) and the preset by the first-save rule: the SAME
   function the empty-mapping seed calls picks `HTTP_PRESETS[entity]` for an `autocount_http`
   task and the SQL master/document seed otherwise. Extract that choice into one helper
   `resolve_preset_rows(config) -> (label, Sequence[PresetField]) | None` used by BOTH the
   first-save seed and the reset, so there is one registry (AC-12-11). None -> 422.
2. `available_columns = effective_result_columns(config.result_columns, lookups)` (None when
   never previewed) - identical to what the seed receives.
3. Build the would-be rows in memory with the `_seed_rows` enable rule (a pure `plan_rows(...)`
   split out of `_seed_rows` so the seed and the dry run cannot drift), diff them against the
   current header rows by `canonical_field`, classify `added` / `changed` / `unchanged`, collect
   `removed`.
4. `dry_run=True` -> return the diff, no writes (statement count pinned, AC-12-12).
   `dry_run=False` -> in the request's single transaction: delete header rows, `_seed_rows(...)`,
   flush, return the mapping view (AC-12-13). Line rows untouched. No other column on
   `ac_entity_config` is written (AC-12-14) - the reset reuses whatever `replace_mapping` already
   does to the Activate gate by calling the same post-save hook, and nothing else.

Route: `POST /companies/{company_id}/entities/{entity_type}/mapping/reset-preset` in
`routers/companies.py` beside `replace_entity_mapping`, `require_permission("autocount.companies.manage")`,
body `MappingResetRequest {dryRun: bool = True}`, response `MappingResetPreview` (dry run) or
`MappingViewResponse` (apply) - two Pydantic models, one route, discriminated by the request.
`MappingViewResponse` gains `hasPreset: bool` (AC-12-21) from the same resolver.

**Frontend** - house layering, mock first:

- `types/autocount.ts`: `AutocountMappingResetPreview`, `AutocountMappingResetRow`;
  `AutocountMappingView.hasPreset`.
- `services/autocount-service.{ts,mock,real}.ts`: `resetMappingToPreset(companyId, entityType,
  {dryRun})` - contract block documented at the top of the service file.
- `hooks/use-mapping-reset.ts`: dry-run fetch on open, apply, error, `onApplied(view)`.
- `mapping/components/mapping-reset-dialog.tsx` (new, ONE component): `Dialog` on the existing
  lightbox spring, row list with `StatusBadge` per `change`, `ClampedText` for formulas, the
  disabled-reason line, the Removed section, primary "Reset mapping".
- `mapping-editor-view.tsx`: the `ActionMenu` item, gated by `can(AC_COMPANIES_MANAGE) &&
  view.hasPreset`; dirty state defers to the shell's guard.

### 2.3 Decision log

- **D1 - one preset resolver for seed AND reset.** Two registries would drift on the next preset
  change - the exact failure this plan is fixing.
- **D2 - `available_columns` from `effective_result_columns`**, same as the seed and the save
  gate: three consumers, one function.
- **D3 - reset is mapping-only.** Lookups live in `source_config` and changing them re-arms the
  Test/Activate gate; a reset that silently edited the Source tab would hide a prerequisite.
  Instead an un-previewed column lands DISABLED and is named in the preview (AC-02-16 rule),
  so the operator sees "add the lookup first". Lookup reset = BL-SS-258.
- **D4 - whole-mapping replace, not merge** (R2). A merge that keeps customised rows cannot
  fix the rows that are wrong; per-row restore is the honest shape for "keep mine" and is
  backlogged (BL-SS-256).
- **D5 - `hasPreset` is server-derived.** The UI never infers "this entity has a preset" from the
  entity type; the resolver answers, so an HTTP task and a DB task of the same entity can differ.
- **D6 - a preview Dialog, not a confirm and not a deferred action.** The value is SEEING the
  diff before acting; a grace-window countdown cannot show it and a typed confirm adds friction
  without information. The apply is recoverable (the mapping stays editable), so it does not
  qualify for the T5 confirm carve-out inventory, which is left untouched. Reviewer checks this.
- **D7 - no client-side sample Test for multi-column formulas** (existing builder rule): the
  server Test is the one that has the row.
- **D8 - preset versioning / auto-migration of seeded mappings rejected here** (BL-SS-257): it
  needs a version stamp per row, an "operator-edited" flag and a migration policy; the reset
  gives the operator the same outcome on demand with a visible diff.

## 3. Files

Backend (`service_backend/modules/autocount/`): `presets.py` (`resolve_preset_rows`, `plan_rows`
extracted from `_seed_rows`), `services/company_service.py` (`reset_mapping_to_preset`,
`has_preset` on `MappingView`), `routers/companies.py` (the route), `schemas.py`
(`MappingResetRequest`, `MappingResetRow`, `MappingResetPreview`, `MappingViewResponse.hasPreset`),
tests `tests/test_s12_mapping_reset_*.py`, `tests/test_s12_master_formula_facts.py`.

Frontend (`service_frontend/`): `types/autocount.ts`, `services/autocount-service.{ts,mock,real}.ts`,
`hooks/use-mapping-reset.ts` (new), `app/(protected)/autocount/companies/[id]/entities/[entityType]/mapping/components/{mapping-editor-body,mapping-editor-view}.tsx`,
`.../mapping/components/mapping-reset-dialog.tsx` (new), tests beside each
(`mapping-editor-body.test.tsx` gains the master "Source columns" cases).

Docs: this pair, `documentation/backlogs/backlog.md` rows BL-SS-256..258,
`documentation/engineering/` AutoCount mapping notes (the reset action + the master variables),
test report + `12-evidence/`.

## 4. Slices and order

| Slice | Scope | UAC |
|---|---|---|
| S1 FE mock | `hasPreset` + reset preview/apply in the mock; the dialog with every state; the `ActionMenu` item; the master "Source columns" group in the builder; Vitest; agent-browser 375/1280 against the mock | AC-12-01, 02, 05, 20, 21, 22, 23 |
| S2 BE | Tester's red tests first: `resolve_preset_rows` parity with the seed, dry-run diff + statement pin, apply in one transaction, disabled-not-dropped, `ac_entity_config` untouched, 404/422/permission, the AC-12-03/04 pins; coder greens; real service swap | AC-12-03, 04, 10..15, 30, 31, 32 |
| S3 | Live: fresh build, recorded run, test report, docs, backlog rows, prod runbook (§7) | AC-12-24, 33, 34, 35 |

Rules: S1 before S2 (frontend-mock first, PRINCIPLES step 3); tester writes S2's failing tests
before the coder; one coder per lane on Sonnet; reviewer (Opus) once on S1+S2 together with the
hard-fail list and D6 named explicitly.

## 5. Risks and answers

- **The reset drops a customisation the owner wanted.** The preview names every changed and
  removed row before anything is written (AC-12-12/22); R2 accepted the trade.
- **Reset and seed drift apart.** One resolver, one row planner (D1, AC-12-11).
- **`list_price` silently stops being sent after a reset.** It cannot be silent: the row lands
  disabled AND the preview says so (AC-12-15); the runbook adds the lookup first (§7).
- **The variable group offers a name the server rejects.** Impossible by construction: both read
  `effective_result_columns` (D2).
- **A document entity accidentally gets "Reset to preset".** `hasPreset` comes from the resolver;
  document entities keep their existing Source-tab "Use preset" and the resolver returns None for
  them in this plan unless the same helper already seeds them - the parity test decides, not a
  guess.

## 6. Backlog (append to `documentation/backlogs/backlog.md` in S3; ids reserved here - verify
the highest existing id first)

| ID | Title | Priority |
|---|---|---|
| BL-SS-256 | Per-row "Restore preset" on the mapping table (keep customised rows, fix one) | Low |
| BL-SS-257 | Preset versioning: stamp seeded rows with a preset version and surface "preset updated" on the Mapping tab | Low |
| BL-SS-258 | Reset the Source tab's lookups from the preset (today: mapping rows only, D3) | Medium |
| BL-SS-259 | Formula engine: `default(X, "")` on a fact key ABSENT from the raw row returns None instead of the default (found by the S2 tester 2026-09-22; a real `/itembypage` row always carries `Desc2`, so the preset is unaffected today) | Low |
| BL-SS-260 | `is_discontinued` is captured by the preset but not Sorento-delivered (absent from `CanonicalProduct.SINK_FIELDS`); verify a post-reset mapping PUT round-trips 200 (S2 coder checks; if the save gate 422s the seeded row, rule on keep-vs-drop) | Medium |

## 7. Production adoption runbook (`SRT` product task; AC-12-35)

1. Source tab: the prod task's `itemuombypage` lookup exposes `Price` under the alias
   `ListPrice` (owner confirmed 2026-09-22; `/itembypage` itself returns no price key - probed,
   19 keys). The preset row sources `BaseUOMPrice`, so rename the lookup field alias to
   `BaseUOMPrice` (Source tab -> lookup -> field -> Test) BEFORE the reset; otherwise the reset's
   `list_price` row lands disabled (named in the preview) and must be re-pointed after.
2. Mapping tab: Reset to preset -> read the diff (expect `name`, `description`, `uom_code`,
   `list_price` changed, `is_discontinued` added) -> Reset mapping.
3. Simulate one item with a `Desc2` (e.g. `TPE-1032`): `description` = Description + " " + Desc2,
   inner double space preserved.
4. Review and Activate -> Run preview -> Activate (pull mode).
5. Sorento: trigger the pull, open the compare: the 177 `Desc2` items match; the Excel view's
   "Desc 2" reads as AutoCount's `Desc2`. Record before/after counts in the test report.
