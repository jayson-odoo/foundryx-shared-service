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

## Fix (round 1)

`CombineEditor` now feeds the picker with `designatedMeasureOptions`, derived
from `allColumnOptions` (source columns + computed aliases) - the same
pre-group set `groupOptions`/`measureSourceOptions` already use - with a
fallback that keeps a legacy out-of-set value visible instead of blanking the
trigger. `SearchSelect` blanks the trigger label for any `value` absent from
its `options`, so the legacy-value fallback matters for saved configs that
predate this fix.

## Fix (round 2, reviewer should-fix)

Round 1 offered every pre-group column, which is wider than the RUNTIME
contract actually supports: `excluded_row_for_mapping_failure`
(`combine.py:966-978`) resolves the designated measure's grouped value by
finding the `measures[]` entry whose `source` IS `combine.measure` and
reading that entry's alias off the post-group row. A pick that is not a
declared `measures[].source` saves clean but reads back `measure: null` in
every exclusion entry, and a non-numeric pick silently inflates
`excludedNonzeroCount` (`combine.py:944`, "not exactly 0" fails closed).

`designatedMeasureOptions` now narrows to the DECLARED `measures[].source`
values (in pre-group column order) whenever at least one measure has a
non-empty source; it only falls back to the full pre-group set when no
measure has declared a source yet (nothing to narrow to). The legacy
out-of-set fallback is unchanged. `groupOptions` (the base pre-group option
list, now also consumed by the narrowing logic) picked up its own `useMemo`
in the same pass - it was recomputing a fresh array every render.

## Run log round 1 (agent-browser, session `s51`, headless)

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

## Run log round 2 (agent-browser, session `s52`, headless)

Build first: `pkill -9 <the worktree-owned next-server pid>` (confirmed via
`lsof -p <pid> | grep cwd` before kill) -> `cd service_frontend && rm -rf
.next && npm run build` -> `npx next start -p 3012 &`. Backend `:8012`
untouched (no backend change in round 2 either).

1. Logged in `demo@example.com` / `demo1234` at `http://localhost:3012`.
2. Navigated straight to the round-1 `Stock balance` task on `Mocha s50`
   (same company/task as round 1 - see the deviation note below) via the
   sidebar/company/Entities path, then Edit, scrolled to Combine rows.
3. Opened the "Designated measure" picker at 1280x900. The task's one
   measure (`{source: 'base_qty', op: 'sum', alias: 'qty'}`) is unchanged
   from round 1, so the picker is now expected to narrow to JUST `base_qty`.
   - Screenshot `1280-designated-measure-picker-offers-base_qty-not-qty.png`
     (RE-TAKEN, replaces the round-1 file of the same name): the option list
     contains exactly one entry, `base_qty`, checked. `ItemCode`, `UOM`,
     `Location`, `BatchNo`, `BalQty`, `ItemBaseUOM`, `ItemDescription`,
     `UomRate`, `item_code`, `location_code` and `qty` are ALL absent - every
     pre-group column round 1 still offered but this measure does not read
     from is now correctly excluded, alongside the measure alias `qty`.
4. Escaped the picker and Cancelled the edit (no pending changes) - task
   left in its round-1 saved state (`measure: "base_qty"`).

No console/server errors observed (`/tmp/s50-frontend-r2.log` checked after
the session).

## Files

- `1280-designated-measure-picker-offers-base_qty-not-qty.png` (round 2:
  narrowed set, `base_qty` alone)
- `1280-save-succeeds-no-error.png` (round 1: save-path proof, still valid -
  round 2 changed no save-path behaviour)
- `375-designated-measure-picker.png` (round 1: viewport clamp + full
  pre-group set, taken before any measure had a declared source - still an
  accurate fixture for the "no measure source declared -> full set" fallback
  path, since that path is unchanged by round 2)

## Assumed / notable

- The Open API company `Mocha s50` had no `stock_balance` task configured on
  this lane; one was created through the UI per the round-1 brief's fallback
  instruction (the task is named "Stock balance" by the entity type, scoped
  to this company only - no separate name field to timestamp).
- Round-2 DEVIATION from the "provision a dedicated tenant/timestamped task
  when mutating shared state" rule: round 2 reused the SAME `Stock balance`
  task round 1 created and left saved, rather than creating a second
  timestamped task, because the point of round 2 is to re-verify the exact
  same task/measure configuration under the narrowed logic (a fresh task
  would have no `measures[].source` yet and would only exercise the
  fallback path, not the narrowing this round-2 fix adds). No new mutation
  was made - round 2 only opened the picker to read its option set, then
  cancelled without saving.
- Saving with `item_code` as the designated measure (round 1, step 5) is not
  a semantically meaningful configuration - it exists only to prove the
  save-path accepts a pre-group, non-alias value without a 422, then the
  task was restored to the correct `base_qty` in step 6.
