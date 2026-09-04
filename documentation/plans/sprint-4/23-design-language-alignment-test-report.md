# 23 - Design language alignment - Test Execution Report

Keyed to `23-design-language-alignment-acceptance-criteria.md`. One section per slice,
appended as each slice completes. Format per `AI_Agent_Orchestration_Guide.md` section 6.

---

## T1 - Tokens, CSS, preferences

**Branch:** `sprint-4/23-T1-tokens` (off `sprint-4/23-design-language-alignment`).
**Evidence:** `documentation/plans/sprint-4/23-evidence/T1/` (`README.md` run log + 24
screenshots).
**Environment:** backend `service_backend` (this worktree's venv) on :8001; frontend
`rm -rf .next && npm run build` (green) served via `npx next start -p 3002` (this worktree);
`agent-browser` CLI only, real sidebar clicks from `/`, `demo@example.com`/`demo1234`.

### AC-DLA-01 - motion tokens `[FE][T]`

**User story:** As a maintainer, I want one curve and three durations defined once so every
component transition reads the same.
**Scenario:** Given `css/config.reui.css`, when I resolve `--ease-standard`/`--duration-fast`/
`-base`/`-slow` via computed style in `:root` and `.dark`, and `--default-transition-*` in
`@theme`, then all six resolve to the documented values.
**Steps:** `npx vitest run css/design-tokens.test.ts -t "AC-DLA-01"`.
**Expected:** `--ease-standard` matches `cubic-bezier(...)`; durations 150/200/300ms in both
themes; `--default-transition-timing-function`/`-duration` reference the same tokens.
**Actual:** PASS - 6/6 assertions green.
**Remarks:** None.

### AC-DLA-02 - material tokens `[FE][T]`

**Scenario:** Given the header and sidebar, when they render, then they use `material-regular`/
`material-thick` (not `bg-background`) with the documented opacity steps per theme.
**Steps:** `npx vitest run css/design-tokens.test.ts -t "AC-DLA-02"`; browser: Users list,
Settings, a record - header/sidebar visibly translucent over scrolled content
(`23-evidence/T1/01-users-list-1280-{light,dark}.png`).
**Expected:** 72%/76% regular, 88%/90% thick, 24px blur, edge + scrim present; utilities in
`styles.css`; header/sidebar class strings updated.
**Actual:** PASS.
**Remarks:** None.

### AC-DLA-03 - named z-scale `[FE][T]`

**Scenario:** Given the shell, when the impersonation banner is active, then it sits above the
header/sidebar via `--z-banner` and PUSHES them down (`top-[var(--impersonation-banner-height,
0px)]`) rather than covering them; given the whole `app/**`/`components/**` tree, then zero
`z-[N]` literals remain.
**Steps:** `npx vitest run css/design-tokens.test.ts -t "AC-DLA-03"`.
**Expected:** 6 named steps at the documented integers, strictly ordered; header/sidebar/banner
reference `z-(--z-*)`; offset mechanism present; zero `z-[N]` under `app/**`/`components/**`.
**Actual:** PASS - 5 sub-suites green, including the whole-tree `z-[N]` sweep (the one baseline
hit, `navigation-menu.tsx`'s local stacking nudge, moved to an inline `style={{zIndex:1}}`
since it is not one of the shared named steps).
**Remarks:** `components/impersonation/impersonation-banner.tsx` was refactored from a
`document.body.style.paddingTop` push (which never actually offset the two FIXED header/sidebar
layers - they would have stacked at the same `top:0` as the banner) to setting
`--impersonation-banner-height` on `document.documentElement`, consumed by both.

### AC-DLA-04 - type scale, optical sizing, title leading `[FE][T]`

**Scenario:** Given the `@theme` type scale, when each step is resolved, then tracking/leading
match the spec; given `body`, then `font-optical-sizing: auto`; given `CardTitle`/`DialogTitle`/
`AlertDialogTitle`/`SheetTitle`, then each carries `leading-tight tracking-normal`.
**Steps:** `npx vitest run css/design-tokens.test.ts -t "AC-DLA-04"`; browser: any card/dialog
title (Settings > General "Default currency", the trash confirm dialog title).
**Expected:** 2xl/xl/lg/base/xs/2xs/2sm tracking+leading exact; `--font-sans`/`--font-heading`
unchanged (Inter/Poppins); 4/4 Title components updated.
**Actual:** PASS.
**Remarks:** None.

### AC-DLA-05 - accessibility preference blocks `[FE][T]`

**Scenario:** Given `prefers-reduced-motion`/`-transparency`/`prefers-contrast: more`, when each
media block is inspected, then it carries the documented rules (tw-animate vars zeroed,
dialog/sheet-content excluded, pulse/bounce stopped and spin left alone, the M3 demo1/vaul/
`transition-[` additions, solid materials + raised scrim, firmer borders in both themes).
**Steps:** `npx vitest run css/design-tokens.test.ts -t "AC-DLA-05"`.
**Expected:** 8 assertions green.
**Actual:** PASS.
**Remarks:** `sheet.tsx`'s `SheetContent` gained `data-slot="sheet-content"` (previously
un-tagged), needed for the reduced-motion exclusion selector to have something to exclude.

