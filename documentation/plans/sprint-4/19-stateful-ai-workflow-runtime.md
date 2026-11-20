# 19 - Stateful AI workflow runtime

Contract: `19-stateful-ai-workflow-runtime-acceptance-criteria.md`.

This feature upgrades the generic workflow engine so builders can compose reliable multi-turn AI workflows without transcript memory or domain-specific collection code. The proof is a progress-update workflow, but every shipped capability is generic: Enum outputs, per-field Agent state, a Correlation key, optional keyed serialization, explicit state clearing, Redis actions, and a sandboxed Python Code action.

## Journey summary

A builder configures a workflow once, using the existing AI Agent, IF, messaging, and new generic state/Redis capabilities. Every incoming message remains an independent workflow run. The AI model interprets only the current message against durable structured state and one unresolved question. Deterministic code validates independent field patches. Downstream nodes receive accepted cumulative values and decide whether to ask, write, confirm, or clear.

The sender experiences a focused conversation. The builder experiences ordinary workflow composition and inspectable runs. A future PM connector consumes the same accepted outputs without changing the collection engine.

### What the builder sees

The canvas remains fully composable, but runtime safety is not represented as wiring the builder can accidentally omit:

| Capability | Frontend representation |
|---|---|
| Incoming message | Existing trigger node |
| Stateful fields, Enum values, `decision`, and `reply` | Configurable output rows inside the existing AI Agent node drawer |
| Per-field deterministic reducer and Postgres state load/save | Engine-owned behavior of stateful AI Agent outputs, visible in node logs but not a separate node |
| Decision routing | Existing IF node configured against `nodes.<agent-id>.decision` |
| Clarification delivery | Existing Send Message node configured with `nodes.<agent-id>.reply` |
| Correlation key and serialization | Workflow Settings, versioned with the graph |
| State reset | New Clear Agent State action node |
| Explicit Redis commands | New optional Redis action node |
| Custom deterministic processing | New Code action with explicit inputs, declared outputs, and an external restricted Python runner |

The reducer is intentionally not a canvas node. Making it one would require every builder to wire the memory safety contract correctly and would allow stateful AI Agent outputs to bypass validation. Builders adjust its inputs through output types, Enum choices, and the Stateful setting; the platform owns the invariant implementation.

The workflow engine does not currently have a Code node, so this feature adds one as a real platform capability rather than evaluating source inside FastAPI or Celery. Builder-authored Python runs only in a separately deployed restricted runner with explicit JSON inputs, declared JSON outputs, no platform secrets, no I/O permissions, and hard resource limits. Code may transform accepted AI Agent outputs before later nodes, but it cannot replace or bypass the Agent-state reducer.

## Decisions

| ID | Decision | Consequence |
|---|---|---|
| D1 | One incoming message creates one workflow run. | No paused execution or wait/resume engine is introduced. |
| D2 | One workflow-level Correlation key identifies related runs. | Serialization and Agent state cannot drift onto different keys. |
| D3 | Serialized execution is opt-in per workflow. | Stateless and unrelated workflows keep current parallel throughput. |
| D4 | Stateful AI Agent outputs require a Correlation key and published serialized mode. | A builder must explicitly choose safe ordering; merely adding any AI Agent does not enable it. |
| D5 | Agent state is isolated by tenant, workflow, AI Agent node, and Correlation key. | Renaming a node does not break state because identity remains ID-based. |
| D6 | Postgres owns durable Agent state and pending runs. | Redis loss cannot erase collected information or queued run records. |
| D7 | Redis/Celery coordinate wakeups and short leases. | Same-key work is serialized without one global queue bottleneck. |
| D8 | Stateful fields receive independent `set`, `clear`, `no_change`, or `ambiguous` patches. | One correction cannot rewrite unrelated state. |
| D9 | Mutating patches require exact current-message evidence. | The model may normalize meaning but cannot copy prior state and present it as new evidence. |
| D10 | User-defined `decision` and `reply` remain ordinary transient model outputs. | IF and Send Message nodes control behavior; the AI Agent has no hidden side effects. |
| D11 | Only the last unresolved question and targeted field are retained. | Short answers work without transcript replay. |
| D12 | State has no inactivity expiry. | Clear Agent State is the only normal lifecycle transition. |
| D13 | Clear Agent State is a generic downstream action. | Builders place it after a successful external write; failures preserve retryable state. |
| D14 | Enum is a first-class output type with configured choices. | Business classifications such as status are schema-constrained instead of prompt-only. |
| D15 | Redis workflow actions use a tenant logical namespace over platform Redis. | Builders gain n8n-style primitives without access to broker or other internal keys. |
| D16 | Existing stateless AI Agent definitions remain valid. | The feature is additive and does not backfill workflow JSON documents. |
| D17 | Test/debug Agent state is isolated from production state. | Testing a workflow cannot contaminate a live conversation. |
| D18 | The progress updater is seeded as a generic-node example only. | No progress-specific service, table, endpoint, or node enters the platform core. |
| D19 | Code is a generic action whose first language is Python. | Builders get one useful language with a bounded security and testing surface; JavaScript is a later extension. |
| D20 | Code runs through an external restricted task runner, never in an application process. | A tenant script cannot read application memory, environment, database, Redis, provider credentials, filesystem, or network. |
| D21 | Code has explicit input mappings and declared typed outputs. | Dynamic content stays discoverable and runtime results are schema-validated before entering workflow context. |
| D22 | `workflows.code` is a dedicated permission. | Adding, changing, publishing, or manually running Code requires an explicit high-risk capability and an existing-tenant grant sweep. |

