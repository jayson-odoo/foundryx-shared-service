---
name: feature
description: Run a non-trivial feature through this repo's mandatory pipeline - grill, UAC, plan, FE mock, BE TDD, review, DoD gate - invoking the mattpocock-skills plugin at the slots where they belong. Use when starting any feature, refactor or engine/module-level change that is more than a one-file change.
---

# /feature - the foundryx-shared-service delivery pipeline

`PRINCIPLES.md` defines the mandatory order (§ Methodology + § Definition of Done
gate). This skill executes it, calling the `mattpocock-skills` plugin as
subroutines at the steps where they fit.

**The order is the point.** Skipping or reordering a step is a process violation.
If a step genuinely cannot be done, say so explicitly and record why in the PR
description - do not silently drop it.

## Where the plugin disagrees with PRINCIPLES.md, PRINCIPLES.md wins

The plugin was written for a different repo. Two standing overrides:

1. **Files are the source of truth; issues (if used) are only the queue.** The
   contract is `documentation/plans/sprint-<N>/<NN>-<feature>-acceptance-criteria.md`
   (UAC) plus `documentation/plans/sprint-<N>/<NN>-<feature>.md` (plan). If GitHub
   Issues are used to track slices, each issue body must link back to those two
   paths - an issue that contradicts the UAC loses. This repo has no mandatory
   ticket-publishing step; skip any plugin step that wants to publish the spec as
   an issue unless the user asks for one.
2. **Frontend mock before any backend code.** `mattpocock-skills:tdd` drives
   straight to red-green-refactor and has no concept of a mock-first phase. Never
   hand it the whole feature - scope it to the backend phase only (PRINCIPLES.md
   step 4), or run the frontend-mock phase yourself first.

## Who executes each step (delegation is part of the order)

Every step has a named executor in `.claude/agents/` (ported from sorento-crm's crew v2,
2026-09-05). Running a step in the wrong seat - e.g. a `general-purpose` agent doing a
coder/tester/reviewer job - is the same process violation as skipping the step.

- **Main session** (the captain, strongest model, holds the grill context): grill, UAC, plan,
  plan review (`lavish` markup + grill), all user-in-the-loop moments, orchestration, briefs.
  Planning is NEVER delegated for a normal feature; `planner` exists only for module/engine-sized
  work needing parallel exploration.
- **`tester` agent** (sonnet): writes Phase 2's failing tests BEFORE the coder sees the slice -
  from the UAC, the Phase 1 contract block in the service file, and the captain's test list (one
  line per UAC id: test name + the assertion in words) - with no implementation to look at,
  confirms each fails for the right reason, commits `test(<slug>): red tests for <slice>`. Also
  runs the end-of-lane browser verification (`agent-browser`, headless) and writes the AC-keyed
  Test Execution Report.
- **`coder` agent** (sonnet): Phase 1 and Phase 2 implementation, ONE agent kept alive for the
  whole lane - the captain continues it with a message for later slices and fix rounds instead of
  respawning, so worktree state and context carry over. Spawn with its own worktree
  (`.claude/worktrees/<lane>/`, own `npm install`, `.env`/`.venv`/`.env.local` symlinked, NEVER
  `node_modules`). Its prompt is ONLY the PLAN path, the UAC path, the slice id and the phase -
  the files are the contract. In Phase 2 it makes the tester's red tests green; it never authors
  or deletes a test.
- **`reviewer`** (opus) + **`security-reviewer`** (opus) + browser verification (`tester`):
  Phase 3, run in **parallel**, once per lane, not per slice. `reviewer` runs the hard-fail rules,
  the DoD gate and a **kill test** (disable the implementing branch for 2-3 UAC lines, the test
  must go red). `security-reviewer` runs only when the diff touches its trigger paths (auth, RBAC,
  tenant scoping, public/API-key gateways, uploads/storage, secrets, SQL source). Optional
  `/codex-review` for a cross-model second opinion on large diffs.
- **`guide-writer`** (sonnet): after review passes, when the lane touched a consumer-visible
  contract (public gateway, sink payload) - updates the ONE guide file for that contract.
- **Model routing**: execution agents run on Sonnet; review + planner on Opus. Escalate a single
  spawn to Opus (`model: "opus"` on the Agent call, never by editing the agent files) only for
  tangled architecture, a bug that survived a Sonnet pass, a critical security review, or drift
  control (a Sonnet coder that rewrote the plan). Never spawn subagents on Fable. Name the reason
  in the brief.
- Trivial one-file changes may run inline in the main session; say so instead of silently
  absorbing a real slice.
- **Every coder/tester brief MUST embed PRINCIPLES.md's Design mandates + DoD gate +
  hard-fail rules** (CLAUDE.md "Agents-team orchestration") - a subagent starts with zero
  project memory.

## The pipeline

### Step 1 - Grill

