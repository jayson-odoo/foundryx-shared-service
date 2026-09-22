# sprint-5/12 S2 (real backend) - agent-browser run log

Recorded 2026-09-22 by the lane coder, AFTER the mock-to-real swap, and **re-recorded in full**
after the owner's two rulings of the same day (BL-SS-260 drop + catalog-derived `is_required`).
Tool: `agent-browser` CLI, `--session s50`, headless Chrome. NO Playwright. Widths 1280x900 and
375x812.

## Stack under test

| Piece | Value |
|---|---|
| Frontend | fresh `rm -rf .next && npm run build`, `npx next start -p 3012` |
| Backend | `uvicorn app.main:app --port 8012` RESTARTED after the ruling changes, lane env + `CORS_ORIGINS=...,http://localhost:3012` (exported ad hoc; the SHARED `service_backend/.env` was NOT edited) |
| DB | `foundryx_service_s50`, no migration (AC-12-32 - this plan ships no schema change) |
| Service binding | `export const autocountService: AutocountService = realAutocountService;` - the S1 `withPhase1MappingResetMock` overlay is DELETED, not merely unbound |
| Route | `POST /autocount/companies/{id}/entities/{entityType}/mapping/reset-preset` |

## Navigation - real clicks only

Sidebar `AutoCount` -> `Companies` -> row `Mocha s50` -> tab `Entities` -> the Product row's
`Actions` menu -> `Configure mapping` -> `Actions` -> `Reset to preset`.

Starting state: the product mapping was bent back (SQL, fixture only) to the production `SRT`
baseline of UAC section 0 - `ItemCode -> name`, plain `Description -> description`, `uom_code`
ENABLED, no `is_discontinued`, plus the stray operator row `ItemType -> cost_price`.

## The expected diff (post-rulings)

`name` changed, `description` changed, `uom_code` changed + `Disabled - withheld by the preset`,
`is_active` changed (required flag only), `ItemType -> Cost price` under Removed, and
`code` / `category_code` / `brand_code` / `list_price` unchanged.

**There is NO `is_discontinued` row any more** (BL-SS-260, owner ruling): the preset no longer
carries `Discontinued -> is_discontinued`, because Sorento derives "discontinued" from the `****`
prefix of the description TEXT (plan 10 D22) and the field is absent from
`CanonicalProduct.SINK_FIELDS`. A first clean save now seeds **8** product rows, not 9.

## Shots