## Reuse map

| Need | Existing seam to extend |
|---|---|
| Versioned graph contract | `WorkflowDefinition` in frontend and `WorkflowDefinitionModel` in backend |
| Publish validation | `validateDefinition` and `definition_issues` parity |
| Workflow settings UI | Existing workflow Resource form Settings tab |
| Dynamic expressions | `render_field`, flat run context, and dynamic-content picker |
| AI model execution | `AiClient.complete` through `ai_agent.run` |
| Friendly structured schema editor | Existing `outputSchema` field renderer |
| Branching | Existing IF node and true/false ports |
| Explicit actions | Core `ActionDef` registry and executor contract |
| Run durability and trace | `WorkflowRun` and `WorkflowRunNode` |
| Background execution | Existing workflow Celery app and Redis broker |
| Recovery tick | Existing workflow Celery beat host |
| Logs UI | Existing workflow run-node inspector |
| Demo transport | Existing seeded omnichannel trigger and Send Message action |
| Code action lifecycle | Existing action registry, publish validation, immutable versions, and downstream-skip semantics |
| Code editing | Add a maintained React code editor because the repository has no Monaco or CodeMirror dependency |
| Code isolation | New external Python task runner behind a narrow authenticated `CodeRunnerClient` seam |

## 1. Versioned workflow execution contract

Extend the root workflow document with an optional execution object. Missing execution data means the current Parallel behavior.

```json
{
  "schemaVersion": 2,
  "execution": {
    "mode": "serialized",
    "correlationKey": "{{ trigger.conversationId }}"
  },
  "nodes": [],
  "edges": []
}
```

The execution object belongs in the draft and immutable published version, not the tenant-wide `workflow_settings` table. A run also snapshots the rendered key into a new nullable `workflow_runs.correlation_key` column. This keeps a run faithful after later edits.

Frontend and backend validation stay in parity:

- missing execution object is valid and means Parallel;
- serialized mode requires a nonblank merge expression;
- any stateful AI Agent requires serialized mode and a Correlation key;
- the key is rendered only from trigger context at run creation;
- an unresolved or empty key blocks run creation with an inspectable failure rather than joining unrelated runs under an empty key.

The Settings tab adds the execution mode and Correlation key inside the existing Resource form. `SearchSelect` is used for the mode. The existing global Edit toggle and dirty guard apply.

## 2. AI output parameter contract

Extend each output parameter without inventing a separate collection schema:

```ts
interface WorkflowAiOutputParam {
  key: string;
  type: 'string' | 'number' | 'boolean' | 'enum';
  enumValues?: string[];
  description?: string;
  required?: boolean;
  stateful?: boolean;
}
```

`required` retains its current JSON Schema meaning. It does not mean that a business task is complete. Enum requires at least two unique, nonblank choices. `enumValues` is rejected for other types. Existing rows default to `stateful=false`.

