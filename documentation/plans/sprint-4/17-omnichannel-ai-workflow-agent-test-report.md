# 17 - Omnichannel × AI Agent workflow nodes - Test Execution Report

Keyed to `17-omnichannel-ai-workflow-agent-acceptance-criteria.md` (AC-OA ids).
Executed 2026-08-14 on branch `fm/fs-omniflow-b1` (isolated worktree).

## Environment

- Backend: pytest + httpx, in-memory SQLite with `schema_translate_map` (repo conftest), Celery eager, stub LLM provider (`app/ai/stub.py`) - zero live API key anywhere, per the brief.
- Frontend: Vitest + React Testing Library (`vitest.config.mts`).
- Live-stack E2E: spec authored (`e2e/omnichannel-ai-workflow.spec.ts`); live run DEFERRED in this worktree - see "Deferred" below.

## Results by AC id

| AC | Tag | Result | Evidence |
|----|-----|--------|----------|
| AC-OA-01 | BE | PASS | `test_trigger_fires_for_any_channel` - run created, SUCCESS, payload carries the message |
| AC-OA-02 | BE | PASS | `test_trigger_filters_by_channel` - mismatched channel creates no run |
| AC-OA-03 | BE | PASS | context flattening asserted via `trigger_payload_json` + the end-to-end reply containing the AI output (`test_end_to_end_inbound_to_reply`) |
| AC-OA-04 | BE | PASS (by construction) | the emit sits inside `_handle_message`, reachable only after the pre-existing `ModuleRepository.is_active` gate at the top of `process_payload` - an inactive tenant's payload returns before any message handling |
| AC-OA-05 | BE | PASS | `test_dispatch_failure_is_isolated` - `notify_entity_event` monkeypatched to raise; inbound counters still report the message stored |
| AC-OA-06 | BE | PASS | `test_get_contact_found_and_not_found` |
| AC-OA-07 | BE | PASS | same test (not-found) + `test_get_contact_cross_tenant_rejected` |
| AC-OA-08 | BE | PASS | `test_send_message_success` - reply row created through `MessageService.send_message` |
| AC-OA-09 | BE | PASS | `test_send_message_csw_closed_fails` - `SendRejected` surfaces as `ActionError` |
| AC-OA-10 | BE | PASS | `test_ai_agent_run_structured_output_via_stub` - scripted stub structured output returned as the node output |
| AC-OA-11 | BE | PASS | `test_ai_agent_run_missing_agent` + `test_ai_agent_run_disabled_agent` |
| AC-OA-12 | BE | PASS | trace row asserted in `test_ai_agent_run_structured_output_via_stub` (`AiTrace` status ok) |
| AC-OA-13 | BE/T | PASS | `tests/test_omnichannel_workflow_triggers.py` - 12/12 green, incl. `test_publish_denormalizes_trigger_entity_type` and the end-to-end `test_end_to_end_inbound_to_reply` (inbound -> stub classify -> reply row) |
| AC-OA-14 | FE | PASS | `node-palette.test.tsx` - omnichannel entries hidden/shown per `isActive('omnichannel')`; `ai_agent.run` always listed |
| AC-OA-15 | FE | PASS | `node-config-drawer.omnichannel-ai.test.tsx` - channel SearchSelect with explicit "All channels" default |
| AC-OA-16 | FE | PASS | same file - mergeable contactId/message fields render with the dynamic-content picker |
| AC-OA-17 | FE | PASS | agent SearchSelect + `output-params-editor.test.tsx` (add/remove rows, string/number/boolean only, duplicate-key flagging) |
| AC-OA-18 | FE | PARTIAL | `aiOutputParams` feeds `upstreamGroups`/`runContextFacts` (implementation + drawer integration test); the full `{ }` picker journey is asserted by E2E journey ② (deferred live run) |
| AC-OA-19 | FE | PASS (by design) | no new surface - run inspector reuses the existing run-node views unchanged |
| AC-OA-20 | FE/T | PASS | 22 new Vitest tests; full frontend suite 142 files / 1160 tests green; eslint clean on all touched files |
| AC-OA-21 | BE | PASS (by inspection) | `seed_demo_ai_workflow` wired into both dev seed scripts behind `ENVIRONMENT=development`; the identical 3-node flow is executed end-to-end by `test_end_to_end_inbound_to_reply` |
| AC-OA-22 | E2E | DEFERRED | spec authored (journey ① in `e2e/omnichannel-ai-workflow.spec.ts`); live run deferred - see below |
| AC-OA-23 | E2E | DEFERRED | spec authored (journey ② - real-click build + publish); live run deferred - see below |

## Suite totals

- Backend: full `python -m pytest -q` = 1745 passed, 35 failed - ALL 35 failures are `tests/test_autocount_pipeline.py`, confirmed PRE-EXISTING by running the same file on a clean `origin/main` worktree (identical 35 failures, unrelated ESB module). Zero regressions from this branch.
- Frontend: `npx vitest run` = 142 files, 1160 tests, all passing.

## Review follow-up

Resolved findings from the follow-up review:

- Omnichannel workflow actions now require the tenant's module to be ACTIVE.
- Workflow metadata filters AI agent options by the caller's `ai_agents.read` permission.
- AI skill loading enforces tenant or sanctioned platform-tier ownership and verifies each active version belongs to its skill.
- AI output parameters now use a strict, shared frontend and backend contract for non-empty rows, canonical keys, uniqueness, and supported types.
- Contact output includes the canonical thread status in both backend and frontend workflow contracts.
- Workflow media output uses a signed, time-limited media URL.

Final validation:

- Backend focused PR tests: 137 passed.
- Focused frontend tests: 23 passed.
- ESLint, Python compile checks, and `git diff --check`: clean.
- `npm run build`: exit 0, 111/111 pages generated, with only existing warnings.

Live E2E execution and responsive verification at 375px and 1280px remain deferred below. They are not claimed by this follow-up.

## Deferred: live E2E run

Ports 3001/8001 are currently held by stale `next-server`/uvicorn processes whose cwd is a DELETED worktree in `~/.Trash` (`.Trash/foundryx/foundryx-shared-service/.claude/worktrees/s17`) - killing processes outside this isolated task worktree and reseeding the shared dev Postgres from this branch both violate the task's isolation rules, so the live run is handed to the stack owner. To execute:

1. `pkill -9 -f next-server` and free :8001 (the stale owners are the `.Trash` processes above - safe to kill from the primary checkout).
2. Backend: `ENVIRONMENT=development python -m scripts.init_db && uvicorn app.main:app --reload --port 8001` (seeds `chn-demo` + the demo AI workflow).
3. Frontend: `rm -rf .next && npm run build && npm start` (port 3001).
4. `npx playwright test e2e/omnichannel-ai-workflow.spec.ts`.

Responsive check (375px AND 1280px) for the new drawer editors rides the same deferred live pass - the editors reuse the existing drawer layout primitives (stacked rows, no fixed widths beyond the existing 28/32-unit selects), so no new horizontal-overflow surface is introduced.
