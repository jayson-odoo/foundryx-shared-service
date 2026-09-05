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