When state is enabled, the node also stores `clarificationOutputKey`, selected from that node's transient Text outputs. The model's internal contract includes a nullable pending target constrained to the configured stateful keys. If it emits a target, the platform stores the exact chosen clarification output and target field. No output name such as `reply`, `decision`, `task`, or `status` is hardcoded.

Downstream paths do not expose the internal patch wrapper:

- stateful `nodes.<id>.<key>` is the accepted cumulative value after reduction;
- transient `nodes.<id>.<key>` is the current model output;
- fixed diagnostic outputs are `stateRevision`, `stateChangedFields`, `stateRejectedFields`, and `pendingField`;
- raw model patch and hidden system prompt stay in AI trace internals, not dynamic content.

## 3. Durable Agent state

Add core table `workflow_agent_states` through core Alembic:

| Column | Purpose |
|---|---|
| `id` | UUID primary key |
| `tenant_id` | Required tenant scope, indexed |
| `workflow_id` | Owning workflow, cascade on permanent workflow deletion |
| `node_id` | Stable AI Agent node ID |
| `correlation_key` | Rendered related-run identity |
| `state_json` | Accepted typed values by output key |
| `provenance_json` | Per-field run, message, evidence, and updated-at metadata |
| `pending_question` | Last unresolved generated question only |
| `pending_field` | Stateful key targeted by that question |
| `revision` | Monotonic optimistic-concurrency revision |
| `created_at`, `updated_at` | UTC timestamps |

Unique constraint: `(tenant_id, workflow_id, node_id, correlation_key)`.

Create `AgentStateRepository` for tenant-scoped queries and compare-and-swap updates. Create `AgentStateService` for schema filtering, reducer calls, pending clarification, provenance, and clear. Routers are not involved because state is manipulated only by workflow actions in this slice.

State survives inactivity. Existing workflow run retention remains unchanged and does not delete live Agent state. Permanent workflow purge cascades the rows. Soft trash does not.

### Schema evolution

The published node definition is the current state schema. On load:

- retain a field only when it remains stateful and its value satisfies the current type and Enum;
- treat new fields as absent;
- exclude removed, transient, type-incompatible, and invalid Enum fields;
- record exclusions in node diagnostics;
- persist the sanitized state only as part of the next successful compare-and-swap.

This avoids a fleet-wide data rewrite on publish while preventing obsolete values from reaching the model.

## 4. Current-turn model contract and deterministic reducer

The AI Agent builds one structured call at the existing `AiClient.complete` seam. Its system content contains the builder's instructions plus a platform-generated state contract. Its user content contains:

```json
{
  "currentMessage": "I am blocked waiting for finance approval",
  "acceptedState": {
    "task": "Launch landing page",
    "status": "in_progress"
  },
  "pendingClarification": {
    "question": "What is blocking the launch?",
    "field": "blocker"
  }
}
```

The pending object is null when none exists. No earlier messages are loaded from omnichannel or another store.

The generated output schema separates transient outputs from internal state patches. Conceptually:

```json
{
  "outputs": {
    "decision": "ready",
    "reply": "I recorded your update."
  },
  "statePatches": {
    "task": {"operation": "no_change"},
    "status": {
      "operation": "set",
      "value": "blocked",
      "evidence": "blocked"
    },
    "blocker": {
      "operation": "set",
      "value": "Waiting for finance approval",
      "evidence": "waiting for finance approval"
    }
  },
  "pendingField": null
}
```

The reducer is a pure function with golden tests. For every field independently:

- `set`: evidence must be a normalized exact substring of the current message and value must pass the configured schema;
- `clear`: evidence must be a normalized exact substring of the current message, then remove value and provenance;
- `no_change`: preserve value and provenance;
- `ambiguous`: preserve value and provenance, list the field as rejected/ambiguous;
- malformed operation, evidence, or value: reject only that field.

Normalization may be semantic in the model's value, not in its evidence. Unicode normalization and surrounding whitespace/case comparison may be applied to evidence matching, but the stored evidence remains the exact message slice.

The state service adds provenance only for accepted `set` operations. A clear is visible in the run-node trace. It compare-and-swaps the expected revision and returns cumulative state plus diagnostics. The executor then flattens those outputs normally.

## 5. Pending clarification

Pending clarification is intentionally bounded to one question and one field.

