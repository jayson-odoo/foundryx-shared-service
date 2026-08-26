# 17 - Omnichannel × AI Agent workflow nodes - Test Execution Report

Keyed to `17-omnichannel-ai-workflow-agent-acceptance-criteria.md` (AC-OA ids).
Executed 2026-08-25 on branch `fm/fs-omniflow-b1` (isolated worktree).

## Environment

- Backend: pytest + httpx, in-memory SQLite with `schema_translate_map` (repo conftest), Celery eager, stub LLM provider (`app/ai/stub.py`) - zero live API key anywhere, per the brief.
- Frontend: Vitest + React Testing Library (`vitest.config.mts`).
- Live-stack E2E: verified with the isolated backend on port 8002 and frontend on port 3001; the existing 8001/Sorento stack was not touched.

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
| AC-OA-18 | FE | PASS | `aiOutputParams` feeds `upstreamGroups`/`runContextFacts`; the full `{ }` picker journey passed in the live AC-OA-23 build at 1280x800 and 375x812 |
| AC-OA-19 | FE | PASS (by design) | no new surface - run inspector reuses the existing run-node views unchanged |
| AC-OA-20 | FE/T | PASS | 22 new Vitest tests; full frontend suite 142 files / 1160 tests green; eslint clean on all touched files |
| AC-OA-21 | BE | PASS (by inspection) | `seed_demo_ai_workflow` wired into both dev seed scripts behind `ENVIRONMENT=development`; the identical 3-node flow is executed end-to-end by `test_end_to_end_inbound_to_reply` |
| AC-OA-22 | E2E | PASS | Live inbound-to-reply journey passed at 1280x800 in 22.5s and 375x812 in 24.0s; document overflow assertion passed at both sizes |
| AC-OA-23 | E2E | PASS | Live real-click build and publish journey passed at 1280x800 in 21.7s and 375x812 in 21.0s; document overflow assertion passed at both sizes. Final rerun evidence: the published workflow snapshot contains `message: "Classified: {{ nodes.act_9dlzkx.intent }}"` (the picker inserted the real upstream AI node token `nodes.act_9dlzkx.intent`), and the Settings surface showed current version `v1` after publish. |

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

## Live E2E and responsive verification

- Environment: `with_server.py` managed FastAPI on 8002 and Next on 3001 with `NEXT_PUBLIC_BACKEND_API_URL`, `BACKEND_API_URL`, and `PUBLIC_BASE_URL` set to `http://localhost:8002`, `ENVIRONMENT=development`, and `CELERY_TASK_ALWAYS_EAGER=true`. The run used one Playwright worker and the dev-seeded demo workflow.
- Desktop viewport: 1280x800. AC-OA-22 passed in 22.5s; final AC-OA-23 passed in 21.7s (wrapper elapsed 22.2s).
- Mobile viewport: 375x812. AC-OA-22 passed in 24.0s; final AC-OA-23 passed in 21.0s (wrapper elapsed 21.5s).
- The spec asserts `document.documentElement.scrollWidth <= document.documentElement.clientWidth` after each journey. The assertion passed at both viewports, with no horizontal document overflow.
- `with_server.py` stopped the temporary 8002/3001 processes after each run. Port 8001 and the unrelated Sorento process were not touched.
- E2E reliability adjustments are test-only: wait for initial page hydration before filling controlled sign-in fields, use stable handle test ids instead of React Flow class names, and save the new workflow through Settings before publishing from Editor. No product behavior was changed for the live gate.
