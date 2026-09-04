# T1 Tokens, CSS, preferences - evidence run log

Slice: `sprint-4/23-T1-tokens` (branched from `sprint-4/23-design-language-alignment`).
Contract: `documentation/plans/sprint-4/23-design-language-alignment-acceptance-criteria.md`
AC-DLA-01 .. AC-DLA-08. Plan section 3.1.

## Environment

- Backend: `service_backend/.venv/bin/python -m uvicorn app.main:app --port 8001` (this
  worktree's venv, symlinked). Health-checked `200` before every run.
- Frontend: `rm -rf .next && npm run build` (green) then `npx next start -p 3002` (this
  worktree's checkout; port 3001 was unowned/free but 3002 was used to stay clear of any
  sibling lane). Login `demo@example.com` / `demo1234`, tenant `default`.
- Browser: `agent-browser` CLI only (no Playwright, per D15). Navigation from `/` by sidebar
  clicks; the mobile drawer (< lg) opened via the header hamburger ("Open navigation").
- Dark mode: no dedicated design-system dark-mode toggle exists yet (BL-SS-047, backlog per
  D-table); the existing Metronic "Dark Mode" switch in the user-menu (top-right avatar ->
  "Dark Mode") toggles the `.dark` class on `<html>` and was used for every `-dark` shot.

## Mid-run environment incident (documented, not a T1 regression)

Partway through the browser-evidence pass, the coordinator reported the SHARED
`service_frontend/node_modules` (symlinked into this worktree, per repo convention) was
mid-repair in the main checkout: it was missing `@codemirror/*` (breaking `npm run build` on
`components/platform/autocount/sql-editor.tsx`, pre-existing and unrelated to T1) and briefly
lost `react`/`tailwindcss`/`eslint` while `npm ci` ran there. This worktree's own
`package.json`/lockfile were never touched and no `npm install` was run from here. Effects and
recovery:
- The prod build failed once (`@codemirror/*` module-not-found) before the repair - handled by
  falling back to `npm run dev` on :3002 for the FIRST screenshot pass so the T1 CSS/token
  changes could still be verified live without mutating shared state.
- Mid-repair, `npm run dev` briefly 500'd (`Cannot find module .../react/jsx-runtime.js`) and a
  stray `.node_modules-sDxXOv3A` symlink (untracked, 0 bytes, same target as `node_modules`)
  appeared inside this worktree and made `vitest run` pick up `zod`'s own internal test suite
  (`.node_modules-*/zod/src/v4/**/*.test.ts`, ~190 extra "test files" that failed to resolve).
  Removed the stray symlink (`rm -f service_frontend/.node_modules-sDxXOv3A` - untracked, not
  gitignored, purely local to this worktree); `vitest run` returned to 172 files / 1465 tests
  green.
- After the shared `node_modules` stabilized (`@codemirror/*` present), re-ran
  `npx eslint <touched files> css/design-tokens.test.ts` (clean), `npx vitest run` (172 files,
  1465 tests, all green), `rm -rf .next && npm run build` (green), and served the REAL prod
  build via `npx next start -p 3002`.
- The Users list (light AND dark, 1280) was re-captured against the prod build and is
  pixel-identical to the interim dev-server capture (same source CSS/components, no dev-only
  artifact) - `01-users-list-1280-{light,dark}.png` are the prod-build shots. The remaining
  1280 surfaces (`02`-`06`) were captured against `next dev` during the interim window before
  the prod build was available; all 375-width shots and the `-light` variants of `04`/`05`/`06`
  were captured AFTER the repair, directly against the prod build on :3002. Given the parity
  proven on `01`, and that no source file changed between the two passes, the interim dev-mode
  shots are treated as valid evidence of the same build.

## Surfaces captured (6 x light/dark x 375/1280 = 24 screenshots)

| # | Surface | 1280 light | 1280 dark | 375 light | 375 dark |
|---|---|---|---|---|---|
| 01 | Users list | done | done | done | done |
| 02 | User record (Admin User) | done | done | done | done |
| 03 | Settings > General | done | done | done | done |
| 04 | Open sheet (header bell -> Notifications, 375 / -> Chat, 1280) | done | done | done | done |
| 05 | Open dialog (row "..." -> Trash -> "Move to trash?" AlertDialog, cancelled every time - no user was actually trashed) | done | done | done | done |
| 06 | Open dropdown (row "..." action menu) | done | done | done | done |

All screenshots named `NN-<surface>-<width>-<light|dark>.png` in this directory.

## Console check

`agent-browser console` after every navigation showed no page errors beyond dev-mode noise
(Fast Refresh, i18next init, React DevTools banner) and two PRE-EXISTING issues unrelated to
T1 (not caused by this slice's diff, not fixed here - out of scope, noted for the reviewer):
- `DialogContent requires a DialogTitle for the component to be accessible for screen reader
  users` - fired on the Notifications sheet (`partials/topbar/notifications-sheet.tsx`, a file
  T1 never touches). Likely T7's aria-label/a11y sweep territory.
- A benign jsdom-unrelated browser warning, "Skipping auto-scroll behavior due to
  `position: sticky` or `position: fixed`" - harmless scroll-into-view diagnostic, not an error.

## Known pre-existing bug surfaced by this evidence pass (NOT a T1 regression, NOT fixed here)

`components/ui/badge.tsx`'s `success`/`warning`/`info` `appearance="light"` compound variants
set **both** `dark:bg-[var(--color-X-soft,...)]` and `dark:text-[var(--color-X-soft,...)]` to
the SAME token - in dark mode a status pill background and its text/dot resolve to the
identical colour, so `StatusBadge` renders as a solid coloured block with invisible text (see
`01-users-list-1280-dark.png` - "Active" pills show a green block, no visible text). This line
predates this session (not part of my diff - I only touched `badgeButtonVariants`'s
`transition-all` -> `transition-opacity`, a different `cva` block) and is squarely T2's badge.tsx
rebuild territory (AC-DLA-11 rewrites `appearance`). Flagging here since it is highly visible
in the dark-mode evidence and should not be mistaken for a T1 regression.

## AC verdicts (T1)

| AC | Verdict | Proof |
|---|---|---|
| AC-DLA-01 | PASS | `css/design-tokens.test.ts` "AC-DLA-01 motion tokens" (6 assertions, computed-style via injected stylesheet); `css/config.reui.css` `:root`/`.dark`/`@theme` |
| AC-DLA-02 | PASS | `css/design-tokens.test.ts` "AC-DLA-02 material tokens"; `header.tsx`/`sidebar.tsx` class strings; `01-users-list-1280-{light,dark}.png` show the translucent header/sidebar |
| AC-DLA-03 | PASS | `css/design-tokens.test.ts` "AC-DLA-03 named z-scale" (values, ordering, shell references, zero `z-[N]` sweep, banner-offset mechanism); `header.tsx`/`sidebar.tsx`/`impersonation-banner.tsx` |
| AC-DLA-04 | PASS | `css/design-tokens.test.ts` "AC-DLA-04 type scale..." (7 steps x tracking/leading, optical sizing, font vars, 4 Title components); `card.tsx`/`dialog.tsx`/`alert-dialog.tsx`/`sheet.tsx` |
| AC-DLA-05 | PASS | `css/design-tokens.test.ts` "AC-DLA-05 accessibility preference blocks" (8 assertions); `css/styles.css` reduced-motion/-transparency/contrast-more blocks incl. M3 demo1/vaul/`transition-[` additions |
| AC-DLA-06 | PASS | `css/design-tokens.test.ts` "AC-DLA-06 literal-sweep" (5 assertions: cubic-bezier, transition-all, duration-N, ease-in/-out, text-[Npx]); manual re-measure confirmed 0 remaining outside the two named allowlist files (`input-otp.tsx` OTP caret, `github-button.tsx` T3-deleted decor) and the demo2-10 exemption |
| AC-DLA-07 | PASS | `css/design-tokens.test.ts` "AC-DLA-07 semantic ink contrast" (contrast >= 4.5:1, both themes); required darkening `--success-foreground`/`--info-foreground`/`--warning-foreground` from white to `--foundryx-black` in `css/foundryx-tokens.css` - was 3.49/3.83/2.17:1 against white, now 6.01/5.49/9.68:1 against black (see file comment) |
| AC-DLA-08 | PASS | 24 screenshots in this directory, verdict table above |

## Deliberately left out / follow-ups

- Sorento's `@theme inline` colour-token contrast test also asserts `text-mono` renders as ink
  ON `--background`/`--card` in BOTH directions and a dark-surface-ramp 3-step-distinctness
  check; this repo's `--background`/`--card`/`--popover` are currently the SAME value
  (`--foundryx-light` in both `:root` layers per `foundryx-tokens.css`) - not a T1 regression
  (pre-existing, brand tokens), but the Sorento-style "3 distinct surface steps" assertion would
  fail today and was NOT ported into `design-tokens.test.ts` for that reason. Flagging as a
  candidate for `docs/reference/design-language.md` (T8) or a backlog row - not blocking T1.
- The dark-mode `StatusBadge` contrast bug above is T2 territory (badge.tsx rebuild), not fixed
  here.
- No dedicated in-app "design system" dark-mode toggle exists (used the Metronic user-menu
  switch, which flips the SAME `.dark` class); BL-SS-047 tracks adding one.

## Fix round 1 (10 `/code-review` findings, all applied - see the test report's
"T1 - Fix round 1" section for the full per-finding table)

Additional screenshots, `fixround1-NN-*.png` in this directory:

- `fixround1-01-banner-expanded-{1280,375}.png` / `fixround1-02-banner-collapsed-{1280,375}.png`
  - a REAL impersonation session (Admin User impersonating KT Demo via the Users list row
    action), banner expanded and collapsed, both widths - the page content is never covered
    under the header in any of the 4 states (finding 1). The collapsed shot at 1280 also shows
    the pill sitting ABOVE the header icons, proving `--z-banner` now outranks the header
    (finding 2).
- `fixround1-03-alert-warning-light-appearance-dark.png` - alert.tsx's actual
  `appearance="light"` warning classes (icon-on-`-soft`) injected onto a live page in dark
  mode; the triangle icon is clearly legible on the amber-tinted background (finding 3 - was
  1.13:1/near-invisible with the old `-foreground`-on-`-soft` pairing).
- `fixround1-04-badge-default-appearance-light.png` - badge.tsx's actual default
  (non-"light") success/info/warning classes injected in light mode; all three read cleanly
  (finding 3 - confirms the badge default pairing needed no code change, only the token fix).
- `fixround1-05-megamenu-reduced-motion.png` - the header mega-menu opened with
  `prefers-reduced-motion: reduce` forced on (`agent-browser set media light reduced-motion`,
  confirmed via `matchMedia(...).matches === true` and
  `getComputedStyle(html).getPropertyValue('--duration-fast') === '1ms'`) - opens instantly,
  fully painted, no console errors (finding 4).
- `fixround1-06-mobile-nav-sheet-reduced-motion.png` - the mobile nav drawer (currently a
  `Sheet`, NOT yet the vaul drawer - `components/ui/drawer.tsx` has zero importers until T3
  wires it in per plan D10/D13; `z-(--z-modal)` was still applied to `drawer.tsx` in this pass
  so the file is ready when T3 mounts it) at 375, same reduced-motion state - opens cleanly, no
  console errors.

Injected-markup screenshots (`fixround1-03`/`fixround1-04`) render the component's OWN class
strings copied verbatim from `alert.tsx`/`badge.tsx` onto a `document.body`-appended element via
`agent-browser eval` - not a mockup - because no reachable page in this build currently renders
a warning/success/info Alert or a default-appearance Badge without deeper, unrelated app setup
(AutoCount company/entity data). The CSS is real; only the trigger path is synthetic.