- The configured clarification output must be a transient Text field.
- `pendingField` is constrained to current stateful keys.
- When the model emits a pending field, the chosen clarification output becomes `pending_question`.
- When an accepted patch changes or clears that field, both pending columns clear.
- Emitting another pending field replaces the previous unresolved question.
- Clear Agent State clears both.

This reproduces the useful part of the existing Sorento brain's `previous response + previous_conversation_state` pattern while eliminating transcript replay and unbounded domain-specific reconciliation.

## 6. Explicit Clear Agent State action

Register core action `ai_agent.clear_state`:

- field `agentNodeId`, rendered as a searchable picker restricted to earlier reachable AI Agent nodes with stateful outputs;
- no Correlation key field because it uses the current run's snapshotted key;
- executor calls `AgentStateService.clear` within the run transaction;
- output `{cleared: boolean, previousRevision: number | null}`;
- idempotent when no state exists;
- test/debug execution addresses only the test namespace.

The node is named Clear Agent State, not Collect Information. It knows no business fields and is useful anywhere state must be explicitly reset.

## 7. Keyed serialized execution

The n8n reference uses one Redis list per contact, a global ready-contact list, a 120-second contact lock, and a one-second scheduler. Foundryx keeps the same useful property, one active consumer per key, while retaining existing Postgres runs as the durable queue.

### Enqueue

At run creation:

1. Render and snapshot the Correlation key.
2. Persist the Pending `WorkflowRun` and commit it.
3. Parallel mode calls the existing `run_workflow_task.delay(run_id)`.
4. Serialized mode sends an idempotent `workflows.wake_serialized` task carrying the tenant/workflow/key digest.

No inbound request waits for the workflow.

### Drain

`wake_serialized`:

1. acquires a Redis `SET NX` lease scoped to tenant/workflow/key digest;
2. queries Postgres for the oldest Pending run in that exact scope using `created_at, id` ordering and a claim guard;
3. executes that run;
4. repeats until no Pending run remains;
5. releases the lease in `finally`.

Duplicate wakeups are harmless. A worker that cannot acquire the lease exits. The lease is renewed while a run is active so normal long LLM calls do not overlap. A run claim prevents a retry from executing an already Running or terminal run.

The existing beat host gains a recovery pass that finds old Pending serialized runs in Postgres and emits wakeups. Redis outage never falls back to Parallel. Once Redis returns, the recovery pass resumes the queue.

Different digests have different leases and drain concurrently. Parallel workflows never enter this path.

### Eager tests

Eager mode uses an injected serializer seam with the same oldest-Pending selection and claim rules, without requiring a live worker. Concurrency tests run against Postgres and an injected Redis client. Production uses the real Redis client from `settings.redis_url`.

## 8. Generic Redis workflow action

Register core action `redis.command`, backed by `WorkflowRedisService`. It uses platform Redis but maps builder-visible logical keys under an internal tenant namespace. Builders never see or control the physical prefix.

Supported operations and fields:

| Operation | Inputs | Outputs |
|---|---|---|
| Get | key | value |
| Set | key, value, optional TTL seconds | stored |
| Delete | key | deleted |
| Increment | key, amount | value |
| List Push | key, value, end | length |
| List Pop | key, end | value |
| List Length | key | length |

All text inputs are mergeable. Operation and list end use `SearchSelect`. Conditional fields use the existing `showWhen` pattern, extended to support an operation set where needed. Backend validation mirrors the editor.

Physical keys use a reserved prefix similar to `workflow:data:<tenant-id>:<logical-key>`. Internal broker, websocket, serialization, and Celery-result prefixes are unreachable. Values are strings in this slice; builders explicitly JSON-stringify through upstream values when needed. Set TTL is optional, but Agent state itself has no TTL.

The Redis service has an injected-client seam for tests. Command failures raise `ActionError`, fail the node, and preserve the existing downstream-skip behavior.

## 9. Sandboxed Code workflow action

Register core action `code.run`. The action is deliberately generic and versioned inside the workflow definition:

```json
{
  "language": "python",
  "inputs": [
    {"key": "task", "value": "{{ nodes.act_agent.task }}"},
    {"key": "status", "value": "{{ nodes.act_agent.status }}"}
  ],
  "source": "result = {'summary': f\"{input['task']}: {input['status']}\"}",
  "outputs": [
    {"key": "summary", "type": "string", "required": true}
  ]
}
```

