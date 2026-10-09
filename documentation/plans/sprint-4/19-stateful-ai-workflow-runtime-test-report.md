# 19 - Stateful AI workflow runtime - Test Execution Report

Contract: `19-stateful-ai-workflow-runtime-acceptance-criteria.md`. Plan: `19-stateful-ai-workflow-runtime.md`.
Branch `sprint-4/stateful-ai-workflow` (worktree `.claude/worktrees/stateful-ai`). Date 2026-08-30.

Slices: S0 (frontend contract + mocks) and S1 (stateful outputs + explicit clear) were built by Codex (issues #22/#23 closed). S2 (serialized runtime), S3 (Redis action), S4 (sandboxed Code action) and S5 (progress-update proof) were completed in this session.

## Environment

| Piece | Value |
|---|---|
| Backend | FastAPI on `:8001` from the worktree, Postgres `foundryx_service` at Alembic head `code_action_s4`, `CODE_RUNNER_URL=http://localhost:8011` |
| Frontend | `npm run build` + `npm start` on `:3001` from the worktree (clean `.next`) |
| Redis | native `redis-server` `:6379` |
| Celery | eager (`CELERY_TASK_ALWAYS_EAGER=true`) for the Playwright run; a second pass with `CELERY_TASK_ALWAYS_EAGER=false` + `celery -A app.workflow_engine.worker worker -Q workflow` + `celery -A modules.omnichannel.worker worker -Q omni` for the real lease/queue proof |
| Code runner | `CODE_RUNNER_ALLOW_ANONYMOUS=1 python -m code_runner` on `:8011` (`/health` ok, `runnerVersion 1.0.0`) |
| LLM | the dev stub provider (no key); the seeded agents are bound to the tenant's `stub` LLM connection |

## Suites

| Suite | Result |
|---|---|
| `tests/test_stateful_ai_runtime.py` (S1) | 26 passed |
| `tests/test_serialized_workflow_runtime.py` (S2) | 15 passed |
| `tests/test_redis_workflow_action.py` (S3) | 10 passed |
| `tests/test_code_runner_sandbox.py` (S4, real subprocess jail) | 19 passed, 1 skipped (`RLIMIT_AS` memory test runs on Linux only) |
| `tests/test_code_workflow_action.py` (S4) | 10 passed |
| `tests/test_stub_stateful_derivation.py` + `tests/test_progress_update_proof.py` (S5) | 5 + 4 passed |
| `tests/test_worker_module_boot.py` | 3 passed |
| Full backend suite (worktree, 39 min) | 1807 passed, 38 failed: 35 are `tests/test_autocount_pipeline.py` + drift tests that fail identically on the base branch (pre-existing, unrelated); the two drift failures caused by `correlation_key` and the one `test_scheduler_tick_fires_due_workflow` flake are fixed / pass in file context (25/25) after this report's commits |
| Frontend Vitest (full) | 1203 passed, 3 failed: 1 real flake in the Code editor diagnostics (incremental Lezer parse - fixed with `ensureSyntaxTree`, 3 consecutive green runs), 2 `timezone-card` timeouts that pass in isolation (pre-existing load flake) |
| `e2e/stateful-ai-workflow.spec.ts` (Playwright, live stack, real clicks) | 3 passed (10.6 s) |

## AC matrix

### Phase 1 - frontend contract (S0, Codex)

| AC | Result | Evidence |
|---|---|---|
| AC-SAR-01..13 | PASS | Codex S0 commits `89f6f61`/`ad70eaf` (Vitest: `run-dialog`, `node-config-drawer.omnichannel-ai`, `output-params-editor`, `workflow-doc.omnichannel-ai`, `workflow-validation`, `workflow-service.mock` tests); journey ③ checks Settings shows `Serialized by key` + key and the editor/Logs at 375/1280 with no document overflow |
| AC-SAR-58..61 | PASS | Code palette entry gated by `workflows.code`; CodeMirror editor + input mappings + output editor + capabilities list (now served from metadata `codeCapabilities`, mirroring `code_runner/policy.py`); runner-health warning + publish block wired to `metadata.codeRunnerAvailable` |

### Phase 2A - stateful AI Agent backend (S1, Codex; verified here)

| AC | Result | Evidence |
|---|---|---|
| AC-SAR-14..32 | PASS | `test_stateful_ai_runtime.py` (26): tenant-scoped repository/CAS, four patch operations, type/enum/evidence rejection, independent merge + provenance, clarification carry/resolve, schema evolution, explicit clear, no expiry, test namespace isolation, disabled/missing agent, stateless regression. Live: `workflow_agent_states` rows for the proof conversations (`{"task","status"}` accumulate, `pending_field` moves `status -> blocker -> null`, revision increments, cleared after confirmation) |

### Phase 2B - correlated serialized execution (S2)

| AC | Result | Evidence |
|---|---|---|
| AC-SAR-33/34 | PASS | `test_definition_v1_defaults_parallel_and_stateful_requires_serialized_key` + FE parity tests |
| AC-SAR-35 | PASS | `test_run_snapshots_resolved_correlation_key_once`; `workflow_runs.correlation_key(+digest)` migration `serialized_run_s4`; Logs show the key per run |
| AC-SAR-36 | PASS | `test_parallel_run_keeps_direct_dispatch_and_no_correlation_snapshot`; live: the parallel "Demo: classify & reply" runs went through `workflows.run_workflow` |
| AC-SAR-37 | PASS | `test_serialized_drain_is_fifo_and_scoped_to_one_key`; live non-eager: same-key runs `25.138-25.250` then `25.322-25.426` (no overlap), other key started `25.216` concurrently |
| AC-SAR-38 | PASS | Postgres rows are the queue; lease keys `foundryx:workflow:serialized:*` released after each drain (0 left) |
| AC-SAR-39 | PASS | `test_duplicate_wakeup_that_loses_lease_executes_nothing`, `test_duplicate_direct_execution_does_not_execute_run_nodes_twice` (`FOR UPDATE` + `status == pending` claim), `test_process_death_leaves_run_pending_for_redrive`, `test_lost_lease_stops_drain_and_leaves_rest_pending`, `test_recovery_redrives_each_oldest_pending_serialized_scope`; live: a duplicate wakeup returned in 4 ms (lease lost) |
| AC-SAR-40 | PASS | `test_redis_outage_leaves_serialized_run_pending` (no parallel fallback; operational error logged) |
| AC-SAR-41 | PASS | `test_repository_compare_and_swap_rejects_stale_revision` (S1) executed inside the serialized run |
| AC-SAR-42 | PASS | 15 S2 tests incl. token-owned Redis lease via `fakeredis[lua]` and the poison-run liveness guard |

### Phase 2C - generic Redis action (S3)

| AC | Result | Evidence |
|---|---|---|
| AC-SAR-43 | PASS | `test_keys_are_tenant_namespaced_and_reserved_prefixes_rejected` (two tenants, same logical key, distinct physical keys; `foundryx:` prefix rejected) |
| AC-SAR-44/45 | PASS | `test_set_get_delete_round_trip_with_optional_ttl`, `test_increment_is_atomic_integer_math`, `test_list_push_pop_length_honour_ends`, `test_ttl_validation_rejects_non_positive_and_non_numeric` (no partial mutation), publish-gate parity (`test_publish_validation_reports_redis_config_issues` + FE `workflow-doc.redis.test.ts`) |
| AC-SAR-46/47 | PASS | `test_run_failure_skips_downstream_and_log_hides_physical_prefix`, `test_outage_raises_action_error_without_leaking_physical_details` |
| AC-SAR-48 | PASS | all S3 tests use the injected `use_workflow_redis_client` seam |

### Phase 2D - sandboxed Code action (S4)

| AC | Result | Evidence |
|---|---|---|
| AC-SAR-62 | PASS | `code.run` ActionDef (language `python` only; `code_config_issues` rejects other languages, bad/duplicate input names, policy violations) |
| AC-SAR-63 | PASS | `test_worker_never_executes_source_locally` (poison source only reaches the fake client; `code_actions.py` has no interpreter entry point); runner is a separate stdlib-only image/process; compose gives it no DB/Redis/Fernet/provider env and an `internal: true` network |
| AC-SAR-64 | PASS | `test_policy_rejects_imports_reflection_io_and_missing_result` (11 cases), `test_denied_capabilities_fail_at_runtime_even_if_policy_slipped`, `test_child_has_no_environment_or_platform_reach` - all against the REAL subprocess jail |
| AC-SAR-65 | PASS (memory limit: Linux) | `test_wall_clock_timeout_kills_the_child`, `test_cpu_limit_terminates_a_busy_loop`, `test_output_console_and_source_limits`; `test_memory_limit_is_enforced_on_linux` is skipped on macOS (RLIMIT_AS unreliable there) and must run on the Linux runner image - the compose service also carries a 512m `mem_limit` |
| AC-SAR-66 | PASS | `test_worker_submits_rendered_inputs_and_flattens_validated_outputs` (undeclared dropped), `test_mistyped_or_missing_required_output_fails_only_the_code_node`, `test_malformed_results_fail_cleanly` |
| AC-SAR-67 | PASS | `runtime{input,stdout,stderr,durationMs,runnerVersion,termination}` on the node output (and under `input_json.runtime` on failure); `test_runner_failures_and_transport_errors_stay_bounded_and_redacted` |
| AC-SAR-68 | PASS | `workflows.code` CSV row + migration `code_action_s4` grant sweep (live: 105 Admin roles granted); `test_workflows_code_permission_gates_create_update_publish_and_run`, `test_http_boundary_returns_403_without_workflows_code`, `test_automated_triggers_skip_unstamped_code_versions` |
| AC-SAR-69 | PASS | `test_retry_executes_the_published_snapshot_not_a_later_draft`; `workflow_versions.code_authorized_by` stamped at publish |
| AC-SAR-70 | PASS | 10 action tests + 19 sandbox tests; live metadata reports `codeRunnerAvailable=true`, 5 capabilities |

### Phase 3 - progress-update proof (S5)

| AC | Result | Evidence |
|---|---|---|
| AC-SAR-49/50 | PASS | `seed_demo_progress_workflow` (dev only) - `test_seed_is_generic_nodes_only_and_serialized`; journey ③ finds only `omnichannel.message_received`, `ai_agent.run`, `if`, `omnichannel.send_message`, `ai_agent.clear_state` on the canvas |
| AC-SAR-51 | PASS | journey ① turns 1-2 ("What is the status?" then "What is the blocker?" after the short answer `blocked`); `test_two_turn_clarification_correction_and_fresh_after_clear` |
| AC-SAR-52 | PASS | journey ① turn 3 ("Actually it is completed" changes only status; confirmation carries `task: Launch landing page, status: completed`) |
| AC-SAR-53 | PASS | journey ② (rapid A1/B1/A2 - A's confirmation carries both contributions, B progresses separately) + the non-eager Celery pass above; `test_same_key_runs_are_ordered_and_state_accumulates` |
| AC-SAR-54 | PASS | journey ① turn 4 ("in progress" after the clear asks "What is the task?"); live state row revision 3 with `{}` |
| AC-SAR-55 | PASS (backend) | `test_downstream_failure_before_clear_retains_state_for_retry` (confirmation send raises -> `send_confirm` failed, `clear_state` skipped, state retained, retry confirms). Not driven through the browser: the seeded graph has no switchable failing node and the Foolproof-UI rule forbids seeding one |
| AC-SAR-56 | PASS | journeys ①-③ are real clicks from the sidebar (`/workflows` list -> workflow -> Logs/Settings/Editor) at 1280 and 375 (`expectNoDocumentOverflow` on Editor, Logs, Settings); screenshots `s19-{editor,logs}-{desktop,mobile}.png` (session scratchpad) |
| AC-SAR-57 | PASS | this report |

## Defects found and fixed during verification

1. Serialized runs failed `Unknown action "omnichannel.send_message"` under a real Celery worker while parallel runs succeeded: `wake_serialized_task` bypassed the lazy module-node boot that `fix/workflow-worker-module-boot` (3470a93, cherry-picked here) adds to `run_workflow_task`. Fixed + pinned by `test_wake_serialized_task_boots_module_nodes_before_draining`.
2. The seeded progress agent had no connection while the default tenant already carries a `stub` LLM connection, so `resolve_for_agent` refused it (Bi-D21). The seed now binds to an existing dev stub connection.
3. `correlation_key` tripped the storage-key drift gate (`*_key`); excluded with a reason in `_NON_STORAGE_KEY_COLUMNS`.
4. Run replay header overflowed at 375px once a correlation key rendered; the chip now wraps (`min-w-0 flex-wrap`, `max-w-full`).
5. Flaky Code-editor diagnostics: `syntaxTree` on an incremental Lezer parse produced a spurious "syntax error"; `ensureSyntaxTree` forces a complete parse.
6. Local Postgres: `foundryx_service` was owned by `sorento_crm`, so the `foundryx` role could not create in `public` and the AI-subsystem migrations had never applied (the `ai_*` tables existed only via `create_all`). Fixed locally by re-owning the database/tables and stamping `ai_msg_summary_s3` before `upgrade head` - an environment repair, not a code change.

## Deferred / notes

- Memory-limit escape test runs only on Linux (the deployed runner); compose additionally caps the container.
- A browser-driven AC-SAR-55 would need a deliberately failing node in the seed; covered by the backend proof instead.
- The `fix/workflow-worker-module-boot` commit was cherry-picked (`-x`) so the live proof could run; merging that branch later is a no-op for this file set.

## Code review round 2 - findings and fixes (2026-08-30)

The slice went through the `reviewer` agent (REQUEST CHANGES: 2 blockers + 6 should-fixes). All are closed on this branch; each fix ships with a red-first regression.

### Blockers

- **B1 - Code sandbox escape (AC-SAR-64).** A generator exposed `gi_frame`; the `f_back` chain walked out of the exec'd module into the harness, whose real builtins still held `__import__`, reaching `os.getcwd()`. Fixed with an HONEST layered model (a first attempt overclaimed the runtime layer "closes it twice" - a round-3 review falsified that; corrected here). GATE = the static AST policy (`code_runner/policy.py`: forbids frame/code/globals reflection attrs, `__`-subscripts, dunder format strings) - it rejects both the frame walk AND the `().__class__.__base__.__subclasses__()` -> `BuiltinImporter.load_module('posix')` route before they run (verified: policed `execute()` -> `termination="policy"`), which is what makes production safe. BOUNDARY = the subprocess jail (`sandbox.py` + deploy: empty env, cwd `/`, RLIMIT CPU/AS/FSIZE=0/NPROC=1/NOFILE, wall-clock kill, read-only non-root container on an internal-only network, `deploy/code-runner-seccomp.json` denying `connect()`). DEFENSE IN DEPTH = `harness._harden()` (neuter `__import__/open/exec/eval/compile`, evict `os/posix/socket/subprocess/ctypes/importlib/...` from `sys.modules`, clear `sys.meta_path`/`path_hooks`/`path`, strip globals) - closes the casual routes but NOT a guarantee (a subclass walk still reaches the importer class in-process; documented in the harness docstring). Regressions: `test_frame_walk_escape_is_closed_at_runtime_without_the_policy`, `test_hardening_closes_the_casual_bypass_routes`, `test_static_policy_is_the_gate_for_reflection_escapes`, `test_runtime_layer_alone_does_not_stop_the_subclass_walk` (pins the documented limitation), a real-reach `test_child_has_no_environment_or_platform_reach`, and the escape sources in the policy matrix.
- **B2 - `POST /workflows/{id}/debug` bypassed `workflows.code` (AC-SAR-68).** Debug re-executes the snapshot with scratch config (edited Code source included) under `workflows.run` alone. `WorkflowService.debug_execute` now takes the actor and `assert_code_permitted`s the snapshot; the router maps `WorkflowPermissionError -> 403`. Regression `test_debug_route_requires_workflows_code_for_code_bearing_runs`.

### Should-fixes

- **S3 - mid-run commits voided no-overtake (AC-SAR-37/39).** An action can COMMIT mid-run (`MessageService.send_message` does), so a hard death leaves the row RUNNING, not rolled back to Pending. Added `workflow_runs.heartbeat_at` (migration `run_heartbeat_s4`), renewed with the lease from `_LeaseHeartbeat`; the drain refuses to advance past a same-scope RUNNING row with a fresh heartbeat and a beat reaper (`reap_stale_running_serialized_runs`, wired into `redrive_pending_serialized_runs`) fails a stale one then wakes the scope. Regressions in `test_serialized_workflow_runtime.py` (live-running block, mid-run-commit crash, heartbeat renewal/write-failure isolation, claim stamps the heartbeat).
- **S4 - Redis key growth.** Every workflow-data key now carries a TTL: `set` defaults to `workflow_redis_default_ttl_seconds` (7d), keys born from increment/list-push get the default if unbounded, and an explicit TTL above `workflow_redis_max_ttl_seconds` (30d) is rejected at publish AND run. Amount parsing is a strict `^-?\d+$`. Documented in `docs/reference/workflow-engine.md`. Regression `test_every_workflow_data_key_carries_a_bounded_ttl`.
- **S5 - stub fallback in prod.** `resolve_for_agent`'s connection-less stub is gated to `environment == "development"`; other environments raise `LLMError`. The `dev`-cred path is unchanged. Regressions `test_connectionless_agent_stubs_only_in_development`, `test_agent_with_dev_credentials_still_stubs_in_production`.
- **S8 - runner `/health` was anonymous.** `/health` now requires the bearer; the backend probe sends its token (so "healthy" proves the token). The container healthcheck reads `/proc/net/tcp` + runs one sandbox job (it can no longer dial a socket under seccomp). Regression `test_health_requires_the_bearer_when_a_token_is_configured` + `test_healthcheck_reads_listen_state_without_dialing`.
- **S6/S7 - frontend.** `ClampedText` on the correlation key in `run-replay.tsx` and `workflow-runs.tsx`; `e2e/stateful-ai-workflow.spec.ts` navigates via sidebar clicks (`openInbox`/`openWorkflows`), not `page.goto`.
- **Nits.** `getRun` mocked in `workflow-runs.test.tsx`; `redis_actions` amount regex; the `seed_demo_progress_workflow` docstring now states the stub's substring/whole-message limits.

### User request implemented in this round

- **Rendered node input in Logs.** The executor stamps `input_json = {config, resolved}` where `resolved` is every `NodeField(mergeable=True)` rendered against the run context (Code nodes keep `runtime.input`); `debug_execute` does the same. Run replay shows a "Resolved input" block above Input. So Send Message now shows the sent text ("Update recorded - task: ..., status: completed"), not `{{ nodes.ai_progress.task }}`. Regression `test_run_node_trace_records_the_resolved_field_values`.

### Still open (handed to the user, not a review blocker)

- **Read-only "Agent State" workflow node** (user request while testing, scope settled 2026-08-30 - BL-SS-032). A generic canvas node that outputs the current accepted Agent state for the run's Correlation key (`nodes.<id>.<field>` + `stateRevision`/`pendingField`) so a builder can inspect/route it into IF / Code / Send Message. READ-ONLY by decision: writes stay through the evidence-checked AI Agent reducer (plan 19 line 29). Pairs with the existing `ai_agent.clear_state` node. Correction: this is a CANVAS NODE, not the "drawer panel" an earlier draft of this note described; and the stored state is per-field structured state keyed by conversationId, NOT last-N-turns transcript (transcript memory stays out of scope per D11 / line 434). Its own slice - UAC + plan addendum, frontend-first - to be built AFTER this branch merges to main. Not built inside the review-fix pass.

### Re-verification after the fixes

- Plan-19 backend suites: `test_serialized_workflow_runtime` (+6), `test_redis_workflow_action` (+1), `test_code_runner_sandbox` (+5, 1 skip macOS), `test_code_workflow_action` (+1), `test_stateful_ai_runtime`, `test_stub_stateful_derivation`, `test_progress_update_proof`, `test_worker_module_boot`, `test_workflow_engine` (+1), `test_workflow_triggers`, `test_omnichannel_workflow_triggers` - **183 passed, 1 skipped**. `test_ai_core` (+2) - **87 passed**.
- Frontend vitest `components/platform/workflow-runs` + `workflow-canvas` + `lib/workflow-doc` - **59 passed**.
- `origin/main` merged in (the `test_worker_module_boot.py` add/add conflict resolved keeping our extra `wake_serialized` test); `docker compose config` renders the seccomp profile + the /proc healthcheck.

### Review round 3 - APPROVED

Round 2 shipped a false "closed twice" claim for B1: a subclass-walk (`object.__subclasses__()` -> `BuiltinImporter.load_module('posix')`) still escaped in-process when the static policy was stubbed. Round 3 (commit `7eee998`) fixed it honestly - static AST policy = GATE (blocks the dunder walk, so production is safe), subprocess jail + seccomp = BOUNDARY, `_harden` = documented best-effort defense-in-depth (now also clears `sys.meta_path`/`path_hooks`/`path`, closing the `meta_path.load_module` variant); the residual in-process limitation is pinned by `test_runtime_layer_alone_does_not_stop_the_subclass_walk` so no false guarantee can silently return. The reviewer independently reproduced the PoC, verified the policy rejects it in production and the meta_path variant is closed, and returned **APPROVE** (all 7 items closed, no new issues from `7eee998`). Branch ready for the user's merge to `main`.
