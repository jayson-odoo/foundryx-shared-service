# T6 evidence - shells (loading, error, not-found, sheets/drawers, sidebar feel)

Stack: this worktree's own backend `:8003` (already running, untouched - T6 is
frontend-only) + frontend prod build `:3002`. `agent-browser --session t6` only,
real clicks from `/`, login `demo@example.com` / `demo1234`.

## Run log

1. Confirmed :8003 healthy (`curl /docs` -> 200); killed the stale `:3002`
   next-server owned by this worktree, `rm -rf .next && npm run build`,
   `nohup npx next start -p 3002 &`.
2. Logged in at 1280, real sidebar clicks (`User Management` -> `Users`).
3. **AC-DLA-72** - pointer-down frames: `agent-browser mouse move/down/up`
   (a genuine held mouse button, not a synthetic event dispatch, so the
   browser's real `:active` CSS state is captured) on the "User Management"
   root trigger and the "Users" child link, at 1280 and again at 375 (mobile
   drawer opened via the hamburger). `06-user-record-one-lit-item-1280.png`
   +a JS query for `[data-slot="accordion-menu-item"][data-selected="true"]`
   confirms exactly one lit item on a user record page.
4. **AC-DLA-50** - forced a render error via a TEMPORARY, reverted-before-
   commit change to `user-management/users/page.tsx` (`throw` gated on
   `?__forceError=1`, `git diff` confirms zero net change afterward):
   `07` shows the sidebar/header/footer intact with "Something went wrong" +
   Reset in the content pane; `history.replaceState` cleared the throw
   condition, Reset (`09`) recovered the real Users list with no full
   reload (URL stayed a client transition). Unknown record id: wired
   `user-form-view.tsx` to call Next's real `notFound()` (previously an
   inline "User not found." paragraph, never routed through Next's 404
   boundary) - `10` shows `/user-management/users/<bogus-uuid>` rendering
   `not-found.tsx` inside the shell.
5. **AC-DLA-52/55** - device-emulated 375 (`agent-browser set device
   "iPhone 14"`): notifications sheet (`13`), chat sheet (`14`), jobs
   drawer (`15`), the omnichannel inbox shell + conversation drawer
   (`16`/`17`) all show their BOTTOM content (action buttons / composer)
   inside the viewport, not clipped. Toast top-center confirmed at both
   375 (`18`, triggered via an out-of-range Settings > General save) and
   1280 (`19`).
6. Cleaned up: reverted the temporary forced-throw edit (`git diff` on
   `page.tsx` is empty), closed the browser session.

## Disclosed limitations (not silently skipped)

- **AC-DLA-50 "no vertical shift" (loading Users then landed)**: NOT
  captured as a live frame-diff. Root cause chased in depth: Next.js's
  `loading.tsx` Suspense boundary is driven by the ROUTE SEGMENT's own
  code-split chunk fetch + first synchronous render, not by the page's
  OWN internal `useResourceList` data fetch (a plain client `useEffect`,
  not something React can suspend on) - so delaying the `/users` API call
  (via an `--init-script`-installed `fetch` proxy) never extended the
  skeleton's on-screen time; the chunk itself loads too fast locally
  (cached after first visit) for the CLI's own process-spawn latency to
  catch the transition. `agent-browser` has no exposed network-conditions
  API to throttle the underlying chunk *download* (only response mocking).
  Verified instead by construction: `components/platform/skeletons/
  list-page-skeleton.tsx` and the real `PageHeader`+title both render
  inside the identical `Container width="fluid"` wrapper with matching
  spacing utilities (reviewed side-by-side in source), and
  `skeletons.test.tsx` pins the skeleton's 60px row height + structural
  shape. A live pixel-diff would need CDP-level chunk throttling, which is
  out of `agent-browser`'s exposed surface and out of scope for a
  throwaway script (no Playwright).
- **AC-DLA-52 "focusing an input does not zoom"**: `agent-browser set
  device "iPhone 14"` sets VIEWPORT DIMENSIONS only - verified live
  (`window.matchMedia('(pointer: coarse)').matches` -> `false`,
  `navigator.maxTouchPoints` -> `0` even under the device emulation), so
  the `pointer-coarse:` Tailwind variant never activates in this tool and
  a live "no zoom on focus" demonstration isn't reachable. The CSS itself
  (`pointer-coarse:text-base` on every `Input` density variant) is
  verified statically by `lib/dvh-pointer-coarse.inventory.test.ts` and is
  the CSS spec's standard mechanism (Safari suppresses its <16px
  auto-zoom whenever the computed font-size is >=16px, independent of how
  that size was reached) - not fabricated evidence, but not a live-browser
  demonstration either, disclosed rather than silently claimed.
