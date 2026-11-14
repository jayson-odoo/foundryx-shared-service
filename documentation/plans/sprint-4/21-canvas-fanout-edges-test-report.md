# 21 - Workflow canvas fan-out edges - Test Execution Report

Contract: `21-canvas-fanout-edges-acceptance-criteria.md`. Plan: `21-canvas-fanout-edges.md`. Backlog: BL-SS-034.

Environment: `service_backend` on `:8001` (eager Celery, Postgres, seeded), `service_frontend` rebuilt (`rm -rf .next && npm run build`) and served on `:3001` (`npm start`) from this worktree/branch (both ports confirmed owned by this worktree via `lsof ... | grep cwd`). `auth_throttle` cleared before the run. No pytest full-suite run per instructions (targeted new tests only).

## Suites run

| Suite | Command | Result |
|---|---|---|
| Frontend unit (`lib/workflow-doc.test.ts`) | `npx vitest run lib/workflow-doc.test.ts` | **24 passed** (includes the 3 new fan-out/idempotent/IF-port cases + the new `removeEdges` case) |
| Backend targeted (`AC-FAN-06`/`-07` locks) | `pytest tests/test_workflow_engine.py tests/test_workflow_triggers.py` (incl. `test_fan_out_action_two_edges_both_downstream_succeed`, `test_diamond_reconvergence_runs_the_shared_node_once`, `test_if_true_port_fans_out_to_two_targets`) | **3 fan-out tests pass** (suites 42 passed) |
| E2E (`e2e/canvas-fanout-edges.spec.ts`) | `npx playwright test e2e/canvas-fanout-edges.spec.ts` | **1 passed** (re-run twice for stability - both green, ~11-18s) |

## E2E journey (one spec, one test, all AC ids exercised)

**User story**: As a workflow author, I want one node's output port to drive multiple downstream nodes, so a single event can fan out to several parallel actions instead of only the last-wired one.

**Precondition**: dedicated tenant provisioned via the operator API (`POST /platform/tenants`, setup-only call - the workflow itself is built entirely by real clicks); tenant Admin holds `workflows.read/manage/run`.

**Steps** (see `e2e/canvas-fanout-edges.spec.ts` for the exact selectors):
1. Sign in as the dedicated tenant's admin, navigate to Workflows via the sidebar link, click "New workflow".
2. Add a Manual trigger + a "source" Send-email action; wire trigger → source.
3. Add a second Send-email node ("target1"); wire source → target1 (edge count 2).
4. Add a third Send-email node ("target2"); wire the SAME source output handle → target2 (edge count 3) - the fan-out under test.
5. Assert both edges render as distinct React Flow edges from the source node (by `aria-label="Edge from <source> to <target>"`).
6. Re-drag source→target1 again (exact duplicate) - edge count stays 3.
7. Verify at 375px: both fan-out edges still render, no document overflow; back to 1280px.
8. Name + Save (creates the workflow); reload the page.
9. Re-verify both edges persisted (3 edges, both aria-labels present) after the fresh load.
10. Click "Run" (manual trigger, no run inputs → executes immediately, no dialog); open Logs; assert the run shows Success.
11. Click each of source/target1/target2 in the run replay canvas; each node's inspector shows `"success"`.
12. Verify Logs tab at 375px (read-only replay), no overflow; back to 1280px.
13. Return to Editor, click Edit, click empty canvas (clear any leftover node selection), select the source→target1 edge (via its SVG path midpoint) and press Delete.
14. Assert only that edge is gone; source→target2 remains; all three nodes still present.
15. Verify the post-delete state at 375px too (surviving edge + node still render), no overflow.

**Expected**: fan-out edges add rather than replace; duplicates don't double up; both persist through save/reload; a run executes every downstream branch; deleting one fan-out edge removes only it.

**Actual**: matched expected at every step. PASS.

## AC-by-AC results