### AC-DLA-06 - literal sweep `[FE][T]`

**Scenario:** Given `app/**`, `components/**`, `css/**`, when scanned for raw `cubic-bezier(`,
`transition-all`, literal `duration-<N>`, `ease-in`/`ease-in-out`, and `text-[Npx]`, then none
remain outside the documented allowlists.
**Steps:** `npx vitest run css/design-tokens.test.ts -t "AC-DLA-06"`; manual re-measure via
`grep` before/after each fix.
**Expected:** zero everywhere except `config.reui.css` (cubic-bezier), `input-otp.tsx` +
`github-button.tsx` (duration-N), and the `demo2`-`demo10` layouts (`text-[Npx]`).
**Actual:** PASS - re-measured baselines on this tree (drifted from the UAC's `e58ae9b` numbers,
as flagged in the brief): `transition-all` 8 FILES / 12 total occurrences (matches the brief's
"8 transition-all now, not 12" re-measure note, read as file count), literal `duration-<N>` 18
(exact UAC match), `ease-in`/`ease-in-out` 4 raw hits (all converted to `ease-(--ease-standard)`
rather than hand-picking which were "entering" - simpler and strictly stronger than the AC's
wording), `text-[Npx]` 80 raw hits across 36 files, 66 hits / 30 files outside the demo2-10
exemption fixed (the remaining 14 hits / 6 files are the demo2-10 exemption itself) - all map
cleanly to `text-2xs` (9/10/11px) or `text-2sm` (13px), only two distinct target steps were
needed. `cubic-bezier(` outside `config.reui.css`: 1 (switch.tsx:86, fixed).
**Remarks:** `app/(protected)/account/home/settings-enterprise/components/company-documents.tsx`
(an SVG upload-progress ring) was fixed in place rather than allowlisted, even though it is
slated for deletion with the rest of `account/**` in T7 - the fix was the same one-liner the
plan already specified for it, cheaper than an allowlist entry.

### AC-DLA-07 - semantic ink contrast `[FE][T]`

**Scenario:** Given `--mono`/`--success`/`--info`/`--warning` and their `-foreground` pairs in
both themes, when contrast is computed, then every pair clears WCAG AA 4.5:1.
**Steps:** `npx vitest run css/design-tokens.test.ts -t "AC-DLA-07"`.
**Expected:** all 4 pairs >= 4.5:1, both themes.
**Actual:** PASS, but only after a real fix, not just a passing test written around a bug: on
first run `--success`/`--info`/`--warning` against their (white) foreground measured
3.49:1 / 3.83:1 / 2.17:1 - all fails. `--foundryx-success`/`-info`/`-warning` are the SAME hex in
light and dark (Tokens Studio export), and all three clear 4.5:1 against BLACK (6.01/5.49/9.68),
so `css/foundryx-tokens.css` now sets `--success-foreground`/`--info-foreground`/
`--warning-foreground` to `--foundryx-black` (a true constant, not `--foundryx-dark`, which
itself flips under `.dark`). `--mono` was already compliant.
**Remarks:** **Flagging for reviewer/design sign-off**: this changes the ink colour on any solid
success/info/warning fill (e.g. a filled `Badge`/`Button` in that tone) from white to black
text. `StatusBadge` (the highest-traffic consumer) uses `appearance="light"` (tinted background,
tinted text) and is UNAFFECTED - the affected consumers are anything using the SOLID
`appearance="default"` badge/button variant in these tones, which a `grep` at the time of this
report found no live call sites for outside `components/ui/badge.tsx` itself. Not reverted
because AC-DLA-07 is an explicit, non-optional WCAG gate for this slice.

### AC-DLA-08 - browser evidence `[FE][E2E]`

**Scenario:** Light and dark screenshots of the Users list, a user record, Settings > General,
an open dialog, an open sheet, and an open dropdown, at 375 and 1280.
**Steps:** `agent-browser`, real sidebar clicks from `/`, both widths, both themes (Metronic
user-menu "Dark Mode" switch). See `23-evidence/T1/README.md` for the full run log.
**Expected:** 24 screenshots, no clipped controls, no console errors attributable to this
slice's diff.
**Actual:** PASS - 24/24 captured. Console clean of this-slice-caused errors; two PRE-EXISTING
issues surfaced and documented (not fixed, out of scope): (1) a dark-mode `StatusBadge` bug in
`badge.tsx`'s `appearance="light"` compound variants (bg and text resolve to the SAME
`-soft` token in dark mode - T2 badge.tsx rebuild territory); (2) a `DialogContent` missing
`DialogTitle` a11y warning on the pre-existing Notifications sheet (T7 a11y-sweep territory).
**Remarks:** A shared-`node_modules` repair ran concurrently in the main checkout mid-pass
(documented in full in `23-evidence/T1/README.md`) - briefly broke the frontend build/dev
server and polluted `vitest run`'s file discovery via a stray untracked symlink in this
worktree; both resolved without touching the shared `node_modules` from this session, and the
full gate (lint/test/build) was re-run clean afterward.