| File | What it proves | AC |
|---|---|---|
| `01-1280-mapping-page-old-style.png` | The old-style mapping before the reset | - |
| `02-1280-action-menu.png` | `Reset to preset` present - `hasPreset` SERVER-derived (`presets.resolve_preset_rows`) | AC-12-21, D5 |
| `03-1280-dry-run-diff.png`, `04-1280-dry-run-scrolled.png`, `05-375-dry-run-scrolled.png` | The REAL `dryRun: true` diff exactly as listed above, with `Required` badges on `Code` / `Name` / `Is active` (the catalog's answer). Nothing written. | AC-12-12, AC-12-22 |
| `06-1280-after-apply-toast.png` | `dryRun: false`: toast "Mapping reset to preset.", dialog closed, table re-rendered from the returned view. No "Not delivered to Sorento" section any more - the preset carries only deliverable rows. | AC-12-13, AC-12-23 |
| `07-1280-empty-diff-after-reset.png`, `09-375-empty-diff-after-reset.png` | Re-opened immediately after the apply: "This mapping already matches the preset.", `Reset mapping` DISABLED, both widths. Idempotent. | AC-12-11, AC-12-22 |
| `08-1280-after-save-only-uom-differs.png` | **The `is_required` ruling proven end to end:** reset -> ordinary "Save mapping" -> re-open. `Name` and `Is active` now read **Unchanged** (they used to read `changed` forever because a Save rewrote their required flag). The ONE remaining `changed` row is `uom_code` - a genuine pre-existing editor defect, see Findings. | owner ruling 2026-09-22 |
| `10-1280-builder-source-columns.png`, `11-375-builder-source-columns.png` | The master formula builder's ONE `Source columns` group (ItemCode, Description, `Desc2`, ... + the `uom` lookup alias `BaseUOMPrice`), the Desc2 join reading "Valid formula", no `Testing` tab | AC-12-01, AC-12-05 |
| `12-1280-simulate-desc2-join.png`, `13-375-simulate-desc2-join.png` | Simulate on the post-reset mapping: `Description` = the joined `ECO SERIES HIGH  LEVEL` | AC-12-04 |

DB after the apply (the reset's own write, not a PUT) - **8 rows**:

```
ItemCode     | code        | string   | REQUIRED | enabled
Description  | name        | string   | REQUIRED | enabled
Description  | description | string   |          | enabled   formula = the Desc2 join
ItemGroup    | category_code | string |          | enabled
ItemBrand    | brand_code  | string   |          | enabled
BaseUOM      | uom_code    | string   |          | DISABLED  (withheld by the preset)
IsActive     | is_active   | t_f_bool | REQUIRED | enabled
BaseUOMPrice | list_price  | string   |          | enabled   formula = the <=0 clamp
```

`cost_price` (the stray row) is gone; `ac_entity_config` was not written at all.

Console during the run: ZERO errors (only the codebase-wide Radix `aria-describedby` warnings).

## Notes

- **The runbook's lookup-alias step (plan section 7 item 1) is PROD-ONLY.** This lane's product
  task carries the preset's own `uom` lookup (`Price as BaseUOMPrice`, seeded on the first clean
  save since sprint-5/10 AC-10-04), so `list_price` lands ENABLED here with no rename. The
  production `SRT` task predates that seed and exposes the same field under the alias `ListPrice`,
  which is why section 7 tells the operator to rename it on the Source tab BEFORE the reset.
- **Simulate reports "This record would be rejected."** on a hand-typed mock record: `source_ref`
  is minted from the vendor envelope's `Data.0.AutoKey`, which a pasted flat record cannot supply.
  Pre-existing behaviour of `simulate_mapping`, unrelated to this plan. The per-field values (the
  point of AC-12-04) are all computed and shown.
- **The inner double space** of `ECO SERIES HIGH  LEVEL` is preserved in the VALUE (the API
  returns `"ECO SERIES HIGH  LEVEL"`, pinned by `test_s12_master_formula_facts.py`); HTML
  collapses it for display, which is a browser rendering rule, not a mapping-engine one.

## Findings

**BL-SS-260 is CLOSED** by the owner ruling: the preset row is gone, so the reset can no longer
create a row the save gate refuses. Proven live - reset, then an ordinary "Save mapping", answers
200 and every preset row round-trips.

**One genuine pre-existing defect remains, and the dialog is correctly reporting it.** After a
reset + an ordinary Save, `uom_code` comes back ENABLED, so the next dry run reads `changed`.
Cause: `use-mapping-draft.ts` `toWrite` sends `isEnabled: r.isEnabled || acFields.includes
(sourcePath)` - a deliberate sprint-5/02 B1 "revive a column-not-found row once its column returns
to the preview" rule. It cannot tell the two disabled CAUSES apart, so it also revives a row the
preset withholds ON PURPOSE (`uom_code`, AC-10-74) whenever `BaseUOM` is in the previewed columns,
which it always is. The distinction now exists at the preset level
(`presets.DISABLED_REASON_WITHHELD` vs `DISABLED_REASON_MISSING_COLUMN`); wiring it into that
revive rule needs an owner ruling on whether a preset-withheld row should ever auto-revive, so it
is raised here rather than changed unilaterally. Impact today: an operator who resets and then
saves silently re-enables `uom_code` and starts sending it, which is exactly what AC-10-74 exists
to prevent.
