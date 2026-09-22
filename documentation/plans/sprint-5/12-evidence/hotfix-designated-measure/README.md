# Hotfix evidence: combine editor Designated measure picker

Branch `fix/combine-designated-measure-picker`, worktree `.claude/worktrees/s50`.
Lane ports: frontend `:3012`, backend `:8012` (`foundryx_service_s50` DB, already
seeded/running before this hotfix started).

## Bug

`combine-editor.tsx`'s "Designated measure" `SearchSelect` fed
`measureAliasOptions` (post-group measure aliases, e.g. `qty`). The backend
validator (`service_backend/modules/autocount/http_source/combine.py` ~line
501) requires `combine.measure` to be a PRE-GROUP column (a source column or
a computed-column alias, e.g. `base_qty`) and 422s any measure alias with
`'<value>' is not a known column.`. A hand-built combine could never be saved
through the UI. The shipped stock preset never hit this because it seeds
`measure: "base_qty"` directly at task creation.

## Fix

`CombineEditor` now feeds the picker with `designatedMeasureOptions`, derived
from `allColumnOptions` (source columns + computed aliases) - the same
pre-group set `groupOptions`/`measureSourceOptions` already use - with a
fallback that keeps a legacy out-of-set value visible instead of blanking the
trigger. `SearchSelect` blanks the trigger label for any `value` absent from
its `options`, so the legacy-value fallback matters for saved configs that
predate this fix.

## Run log (agent-browser, session `s51`, headless)

1. Logged in `demo@example.com` / `demo1234` at `http://localhost:3012`.
2. Sidebar AutoCount -> Companies -> `Mocha s50` (Open API company, no-auth
   REST connection `Mocha REST (s50)`).
3. Entities tab had no `Stock balance` task yet on this lane - added one via
   `Add entity` -> `Stock balance` -> `Configure` (creates a Draft task
   seeded from the stock preset, `measure: "base_qty"` already correct by
   construction - the preset path, not the bug path).
4. Edit -> scrolled to the Combine rows section -> opened the "Designated
   measure" picker at 1280x900.
   - Screenshot `1280-designated-measure-picker-offers-base_qty-not-qty.png`:
     options are `ItemBaseUOM, ItemDescription, UomRate, item_code,
     location_code, base_qty` (source columns + computed aliases); `qty`
     (the measure alias defined a few rows below) is NOT offered; `base_qty`
     carries the checkmark.
5. Proved the save path end to end (the preset's own `base_qty` was already
   selected, so re-picking it would not dirty the form): changed Designated
   measure to `item_code` (a pre-group source-derived computed alias, same
   option set the fix now offers), ran the Source tab's own Test (required
   before Save is enabled - `httpPreviewValid` gate), then Save task.
   - Screenshot `1280-save-succeeds-no-error.png`: "Task saved." toast, no
     422/validation error - confirms the picker's offered values are exactly
     what the backend validator accepts.
6. Re-opened Edit, restored Designated measure to `base_qty` (matching the
   stock preset), Test, Save task - task left in its original preset state.
7. Re-opened Edit, resized to 375x800, scrolled to the picker, opened it.
   - Screenshot `375-designated-measure-picker.png`: same pre-group option
     set, viewport-clamped, `base_qty` selected, `qty` absent.
8. Cancelled the edit (no pending changes after the viewport resize) and
   closed the session.

No console/server errors observed during the run (`/tmp/s50-frontend.log`
checked after the session).

## Files

- `1280-designated-measure-picker-offers-base_qty-not-qty.png`
- `1280-save-succeeds-no-error.png`
- `375-designated-measure-picker.png`

## Assumed / notable

- The Open API company `Mocha s50` had no `stock_balance` task configured on
  this lane; one was created through the UI per the brief's fallback
  instruction (timestamped nothing extra needed - the task is named
  "Stock balance" by the entity type, scoped to this company only).
- Saving with `item_code` as the designated measure (step 5) is not a
  semantically meaningful configuration - it exists only to prove the
  save-path accepts a pre-group, non-alias value without a 422, then the
  task was restored to the correct `base_qty` in step 6.
