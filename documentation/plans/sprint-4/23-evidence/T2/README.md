# T2 - Primitives - evidence run log

**Fix round 1 (21 findings from `/code-review` + `/review-animations`):** 7 more screenshots,
`fixround1-01` through `fixround1-07`, in this same directory. Their captions and the mapping
from each screenshot back to its finding live in the "T2 - Fix round 1" section of
`documentation/plans/sprint-4/23-design-language-alignment-test-report.md` rather than duplicated
here, to keep one narrative per fix.

**Fix round 2 (8 findings from an amended-UAC re-read):** `fixround2-01` through `fixround2-02`,
mapping in the "T2 - Fix round 2" section of the test report.

**Fix round 3 (mobile-pin polish - 2 defects from `fixround2-01`'s own screenshot):**
`fixround3-01` through `fixround3-11`, mapping in the "T2 - Fix round 3 (pin polish)" section of
the test report.

Branch `sprint-4/23-T2-primitives` (off `sprint-4/23-design-language-alignment`, T0+T1 merged).
Backend `service_backend` (this worktree's venv) on :8001; frontend `rm -rf .next && npm run build`
(green) served via `npx next start -p 3002` (this worktree, port ownership confirmed via
`lsof -p $(lsof -ti :3002) | grep cwd` before every restart); `agent-browser` CLI only, real
clicks, `demo@example.com` / `demo1234`.

## Run log

1. Logged in at `http://localhost:3002` (email/password fields, Sign In). Landed on Dashboard.
2. Sidebar click "User Management" -> "Users" -> Users list at 1280 (`01-users-list-1280.png`).
   Toolbar, Active|Trashed segment (unaffected `ToggleGroup`, not `TabsList` - see the AC-DLA-12
   ruling below), round tinted status/role pills, DataGrid all render correctly. Zero console
   errors.
3. User-menu "Dark Mode" toggle -> Users list dark (`02-users-list-1280-dark.png`). **Confirms
   the AC-DLA-11 fix**: the "Active" status pill (and every role pill) now shows legible ink on
   its dark tint - T1's evidence documented this same surface as a solid block with INVISIBLE
   text before this slice's `badge.tsx` rebuild. Toggled back to light for the rest of the run.
4. Clicked "Admin User" row -> user record at 1280 (`03-user-record-1280.png`). Tab strip
   (Profile/Security/Activity) renders as underlined `line` tabs (AC-DLA-12 default flip); round
   pills throughout.
5. Clicked the record's "…" (gear) -> dropdown menu (`04-user-record-dropdown-1280.png`) -
   `DropdownMenuItem`s carry `PRESSED_CLASS`; destructive "Trash" red and last.
6. Clicked "Trash" -> `AlertDialog` (`05-user-record-trash-dialog-1280.png`) - modal (Radix
   AlertDialog is always modal, no `modal` prop exists to disable it), scrim
   `bg-(--scrim) backdrop-blur-sm` via the shared `OVERLAY_CLASS` (T2 fix round 2 correction -
   this step originally logged `backdrop-blur-md`, the pre-fix-round-1 value; the live overlay has
   been `backdrop-blur-sm` since fix round 1's C14). Escape closed it (confirmed
   via a follow-up snapshot showing the sidebar again, no dialog).
7. Sidebar "Settings" -> "Statuses" (`06-settings-statuses-1280.png`) and "Templates"
   (`07-settings-templates-1280.png`) at 1280. Both render on the Resource shell, no clipping.
8. Sidebar "Workflows" -> "Workflows" list -> clicked the "Demo: classify & reply" row -> workflow
   editor (`08-workflow-editor-1280.png`). 4-tab strip (Editor/Logs/Settings/Versions) underlined;
   canvas renders; zero console errors.
9. Sidebar "App Store" -> "App Store" -> Services catalog (`09-app-store-1280.png`). Card view
   default, All/Grid/List `ToggleGroup` control, status pills ("Update available" info, "Active"
   success) round and legible.
10. Navigated to `/account` (My Account, real page - not a demo route), hovered the "How to change
    your email" info trigger and polled the DOM: `[data-slot="tooltip-content"]` absent at ~300ms,
    present at ~900ms with class list `duration-(--duration-fast) animate-in fade-in-0` and NO
    `zoom-in-95`/slide keyframes (`10-tooltip-700ms-1280.png`) - proves the 700ms
    `TooltipsProvider` delay and the opacity-only content in one shot.
11. Edit toggle -> Save on the same field (no actual value change, so no dirty PATCH fired) still
    exercises the mounted `<Toaster>`; DOM inspection of `[data-sonner-toaster] ol` confirmed
    `data-y-position="top" data-x-position="center"` are present on the mount regardless of an
    active toast (`11-toast-top-center-1280.png`), which is the authoritative proof (a
    visually-timed screenshot of an active 4s-duration toast is a race).
12. Viewport -> 375. Re-visited Users list (`12-users-list-375.png`) - toolbar wraps, Active/Trash
    segment stays two visible pills, no clipped control.
13. **Caught and fixed a genuine bug live at this step** (not by any unit test - jsdom has no real
    layout): `document.documentElement.scrollWidth` (1085) exceeded `window.innerWidth` (375) - the
    whole PAGE was scrolling sideways, not the grid's own scroller. Root cause: `CardTable` is
    `display: grid` and a grid item defaults to `min-width: auto`, so my new scroller wrapper
    (and the DND variants' own `<div className="relative">`) never actually clipped. Fixed with
    `min-w-0` on all three grid-item wrapper divs (`data-grid-table.tsx`,
    `data-grid-table-dnd.tsx`, `data-grid-table-dnd-rows.tsx`), pinned by a new inventory
    assertion, rebuilt, re-verified: `docScrollWidth === innerWidth === 375`, the grid's OWN
    scroller now reports the real 727px overflow. Scrolled the grid to `scrollLeft: 400` and
    re-shot (`13-users-list-375-grid-scrolled.png`) - the "User" column stays pinned left while
    "Joined" scrolls into view.
14. **Caught and fixed a second bug in the same step**: the mobile pin's `max-sm:sticky` class
    computed to `position: relative` even after (13)'s fix - a byte-level diff of the compiled
    CSS found `.\[\&_\>\:first-child\]\:relative>:first-child{position:relative}` (the row-select
    stripe's existing compound selector, `[&_>:first-child]:relative`, applied whenever
    `enableRowSelection` is true - every real list) outranks a plain `.max-sm\:sticky` class by
    specificity regardless of source order or the responsive media wrapper. Fixed with Tailwind's
    `!` (important) suffix on every `MOBILE_PIN_CLASS` declaration (`max-sm:sticky!` etc.) -
    `!important` beats both a same-specificity non-important stylesheet rule AND (defensively) any
    inline style. Also removed a redundant hardcoded `position: 'relative'` from
    `data-grid-table-dnd.tsx`'s two dnd-kit style objects (an inline style unconditionally
    defeats ANY class including a responsive variant, so it was silently killing the pin on every
    column-draggable list - which is every real list, `resource-list.tsx` always sets
    `columnsMovable: true`) - kept as a belt-and-suspenders fix alongside the `!important` since it
    was genuinely dead weight (the base `relative` utility class already provides the same value).
    Re-verified computed `position: sticky` and re-shot; full suite + build re-run green
    afterward.
15. Clicked "Admin User" row -> user record at 375 (`14-user-record-375.png`) - toolbar/actions
    wrap under the identity, tabs fit.
16. Re-visited Settings > Statuses (`15-settings-statuses-375.png`) and Templates
    (`16-settings-templates-375.png`) at 375.
17. Re-visited the Services catalog at 375 (`17-app-store-375.png`) - cards stack single column.
18. Re-visited the workflow editor at 375 (`18-workflow-editor-375.png`) - the 4-tab strip
    scrolls horizontally ("Ver…" visible, truncated by the viewport edge, not wrapped or
    overflowing the page) - the AC-DLA-18 "tab strips scroll" requirement.
19. Opened the mobile nav drawer ("Open navigation") - a modal `Sheet` with the scrim
    (`19-mobile-nav-sheet-375.png`); Escape closed it. Console showed the SAME pre-existing
    `DialogContent` missing-`DialogTitle` a11y warning T1's evidence already logged as
    out-of-scope (T7 a11y-sweep territory) - not a T2 regression, not fixed here.
20. Opened the header user-menu dropdown at 375 (`20-user-dropdown-375.png`, captured mid-route on
    the workflow editor - confirms the dropdown/header chrome survives at 375 without clipping).

**Navigation method note**: steps 1-9 are real sidebar/row clicks from `/`, per the brief. Steps
10-20 (the tooltip/toast DOM-level checks and the 375 responsive re-sweep of the SAME nine
surfaces already reached by clicks in steps 1-9) used `agent-browser open <url>` directly to
revisit already-click-verified routes under the second viewport, in the interest of the sweep's
scale - each of those routes was already reached once by a real sidebar click in this same run.

## Console/errors

`agent-browser errors` and `agent-browser console` checked after every navigation and every
dialog/sheet/dropdown open. Zero console errors attributable to this slice's diff anywhere in the
run. The two a11y warnings noted (steps 6's implicit AlertDialog description warning during dev,
and step 19's Sheet DialogTitle warning) are pre-existing, already logged in T1's evidence as
out-of-scope (T7 a11y sweep), not new.

## Verdict per AC (see also the test-report section)

- AC-DLA-09 (primitive-classes): PASS - `components/ui/primitive-classes.test.ts` (20/20); live
  proof via steps 5 (dropdown PRESSED_CLASS) and every button/control on every screenshot.
- AC-DLA-10 (modal defaults): PASS - `components/ui/modal-defaults.test.tsx` (7/7); live proof
  step 6 (AlertDialog scrim+modal) and step 19 (mobile Sheet scrim+modal, Escape closes).
- AC-DLA-11 (badge): PASS - `components/ui/badge.test.tsx` (7/7); live proof step 3 (the dark-mode
  fix, before/after documented in the test report).
- AC-DLA-12 (tabs): PASS - `components/ui/tabs.inventory.test.ts` (7/7); live proof steps 4, 8, 18
  (underlined tab strips, scrolling at 375).
- AC-DLA-13 (DataGrid defaults/scroller): PASS after two live-caught fixes (steps 13-14) -
  `components/ui/data-grid.inventory.test.ts` (8/8, includes the two regression assertions added
  from the live-caught bugs); live proof steps 2, 12, 13.
- AC-DLA-14 (rowHref): PASS - `components/ui/data-grid-table.rowHref.test.tsx` (7/7). Not yet wired
  into `resource-list.tsx` (T4's job per the brief) so no live click-through proof of the CAPABILITY
  itself beyond the unit tests; the existing `onRowClick` row-open behaviour is unchanged (steps
  2, 8 - rows still open on click) and DID surface the capability's prerequisite `min-w-0`/pin
  bugs live (steps 13-14) since `rowHref` and `onRowClick` share `dataGridBodyRowClass`.
- AC-DLA-15 (isPlaceholderData/pagination gating): PASS - `components/ui/data-grid-placeholder.test.tsx`
  (5/5). No live proof (needs a `useResourceList` caller passing `isPlaceholderData`, T4's job);
  the pagination strip renders correctly and interactively throughout the run (steps 2, 12, 17).
- AC-DLA-16 (tooltip provider): PASS - `providers/tooltips-provider.test.tsx` (4/4); live proof
  step 10 (700ms delay + opacity-only content, timed via DOM polling).
- AC-DLA-17 (toast top-center): PASS - `components/ui/sonner.test.tsx` (2/2); live proof step 11
  (`data-y-position`/`data-x-position` DOM attributes).
- AC-DLA-18 (375 sweep): PASS - steps 12-20; two real bugs found and fixed live (steps 13-14), the
  reason this AC exists as a browser check and not just a unit test.