The first slice supports Python only. One language keeps the security surface testable while still covering general transforms, reducers, formatting, and business calculations. The drawer uses CodeMirror 6 with Python syntax highlighting, keyboard accessibility, and inline diagnostics. Input rows reuse mergeable dynamic content. Output rows reuse the friendly typed schema editor so downstream dynamic content can expose only declared keys.

### Runner boundary

`code.run` calls a `CodeRunnerClient`; it never calls Python `eval`, `exec`, `compile`, or an embedded interpreter inside FastAPI or Celery. The production client submits an authenticated task to a separately deployed Python runner. The runner is deployed without application secrets, database access, Redis access, mounted tenant files, or network egress. Development uses the same external process boundary rather than silently weakening the contract.

Each execution gets one read-only `input` dictionary and a narrow allowlist of pure builtins and helpers. Static AST validation rejects imports, dangerous builtins, dunder access, and unsupported reflection features before submission. This language policy is not treated as the security boundary. The external runner starts a fresh isolated process in a minimal non-root jail with an empty environment, read-only minimal filesystem, no network, process and memory limits, CPU quotas, and a restrictive syscall profile. Defense in depth follows the [n8n external task-runner production model](https://docs.n8n.io/deploy/host-n8n/configure-n8n/set-up-task-runners/); application processes never host untrusted code.

The runner and client jointly enforce configurable source, input, output, console, wall-time, CPU, memory, and process limits. Builder code assigns a plain JSON-compatible dictionary to `result`, which must pass the declared output schema. Undeclared keys are discarded. Invalid types, missing required fields, timeout, resource exhaustion, runner loss, and malformed JSON raise `ActionError`, fail the node, and skip downstream nodes under the existing executor contract.

Standard output and error are bounded and appear in the existing node trace with duration, runner version, and termination reason. Runner authentication, physical transport details, and platform configuration are redacted. Published workflow versions snapshot source and schema, so retry fidelity is unchanged.

Add `workflows.code` to the core permission CSV. The frontend palette and drawer, backend save/publish validation, and manual execution require it. Publishing stamps the immutable version as Code-authorized by the permitted actor; automated triggers may then execute that reviewed version without inventing an end-user permission context. A grant sweep gives existing tenant Admin roles the new installed-core permission while preserving custom roles.

## 10. Frontend-first implementation

Phase 1 changes only the frontend document model, validation, editor, catalogs, and mock services:

1. extend `WorkflowDefinition` and `WorkflowAiOutputParam` types;
2. add immutable schema-v2/default helpers and validation;
3. extend the existing output-schema editor for Enum and stateful fields;
4. add execution controls to the existing Settings tab;
5. register mocked Clear Agent State, Redis, and Code actions in the catalog;
6. add the Code editor, input mappings, declared outputs, permission gate, runner-health warning, and mocked traces;
7. extend dynamic-output discovery and prior-node filtering;
8. render mocked run-node results for state and Code diagnostics;
9. tune invalid, empty, read, edit, mobile, and desktop states.

No backend file changes in Phase 1. The service contract at the mock/real boundary documents the new graph wire shape.

## 11. Backend TDD implementation

Phase 2 follows red-green-refactor in this order:

1. definition v2 parsing, v1 compatibility, and publish validation;
2. `workflow_runs.correlation_key` migration and run snapshot behavior;
3. Agent-state model, repository, service, and reducer golden tests;
4. stateful AI schema/prompt and stateless regression;
5. pending clarification and Clear Agent State;
6. serialized dispatcher, lease abstraction, recovery tick, and claim guards;
7. generic Redis service and action;
8. Code action contract, permission, external runner client, and runner sandbox;
9. registry metadata and API wire parity;
10. swap frontend mock service to the existing real workflow service boundary;
11. full browser verification and test report.

No new public HTTP endpoint is needed for Agent state, Redis data, or Code execution. Workflow CRUD already carries the versioned definition. Existing run APIs already return node input/output traces. Runner transport is private infrastructure and is never exposed as a tenant API.

## 12. Test seams agreed before implementation

- Pure `reduce_agent_state(current, patches, message, schema)` golden table.
- `AgentStateRepository` with Postgres transaction and compare-and-swap tests.
- Injectable Redis lease client for serialized execution.
- Injectable Redis command client for workflow actions, distinct namespaces from the lease client.
- Frozen clock for lease and provenance timestamps.
- Stub LLM fixtures that return exact structured patches and transient outputs.
- A blocking test action that proves different keys overlap while the same key cannot.
- Worker-crash simulation between claim, execution, and lease release.
- Existing test-trigger sandbox proves production state isolation.
- Real omnichannel seeded flow for two-turn, correction, rapid-message, failure-before-clear, and fresh-after-clear journeys.
- `CodeRunnerClient` fake for workflow action tests plus a real external-runner contract suite.
- Runner escape tests for network, filesystem, environment, subprocess, imports, CPU, memory, time, output, and console limits.
- Permission and existing-tenant Admin grant-sweep tests for `workflows.code`.

## 13. Slices and dependencies

### S0 - Frontend mock and versioned contract

Implements AC-SAR-01 through AC-SAR-13 and AC-SAR-58 through AC-SAR-61 against mocks. Produces the reviewed screen and graph contract before backend work.

### S1 - Stateful outputs and explicit clear

Implements AC-SAR-14 through AC-SAR-32. Depends on S0 wire contract.

### S2 - Serialized runtime

Implements AC-SAR-33 through AC-SAR-42. Depends on S1 because state revision tests are the correctness proof.

### S3 - Redis action

Implements AC-SAR-43 through AC-SAR-48. May follow S1 in parallel with S2 only if implementation worktrees do not touch the shared registry/catalog files concurrently; merge sequentially otherwise.

### S4 - Sandboxed Python Code action

Implements AC-SAR-62 through AC-SAR-70. Depends on S0. Its permission grant sweep, runner boundary, and escape suite must pass before any Code workflow can publish.

### S5 - Progress-update proof and DoD

Implements AC-SAR-49 through AC-SAR-57. Depends on S1, S2, S3, and S4. Writes `19-stateful-ai-workflow-runtime-test-report.md`. The seeded proof need not use Code merely to prove it exists; Code receives its own E2E transform and failure-path proof.

## 14. Security, tenancy, and operations

- `workflows.code` is the only new permission. Stateful outputs, Clear Agent State, serialization, and Redis actions remain under existing workflow permissions.
- Existing tenant Admin roles receive `workflows.code` through a tested grant sweep. Custom roles remain unchanged until an authorized Admin grants it.
- Tenant ID always comes from the run, never node configuration or an expression.
- Correlation keys and logical Redis keys are data, never SQL or raw physical Redis keys.
- Run logs may show business values and evidence because builders already see node input/output. Provider credentials, internal prefixes, and hidden prompts remain redacted.
- Redis unavailability must not break inbound omnichannel message persistence.
- Core migration revision identifiers remain at most 32 characters.
- The Code runner has no application secrets or platform data access. Its production isolation and health are deployment prerequisites, not best-effort application checks.

## 15. Out of scope and backlog

- PM tool and third-party connector nodes are separate future slices consuming the accepted outputs.
- MCP/function calling stays `BL-SS-031`.
- Full transcript memory, vector recall, summarization, inactivity expiry, and workflow wait/resume do not ship.
- A standalone Agent-state administration Resource page does not ship. Current state is observable through run logs and controllable through the workflow action.
- JavaScript, package installation or imports, and network, filesystem, environment, subprocess, or credential access from Code do not ship.
- Custom replacement of the Agent-state reducer does not ship; trusted state mutation remains a platform invariant.

## Definition of Done

- Frontend mock is replaced by the real workflow service and real runtime.
- Both core migrations apply to a populated Postgres database; existing definitions remain Parallel and stateless.
- The `workflows.code` permission and existing-tenant Admin grant sweep pass; no other new permission is introduced.
- New run and state fields reach API outputs and the existing run inspector where applicable.
- Relevant pytest, Vitest, workflow, AI, and omnichannel regressions pass.
- The external Code runner contract and escape suite pass under production-equivalent restrictions; ordinary workers contain no builder-code execution path.
- Real sidebar-click verification passes at 375px and 1280px with FastAPI on 8001 and frontend on 3001.
- The test report maps every `AC-SAR` criterion to evidence.
- Code review finds no layering, tenant-scope, raw-CSS, type, migration, or mock hard fail.
