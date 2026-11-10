# T3 Motion - evidence run log

Slice: `sprint-4/23-T3-motion` (branched from `sprint-4/23-design-language-alignment`,
T0+T1+T2 merged). Contract: `documentation/plans/sprint-4/23-design-language-alignment-acceptance-criteria.md`
AC-DLA-19 .. AC-DLA-26. Plan section 3.3.

## Environment

- Backend: shared `service_backend` on :8001 (owned by the `.claude/worktrees/s23` checkout's
  `uvicorn` process, per the repo's "one Postgres/one backend serves every worktree" convention).
  Health-checked `200` before the run.
- Frontend: this worktree's checkout, `rm -rf .next && npm run build` (green) then
  `npx next start -p 3003` (3001 free/unowned at the time, 3002 owned by a sibling lane's
  `next-server`, per the brief's port assignment - confirmed via `lsof -ti :3002` +
  `lsof -p <pid> | grep cwd` before starting).
- Browser: `agent-browser` CLI only (no Playwright, per D15). Sidebar clicks from `/`; a
  logged-in session (`demo@example.com`, tenant `default`) was already live in the CLI's
  persistent browser profile from an earlier verification pass in this session, so no fresh
  login was needed (confirmed via the user-menu identity: "Demo User" / `demo@example.com`).

## Environment finding that shaped this run (not a T3 code regression - flagging for the reviewer and for `docs/reference/process-lessons.md`)

**`service_backend/app/config.py`'s CORS allow-list stops at port 3002**
(`cors_origins` default = `"http://localhost:3000,http://localhost:3001,http://localhost:3002"`;
`cors_origin_regex` = `` r"http://[a-z0-9-]+\.localhost:300[0-2]" `` - the character class caps
at `0-2`). This plan's own port-assignment scheme (T2 = 3002, T3 = 3003, and presumably T4+ move
further up) runs past that allow-list the moment a second concurrent lane needs a third port.
Effect observed live: every `Authorization`-bearing request from `localhost:3003` to the shared
`:8001` backend fails its CORS preflight (`OPTIONS ... 400`), so every backend-driven list/form
in the app rendered empty (Users, Roles, App Store, Documents) even though the pages themselves,
the auth session, and every pure-client surface (dialogs, sheets, dropdowns, the mobile drawer)
worked perfectly. This is shared infrastructure (`service_backend/app/config.py`/`.env`, and the
running process is owned by the `s23` worktree, not this one) - out of scope for a single slice
coder to patch and restart out from under concurrent lanes, so it was **worked around, not
fixed**: evidence below leans on surfaces that don't need live backend data (SearchDialog,
Notifications sheet, the user-menu dropdown, the mobile nav/mega-menu drawers, the Roles Popover
and Status Select on the New User form - both open and animate correctly even though their
option lists render empty for the same CORS reason) plus direct DOM/computed-style proof of the
spring's progression over real wall-clock time (`agent-browser eval`, since the CLI's own
round-trip latency makes a literal 50ms screenshot burst impractical - same adaptation T1/T2's
evidence runs made for their own timing claims). **Recommend widening `cors_origins`/
`cors_origin_regex` to a wider port range (or a regex on the port instead of an enumerated
class) before more slices in this plan need a 4th+ concurrent port.**

A second, self-inflicted-and-recovered-from artifact: one exploratory `eval` call removed
overlay DOM nodes directly (bypassing React) to unstick a misdirected click, which correctly
crashed React with "Application error: a client-side exception has occurred" on the next
paint - a `agent-browser open` reload recovered cleanly. Not a product bug; documented so a
reviewer doesn't mistake the one screenshot of that error page (not included above) for a
regression.

## Run log

1. `agent-browser open http://localhost:3003` -> Dashboard (already authenticated). Sidebar
   click "User Management" -> "Users" -> `01-users-list-empty-cors-1280.png` - list renders
   correctly (toolbar, segmented control, DataGrid header) but "No data available" per the CORS
   finding above, not a T3 issue (identical empty state on Roles/App Store/Documents).
2. Clicked the header avatar ("User menu") -> DropdownMenu opens on the spring, scaling in from
   the top-right corner exactly where the trigger sits (`02-user-dropdown-1280.png` /
   `10-dropdown-menu-user-1280.png`) - confirms "Demo User" / `demo@example.com`, i.e. the
   canonical seeded demo tenant (its Users/Roles tables being CORS-unreachable, not empty, is
   the finding above).
3. Header search icon -> `SearchDialog` (a plain client-mock `Dialog`, zero backend calls) opens
   centered, fully opaque, scrim blurred (`03-search-dialog-1280.png`). Escape closes it. Motion
   is normal (not yet reduced) for this and the next three steps.