`mattpocock-skills:grilling` - grill the user on the design, frontend AND
backend, before any code or file is written. Resolve every branch of the
decision tree. For terminology/domain-model questions that surface mid-grill,
run `mattpocock-skills:domain-modeling` to pin the vocabulary before continuing.

### Step 2 - UAC, then plan (the contract)

**UAC first.** Write
`documentation/plans/sprint-<N>/<NN>-<feature>-acceptance-criteria.md`:
independently-verifiable Given/When/Then ACs, each with an id, grouped by
slice/phase, tagged `[BE]`/`[FE]`/`[E2E]`/`[T]`. Use any existing
`*-acceptance-criteria.md` under `documentation/plans/` as the reference format.

**Then** the plan: `documentation/plans/sprint-<N>/<NN>-<feature>.md` - the
design that fulfils the UAC. **No plan ships without its UAC file.** One plan +
one UAC file per feature, numbered sequentially within the sprint folder.

Defer-items go to `documentation/backlogs/backlog.md` (register table: `ID ·
Title · Source plan link · Priority · Status`).

If the open question is "which of these designs feels right" rather than "what
should we build", run `mattpocock-skills:prototype` first and **throw the
result away** - it isn't built to this repo's layering rules (Resource shell,
Service-Repository, tenant scoping) and must not become the shipped code.

### Step 3 - Review the plan

