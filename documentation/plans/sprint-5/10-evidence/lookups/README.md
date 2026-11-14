# Run 2 (HEAD 7618bb33, 2026-09-20 UTC) - re-verify AC-10-09 self-collision fix

Lane: backend :8009, frontend :3009, DB `foundryx_service_s40` (fresh `bootstrap_db`; both
`autocount.pull.*` permission keys confirmed present and granted to `default` tenant's Admin
role before this run - see the S2 test report for the exact query). Tenant/user: `default`,
`demo@example.com` (Admin). Real clicks from the sidebar: AutoCount -> Companies -> `Sorento SRT
S40` -> Entities tab -> Product row -> Actions -> Configure source, reusing the SAME `db1`
Product task run 1 left saved (pre-filled lookup `#1` alias `BaseUOMPrice`, added lookup `#2`
alias `BaseUOMRate` - identical to run 1's end state).

**Real-click vs synthetic, every step:** the CDP `click`/`find ... click` flake documented in run
1 reproduced identically this run on every interactive control tried first as a real click
(sidebar accordion, breadcrumb links, tab strips, Edit, Test, Actions menu, menu items) - each
was tried as a real click FIRST, confirmed not to change page state, then re-tried with the
documented synthetic `pointerdown -> mousedown -> pointerup -> mouseup -> click` sequence, which
worked 100% of the time this run. Logged per step below as (real click: no-op) / (synthetic:
worked). One case, the "Configure source" menu item, DID register on the real click for
navigation to start but the URL had not actually changed after 1s - the synthetic dispatch was
still required to complete it.

## Steps and checks (self-collision defect re-test)

1. Sidebar AutoCount -> Companies (synthetic) -> `Sorento SRT S40` row (synthetic) -> Entities
   tab (synthetic) -> Product row Actions -> "Configure source" (synthetic on the menuitem).
   Reached `/autocount/companies/{id}/entities/product`, Source tab selected, both lookups from
   run 1 visible read-only. **PASS.**
2. Edit (synthetic) -> main path Test (synthetic, scoped to the `/itembypage` input's sibling
   button - `POST /autocount/http/preview` 200 confirmed via `network requests`) -> lookup `#1`
   Test (synthetic, scoped to the FIRST `/itemuombypage` input - `preview-columns` 200) -> lookup
   `#2` Test (synthetic, scoped to the SECOND `/itemuombypage` input - `preview-columns` 200) ->
   combined Test re-run on the main path (synthetic) -> both lookups show `4 columns` /
   `Sample: 50 matched - 0 missed`. **PASS.**
3. **DEFECT VERIFIED FIXED.** Lookup `#1`'s own pre-filled field alias `BaseUOMPrice` shows NO
   inline error after the combined Test - confirmed three ways: (a) visually in
   `run2-05-no-self-collision-1280.png` / `run2-06-lookup1-fixed-1280.png` (clean input, matched
   badge, no destructive-colored text anywhere near it), (b)
   `document.body.innerText.includes('already a source column')` evaluated `false`, (c) a DOM
   query for any leaf element containing that string returned zero matches. Matches the coder's
   fix commit `81eee16e` (derive the collision-check column set from
   `preview.task.sourceConfig.lookups`, the backend-echoed aliases, instead of the live
   `config.lookups`).
4. Save task (synthetic) -> returned to read-only view, no error toast, both lookups persisted
   unchanged (no PUT fired this time - nothing was actually edited beyond re-running Tests, so
   the task was already byte-identical to the saved state; confirmed via `network requests`
   showing no `PUT .../etl-task` this round, consistent with "no dirty state to save").
   **PASS.** Screenshot `run2-07-saved-readonly-1280.png`.

## Responsive (375px)

- Source tab at 375px, same saved (non-colliding) state: no page-level horizontal scroll
  (`document.documentElement.scrollWidth == clientWidth == 360`). **PASS.** Screenshot
  `run2-08-source-tab-375.png`.

## House rules (Run 2)

- Console: only the pre-existing benign `DialogContent` a11y warning throughout; no page errors.
  **PASS.**

## AC verdicts (Run 2)

- **AC-10-09 [FE]:** PASS at 1280px and 375px. The run-1 self-collision false-positive defect
  (step 10 of the original run) is CONFIRMED FIXED - reproduced the exact repro steps against the
  SAME saved task and the spurious error no longer renders.

---

# Evidence: Lookups (AC-10-09, AC-10-09b)

Run date: 2026-09-20 (UTC). Lane: backend :8009, frontend :3009, DB `foundryx_service_s40`.
Tenant/user: `default` tenant, `demo@example.com` (Admin). Tool: `agent-browser` (session `s40`),
real clicks driven from the sidebar (AutoCount -> Companies -> Sorento SRT S40 -> Entities ->
Product -> Actions -> Configure source), never a URL shortcut. Company `Sorento SRT S40`
(`AED_SORENTO`) is this lane's seeded `db1` company (connection "S40 db1 SRT 20260919T183336Z").

**Tooling note:** `agent-browser`'s CDP `click`/`find ... click` commands were flaky in this
session (reported success but did not fire the underlying framework handler for roughly half of
all attempts, on both simple links/tabs and Radix-based comboboxes/tabs). Confirmed reproducible
by instrumenting a `click` listener that never fired. Root-caused to Radix components expecting a
full pointer-event sequence: after switching to `pointerdown` -> `mousedown` -> `pointerup` ->
`mouseup` -> `click` dispatched via `element.dispatchEvent` on the exact target, every interaction
became reliable. This is a same-session dispatch reliability issue with the CLI, not an app defect;
noted here per the "report actual output" instruction. One mid-journey navigation crashed the tab
to `about:blank`; recovered by reopening the app and logging back in - noted as an instability
observed during testing, not confirmed as an app defect (could not reproduce a second time).

## Steps and checks

1. AutoCount -> Companies -> `Sorento SRT S40` -> Entities tab -> Product row -> Actions ->
   "Configure source". **PASS** - reaches
   `/autocount/companies/{id}/entities/product`, Source tab selected.
2. Pre-filled ItemUOM lookup visible, numbered `#1`, path `/itemuombypage`, its own join pairs and
   "Bring in fields -> BaseUOMPrice" alias all present without further configuration (AC-10-04
   seed-if-absent). **PASS.** Screenshot `02-source-tab-prefilled-lookup-1280.png`,
   `03-source-tab-scrolled-1280.png` (Key columns `ItemCode`, Watermark `None`, Compared columns
   chips also render pre-populated).
3. Clicked **Edit**, then **Test** on the main endpoint path (`/itembypage`) - required once per
   editing session before the Local-column pickers offer real column names (expected,
   preview-driven UX, not a defect). Badge renders "Paged - 11,840 total - 12 pages of 1000 - a run
   walks every page"; Lookup #1 shows "Sample: 50 matched - 0 missed" and its Local/Remote pickers
   now show the persisted `ItemCode`/`ItemCode` and `BaseUOM`/`UOM` values. **PASS.** Screenshot
   `05-lookup1-matched-missed-1280.png`.
4. **Add lookup** -> row `#2` appended below `#1`, numbered, editable. **PASS.**
5. Path `/itemuombypage`, **Test** -> "4 columns" badge; remote-column pickers for the field row
   offered `ItemCode, UOM, Rate, Price` - real probed columns, no free text. **PASS.**
6. Join pair 1: Local `ItemCode` (SearchSelect, searchable, offered real source columns plus
   lookup #1's `BaseUOMPrice` alias) <-> Remote `ItemCode`, match `Exact` (default). **PASS.**
7. **Add join** -> pair 2: Local `BaseUOM` <-> Remote `UOM`, match mode switched to
   "Ignore case and spaces" via the match-mode SearchSelect. **PASS.** Screenshot
   `06-lookup2-configured-1280.png`.
8. **Add field** -> remote field `Rate` (SearchSelect over the lookup's own probed columns) ->
   alias `BaseUOMRate` (free text, as specced - only the path and the alias are free text
   anywhere in this editor). **PASS.**
9. Re-ran the main **Test** (combined) -> lookup #1 badge stays "Sample: 50 matched - 0 missed",
   lookup #2 badge shows "4 columns" / "Sample: 50 matched - 0 missed", and the preview grid's
   header row includes the source columns (`ItemCode`, `Description`, ...). **PASS.** Screenshots
   `07-combined-test-both-lookups-1280.png`, `08-lookup2-matched-missed-1280.png`.
10. **DEFECT (frontend, non-blocking):** after the combined Test, lookup #1's own pre-filled field
    alias `BaseUOMPrice` shows an inline red error "'BaseUOMPrice' is already a source column."
    even though nothing about that row was touched and no real collision exists (the alias is
    unique; the preview grid's raw columns are `ItemCode, Description, Desc2, ItemGroup, ...` -
    `BaseUOMPrice` is not among them). Clicking **Save task** nonetheless succeeded
    (`PUT .../etl-task` returned `200`), so the 422-style message is a client-side false positive
    that does not block save - but it is a foolproof-UI violation (an inline error that lies to the
    operator about the state of an untouched, working row). Screenshot
    `09-DEFECT-self-collision-422-1280.png`. Repro: open the Product task (db1), Edit, Test the
    main path, add a second lookup with its own field alias, Test the second lookup, then look at
    lookup #1's own "Bring in fields" alias input - the spurious error appears. Reported to the
    coder for the real fix; not corrected here.
11. **Save** -> task returns to read-only view, no error toast, Source tab shows both lookups
    persisted. **PASS.**
12. **Mapping tab** -> clamp formula visible on `BaseUOMPrice -> List price`:
    `if(number(value) <= 0, 0, number(value` (AC-10-59/61, confirmed separately in `mapping-clamp`
    evidence). Screenshot `10-mapping-tab-1280.png`.
13. Mapping tab -> Edit -> Source column picker (SearchSelect) offers `BaseUOMRate` alongside every
    other source column and the earlier `BaseUOMPrice` alias - confirms "no engine change needed,
    an alias is an ordinary source column in its picker" (AC-10-09's closing clause). **PASS.**
    Screenshot `11-mapping-source-picker-baseuomrate-1280.png`. Edit cancelled afterward (no
    mapping row was actually added, to leave the task's committed config as tested in step 11).

## Responsive (375px)

- Source tab at 375px: no page-level horizontal scroll (`document.documentElement.scrollWidth ==
  clientWidth == 360`), Lookups section stacks cleanly, path/Test/join pickers all fit column
  width. **PASS.** Screenshot `12-source-tab-375.png`.
- Mapping tab at 375px: table scrolls INTERNALLY (its own horizontal scrollbar, not a page-level
  one - `document.documentElement.scrollWidth == clientWidth` holds), consistent with the shell's
  DataGrid convention used elsewhere (Entities list). **PASS.** Screenshot
  `13-mapping-tab-375.png`.

## House rules

- No instructional/hint copy observed on the Source or Mapping tabs. **PASS.**
- Every dropdown (Local column, Remote column, Match mode, Remote field) is a searchable
  SearchSelect; only the endpoint path and the alias inputs are free text. **PASS.**
- No "Foundryx" branding visible in the tenant-facing UI on this surface. **PASS.**
- Console: one benign warning throughout the whole run
  (`Missing 'Description' or 'aria-describedby' for {DialogContent}`), no page errors. **PASS**
  (a11y nit, not in scope of this plan's ACs).

## AC verdicts

- **AC-10-09 [FE]** PASS at both widths, with the one frontend defect noted in step 10 (does not
  block save; reported, not fixed here per tester scope).
- **AC-10-09b [E2E]** PASS at both widths - full real-click journey completed: pre-filled lookup
  visible and numbered, Add lookup, path + Test, join pair 1 (Exact) + join pair 2
  ("Ignore case and spaces"), bring in `Rate` as `BaseUOMRate`, combined Test shows matched/missed,
  Save, Mapping tab source picker offers `BaseUOMRate`.