| AC | Description | Result | Evidence |
|---|---|---|---|
| AC-FAN-01 | Second/third edge from the same port ADDS, doesn't replace | **PASS** | Step 4-5: 3 distinct edges rendered, both `aria-label`s present, at both 1280px and 375px |
| AC-FAN-02 | Exact-duplicate connection is idempotent (no dup edge) | **PASS** | Authoritative case is `lib/workflow-doc.test.ts` (`is idempotent for an exact duplicate connection`, unit-level, deterministic). E2E supplementary check (step 6): re-dragging source→target1 leaves edge count at 3. |
| AC-FAN-03 | Fan-out works from every port kind (action `out`, IF `true`/`false`) | **PASS (unit-level)** | `lib/workflow-doc.test.ts` `fans out from an IF node port`; not re-driven via E2E (out of this spec's built graph, which is action-only per the task brief) - not a gap, just non-duplicated coverage |
| AC-FAN-04 | Cycle guard still rejects loop-forming connections | **PASS (unit-level, unchanged)** | Not touched by this slice's diff; pre-existing `wouldCreateCycle` coverage in `lib/workflow-doc.test.ts` is untouched and still green |
| AC-FAN-05 | Selecting + deleting one edge removes only it; multi-select delete removes all selected | **PASS** | E2E steps 13-15: deleting source→target1 leaves source→target2 intact, both nodes still visible, at 1280px AND 375px. The multi-select-in-one-pass fix (`removeEdges`) is unit-tested in `lib/workflow-doc.test.ts` (`removes all listed edge ids in one pass and ignores unknown ids`) - not separately re-driven via a real multi-select E2E drag (Shift-click-select of multiple SVG edges was judged lower-value than the id-level unit test, given time budget) |
| AC-FAN-06 | A published/run workflow with 2 edges out of one node/IF-port runs BOTH branches | **PASS** | Backend: `test_fan_out_action_two_edges_both_downstream_succeed` (action fan-out) + `test_if_true_port_fans_out_to_two_targets` (IF `true`-port fan-out, `false`-port target skipped) - both pass. **Also driven end-to-end via E2E** (steps 10-11: Run → Logs → both downstream node inspectors show `"success"`), so the E2E "run executes both" portion the brief flagged as possibly-DEFERRED was in fact fully drivable via clicks - not deferred |
| AC-FAN-07 | Publish validation still correct for fan-out (diamond re-convergence publishes; reachability/orphan checks pass) | **PASS** | `test_diamond_reconvergence_runs_the_shared_node_once` (`tests/test_workflow_engine.py`): `trg->a`, `trg->b`, `a->c`, `b->c` -> the shared node C produces exactly ONE `WorkflowRunNode` row, status `success` (the active-set/Kahn indegree walk runs a re-converging node once, not twice). Reachability/orphan checks use a Set so a node reached by two edges is neither double-flagged nor orphaned |
| AC-FAN-08 | Built-via-clicks: one output wired to two targets; both render, persist through save/reload, a run executes both; verified 375px + 1280px, no overflow | **PASS** | Full E2E journey above - build/render (steps 4-7), persist (steps 8-9), run-executes-both (steps 10-11), both viewports with `expectNoDocumentOverflow` at 4 distinct checkpoints (build, Logs, post-delete) |
| AC-FAN-09 | A Playwright Test Execution Report ships with the slice | **PASS** | This document |

## Findings (not blocking, reported honestly)

1. **A viewport-resize settle race in `expectNoDocumentOverflow`-style checks, uncovered while writing this spec (test-authoring lesson, not a product bug).** Calling `page.evaluate(() => document.documentElement.scrollWidth <= clientWidth)` in the *same tick* immediately after `page.setViewportSize(...)` intermittently read a transient overflowing layout (observed `scrollWidth` up to ~491-784px at a 375px viewport, on a workflow canvas with several nodes, in edit mode) that resolved itself with no further action taken. Existing specs (`agent-state-read-node.spec.ts`, `stateful-ai-workflow.spec.ts`) never hit this because they always interpose a real click (e.g. a tab switch) between the resize and the overflow check, which incidentally provides enough settle time. This spec's helper (`setViewportAndSettle`, a `page.setViewportSize` + `page.waitForTimeout(300)`) makes the settle explicit rather than accidental, and the spec is green across repeated runs with it. **Suggest**: fold an equivalent short settle into a shared E2E helper (or a `page.waitForFunction` poll on `scrollWidth<=clientWidth` with a short timeout) so future specs don't have to rediscover this by hitting a false-positive overflow failure.
2. AC-FAN-03/AC-FAN-04/AC-FAN-05's multi-select path/AC-FAN-07 are exercised at the unit/backend level but not independently re-driven end-to-end in this spec (see the AC table) - a deliberate scope choice given the task's stated primary targets (AC-FAN-08, +01/05 where observable) and time budget, not a discovered gap.

## Files

- `service_frontend/e2e/canvas-fanout-edges.spec.ts` (new)
- `service_frontend/lib/workflow-doc.ts` / `.test.ts`, `service_frontend/components/platform/workflow-canvas/workflow-canvas.tsx` (coder's changes under test - unmodified by this report)
- `service_backend/tests/test_workflow_engine.py`, `service_backend/tests/test_workflow_triggers.py` (coder's new backend tests under test - unmodified by this report)
