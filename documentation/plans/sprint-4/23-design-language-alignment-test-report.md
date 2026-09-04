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
