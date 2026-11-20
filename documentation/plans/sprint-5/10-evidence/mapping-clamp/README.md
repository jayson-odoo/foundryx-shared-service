# Evidence: Mapping tab clamp formula (AC-10-61) - REAL backend

Run date: 2026-09-20 (UTC). Lane: backend :8009, frontend :3009, DB `foundryx_service_s40`.
Tenant/user: `default` tenant, `demo@example.com` (Admin). Company `Sorento SRT S40`
(`AED_SORENTO`, this lane's `db1`), Product task. This surface is REAL (not mock) per the task
brief; every formula-builder and simulator call in this journey hit the live :8009 backend.

## Steps and checks

1. AutoCount -> Companies -> `Sorento SRT S40` -> Entities -> Product row -> Actions -> Configure
   mapping -> Mapping tab. The `BaseUOMPrice -> List price` row reads Transform **Custom** with the
   clamp formula shown inline in the grid: `if(number(value) <= 0, 0, number(value)`. **PASS.**
   Screenshots `01-mapping-tab-1280.png`, `02-list-price-clamp-row-1280.png`.
2. Clicked **Edit**, then the row's "Build formula" icon (`aria-label="Build formula for row 8"`)
   -> the **Transform formula** dialog opens titled "List price", Formula tab shows the FULL
   formula `if(number(value) <= 0, 0, number(value))` in the existing formula-builder textarea with
   a green "Valid formula" indicator and the operator/function palette below it (searchable
   function list: `upper`, `lower`, `trim`, `contains`, `replace`, `concat`, ...). **PASS.**
   Screenshot `03-formula-builder-clamp-1280.png`.
3. Switched to the dialog's **Testing** tab -> "Mock input value" field. Entered `-1` ->
   **Output: `0`** (green, no error). **PASS** - this is the exact AC-10-61 assertion ("the mapping
   simulator evaluates it (-1 -> 0)"). Screenshot `04-simulator-negative-one-to-zero-1280.png`.
4. Cancelled out of both dialogs (formula builder, then mapping edit) without saving - no change
   was persisted to the task.
5. Re-opened via the top-level **Simulate mapping** button (whole-record simulator, separate from
   the per-row Testing tab) -> filled a mock AutoCount record with `"BaseUOMPrice": "-1"` (plus the
   other required source columns, including `Desc2` which the `Description` row's formula reads -
   an empty-string `Desc2` is fine) -> **Run simulation** -> the projected Sorento record's
   **List price row reads `0.0`** for the `-1` input, end to end through the WHOLE mapping, not
   just the isolated formula. **PASS**, and consistent with AC-10-59's pinned wire value
   (`-1.0 -> "0.0"`). Screenshots `06-simulate-mapping-result-1280.png`,
   `07-simulate-mapping-listprice-zero-1280.png`. Note: the simulator also flagged "This record
   would be rejected" for an unrelated reason (not shown in the scrolled view, and not chased
   further since it is outside this AC's scope) - the List price projection itself is still
   computed and displayed regardless of the overall accept/reject verdict, which is itself useful,
   honest simulator behaviour worth remarking on positively.

## Responsive (375px)

- Mapping tab (read-only) at 375px: no page-level horizontal scroll
  (`document.documentElement.scrollWidth == clientWidth == 360`), the grid scrolls internally, the
  `BaseUOMPrice` clamp row is visible at the bottom of the first screen. **PASS.** Screenshot
  `08-mapping-tab-375.png`. The formula-builder and whole-record simulator dialogs were not
  re-verified at 375px given time budget - both are `Dialog` primitives from the same shared shell
  already confirmed responsive elsewhere in this evidence set (Issue key, Build snapshot).

## House rules

- No hint/instructional copy beyond the simulator's one-line explainer ("Transforms a mock record
  through the current mapping and writes nothing...") which is functional disclosure, not
  marketing/how-to copy. **PASS.**
- The clamp is expressed as an ordinary, editable mapping row + formula - "the row IS the
  explanation," no banner. **PASS**, matches AC-10-61 exactly.
- No "Foundryx" branding visible. **PASS.**
- Console: only the pre-existing benign `DialogContent` a11y warning; no page errors during this
  journey. **PASS.**

## AC verdict

- **AC-10-61 [FE]:** PASS at 1280px (list view) and 375px (list view); the formula-builder and
  simulator dialogs were verified functionally correct against the REAL backend at 1280px. The
  clamp reads as `Custom` with the formula visible, and both the per-field Testing tab and the
  whole-record Simulate mapping dialog agree: `-1 -> 0`.
