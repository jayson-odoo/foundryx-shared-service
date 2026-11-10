# 20 - Read-only Agent State workflow node - Test Execution Report

Contract: `20-agent-state-read-node-acceptance-criteria.md`. Plan: `20-agent-state-read-node.md`.
Branch `sprint-4/agent-state-node` (worktree `.claude/worktrees/stateful-ai`). Date 2026-08-30.

## Environment

| Piece | Value |
|---|---|
| Backend | FastAPI on `:8001` from the worktree (`CELERY_TASK_ALWAYS_EAGER=true`, `CODE_RUNNER_URL=http://localhost:8011`), Postgres `foundryx_service` |
| Frontend | `rm -rf .next && npm run build && npm start` on `:3001` from the worktree (clean prod build) |
| Ports | `:3001` confirmed owned by this worktree's `next-server`; `:8001`/`:8011` confirmed owned by this worktree's Python processes (`lsof -p $(lsof -ti :PORT) \| grep cwd`) |
| LLM | dev stub provider (`stub-model-1`); the E2E's own AI agent is bound to a dev-flagged connection (see Environment issue #2 below) so the run needs no real API key |
| Demo login | not used directly - the E2E provisions its own dedicated tenant per the spec-isolation rule |

## Environment issues hit (both fixed before/during this pass, neither is a product-code bug in this slice)

1. **DB one migration behind (`run_heartbeat_s4` not applied).** The worktree's Postgres was stamped at `code_action_s4`; `workflow_runs.heartbeat_at` (added by plan 19's `run_heartbeat_s4` migration) was missing. Every request touching `workflow_runs` (e.g. opening the workflow list, saving a new workflow) threw an unhandled `psycopg2.errors.UndefinedColumn`, which - because it propagated as a raw ASGI failure rather than a clean HTTP error - showed up in the browser as a misleading **CORS error** on the `POST /workflows` request (a classic "no response ⇒ no CORS headers ⇒ browser blames CORS" symptom, not an actual CORS misconfiguration). Fixed with `alembic upgrade head` against the live worktree DB (`code_action_s4 -> run_heartbeat_s4`). Not this slice's bug - a stale DB from before plan 19's last migration landed; flagging per the CLAUDE.md "`create_all` never ALTERs an existing table" gotcha for the next person who hits it.
2. **A connection-less AI agent does not stub in this environment.** `AiClient.resolve_for_agent` only falls back to the deterministic stub when *no* LLM connection exists anywhere (tenant or platform); this environment's PLATFORM tenant carries a real LLM connection (`GRILL_API_KEY`/`GRILL_API_PROVIDER=google`, seeded for the Ideation/grill feature). So a plain `POST /ai/agents` with no `connectionId` (the pattern used by the sibling `omnichannel-ai-workflow.spec.ts` setup, which never actually *runs* the workflow) fails at run time with `"This agent's AI connection is missing or was removed - pick another connection on the agent."`. Worked around test-side (no product change) by creating a real-provider (`gemini`) connection via `POST /integrations/connections` with `credentials.dev: "true"` (the same dev-flag `is_dev()` checks, mirroring the seeded demo workflow's own stub-connection pattern) and binding the agent to it at creation. Documented here so a future E2E that needs a live run of `ai_agent.run` reuses this pattern instead of rediscovering it.

## Suites

| Suite | Result |
|---|---|
| `tests/test_agent_state_read_node.py` | 13 passed |
| Full backend suite (`python -m pytest -q`, worktree, ~20 min) | 1916 passed, 1 skipped, 18 deselected, 35 failed - all 35 in `tests/test_autocount_pipeline.py`, pre-existing/unrelated to this slice (`sqlite3.OperationalError: unknown database app_ideation` when that file runs - an autocount/ideation cross-module schema-attach gap in this env, reproduced identically running that file alone; zero failures anywhere in `workflow_engine`/agent-state code) |
| Frontend Vitest (`npm test -- --run`, full) | **151 files / 1213 tests passed**, 0 failed |
| `lib/workflow-doc.agent-state-read.test.ts` + `node-config-drawer.agent-state-read.test.tsx` | 4 + 3 = 7 passed (included in the 1213 above) |
| `e2e/agent-state-read-node.spec.ts` (Playwright, live stack, real clicks) | **1 passed** (~10-12s); re-run 5x total (solo x2, `--repeat-each=3` in parallel) - all green, no flakes after the fixes below |
| `npx eslint e2e/agent-state-read-node.spec.ts` | clean |

