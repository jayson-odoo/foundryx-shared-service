# 19 - Stateful AI workflow runtime - Acceptance Criteria

Contract for `19-stateful-ai-workflow-runtime.md`.

IDs: `AC-SAR-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Journey

1. A workflow builder opens an existing workflow or creates a progress-update workflow from the Workflows surface.
2. In workflow Settings, the builder supplies one Correlation key, normally `{{ trigger.conversationId }}`, and chooses whether runs sharing that key execute in parallel or serially.
3. On the existing AI Agent node, the builder defines typed output parameters. `task`, `status`, and `blocker` may be retained as state; `decision` and `reply` remain current-turn outputs. Enum values are configured in the output editor, not hidden in prompt prose.
4. When visual nodes are insufficient, the builder may add a generic Code action, write restricted Python against explicitly mapped inputs, declare its output schema, and route the validated result to later nodes.
5. The builder connects the AI Agent to an IF node. A decision such as `needs_clarification` sends `reply`; `ready` continues to a downstream action.
6. A person sends a natural-language message. That message starts a new workflow run. The model receives the current message, accepted structured state, and at most one unresolved clarification. It never receives a replayed transcript.
7. The model proposes independent, evidence-backed operations for each stateful field. Deterministic platform code validates and merges those operations into durable Postgres state.
8. If information is missing or ambiguous, the workflow sends the model's transient `reply`. The next incoming message starts another run and can answer briefly because the unresolved question and its target field are retained.
9. When the model emits `ready`, downstream nodes receive the accepted cumulative values through the normal `nodes.<agent-id>.<field>` paths. The AI Agent itself does not send, clear, or call an integration.
10. After a downstream write succeeds, a Clear Agent State action removes retained values and pending clarification. A downstream failure leaves state available for retry.
11. The sender receives a clarification or confirmation, and the builder can inspect each run, applied field changes, rejected changes, Code logs, and provenance in existing workflow logs.

## Phase 1 - Frontend-first mock

- **AC-SAR-01 [FE]** Given a workflow is in Edit mode, its Settings tab offers an execution mode with `Parallel` as the existing-compatible default and `Serialized by key` as the opt-in mode.
- **AC-SAR-02 [FE]** Given serialized execution is selected, the Settings tab shows one mergeable Correlation key field whose dynamic-content picker exposes trigger outputs; read mode renders the saved mode and key without procedural help text.
- **AC-SAR-03 [FE]** Given serialized execution is selected or any AI Agent output is stateful, saving or publishing without a Correlation key is blocked in the frontend with the same rule enforced by the backend.
- **AC-SAR-04 [FE]** Given an AI Agent output parameter is edited, its type picker includes Text, Number, Boolean, and Enum. Choosing Enum reveals a reorderable value editor that rejects blank and duplicate values and requires at least two choices.
- **AC-SAR-05 [FE]** Given an AI Agent output parameter, the builder can mark it stateful. Transient is the default for existing definitions. The existing Required setting continues to describe the model output schema and is not relabelled as task or collection completion.
- **AC-SAR-06 [FE]** Given at least one stateful output exists, the AI Agent drawer offers a searchable Clarification output picker containing only transient Text outputs from that node. It never offers an incompatible output.
- **AC-SAR-07 [FE]** Given output parameters are configured, downstream dynamic content exposes each configured key at `nodes.<agent-id>.<key>`. Stateful keys represent accepted cumulative values; transient keys represent only the current model response.
- **AC-SAR-08 [FE]** The palette contains a core Clear Agent State action. Its Agent picker lists only earlier, reachable AI Agent nodes that have stateful outputs.
- **AC-SAR-09 [FE]** The palette contains one core Redis action with a searchable operation picker. Only fields valid for the selected operation are shown. Supported operations are Get, Set, Delete, Increment, List Push, List Pop, and List Length.
- **AC-SAR-10 [FE]** Mutating Redis operations are identified as side effects by the existing manual/test-run confirmation path; read-only Get and List Length do not trigger a destructive confirmation.
- **AC-SAR-11 [FE]** Existing workflow logs render AI Agent state results, applied and rejected field names, state revision, and Clear Agent State or Redis outputs through the existing run-node inspector, with no parallel logging surface.
- **AC-SAR-12 [FE][T]** Vitest covers workflow-document migration/defaults, frontend/backend-parity validation, Enum editing, stateful toggles, Clarification output filtering, execution settings, dynamic outputs, Clear Agent State targeting, Redis conditional fields, and existing stateless AI definitions.
- **AC-SAR-13 [FE][E2E]** The editor, Settings tab, output-parameter editor, node palette, drawers, and run inspector are usable without clipping or horizontal page scroll at 375px and 1280px.
- **AC-SAR-58 [FE]** The palette contains a core Code action gated by `workflows.code`. Its drawer provides a Python editor, explicit input mappings, a typed output-parameter editor, and a concise read-only list of runtime capabilities. No procedural hint text is added to the canvas.
- **AC-SAR-59 [FE]** The Code action exposes only declared output keys at `nodes.<code-node-id>.<key>`. The editor blocks duplicate or invalid output keys and highlights syntax errors before publish without claiming that static checks prove runtime success.
- **AC-SAR-60 [FE]** If the external Code runner is unavailable, the Code node shows a prerequisite warning and manual execution fails clearly. The workflow can still be edited and versioned, but publishing a newly introduced or changed Code node is blocked until runner health is available.
- **AC-SAR-61 [FE][T]** Vitest covers Code drawer edit/read states, input mappings, output-schema discovery, permission gating, syntax diagnostics, runner-health warnings, and mobile/desktop layout.

## Phase 2A - Stateful AI Agent backend

- **AC-SAR-14 [BE]** A core Alembic migration creates a tenant-scoped durable Agent-state table with a unique scope of tenant, workflow, AI Agent node, and Correlation key, plus accepted values, field provenance, pending clarification, revision, and UTC timestamps.
- **AC-SAR-15 [BE]** Every Agent-state repository read, write, compare-and-swap, and clear is tenant-scoped. A caller cannot address another tenant, workflow, node, or Correlation key through client input.
- **AC-SAR-16 [BE]** Existing AI Agent definitions containing only string, number, and boolean outputs execute unchanged and create no state row.
- **AC-SAR-17 [BE]** Enum output parameters become JSON Schema enums at the one existing `AiClient.complete` seam. Provider output outside the configured choices is rejected as an AI node failure rather than accepted as an arbitrary string.
- **AC-SAR-18 [BE]** For a stateful AI Agent call, the model input contains the current rendered message, accepted typed state, configured output descriptions and enums, and at most the pending clarification. It contains no earlier user-message or assistant-message transcript.
- **AC-SAR-19 [BE]** The structured model contract proposes one independent operation per stateful field from the fixed enum `set`, `clear`, `no_change`, or `ambiguous`, with a typed value where applicable and current-message evidence for mutation operations.
- **AC-SAR-20 [BE]** The reducer applies `set` only when the value satisfies the configured type or enum and its evidence occurs in the current message; applies `clear` only with current-message evidence; preserves the value for `no_change`; and does not mutate the field for `ambiguous`.
- **AC-SAR-21 [BE]** Evidence may support semantic normalization, such as `wrapped up` becoming Enum value `completed`, but evidence copied only from retained state or invented by the model is rejected deterministically.
- **AC-SAR-22 [BE]** One rejected field patch does not reject valid patches for other fields. The node output identifies applied and rejected field names without exposing provider credentials or hidden prompt text.
- **AC-SAR-23 [BE]** Each accepted value stores its source run ID, source message ID when the trigger provides one, exact evidence, and UTC update time. Updating one field does not replace another field's value or provenance.
- **AC-SAR-24 [BE]** `nodes.<agent-id>.<field>` resolves to the accepted cumulative value for a stateful field and to the current-turn model value for a transient field. User-defined decision and reply outputs remain ordinary LLM outputs.
- **AC-SAR-25 [BE]** The AI Agent takes no automatic branch, send, integration call, clear, or completion action based on a decision output. Existing downstream IF and action nodes remain responsible.
- **AC-SAR-26 [BE]** When a configured clarification Text output asks a question and the model identifies one targeted stateful field, the platform retains only that exact question and target field. It supplies them to the next run and clears them when the target is resolved or state is cleared.
- **AC-SAR-27 [BE]** A short answer such as `yes`, `tomorrow`, or `blocked` can update the targeted field using pending clarification plus evidence from that current short message; older questions are unavailable to the model.
- **AC-SAR-28 [BE]** Agent state has no inactivity expiry. It remains until Clear Agent State executes or the owning workflow is permanently purged.
- **AC-SAR-29 [BE]** Clear Agent State is idempotent, operates on the current run's Correlation key and selected earlier AI Agent node, clears retained values and pending clarification, and leaves current run outputs and workflow logs intact.
- **AC-SAR-30 [BE]** Changing a published node schema retains still-stateful fields whose key, type, and Enum value remain valid; removed, newly transient, type-incompatible, or now-invalid Enum fields are excluded on the next load and reported in the node trace.
- **AC-SAR-31 [BE]** Manual and debug/test executions use a test-isolated state namespace and cannot read, modify, or clear production Agent state.
- **AC-SAR-32 [BE][T]** Postgres pytest tests first cover state isolation, all four patch operations, type and Enum rejection, evidence rejection, independent field merge, provenance, clarification carry and resolution, schema evolution, explicit clear, no expiry, test isolation, disabled/missing agent errors, and stateless regression.

## Phase 2B - Correlated serialized execution

- **AC-SAR-33 [BE]** The versioned workflow definition accepts an optional execution contract containing mode and Correlation key. Definitions without it parse and run as Parallel without migration of stored JSON rows.
- **AC-SAR-34 [BE]** Publish validation requires a syntactically valid Correlation key when serialized execution is selected or a stateful AI Agent exists, and rejects duplicate or invalid AI output contracts with frontend/backend parity.
- **AC-SAR-35 [BE]** A run snapshots the resolved Correlation key at creation from its immutable definition and trigger payload. Later workflow edits cannot move that run into another queue or state scope.
- **AC-SAR-36 [BE]** Parallel workflows retain the existing direct Celery enqueue behavior and throughput.
- **AC-SAR-37 [BE]** For a serialized workflow, runs with the same tenant, workflow, and resolved Correlation key begin in creation order and never overlap. Runs for different keys and different workflows may execute in parallel.
- **AC-SAR-38 [BE]** Postgres `WorkflowRun` rows remain the durable pending-work source. Redis and Celery coordinate wakeups and a short-lived keyed lease, so flushing or restarting Redis cannot erase a pending run or Agent state.
- **AC-SAR-39 [BE]** Duplicate wakeups or worker retries cannot execute a claimed run twice. A worker crash releases through lease expiry, and the workflow beat backstop re-drives stranded pending serialized runs without allowing later same-key runs to overtake them.
- **AC-SAR-40 [BE]** If Redis is unavailable, serialized runs remain Pending and report an operational error for logs; they never silently fall back to parallel execution. Unrelated inbound message persistence remains failure-isolated.
- **AC-SAR-41 [BE]** The Agent-state revision is compare-and-swapped inside the serialized run. A stale or unexpected revision fails safely and is visible in the node/run error rather than overwriting newer state.
- **AC-SAR-42 [BE][T]** Tests cover same-key FIFO behavior, different-key parallel admission, parallel-mode regression, duplicate wakeups, lock expiry, crash recovery, Redis outage, pending-run re-drive, immutable run snapshots, and state revision conflicts.

## Phase 2C - Generic Redis action

- **AC-SAR-43 [BE]** Redis workflow data uses the platform Redis service through a tenant-managed logical namespace. A workflow expression can choose a logical key but cannot access Celery broker, serialization, websocket, another tenant's, or other platform-internal keys.
- **AC-SAR-44 [BE]** Get returns a stored string or null; Set writes a rendered string with an optional positive TTL; Delete is idempotent and reports whether a key existed; Increment atomically changes an integer by a rendered integer amount.
- **AC-SAR-45 [BE]** List Push appends or prepends a rendered string; List Pop removes from the chosen end and returns a string or null; List Length returns an integer. Invalid operation-specific config fails publish or node validation with no partial mutation.
- **AC-SAR-46 [BE]** A Redis command failure fails that node and skips downstream nodes under the existing executor contract. It does not corrupt Agent state or the internal serialized-run queue.
- **AC-SAR-47 [BE]** Redis node inputs and outputs appear in existing run logs with secret-bearing connection details and internal physical key prefixes absent.
- **AC-SAR-48 [BE][T]** Tests use an injected Redis seam and cover all operations, TTL validation, list ends, atomic increment, tenant namespace isolation, reserved-prefix rejection, outage behavior, merge rendering, and run-log redaction.

## Phase 2D - Sandboxed Code action

- **AC-SAR-62 [BE]** The workflow registry defines a generic Code action whose only first-slice language is Python. Its versioned config contains source code, explicit named input mappings, and declared typed output parameters. JavaScript and package imports are not silently accepted.
- **AC-SAR-63 [BE]** Builder code never executes inside the FastAPI process, Celery workflow worker, or database process. The worker submits an authenticated task to a separately deployed Code runner that has no platform database URL, Redis URL, provider credentials, tenant credentials, or application secret in its environment.
- **AC-SAR-64 [BE]** Each execution receives only the rendered read-only `input` dictionary plus a small allowlist of pure builtins and helpers. Filesystem, environment, subprocess, foreign-function, raw socket, reflection escape, and network access are denied. Import statements, dynamic imports, and third-party packages are rejected.
- **AC-SAR-65 [BE]** The runner enforces configurable wall-time, CPU, memory, process, source-size, input-size, output-size, and console-log limits. Timeout, resource exhaustion, invalid JSON, and runner loss fail only the Code node and follow the existing downstream-skip contract.
- **AC-SAR-66 [BE]** Builder code must assign a plain JSON-compatible dictionary to `result`. The platform validates it against the node's declared output schema before flattening it to `nodes.<code-node-id>.<key>`; undeclared keys are discarded and missing required or mistyped values fail the node.
- **AC-SAR-67 [BE]** Standard output and error are bounded and recorded in the existing run-node trace. Source, rendered inputs, validated outputs, duration, runner version, and termination reason are inspectable by existing workflow-log viewers, while transport credentials and runner authentication remain redacted.
- **AC-SAR-68 [BE]** A dedicated `workflows.code` permission gates Code-node creation, editing, publishing, and manual execution. Existing tenant Admin roles receive the new installed-core permission through the required grant sweep. Automated triggers execute only an immutable Code-bearing version stamped as authorized when a permitted actor published it.
- **AC-SAR-69 [BE]** Published workflows snapshot Code source and declared schema in the immutable workflow version. Retries execute that same snapshot, not a later draft. Code cannot call or bypass the internal Agent-state repository or reducer.
- **AC-SAR-70 [BE][T]** Tests cover permission enforcement, tenant isolation, authenticated runner transport, input and output schema validation, every denied capability, timeout, memory and output limits, malformed returns, console truncation, runner unavailability, retry snapshot fidelity, and ordinary non-Code workflow regression.

## Phase 3 - Progress-update proof and Definition of Done

- **AC-SAR-49 [E2E]** A dev-seeded Progress Update Agent workflow is built only from generic nodes: Incoming omnichannel message, AI Agent, IF, Send Message, and Clear Agent State. Its Correlation key is `{{ trigger.conversationId }}` and execution is serialized.
- **AC-SAR-50 [E2E]** The seeded AI Agent defines stateful `task`, `status`, and optional `blocker`; Enum `status`; transient Enum `decision`; and transient Text `reply`. No progress-specific backend action or hardcoded collection schema exists.
- **AC-SAR-51 [E2E]** Given the first message supplies only part of an update, the workflow sends one focused clarification. A second short message starts a new run, uses retained state and pending clarification, and produces cumulative accepted outputs.
- **AC-SAR-52 [E2E]** Given a later message corrects only status or clears only blocker, that field changes while unrelated fields and their provenance remain intact.
- **AC-SAR-53 [E2E]** Given two messages arrive quickly for one conversation, logs show same-key runs executing in order and the final state contains both contributions. Another conversation can progress concurrently.
- **AC-SAR-54 [E2E]** Given the model emits `ready`, the true IF branch can send a confirmation containing cumulative state and then clear Agent state. The next inbound message starts fresh.
- **AC-SAR-55 [E2E]** Given the downstream action before Clear Agent State fails, the clear node is skipped and a later retry can still read the retained update.
- **AC-SAR-56 [E2E]** A real-click browser walk from the sidebar builds, publishes, triggers, inspects, and verifies the workflow against FastAPI, Postgres, Redis, Celery, and the seeded omnichannel conversation at 375px and 1280px.
- **AC-SAR-57 [T]** The Test Execution Report maps every AC to PASS, FAIL, or explicitly justified DEFERRED evidence and runs the relevant backend, frontend, workflow, AI, and omnichannel regression suites.

## Out of scope

- Any project-management product, task schema, or third-party PM connector.
- A dedicated Collect Information or Progress Update node.
- Transcript replay, vector memory, summaries of full chat history, or inactivity expiry.
- Model-controlled automatic clearing, sending, branching, or downstream invocation.
- MCP or tool attachment to the AI Agent node. This remains `BL-SS-031`.
- A general workflow wait/resume primitive. Each incoming message starts a new run.
- JavaScript, package installation or imports, and network, filesystem, environment, or subprocess access from the Code action.
- Custom code inside the trusted Agent-state reducer. Code actions may process its validated downstream outputs but cannot replace its invariants.
