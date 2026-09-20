# Evidence: Combine rows (AC-10-82, AC-10-83, AC-10-16, AC-10-40/41) - Run S5b

Run date: 2026-09-20 (UTC). HEAD `29c021905c6e3fc6a4954d17b137779ddf93aadd` (worktree `.claude/worktrees/s40`,
branch `sprint-5/10-autocount-pull-review`). Lane: backend `:8009` (uvicorn, no `--reload`),
frontend `:3009` (`npx next start -p 3009` after `rm -rf .next && npm run build`), DB
`foundryx_service_s40`. Tenant `default`, user `demo@example.com` (Admin). Company
`Sorento SRT S40` (`AED_SORENTO`, this lane's `db1`, id `0e6f5c95-b099-4a1f-8de9-425b63f561b4`).

**Superseded verdict:** the prior README recorded AC-10-82/83 BLOCKED because "Stock balance" was
absent from the Add-entity picker on that lane snapshot. On this HEAD the picker offers
`Customer, Warehouse, Product category, Brand, Unit of measure, Stock balance` - Group E
(AC-10-39..41) is present and reachable. This run supersedes that BLOCKED verdict with a full
PASS-with-one-defect run at both 375px and 1280px.

## Journey (real clicks from the sidebar, both viewports)

1280px screenshots `01`-`15`; 375px screenshots `16`-`25`. Every step below was performed at BOTH
widths via a fresh sidebar navigation (AutoCount -> Companies -> `Sorento SRT S40` -> Entities tab
-> Add entity -> Stock balance -> Configure), not a URL jump.

1. **Add entity -> Configure.** The "Add entity" `SearchSelect` lists `Stock balance`; picking it
   enables **Configure**, which opens a NEW Stock balance task already in `Draft` status, Pull
   delivery, on the Source tab with every field pre-filled and read-only (view mode).
   Screenshot `01-source-tab-prefilled-view-1280.png` / `18-source-tab-view-375.png`.
2. **Edit -> Combine rows section (AC-10-82).** Clicking Edit turns every field live. Scrolling to
   "Combine rows" (a toggle-enabled section below Lookups) shows the PRE-FILLED AC-10-41 config
   exactly: computed columns `item_code = trim(ItemCode)`, `location_code = trim(Location)`,
   `base_qty = if(lower(trim(UOM)) == lower(trim(ItemBaseUOM)), number(BalQty), number(BalQty) *
   number(UomRate))`; require rule `uom_rate` with reason `uom_rate_unresolved`; group by
   `item_code, location_code` (chips); carry `ItemBaseUOM, ItemDescription`; measure `base_qty` sum
   as `qty`; rounding `qty` half up 0dp; drop rules `zero` (`qty == 0`, list rows OFF) and
   `negative` (`qty < 0`, list rows ON). Screenshots `02-combine-section-top-1280.png`,
   `03-combine-drop-rules-1280.png` (1280px), `19-combine-rows-scroll-375.png`,
   `20-drop-rules-375.png` (375px). Shell primitives only - computed/require/drop formulas open
   the existing formula-builder dialog (`Edit formula`), group-by/carry are `MultiSelect` chip
   pickers, no free text except aliases/names/formulas, no hint copy anywhere. **PASS.**
3. **Key columns derived from group-by (AC-10-80).** The read-only "Key columns" pill row under
   the funnel reads `item_code, location_code` - taken from the combine step's group-by, never
   typed separately. **PASS.**
4. **Open the `negative` rule -> toggle "List dropped rows" off.** Toggled the switch directly
   (see Defect 1 below for why "Edit formula" was not usable for this step). Screenshot
   `06-negative-list-rows-off-1280.png` / `21-negative-off-375.png`.
5. **Test (AC-10-83).** Clicked the top-level **Test** button next to the endpoint path. Result
   rendered in well under the "may take ~20-60s" budget noted in the brief (a few seconds both
   runs): `Paged - 68,612 total - 69 pages of 1000 - a run walks every page` on the endpoint, and
   `Sample: 50 matched - 0 missed` on the `/itembypage` lookup. Screenshots
   `07-test-in-progress-1280.png`, `22-test-result-endpoint-375.png`. **This independently
   reproduces AC-10-84's amended "68,612 rows in" figure via a live call against `db1`, not a
   fixture.**
6. **Funnel (AC-10-82).** Scrolling to the Combine rows section after Test shows the funnel over a
   50-row interactive sample: `50 in - 0 excluded - 50 groups - negative: 16 dropped - zero: 29
   dropped - 5 out`, with the drop-rule pills showing counts only (no listed rows) because BOTH
   `zero` and `negative` list-rows switches read off at this point - matching the toggle from step
   4. The combined-rows preview grid below shows `item_code, location_code, ItemDescription,
   ItemBaseUOM, qty` columns with real values (e.g. `1/2" ULTRA CIRCULAR / BRW-BB / ... / PC /
   672`). Screenshots `09-funnel-results-1280.png` (1280px), `23-funnel-375.png` (375px). **PASS.**
7. **Watermark/compared-columns pickers (post-Test).** Watermark column options:
   `None, ItemCode, UOM, Location, BatchNo, BalQty, item_code, location_code, base_qty` - pre-combine
   columns only, `qty` never offered (screenshot `10-watermark-picker-no-qty-1280.png`). Compared
   columns is a DIFFERENT picker (post-combine output columns) and correctly offers/pre-selects
   `ItemBaseUOM, ItemDescription, qty` as the default "all except key columns" set - this is
   expected (compared columns diff the DELIVERED row, so `qty` belongs there); only the WATERMARK
   picker is pre-combine-only. Amending the brief's blanket "never offer qty" to this more precise,
   confirmed split.
8. **Undo -> Save.** Toggled `negative`'s list-rows switch back ON, clicked **Save task** ->
   toast "Task saved." with no other change. Screenshot `11-after-save-1280.png` /
   `24-saved-375.png`. **PASS.**
9. **Reload via real sidebar navigation (not URL).** AutoCount -> Companies -> Sorento SRT S40 ->
   Entities tab -> row Actions ("..." menu, off-screen right on both a 1280 table and a 375
   viewport - required a horizontal scroll/`scrollintoview` to reach) -> **Configure source**
   (direct row-click does NOT navigate on this list - see Defect 2 below). The re-opened task shows
   the persisted state: `zero` list-rows OFF, `negative` list-rows ON - exactly what was saved in
   step 8, confirmed both collapsed (view mode) and after Edit. Screenshot
   `12-persisted-combine-after-reload-1280.png`. **PASS** on persistence.
10. **Mapping tab (AC-10-82 cross-check).** Every Source-column picker on the Mapping tab offers
    only the COMBINED columns - `item_code, location_code, ItemDescription, ItemBaseUOM, qty` -
    never the raw `BalQty`. Screenshots `13-mapping-tab-combined-columns-1280.png`,
    `14-mapping-source-column-picker-no-balqty-1280.png`. **PASS.**
11. **Schedule tab (AC-10-16).** No `ToggleGroup`; a single read-only `StatusBadge` "Pull on
    request" and nothing else on the tab (the push cadence controls are not rendered at all, since
    AC-10-15's contract gate is shut for this consumer version). Screenshot
    `15-schedule-tab-pull-on-request-1280.png`. **PASS.**
12. **Entities list Delivery column (AC-10-17).** Both at 1280px and 375px the Entities table shows
    a Delivery column: `Product` = `Push` badge, `Stock balance` = `Pull on request` badge.
    Screenshots `16-companies-list-375.png` (Companies list), `17-entities-tab-375.png`
    (Entities list). **PASS.**

## Defect 1 - "Edit formula" dialog rejects the pre-filled drop-rule formulas (new, this run)

Opening **Edit formula** on either pre-filled drop rule (`zero`: `qty == 0`, `negative`: `qty < 0`)
shows a validation error **"Unknown name 'qty' - expected the variable 'value', a literal, or a
function call."** and disables the **Apply** button. The dialog's own "Columns" palette for a drop
rule lists only `ItemBaseUOM, ItemDescription, UomRate, item_code, location_code, base_qty` - it
does NOT include `qty` (the measure alias drop rules are defined against, per AC-10-41) or a
generic `value` binding either, despite the error message naming `value` as what's expected. This
reproduces identically for BOTH drop rules and at both viewports (screenshots
`04-negative-rule-formula-builder-1280.png`, `05-zero-rule-formula-builder-check-1280.png`). It
does NOT block Save (the pre-filled formula strings are untouched on disk since Cancel was clicked
both times, never Apply) and does NOT block Test/the funnel (which correctly evaluates `qty == 0`
/ `qty < 0` server-side) - but an operator cannot use "Edit formula" to view or modify EITHER
pre-filled drop-rule formula without hitting a dead end, and a naive click of Apply-while-disabled
is simply inert, so no data corruption risk - just a broken affordance. Root cause is a variable-
scope mismatch: the formula-builder's palette for a drop-rule context needs to expose the
COMBINE's measure-alias columns (`qty` here), not just the pre-combine computed/carried columns.
Reported for the coder; not fixed here.

## Defect 2 - row click on the Entities list does not navigate; false-positive lookup-alias
## validation text (secondary, lower severity, this run)

- Clicking an Entities-list row (`<tr>`, confirmed `onclick` present via DOM inspection) does not
  navigate anywhere - it only applies a row-selection visual state. The only way to reopen an
  existing entity's task editor is the row's **Actions** ("...") menu -> **Configure source** (or
  **Configure mapping**). This is a real, reproducible UX gap versus the Companies list one level
  up, where the equivalent row IS a working navigation link (`cursor:pointer` + `tabindex` present
  there, absent on the Entities row). Low severity (there is a working path via Actions), noted for
  completeness since it changed this run's navigation script.
- After Save, the Lookups' "Bring in fields" alias inputs (`ItemBaseUOM`, `UomRate` - both
  DELIBERATE per AC-10-40's field map) show a red inline message `"<alias>" is already a source
  column.` This is a false positive (Save succeeds anyway, "Task saved." toast fires, and the
  values round-trip correctly on reload per step 9) but is confusing, persistent UI noise on a
  correctly-configured preset. Reported for the coder; not fixed here.

## House rules

- No hint/instructional copy anywhere on the Combine rows section or its dialogs. **PASS.**
- Every column pick is a searchable `SearchSelect`/`MultiSelect` (group-by, carry, measure source/
  op, round measure/mode, watermark, compared columns). **PASS.**
- Console: only the pre-existing benign `DialogContent` missing-`aria-describedby` warning across
  the whole journey; no page errors. **PASS.**
- No em/en dashes, no "Foundryx" branding visible to the tenant. **PASS.**

## Wrapper / live-call timing observed

Both the 1280px and 375px Test runs against the live `https://hapi.sorento.cc.cd` wrapper (via the
lane's `db1` connection) completed in a few seconds - well inside the "~20-60s" budget flagged in
the brief; no retry was needed either time.

## AC verdicts (this run)

- **AC-10-82 [FE]** PASS. Combine rows section renders below Lookups with every field type named
  in the AC, shell primitives only, funnel renders after Test. Defect 1 (formula-builder dead end
  for drop-rule formulas) does not block the AC's own acceptance text but is a real, reproducible
  bug reported above.
- **AC-10-83 [E2E]** PASS at both 375px and 1280px: pre-filled rules visible -> opened the
  `negative` rule's control -> toggled list-dropped-rows off -> Test -> funnel showed the dropped
  count with no listed rows -> toggled back on (undo) -> Save -> reload via real sidebar clicks ->
  persisted correctly.
- **AC-10-16 [FE]** PASS. Schedule tab shows the read-only "Pull on request" `StatusBadge`, no
  toggle, confirmed both viewports.
- **AC-10-17 [FE]** PASS. Delivery column badges (`Push` / `Pull on request`) confirmed on the
  Entities list both viewports.
- **AC-10-40/41 [BE, verified via FE]** PASS. The pre-filled preset matches the spec's formulas,
  group-by, carry, measure, rounding and drop rules exactly, and a live Test against `db1`
  reproduces the `68,612` total-rows figure from AC-10-84 independently of the T-tagged test
  suite.
- **AC-10-80 (key columns derived from group-by)** PASS - confirmed via the read-only Key columns
  pills tracking the group-by chips.
