# 23 - Design language alignment (Sorento parity) - Test Execution Report

Keyed to `23-design-language-alignment-acceptance-criteria.md`. One section per slice,
appended as each slice completes (`AI_Agent_Orchestration_Guide.md` §6 format).

---

## T0 - Playwright retirement

Branch `sprint-4/23-T0-playwright-retirement`, worktree `.claude/worktrees/s23-t0`.

| AC | Given/When/Then | Result | Proof |
|----|----|----|----|
| AC-DLA-68 | `service_frontend/e2e/`, the three `playwright*.config.ts`, `playwright-report/`, `test-results/` are deleted; `package.json` has no `test:e2e` script and no `@playwright/test` dependency; `package-lock.json` regenerated `--package-lock-only` without touching the shared `node_modules`; `.gitignore` drops the three Playwright lines; `npm run lint`, `npm test`, `npm run build` green. | **PASS** (build and test legs re-verified green by the main session on 4 Sep after the node_modules fix, see Remarks). | `git rm -r service_frontend/e2e` (57 tracked files incl. `fixtures/avatar.png`, `helpers/*`) + `git rm` on the 3 configs; `playwright-report/`/`test-results/` were absent on disk and untracked (nothing to remove). `package.json` diff = exactly 2 line removals (`test:e2e` script, `@playwright/test` devDependency). `package-lock.json`: `git diff --stat` = `1 file changed, 64 deletions(-)` (verified: the diff's only `+` line is the `+++` header - a pure removal). `node_modules` mtime unchanged before/after (`stat -f "%m %N" node_modules` and `node_modules/@playwright` both identical pre/post-uninstall) - the symlinked shared `node_modules` was not rewritten. `.gitignore` no longer has `playwright-report/`, `playwright/.cache/`, `.playwright-mcp/` (also cleaned the same 3 lines from `service_frontend/.dockerignore` plus its now-dead `e2e/` ignore entry, found in the same sweep). `npm run lint`: 0 errors, 3 pre-existing unrelated warnings. `npm test`: 1315/1315 individual tests pass; 13 test FILES fail to even load with `Failed to resolve import "@codemirror/..."` from `components/platform/autocount/sql-editor.tsx` - a pre-existing, unrelated gap (the shared `node_modules/@codemirror/*` directories exist but are empty; `package.json` already declared these `dependencies` before this slice touched anything; `git diff service_frontend/package.json` shows only the two Playwright-removal lines). `npm run build`: fails on the same 5 `@codemirror/*` module-not-found errors from the same file - not caused by this slice, and not fixable from this worktree without writing into the main checkout's `node_modules` (forbidden by this slice's brief). Filed as a note for the plan owner rather than silently touched. |
| AC-DLA-69 | Zero case-insensitive `playwright` occurrences remain outside `documentation/plans/**` and `node_modules`; covers `AGENTS.md`/`CLAUDE.md`, `PRINCIPLES.md`, `service_frontend/CLAUDE.md`, `.claude/skills/**`, `.claude/agents/**`, `docs/**`, `.github/**`, code comments; a vitest guard walks the repo and fails on any hit. | **PASS** | `service_frontend/no-playwright.guard.test.ts` (named `AC-DLA-69`) passes: `npx vitest run no-playwright.guard.test.ts` -> `1 passed`. Full-repo sweep after all edits (`grep -rIli playwright . --exclude-dir={node_modules,.next,.git,.claude/worktrees,documentation/plans,documentation/preliminary_planning,service_backend/modules/meetings/bot}`) returns only `AGENTS.md` (1 hit, the retained retirement sentence), `PRINCIPLES.md` (1 hit, same), `service_frontend/no-playwright.guard.test.ts` (self-referential, the test's own doc comments) and `service_frontend/package-lock.json` (Next.js's own optional `@playwright/test` peerDependency metadata - upstream, not authored here). `.claude/agents/**` and `docs/**` were checked and contain no Playwright mentions in this worktree (no `.claude/agents/` directory present; `docs/agents/*.md` clean); no `README.md` at repo root; `.github/workflows/*.yml` clean. |
| AC-DLA-70 | `PRINCIPLES.md` step 6/DoD, `AGENTS.md` commands + methodology, `service_frontend/CLAUDE.md`, `.claude/skills/feature/SKILL.md` (steps 5/6, skill map) state `[E2E]` = one recorded `agent-browser` run per user flow (real clicks from the sidebar, 375 AND 1280, evidence dir, README run log); Playwright is named only in the one retirement sentence per file. | **PASS** | `PRINCIPLES.md` step 6 rewritten to "Browser verification (Playwright is retired...)" - the sole retained sentence, confirmed by the guard test's per-file allowance assertion (`toBe(1)`). `AGENTS.md` methodology step 7 rewritten identically (the sole retained sentence there) plus 10 other in-file mentions reworded to `agent-browser`/generic browser-automation language with zero remaining Playwright words. `service_frontend/CLAUDE.md` both mentions (`Responsive` bullet, `Tests` bullet) rewritten to `agent-browser` CLI, zero Playwright words remain. `.claude/skills/feature/SKILL.md` steps 5/6 and the skill map row rewritten to `agent-browser` CLI, zero Playwright words remain. No `.claude/agents/{coder,tester,planner}.md` exist in this worktree (nothing to edit there). |

### Remarks

- **Resolved 4 Sep (main session):** the worktree now has its own `node_modules` (`rm node_modules && npm ci --force`, 801 packages, no `@playwright`); `rm -rf .next && npm run build` = `Compiled successfully in 50s`, 113/113 static pages; `npm test` = 172 files, 1412 tests passed (the 13 files that could not load now run). Process lesson recorded: worktrees must not symlink `node_modules`, branches diverge in `package.json`. Original finding: **`npm run build` did not go green**, for a cause unrelated to this slice: `components/platform/autocount/sql-editor.tsx` (part of the plan-22 AutoCount DB ETL feature, untouched by T0) imports `@codemirror/{autocomplete,commands,lang-sql,language,state}`, all declared in `package.json` `dependencies` (pre-existing, `git diff` confirms this slice never touched that section) but physically absent from the shared `node_modules` (`node_modules/@codemirror/*` directories exist but are empty - an incomplete `npm install` predating this session, mtime Sep 1). Fixing it requires `npm install`/writing into the main checkout's `node_modules` (the worktree's `node_modules` is a symlink to it), which this slice's brief explicitly forbids touching. Recommend the next coder or the user runs a fresh `npm install --force` in the main checkout.
- **One unrelated pre-existing lint error was fixed in passing** (`services/import-service.mock.ts:33` - unused `_i: CreateImportInput` parameter/import, `@typescript-eslint/no-unused-vars`) because it blocked the `npm run lint` gate this slice's DoD requires; the fix is a one-line removal with zero behavior change, called out here for visibility since it is outside T0's Playwright scope.
- **Two directories were judged out of scope and excluded from the guard test, both documented inline in the test file:** `documentation/preliminary_planning/**` (pre-repo founding planning docs, treated as historical record like `documentation/plans/**` since rewriting them to describe today's tooling would misrepresent history) and `service_backend/modules/meetings/bot/**` (a shipped Google-Meet-joining bot that genuinely depends on the `playwright` PyPI package as its own headless-browser engine - an unrelated product feature, not this repo's E2E test tooling).
- `documentation/backlogs/backlog.md` (BL-061, BL-069) and `documentation/development_process/{AI_Agent_Orchestration_Guide.md,EMS_Developer_Governance_Framework.md}` and `documentation/research/template-engine-builder-landscape.md` were swept and reworded even though the brief's literal sweep grep excludes `documentation/` - rule (a) explicitly calls these "process guides" out for rewriting, and the AC-DLA-69 guard walks them.

---

## T0 - Fix round 1 (code review)

`/code-review` returned 10 confirmed findings against the T0 slice above. The UAC was amended at
`5661cbd` (AC-DLA-68/69/70 in `23-design-language-alignment-acceptance-criteria.md`) to define
"done" for this round; findings are grouped under the amended AC they close. Same branch/worktree.
The worktree's `node_modules` was fixed to a real `npm ci` install (not a symlink) by the main
session before this round started - `npm run build` was already green going in; this round did
not touch `node_modules`.

| # | Finding | What changed |
|---|---|---|
| F1 | The guard test walked the filesystem (`readdirSync` recursion from the repo root) instead of scoping to git-tracked content - gitignored artefacts and untracked local scratch files could decide the verdict. | Rewritten around ONE `git grep -Iin playwright -- . <pathspecs>` call (`execFileSync`), matching `git ls-files`' notion of "tracked". |
| F2 | The old walk silently swallowed `readdirSync`/`readFileSync`/`lstatSync` errors (`try { } catch { continue/return }`), so a permissions or race error would silently under-scan instead of failing the test. | The rewrite has exactly one place an error can occur (the `execFileSync` calls) and rethrows with context on any exit code other than git grep's expected "no matches" (1); a `git rev-parse` failure (not a repo) throws loudly too. |
| F3 | An arbitrary 2MB file-size cap could hide a real hit in a large tracked file. | Removed - `git grep` has no such cap. |
| F4 | The walk ran under jsdom (the default vitest environment for this project) for a test that never touches the DOM - unnecessary overhead and a category error. | `// @vitest-environment node` on the guard test. This required a defensive fix to the shared `vitest.setup.ts` (`if (typeof Element !== 'undefined')` around its jsdom-only polyfills), since that file runs for every test file regardless of its own declared environment and previously assumed `Element` always exists. |
| F5 | AC-DLA-69 was enforced only by the frontend vitest suite - a backend-only PR (or any PR that skips `npm test`) could reintroduce Playwright with nothing to catch it. | Added a "No stray play[w]right mentions..." step to the existing `lint-conventions` job in `.github/workflows/deploy.yml`, same `git grep` pathspecs, same style as the neighbouring em-dash/brand-spelling steps (bracket-expression pattern so the step's own script text never self-matches, same trick as the file's existing `Foundry[X]` check). |
| F6 | `.gitignore`/`.dockerignore` had genuinely lost the `playwright-report/`, `playwright/.cache/`, `.playwright-mcp/` lines - these are real local artefact dirs that can still exist on a developer's disk from before the purge, and un-ignoring them risks `git add -A` staging them as junk. | Restored in both files as bracket-expression patterns (`[p]laywright-report/`, `[p]laywright/.cache/`, `.[p]laywright-mcp/`) with a one-line comment explaining why, verified with `git check-ignore -v` against dummy files (deleted after verification) - the patterns ignore correctly and the guard test does not flag the `.gitignore`/`.dockerignore` lines themselves. `test-results/` was already kept. |
| F7 | `AGENTS.md` had 13 dangling citations to deleted `e2e/*.spec.ts` files and `e2e/helpers/mailbox.ts` (lines 158, 169, 179, 207, 220, 236, 248, 253, 281, 302, 315, 419, plus one inside a sub-bullet). | Each citation reworded to "Coverage = the slice's agent-browser evidence run" (keeping any still-relevant substance - journey counts, report paths, isolation lessons) or dropped where it named only a deleted helper file. Verified: `grep -n "e2e/\|\.spec\.ts" AGENTS.md` now returns nothing. |
| F8 | Four `AGENTS.md` sub-bullets directly under the retirement sentence (methodology step 7, lines 461-465) still described Playwright-specific mechanics: `fullyParallel`, the Meta-env Embedded-Signup spec "fails by design", `tenants.spec.ts` page-1 residue, and the mailbox rig "for specs". | Rewritten as lessons for `agent-browser` evidence runs: dedicated tenant before a shared-state-mutating run, unset the Meta env for the simulated Embedded Signup flow, timestamp every name a run creates, and the same mailbox rig for reading delivered mail during a run. The un-touched fifth sub-bullet (`Wrong-build gotcha`) needed no change - it never cited a spec file. |
| F9 | Four code comments (`status-engine.test.tsx:86`, `canvas-editor.test.tsx:3`, `node-palette.tsx:9`, `palette.tsx:7`) claimed in the present tense that a live E2E run asserts the drag/edge/canvas behaviour jsdom can't - no such run exists anymore, so the claim was false. | Reworded as explicit gaps: "not asserted in jsdom; ... needs a recorded agent-browser check in any slice that touches it." `node-palette.tsx:9` additionally dropped the Playwright-specific `dragTo` API name (now describes it generically as "scripted mouse-event drag automation"). |
| F10 | The T0 test report's AC-DLA-68/69/70 rows were written against the pre-amendment UAC wording (`.gitignore` DROPS the lines; guard test = filesystem walk) and needed re-verification against the amended text. | This section re-verifies all three ACs against the amended wording (below) and re-runs `npm run lint && npm test && rm -rf .next && npm run build` in full. |

### Re-verification against the amended AC-DLA-68/69/70

| AC | Amended wording (key deltas from round 0) | Result | Proof |
|----|----|----|----|
| AC-DLA-68 | `.gitignore` now KEEPS `playwright-report/`/`playwright/.cache/`/`.playwright-mcp/`/`test-results/` (reversed from round 0: "drops" -> "keeps"), with a one-line comment; `npm run lint`/`npm test`/`npm run build` green. | **PASS** | See F6 for the gitignore restoration + `git check-ignore` proof. Lint/test/build tails below - all green, no errors. |
| AC-DLA-69 | Scope = TRACKED tree only (`git ls-files`), not gitignored/untracked disk state; named exclusions now include `documentation/preliminary_planning/**` explicitly (was an unwritten judgment call in round 0, now in the contract) and drop the earlier `node_modules` wording (moot under git-grep scoping); guard = ONE `git grep -Iil playwright -- <pathspecs>` call, `@vitest-environment node`, repo root via `git rev-parse --show-toplevel`, ALSO fails on any tracked path NAME containing `playwright`; `.claude/**` is gitignored so it is explicitly out of this guard's scope (covered by the user's own main-checkout copies instead). | **PASS** | `service_frontend/no-playwright.guard.test.ts` rewritten per spec (F1-F4); `npx vitest run no-playwright.guard.test.ts` -> 1 passed, 72-108ms (well under 1s). Verified both directions with a throwaway tracked file (`stray-pw-test.md` containing the word, staged then removed): the guard test AND the CI step both fail loudly on it, and both pass clean once removed. `git ls-files \| grep -i playwright` returns only the guard test's own filename (excluded by name in the test). |
| AC-DLA-70 | Unchanged in substance; `AGENTS.md`'s "every lesson bullet that cited a deleted `e2e/*.spec.ts` or helper (13 sites) or described the deleted runner" is now explicit in the AC text (was implicit before review). | **PASS** | F7 + F8 above; `grep -n "e2e/\|\.spec\.ts" AGENTS.md` -> no matches. `AGENTS.md`/`PRINCIPLES.md` each still carry exactly one retirement sentence (asserted by the guard test's `RETIREMENT_LINE_ALLOWANCE` check, `toBeLessThanOrEqual(1)`). |

### Command tails (this round, after all fixes)

`npm run lint`:
```
✖ 3 problems (0 errors, 3 warnings)
  0 errors and 2 warnings potentially fixable with the `--fix` option.
```
(same 3 pre-existing, unrelated warnings as round 0 - `idea-attachment-preview-dialog.tsx`,
`use-connections-list-config.tsx`, `share-browser.tsx`.)

`npm test`:
```
 Test Files  172 passed (172)
      Tests  1412 passed (1412)
   Duration  28.89s
```
(includes `no-playwright.guard.test.ts` - 1 passed. One unrelated `stderr` accessibility warning
from `share-dialog.test.tsx` prints during the run - a pre-existing console warning inside a
passing test, not a failure.)