## Spec-building notes (debugging trail, kept for the next agent)

- The sidebar's "Workflows" parent heading and its "All workflows" child link both render through the terminology-plural resolver (`labelPlural('workflow')` → "Workflows" by default, no override on a fresh tenant) - so on a **freshly-provisioned** tenant both nodes share the accessible name "Workflows", unlike the literal "All workflows" text the config declares. `openWorkflows()` in this spec disambiguates the child anchor by `href="/workflows"` rather than by name.
- React Flow's "Fit View" is CSS-animated (300ms); a handle-drag immediately after adding a node without settling produced a flaky `0` edges. `addNode()` now waits ~400ms after Fit View, and the connect helper retries the drag once before failing.
- `waitForURL(/\/workflows\/[^/]+(\?|$)/)` is a **false-positive trap** on a workflow still at `/workflows/new` - `[^/]+` also matches the literal `new` segment, so the assertion can "pass" before Save actually completes. Tightened to `/\/workflows\/(?!new)[^/?]+/`.

## AC matrix

| AC | Result | Evidence |
|---|---|---|
| AC-ASR-01 | PASS | E2E: palette search "Read Agent State" surfaces `palette-ai_agent.read_state` (Actions category) on a dedicated tenant with no module installed - core, no gate. `lib/workflow-doc.agent-state-read.test.ts` pins the catalog entry (Actions, single `agentNode` field). |
| AC-ASR-02 | PASS | E2E: before any wiring, the read node's Agent combobox opens to 0 options + "No matches." (never a free-text fallback - the field is a picker). After wiring `ai_agent.run -> ai_agent.read_state`, the SAME combobox lists "AI Agent" and selecting it succeeds. FE unit (`node-config-drawer.agent-state-read.test.tsx`) additionally asserts the reachability warning toggles off once a stateful agent is upstream. |
| AC-ASR-03 | PASS | E2E: the IF node's condition-builder Fact picker (searching "exists") lists "State exists" (the reserved diagnostic) grouped under the read node; the downstream Send-email Body field's `{ }` picker lists `nodes.<readNodeId>.task` (the agent's stateful field) distinctly from the AI Agent node's own `task` output one hop closer. FE unit `readStateOutputParams` test pins fields+diagnostics shape. |
| AC-ASR-04 | PASS (unit) | `node-config-drawer.agent-state-read.test.tsx`: `readStateOutputParams` returns only the newly-selected agent's fields when the selection changes, and only the 3 reserved diagnostics when no agent is selected. Not separately re-driven via E2E clicks (time-boxed) - the single E2E journey exercises one selection end-to-end; switching agents mid-build was left to the unit test per the AC's own "diagnostics-only on unset" wording, which the unit test covers directly. |
| AC-ASR-05 | PASS | `tests/test_agent_state_read_node.py::test_read_agent_state_flattens_accepted_fields_and_diagnostics`. Live: the E2E run's node inspector (Logs replay) showed `"task": "Launch the landing page"`, `"stateRevision"`, `"pendingField"`, `"exists": true` on the read node. |
| AC-ASR-06 | PASS | `test_read_agent_state_no_row_yields_defaults_and_run_continues` + `test_read_agent_state_never_writes_or_bumps_revision` (BE). |
| AC-ASR-07 | PASS | `test_read_agent_state_is_tenant_scoped` + the FE/BE publish-gate parity (a target must exist in THIS graph). |
| AC-ASR-08 | PASS | `test_read_agent_state_namespace_isolation_test_vs_prod`. |
| AC-ASR-09 | PASS | `test_executor_reads_durable_state_on_a_branch_that_never_ran_the_agent` - structural reachability, not executed-this-pass. |
| AC-ASR-10 | PASS | BE `test_definition_issues_blocks_read_state_without_a_stateful_target` / `..._allows_read_state_referencing_a_stateful_agent` / `..._blocks_read_state_referencing_a_non_stateful_agent`; FE parity `workflow-doc.agent-state-read.test.ts` (`blocks publish when no agent is selected` / `...when the referenced node is not a stateful agent`). E2E covers only the **happy path** per the task's own scope ("Assert publish succeeds with a valid selection") - Publish went through cleanly to `v1` with a valid `agentNodeId`; the reject path is not separately click-driven (fully covered by the BE+FE unit matrix above). |
| AC-ASR-11 | PASS | `test_read_agent_state_missing_or_removed_agent_raises_action_error`, `test_run_workflow_marks_read_state_failed_and_skips_downstream_on_missing_agent`, `test_debug_execute_marks_read_state_failed_without_raising_and_never_runs_the_target` - all `ActionError`, never a 500. |
| AC-ASR-12 | PASS | E2E: Logs tab → clicked the `ai_agent.read_state` node in the run-replay canvas → `node-inspector` Output JSON shows the accepted `task` field + `stateRevision`/`pendingField`/`exists`. |
| AC-ASR-13 | PASS | E2E full journey (see below) built entirely via clicks on a dedicated tenant: manual trigger → stateful `ai_agent.run` (`task`, stateful) → `Read Agent State` → IF on `nodes.<readNode>.exists` → Send-email (custom, body merged from `nodes.<readNode>.task`). Published, ran with `sessionId`/`message` inputs, and the Logs replay showed the IF's TRUE branch executed (`email.send` node status "success", with the resolved body `"Recorded task: Launch the landing page"` - matching the value the AI Agent node itself accumulated). Verified `expectNoDocumentOverflow` at 1280×900 (desktop) and again at 375×812 (mobile) on both the Editor and Logs tabs. |
| AC-ASR-14 | PASS (by inspection) | `lib/workflow-catalog.ts` entry description: "Read the current saved values from an earlier AI Agent." - states what the node is, not how to use it; no hint/instructional copy added to the canvas or drawer for this node. |
| AC-ASR-15 | PASS | This report. |

## Journey (E2E, single spec, dedicated tenant `e2e-asr20-<ts>`)

1. Provisioned a fresh tenant via the platform API (setup only), created a `gemini`-provider connection flagged `dev` (test-side workaround, see Environment issue #2) and an AI agent bound to it (setup only).
2. Logged in as the tenant's admin and opened Workflows via the sidebar (real clicks) → "New workflow".
3. Added a **Manual** trigger with two run inputs (`sessionId`, `message`).
4. Added **Read Agent State** unwired first and confirmed its Agent picker is empty (AC-ASR-02 negative case) - proving the palette entry from AC-ASR-01 in the same pass.
5. Added **AI Agent**, wired Manual → AI Agent, configured it (agent pick, instructions, `{{ trigger.input.message }}` message, one **stateful** output param `task`).
6. Wired AI Agent → Read Agent State, re-opened the Agent picker (now lists "AI Agent"), selected it (AC-ASR-02 positive case).
7. Added a **Condition (IF)** node, wired Read Agent State → IF, added a condition on the picked "State exists" fact (AC-ASR-03), leaving the default "is yes" operator.
8. Added a **Send email** (custom) node on the IF's TRUE port, set Subject/To, and used the `{ }` dynamic-content picker on Body to insert `nodes.<readNodeId>.task` (AC-ASR-03), disambiguated from the AI Agent node's own same-named output.
9. On Settings: named the workflow, switched Execution mode to "Serialized by key", set the Correlation key to `{{ trigger.input.sessionId }}`, and Saved (created).
10. Published from the Editor tab - succeeded with no publish-gate errors (AC-ASR-10 happy path), version bumped to `v1`.
11. Ran the workflow with `sessionId`/`message` inputs via the Run dialog.
12. In Logs: the run showed Success, the correlation key was visible, the Read Agent State node's inspector showed the accumulated `task` + diagnostics (AC-ASR-12), and the Send-email node showed a `success` status with the correctly-merged body - proving the IF routed to the TRUE branch on the read node's `exists` fact (AC-ASR-13).
13. Re-verified the Editor and Logs tabs at 375×812 with no document overflow.

## Deferred / follow-ups

- None new. AC-ASR-04's agent-switch behaviour is unit-tested (see above) rather than separately E2E-driven; this is a scope choice for time, not a defect - flag if the team wants an additional click-driven regression for it.
- The two environment issues above are documented for reuse, not filed as backlog items (issue 1 is a one-time DB-state fix; issue 2 is a documented test-authoring pattern, not a product gap - `ai_agent.run`'s connection-resolution behaviour is deliberate, per `app/ai/client.py`'s own comments).