- Chat sheet needed NO dvh code change (already sizes via `flex-1` off an
  inset-based container, no raw `vh`) - `03`/`13`/`14` show it fitting
  correctly as a baseline confirmation, not a fix demonstration.

## Live-caught side effect (disclosed, fixed in the same slice)

While forcing the AC-DLA-50 error/not-found evidence, found that NOTHING
in the repo actually called Next's `notFound()` - every one of ~17
`use-XForm` hooks renders its own ad-hoc "X not found." paragraph instead
(pre-existing pattern, not a T6 regression). Wiring `user-form-view.tsx`
(the Users record page, matching AC-DLA-72's own "Users > a user record"
example) is the ONE conversion done in this slice; the other 16 forms
keep their inline pattern (already inside the shell trivially, just not
via the new shared `not-found.tsx`) - tracked as a backlog sweep, not
silently left inconsistent.

## T6 - Fix round 1

Stack unchanged: this worktree's own backend `:8003` (untouched - fix round
1 is frontend-only), frontend prod build `:3002` (`pkill` only the pid whose
`lsof cwd` is this worktree, `rm -rf .next && npm run build`,
`nohup npx next start -p 3002 &`). `agent-browser --session t6fix1`, real
clicks from `/`, login `demo@example.com` / `demo1234`.

Items 1-4 (commits `3bb9700`/`427a112`/`6e8bb39`/`296148d`, done by the
previous coder) are covered by the "T6 - Shells" section above; items 5/7-11
are source/CSS/test-only fixes verified by the updated Vitest suites (no new
screenshots needed per-item - the two captures below are the round's own
evidence requirement, item 12).

### Run log

1. Confirmed `:8003` healthy, rebuilt and restarted `:3002` from this
   worktree (`lsof -p <pid> | grep cwd` confirmed ownership before kill).
2. **`fixround1-02-settings-general-skeleton-1280.png`** - logged in at
   1280 (real form fill + submit), then from the Dashboard: real click to
   expand the "Settings" sidebar section, immediately followed by a real
   click on "General" with the screenshot fired back-to-back (no
   intervening `wait`) to win the race against the client-side route
   transition. Caught the neutral, generic `PageSkeleton` (item 1's fix -
   two title bars + one card with header + a few content bars) rendering
   in the content pane while the sidebar/header chrome stays mounted -
   this is the group-root `loading.tsx` fallback, not a list/record-shaped
   skeleton, matching item 1's ruling.
3. Attempted `fixround1-01-press-375-crop.png` (a held root sidebar item at
   375, cropped) and could not obtain it - see "Disclosed limitation"
   below. Kept `01-sidebar-root-pointerdown-1280.png` /
   `02-sidebar-child-pointerdown-1280.png` (already in this folder, from
   the original T6 run) as the press proof per the fix brief's own
   fallback instruction.
4. Verified no console errors on `/settings/general` after the race
   capture (`agent-browser errors`), closed the session.

### Disclosed limitation - could not hold a pointer for the 375 press crop

`agent-browser mouse move`/`mouse down`/`mouse up` (the same primitives
`01`/`02` were captured with, on this same build, at 1280) produced NO
observable press effect in this session, at EITHER 375 or 1280, with or
without `set device` touch emulation:

- `document.querySelector(':active')` returned `null` immediately after
  `mouse down` at a coordinate independently confirmed correct via
  `document.elementFromPoint` (the button/link IS the top hit-test result).
- More surprising: a full `mouse down` + `mouse up` pair at that same
  coordinate never fired a `click` at all - an accordion trigger's
  `data-state` stayed `"closed"` through the whole sequence (checked
  immediately after `down`, again after `up`, and again after an extra
  500ms) where a real user press-release unquestionably toggles it. A
  plain JS `.click()` on the same element (via `eval`) DOES toggle it
  instantly - consistent with the pre-existing house lesson in `CLAUDE.md`
  ("a browser-automation click helper on a freshly-mounted React button
  sometimes doesn't fire the onClick... a native `.click()` via a JS-eval
  bridge does; not a product bug") but here extended to raw CDP mouse
  down/up as well, not just the `click` command.
- This is an `agent-browser`/Chrome-for-Testing (152.0.7977.42) environment
  quirk, not a product regression: item 5's fix is CSS-only (Tailwind
  classes on `SheetContent`), unrelated to sidebar `:active` styling, and
  the sidebar's own `PRESSED_CLASS` code is untouched by fix round 1.
  Per the brief's own fallback instruction, this is disclosed rather than
  faked, and `01`/`02` (1280, from the original T6 run, captured when this
  same technique DID work) remain the press proof on file.
