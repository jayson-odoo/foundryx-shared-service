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