`rm -rf .next && npm run build`:
```
 ✓ Compiled successfully in 23.0s
   Linting and checking validity of types ...
```
exit code 0. (One pre-existing, unrelated CSS-optimizer warning - "Invalid media query" on a
Metronic `.kt-scrollable` rule - prints during the build; not new, not fatal.)

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

---

## T2 - Primitives

**Branch:** `sprint-4/23-T2-primitives` (off `sprint-4/23-design-language-alignment`, at `53ee957`
- T0+T1 merged).
**Evidence:** `documentation/plans/sprint-4/23-evidence/T2/` (`README.md` run log + 20
screenshots).
**Environment:** backend `service_backend` (this worktree's venv) on :8001; frontend
`rm -rf .next && npm run build` (green) served via `npx next start -p 3002` (this worktree, port
ownership confirmed via `lsof` before every restart); `agent-browser` CLI only, real clicks,
`demo@example.com`/`demo1234`.

Tests were written first per primitive and watched fail for the right reasons (missing exports,
un-migrated primitives, old defaults) before implementation, per the work order - see each AC's
Steps for the exact file. Two AC-DLA-13/18 bugs (mobile page-scroll, mobile-pin specificity) were
NOT caught by any unit test - jsdom has no real layout - and were found and fixed live during the
375 evidence pass; both are now pinned by new inventory assertions.

### AC-DLA-09 - primitive-classes exports + PRESSED_CLASS/COARSE_HIT_TARGET_CLASS `[FE][T]`

**User story:** As a maintainer, I want the pressed feedback and touch-target rules defined once
so every control answers the same way.
**Scenario:** Given `components/ui/primitive-classes.ts`, when a primitive that must feel pressed
or reach 44px imports it, then the class strings are wired exactly where AC-DLA-09 names.
**Steps:** `npx vitest run components/ui/primitive-classes.test.ts`.
**Expected:** exports present with the exact token/class content; Button lg/md/icon, checkbox,
switch, radio, toggle, TabsTrigger, slider thumb, DropdownMenuItem, ContextMenuItem, MenubarItem,
CommandItem carry `PRESSED_CLASS`; Button lg/md/icon + checkbox/switch/radio carry
`COARSE_HIT_TARGET_CLASS`; `sm` buttons do not.
**Actual:** PASS - 20/20 assertions green.
**Remarks:** Ported verbatim from Sorento `origin/main` with the M1-01 `duration-fast`/
`ease-standard` refinement (from `origin/integration/ui-motion-round2`) already baked into
`PRESSED_CLASS`, per the AC's literal quoted class string - deliberately did NOT port the
integration branch's separate `PRESSED_TRANSFORM_CLASS` (keyboard-item variant without a colour
transition), since AC-DLA-09 explicitly lists `DropdownMenuItem`/`ContextMenuItem`/`MenubarItem`/
`CommandItem` under plain `PRESSED_CLASS` with no mention of a transform-only variant - see "AC
wording I flagged" at the end of this report.

### AC-DLA-10 - Dialog/AlertDialog/Sheet modal + overlay + caps + close ring `[FE][T]`

**Scenario:** Given any `Dialog`/`AlertDialog`/`Sheet` without an explicit `modal`, when it opens,
then it is modal (focus trapped, Escape closes); overlay = the shared `OVERLAY_CLASS` scrim;
`AlertDialog`/`Sheet` top-bottom content cap height and scroll; `SheetBody` scrolls independently;
`DialogClose` no longer suppresses the focus-visible ring.
**Steps:** `npx vitest run components/ui/modal-defaults.test.tsx`; browser: user-record Trash
AlertDialog, mobile nav Sheet.
**Expected:** 7/7 assertions; live Escape-closes and scrim-visible proof.
**Actual:** PASS - 7/7. Live: `23-evidence/T2/05-user-record-trash-dialog-1280.png` (AlertDialog,
scrim+blur, Escape confirmed to close it) and `19-mobile-nav-sheet-375.png` (Sheet, same scrim,
Escape closes).
**Remarks:** `AlertDialog` needed no `modal` default change - Radix's `AlertDialogProps` OMITS the
`modal` prop entirely (`Omit<DialogProps, 'modal'>`), so it is unconditionally modal already; only
`Dialog` and `Sheet` gained an explicit `modal = true` default (Radix's own default was already
`true`, so this is a documentation/defensiveness change with zero behavioural delta for existing
callers - confirmed no call site anywhere in the tree passes `modal={false}`). The plan's risk note
about utility sheets (workflow canvas drawer, conversation drawer, jobs drawer) needing
`overlay={false}`/`modal={false}` did not apply: none of those three surfaces in this codebase are
actually built on the `Sheet`/`Dialog` primitives (the conversation drawer and workflow
node-config panel are hand-rolled inline panels, not Radix dialogs) - grepped and confirmed, no
code change needed there.

### AC-DLA-11 - Badge shape/appearance/status dot `[FE][T]`

**Scenario:** Given `Badge`, when rendered with `appearance="light"` (default) in dark mode, then
the background and text resolve to DIFFERENT tokens (was: both read the same `-soft` var, so the
pill rendered as a solid block with invisible text); given `shape="circle"`, then it stays a solid
disc; given `appearance="ghost"`, then it does not exist anywhere.
**Steps:** `npx vitest run components/ui/badge.test.tsx`; browser: Users list dark.
**Expected:** `rounded-full` base, `md`=h-6/px-2.5, `sm`=h-5/px-2; every `light`/`outline` compound's
`dark:bg`/`dark:text` reference different `--color-*` custom properties; zero `<Badge
appearance="ghost">` remains; `status-badge.tsx` keeps the 6px dot.
**Actual:** PASS - 7/7. Live: `01-users-list-1280.png` (light) vs `02-users-list-1280-dark.png`
(dark) - the "Active" status pill and every role pill are legible in both themes now, where T1's
own evidence (`23-evidence/T1/01-users-list-1280-dark.png`) documented the SAME surface with
invisible text in dark.
**Remarks:** Kept `lg` size (proven needed - `status-badge.tsx`'s `StatusBadgeProps.size` includes
`'lg'`, and 6 dead Metronic demo card partials under `app/components/partials/cards/**` - zero
real importers, confirmed by grep, slated for T7 deletion - pass it too, so removing it would have
broken the type even though nothing renders them); dropped `xs` (zero call sites anywhere). Only
ONE real `appearance="ghost"` site existed outside `account/**` demo routes -
`app/(protected)/account/security/allowed-ip-addresses/components/ip-addresses.tsx` (itself part
of the Metronic `account/security/*` demo subtree slated for T7 deletion, not the REAL
`/account/security` feature) - migrated to `appearance="outline"`. Kept the existing
`shape="circle"` auto-solid convenience (a caller that omits `appearance` on a count badge gets
the solid fill it always had - `resource-list.tsx`'s selection-count pill and the omnichannel
unread badge both rely on this without passing `appearance` explicitly; verified live no visual
regression on either).

### AC-DLA-12 - Tabs default `line` + scroll + mask + segmented-keeper inventory `[FE][T]`