### Definition of Done checklist (T1)

1. Every AC-DLA-01..08 verified above (`[T]` tests + the `[E2E]` agent-browser run). PASS.
2. `npm run lint` (touched files), `npm test` (`npx vitest run`), `npm run build` all green -
   confirmed AFTER the shared-node_modules incident resolved (172 files / 1465 tests; build
   clean). PASS.
3. `rm -rf .next && npm run build` before the final live check; port ownership checked
   (`lsof -ti :3001`/`:3002`; served on :3002, backend confirmed healthy on :8001 before use).
   PASS.
4. No mock left behind (T1 has no service-trio slice - N/A). No backfill needed (CSS/token-only,
   no new columns). No new permission (N/A). Verified from the user's perspective at 375 AND
   1280, both themes, on the real prod build.
5. One deliberate, reviewer-facing colour change (AC-DLA-07's success/info/warning foreground)
   flagged above, not silently absorbed.

**Verdict: T1 DONE.** 8/8 AC-DLA ids PASS. Zero DEFERRED, zero FAIL.

---

## T1 - Fix round 1

`/code-review` on the DONE-verdict T1 diff above returned 10 confirmed findings, applied as
written on the same branch (`sprint-4/23-T1-tokens`, same worktree). All rulings are
decisions, not proposals - findings 3-4-6-7-9 uncovered further pre-existing behaviour (a
badge/alert contrast regression, a losing-cascade bug, duplicated media queries) that the
rulings' exact wording resolved; nothing here reopens a PASS verdict above, this section
documents the additional work and its evidence.

| # | Finding | Fix | Proof |
|---|---|---|---|
| 1 | Banner offset covered the page title; `BANNER_HEIGHT=40` undercounted the rendered ~45px | `impersonation-banner.tsx` now measures itself with a `ResizeObserver` and publishes `--shell-top-offset` (not a constant); header/sidebar `top` read it directly; `demo1.css`'s two `.wrapper` padding-top rules and the settings-sidebar sticky nav read `calc(var(--header-height) + var(--shell-top-offset, 0px))` - the header alone dropping while the wrapper stayed at a bare `--header-height` is what hid the title | `fixround1-01-banner-expanded-{1280,375}.png`, `fixround1-02-banner-collapsed-{1280,375}.png` - real impersonation session (KT Demo), title never covered in any of the 4 states; `css/design-tokens.test.ts` "carries --shell-top-offset..." + "offsets the header and sidebar..." (asserts `ResizeObserver` present, `BANNER_HEIGHT` constant gone) |
| 2 | Banner could be buried under an open dialog/sheet | `--z-banner: 30` -> `60` (above `--z-modal: 50`) in `config.reui.css`, comment states the rationale (operator must always reach Exit); z-scale test reorders to `header < sidebar < modal < banner` | `css/design-tokens.test.ts` "AC-DLA-03 named z-scale" (z-scale values + ordering); `fixround1-02-banner-collapsed-1280.png` shows the collapsed pill sitting on top of the header icons (z-banner over z-header) |
| 3 | `--success-foreground` etc flipped to black system-wide (fix round 1's starting point) failed Sorento's double constraint and broke two OTHER pairings that had been fine | Reverted the foreground flip; instead `--success`/`--info` now resolve to `--foundryx-success-active`/`-info-active` (existing per-theme primitives, untouched) with `--success-foreground`/`-info-foreground` = white (light) / black (dark, new `.dark` override); `--warning` resolves to `--foundryx-warning-accent` (the one hue where `-active` still fails vs white in light mode, matching the ruling's anticipated fallback) with the same white/black foreground split. `alert.tsx`'s 3 `appearance="light"` icon colours moved from `-foreground` (white/black - a fill-ink colour, unreadable at 1.13:1 on the pale `-soft` tint, a PRE-EXISTING bug this surfaced) to `-accent` directly. `badge.tsx`'s default `-accent`+`-foreground` pairing needed NO change - it already passes with the new foreground values. | `css/design-tokens.test.ts` "AC-DLA-07 semantic ink contrast" (33 assertions: constraint a foreground-on-ink, constraint b ink-on-background, alert accent-on-soft, badge accent+foreground, all both themes); measured ratios: success light 5.05:1 / dark 8.23:1 (fg) and 7.70:1 (bg-ink), info light 5.56:1 / dark 7.56:1 and 7.08:1, warning light 5.41:1 / dark 10.02:1 and 9.38:1; alert icon-on-soft 7.12/7.53 (success), 7.33/8.88 (info), 4.80/7.72 (warning); badge default 8.08/9.81 (success), 8.53/10.84 (info), 5.41/10.02 (warning) - light/dark. Live: `fixround1-03-alert-warning-light-appearance-dark.png` (real alert.tsx classes injected, icon clearly legible on the amber tint), `fixround1-04-badge-default-appearance-light.png` (all 3 badges legible) |
| 4 | Reduced-motion selector rules lost to `!`-suffixed Tailwind utilities (unlayered `!important` is the WEAKEST important origin, and `navigation-menu.tsx`'s two `slide-in-from-*-52!` utilities live in Tailwind's `utilities` layer) | Two-part fix per the ruling: (a) `config.reui.css` collapses `--duration-fast/base/slow` to `1ms` under the media query at the TOKEN layer - every present/future `duration-(--duration-*)` consumer stops without a selector list; (b) the selector-based tw-animate/demo1/vaul reset in `styles.css` moved inside `@layer base`, which importants-invert AHEAD of `utilities` - not dropping the two navigation-menu `!` utilities, which resolve a real simultaneous-data-attribute conflict unrelated to motion | `css/design-tokens.test.ts` "AC-DLA-05" (unchanged assertions on content, now sourced from inside `@layer base`) + "AC-DLA-01" (token collapse values); live: `matchMedia('(prefers-reduced-motion: reduce)').matches === true` and `getComputedStyle(html).getPropertyValue('--duration-fast') === '1ms'` confirmed via `agent-browser eval`, then `fixround1-05-megamenu-reduced-motion.png` + `fixround1-06-mobile-nav-sheet-reduced-motion.png` (both open cleanly, no console errors). Dialog and Sheet keep their tw-animate travel under reduced motion until T3 moves them onto the spring (the accepted T1-to-T3 window - no backlog row, T3 is the next-but-one slice). |
| 5 | Header hairline conditional on scroll position was dead weight - the material look means the edge is always on | Deleted the `headerSticky`/`useScrollPosition` subscription and the `border-transparent` branch; `header.tsx` now carries a bare, static `border-b border-border` alongside `material-edge` | `header.tsx` diff (no `useScrollPosition` import remains); `npx eslint` clean (no unused-import warning); visible in every T1 and fix-round-1 screenshot of the header |
| 6 | `prefers-reduced-transparency` and `prefers-contrast: more` carried two independent copies of the same material/scrim/pinned flattening, and `prefers-contrast: more` was MISSING the overlay scrim rule reduced-transparency had | Merged into one `@media (prefers-reduced-transparency: reduce), (prefers-contrast: more) { ... }` query carrying the shared flattening (now including the overlay scrim rule for both); a second, contrast-only `@media (prefers-contrast: more)` block keeps just the border/input/muted-foreground/material-edge deltas | `css/design-tokens.test.ts` "merges reduced-transparency and prefers-contrast: more..." (asserts the merged selector text contains both conditions + the scrim-on-overlay rule) and "raises borders/muted-foreground/material-edge under prefers-contrast: more ONLY..." (asserts the contrast-only block does NOT repeat backdrop-filter/pinned) |
| 7 | `--z-sticky-content`/`z-1` unused; DataGrid's sticky header and navigation-menu's indicator still used ad-hoc literals; the `z-[N]` guard had a `zIndex:` inline-style escape hatch | `data-grid.tsx`'s `headerSticky` -> `z-(--z-sticky-content)` (was `z-10`); `dialog.tsx`/`alert-dialog.tsx`/`sheet.tsx`/`drawer.tsx` overlays AND contents (8 sites) -> `z-(--z-modal)` (was `z-50`); `navigation-menu.tsx`'s `style={{zIndex:1}}` -> the bare-numeric `z-1` utility (Tailwind v4, out of the banned `z-[N]` class vocabulary). Guard widened to ALSO ban a raw `zIndex:` inline style outside a documented runtime-drag/-pin allowlist (`data-grid-table.tsx`, `data-grid-table-dnd.tsx`, `data-grid-table-dnd-rows.tsx`, `avatar-group.tsx` - these compute the value from drag/pin STATE, which no static class can express) - navigation-menu.tsx's own `zIndex:` was the one non-allowlisted hit and is now gone. Numeric `z-<N>` utilities stay allowed (Sorento parity); a baseline-range test (74 measured, ceiling 120) guards against a mass-revert without hand-maintaining an exact count. `--grid-max-h` stays defined, comment now says "T2 wires the first consumer". | `css/design-tokens.test.ts` "leaves no zIndex: inline style..." + "documents the remaining bare numeric z-<N>..." |
| 8 | Raw-CSS-in-components hard-fail conflicted with T1 legitimately owning 4 CSS files | Sanctioned in THIS slice (not deferred to T8): `PRINCIPLES.md` design-mandate bullet and hard-fail-rules line, and `service_frontend/CLAUDE.md`'s equivalent bullet, all three now read the identical sentence naming the four sanctioned files (`config.reui.css`, `foundryx-tokens.css`, `styles.css`, `demos/demo1.css`) verbatim, so the coordinator's identical main-checkout edit merges clean | `PRINCIPLES.md` + `service_frontend/CLAUDE.md` diffs; no em/en dash (`grep` clean) |
| 9 | Below-cap cleanups | Dropped the identical `.dark` motion-token redeclaration in `config.reui.css` (inheritance already carries `:root`'s values; the AC-DLA-01 dark-mode assertions still pass unchanged since the VALUES are identical, just declared once); `demo1.css`'s `--sidebar-transition-timing: ease` -> `var(--ease-standard)` and `-duration: 0.3s` -> `var(--duration-slow)`; removed a redundant explicit `ease-(--ease-standard)` from every bare `transition-*` utility that had NO ease originally (accordion.tsx x4, accordion-menu.tsx x2, collapsible.tsx, navigation-menu.tsx x2, progress.tsx bar) - kept it where an ORIGINAL non-default ease was actually replaced (switch.tsx's raw cubic-bezier, progress.tsx's circle/radial `ease-in-out`, screen-loader.tsx's `ease-in-out`, sheet.tsx's `ease-in-out`); `design-tokens.test.ts`'s `injectStylesheet` now appends its `<style>` tag ONCE (memoized) instead of once per call (11 call sites collapsed to 1 real injection) | `css/design-tokens.test.ts` all 78 assertions green; `grep -c ease-(--ease-standard)` shows only the 4 kept sites |
| 10 | Re-run gate + evidence refresh | `npx eslint` (16 touched files, clean), `npx vitest run` (172 files / 1489 tests, +24 vs the DONE baseline), `rm -rf .next && npm run build` (green), served on :3002. Evidence refreshed for every surface the fixes touched. | This section + the 8 `fixround1-*.png` screenshots under `23-evidence/T1/` |

**Harness note (not a product bug):** mid-verification the sidebar accordion's synthetic click
stopped registering through `agent-browser`'s CDP click on one long-lived tab (a native
`element.click()` via `agent-browser eval` worked immediately) - closing the session and
opening a fresh one also cleared it. Same class of harness quirk CLAUDE.md's sprint-3
process-lessons section already documents for Playwright MCP; not caused by this diff (a
fresh session drove the identical dropdown/menu flows without incident both before and after).

**Verdict: T1 fix round 1 DONE.** 10/10 findings resolved and re-verified; full gate green;
evidence refreshed. `css/design-tokens.test.ts`: 78 assertions, all green.

---

## T1 - Fix round 2

One confirmed finding from a second `/code-review` pass over the fix-round-1 diff.

**Finding:** with the impersonation banner expanded on `lg`, the sidebar box itself already
shrinks with the banner (`sidebar.tsx:16` `lg:top-[var(--shell-top-offset,0px)] lg:bottom-0`,
fix round 1's own change), but the menu scroller kept a `100vh`-relative cap
(`sidebar-menu.tsx:246` `lg:max-h-[calc(100vh-5.5rem)]`) inside an `overflow-hidden` wrapper
(`sidebar.tsx:23`) that had no `flex-1 min-h-0` - so with the banner's real measured height
B=45px, the scroller's cap stayed a FIXED viewport fraction while the box underneath it
shrank by B, and the last ~7px of the final nav item (after its own `py-5`) sat past the
sidebar's real bottom edge, unreachable at max scroll.

**Fix:** `sidebar.tsx`'s `overflow-hidden` wrapper gained `flex-1 min-h-0` (a flex child never
shrinks below its content size without `min-h-0`, which is exactly why the wrapper had stayed
content-sized before) plus `h-full` on the inner width-only div so the percentage height has
a definite ancestor to resolve against; `sidebar-menu.tsx`'s scroller dropped the `100vh` calc
entirely for `lg:h-full lg:max-h-full` (kept `lg:`-scoped, matching the original's scope - the
same `SidebarMenu` component also renders unscoped inside the MOBILE nav `Sheet` via
`header.tsx`, a completely different flex/scroll context that must not be touched). The
scroller is now bounded purely by whatever height the flex ancestor chain actually gives it,
whatever the banner does - no more viewport-relative guessing.

**Test:** `css/design-tokens.test.ts` "bounds the sidebar menu scroller by the remaining flex
height, not a 100vh calc" - asserts `sidebar.tsx` carries `flex-1`+`min-h-0` on the
overflow-hidden wrapper, and `sidebar-menu.tsx` no longer matches `max-h-[calc(100vh` and
instead carries `lg:h-full`/`lg:max-h-full`. 79/79 assertions green (was 78).

**Browser verification:** `demo@example.com` (Admin, full ~19-item menu - the one role whose
menu reliably overflows even before any banner) at 1280x700 (per the brief's "window at ~700px
tall"). The impersonation feature's OWN permission rule blocked an Admin-impersonating-Admin
session in this pass (`POST /impersonation/start` 400 - unrelated to this CSS fix, not
investigated further here; a Member-role target's session started fine and its real banner
measured exactly B=45px, confirming the round-1 `ResizeObserver` value independently) - rather
than debug an unrelated permission rule, `--shell-top-offset` was set to that SAME real,
just-measured 45px value directly on `document.documentElement` (`agent-browser eval`, the
identical mechanism the banner's own `ResizeObserver` effect uses) while viewing the Admin
account's own full menu, which is a faithful reproduction of "banner expanded" for this
CSS-only fix (the fix has zero dependency on WHERE the offset value comes from). Confirmed via
`agent-browser eval`: sidebar box `top: 45, bottom: 577` (== `window.innerHeight`, no overflow
past the viewport), scroller `scrollHeight: 858` vs `clientHeight: 462` (genuinely overflows,
`scrollTop` set to `scrollHeight` reached exactly `396 = 858-462`, i.e. true max scroll, not
clamped short). Screenshot `fixround2-01-sidebar-bottom-banner.png`: "AutoCount" (the last menu
item) fully visible with clean spacing below it, nothing clipped.

**Recorded, not fixed (accepted per the coordinator):** the material header
(`material-regular material-edge`, `header.tsx`) has no `@media print` fallback - a printed
page would carry the translucent/blurred material styling as-is. This app has no print use
case (no print stylesheet, no print button anywhere in the product), so this is accepted as
out of scope rather than fixed.

**Gate:** `npx eslint` (`sidebar.tsx`, `sidebar-menu.tsx`, `design-tokens.test.ts` - clean),
`npx vitest run` (172 files / 1490 tests, +1 vs fix round 1), `rm -rf .next && npm run build`
(green), served on :3002 (backend :8001 healthy throughout).

**Verdict: T1 fix round 2 DONE.** 1/1 finding resolved and verified; print-fallback gap
recorded as accepted, not fixed; full gate green.

---

## T1 - Fix round 3

10 findings from a third `/code-review` pass over the fix-round-2 diff, applied as written
(same branch/worktree). Findings 1+2 REVERT fix round 1's `-active`/`-accent` remap of
`--success`/`--info`/`--warning` (it disconnected the tenant Branding controls from those
semantic vars) and fix it one layer down instead - see the hex/ratio table below.

| # | Finding | Fix | Proof |
|---|---|---|---|
| 1+2 | `--success`/`--info`/`--warning` pointed at `--foundryx-*-active`/`-accent` (fix round 1), which the tenant Branding editor never writes to - a tenant's picked Success/Info/Warning colour became invisible to any consumer of the semantic var; `--warning`'s dark hue also read as a tan/olive off-shade | Semantic vars reverted to a plain pass-through (`--success: var(--foundryx-success)`, same for info/warning); the DARKENING moved to the `--foundryx-success/-info/-warning` primitives THEMSELVES (light only - `.dark` already passed unmodified) so the raw hue clears 4.5:1 both as ink-on-`--background` and against a white foreground at once (same bound, `--background` is white in light). `warning`'s raw hue cannot pass while staying lighter than its OWN original `-active`/`-accent`, so those two are darkened in proportion too (whole amber scale moves down together, never crosses over itself) - `-soft` untouched throughout. `-transparent` recomputed from each new base RGB. Branding defaults (`lib/branding-tokens.ts`, `app/branding/token_whitelist.py`) updated to the same hex; `service_backend/tests/test_branding.py`'s one hardcoded default (`"#1f9d54"`) updated to match | Hex + ratio table below; `css/design-tokens.test.ts` "AC-DLA-07 semantic ink contrast" (unchanged assertions, now measuring the new values) - 80/80 green; `service_backend/.venv/bin/python -m pytest service_backend/tests/test_branding.py -q` - 28/28 green (parity test `test_frontend_defaults_parity` unaffected, it diffs the two files against each other, not against a fixed hex); `fixround3-02-alert-warning-variants-{1280,375}-{light,dark}.png` |
| 3 | `--z-banner` comment (and its test mirror) implied clickability under a modal - it only means paint order | Reworded both comments to "paint order only" and explicit non-claim of clickability, pointing at a new backlog row for the real gap | `css/config.reui.css` (`--z-banner` comment), `css/design-tokens.test.ts` (matching comment); `documentation/backlogs/backlog.md` `BL-SS-050` |
| 4 | Hand-rolled sticky surfaces still at `z-10`: `sql-preview-grid.tsx:66`, `branding-editor.tsx:203`, `settings-sidebar/content.tsx:76` | All three -> `z-(--z-sticky-content)`. Guard widened: a NEW test bans bare `z-<N>` under `app/**`+`components/platform/**` outside an explicit, fully-enumerated allowlist (10 files - the genuine remaining stacking-order consumers this sweep found: avatar-group hover-to-front, canvas drag-handle locals, context-menu/inspector portals); `components/ui/**` stays under the pre-existing loose ceiling (Sorento parity) | `css/design-tokens.test.ts` "bans bare z-<N> under app/\*\* and components/platform/\*\* outside the recorded baseline allowlist" + "records the ... baseline as exactly 10 files"; the 3 fixed files' diffs |
| 5 | Reduced-motion `[data-slot$='-content']` selector could still hit a vaul drawer once T3 mounts it (only dialog-content/sheet-content were excluded) | Added `:not([data-vaul-drawer])` to the selector; comment rewritten to state the literal 150ms is DELIBERATE (an overlay must still fade, not instant-snap, under reduced motion) and separate from the 1ms token-layer collapse (which covers every OTHER duration-token consumer) - replaces the old "token collapse covers every consumer" framing | `css/styles.css` selector + comment; `css/design-tokens.test.ts` "excludes dialog-content/sheet-content..." unaffected (still matches the widened selector) |
| 6 | `email-editor/canvas.tsx` DropGap's `transition-[height,margin,background-color,border-color]` omits `border-width`, so a state change that flips `border` from none to `border-dashed` (or vice versa) snaps the border THICKNESS instantly while color/height still animate | Added `border-width` to the transition property list | `components/platform/email-editor/canvas.tsx` DropGap diff |
| 7 | `alert.tsx`'s "mono" variant `icon` compounds (success/warning/info) tinted the icon with `-foreground` (a fill-ink white/black constant meant for text ON a solid hue fill) instead of a hue tint - wrong role, and on a neutral mono surface a near-white/near-black icon barely reads as "coloured" at all | Mono+icon compounds -> `-accent`, matching the already-correct `appearance="light"` compounds exactly (same CSS var, same fallback shade) | `components/ui/alert.tsx` 3 compound diffs; `css/design-tokens.test.ts` "sends alert.tsx light-appearance AND mono+icon compounds to -accent, not -foreground" (asserts exactly 2 `-accent` occurrences per hue - light-appearance + mono - and zero `-foreground` occurrences on the icon selector); `fixround3-02-alert-warning-variants-*.png` (both the light-appearance AND solid/outline mono rows read clearly) |
| 8 | `ProgressRadial`'s indicator transitioned `stroke-dashoffset`, but its arc is drawn via a recomputed `d` (path) attribute on every value change - `stroke-dashoffset` is never set, so the transition target doesn't exist (dead declaration, silently a no-op) | -> `transition-[stroke,color]` (what the component actually varies: `stroke="currentColor"` following a `text-*` colour change, plus any future stroke-colour swap); `ProgressCircle` (which DOES use `strokeDashoffset`) is untouched | `components/ui/progress.tsx` `ProgressRadial` diff (line ~212), `ProgressCircle` diff unchanged (verified by inspection, not touched) |
| 9 | `data-grid.tsx`'s `headerSticky` classes (`bg-background/90 backdrop-blur-xs`) fought the T1 material system - a sticky table header showing rows blur/ghost through it reads as a bug, not a material, on a plain content surface (not a header/sidebar shell layer) | -> `bg-background` (solid, no blur); z-scale token (`z-(--z-sticky-content)`, from fix round 1) untouched; does not flip the grid's default `headerSticky: false` (T2's job) | `components/ui/data-grid.tsx` line 144 diff |
| 10 | `config.reui.css` carried an unused `--z-sticky-content-corner` (zero consumers) and a `.dark` `--material-blur: 24px` re-declaration identical to `:root`'s (dead weight); `--grid-max-h`'s comment was stale; `dialog.tsx`/`alert-dialog.tsx`/`sheet.tsx` overlays hardcoded `bg-black/30` instead of the `--scrim` token, so the preference blocks' `--scrim` raise (fix round 1 finding 6) never reached them | Dropped `--z-sticky-content-corner` (+ its two z-scale test rows) and the `.dark` `--material-blur` duplicate; `--grid-max-h` comment -> "consumer = T2 DataGrid scroller"; all three overlays -> `bg-(--scrim)` (3 literals removed) | `css/config.reui.css` diffs; `css/design-tokens.test.ts` z-scale steps/ordering (5 steps now, was 6) - 80/80 green; `components/ui/{dialog,alert-dialog,sheet}.tsx` overlay diffs (`grep -c bg-black/30` -> 0 in these three files) |

### Semantic hue hex + contrast table (findings 1+2)

All ratios computed via the same WCAG relative-luminance formula `css/design-tokens.test.ts`
uses (sRGB gamma-correct, `(L1+0.05)/(L2+0.05)`). Light `--background` is white; dark
`--background` (`--foundryx-light` under `.dark`) is `#0c0b0a` (near-black) - both round to
the same ~4.5:1 threshold against a black/white foreground, which is why dark needed no
primitive change (the ORIGINAL dark hues already cleared it).

| Token (light) | Old hex | New hex | vs white (constraint a: fg=white, and b: ink-on-`--background`) |
|---|---|---|---|
| `--foundryx-success` | `#1f9d54` | `#1b8648` | 3.49:1 -> **4.62:1** |
| `--foundryx-info` | `#2c7ff7` | `#0f6ef6` | 3.83:1 -> **4.58:1** |
| `--foundryx-warning` | `#e8a318` | `#9b6d0f` | 2.17:1 -> **4.58:1** |
| `--foundryx-warning-active` | `#c2860d` | `#7e5708` | 3.13:1 -> **6.45:1** (kept strictly darker than the new base) |
| `--foundryx-warning-accent` | `#8f6107` | `#5b3e04` | 5.41:1 -> **9.83:1** (kept strictly darker than the new active) |

| Token (dark, UNCHANGED) | Hex | vs black (constraint a, fg=black) | vs `--background` dark #0c0b0a (constraint b) |
|---|---|---|---|
| `--foundryx-success` | `#1f9d54` | 6.01:1 | 5.63:1 |
| `--foundryx-info` | `#2c7ff7` | 5.49:1 | 5.14:1 |
| `--foundryx-warning` | `#e8a318` | 9.68:1 | 9.07:1 |

Derived pairings re-verified with the new hex (unaffected code paths, since `alert.tsx`'s
light-appearance and `badge.tsx`'s default compounds already read `-accent`/`-foreground`
directly, not the semantic `--warning` var that moved):

| Pairing | success | info | warning (the only hue whose `-accent` changed) |
|---|---|---|---|
| alert.tsx light-appearance icon (`-accent`) on `-soft` (light) | 7.12:1 | 7.33:1 | **8.72:1** (was 4.80:1 pre-round-1) |
| badge.tsx default (`-foreground` on `-accent`, light) | 8.08:1 | 8.53:1 | **9.83:1** (was 5.41:1 pre-round-1) |

Dark-theme derived pairings are unaffected (dark `-accent`/`-active` untouched): success
7.53/9.81:1, info 8.88/10.84:1, warning 7.72/10.02:1 (alert-icon-on-soft / badge-default),
all already >= 4.5:1 from fix round 1.

**Reviewer-facing colour change (flagged, not silently absorbed):** the light-theme
`--success`/`--info`/`--warning` semantic ink (and, for warning only, its `-active`/`-accent`
steps) is visibly darker than before this round - any consumer reading the bare `--success`/
etc var directly (not `-accent`/`-foreground`, which were already the darkest steps and are
mostly unchanged except warning's) picks up the new colour. Grep at the time of this report
found no other call site of the bare `--success`/`--info`/`--warning` var outside
`alert.tsx`'s solid/outline compounds (which read the CORRECT var for "the ink itself", so
this is the fix, not a side effect) and `badge.tsx`'s solid compound (same).

**Gate:** `npx eslint` (all touched files - clean), `npx vitest run` (172 files / 1491 tests,
80/80 in `css/design-tokens.test.ts` alone - was 79/79 in fix round 2, net +1 after dropping
2 `-corner` assertions and adding 3 new ones), `rm -rf .next && npm run build` (green), served
on :3002; `service_backend/.venv/bin/python -m pytest service_backend/tests/test_branding.py -q`
(28/28 green); full backend regression `service_backend/.venv/bin/python -m pytest -q` -
**2702 passed, 1 skipped, 18 deselected, 0 failed** (1699s) - the semantic-hue default swap
touches only `token_whitelist.py` + its own test file, and this confirms nothing else in the
suite (branding, status/rule/template/workflow/form engines, omnichannel, AutoCount,
ideation, ...) reads a hardcoded copy of the old hex.
Evidence: `fixround3-01-users-list-{1280-light,1280-dark,375-dark}.png`,
`fixround3-02-alert-warning-variants-{1280,375}-{light,dark}.png`.

**Verdict: T1 fix round 3 DONE.** 10/10 findings resolved and re-verified; one deliberate,
reviewer-facing colour change flagged above (not silently absorbed); full gate green.
