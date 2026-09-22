# sprint-5/12 S2 (real backend) - agent-browser run log

Recorded 2026-09-22 by the lane coder, AFTER the mock-to-real swap. Tool: `agent-browser` CLI,
`--session s50`, headless Chrome. NO Playwright. Widths 1280x900 and 375x812.

## Stack under test

| Piece | Value |
|---|---|
| Frontend | fresh `rm -rf .next && npm run build`, `npx next start -p 3012` |
| Backend | `uvicorn app.main:app --port 8012` RESTARTED after the new route, lane env + `CORS_ORIGINS=...,http://localhost:3012` (exported ad hoc; the SHARED `service_backend/.env` was NOT edited) |
| DB | `foundryx_service_s50`, no migration (AC-12-32 - this plan ships no schema change) |
| Service binding | `export const autocountService: AutocountService = realAutocountService;` - the S1 `withPhase1MappingResetMock` overlay is DELETED, not merely unbound |
| Route | `POST /autocount/companies/{id}/entities/{entityType}/mapping/reset-preset` (confirmed in `/openapi.json`) |

## Navigation - real clicks only

Sidebar `AutoCount` -> `Companies` -> row `Mocha s50` -> tab `Entities` -> the Product row's
`Actions` menu -> `Configure mapping` -> `Actions` -> `Reset to preset`.

Starting state: the product mapping was bent back (SQL, fixture only) to the production `SRT`
baseline of UAC section 0 - `ItemCode -> name`, plain `Description -> description`, `uom_code`
ENABLED, no `is_discontinued`, plus the stray operator row `ItemType -> cost_price`.

## Shots

| File | What it proves | AC |
|---|---|---|
| `01-1280-mapping-page-old-style.png` | The old-style mapping before the reset | - |
| `02-1280-action-menu.png` | `Reset to preset` present - `hasPreset` now SERVER-derived (`presets.resolve_preset_rows`), not the S1 client heuristic | AC-12-21, D5 |
| `03-1280-dry-run-diff.png`, `04-1280-dry-run-scrolled.png`, `05-375-dry-run-scrolled.png` | The REAL `dryRun: true` diff: `name` changed, `description` changed, `uom_code` changed + `Disabled - withheld by the preset`, `is_discontinued` ADDED, `list_price` unchanged, `ItemType -> Cost price` under Removed. Nothing written (the table behind is unchanged). | AC-12-12, AC-12-22 |
| `06-1280-after-apply-toast.png` | `dryRun: false`: toast "Mapping reset to preset.", dialog closed, table re-rendered from the returned view - including `Discontinued -> Is discontinued` under "Not delivered to Sorento" | AC-12-13, AC-12-23 |
| `07-1280-empty-diff-after-reset.png` | Re-opened immediately after the apply: "This mapping already matches the preset.", `Reset mapping` DISABLED. The reset is idempotent and its output equals the preset row for row. | AC-12-11, AC-12-22 |
| `08-1280-builder-source-columns.png`, `09-375-builder-source-columns.png` | The master formula builder's ONE `Source columns` group (ItemCode, Description, `Desc2`, ... + the `uom` lookup alias `BaseUOMPrice`), the Desc2 join reading "Valid formula", no `Testing` tab | AC-12-01, AC-12-05 |
| `10-1280-simulate-desc2-join.png`, `11-375-simulate-desc2-join.png` | Simulate on the post-reset mapping: `Description` = the joined `ECO SERIES HIGH  LEVEL` | AC-12-04 |

DB after the apply (the reset's own write, not a PUT):

```
ItemCode     | code            | string   | required | enabled
Description  | name            | string   |          | enabled
Description  | description     | string   |          | enabled  formula = the Desc2 join
ItemGroup    | category_code   | string   |          | enabled
ItemBrand    | brand_code      | string   |          | enabled
BaseUOM      | uom_code        | string   |          | DISABLED   (withheld by the preset)
IsActive     | is_active       | t_f_bool |          | enabled
Discontinued | is_discontinued | t_f_bool |          | enabled
BaseUOMPrice | list_price      | string   |          | enabled  formula = the <=0 clamp
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
  is minted from the vendor envelope's `Data.0.AutoKey`, which a pasted flat record has no way to
  supply. Pre-existing behaviour of `simulate_mapping`, unrelated to this plan. The per-field
  values (the point of AC-12-04) are all computed and shown.
- **The inner double space** of `ECO SERIES HIGH  LEVEL` is preserved in the VALUE
  (`GET .../mapping/simulate` returns `"ECO SERIES HIGH  LEVEL"`, pinned by
  `test_s12_master_formula_facts.py`); HTML collapses it for display, which is a browser
  rendering rule, not a mapping-engine one.
- **BL-SS-260, checked as instructed (captain ruling 4) and NOT worked around.** Taking the rows a
  reset produces and PUTting them straight back through `replace_mapping` answers
  **422**: `'is_discontinued' is not a Sorento field accepted for product. Choose one of:
  brand_code, category_code, code, cost_price, description, is_active, list_price, name,
  source_doc_no, uom_code.` The row is captured but not delivered (absent from
  `CanonicalProduct.SINK_FIELDS`), so the save gate rejects it - exactly as it already rejects the
  row first-save seeding has been creating since sprint-5/08; the reset does not introduce the
  condition, it just re-creates the row after a save had swept it away. The operator never SEES
  that 422, because the mapping editor splits the view into deliverable and provenance rows
  (`use-mapping-draft.ts` `splitMappingRows`) and PUTs only the deliverable ones - so the next
  ordinary "Save mapping" on this entity silently DELETES the `is_discontinued` row again
  (`_replace_header_mapping`'s `delete_unknown` sweep). Nothing here special-cases or drops the
  row; the keep-versus-drop ruling is the owner's, per BL-SS-260.