**Scenario:** Given `TabsList`, when no `variant` is passed, then it renders as an underline
(`line`) that scrolls horizontally with a hidden scrollbar and a right-edge mask on overflow;
given a genuine 2/3-option segmented switch built on `TabsList`, then it pins `variant="default"`
explicitly and is the ONLY kind of site that does.
**Steps:** `npx vitest run components/ui/tabs.inventory.test.ts`; browser: user record tabs,
workflow editor tabs (1280 and 375).
**Expected:** both cva blocks + the context default to `'line'`; base class carries
`overflow-x-auto [scrollbar-width:none]` + the `data-fade` mask; exactly the recorded keeper set
pins `variant="default"`, nowhere else does.
**Actual:** PASS - 7/7. Live: `03-user-record-1280.png` (Profile/Security/Activity underlined),
`08-workflow-editor-1280.png` + `18-workflow-editor-375.png` (Editor/Logs/Settings/Versions
underlined, scrolling not wrapping at 375).
**Remarks - AC/plan ruling on the "resource-list Active|Trashed, card/list toggle" keepers named
in AC-DLA-12 and plan section 3.2:** grepped and confirmed `resource-list.tsx`'s Active|Trashed
control and its card/list view toggle are BOTH built on `ToggleGroup`/`ToggleGroupItem`
(`components/ui/toggle-group.tsx`), not `TabsList` - they were never affected by the `TabsList`
default flip and have no `variant` prop to pin. This is a genuine mismatch between the AC/plan
text (written assuming a different implementation) and this codebase's actual primitives - not a
gap in this slice's work, since there is nothing on those two controls FOR a `TabsList`-scoped AC
to change. The inventory instead greps the whole tree for real `<TabsList variant="default">`
sites and finds exactly two genuine 2/3-option switches: `autocount-formula-builder.tsx`
(Formula|Testing mode toggle) and `app/(protected)/omnichannel/inbox/components/thread-list.tsx`
(All|Mine|Unassigned filter) - both pinned, both proven the ONLY sites via the inventory's
tree-wide negative assertion. `conversation-drawer.tsx`'s Messages|Activities `TabsList` was
judged a navigational content-tab strip (same category as `resource-form`'s record tabs), not a
segmented switch, so it was left unpinned and now renders `line` like every other tab strip.

### AC-DLA-13 - DataGrid defaults + scroller + pinned column + tabular-nums + no-ScrollArea `[FE][T]`

**Scenario:** Given `DataGrid`, when no `tableLayout` override is passed, then `headerSticky`/
`columnsResizable`/`columnsMovable` default true; given the grid's own content, when it exceeds
the container, then ONLY the grid's own scroller scrolls (never the page) with a right-edge fade;
given a phone viewport, then the first non-select column pins left; given the resize handle, then
it captures the pointer; given any list, then zero wrap `DataGridTable*` in a `ScrollArea`.
**Steps:** `npx vitest run components/ui/data-grid.inventory.test.ts`; browser: Users list at 1280
and 375 (scrolled).
**Expected:** 8/8 assertions (added 1 live-caught regression assertion beyond the original 7);
live proof of a genuinely scrolling grid with a pinned first column and a page that does NOT
scroll sideways.
**Actual:** PASS after two live-caught fixes - 8/8. Live: `12-users-list-375.png`,
`13-users-list-375-grid-scrolled.png` (User column pinned, Joined column scrolled into view,
`document.documentElement.scrollWidth === window.innerWidth === 375` confirmed via `agent-browser
eval` before AND after scrolling the grid to `scrollLeft: 400`).
**Remarks - two real bugs found live, not by any test (jsdom has no real layout):**
1. **The whole page scrolled sideways, not the grid.** `CardTable` (the grid's usual ancestor) is
   `display: grid`; a grid item defaults to `min-width: auto` and refuses to shrink below its
   content's intrinsic width. My new scroller wrapper (and the `DataGridTableDnd`/
   `DataGridTableDndRows` variants' own pre-existing `<div className="relative">` wrapper, one
   level further out) never actually clipped as a result. Fixed with `min-w-0` on all three
   grid-item wrapper divs; pinned by a new inventory test.
2. **The mobile pin computed `position: relative`, not `sticky`, even after fix 1.** A byte-level
   diff of the compiled CSS found the row-select stripe's PRE-EXISTING compound selector
   (`[&_>:first-child]:relative>:first-child`, applied whenever `enableRowSelection` is true -
   every real list) outranks a plain `.max-sm\:sticky` class by CSS specificity (one class + one
   pseudo-class beats one class) regardless of source order or the responsive media wrapper.
   Fixed with Tailwind's `!` (important) suffix on every `MOBILE_PIN_CLASS` declaration. Also
   found and removed a second, independent cause while investigating: `DataGridTableDnd`'s
   dnd-kit `style` objects hardcoded `position: 'relative'` unconditionally on EVERY header and
   body cell whenever `columnsMovable` is true (`resource-list.tsx`'s default, so every real
   list) - an inline style always wins over ANY class including a responsive variant, defeating
   the pin outright regardless of the `!important` fix. Removed as dead weight (the base
   `relative` utility class the cell already carries provides the identical value).
3. `columnResizeMode: 'onChange'` (named in the AC text as a "DataGrid default") is a
   `useReactTable` construction option, not a `DataGridProps` field - `resource-list.tsx` (the
   real caller) already set it explicitly before this slice; confirmed unchanged, no action
   needed.
4. The `min-width` sizing on the table itself uses a JS-computed `getTotalSize()` pixel value
   (matching Sorento's LATER, bug-fixed implementation) rather than the plan text's literal
   `min-w-max` - `min-w-max` is meaningless on a `table-layout: fixed` table (fixed layout ignores
   content by design; Chrome resolves `max-content` to an "infinite" sentinel and scales every
   column to fill it), which is exactly the failure mode Sorento's own comment on the file
   documents. Implementation detail, not an AC wording change.
5. `resource-list.tsx` was wrapping its `DataGridTableDnd`/`DataGridTableDndRows` render in a
   Radix `<ScrollArea><ScrollBar orientation="horizontal"/></ScrollArea>` - exactly the anti-pattern
   AC-DLA-13's own "zero list wraps DataGridTable in a ScrollArea" clause bans (`ScrollArea`'s
   viewport is `display: table`, which shrink-fits and never reports an overflow, so the grid
   could never actually scroll sideways there either). Removed; the grid's own scroller is now
   the only scrollport. This is the one `components/platform/**` edit beyond the "pin only"
   allowance in the brief, made because AC-DLA-13's own inventory clause can only pass with it
   fixed, and it is inseparable from the primitive work (the primitive's new scroller and the
   removed wrapper are the same bug from two ends).

### AC-DLA-14 - `rowHref` link semantics + prefetch-once + active: + transition-opacity `[FE][T]`

**Scenario:** Given `DataGrid` `rowHref`, when a row is clicked/Enter-Space'd/middle-clicked/
hovered, then it behaves as a real link (push, new tab, prefetch-once); given a cell with its own
control, then clicking it never navigates the row; given neither `rowHref` nor `onRowClick`, then
no pointer cursor and no link role.
**Steps:** `npx vitest run components/ui/data-grid-table.rowHref.test.tsx`.
**Expected:** 7/7 assertions (role=link + tabIndex, click pushes, Enter/Space push, middle-click
opens a new tab via `window.open` not `push`, hover prefetches exactly once, a nested control's
click does not navigate, neither prop = no link role and no `cursor-pointer`).
**Actual:** PASS - 7/7.
**Remarks:** `role="link"` is what AC-DLA-14 explicitly asks for, quoted directly in this slice's
brief - implemented as literally specified. Worth flagging: Sorento's OWN later revision
(`origin/integration/ui-motion-round2`, `LinkableBodyRow`) deliberately REMOVED `role="link"` from
this exact pattern, with a comment explaining an explicit ARIA role REPLACES the implicit `row`
role, so a linkable `<tr>` stopped being a `row` to assistive tech and `getAllByRole('row')`
broke in their own test suite. This repo's AC text was written without visibility into that later
reversal. Implemented per the AC as written (contract wins); flagged under "AC wording I flagged"
below rather than silently deviating. The capability is NOT yet wired into any real list
(`resource-list.tsx` still passes `onRowClick`, unchanged) - that wiring is explicitly T4's job
per the brief ("do NOT rewire row navigation to `rowHref`, that is T4").

### AC-DLA-15 - `isPlaceholderData` dim + pagination gating `[FE][T]`

**Scenario:** Given `DataGrid` `isPlaceholderData`, when true, then the body dims (`opacity-60`)
and the pagination strip stays mounted and interactive; given `isLoading`, then skeleton rows
render ONLY when there are zero rows to show.
**Steps:** `npx vitest run components/ui/data-grid-placeholder.test.tsx`.
**Expected:** 5/5 assertions (body dims + rows still render, no skeleton while
`isPlaceholderData`, skeleton only on a genuine first load, empty state once settled with zero
rows, pagination's own skeleton gate matches).
**Actual:** PASS - 5/5.
**Remarks:** `DataGridPagination`'s own skeleton gate changed from bare `isLoading` to
`isLoading && !isPlaceholderData && recordCount === 0` - reads `isPlaceholderData` off the
`DataGridProps` exposed via `useDataGrid()`'s `props` key (not a new context field). Not yet wired
into `use-resource-list.ts`/`ResourceList` (T4's job, per plan section 3.4: "keep `rows` while
`isLoading`... expose `isPlaceholderData`... `ResourceList` forwards it").

### AC-DLA-16 - Tooltip bare Root + ONE provider 700/300 `[FE][T]`

**Scenario:** Given `tooltip.tsx`, when `Tooltip` renders, then it is a bare Radix `Root` with no
internal provider; given the app, then exactly one `TooltipProvider` (700ms delay, 300ms skip) is
mounted, in `providers/tooltips-provider.tsx`; given tooltip content, then it animates opacity
only, no `zoom-in-95`.
**Steps:** `npx vitest run providers/tooltips-provider.test.tsx`; browser: My Account page info
tooltip.
**Expected:** 4/4 assertions; live 700ms-delay + opacity-only proof.
**Actual:** PASS - 4/4. Live: `10-tooltip-700ms-1280.png` + the DOM-polling proof in the README
(absent at ~300ms, present at ~900ms, class list has `duration-(--duration-fast) animate-in
fade-in-0` and no zoom/slide keyframes).
**Remarks:** Making `Tooltip` a bare Root (removing its previous auto-wrap) broke 2 EXISTING test
files that rendered a `<Tooltip>`-using component with no provider in their own tree (`app/
(protected)/account/page.test.tsx`, `components/platform/rule-builder/rule-builder.test.tsx`) -
both fixed by wrapping their local `render()` helper in `TooltipsProvider`, a one-time cost since
those are the only two component tests that render a live `<Tooltip>` without their own wrapper
(full-suite grep + the green 182/182 file run confirms no others). `theme-provider.tsx` and
`query-provider.tsx` both had a duplicated `'use client';'use client';` pragma at their top,
fixed in passing while editing these files (zero behavioural change, harmless leftover from an
earlier generation pass).

### AC-DLA-17 - Toaster top-center + closeButton `[FE][T]`

**Scenario:** Given `<Toaster>`, when mounted, then it renders `position="top-center"` and
`closeButton`; given `query-provider.tsx`'s error toast, then it no longer passes a per-call
`position`.
**Steps:** `npx vitest run components/ui/sonner.test.tsx`; browser: DOM inspection of the mounted
Toaster.
**Expected:** 2/2 assertions; live `data-y-position="top" data-x-position="center"` proof.
**Actual:** PASS - 2/2. Live: `11-toast-top-center-1280.png` + the `data-sonner-toaster`
attribute dump in the README (present on the mount itself, independent of an active toast, which
is the more reliable signal than timing a 4s-duration toast's screenshot).
**Remarks:** Only ONE `<Toaster/>` mount exists in the whole tree (`app/layout.tsx`), confirmed by
grep - no second Toaster to reconcile.

### AC-DLA-18 - 375 sweep: Users, a record, Settings tabs, Services, a workflow `[FE][E2E]`

**Scenario:** Given every primitive surface above, when viewed at 375, then no clipped control,
tab strips scroll, the grid scrolls sideways inside itself with the first column pinned, the
toolbar wraps.
**Steps:** `agent-browser`, real clicks from `/` for the initial 1280 pass (sidebar + row clicks),
direct URL revisit of the same nine already-click-reached routes for the 375 responsive re-check
(see the README's navigation-method note) - both widths, both themes for Users.
**Expected:** 20 screenshots, no clipped control, no console errors attributable to this slice's
diff.
**Actual:** PASS - 20/20 captured; zero new console errors (two PRE-EXISTING a11y warnings noted,
matching T1's own already-logged findings, not new). Two real bugs were caught and fixed during
this exact step (AC-DLA-13's remarks above) - which is the reason this AC exists as a live browser
check and not only a unit test suite.
**Remarks:** See `23-evidence/T2/README.md` for the full run log, including the two live-caught
bugs' before/after evidence.

### AC wording I flagged (not silently deviated from - implemented as written)

1. **AC-DLA-09's `PRESSED_CLASS` on `ContextMenuItem`/`MenubarItem`/`CommandItem`** matches
   Sorento `origin/main`'s `PRESSED_CLASS`, but Sorento's LATER revision
   (`origin/integration/ui-motion-round2`) splits these three into a separate
   `PRESSED_TRANSFORM_CLASS` (shrink only, no colour transition) specifically because animating
   the highlight colour on a KEYBOARD-navigated selection (arrow keys moving the highlight) is
   "motion on a keyboard-initiated action" - a hard-fail this very plan's own PRINCIPLES.md
   addition (T8) will codify. `DropdownMenuItem` is exempt in Sorento's own reasoning (normally
   pointer-driven, already carried `transition-colors` pre-M1). This repo's AC-DLA-09 text quotes
   `PRESSED_CLASS` (not the split variant) for all four menu-item types, so it is implemented
   exactly as written; flagging because a future motion-audit slice (T3's `/review-animations` or
   T8's hard-fail sweep) may want to revisit these three specifically against the same rule this
   plan is about to adopt for everything else.
2. **AC-DLA-14's `role="link"` on the DataGrid row** - see AC-DLA-14's Remarks above (Sorento
   reversed this exact choice after it broke `getAllByRole('row')` semantics). Implemented as
   written since the UAC is the contract.
3. **AC-DLA-12/plan 3.2's "resource-list Active|Trashed, card/list toggle" keepers** - see
   AC-DLA-12's Remarks above; these two controls are `ToggleGroup`, not `TabsList`, so there is
   nothing to pin on them. Not a gap, a mismatch between the AC/plan text and this codebase's
   actual primitives.
4. **AC-DLA-13's "min-w-max on the table"** - implemented as a JS-computed `getTotalSize()` pixel
   value instead (matches Sorento's own later bug-fixed version, not the plan's literal wording);
   see AC-DLA-13 Remarks point 4. Same observable outcome (a fade + real overflow), a strictly
   more correct implementation for a `table-layout: fixed` table.

### Definition of Done checklist (T2)

1. Every AC-DLA-09..18 verified above (`[T]` tests + the `[E2E]` agent-browser run, including two
   live-caught-and-fixed bugs). PASS.
2. `npm run lint` (touched files, 0 errors), `npm test` (`npx vitest run`, 182 files / 1559 tests,
   +67 new tests vs the pre-T2 baseline), `npm run build` all green.
3. `rm -rf .next && npm run build` before the final live check; port ownership checked
   (`lsof -p $(lsof -ti :3002) | grep cwd`) before every kill/restart across the whole slice,
   including twice mid-slice after the live-caught fixes.
4. No mock left behind (T2 has no service-trio slice - N/A). No backfill needed (primitives-only,
   no new columns). No new permission (N/A). Verified from the user's perspective at 375 AND
   1280, light AND dark (Users list), on the real prod build.
5. Two genuine bugs found live (not by any test) are documented with full root-cause + fix +
   re-verification, not silently absorbed; both are now pinned by inventory assertions so a
   regression fails the suite, not just a future live-verify pass.

**Verdict: T2 DONE.** 10/10 AC-DLA ids (09-18) PASS. Zero DEFERRED, zero FAIL. Four AC/plan wording
notes flagged above for reviewer awareness, none blocking.

---

## T2 - Fix round 1

Two reviews ran against the T2 DONE diff: `/code-review` (10 confirmed findings) and
`/review-animations` (Block, 11 items). The UAC was amended on the integration branch
(`b7f2eb7`) for AC-DLA-09/13/14/15/29/32 - re-read before starting; the amended text is quoted
inline below where it governs. All 21 findings, grouped into 19 numbered rulings (some rulings
close more than one finding - e.g. the `scale` transition bug was raised by both reviews
independently against the same line).

### A. Press mechanics

**A1 - PRESSED_CLASS's active:scale-[0.97] never eased (`/review-animations` Block: motion snaps).**
Tailwind 4 compiles `active:scale-[0.97]` to the standalone CSS `scale` property, not `transform`
- `transition-[transform,color,...]` (no `scale`) never animated it, so every pressed control
snapped instead of easing. `PRESSED_CLASS`'s transition list now includes `scale` alongside
`transform`; a new `PRESSED_TRANSFORM_CLASS` (transform-only, `transition-transform` - which
Tailwind 4 itself expands to cover `transform`/`translate`/`scale`/`rotate` as one named utility,
unlike the arbitrary `transition-[...]` bracket syntax which takes exactly what is written)
serves the roving-focus items in A2. Test: `components/ui/primitive-classes.test.ts` reads the
`transition-[...]` bracket itself and asserts `scale` is one of its comma-separated properties
(not a substring hit that could pass by accident).
**Fixed:** `components/ui/primitive-classes.ts`.

**A2 - press class assignment per control (`/code-review` + `/review-animations`: colour easing
on a keyboard-navigated item is motion-on-keyboard-action, a hard-fail).** `DropdownMenuItem`,
`ContextMenuItem`, `MenubarItem` (Radix roving focus moves `focus:bg-accent` on arrow keys) now
carry `PRESSED_TRANSFORM_CLASS`, never `PRESSED_CLASS`. `CommandItem` (keyboard-driven, 100+/day)
and `SliderThumb` (a drag is a hold, no discrete press moment) carry **no** press class at all.
Everything else (Button lg/md/icon, checkbox, switch, radio, toggle, TabsTrigger) keeps
`PRESSED_CLASS` unchanged.
**Fixed:** `components/ui/{dropdown-menu,context-menu,menubar,command,slider}.tsx`.
**Test:** `components/ui/primitive-classes.test.ts` rewritten - per-file `it.each` tables for
`PRESSED_CLASS` carriers, `PRESSED_TRANSFORM_CLASS` carriers (and NOT `PRESSED_CLASS`), and the
two no-press-class files (assert neither).
**Live:** `fixround1-06-dropdown-item-pressed-1280.png` (Actions dropdown open on a user record)
+ a computed-className check confirming the rendered `DropdownMenuItem` carries
`transition-transform` with zero `color`/`background-color`/`border-color`/`box-shadow` in its
class list. Capturing the CSS `:active` pseudo-state itself mid-press in a screenshot is a known
automation-timing limitation (the press-and-release round trip is faster than a screenshot
command's own latency) - the computed-style proof is the reliable evidence here, same as T2's
original tooltip-timing proof used DOM polling over a raced screenshot.

### B. DataGrid

**B3 - the hook half of AC-DLA-32 (amended AC-DLA-15).** `resource-list.tsx:290`'s skeleton gate
moving to `rows.length === 0` meant every shell list lost its "something is happening" feedback
during a refetch unless the placeholder-dim behaviour actually reached `ResourceList`. Per the
amended UAC ("Because that gate removes the old loading feedback, the hook half of AC-DLA-32
ships in T2"): `useResourceList` now exposes `isPlaceholderData` (`isLoading && data.length > 0`
- `data` was ALREADY staying stale during a refetch, since `setData` only ever runs on a
resolved fetch) and `loadedQuery` (the query the CURRENT rows actually came from, captured when
a fetch resolves - NOT the live `query`, which has already advanced by the time a refetch is in
flight). `ResourceList` forwards `isPlaceholderData` to `DataGrid`, and `openRow`'s
`globalIndex`/`ctx` now read `loadedQuery` instead of the live `list.page`/`list.query` - a row
clicked while stale rows are still showing (AC-DLA-15 keeps them clickable) would otherwise be
indexed against a page it is not actually on. `onRowClick` wiring is untouched (T4 does
`rowHref`).
**Fixed:** `hooks/use-resource-list.ts`, `components/platform/resource-list/resource-list.tsx`.
**Test:** `hooks/use-resource-list.placeholder.test.ts` - a fetcher that resolves on demand;
asserts rows persist across a page change, `isPlaceholderData` flips true then false, and
`loadedQuery.page` stays at the OLD page while stale rows are showing.
**Live:** `fixround1-07-list-dimmed-rows-search-1280.png` - Roles list, search box shows a
non-matching query ("zz") but the table still shows the full previous 7-role result set, visibly
dimmed, pagination strip intact. Reproduced via a `window.fetch` interception delaying only the
`/roles?...` response (the real local backend resolves in tens of milliseconds, too fast for a
screenshot's own command latency to reliably land inside the window otherwise - the delay proves
the SAME code path a slow network would exercise, not a different one).

**B4 - `headerSticky` was a no-op (`/code-review`: dead default).** The AC-DLA-13 amendment
spells this out: the scroller must be bounded (`max-h-(--grid-max-h)`, token already defined in
`config.reui.css` since T1) on the SAME element that scrolls horizontally, or `position: sticky`
has no bounded ancestor to stick inside and the header just scrolls away with everything else.
Added `tableClassNames.scroller` (default `'max-h-(--grid-max-h) overflow-y-auto'`, overridable
per list) and applied it to the one scroller div in `DataGridTableBase` alongside its existing
`overflow-x-auto overscroll-x-contain`.
**Fixed:** `components/ui/data-grid.tsx`, `components/ui/data-grid-table.tsx`.
**Test:** `components/ui/data-grid.inventory.test.ts` new assertions for the scroller class,
the `scroller?: string` prop type, and `--grid-max-h`'s existence in `config.reui.css`.
**Live:** `fixround1-01-sticky-header-scrolled-1280.png` / `fixround1-02-...-375.png` - Workflows
list narrowed to a 500px-tall viewport (its 8 rows don't overflow at a normal window height, so
the window itself was narrowed per the ruling's own suggested fallback) genuinely overflows
(`scrollHeight` 475 vs `clientHeight` 228), scrolled 200px, header still pinned at the top with a
row visibly sliding underneath it.

**B5 - mobile-pin selector generalisation (`/code-review`: hardcoded to `select`-only, breaks on
a `rowReorder` list's drag column).** `firstDataColumnIndex` now `findIndex`s the first LEAF
column whose id is not `select`/`__drag` AND whose `meta.reorderable !== false` AND
`meta.utility !== true` (a new `ColumnMeta.utility` flag, declared for a future structural
column that needs excluding without also lying about `reorderable`). `__drag` (resource-list.tsx's
row-drag grip column) already sets `meta: { reorderable: false }`, so it is excluded by the SAME
convention every fixed/action column in the app already uses - no new per-column wiring needed.
**Fixed:** `components/ui/data-grid-table.tsx`, `components/ui/data-grid.tsx` (the `utility` meta
field).
**Test:** `components/ui/data-grid.inventory.test.ts` new assertions.
**Live:** `fixround1-03-rowreorder-mobile-pin-375.png` - Ideation > Ideas (a real `rowReorder`
list), scrolled sideways: the drag-grip and select columns have scrolled off-screen, "Idea" (the
real first data column, index 2) is pinned left. A DOM check confirmed the exact header index
list (`0,1` unpinned/structural, `2` pinned = "Idea").

**B6 - pinned cell background did not match its row's hover/selected/striped state (`/code-review`:
a flat `bg-background` reads as a visual bug once the row itself tints).** The `<tr>` (both the
header row and the shared body-row class builder) now carries `group`; the pinned cell's
background is a set of `group-*:max-sm:bg-*` variants mirroring the row's own
`hover:`/`data-[state=selected]:`/`odd:` conditions, split into `MOBILE_PIN_CLASS_HEAD` (the
header row's constant `bg-muted/40`) and `MOBILE_PIN_CLASS_BODY` (hover/selected/striped, each
`!important` for the same specificity reason `position` needed it - the row-select stripe's
compound selector otherwise outranks a plain class regardless of source order).
**Fixed:** `components/ui/data-grid-table.tsx`.
**Test:** `components/ui/data-grid.inventory.test.ts` new assertions (the `group` classes present,
the `group-hover:`/`group-data-[state=selected]:`/`group-odd:` variants present).
**Live:** `fixround1-04-selected-row-pinned-cell-375.png` - Ideas list, first row selected via its
checkbox, scrolled sideways: a `getComputedStyle` check confirmed the pinned "Idea" cell's
background is OPAQUE and matches the selected tint (`rgb(247, 246, 244)`), while a neighbouring
non-pinned cell in the same row stays transparent (correctly letting the `<tr>`'s own background
show through instead).
**Known simplification (documented, not a silent gap):** the header pin's background covers only
the common `bg-muted/40` case, not every `stripped`/`headerBackground: false` permutation - noted
in a code comment; no current real list combines the mobile pin with those header variants.

**B7 - `role="link"` on the DataGrid row + outer focus ring clipped by the scroller (amended
AC-DLA-14 + `/code-review`).** The amended UAC states plainly: `role="link"` "would remove the row
from the table structure for assistive tech" - dropped. `tabIndex={0}`, click, Enter/Space,
middle-click and hover-prefetch are all unchanged; the real `<a href>` lands in T4. The scroller
clips anything an outer ring/offset would draw past the row's own box, so the linked row now
carries `focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring` instead.
**Fixed:** `components/ui/data-grid-table.tsx`.
**Test:** `components/ui/data-grid-table.rowHref.test.tsx` rewritten off `getAllByRole('link')`
onto `getAllByRole('row')` (skipping the header row) + `tabindex` assertions; a new test asserts
the inset-ring classes are present; the "neither prop set" test now also asserts no `tabindex`
attribute at all (was previously proven only via the absent link role).

**B8 - placeholder-dim transition was conditional, so the RESTORE snapped (amended AC-DLA-15:
"the transition-opacity declaration is unconditional so the restore eases too, never snaps").**
`transition-opacity duration-(--duration-fast) ease-(--ease-standard)` moved to always apply on
`DataGridTableBody`'s `<tbody>`; only `opacity-60` itself stays conditional on
`isPlaceholderData`.
**Fixed:** `components/ui/data-grid-table.tsx`.
**Test:** covered by the existing `data-grid-placeholder.test.tsx` suite (unchanged assertions,
now reading the always-present transition class).

**B9 - row transition property list + a redundant reduced-motion override (amended AC-DLA-14:
"`transition-[background-color,opacity] duration-(--duration-fast) ease-(--ease-standard)`... no
`motion-reduce:transition-none`, the tokens already collapse").** The linked-row transition now
lists `background-color` (hover/active) AND `opacity` (T5's future pending-row dim) explicitly,
replacing the earlier bare `transition-opacity`; the per-component `motion-reduce:transition-none`
override was removed - T1's reduced-motion preference block already collapses every
`duration-(--duration-*)` token to ~0, so the per-component copy was dead weight duplicating a
global rule.
**Fixed:** `components/ui/data-grid-table.tsx` (`dataGridBodyRowClass`).

**B10 - the right-edge fade toggled by mount/unmount (grid) or `mask-image` (tabs) (`/review-animations`
Block: abrupt property, no interruptible transition).** Amended AC-DLA-14: "always mounted... toggles
`opacity` over `--duration-fast`, never mount/unmount or `mask-image`." Both surfaces now render an
always-mounted `aria-hidden` overlay div (`opacity-0 data-[fade=true]:opacity-100
transition-opacity duration-(--duration-fast)`); `tabs.tsx`'s `TabsList` gained a wrapping
`<div className="relative">` to host its own copy (the CSS `mask-image` toggle it previously
carried directly on the scrollable element is gone).
**Fixed:** `components/ui/data-grid-table.tsx`, `components/ui/tabs.tsx`.
**Test:** `components/ui/data-grid.inventory.test.ts` + `components/ui/tabs.inventory.test.ts` -
both assert no conditional `{isFading && (` / no `[mask-image:` remains, and the always-mounted
`data-fade={isFading}` + opacity-transition classes are present.

**B11 - the overflow-measure scroll handler was unthrottled and only watched the scroller's own
box, missing content-width changes (`/code-review` + `/review-animations`: excess re-renders +
a resize/reorder that changes overflow state without the fade updating).** `useHorizontalOverflow`
now rAF-guards its scroll/resize handlers (`requestAnimationFrame`-coalesced, at most one measure
per frame) and additionally `ResizeObserver`s the scroller's FIRST CHILD (the table or the tab
strip itself) alongside the scroller box - a column resize/hide/reorder or a late-added tab
changes the child's content width while the scroller's own box stays the same size.
**Fixed:** `hooks/use-horizontal-overflow.ts`.
**Live:** implicitly exercised by every DataGrid/Tabs screenshot in this round and the original
T2 run; no dedicated new screenshot (a perf/correctness fix with no distinct visual state).

**B12 - the "no ScrollArea around DataGridTable" inventory only scanned `components/platform/**`
(`/code-review`: the real offenders documented in AC-DLA-13 live under `app/**`, unscanned).**
Widened the walk to `app/**` too, with an explicit 14-file allowlist (all `account/**` Metronic
demo pages + the `demo1/light-sidebar` showcase team - dead code slated for wholesale deletion in
T7, AC-DLA-57/60) - a new offender anywhere else in either tree now fails the build.
**Fixed:** `components/ui/data-grid.inventory.test.ts` (test-only; no production code in the
allowlisted files was touched, per the brief).

### C. Other primitives

**C13 - TabsTrigger's outer focus ring was clipped by the tab strip's own `overflow-x-auto`
(`/code-review`).** `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2` ->
`focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring focus-visible:ring-offset-0`
on both the base class and the `button` variant compound (which duplicated - and without the fix
would have RE-introduced - the outer ring for `variant="button"` tabs specifically, since a later
compound-variant class wins a same-specificity tie).
**Fixed:** `components/ui/tabs.tsx`.
**Test:** `components/ui/tabs.inventory.test.ts` new assertion.
**Live:** `fixround1-05-tabs-keyboard-focus-ring-1280.png` - Users record, Security tab focused
via `agent-browser focus` (confirmed `:focus-visible` true via `matches(':focus-visible')`, not
just a class-string check); the ring renders as a clean inset outline hugging the tab pill, no
clipping. The conversation-drawer tabs use the identical shared `TabsTrigger` component, so this
is the same code path; that specific surface was not independently re-verified live in this pass
(the drawer did not open reliably during the attempt - unrelated interaction nuance, not
re-investigated given the shared-component proof already covers the mechanism).

**C14 - overlay blur was 12px (`backdrop-blur-md`), amended AC-DLA-09 specifies 8px
(`backdrop-blur-sm`) (`/review-animations`: visual regression vs the design spec).**
**Fixed:** `components/ui/primitive-classes.ts` (`OVERLAY_CLASS`, `OVERLAY_CLASS_STATIC`).
**Test:** `components/ui/primitive-classes.test.ts` new assertion (`backdrop-blur-sm` present,
`backdrop-blur-md` absent).

**C15 - `badge.tsx`'s JS-level `shape="circle"` appearance override (`/code-review`: a
component silently reinterpreting a caller's explicit prop is a footgun - the default should be
data-driven by the CALLER, not inferred from `shape`).** Removed the `effectiveAppearance`
special-case entirely; `resource-list.tsx`'s selection-count pill and the omnichannel unread
badge (the two real callers that relied on it) now pass `appearance="default"` explicitly.
**Fixed:** `components/ui/badge.tsx`, `components/platform/resource-list/resource-list.tsx`,
`app/(protected)/omnichannel/inbox/components/thread-list.tsx`.
**Verified no other real (non-demo) `<Badge shape="circle">` caller relies on the removed
default** - grepped every `shape="circle"` site in the tree; the rest are either `<Button
shape="circle">` (an unrelated prop on a different component), demo2/3/5/9 dead layouts, or
`search-users.tsx`'s Badge, which already passes `appearance="light"` explicitly.

**C16 - the AC-DLA-11 ghost->outline migration on `ip-addresses.tsx` turned a bare status dot
into a visible pill (`/code-review`: a visual regression the badge sweep must not leave behind,
even on a file slated for T7 deletion).** Replaced the `Badge`+`BadgeDot` wrapper with a bare
`<span className="size-1.5 rounded-full bg-[currentColor] opacity-75">` (the same visual as
`BadgeDot` itself, minus the pill container) - restores the original ghost look (no border, no
background) without reintroducing the deleted `appearance="ghost"`.
**Fixed:** `app/(protected)/account/security/allowed-ip-addresses/components/ip-addresses.tsx`.

### D. Gate, evidence, docs

**D17 - gate + evidence.** `npm run lint` (touched files, 0 errors), `npm test` (183 files / 1572
tests, +11 vs the T2-DONE baseline), `rm -rf .next && npm run build` (green), restarted :3002
(port ownership confirmed via `lsof` before kill). 7 new `fixround1-NN-*.png` screenshots (listed
under each finding above) plus this section serve as the evidence + report; `23-evidence/T2/README.md`
is left as the original T2 run log (the fix-round screenshots and their captions live in this
report to avoid duplicating narrative in two places).

**D18 - this section** maps all 21 findings (10 code-review + 11 animation) to what changed, with
the `/review-animations` Block reasons named inline under each relevant item (A1, A2, B6, B10,
B11, C14) and how each was cleared.

**D19 - commits.** Small, one per ruling group (A, B-scroller, B-hook, B-pin/bg, B-inventory, C,
docs), each trailer exactly `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

### Definition of Done checklist (T2 fix round 1)

1. All 19 rulings (21 findings) addressed, each with a code change, a test, or both; 6 have live
   `agent-browser` evidence (the ones with a genuinely new visual/behavioural state); the rest
   (B8, B9, B11, B12, D-items) are covered by existing or new unit/inventory tests plus the
   unchanged full-suite live pass.
2. `npm run lint`, `npm test` (183/183 files, 1572/1572 tests), `npm run build` all green.
3. `rm -rf .next && npm run build` before the final live check; port ownership confirmed via
   `lsof -p $(lsof -ti :3002) | grep cwd` before every kill/restart in this round.
4. No mock left behind, no backfill needed, no new permission - primitives-only fix round.
5. Verified from the user's perspective at 375 AND 1280 on the real prod build, including two
   genuinely hard-to-reproduce states (a vertically overflowing sticky-header grid, and a
   dimmed-rows-during-refetch frame) caught via legitimate reproduction techniques (a narrowed
   viewport height; a `window.fetch` response-delay injected purely to widen an otherwise-too-fast
   local-network timing window, not a different code path than a slow real network would exercise).

**Verdict: T2 fix round 1 DONE.** 19/19 rulings (21/21 findings) resolved and re-verified; full
gate green.

## T2 - Fix round 2

Amended UAC re-read for AC-DLA-03/09/10/13/14/15/29 (integration checkout, today's date). 8
findings from the round-2 review, addressed as 8 rulings.

**1 - BLOCKER: pinned body column painted OVER the sticky header on scroll (<=640px).**
`MOBILE_PIN_CLASS_HEAD` (the sticky `<thead>` and its mobile-pinned header cell) and
`MOBILE_PIN_CLASS_BODY` (pinned body cells) shared ONE z-scale step (`--z-sticky-content`), so
paint order between them was DOM-order-dependent, not z-order-dependent - a pinned body cell
scrolling past the header could paint on top of it (the round-1 evidence's own
`fixround1-02-sticky-header-scrolled-375.png` shows exactly this: a body cell rendered inside the
header row). Added `--z-sticky-header: 6` to `css/config.reui.css` (one step above
`--z-sticky-content: 5`, both below `--z-header`), doc comment explains the relationship (no
stale `--z-sticky-content-corner` mention existed in this file to remove - it lives only in
`design-tokens.test.ts`'s own comment, about an unrelated doubly-pinned-cell token, left as is).
`data-grid.tsx`'s `headerSticky` default and `data-grid-table.tsx`'s `MOBILE_PIN_CLASS_HEAD` now
both reference `z-(--z-sticky-header)`; `MOBILE_PIN_CLASS_BODY` stays on `--z-sticky-content`.
**Fixed:** `css/config.reui.css`, `components/ui/data-grid.tsx`, `components/ui/data-grid-table.tsx`.
**Test:** `css/design-tokens.test.ts` (`--z-sticky-header` defined as 6, ordered between
sticky-content and header); `components/ui/data-grid.inventory.test.ts` (thead references
`z-(--z-sticky-header)` not `z-(--z-sticky-content)`; `MOBILE_PIN_CLASS_HEAD`/`_BODY` reference the
right step each).
**Live:** `fixround2-01-sticky-header-pinned-375.png` (Workflows list, window narrowed to ~500px
tall so the 8 rows genuinely overflow - `scrollHeight` 475 vs `clientHeight` 228 - scrolled BOTH
directions, `scrollTop:150/scrollLeft:400`; a `getComputedStyle` check confirmed `thead` z-index 6,
every mobile-pinned body cell z-index 5) + `fixround2-01b-sticky-header-vertical-only-375.png`
(same list, vertical scroll only, scrollLeft 0 - a clean, unambiguous shot of the header staying
crisp with a row scrolled/clipped cleanly underneath, no bleed into the header text) +
`fixround2-02-sticky-header-scrolled-1280.png` (1280 re-check, same list, `scrollTop:200` -
`thead` z-index 6 confirmed, header intact with a partial row clipped just above it).

**2 - `useHorizontalOverflow` only ever watched `el.firstElementChild`, which for `Tabs` is the
first TRIGGER, not the strip.** `TabsList` refs the list element itself (`ref={mergedRef}` on
`TabsPrimitive.List`), so "the strip's own first child" is a single tab, not a stand-in for the
whole strip's content width - a resize/rename/reorder among the OTHER triggers went unnoticed.
Now every child of the scroller is `ResizeObserver`'d (`for (const child of Array.from(el.children))
observer.observe(child)` - `Array.from` per the house `downlevelIteration` rule for iterating a
`HTMLCollection`), AND a `MutationObserver` on the scroller itself (`childList`) re-measures AND
re-observes on any add/remove - so a tab added/removed/relabelled, or a DataGrid column
reordered, keeps the fade accurate without a remount.
**Fixed:** `hooks/use-horizontal-overflow.ts`.
**Test:** new `hooks/use-horizontal-overflow.test.tsx` (3 cases, fake `ResizeObserver` spy +
jsdom's real `MutationObserver`) - every initial child is observed (not just the first); a child
added after mount via rerender is re-observed; a mutation triggers a real re-measure
(`scrollWidth`/`clientWidth` stubbed on the element, `isOverflowing` flips from false to true once
a rerender both grows the content and a `requestAnimationFrame` flush runs).

**3 - the pinned cell's striped legs (`group-odd:max-sm:bg-muted/90`/
`group-hover:group-odd:max-sm:bg-muted`) were unconditional, but a row only stripes when
`tableLayout.stripped` is true.** Split them into a separate `MOBILE_PIN_CLASS_BODY_STRIPED`
constant, applied at the usage site only when `isMobilePinned && props.tableLayout?.stripped` -
mirrors exactly how the ROW itself gates its own `odd:bg-muted/90` class
(`dataGridBodyRowClass`'s `props.tableLayout?.stripped && 'odd:bg-muted/90 ...'`), so a
non-stripped list's pinned cell no longer darkens on odd rows for no reason.
**Fixed:** `components/ui/data-grid-table.tsx`.
**Test:** `components/ui/data-grid.inventory.test.ts` new assertion (the gated expression is
present verbatim).

**4 - `rowHref` returning `'#'`/`''` (AC-DLA-29's documented opt-out sentinel) was only handled by
the FALSY branch (`''`); `'#'` is truthy, so a sentinel row still rendered as a full
`LinkableDataGridTableBodyRow`** (tabIndex, click-to-push to literally `'#'`, prefetch of `'#'`,
pointer cursor) - the opposite of "no detail page for this row". New `hasRowHref(href): href is
string` type guard (`Boolean(href) && href !== '#'`) replaces the plain truthiness check in
`DataGridTableBodyRow`, so a sentinel row takes the plain (non-link) branch. The plain branch's
own cursor computation also had to change: it previously read `props.rowHref` (the LIST-level
callback, always truthy once configured) rather than the per-row resolution, so an opted-out row
still showed `cursor-pointer`. `dataGridBodyRowClass` gained a 4th param `unknownHref` (default
false) - the skeleton row (which has no `row.original` to resolve `rowHref` against yet) passes
`true` to keep its pre-existing "this list navigates" cursor heuristic; a real resolved row passes
its actual `isLinkRow`, so cursor-pointer now correctly tracks the SPECIFIC row's opt-out.
**Fixed:** `components/ui/data-grid-table.tsx`.
**Test:** `components/ui/data-grid-table.rowHref.test.tsx` - `it.each(['#', ''])` (no tabIndex, no
cursor, click does not push) + a mixed-list case (one row sentinel, one row real - only the
sentinel row opts out, the other still navigates).

**5 - stale comment in `badge.tsx` claimed circle badges (`shape="circle"`) default to the solid
`appearance="default"` fill.** They do not - `defaultVariants.appearance` is `'light'` for every
shape (removed entirely in fix round 1's C15, which made the default caller-driven); a solid
circle badge requires the caller to pass `appearance="default"` explicitly, as the two real
callers (`resource-list.tsx`'s selection-count pill, the omnichannel unread badge) already do.
Corrected the comment to state the caller-driven contract instead of the old JS-level override
that no longer exists.
**Fixed:** `components/ui/badge.tsx` (comment only, no behaviour change).

**6 - animation-review nits (4 items, one per bullet in the brief).**
- `MOBILE_PIN_CLASS_BODY` gained `transition-[background-color] duration-(--duration-fast)
  ease-(--ease-standard)` so the pinned cell's background eases with its row's
  hover/select/stripe change instead of snapping (it already inherited the row's OWN transition
  via nothing - the pinned cell is a `<td>`, a sibling of the row, not a child that inherits the
  row's `transition-[...]` class).
- `group-hover:` legs: investigated whether to wrap them in `[@media(hover:hover)]:`. Checked
  `css/` - **no project override exists**; Tailwind v4's OWN default `hover` variant already
  compiles to `&:hover { @media (hover: hover) { ... } }` (confirmed by inspecting
  `node_modules/tailwindcss/dist/lib.js`'s variant registration), so `group-hover:` here is
  ALREADY hover-capable-gated with zero code change needed - added a code comment recording this
  so a future pass doesn't re-litigate it or add a redundant arbitrary-variant wrapper.
- Named `ease-(--ease-standard)` on both edge-fade transitions (`data-grid-table.tsx`'s
  `data-grid-fade`, `tabs.tsx`'s `tabs-fade`) - previously `transition-opacity
  duration-(--duration-fast)` with no explicit easing (inherited Tailwind's default curve, which
  happens to already BE the house curve per `config.reui.css`'s
  `--default-transition-timing-function`, but naming it explicitly on every hand-tuned transition
  is the house convention every other transition in this diff follows).
- Retitled the stale `modal-defaults.test.tsx` test name from `backdrop-blur-md` to
  `backdrop-blur-sm` (the assertion body never checked the literal blur value - source has read
  `backdrop-blur-sm` since fix round 1's C14 - only the test's OWN title string was stale).
**Fixed:** `components/ui/data-grid-table.tsx`, `components/ui/tabs.tsx`,
`components/ui/modal-defaults.test.tsx`.
**Test:** `components/ui/data-grid.inventory.test.ts` + `components/ui/tabs.inventory.test.ts`
regexes updated to include `ease-(--ease-standard)` in the expected fade class string.

**7 - `npx prettier --write` on the two files the brief named as newly unformatted.** Confirmed
first that `npx prettier --check` fails on effectively every file in the tree at `HEAD` (prettier
is not lint-gated in this repo - `npm run format` is opt-in, `npx eslint` is the actual build
gate) - so "already unformatted before this branch" is the norm, not the exception, and reformatting
broadly would inflate this diff with unrelated churn. Ran `--write` on exactly the two named files:
`hooks/use-horizontal-overflow.ts` (this round's own edit had drifted from the 80-col wrap) and
`app/(protected)/account/security/allowed-ip-addresses/components/ip-addresses.tsx` (fix round 1's
C16 bare-dot fix left one line over 80 cols, and the import order had drifted - `Badge` was
sorted ahead of `cn` instead of after per the `@ianvs/prettier-plugin-sort-imports` groups).
**Fixed:** `hooks/use-horizontal-overflow.ts`,
`app/(protected)/account/security/allowed-ip-addresses/components/ip-addresses.tsx` (formatting
only, no behaviour change - both re-ran through the affected test suites afterward).

**8 - evidence README step 6 mis-recorded the scrim as `backdrop-blur-md`.** The T2 original run
log (step 6) logged the OLD pre-fix-round-1 blur value even though the live overlay was already
`backdrop-blur-sm` by the time that run executed (fix round 1's C14 changed the source before the
evidence doc was corrected) - a copy-paste-from-memory error, not a re-verification of a stale
build. Corrected the line to `bg-(--scrim) backdrop-blur-sm` with a note explaining the
discrepancy's origin so a future reader doesn't wonder whether the value regressed.
**Fixed:** `documentation/plans/sprint-4/23-evidence/T2/README.md` (doc only).

### Gate

`npm run lint` (0 errors, 3 pre-existing warnings unrelated to this diff), `npm test` (184 files /
1581 tests, +1 file / +9 tests vs the fix-round-1 baseline of 183/1572), `rm -rf .next && npm run
build` (green, run twice - once mid-fix to catch the `Array.from` downlevel-iteration build error
on finding 2's `for...of HTMLCollection`, once final), restarted `:3002` (port ownership confirmed
via `lsof -p $(lsof -ti :3002) | grep cwd` before every kill, per the worktree rule).

### Definition of Done checklist (T2 fix round 2)

1. All 8 findings addressed, each with a code change + a test (or, for 5/7/8, a doc/comment-only
   fix where no behaviour changed) - 3 with new live `agent-browser` evidence (finding 1, the
   BLOCKER, at both 375 and 1280).
2. `npm run lint`, `npm test` (184/184 files, 1581/1581 tests), `npm run build` all green.
3. `rm -rf .next && npm run build` before the final live check; port ownership confirmed via
   `lsof -p $(lsof -ti :3002) | grep cwd` before the restart.
4. No mock left behind, no backfill needed, no new permission - primitives-only fix round.
5. Verified from the user's perspective at 375 AND 1280 on the real prod build: the BLOCKER's
   fix reproduced live in the SAME narrowed-viewport-height technique fix round 1 used (a
   legitimate reproduction, not a different code path than a real short window would exercise),
   confirming the header now paints correctly above a scrolling pinned column at both sizes.

**Verdict: T2 fix round 2 DONE.** 8/8 findings resolved and re-verified; full gate green.

## T2 - Fix round 3 (pin polish)

Branch `sprint-4/23-T2b-pin-polish` off `sprint-4/23-design-language-alignment` (integration branch
at `8cac6ec`, T2 already merged in). Two defects visible in fix round 2's own evidence screenshot
(`fixround2-01-sticky-header-pinned-375.png`, Workflows list at 375 scrolled sideways): the pinned
HEADER cell was translucent (scrolled-under header text showed through it) and the pinned BODY
cell's content wasn't reliably clipped (long names bled into the next column). Both diagnosed via
`agent-browser eval` on the real DOM (`getComputedStyle`) before any code change, per the brief.

**1 - the pinned HEADER cell was translucent (`bg-muted/40`), letting the scrolled-under header
text of another column show straight through it.** Live DOM check confirmed the exact mechanism:
`getComputedStyle` on the pinned `th` returned `background-color: oklab(... / 0.4)` - the SAME
`bg-muted/40` the header ROW paints underneath every `th` (itself correct - the row blends into
its ancestor card). But the pinned cell has no such ancestor at those screen pixels; the columns
sliding underneath it on scroll are unrelated data, not a backdrop. `MOBILE_PIN_CLASS_HEAD` now
uses solid `bg-muted` (opaque) instead of `bg-muted/40`. The z-index/size diagnosis from the brief
turned out clean on inspection - `z-index: 6` already matched the sticky `thead` (fix round 2's
own fix) and the pinned `th`'s rendered width (`240px`) already matched its column exactly
(`props.tableLayout.width` defaults to `'fixed'`, every real list uses the default) - only the
opacity was wrong.
**Fixed:** `components/ui/data-grid-table.tsx` (`MOBILE_PIN_CLASS_HEAD`).
**Test:** `components/ui/data-grid.inventory.test.ts` - new assertion the declaration contains
`max-sm:bg-muted!` and not `bg-muted/40`.
**Live:** `fixround3-01-workflows-375-h-scroll-light.png` (scrolled to `scrollWidth`, "Name" header
fully opaque, no "Published"/other-column text bleeding through) +
`fixround3-02-workflows-375-midscroll-light.png` (a partial scroll position, same result).

**2 - the pinned BODY cell's content overflowed into the neighbour column** ("Fan-out edges
1788080274192" running into the next cell's text with no separation). Root cause: a
`position: sticky` table cell does not reliably clip its own overflowing content via
`overflow: hidden` - a real, documented cross-browser rendering gap on sticky cells inside a
table. The cell's content here is a `flex flex-col` wrapper (title + `ClampedText` subtitle), not
a bare text node; the `nowrap` the cell's own conditional `truncate` class sets is INHERITED down
into that flex box, so a long title refuses to wrap and can grow past the cell's box - and the
sticky `<td>`'s `overflow: hidden` does not reliably clip that overflow (confirmed via live
`getBoundingClientRect` measurement across scroll positions). Fix: wrap the pinned body cell's
`children` in a plain, NON-sticky `<div className="max-sm:overflow-hidden max-sm:truncate">` -
an ordinary block box establishes its own clip that is not subject to the sticky-cell bug,
applied ONLY when `isMobilePinned` so every other cell's DOM/layout is untouched. Also converted
the two lists exercised by this evidence run (Workflows' `name` column, Users' `user` column) to
render their primary label through `ClampedText` (already used for the WORKFLOWS subtitle, not
yet the title) rather than a bare `<span>`, so the truncated text stays recoverable via ClampedText's
tooltip-on-real-overflow contract, not just visually clipped.
**Fixed:** `components/ui/data-grid-table.tsx` (`MOBILE_PIN_CONTENT_CLASS_BODY`, new wrapper on
`DataGridTableBodyRowCell`), `app/(protected)/workflows/components/use-workflows-list-config.tsx`,
`app/(protected)/user-management/users/components/use-users-list-config.tsx`.
**Test:** `components/ui/data-grid.inventory.test.ts` - new assertion the wrapper class carries
`max-sm:overflow-hidden`/`max-sm:truncate` and the conditional wrapper JSX is present verbatim.
**Live:** `fixround3-01`/`-02` (Workflows, "Fan-out edges …" names now end in an ellipsis, no
overlap with the "Updated"/"Trigger" text next to them).

**3 - found live while re-verifying finding 2: the pinned cell's hover/selected/striped states
were STILL translucent** (`group-hover:max-sm:bg-muted/40`, `group-data-[state=selected]:max-sm:
bg-muted/50`, `group-odd:max-sm:bg-muted/90`) - the same bleed-through defect as finding 1, just
gated on row state instead of always-on. Selecting a row and scrolling live reproduced it exactly:
the Users list's selected "Admin User" pinned cell showed a scrolled-under date ("…Jul 2026,
12:43") straight through the 50%-alpha selected tint. Fix: three new opaque tokens in
`css/config.reui.css` (`--pinned-cell-hover`, `--pinned-cell-selected`, `--pinned-cell-striped`),
each a `color-mix(in oklab, var(--muted) N%, var(--background))` - the SAME alpha math the old
`bg-muted/N` classes expressed, pre-mixed against `--background` (the pinned cell's own resting
colour) into a solid result. This keeps the intended visual WEIGHT (selected reads a touch
stronger than hover, matching the row's own hierarchy) while leaving nothing to bleed through.
One declaration each (`:root` only) - `--muted`/`--background` already flip under `.dark`, so the
tokens recompute correctly per theme with no separate `.dark` entry needed (same pattern
`--material-blur` already uses in the same file). The ROW itself is untouched and stays
translucent (`bg-muted/40`/`bg-muted/50` etc.) - it blends into its ancestor card/dialog
correctly; only the PINNED CELL needed the opaque swap, since it alone sits over unrelated
scrolled-under content rather than a backdrop.
**Fixed:** `css/config.reui.css` (3 new tokens), `components/ui/data-grid-table.tsx`
(`MOBILE_PIN_CLASS_BODY`, `MOBILE_PIN_CLASS_BODY_STRIPED`).
**Test:** `components/ui/data-grid.inventory.test.ts` - updated the existing "pinned cell
background matches its row state" assertion to the new token classes (the row-level classes it
also checks are unchanged) + a new assertion the three `color-mix` token declarations exist in
`css/config.reui.css`.
**Live:** `fixround3-09-users-375-selected-light.png` / `fixround3-10-users-375-selected-dark.png`
(Admin User row selected, scrolled to the far right, pinned cell solid in both themes - a
`getComputedStyle` check on the selected pinned `td` confirmed `background-color: oklab(...)` with
NO alpha component) + `fixround3-04-workflows-375-selected-dark.png` (same check on Workflows,
dark theme, mid-scroll).

### Gate

`npx eslint` on every touched file (clean), `npm test` (184 files / 1584 tests, +1 test file
assertion net vs the round-2 baseline of 184/1581 - one existing assertion updated in place, three
new assertions added), `rm -rf .next && npm run build` (green), restarted `:3002` (port ownership
confirmed via `lsof -p $(lsof -ti :3002) | grep cwd` before every kill).

### Definition of Done checklist (T2 fix round 3)

1. Both named defects fixed, each with a code change + a test; a third related defect (hover/
   selected/striped pinned-cell opacity) found live while re-verifying defect 2 and fixed the same
   way, per the brief's own checklist item ("Check the pinned cell's own background is opaque...
   in light AND dark, hover, selected and striped states").
2. `npx eslint`, `npm test` (184/184 files, 1584/1584 tests), `npm run build` all green.
3. `rm -rf .next && npm run build` before the final live check; port ownership confirmed via
   `lsof -p $(lsof -ti :3002) | grep cwd` before the restart.
4. No mock left behind, no backfill needed, no new permission - primitives-only fix round.
5. Verified from the user's perspective at 375 AND 1280 on the real prod build, light AND dark, a
   plain row AND a selected row, scrolled sideways AND vertically (page-level, `window.scrollTo`,
   since the seeded Workflows/Users lists are too short to overflow the grid's own bounded
   vertical scroller at these viewport heights) - Workflows and Users lists, real sidebar clicks
   from `/` (mobile nav `Sheet` trigger + accordion + link, eval-`click()`'d per the existing
   house note that a fresh Radix trigger sometimes needs a native `.click()` bridge rather than
   the CDP click helper).

**Verdict: T2 fix round 3 (pin polish) DONE.** Both named defects + one live-caught related defect
resolved and re-verified; full gate green.

## T3 - Motion

**Branch:** `sprint-4/23-T3-motion` (off `sprint-4/23-design-language-alignment`, at `8cac6ec` -
T0+T1+T2 merged).
**Evidence:** `documentation/plans/sprint-4/23-evidence/T3/` (`README.md` run log + 15
screenshots + live timing tables from `agent-browser eval` DOM polling).
**Environment:** backend `service_backend` shared on :8001 (owned by the `s23` worktree's
`uvicorn` process); frontend `rm -rf .next && npm run build` (green) served via
`npx next start -p 3003` (this worktree, port ownership confirmed via `lsof` before starting -
3001 free, 3002 owned by a sibling lane); `agent-browser` CLI only, real clicks/pointer events,
`demo@example.com`/`demo1234` (session already live).

**Environment finding (not a T3 regression, see the evidence README for the full writeup):** the
shared backend's `cors_origins`/`cors_origin_regex` allow-list stops at port 3002, so every
`Authorization`-bearing request from this slice's assigned port 3003 fails CORS preflight and
every backend-driven list/form (Users, Roles, App Store, Documents) rendered empty throughout
this run. Evidence below substitutes surfaces that don't need live backend data (SearchDialog,
Notifications sheet, the user-menu dropdown, both mobile drawers, the Roles Popover and Status
Select on the real New User form) plus direct DOM/computed-style timing proof via
`agent-browser eval` (the CLI has no DevTools-Animations-panel equivalent). ContextMenu/HoverCard/
Menubar's only real product call sites all need backend list data this gap blocks - covered by
code-parity + green build/lint/vitest instead of live clicks this run (see AC-DLA-20/21 below).

### AC-DLA-19 - `lib/motion.ts` exports + `lib/motion.test.ts` `[FE][T]`

**User story:** As a maintainer, I want one file owning the surface spring so every primitive
opens/closes on the same physics instead of inventing its own.
**Scenario:** Given `lib/motion.ts`, when any of `SURFACE_SPRING`/`MENU_SPRING`/
`SURFACE_SPRING_EXIT`/`REDUCED_MOTION_TRANSITION`/`surfaceTransition`/`surfaceExitTransition`/
`surfaceVariants`/`useOpenState`/`useReducedMotion` is imported, then it matches Sorento's API
verbatim plus the M2 exports.
**Steps:** `npx vitest run lib/motion.test.ts`.
**Expected:** every branch (lightbox vs menu preset, reduced-motion collapse, scale-drop under
reduced motion, `useOpenState`'s controlled/uncontrolled contract) pinned.
**Actual:** PASS - 11/11 tests green.
**Remarks:** this repo's `lib/motion.ts` already carried the M2 exports verbatim from the start
(D1) - `git diff` against `sorento_crm` `origin/main` and `origin/integration/ui-motion-round2`
both came back CODE-identical for this file (same exports, same functions, same reduced-motion
branching) at the time of this run - not byte-identical, since Sorento's own comments/wording
differ in a few places even where the logic matches exactly. **Superseded by T3 - Fix round 1
below**: the port's `visualDuration` LITERALS (`0.3`/`0.2`/`0.2`) were copied verbatim from
Sorento, but `visualDuration` is not the animation's wall-clock length - measuring with the real
`motion-dom` spring generator showed those settle at 559ms/390ms/390ms (~1.9x the intended
300ms/200ms/200ms), so fix round 1 changes the constants to `0.15`/`0.1`/`0.1` (D16) and the file
now deliberately DIVERGES from Sorento's literals (fed back upstream as BL-SS-049) while staying
code-identical in shape.

### AC-DLA-20 - nine surfaces on `AnimatePresence` + `surfaceVariants` + `surfaceTransition` `[FE][T]`

**User story:** As a user, I want every dialog/menu/popover to open and close with the same feel,
and to be able to re-open one I just started closing without a visual jump.
**Scenario:** Given Dialog/AlertDialog/Sheet/Popover/DropdownMenu(+SubContent)/
ContextMenu(+SubContent)/HoverCard/Menubar/Select, when opened, then each renders through
`useOpenState` + `AnimatePresence` gating a `motion.div` driven by `surfaceVariants`/
`surfaceTransition`, with the overlay on `OVERLAY_CLASS_STATIC`; lightboxes open ~300ms/close
~200ms, menus 200ms/200ms; zero `animate-in`/`animate-out`/`zoom-in`/`slide-in` classes remain;
re-opening mid-close continues from the live scale.
**Steps:** live `agent-browser` clicks + `eval`-driven `getComputedStyle` polling (see evidence
README steps 3-16); `npx eslint`/`npx vitest run`/`npm run build`; a class-literal grep sweep of
all 9 files.
**Expected:** per the AC text above.
**Actual:** PASS for Dialog/AlertDialog/Sheet/Popover/DropdownMenu+SubContent/Select (all six
live-verified with real timing tables - see the evidence README; **Select's own timing table
below is superseded by T3 - Fix round 1**, which moves it off the spring onto a symmetric CSS
fade - see that section); PASS-by-code-parity for
ContextMenu+SubContent/HoverCard/Menubar (identical `AnimatePresence`+`forceMount`+
`surfaceVariants`/`surfaceTransition` shape applied, diffable in the PR against the six
live-verified files; their only real call sites - Documents right-click, `resource-list.tsx`
hover cards, dead demo2/3 Menubar - all need backend data the CORS gap above blocks). Grep sweep:
zero `animate-in`/`animate-out`/`zoom-in`/`slide-in` classes remain in any of the 9 files (the
comments mentioning them explain what was REMOVED, not residue). Dialog trajectory: 16ms
opacity 0.042/scale 0.962 -> 100ms 0.527/0.981 -> 300ms 0.967/0.999. Menu-family trajectory
(DropdownMenu and Select both sampled): 16ms opacity ~0.04/scale ~0.962 -> 100ms ~0.71-0.77/
~0.99 -> 200ms ~0.96-0.97/0.999. Mid-close reopen: full-open (opacity 0.991/scale 1) -> Escape ->
60ms into close (0.680/0.986) -> **immediate re-open** -> 16ms later (0.523/0.981, continuing the
live trajectory, not reset to 0/0.96). Sheet: opacity fixed at 1 throughout, transform's scale
terms fixed at `1,0,0,1` throughout, only translate-X travels (466.7px -> 183.9px -> 11.5px) -
slide-only, no scale, no fade.
**Remarks:** two real Radix API constraints surfaced and were resolved, both documented inline in
the diff: (1) Radix Select's `Content`/`Portal` have no `forceMount` prop at all (confirmed
against `@radix-ui/react-select@2.2.6`'s own types), and Menubar's top-level `Content` has the
same gap - **superseded by T3 - Fix round 1 below**: both `SelectContent` and `MenubarContent`
originally played the menu SPRING in on mount with no exit (a one-sided 390ms-in/instant-out
asymmetry), which fix round 1 replaces with a SYMMETRIC CSS opacity fade on `--duration-fast`
(no `forceMount`, no spring at all) so open and close read as the same intent even though close
never gets to visibly finish before Radix unmounts it; (2) `vitest.setup.ts` needed
`MotionGlobalConfig.skipAnimations = true` (ported from `sorento_crm`'s identical fix) - without
it, `AnimatePresence`+`forceMount`'s exit never resolves under jsdom (no real animation-frame
pump), which broke 4 pre-existing test files (9 tests) that open-then-close one of these surfaces
and then query something else; all 9 pass again after the fix (one, `rule-builder.test.tsx`, also
needed a `waitFor` added around a query that ran one microtask tick too early against
synchronous `fireEvent.click` - production code untouched).

### AC-DLA-21 - origin-anchored scale, centered modals, `navigation-menu.tsx` `origin-top` `[FE][T]`

**User story:** As a user, I want a popover/menu to visibly grow FROM its trigger, not from a
random corner, and a modal to stay centered regardless.
**Scenario:** Given Popover/DropdownMenu/ContextMenu/HoverCard/Select, when open, then the scale
origin sits at the Radix-computed trigger anchor; Dialog/AlertDialog stay centered; the
navigation-menu viewport uses `origin-top`.
**Steps:** code review (`origin-(--radix-*-content-transform-origin)` on each inner `motion.div`)
+ live proof (the Dialog transform samples in AC-DLA-20 all carry the same `-300,-304.5` center
offset throughout the whole open/close/reopen trajectory).
**Expected:** per the AC text.
**Actual:** PASS - `navigation-menu.tsx`'s viewport class changed `origin-top-center` (not a real
Tailwind v4 utility) -> `origin-top`; every menu-family surface's inner `motion.div` carries the
matching origin utility.

### AC-DLA-22 - `command.tsx` `motion={false}` `[FE][T]`

**User story:** As a keyboard user, I want a palette I summoned with a shortcut to be simply
THERE on the next frame, not animate in.
**Scenario:** Given `CommandDialog`, when `motion={false}` (default `true`), then no scale/no
entry fade, the overlay fades on a plain `--duration-fast` tween, and Escape closes the same way.
**Steps:** `npm run build` (type-checks the new prop threading through `DialogContent`); code
review of `dialog.tsx`'s `motionEnabled` branch.
**Expected:** the prop compiles and reaches `DialogContent`'s existing `motion` prop unchanged.
**Actual:** PASS (mechanism) / **N/A live** - this codebase has no live keyboard-shortcut-opened
`CommandDialog`: `app/components/partials/dialogs/search/search-dialog.tsx` (the only header
search surface) is a plain click-triggered `Dialog` with hardcoded demo tabs, not `cmdk`-backed,
and `CommandDialog` itself has zero importers outside `command.tsx` (grepped, confirmed). This is
a plan/reality mismatch, not a T3 gap - flagged for T8/`docs/reference/design-language.md` rather
than worked around with a throwaway page. **Corrected in T3 - Fix round 1 below**: this row
originally described `motion={false}` as an opt-OUT (default `true`) - the frequency table
forbids animating a command palette outright, so a default of `true` satisfied the AC only on
paper with zero call sites ever passing `false`. Fix round 1 flips the default to
**`motion=false`** (opt IN to motion, never out); the verdict stays PASS (mechanism) / N/A (no
live opener) - the default flip changes nothing observable without a live `CommandDialog`, it
only changes what a FUTURE caller gets for free. This row remains a guard-only mechanism check
(`command.test.tsx` pins the default via `data-motion="off"`), not a live click.

### AC-DLA-23 - mobile nav on `vaul` `Drawer` `[FE][E2E]`

**User story:** As a phone user, I want the sidebar to slide open with my finger and dismiss on a
swipe, not react to a fixed CSS transition.
**Scenario:** Given `header.tsx`'s two mobile Sheets (sidebar nav + mega-menu), when replaced with
`Drawer` (`direction="left"`, `OVERLAY_CLASS_STATIC`, `shouldScaleBackground={false}`), then both
track a real drag and `[data-vaul-drawer]` collapses to 1ms under reduced motion.
**Steps:** live `agent-browser` at 375 - hamburger icon and the mega-menu icon, both under normal
AND reduced motion (see evidence README steps 8-10).
**Expected:** per the AC text.
**Actual:** PASS - both triggers open a `data-vaul-drawer-direction="left"` panel with the shared
scrim; under reduced motion `[data-vaul-drawer]`'s `transitionDuration` reads `"0.001s"`; under
normal motion it reads `"0.5s"` (vaul's own drag-tracked default, untouched by T3 - the plan only
assigns T3 the direction/overlay/reduced-motion wiring, not vaul's own physics).
**Screenshot note (T3 fix round 1 finding 14):** `07-mobile-sidebar-drawer-reduced-motion-375.png`
and `08-mobile-sidebar-drawer-normal-375.png` are BYTE-IDENTICAL (confirmed via checksum) - a
static screenshot of a fully-open drawer necessarily looks the same regardless of how long it took
to get there, so the two screenshots alone prove nothing about motion; the actual proof is the
`transitionDuration` values quoted above (`"0.001s"` vs `"0.5s"`), sampled live via
`agent-browser eval` against the real DOM. Both files are correctly labelled here as SETTLED-STATE
screenshots (confirming the drawer opened and rendered correctly under each preference), not as
frame-by-frame motion evidence - that evidence is the timing data, not the images.

### AC-DLA-24 - sidebar collapse: `hover`-gated, reduced-motion-gated, double-rAF init `[FE][T]`

**User story:** As a user on a touch device, I don't want the collapsed sidebar to phantom-expand
on a tap; as a user who asked for less motion, I don't want it to travel at all.
**Scenario:** Given `demo1.css`'s hover-expand rule, when wrapped in
`@media (hover: hover) and (pointer: fine)`, and the width transition wrapped in
`@media (prefers-reduced-motion: no-preference)`; given `demo1/layout.tsx`'s
`setTimeout(...,1000)`, when replaced with a double `requestAnimationFrame`; then a DevTools-trace
(or equivalent) of a collapse at 1280 shows no dropped frames, or a follow-up is filed and the
transition left as-is.
**Steps:** live `agent-browser` reduced-motion poll of `.sidebar`'s computed
`transitionProperty`/`transitionDuration`; a real `requestAnimationFrame` sampler (24 frames)
across a real collapse-toggle click on the Users list at 1280.
**Expected:** `transition: none` under reduced motion; no dropped frames on the collapse (or a
filed follow-up).
**Actual:** PASS - reduced motion: `transitionProperty: "none"`, `transitionDuration: "0s"`.
Frame sampler: 24 consecutive deltas all in a tight 16.6-16.8ms band (steady 60fps, no delta
anywhere near the ~20ms dropped-frame threshold); the sidebar's `getBoundingClientRect().width`
trace is one clean easing curve from 280px to the 80px collapsed rail, settled by frame ~19
(~300ms, matching `--duration-slow`), no stutter or backtrack. No dropped frames -> per the
plan's own instruction the transition is left as-is; BL-SS-046 (the transform-only rewrite,
already backlogged, Sorento tried and reverted it) is unchanged by this slice.
**Remarks:** `agent-browser` ships no DevTools-Animations-panel-equivalent or CDP trace
passthrough in this version - the rAF sampler is the load-bearing substitute, same adaptation
class as the timing tables in AC-DLA-20/26.

### AC-DLA-25 - 16 decor components + `framer-motion` deleted `[FE][T]`

**User story:** As a maintainer, I don't want dead decorative components with their own
animation dependency lingering in the primitives directory.
**Scenario:** Given the 16 named files (`marquee`, `text-reveal`, `shimmering-text`,
`sliding-number`, `counting-number`, `gradient-background`, `hover-background`,
`grid-background`, `stepper`, `word-rotate`, `typing-text`, `avatar-group`, `video-text`,
`github-button`, `skeleton-with-pattern`, `svg-text`), when deleted with zero remaining
importers, then `framer-motion` is removed and a guard test fails if any reappears.
**Steps:** `grep -rl` (quoted globs) confirmed zero importers per file BEFORE deleting; `git rm`
(not a bare `rm`, so the deletion is staged, not just working-tree); `npx vitest run
components/ui/deleted-motion-components.guard.test.ts`; `npm run build`.
**Expected:** all 16 gone, zero framer-motion imports remain, build green.
**Actual:** PASS - all 16 deleted (confirmed via `existsSync` in the guard test, 18/18 green);
zero `components/ui/*` files import `framer-motion` directly (the guard test's own second
assertion); `npm run build` green.
**Remarks:** `framer-motion` was **never a direct `package.json` dependency in this repo** - only
`motion`'s own internal transitive dependency (`node_modules/motion/package.json` declares
`"framer-motion": "^12.40.0"` itself; confirmed via `python3 -c "import json..."` against
`package.json` that no top-level `dependencies`/`devDependencies` entry named it before this
diff). `npm uninstall framer-motion --package-lock-only` + `npm ci` therefore produced a genuine
no-op (`git status` on `package.json`/`package-lock.json` empty afterward) - run anyway per the
brief, confirming rather than skipping the instruction. `motion` stays the one animation
dependency the app imports from.

### AC-DLA-26 - frame-by-frame + reduced-motion pass, evidence under `23-evidence/T3/` `[FE][E2E]`

**User story:** As a reviewer, I want proof the spring actually ticks over real time and that
reduced motion actually removes travel/scale, not just a claim from reading the source.
**Scenario:** Given Dialog/Sheet/DropdownMenu/Popover/the command palette/the mobile drawer, when
reviewed frame-by-frame at 4x (or equivalent), then normal motion shows the spring's progression
and reduced motion shows an instant cross-fade with no travel/scale; the sidebar collapse is
instant under reduced motion.
**Steps:** see AC-DLA-20/23/24 above for the underlying data; this AC is the "evidence exists and
is saved" check - `documentation/plans/sprint-4/23-evidence/T3/README.md` + 15 screenshots.
**Expected:** evidence directory populated, one verdict line per AC, reduced-motion pass covering
every AC-DLA-20 surface reachable this run.
**Actual:** PASS for Dialog/Sheet/DropdownMenu/Popover/Select/mobile drawer (all six have both a
normal-motion timing table AND a reduced-motion sample above); **N/A** for the command palette
(AC-DLA-22 - no live surface exists to record). `agent-browser` has no DevTools-Animations-panel
equivalent in this CLI version, so `agent-browser eval`-driven `getComputedStyle` sampling on a
`setTimeout`/`requestAnimationFrame` cadence stands in for it throughout - the same adaptation
T1/T2's evidence runs made for their own timing claims (documented explicitly in the README so a
reviewer doesn't expect a literal screen-recording).

### Gate

`npx eslint` on all touched-and-surviving files (0 errors); `npx vitest run` - **186 files / 1610
tests, all green** (includes the new `lib/motion.test.ts` and
`components/ui/deleted-motion-components.guard.test.ts`, plus the `vitest.setup.ts`
`skipAnimations` fix and the one `rule-builder.test.tsx` `waitFor` addition needed for the real
async close the spring introduces); `rm -rf .next && npm run build` - green, run twice (once
after the Radix Select `forceMount` compile errors were fixed, once final); restarted `:3003`,
port ownership confirmed via `lsof -p $(lsof -ti :3003) | grep cwd` before every restart.

### Definition of Done checklist (T3)

1. All AC-DLA-19..26 addressed - 6 fully live-verified end-to-end with real timing data
   (AC-DLA-19/20/21/23/24/25/26 partially or fully), AC-DLA-22 mechanism-verified with an honest
   N/A note on the missing live call site, AC-DLA-20's ContextMenu/HoverCard/Menubar covered by
   code parity + green suite rather than live clicks (CORS gap, documented, not silently
   dropped).
2. `npx eslint`, `npx vitest run` (186/186 files, 1610/1610 tests), `npm run build` all green.
3. `rm -rf .next && npm run build` before every live check; port ownership confirmed via `lsof`
   before every restart on :3003.
4. No mock left behind (motion is a pure primitives slice, no backend/mock boundary to swap); no
   backfill needed; no new permission. The 16 decor deletions have zero surviving importers
   (grepped before deleting, re-confirmed by the guard test after).
5. Verified from the user's perspective at 375 AND 1280 on the real prod build, both normal AND
   reduced motion, with live DOM-level proof (not just visual screenshots) that the spring
   genuinely ticks over wall-clock time, is interruptible without a jump, and fully collapses
   under reduced motion - the CORS-3003 environment gap is disclosed rather than hidden, with the
   evidence substitution strategy spelled out per surface.

**Verdict: T3 - Motion DONE**, with two disclosed, non-blocking gaps for the reviewer/T8 to
weigh: (a) the CORS-3002-cap environment gap (recommend widening before more concurrent-port
slices land), (b) AC-DLA-22's missing live command-palette call site (a plan/reality mismatch,
not code debt - the mechanism is built and unit-covered, ready for the day a real Cmd/Ctrl+K
palette exists).

## T3 - Fix round 1

**Reviewer input:** `.claude/skills/codex-review` / `review-animations` full pass (12
findings + 3 blockers) against `sprint-4/23-T3-motion` at `04f8646` (T3's original merge),
measured with the real `motion-dom` spring generator. Full text at
`/private/tmp/claude-501/.../scratchpad/t3-review-animations.md` (session-scoped scratchpad, not
in the repo - findings reproduced below against the actual diff).
**Branch/commit:** same `sprint-4/23-T3-motion`, fix-round-1 commits on top.
**Evidence:** `documentation/plans/sprint-4/23-evidence/T3/README.md` "T3 - Fix round 1" section
(9 new `fixround1-NN-*.png` screenshots + live DOM/CSS-source proof per finding).
**Gate:** `npx eslint` (0 errors), `npx vitest run` (191 files / 1631 tests, all green),
`rm -rf .next && npm run build` (green) - see the evidence README's own Gate subsection for the
one real compile error surfaced and fixed (Radix's `AlertDialogContentProps` omitting
`onPointerDownOutside`/`onInteractOutside`).

| # | Finding | Outcome |
|---|---|---|
| 1 (BLOCKER) | Search dialog centering broke under `lg:top-[15%] lg:translate-y-0` once centering moved into the animated transform. | FIXED - `dialogContentVariants` gained a `position: 'center' \| 'top'` variant; `DialogContent` maps `position="top"` to `{x:'-50%', y:0}` (no vertical translate needed, `top-[15%]` handles it) vs `center`'s `{x:'-50%', y:'-50%'}`. `search-dialog.tsx` switched to `position="top"`. Live-verified fully visible at 1280 (`top:135/900 = 15%` exactly, `bottom` inside viewport) - `fixround1-01-search-dialog-1280.png`; confirmed absent (by pre-existing design, not a regression) at 375, where the header never renders the search trigger under `mobileMode` - `fixround1-02-search-dialog-375.png`. |
| 2 (BLOCKER) | Collapsed-rail presentation rules (logo swap, label/badge hiding) had moved inside `@media (hover: hover) and (pointer: fine)` alongside the hover-expand rule, so a coarse-pointer device at >= lg with `sidebarCollapse=true` got the collapsed WIDTH with none of the collapsed PRESENTATION. | FIXED - `demo1.css`: only `.demo1.sidebar-collapse .sidebar:hover{width:...}` stays inside the hover-pointer gate; every presentation rule (`.default-logo`/`.small-logo`/`[data-slot=accordion-menu-*]`/`[data-slot=badge]`) moved back outside it, applying on any pointer whenever `.sidebar-collapse` is set. `agent-browser`'s CDP session cannot toggle `pointer`/`hover` media features (confirmed: none of its device presets do, `matchMedia` still reports `fine`/`hover` on all of them) - verified instead by fetching the actual SERVED build CSS and confirming the rule nesting byte-for-byte matches the fix; live regression check with a real (fine) pointer confirms the collapsed rail still renders correctly (`fixround1-03-sidebar-collapsed-presentation-1280.png`). |
| 3 | `SURFACE_SPRING`/`MENU_SPRING`/`SURFACE_SPRING_EXIT` `visualDuration` literals (0.3/0.2/0.2, copied from Sorento) settle at 559ms/390ms/390ms - not the intended 300ms/200ms/200ms, since `visualDuration` is the perceived-response knob, not the wall-clock length. `REDUCED_MOTION_TRANSITION` at `duration: 0.01` was indistinguishable from a hard pop. | FIXED (D16) - `lib/motion.ts`: `SURFACE_SPRING visualDuration: 0.15` (measured settle 302ms), `MENU_SPRING`/`SURFACE_SPRING_EXIT: 0.1` (measured settle 210ms), `REDUCED_MOTION_TRANSITION: { duration: 0.15 }` (matches `--duration-fast`, keeps the fade). Comments rewritten to state what each settles to and why, and to flag the deliberate divergence from Sorento's literals (fed back as BL-SS-049). `lib/motion.test.ts` now imports `spring` from `motion-dom` directly and asserts real settle times (250-350ms lightbox, 180-240ms menu/exit) alongside the existing config-object assertions - this is what would have caught the original 559/390ms regression, since `vitest.setup.ts`'s `skipAnimations` flag means no rendered-component test ever exercises the generator. Added real `renderHook` tests for `useOpenState`: uncontrolled default + update, controlled prop wins with internal state untouched, `onOpenChange` fired in both modes; the `typeof === 'function'` placeholder is gone. 18/18 green. |
| 4 | `CommandDialog` defaulted `motion={true}` - the frequency table's one absolute no-animate surface, opt-out instead of opt-in, with zero call sites ever passing `false`. | FIXED - default flipped to `motion={false}` (AC-DLA-22). New `command.test.tsx` (3 tests) pins the default via `DialogContent`'s `data-motion="off"` attribute, an explicit `motion` override, and an explicit `motion={false}` matching the default. |
| 5 (BLOCKER) | `[data-vaul-drawer]`'s reduced-motion reset only touched `transition-duration` - vaul opens/closes via a CSS ANIMATION, so the 275px mobile drawer still slid at full 500ms speed for a reduced-motion reader. Normal-motion drawer had no house-token pin either (vaul's un-pinned 500ms default, vs every other migrated surface's ~200-300ms). | FIXED - `css/styles.css`: `[data-vaul-drawer], [data-vaul-overlay] { transition-duration: 1ms !important; animation-duration: 1ms !important; }` inside the reduced-motion block; a new unlayered-vs-layered `!important` block outside it pins normal-motion `animation-duration: var(--duration-slow) !important` (300ms) for both selectors (`!important` needed because vaul injects its own CSS unlayered, which otherwise always beats a layered non-important declaration). Live-verified at 375: reduced motion `animationDuration: "0.001s"` (was untouched before this fix), normal motion `animationDuration: "0.3s"` (was vaul's un-pinned `.5s`) - `fixround1-04/05-mobile-drawer-{reduced-motion,normal}-375.png` (byte-identical to each other by design - settled-state screenshots can't show a duration difference; the computed-style values are the proof, noted inline in both READMEs per finding 14). `css/design-tokens.test.ts` updated (one existing case, one new case) to pin both selectors and both properties. |
| 6 | `navigation-menu.tsx`'s viewport stayed on 150ms plain-`ease` tw-animate keyframes, asymmetric `zoom-in-90`/`zoom-out-95`, and sat outside the reduced-motion selector's reach entirely (`data-slot` doesn't end in `-content`, not inside a popper wrapper). | FIXED, via the documented "at minimum" fallback, NOT the spring - investigated `forceMount` + `AnimatePresence` first (Radix's `Viewport` DOES support `forceMount`), but `NavigationMenuViewportImpl` computes its own `children` internally (`Array.from(viewportContentContext.items).map(...)`, one per active trigger) and unconditionally overwrites whatever `children`/`asChild` target this component passes - the inner-`motion.div` split every sibling surface uses has no single child to attach to here, confirmed by reading Radix's own source rather than guessing. Landed the documented fallback instead: symmetric `zoom-in-95`/`zoom-out-95` (was asymmetric 90/95) + `duration-(--duration-base) ease-(--ease-standard)` (tokenised, matches the menu family's ~200ms). `css/styles.css`'s reduced-motion selector gained `[data-slot='navigation-menu-viewport']` explicitly. Live-verified: normal motion `animationDuration: "0.2s"`, `animationTimingFunction: "cubic-bezier(0.2, 0, 0, 1)"` (`fixround1-07-navigation-menu-viewport-1280.png`); reduced motion `animationDuration: "0.15s"` (previously unreachable, now reset). |
| 7 | `SelectContent`/`MenubarContent` (no `forceMount` in Radix) entered on the one-sided menu spring (390ms in) and vanished in one un-animated frame on close - the deliberate-slow-half was the wrong one for a form control opened tens of times a day. | FIXED - both dropped the spring entirely for a symmetric CSS opacity fade on `--duration-fast` (`data-[state=open]:animate-in data-[state=closed]:animate-out fade-in-0 fade-out-0 duration-(--duration-fast) ease-(--ease-standard)`, no zoom), matching the honest-simplification call in the review (`MenubarSubContent`, which DOES have `forceMount`, is unaffected and stays on the spring - it was never part of this finding). Live-verified: `[data-slot="select-content"]` `animationDuration: "0.15s"`, `transform: "none"` (confirmed no residual zoom) - `fixround1-08-select-status-fade-1280.png`. Menubar has no live product call site (same as the original run) - code review + green build/lint/vitest cover it. |
| 8 | No `guardOutsideInteraction`/`restoreFocusToOpener` on any of Dialog/AlertDialog/Sheet - a plain-button-opened dialog (244 of 250 call sites in this repo) left focus on `<body>` after close, and a DropdownMenu/Popover/Select item that opened a dialog could have its trailing event misread as an outside click on the freshly-mounted dialog. | FIXED - ported `sorento_crm`'s `dialog.tsx` pair verbatim (mount-grace window, `focusIsInsideFloating` stacked-surface guard, `onCloseAutoFocus` restore-to-opener with a caller-`preventDefault` escape hatch) onto `dialog.tsx`, and applied the SAME pair to `alert-dialog.tsx`/`sheet.tsx` per this finding's explicit instruction (Sorento itself only ships it on `dialog.tsx` and left AlertDialog as its own follow-up - this repo ships both now). New `components/common/floatingAncestry.ts` (ported, with this repo's own `sheet-content`/`drawer-content` slots added to the selector). **Real Radix API constraint found while wiring AlertDialog**: `AlertDialogContentProps` deliberately `Omit`s `onPointerDownOutside`/`onInteractOutside` from `DialogContentProps` (confirmed against `@radix-ui/react-alert-dialog`'s own types) - an AlertDialog is never dismissable by an outside click at all, by design; only `onFocusOutside` + `onCloseAutoFocus` survive that Omit, so `alert-dialog.tsx`'s guard wiring is intentionally narrower than `dialog.tsx`/`sheet.tsx`'s. Unit-tested: `dialog.test.tsx` (4), `alert-dialog.test.tsx` (2), `sheet.test.tsx` (2) - all via `userEvent` (not bare `fireEvent`, which does not reproduce a real click's focus-follows-click behaviour in jsdom) - covering Escape-close, close-button-close, a caller's own `onCloseAutoFocus` taking over, and the opener-left-the-DOM edge case. |
| 9 | `demo1/layout.tsx` set `layout-initialized` from the MOUNT effect's own double-`requestAnimationFrame`, independent of the `[settings]` effect that actually applies `sidebar-collapse` - `SettingsProvider` hydrates `sidebarCollapse` from localStorage in an effect of its OWN that can fire AFTER the mount effect's rAFs already scheduled, so a returning collapsed-sidebar user could get `layout-initialized` (enabling the width transition) BEFORE the hydrated class landed, then see the wrapper visibly collapse into place. | FIXED - `layout-initialized` is now scheduled from inside the `[settings]` effect itself, one `requestAnimationFrame` after `sidebar-collapse` is applied in that SAME effect run (not the mount effect, which now only owns `demo1`/`sidebar-fixed`/`header-fixed` mount/unmount). Live-verified: `localStorage.setItem('app_settings_layouts.demo1.sidebarCollapse','true')` + reload -> `document.body.className` carries BOTH `sidebar-collapse` AND `layout-initialized` together on the settled page (`fixround1-03-...png` is this same state) - the two classes never observably land out of order in this run. |
| 10 | `drawer.tsx`'s `data-[vaul-drawer-direction=left]:w-3/4 sm:max-w-sm` (a data-ATTRIBUTE-scoped Tailwind utility, which compiles to a two-selector rule) out-specified `header.tsx`'s plain `w-[275px]` regardless of source order, so the nav drawer silently rendered at 75% of the viewport instead of 275px. | FIXED - dropped the width utilities from the left/right direction variants entirely (the sole consumer, `header.tsx`, already sets its own width via `className`); position/height/border stayed. Live-verified at 375 (`width: 275`, was previously masked by a near-coincidental match with `w-3/4` at that one width) AND at 700px (`width: 275`, was `525` = `w-3/4` pre-fix, unambiguously wrong) - `fixround1-06-mobile-drawer-width-700.png`. |
| 11 | `header.tsx`'s two mobile drawers had no `DrawerTitle` at all (a11y gap); `DrawerContent` lacked the sr-only fallback `DialogContent` has. | FIXED - `drawer.tsx` gained a `hasDrawerTitleInChildren` check (same shape as `dialog.tsx`'s) with a generic sr-only "Panel" fallback; `header.tsx` renders explicit `<DrawerTitle className="sr-only">Navigation</DrawerTitle>` / `Apps` in each drawer's `DrawerHeader` (more descriptive than the generic fallback, which only fires when a caller supplies nothing). Live-verified: `[data-slot="drawer-title"]` reads `"Navigation"`/`"Apps"` respectively while each drawer is open. New `drawer.test.tsx` (2 tests) pins the fallback-vs-caller-supplied behaviour. |
| 12 | `dialog.tsx`'s standalone `DialogOverlay` export used `OVERLAY_CLASS_STATIC` (no CSS fade) even though it's not spring-driven when used alone; `alert-dialog.tsx` had no standalone `AlertDialogOverlay` export at all (T3's spring migration deleted the pre-spring one that existed at `8cac6ec`, without replacing it). | FIXED - `DialogOverlay` switched to `OVERLAY_CLASS` (the CSS-fade variant). `AlertDialogOverlay` restored as a standalone export using `OVERLAY_CLASS` too, mirroring `DialogOverlay`. Both remain zero-importer today (confirmed by grep) - kept for API stability, per the finding's own instruction. |
| 13 | `demo1.css` still transitions `width`/`padding-inline-start`/`inset-inline-start` (layout properties, normally an escalation trigger) with no comment explaining why that's accepted. | DOCUMENTED (not rewritten - the finding's own ruling: "leave them, trace showed zero dropped frames") - one-line-plus comment added above the width transition naming the exception and `BL-SS-046` explicitly, cross-referencing the original run's 24-frame `requestAnimationFrame` sampler (zero dropped frames, all deltas 16.6-16.8ms) that justified leaving it. |
| 14 | Test report inaccuracies: `lib/motion.ts` called "byte-identical" to Sorento's (it's code-identical, and post-fix-round-1 deliberately diverges on the `visualDuration` literals); Select/Menubar rows described the one-sided spring that no longer exists; AC-DLA-22 described `motion={false}` as opt-out; the two byte-identical drawer screenshots (07/08) were unlabelled; no "close a dialog, click a button immediately" check existed anywhere in the suite or the evidence. | FIXED - AC-DLA-19/20/22 rows in the T3 body above amended with "Superseded by T3 - Fix round 1" pointers explaining exactly what changed and why (kept the original text as historical record rather than silently rewriting it, so a reader can see what was true AT THE TIME); AC-DLA-23/26 gained the byte-identical-screenshot disclosure; this row's own outcome cell doubles as the "close a dialog, click a button immediately" writeup: dispatched a real `Escape` keydown on an open `SearchDialog`, `requestAnimationFrame`-polled `getComputedStyle(document.body).pointerEvents` from that instant - **cleared at ~326ms** (down from the pre-fix 390-559ms window measured in D16), and a from-scratch back-to-back CDP `mouse move/down/up` click on the "Filters" toolbar button immediately after a second close landed successfully (`aria-expanded="true"` on the very next click) - `fixround1-09-close-dialog-click-immediately-1280.png`. |
| 15 (gate) | Full gate + evidence for this round. | `npx eslint` clean (0 errors); `npx vitest run` 191 files / 1631 tests green; `rm -rf .next && npm run build` green (after fixing the one real Radix `AlertDialogContentProps` compile error, see above); restarted `:3003` from this worktree, ownership confirmed via `lsof -p $(lsof -ti :3003) \| grep cwd` before every check; 9 new `fixround1-NN-*.png` screenshots + the full write-up under `documentation/plans/sprint-4/23-evidence/T3/README.md`'s "T3 - Fix round 1" section; this section appended to the test report mapping all 15 items. No push, no merge, no branch switch. |

**Files touched this round:** `lib/motion.ts`, `lib/motion.test.ts`, `components/ui/{dialog,alert-dialog,sheet,drawer,select,menubar,navigation-menu,command}.tsx`, new
`components/ui/{dialog,alert-dialog,sheet,drawer,command}.test.tsx`, new
`components/common/floatingAncestry.ts`, `css/{styles,demos/demo1,design-tokens.test}.ts`/`.css`,
`app/components/layouts/demo1/layout.tsx`, `app/components/layouts/demo1/components/header.tsx`,
`app/components/partials/dialogs/search/search-dialog.tsx`.

**Verdict: T3 - Fix round 1 DONE.** All 3 blockers resolved and live-verified; all 11 non-blocker
findings resolved (10 code + 1 documented-as-accepted per the finding's own ruling); the report
accuracy issues (finding 14) corrected in place with pointers rather than silent rewrites. Same
two disclosed non-blocking gaps as the original run carry forward unchanged: the CORS-3002-cap
environment gap (still not this slice's file scope to fix) and AC-DLA-22's missing live
command-palette call site (still a plan/reality mismatch, not code debt).

## T3 - Fix round 2

**Reviewer input:** verification pass on T3 fix round 1's commits (`d9dc49e`..`69e1815`) - 10 items
FIXED, 2 PARTIAL (findings 1 and 2 needed a second pass; both landed correctly per verification).
**Branch/commit:** same `sprint-4/23-T3-motion`, fix-round-2 commits on top.
**Evidence:** `documentation/plans/sprint-4/23-evidence/T3/README.md` "T3 - Fix round 2" section
(7 new `fixround2-NN-*.png` screenshots + live DOM/CSS-source proof per item), `agent-browser
--session t3fix2` on every browser call per the coordinator's session-isolation request.
**Gate:** `npx eslint` (0 errors), `npx vitest run` (192 files / 1642 tests, all green), `rm -rf
.next && npm run build` (green, no compile errors this round).

| # | Item | Outcome |
|---|---|---|
| 1 (was PARTIAL) | `position="top"` combined `top-[15%]` with the default `max-h-[90dvh]` unconditionally - at 1280x577 the search dialog's bottom sat ~29px below the fold (`top 86.5 + height 519 = 605.8 > 577`). | FIXED - `dialogContentVariants` gained a `compoundVariants` entry: `variant: 'default'` + `position: 'top'` now also applies `max-h-[calc(85dvh-2rem)]` (cva's `compoundVariants` output comes last, so `twMerge` correctly drops both the stale `top-[50%]` AND `max-h-[90dvh]` in favour of the position-aware ones - verified via a direct `cva()`/`twMerge()` node repro before touching the component). `85dvh - 2rem` keeps offset(15dvh) + cap <= 100dvh with a fixed 2rem of bottom breathing room at ANY viewport height. Live-verified at 1280x577 (`top:86.5, height:458.4, bottom:545.0`, ~32px of headroom - `fixround2-01-search-dialog-1280x577.png`) AND 1280x900 (`top:135, height:609, bottom:744` - `fixround2-02-search-dialog-1280x900.png`, regression check: the dialog's natural content height never approaches the cap at this taller viewport). |
| 2 (was PARTIAL) | The collapsed-rail presentation rules moved outside the hover-pointer gate in round 1, but stayed qualified with a negated `:hover` on `.sidebar` - `:hover` STICKS after a tap on a coarse (touch) pointer (no "unhover" event), so a single tap anywhere in the rail on a touch device silently un-hid every label/badge inside the still-80px rail. | FIXED - `demo1.css`: base rules (`.demo1.sidebar-collapse .sidebar .default-logo` etc.) now carry NO hover qualifier of any kind - unconditional whenever `.sidebar-collapse` is set, on ANY pointer. The RESTORE-on-hover half (undoing every base rule back to the full sidebar's presentation, PLUS the pre-existing width-expand rule) all moved inside `@media (hover: hover) and (pointer: fine)`, targeting `.sidebar:hover` explicitly - higher specificity than the base rules via the added pseudo-class, so it wins without needing `!important` except where the base rule itself has one (display/transition/animation on title/badge/sub-indicator, restored via `!important` too). `css/design-tokens.test.ts` gained a new case asserting NO negated-hover selector remains anywhere in `demo1.css` and that the restore rules live inside the hover-pointer gate. Verified via the actual served build CSS (agent-browser still cannot toggle `pointer`/`hover` media features in this CLI version - re-confirmed against every device preset) plus a live regression pass with the real pointer: collapsed-not-hovered renders correctly (`fixround2-03-...png`), hover-expand still restores full width + labels (`fixround2-07-sidebar-hover-expand-1280.png`). |
| 3 | The normal-motion vaul `animation-duration: var(--duration-slow) !important` pin sat UNCONDITIONALLY in the same `@layer base` as the reduced-motion block's own `1ms !important` pin, later in source - for two `!important` declarations at equal specificity in one layer, the later one wins regardless of media query, so this pin actually won the cascade under reduced motion too. It was harmless only because `--duration-slow` itself collapses to `1ms` under reduced motion (masking wrong precedence with a coincidentally-right value). | FIXED - wrapped in `@media (prefers-reduced-motion: no-preference)`, so it structurally can never apply under reduced motion. `css/design-tokens.test.ts`'s existing case rewritten to assert the pin lives INSIDE that media block (via the file's own `block()` brace-balancer helper) and does NOT appear unconditionally outside it - a structural, not value-based, assertion per the coordinator's "keep the test honest" instruction. Live re-verified at 375: reduced motion still `0.001s`, normal motion still `0.3s` (outcome unchanged, as expected - this was a precedence bug masked by a coincidence, not a wrong value) - `fixround2-04/05-...png`. |
| 4 | `floatingAncestry.ts`'s `isInsideOpenDialog` export had zero importers. | FIXED - deleted (re-confirmed zero importers via grep before deleting). |
| 5 | No dedicated test coverage for `guardOutsideInteraction`/`focusIsInsideFloating` - fix round 1 only covered them indirectly via the dialog/alert-dialog/sheet component tests' Escape/close-button flows. | FIXED - the identical closure duplicated in `dialog.tsx`/`alert-dialog.tsx`/`sheet.tsx` factored into one `createOutsideInteractionGuard(mountedAtRef)` in `floatingAncestry.ts` (all three components now call the shared factory instead of redefining the same logic), then directly unit-tested: a `CustomEvent` with `detail.originalEvent.target` inside `[data-slot="dropdown-menu-content"]` is prevented; one outside any floating surface, well past the grace window, is not; one inside the 300ms mount-grace window is prevented (both a static case and a `performance.now()`-spied 301ms-later case - `vi.useFakeTimers()` does not fake `performance.now()` in this vitest version, discovered mid-round and fixed with a direct spy); plus `focusIsInsideFloating` itself (null, plain element, nested-in-floating-surface, nested-in-stacked-dialog). `floatingAncestry.test.ts` - 10/10 green. |
| 6 | `header.tsx`'s mega-menu drawer trigger (`:105`) had no `aria-label`, unlike its sibling hamburger trigger (`:79`, `aria-label="Open navigation"`). | FIXED - added `aria-label="Open apps menu"`. Live-verified at 375: accessible name now reads "Open apps menu" in the a11y snapshot, and the drawer still opens correctly with `DrawerTitle` "Apps" - `fixround2-06-mega-menu-aria-label-375.png`. Surfaced (not fixed, out of scope) a pre-existing, unrelated layout overlap: the `ActivityTriggers` icon group visually overlaps the hamburger+apps-menu icon group by ~20px at 375px width, which twice misdirected a coordinate-based click onto the wrong button during this verification (each time leaving a stuck `document.body{pointer-events:none}` lock until that surface's own Close button was clicked) - documented in the evidence README as a follow-up candidate, not touched here. |

**Files touched this round:** `components/ui/dialog.tsx` (compound variant), `css/demos/demo1.css`,
`css/styles.css`, `css/design-tokens.test.ts`, `components/common/floatingAncestry.ts` (new
`createOutsideInteractionGuard`, dropped `isInsideOpenDialog`), new
`components/common/floatingAncestry.test.ts`, `components/ui/{dialog,alert-dialog,sheet}.tsx`
(wired onto the shared guard factory), `app/components/layouts/demo1/components/header.tsx`
(`aria-label`).

**Verdict: T3 - Fix round 2 DONE.** Both PARTIAL items from the verification pass (findings 1 and
2) are now FIXED and live-verified at both their originally-failing measurement AND a regression
viewport; all 4 remaining items landed cleanly. No new gaps introduced (gate green, zero new
console errors). Same two disclosed non-blocking gaps carry forward unchanged from prior rounds
(the CORS-3002-cap environment gap, AC-DLA-22's missing live command-palette call site), plus one
new non-blocking observation (the `ActivityTriggers`/mega-menu icon overlap at 375px, out of
scope for this round).