Render the plan with **`lavish-axi`** (`.lavish/<sprint>-<NN>-<slug>.html`, playbooks `plan` +
`input`, this app's design tokens) so the user marks it up in the browser, `lavish-axi poll`
for the feedback, then `mattpocock-skills:grilling` on the plan itself. Grill before code,
always. This step is mandatory, not optional.

### Step 4 - Component-library discipline (applies throughout)

Reuse before inventing. A new variant is a prop/mode on the existing shared
component (`components/platform/{resource-list,resource-form,...}`, `SearchSelect`,
`MultiSelect`, `ClampedText`, `FlowCanvas`, …), never a parallel one-off. Check
PRINCIPLES.md "Design mandates" before adding any new UI primitive.

### Step 5 - Phase 1: frontend-first, mocked

UI → hook → service → **mock**. No backend code. No tests yet - the shape may
still shift.

Tune every state: loading, empty, error, partial, success. Document the
expected API contract at the top of the service file (backend phase must match
it exactly). Follow the Resource shell contract for any list/form
(PRINCIPLES.md "Resource shell for every list/form").

Verify in a real browser via the `agent-browser` CLI (headless; the former E2E runner is retired
entirely - user ruling 2026-09-04, plan 23 D15: no browser MCP, no ad-hoc E2E-runner script,
no `e2e/*.spec.ts`), navigating by **sidebar/UI clicks** - never a deep URL, real
users don't know URLs. Check console messages. Screenshot the golden path and edge cases at
**375px AND 1280px** (responsive mandate). Close the browser session when done.

### Step 6 - Phase 2: backend wiring, test-FIRST

Models → migration → schema → service → route (Service-Repository layering),
matching the Phase 1 contract exactly. Then swap the mock for the real
`api-client` call at the service boundary - a one-line change.

**Tester writes the red tests FIRST.** Before the coder opens the slice, the `tester` agent
gets the UAC, the Phase 1 contract block and the captain's test list, writes the failing tests
with no implementation to look at, confirms each fails for the right reason, commits them.
**Then the same lane `coder` makes them green** (continued via message, not respawned).

**Red → green → refactor, not test-after.** `mattpocock-skills:tdd` drives this
loop, scoped to this phase only (never the whole feature - see the override
above). Write the failing test, watch it fail for the right reason, implement
the minimum, refactor green. Applies to every route (happy + auth-denial +
validation), every service branch, and above all to deterministic engines
(status/rule/template/workflow/form/import/terminology), whose golden-set
numbers are written as failing tests first.

Tests land here, never deferred: pytest + httpx (backend, **Postgres only, never
sqlite** - CLAUDE.md "DB = Postgres everywhere"), Vitest + RTL (frontend), one
recorded `agent-browser` run per user flow (real clicks from the sidebar, never
a typed URL, 375 AND 1280, evidence under
`documentation/plans/sprint-<N>/<NN>-evidence/<slice>/` with a README run log).
Re-verify live against the running stack - `rm -rf .next && npm run build`
before any live check (PRINCIPLES.md "Ops quick-reference"; a stale `.next`
renders the old build).

If something breaks and the fix isn't obvious, use
`mattpocock-skills:diagnosing-bugs` before guessing.

### Step 7 - Definition of Done gate

Before calling the slice done, check PRINCIPLES.md's Definition of Done gate in
full:
1. Mock swapped to real, verified showing real data.
2. Existing rows/tenants backfilled (new column/engine on an existing entity).
3. No hardcoded lookup of a tenant-editable key.
4. New permission → grant sweep for already-provisioned tenants.
5. Verified from the user's perspective - real clicks, real data, fresh build,
   **375px AND 1280px**, correct ports (3001 FE / 8001 backend).

### Step 8 - Review, in parallel

Once the coder is green for the whole lane, run `reviewer` + `security-reviewer` (when in
scope) + the `tester`'s browser verification **in parallel, once per lane**. The `reviewer`
agent (Opus, `.claude/agents/reviewer.md`) is the primary pass: brief it with the branch, the
diff range, the plan + UAC paths and the hard-fail list. NEVER the built-in `code-review`
skill: it forks on the main session's model (Fable) and spawns 20+ Fable verifiers.
`mattpocock-skills:code-review` (parallel Standards + Spec review) is a second lens only if
it is run as a Sonnet/Opus agent, not a fork. Then
`/codex-review` (this repo's ported skill) for a cross-model second opinion on
risky or large diffs. Apply findings via `simplify` or `--fix`.

Reviewer checks PRINCIPLES.md's Code-review hard-fail rules plus the DoD gate
above - not just correctness.

### Step 9 - Ship

Branch per feature: `sprint-<N>/<feature>` (PRINCIPLES.md step 8). The user may
be coding concurrently in the main checkout - run `git status` immediately
before any branch/merge/rebase operation, never assume the tree is clean
(CLAUDE.md "The user codes concurrently in the main checkout"). Merge to `main`
only after review passes. Hand off on a prod build (`npm run build && npm
start`), never a dev server.

For work parked mid-flight while switching to another plan's branch, follow
CLAUDE.md "Concurrent plans": a `wip(...)` commit, then finish/review/merge from
a git worktree (`.claude/worktrees/<name>`, with the gitignored backend `.env`
and frontend `node_modules` symlinked in) so the main checkout stays on the
active plan.

## Skill map (quick reference)

| step | skill | executor |
| ---- | ----- | -------- |
| 1 grill | `mattpocock-skills:grilling` | main session (user in loop) |
| 1b terms shifting | `mattpocock-skills:domain-modeling` | main session |
| 2 UAC + plan | manual - files are the contract | main session (plan mode) |
| 2b design options | `mattpocock-skills:prototype` (throwaway) | main session |
| 3 plan review | `lavish-axi` (mandatory) then `mattpocock-skills:grilling` | main session (user in loop) |
| 5 Phase 1 FE mock | `agent-browser` CLI to verify (headless) | `coder` agent (worktree if concurrent) |
| 6 red tests | UAC + contract block + captain's test list, no implementation | `tester` agent, BEFORE the coder |
| 6 Phase 2 TDD | `mattpocock-skills:tdd` (scoped to backend phase) | the lane `coder` agent (same instance) |
| 6 hard bugs | `mattpocock-skills:diagnosing-bugs` | main session or `coder` agent |
| 8 review | `reviewer` agent on Opus (never the built-in `code-review` fork) + kill test, then optional `/codex-review` | `reviewer` agent, parallel with `security-reviewer` + tester browser verify |
| 8 security review | trigger paths in `.claude/agents/security-reviewer.md` | `security-reviewer` agent |
| 8 contract guide | ONE guide file per contract | `guide-writer` agent, after review |
| periodic | `mattpocock-skills:codebase-design` | main session |
| context capture | `mattpocock-skills:research` | main session or background agent |

## Design-skill slots (plan 23, `docs/reference/design-language.md` section 8)

Where the installed animation/design skills plug into the pipeline above - a slot fires
whenever the feature touches UI, not on every feature:

| Step | Skill | Mode |
| ---- | ----- | ---- |
| 1 grill | `animation-vocabulary` | Naming only |
| 2 UAC | `find-animation-opportunities` | Read-only; capped output becomes ACs or an explicit no-motion list |
| 5 Phase 1 FE mock | `animate` | Decision gate for any new motion added in Phase 1 |
| 8 review | `emil-design-eng` | Before/After/Why table on every UI diff |
| 8 review | `review-animations` | Only when the diff touches motion. Runs as ONE `general-purpose` agent on Opus - **never** the built-in `/code-review` fork, and never delegated to the `reviewer` agent's own pass (they check different things: `reviewer` = correctness + hard-fails, `review-animations` = feel) |
| Any new FE dependency | `pick-ui-library` | First - repo picks already made: `motion`, `sonner`, `vaul`, `@dnd-kit` |
| Periodic | `improve-animations` | - |

Not used here: `animate-expo`, `write-swift`, `webapp-testing` (idle for this stack, D15).

## Related

- `PRINCIPLES.md` - the binding contract this skill executes (governs on conflict)
- `docs/reference/design-language.md` - tokens, motion, primitives roster, decisions D1-D16
- `CLAUDE.md` - the detailed per-engine reference, conventions, lessons learned
- `documentation/development_process/AI_Agent_Orchestration_Guide.md` §6 - Test
  Execution Report format
- `documentation/development_process/EMS_Developer_Governance_Framework.md` -
  module/Service packaging rules
- `documentation/plans/sprint-<N>/` - UAC + plan files per feature
- `documentation/backlogs/backlog.md` - deferred-work register