4. Header bell icon -> Notifications `Sheet` (also zero backend calls) -> screenshot
   `05-notifications-sheet-1280.png`; Escape, then DOM-polled the SAME sheet reopening (real
   pointer events on the bell button, sampled the inner `motion.div`) to confirm slide-only
   under normal motion - see the timing table in step 12 below (kept together with the other
   timing tables rather than duplicated here).
5. Dialog spring timing + interruptibility, still under normal motion - see step 13 below (the
   full trajectory table + the mid-close reopen proof).
6. `agent-browser set media light reduced-motion` -> reopened the `SearchDialog` -> DOM-polled
   `[data-slot="dialog-content"] > div` (the inner `motion.div` the spring actually animates -
   the OUTER `DialogPrimitive.Content` carries only Radix's own positioning transform) at 16ms:
   `opacity: 0.963`, `transform: matrix(1,0,0,1,-300,-304.5)` - **no scale component** (identity
   1,0,0,1) - matches `REDUCED_MOTION_TRANSITION` (10ms), proving AC-DLA-26's "opaque on the
   first frame, cross-fade only" live, not just via the unit test. Screenshot
   `04-search-dialog-reduced-motion-1280.png`.
7. Reduced motion still on: polled `.sidebar`'s computed `transitionProperty`/`transitionDuration`
   -> `"none"` / `"0s"` - the width transition is entirely absent under reduced motion
   (AC-DLA-24), not just shortened.
8. `agent-browser set viewport 375 800` -> Home at 375 (`06-home-375.png`) -> hamburger icon ->
   the sidebar nav is now a **vaul `Drawer`** (`data-vaul-drawer-direction="left"`), scrim
   `OVERLAY_CLASS_STATIC`, still under reduced motion: polled `[data-vaul-drawer]`'s
   `transitionDuration` -> `"0.001s"` (1ms), matching AC-DLA-23's requirement exactly.
   `07-mobile-sidebar-drawer-reduced-motion-375.png`.
9. `agent-browser set media light` (motion back on, stays on for the remainder of the run) ->
   reopened the same drawer -> polled `transitionDuration` -> `"0.5s"` (vaul's own drag-tracked
   default, untouched by T3 - the
   plan only asks T3 to own direction/overlay/reduced-motion, not vaul's own physics).
   `08-mobile-sidebar-drawer-normal-375.png`.
   **Fix round 1 note (finding 14):** `07-...-reduced-motion-375.png` and
   `08-...-normal-375.png` are byte-identical checksums - both are SETTLED-STATE screenshots of a
   fully-open drawer, which necessarily look the same regardless of how long the open took. The
   actual motion proof is the `transitionDuration` values quoted above (`0.001s` vs `0.5s`), not
   the images; labelled here so a reviewer doesn't read the identical files as a copy-paste error.
10. Second mobile trigger (the mega-menu icon, right of the hamburger) -> also a vaul `Drawer`
    now, `direction="left"`, shows the mega-menu's own item list ("Home", "My Account", "User
    Management", "Developers") -> `09-mega-menu-mobile-drawer-375.png`. (One CLI quirk hit and
    worked around here: `agent-browser click "button:has(svg...)"` intermittently landed on a
    DIFFERENT header icon than the one the selector named - a `agent-browser eval` dispatching a
    real `pointerdown`/`pointerup`/`click` sequence directly on the located element was reliable
    every time after that; used for the rest of the run's ambiguous icon-button clicks.)
11. Set viewport back to 1280.
12. Sheet slide-only proof (referenced from step 4 above): `agent-browser eval` fired the bell
    button's own pointer events, then sampled `[data-slot="sheet-content"]`'s `motion.div` on a
    timer:

    | t | opacity | transform |
    |---|---|---|
    | ~30ms | 1 | `matrix(1,0,0,1,466.658,0)` |
    | ~130ms | 1 | `matrix(1,0,0,1,183.869,0)` |
    | ~330ms | 1 | `matrix(1,0,0,1,11.476,0)` |

    Opacity is `1` at every sample (no fade) and the matrix's scale terms are always `1,0,0,1`
    (no scale) - only the translate-X term travels from ~467px toward 0 as the panel slides in
    from the right. Confirms AC-DLA-20's "Sheet (slide per side, no scale)" over real time.
13. Dialog spring timing + interruptibility (referenced from step 5 above; `lib/motion.ts`
    `SURFACE_SPRING`, `visualDuration: 0.3`): reopened `SearchDialog`, sampled the inner
    `motion.div`:

    | t | opacity | scale (matrix a/d) |
    |---|---|---|
    | ~16ms | 0.042 | 0.962 |
    | ~100ms | 0.527 | 0.981 |
    | ~300ms | 0.967 | 0.999 |

    Then the interruptibility claim itself (AC-DLA-20 "re-opening mid-close continues from its
    current scale, no jump to 0.96"): opened fully (opacity 0.991, scale 1), dispatched Escape,
    sampled 60ms into the close (opacity 0.680, scale 0.986 - already animating back down), then
    **re-clicked the trigger immediately** and sampled 16ms later: opacity **0.523**, scale
    **0.981** - continuing the trajectory from the live in-flight values, not reset to the fresh
    -open start (opacity 0, scale 0.96). No jump.
14. DropdownMenu spring timing (`MENU_SPRING`, `visualDuration: 0.2`): user-menu button, real
    pointer events via `eval`, sampled the Content's inner `motion.div`:

    | t | opacity | scale |
    |---|---|---|
    | ~16ms | 0 | 0.964 |
    | ~100ms | 0.770 | 0.991 |
    | ~200ms | 0.972 | 0.999 |

    `10-dropdown-menu-user-1280.png` is the fully-open screenshot from this same interaction.
15. Navigated to `/user-management/users/new` (a real product route, not a mock). Roles field
    `Popover` (`SearchSelect`) opened on real pointer events -> `11-popover-roles-1280.png` -
    positioned and scaled from the trigger correctly; "No matches" in the list is the same CORS
    finding (the options fetch is blocked), not a motion defect.
16. Status field `Select` (`components/ui/select.tsx`, a real `<Select>` not a `SearchSelect`) -
    opened via real pointer events, sampled the Content's inner `motion.div` (found via
    `[data-slot="select-content"] .origin-...`, since react-hook-form's `FormControl` `Slot`
    overwrites the trigger's own `data-slot` with `"form-control"` - a pre-existing behaviour,
    unrelated to this diff):

    | t | opacity | scale |
    |---|---|---|
    | ~16ms | 0.038 | 0.962 |
    | ~100ms | 0.708 | 0.989 |
    | ~200ms | 0.963 | 0.999 |

    Same menu-spring trajectory as DropdownMenu. `12-select-status-1280.png`.
17. Documents (`13-documents-cors-blocked.png`) and App Store (`14-app-store-cors-blocked.png`)
    confirmed the CORS finding is systemic, not a Users-list-only anomaly, and that ContextMenu
    (Documents trash/folder-tree right-click) and HoverCard (`resource-list.tsx`) have no
    backend-data-free path to reach live in this environment - see the AC-DLA-20/21 verdict note
    below for how those two are covered instead.

## Console

`agent-browser console` checked after every navigation and every surface open/close. Zero new
console errors anywhere in this run. The two a11y warnings already logged by T1/T2's evidence as
out-of-scope (T7 territory) recurred identically and are not new:
`DialogContent requires a DialogTitle` / `Missing Description or aria-describedby` (fired by
`notifications-sheet.tsx`, a file this slice never touches).

## `npm run lint` / `npm test` / `npm run build` gate tails

- `npx eslint <36 touched files, minus the 16 deleted>` - clean, zero errors/warnings.
- `npx vitest run` - **186 files / 1610 tests, all green** (includes the new `lib/motion.test.ts`,
  `components/ui/deleted-motion-components.guard.test.ts`, and one pre-existing test file fixed
  for the spring's real async close - see "Fix note" below).
- `rm -rf .next && npm run build` - green (Next 15.3.4, zero type errors after the two Radix
  `forceMount`-on-Select compile errors below were fixed).

## Fix notes (both load-bearing, both explained inline in the diff too)

1. **`vitest.setup.ts` gained `MotionGlobalConfig.skipAnimations = true`** (`motion/react`).
   Without it, `AnimatePresence` + `forceMount`'s exit animation never resolves under jsdom (no
   real animation-frame pump), so a closed Popover/DropdownMenu/etc. stays mounted with
   `aria-expanded="true"` for the rest of the test - broke 4 pre-existing test files (9 tests)
   that open-then-close one of these surfaces and then query something else. Ported the same fix
   `sorento_crm`'s `vitest.setup.ts` uses for the identical reason.
2. **Radix Select's `Content`/`Portal` have NO `forceMount` prop at all** (confirmed against
   `@radix-ui/react-select@2.2.6`'s own `.d.mts` - unlike Dialog/Popover/DropdownMenu/HoverCard/
   ContextMenu/Menubar, which all do). `SelectContent` therefore cannot gate an `<AnimatePresence>`
   exit the way the other eight surfaces do - it plays the menu spring in on mount and Radix
   unmounts it un-animated on close, exactly the same accepted shape `MenubarContent` already
   uses in this codebase (and in `sorento_crm`) for the identical reason. Documented inline in
   `select.tsx`; AC-DLA-20 is satisfied for the entrance (the only half Radix's own lifecycle
   allows here).
3. **`components/platform/rule-builder/rule-builder.test.tsx`** - one test (`offers operators
   per the selected fact type`) used synchronous `fireEvent.click` with no `await`/`waitFor`
   between closing the fact Popover and querying the Operator combobox. Even with
   `skipAnimations` collapsing the tween itself, `AnimatePresence`'s exit-complete callback still
   resolves on a microtask, so the very next synchronous line ran one tick too early. Wrapped the
   query in `waitFor` (both `waitFor` import and the `it` -> `async` change scoped to that one
   test) rather than touching the (correct) production code.

## AC verdicts (T3)

| AC | Verdict | Proof |
|---|---|---|
| AC-DLA-19 | PASS | `lib/motion.ts` (ported verbatim + M2 exports, already present from the start per D1); `lib/motion.test.ts` (11/11, pins every branch: lightbox vs menu preset, reduced-motion collapse, `useOpenState` contract) |
| AC-DLA-20 | PASS (Dialog/AlertDialog/Sheet/Popover/DropdownMenu+SubContent/Select live-verified; ContextMenu+SubContent/HoverCard/Menubar code-verified, see note) | Steps 3-14 above (live spring timing tables + screenshots); `AnimatePresence`+`useOpenState`+`forceMount` pattern applied identically to `context-menu.tsx`/`hover-card.tsx`/`menubar.tsx` (same `surfaceVariants`/`surfaceTransition` calls, same structure as Popover/DropdownMenu - diffable in the PR) but their only real product call sites (Documents right-click, `resource-list.tsx` hover cards, dead demo2/3 Menubar) all need backend list data the CORS finding above blocks; build+lint+full vitest green confirms they compile and their own component tests (pre-existing, e.g. `data-grid-table` hover-card usage) still pass. Zero `animate-in`/`animate-out`/`zoom-in`/`slide-in` classes remain in any of the 9 files (grep swept, only comments mention the removed classes). Lightboxes 300ms in / 200ms out and menus 200ms/200ms confirmed by the timing tables above (SURFACE_SPRING vs MENU_SPRING `visualDuration`). Re-opening mid-close continues from its live scale (step 11, no jump to 0.96). |
| AC-DLA-21 | PASS | Popover/DropdownMenu/Select all carry `origin-(--radix-*-content-transform-origin)` on the inner `motion.div` (code, diffable); Dialog/AlertDialog stay centered (`x:'-50%',y:'-50%'` offset baked into every sampled transform above, e.g. `matrix(...,-300,-304.5)` throughout the whole Dialog trajectory); `navigation-menu.tsx` viewport class changed `origin-top-center` -> `origin-top` (not a real Tailwind utility before this fix) |
| AC-DLA-22 | PASS (`command.tsx`) / N/A (no live call site) | `CommandDialog` gained a `motion` prop (`false` -> `DialogContent motion={false}`, zero scale, overlay fades on a plain `--duration-fast` tween per `dialog.tsx`'s `motionEnabled` branch); **this codebase has no live keyboard-shortcut-opened `CommandDialog`** - `app/components/partials/dialogs/search/search-dialog.tsx` (the only header search surface) is a plain click-triggered `Dialog` with hardcoded demo tabs, not `cmdk`-backed, and `CommandDialog` itself has zero importers outside `command.tsx` (grepped). Flagging as a plan/reality mismatch, not a T3 gap: the AC's "the global search opener passes it" clause has no code to touch, since that opener isn't `CommandDialog`. The mechanism is built and ready for the day a real Cmd/Ctrl+K palette exists. |
| AC-DLA-23 | PASS | `header.tsx`'s two mobile `Sheet`s replaced with `Drawer` (`direction="left"`, `shouldScaleBackground={false}`, `OVERLAY_CLASS_STATIC`); steps 7/9 (live, both drawers); step 7's `[data-vaul-drawer]` reduced-motion poll = `0.001s` |
| AC-DLA-24 | PASS + follow-up filed | `demo1.css`: hover-expand rule (and everything gated on `:hover`) now sits inside `@media (hover: hover) and (pointer: fine)`; every `transition: width ...` declaration (both plain and `.sidebar-collapse`) plus the `layout-initialized` wrapper/header transitions now sit inside `@media (prefers-reduced-motion: no-preference)`; `demo1/layout.tsx`'s `setTimeout(...,1000)` replaced with a double `requestAnimationFrame`. Step 5 above live-confirms `transition: none` under reduced motion. **Frame trace**: `agent-browser` has no DevTools-Animations-panel equivalent and no CDP tracing command in this CLI version; a `performance.now()`-timestamped `requestAnimationFrame` sampler was run instead (see below) - if it had shown dropped frames the transition would have been left as-is per the plan's own instruction ("if it drops frames... leave the transition"); it did not, so no further action, and BL-SS-046 (the transform-only rewrite) stays exactly as already backlogged, not attempted here (Sorento tried and reverted it). |
| AC-DLA-25 | PASS | All 16 files deleted (`git rm`, confirmed via `existsSync` in the guard test, not just the working tree); zero remaining importers (grepped before deleting); `components/ui/deleted-motion-components.guard.test.ts` (18/18) asserts both the deletion and that no `components/ui/*` file imports `framer-motion` directly; `framer-motion` was **never a direct `package.json` dependency in this repo** (only `motion`'s own internal transitive dependency - confirmed against `node_modules/motion/package.json`) so there was nothing to `npm uninstall` from `package.json`/the lockfile's top-level deps; `npm uninstall framer-motion --package-lock-only` + `npm ci` produced a genuine no-op (`git status` on `package.json`/`package-lock.json` empty) confirming this, not skipped; `motion` stays the one animation dependency; `npm run build` green. |
| AC-DLA-26 | PASS (Dialog/Sheet/DropdownMenu/Popover/Select/mobile drawer); N/A (command palette, see AC-DLA-22) | Step-by-step timing tables above ARE the frame-by-frame proof (`agent-browser` ships no DevTools-Animations-panel equivalent, so `agent-browser eval`-driven `getComputedStyle` sampling on a `setTimeout` cadence - the same adaptation T1/T2's evidence used for their own timing claims - stands in for it); reduced-motion pass (step 4 Dialog, step 5 sidebar, step 7 mobile drawer) shows every surface cross-fading/instant with no travel or scale; the command palette has no live surface to record (AC-DLA-22 note) |

### Sidebar collapse frame sampler (AC-DLA-24)

No DevTools Animations panel is reachable through `agent-browser` (CDP-only CLI, no trace/
protocol passthrough command in this version). Ran a real `requestAnimationFrame` sampler
instead, on the Users list at 1280: 24 consecutive frames sampled from just before the
`sidebar-header`'s own collapse-toggle button fires (real `pointerdown`/`pointerup`/`click`)
through the end of the width transition, recording each frame's `performance.now()` delta AND
the sidebar's live `getBoundingClientRect().width`:

```
frame deltas (ms): 16.7, 16.6, 16.7, 16.6, 16.7, 16.7, 16.6, 16.7, 16.7, 16.6, 16.7, 16.6,
                    16.7, 16.7, 16.7, 16.6, 16.7, 16.6, 16.7, 16.7, 16.6, 16.7, 16.6, 16.8
sidebar width (px): 280, 280, 272.6, 240.2, 198.7, 169.6, 149.1, 133.6, 121.6, 112.1, 104.4,
                     98.3, 93.3, 89.3, 86.2, 83.8, 82, 80.9, 80.2, 80, 80, 80, 80, 80
```

Every delta lands in a tight 16.6-16.8ms band (a steady 60fps; the browser's own vsync jitter,
not a stall - the conventional dropped-frame threshold at 60Hz is a delta materially above
~16.7ms, e.g. 20ms+ for a skipped frame). The width trace is a clean single easing curve from
280px to the 80px collapsed rail, settled by frame 19 (~300ms, matching `--duration-slow`) with
no stutter or backtrack. No dropped frames observed; per the plan's own instruction this means
the transition is left as-is (not rewritten to transform-only) and BL-SS-046 stays a backlog
item, unchanged by this slice. `15-sidebar-collapsed-1280.png` is the settled collapsed state
(icon-only 80px rail) from this same interaction.

## Deliberately left out / follow-ups

- ContextMenu/HoverCard/Menubar live click-through evidence - blocked by the CORS-3003 gap
  documented above (all three real call sites need backend list data); code-level parity with
  Popover/DropdownMenu (identical `AnimatePresence`+`forceMount`+`surfaceVariants` shape) plus
  green build/lint/vitest is the substitute proof for this run. Re-verify live once the CORS
  allow-list is widened or this slice is re-verified from an allowed port.
- The command palette (AC-DLA-22/26) - no live `CommandDialog` call site exists in this
  codebase; `command.tsx`'s `motion={false}` support is built and unit-covered structurally
  (compiles, `CommandItem`'s existing no-press-class behaviour untouched) but has nothing to
  click. Not a T3 regression - a plan/reality mismatch worth a one-line note if `docs/reference/
  design-language.md` (T8) documents this AC.
- `docs/reference/process-lessons.md` / CLAUDE.md CORS note - recommended, not made (out of this
  slice's file scope; flagged for the reviewer/T8 instead of edited unilaterally mid-slice).

## T3 - Fix round 1 (2026-09-05)

Same worktree/branch, this time served on port **3003 from THIS worktree directly**
(`rm -rf .next && npm run build` then `npx next start -p 3003`, ownership confirmed via
`lsof -p $(lsof -ti :3003) | grep cwd`). Same shared backend on :8001 - the CORS-3003 gap from
the original run still applies (backend-driven lists render "No data available"); every check
below targets surfaces that don't need live backend data, same as the original run.

1. **BLOCKER 1 (finding 1) - search dialog position.** Header search icon -> `SearchDialog` at
   1280: `getBoundingClientRect()` on `[data-slot="dialog-content"]` = `top:135, bottom:744` in a
   900px-tall viewport - `135/900 = 15%` exactly, `bottom` well inside the viewport (fully
   visible, not clipped). `fixround1-01-search-dialog-1280.png`. At 375: the header does not
   render the search trigger at all under `mobileMode` (`{!mobileMode && <SearchDialog .../>}`,
   `header.tsx` - pre-existing, not something this fix touches) - `fixround1-02-search-dialog-
   375.png` shows the Dashboard with no search icon, confirming there is no mobile search
   surface to clip in the first place.
2. **BLOCKER 2 (finding 2) - collapsed-rail presentation.** `agent-browser`'s CDP session has no
   way to flip `(pointer: coarse)`/`(hover: none)` short of full mobile-device emulation (checked:
   none of the built-in `set device` presets - iPad Pro, Pixel 9 - toggle `pointer`/`hover` media
   features at all in this CLI version, confirmed via `matchMedia` returning `fine`/`hover` on
   every one of them). Verified instead by fetching the ACTUAL SERVED build CSS
   (`curl .../_next/static/css/f48830121753e9a7.css`) and confirming byte-for-byte that
   `.demo1.sidebar-collapse .sidebar:not(:hover) .default-logo` (and every other presentation
   rule) sits OUTSIDE any `@media (hover:...)` block, while ONLY
   `.demo1.sidebar-collapse .sidebar:hover{width:...}` is wrapped in
   `@media (hover:hover) and (pointer:fine){...}` - this is a stronger proof than an emulated
   screenshot for this specific bug class (it inspects the exact rule nesting a coarse pointer
   would evaluate against, not a rendered approximation). Live regression check with the real
   (fine) pointer: `localStorage.setItem('app_settings_layouts.demo1.sidebarCollapse','true')` +
   reload -> `fixround1-03-sidebar-collapsed-presentation-1280.png` - 80px icon-only rail, small
   logo, labels/badges hidden, exactly as the presentation rules specify.
3. **Finding 5 (BLOCKER 3) - vaul animation-duration.** 375, `set media light reduced-motion`,
   opened the sidebar drawer: `getComputedStyle([data-vaul-drawer])` = `transitionDuration:
   "0.001s"`, **`animationDuration: "0.001s"`** (previously untouched by the reduced-motion
   reset - this is the actual BLOCKER, since vaul opens via a CSS animation, not a transition).
   Same for `[data-vaul-overlay]`. `fixround1-04-mobile-drawer-reduced-motion-375.png`. Normal
   motion: `transitionDuration: "0.5s"` (vaul's own drag-release default, untouched), **`animation
   Duration: "0.3s"`** (pinned to `--duration-slow`, was vaul's un-pinned `.5s` default before this
   fix). `fixround1-05-mobile-drawer-normal-375.png`. **These two screenshots are byte-identical
   (checksummed) to each other** - both are settled-state screenshots of a fully-open drawer,
   which necessarily look the same regardless of how long the open took; the `animationDuration`
   values above are the actual proof, not the images (T3 fix round 1 finding 14 - same call as
   the original run's 07/08 pair).
4. **Finding 10 - drawer width.** At 375: `[data-vaul-drawer].getBoundingClientRect().width` =
   **275** (was `w-3/4` = 281.25px pre-fix at 375, an accidental near-match that hid the bug at
   this one width). At **700px** width (`fixround1-06-mobile-drawer-width-700.png`): width is
   still exactly **275** - pre-fix this would have been `w-3/4` = 525px, visibly wrong. Confirms
   the direction-scoped width utilities no longer out-specify the consumer's `w-[275px]`.
5. **Finding 11 - DrawerTitle.** `[data-slot="drawer-title"]` textContent = `"Navigation"` for the
   hamburger drawer and `"Apps"` for the mega-menu drawer (both read via `eval` while each was
   open) - confirms `header.tsx`'s explicit sr-only titles render (not just the primitive's
   generic fallback, which only fires when a caller supplies none).
6. **Finding 6 - NavigationMenu viewport symmetric fade.** 1280, real `mouse move` onto the "Apps"
   top-nav trigger (Radix opens on hover, not click - `mouse move` + a settle wait, not `click`):
   `[data-slot="navigation-menu-viewport"]` opens (`data-state="open"`), computed
   `animationDuration: "0.2s"` (= `--duration-base`) with `animationTimingFunction:
   "cubic-bezier(0.2, 0, 0, 1)"` (= `--ease-standard`) under normal motion -
   `fixround1-07-navigation-menu-viewport-1280.png`. Under `set media light reduced-motion`,
   re-opened: `animationDuration: "0.15s"` (the reduced-motion reset's 150ms, now reachable -
   previously this slot was outside the reduced-motion selector's reach entirely and would have
   kept its full un-reduced duration).
7. **Finding 7 - Select/Menubar symmetric fade.** `/user-management/users/new`, opened the Status
   `<Select>`: `[data-slot="select-content"]` `data-state="open"`, `transform: "none"` (no zoom -
   confirmed no scale/zoom classes remain), `animationDuration: "0.15s"` (= `--duration-fast`).
   `fixround1-08-select-status-fade-1280.png`. Menubar has no live product call site in this
   codebase (same as the original run) - covered by code review + the green build/lint/vitest
   gate below, not a live click.
8. **Finding 14 - "close a dialog, click a button immediately."** Opened `SearchDialog`, dispatched
   a real `Escape` keydown, then polled `getComputedStyle(document.body).pointerEvents` via
   `requestAnimationFrame` every frame from the moment Escape fired: **cleared at ~326ms**
   (Radix's `disableOutsidePointerEvents` lock lifts once `AnimatePresence` actually unmounts the
   dialog, i.e. once the exit spring settles) - down from the pre-fix ~390-559ms window (D16
   measurements). Then, as a practical proof rather than just a synthetic measurement: opened the
   dialog again, closed it, and **immediately** (back-to-back `agent-browser mouse move/down/up`
   CLI calls, no artificial sleep) clicked the "Filters" toolbar button underneath where the
   scrim had been - its popover opened (`aria-expanded="true"`) on the very next real click,
   confirming the click was NOT swallowed. `fixround1-09-close-dialog-click-immediately-1280.png`.
   (One CLI quirk hit here, consistent with the original run's note: `agent-browser click @ref`
   right after a DOM mutation intermittently missed - `mouse move` + `mouse down` + `mouse up` at
   a freshly-measured coordinate was reliable.)

### Console

`agent-browser console` after the full fix-round-1 pass: only the same pre-existing a11y warnings
the original run logged as out-of-scope (`Missing Description or aria-describedby` on
`DialogContent`, from `notifications-sheet.tsx` - a file this slice never touches). Zero new
errors.

### Gate (this round)

- `npx vitest run` - **191 files / 1631 tests, all green** (18 new: `lib/motion.test.ts` settle-time
  + `useOpenState` renderHook additions, `command.test.tsx`, `dialog.test.tsx`,
  `alert-dialog.test.tsx`, `sheet.test.tsx`, `drawer.test.tsx`, plus one pre-existing
  `css/design-tokens.test.ts` case updated for the new `[data-vaul-overlay]` selector + a new
  case pinning the normal-motion `--duration-slow` pin).
- `npx eslint` on every touched file - 0 errors (3 pre-existing warnings elsewhere, untouched by
  this round).
- `rm -rf .next && npm run build` - green (one real compile error surfaced and fixed along the
  way: Radix's `AlertDialogContentProps` deliberately omits `onPointerDownOutside`/
  `onInteractOutside` from `DialogContentProps` - an AlertDialog is never dismissable by an
  outside click by design, confirmed against `@radix-ui/react-alert-dialog`'s own `.d.mts`; the
  guard's `onFocusOutside` + `onCloseAutoFocus` wiring stayed, the two unsupported props were
  dropped from `alert-dialog.tsx`).

## T3 - Fix round 2 (2026-09-05)

Same worktree/branch, `agent-browser --session t3fix2` on every call (coordinator's session-isolation
request). Server restarted from THIS worktree (`rm -rf .next && npm run build` then
`npx next start -p 3003`; killed the prior fix-round-1 process first, ownership re-confirmed via
`lsof -p $(lsof -ti :3003) | grep cwd` both before the kill and after the restart). Same shared
backend :8001, same CORS-3003 gap as both prior rounds (documented above) - every check below
targets surfaces that don't need live backend data.

1. **Finding 1 - `position="top"` + `max-h-[90dvh]` overflow.** Header search icon at **1280x577**:
   `getBoundingClientRect()` on `[data-slot="dialog-content"]` = `top: 86.5, height: 458.4,
   bottom: 545.0` - inside the 577px viewport with ~32px of breathing room at the bottom (was
   `top 86.5 + height 519 = 605.8 > 577` pre-fix). `fixround2-01-search-dialog-1280x577.png`. Same
   check at **1280x900**: `top: 135, height: 609, bottom: 744` - well inside 900px (the dialog's
   natural content height never approaches the `85dvh - 2rem` cap at this taller viewport, so this
   is a regression check, not a cap-triggering one). `fixround2-02-search-dialog-1280x900.png`.
2. **Finding 2 - collapsed-rail presentation still qualified on a hover negation.** `agent-browser`
   still has no way to toggle `pointer: coarse`/`hover: none` in this CLI version (re-confirmed:
   none of the built-in device presets - iPad Pro, Pixel 9 - flip `matchMedia('(pointer: coarse)')`
   at all). Verified via the actual SERVED build CSS instead (`curl` the `_next/static/css/*.css`
   bundle containing `sidebar-collapse`): the base rules
   (`.demo1.sidebar-collapse .sidebar .default-logo{display:none}` etc.) now carry **zero** hover
   qualifier of any kind, and the ENTIRE restore-on-hover half (width-expand + all 6 presentation
   restores) sits inside the single `@media (hover:hover) and (pointer:fine){...}` block, scoped to
   `.sidebar:hover` - byte-for-byte matching the source. Live regression check with the real (fine)
   pointer: collapsed-not-hovered renders the 80px icon-only rail correctly
   (`fixround2-03-sidebar-collapsed-unconditional-1280.png`); hovering the rail still expands it to
   280px with full labels/logo restored (`fixround2-07-sidebar-hover-expand-1280.png`, `.sidebar`
   `getBoundingClientRect().width === 280`).
3. **Finding 3 - vaul normal-motion pin cascade-shadowing the reduced-motion pin.** Verified via the
   served build CSS: `[data-vaul-drawer],[data-vaul-overlay]{animation-duration:var(--duration-slow)
   !important}` is now nested INSIDE `@media (prefers-reduced-motion:no-preference){...}` (previously
   unconditional, in the same `@layer base` as the reduced-motion block's own `!important` pin, and
   later in source - so it silently won the cascade under reduced motion too, masked only by
   `--duration-slow` itself collapsing to `1ms` under reduced motion). Live re-check at 375, both
   states unchanged in OUTCOME (as expected - the fix is structural, not a value change):
   reduced motion `animationDuration: "0.001s"` (`fixround2-04-mobile-drawer-reduced-motion-375.png`),
   normal motion `animationDuration: "0.3s"` (`fixround2-05-mobile-drawer-normal-375.png`) - **these
   two screenshots are byte-identical to each other AND to the fix-round-1 pair**, for the same
   reason disclosed there: both are settled-state screenshots of a fully-open drawer, which cannot
   visually differ by duration; the `animationDuration` values are the actual proof.
4. **Finding 4 - dead `isInsideOpenDialog` export.** Deleted (zero importers, re-confirmed via grep
   before deleting). No live check applicable - code-only.
5. **Finding 5 - `guardOutsideInteraction`/`focusIsInsideFloating` test coverage.** Factored the
   duplicated closure in `dialog.tsx`/`alert-dialog.tsx`/`sheet.tsx` into
   `createOutsideInteractionGuard` (`floatingAncestry.ts`), then unit-tested directly (no browser
   needed - this is DOM/event logic, not rendering): a `CustomEvent` whose
   `detail.originalEvent.target` is inside `[data-slot="dropdown-menu-content"]` is prevented; one
   outside any floating surface, well past the mount-grace window, is NOT prevented; one inside the
   window (both a static "just mounted" case and a `performance.now()`-spied "301ms later" case) IS
   prevented; plus two edge cases (`detail.originalEvent` absent, falls back to `event.target`;
   `mountedAtRef.current === 0` - content already unmounted - never triggers the grace window).
   `npx vitest run components/common/floatingAncestry.test.ts` - 10/10 green.
6. **Finding 6 - missing `aria-label` on the mega-menu drawer trigger.** Added
   `aria-label="Open apps menu"` (its sibling, the hamburger trigger, already carries
   `aria-label="Open navigation"`). Live-verified at 375: the button's accessible name now reads
   "Open apps menu" in the `agent-browser snapshot` output, and clicking it still opens the
   mega-menu drawer with the correct `DrawerTitle` ("Apps") - `fixround2-06-mega-menu-aria-label-
   375.png`. **Pre-existing, unrelated layout note** (not caused by this diff, not in scope for this
   round): at 375px the `ActivityTriggers` icon group (Uploads/Imports/Jobs/Downloads) and the
   hamburger+apps-menu icon group visually OVERLAP by ~20px (`getBoundingClientRect()` confirmed
   `[132.6,168.6]` vs `[147.5,181.5]` on the x-axis at the same y) - a coordinate-based click near
   that boundary can land on the wrong button (hit the "Uploads" activity Sheet instead of the Apps
   drawer trigger twice during this verification, each time leaving a stuck
   `document.body{pointer-events:none}` lock until its own Close button was clicked - the SAME
   modal-lock mechanism this whole slice is about, just triggered by a misdirected click rather
   than a slow exit spring). Worth a follow-up ticket for the header's icon-group layout at narrow
   widths; out of scope for T3.

### Console

`agent-browser console`/`errors` checked after every navigation and after resolving the one stuck
Sheet noted above. Zero NEW console errors introduced by this round's changes; the same pre-existing
`Missing Description` a11y warnings (T7 territory, unrelated to this slice) recurred identically.

### Gate (this round)

- `npx vitest run` - **192 files / 1642 tests, all green** (10 new in `floatingAncestry.test.ts`,
  including a fix mid-round: the "grace window elapsed" case needed `vi.spyOn(performance, 'now')`
  rather than `vi.useFakeTimers()` + `vi.advanceTimersByTime` - this vitest version's fake timers do
  not fake `performance.now()` by default).
- `npx eslint` on every touched file - 0 errors (same 3 pre-existing warnings elsewhere).
- `rm -rf .next && npm run build` - green, no compile errors this round.
