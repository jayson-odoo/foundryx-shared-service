# Sprint 2 · Plan 08 — Workflow Engine (foundation: thinnest end-to-end slice)

**Branch:** `sprint-2/08-workflow-engine`
**Advances:** BL-025 (core Workflow engine — trigger→action). **First of 3 vertical slices** (08 foundation → 09 triggers/actions breadth → 10 integration & polish). The **last core engine** (status, rule, template already live).
**Closes here:** nothing yet — BL-025 closes at the end of slice 10; BL-081 (notification template picker) + BL-064 (FlowCanvas undo/redo) close in slice 10. **Spawns** BL-084 (audit log — subscribes the same emit seam).
**Depends on:** template engine `render_email`/`render_by_key` (plan 07), email outbox + dispatcher (plan 09), rule engine `evaluate`/fact registry (plan 02), Celery+Redis (omnichannel plan 05), FlowCanvas primitives + dnd-kit (plans 01/07).

---

## Context

Project plan §1.2.1 calls for a table-driven publisher/subscriber Workflow engine with triggers, actions, an execution engine, and a scheduler — Power Automate / UiPath / n8n class. This is the **last core engine** and the one that ties the others together: it subscribes to events, evaluates rule trees (IF nodes), renders templates (SendEmail), and orchestrates the integration primitives (email outbox, StorageService).

Rather than land the whole engine in one unreviewable mega-branch, it ships as **3 vertical slices**, each end-to-end (FE+BE+E2E) per the methodology. **This plan (08) builds the thinnest complete slice**: the full stack — data model, versioning, node registry, Celery executor, canvas builder, run logs, debug-replay — wired against exactly **one trigger (manual) and one action (send email)**. That proves every hard unknown (executor, versioning, canvas, staleness-aware debug) on the simplest trigger/action pair. Slice 09 fans out triggers (CRUD event bus, status-change, schedule) and actions (storage, transition, update) + the IF node on a *proven* executor. Slice 10 closes integrations and polish.

**Net demo at end of 08:** create a workflow, drag a Manual trigger → Send Email action, configure with merge fields, publish, run it (with optional manual inputs), watch the run in the Logs tab, click into a run to replay the graph with its data, debug-in-editor and re-execute nodes.

### Engine is PLATFORM CORE, not an App Store module
Like status/rule/template engines: lives in core `app/workflow_engine/` + core `public` tables, perms in core CSV, present for every tenant always, never packaged/uninstallable. Modules only **extend** it — register extra `TriggerDef`/`ActionDef` at their `install()` (closes the BL-025 omnichannel-trigger requirement structurally in a later module update, no core change).

---

## Locked design decisions (from grilling)

1. **D1 — Execution = Celery-queued, run row is the source of truth.** A trigger enqueues a `workflow_run` (PENDING) + a Celery task; a worker executes node-by-node, persisting per-node state. Reuses the proven Celery+Redis stack (omnichannel). Dev/E2E keep `CELERY_TASK_ALWAYS_EAGER=true` → inline, zero extra process. The email outbox stays the *delivery* primitive underneath (SendEmail enqueues to the outbox, never SMTPs inline).

2. **D2 — Graph = DAG; node kinds = Trigger / Action / IF.** One Trigger per workflow (root, no incoming edges). Actions (n). IF = built-in condition node (rule-engine `conditions_json` → true/false output ports). **No parallel/merge/loop in v1** (backlog). Executor is topological. *Slice 08 ships Trigger + Action only; the IF node lands in slice 09 — the executor is built DAG-capable from the start so 09 only adds the node kind, not a new traversal model.*

3. **D3 — Graph stored as ONE `definition_json` doc** (template-engine precedent, not status-engine rows): `{schemaVersion, nodes[], edges[], positions}`. Editor saves the whole graph atomically; `validate_definition` gates at publish. We never query "all nodes of type X across workflows", so relational node/edge rows buy nothing and complicate atomic save + versioning.

4. **D4 — Versioning + publish mechanism.** Editing always writes a **mutable draft** (`draft_definition_json`). **Publish** snapshots draft → a new immutable `workflow_versions` row (incrementing `version_number`) → sets `workflows.current_version_id` → re-registers the trigger (computes `next_run_at` for schedule; rebinds event subscription). Triggers fire **only against `current_version_id`'s definition** — a draft that was never published does not fire; edits don't change live behavior until published (n8n model). UI shows "unpublished changes" when draft ≠ current version. Settings tab carries a read-only version history.

5. **D5 — `is_active` is a plain boolean column, NOT the status engine.** Two operational states (active/inactive), no configurable lifecycle → overkill to ride the status engine. Orthogonal to publish: active + published = live; inactive = registered but suppressed. Toggling active never changes the version.

6. **D6 — Runs pin `version_id` for exact replay.** A `workflow_run` references the exact `workflow_versions.id` it ran on. Logs replay loads that version's immutable `definition_json` + injects the run's captured per-node data — a run whose version was later superseded still shows the old graph exactly. No per-run JSON copy (the version row IS the immutable snapshot).

7. **D7 — Data flow = ONE flat run-context, two readers + a structured picker.** The run starts with a context seeded by the trigger; each node writes its output under `nodes.<nodeId>.*`. **String config fields** (email to/subject/body) are merge-templated with the template engine's `{{ dotted.path }}` micro-renderer (substitution only, HTML-escape, **no eval** — anti-SSTI). **IF nodes** (slice 09) evaluate a rule-engine tree over the same context exposed as facts. On top of the flat context, the builder ships an **n8n-style structured "Dynamic content" picker** (in THIS plan): every node declares an **output schema**, the picker lists available upstream references grouped by source node, and inserting one writes the correct `{{ nodes.<id>.field }}` / `{{ trigger.* }}` path. Flat-context simplicity underneath, typed picker on top. **No expression language / JS eval** (the SSTI line the template engine drew).

8. **D8 — Node-type registry (`app/workflow_engine/registry.py`)**, mirrors StatusEntity/FactSource/TemplateContext. `TriggerDef{key, label, category, config_schema, output_schema, binding}` + `ActionDef{key, label, category, config_schema, output_schema, requires_connection, executor, module}`. **No per-node retry/timeout policy in v1.** Actions own no transport — `email.send` enqueues to the outbox; storage actions (slice 09) go through `storage_for_tenant`. Modules register defs at `install()`, deregistered at uninstall. *Slice 08 registers `manual` (TriggerDef) + `email.send` (ActionDef) only.*

9. **D9 — Triggerable-entity contract = the rule-engine fact source + a `triggerable` flag.** No new entity registry: an entity becomes workflow-triggerable when it has a `record:<entity>` FactSource (rule engine — gives typed fields for context + IF conditions + the dynamic-content picker) AND its service calls `emit_entity_event`. The `entity.*` TriggerDef reads the fact-source registry to populate the entity picker; the chosen entity's FactDefs become the trigger output schema + IF fact source — one definition, three uses. *(CRUD bus + the instrumented entity set land in slice 09; 08's manual trigger needs none of this.)*

10. **D10 — Action authority = elevated system, authorized at publish, audited per run.** A published workflow's actions execute as a **synthetic Workflow principal** (detached from any live user — scheduled runs have none), NOT permission-checked against the publisher at run time (that makes 3am jobs silently break on unrelated role edits). **Publishing is the authorization boundary** (gated `workflows.manage`). Every run records `actor = Workflow principal` + `published_by = the human` → fully attributable in the audit log. **Tenant isolation is never relaxed**: every action stays hard-scoped to the workflow's `tenant_id`.

11. **D11 — Permissions (core CSV):** `workflows.read` (list/view + run logs), `workflows.manage` (create/edit/publish/activate/delete), `workflows.run` (manual execute/test — separate so you can run-but-not-edit). Implied-read normalization forces `workflows.read`. Seeded to tenant Admin via `tenant_admin_grant`. Menu `Workflows` tagged `workflows.read` in ALL THREE menu arrays (sidebar/mega/mobile).

12. **D12 — Manual trigger declares optional inputs.** The manual trigger node config = a list of named typed input fields. Run-now pops a form; values seed `trigger.input.*` into the run context (pickable downstream via D7's picker). Empty list = instant run. Makes manual workflows genuinely useful (ad-hoc "send announcement to role X").

13. **D13 — Test/manual runs do REAL side effects (no dry-run).** "Run" / "Execute" really fires (real email sent). Matches the codebase ethos (integration Test buttons + template test-send are real); dry-run mocking is a disproportionate lift → backlog. Every manual/editor run writes a normal `workflow_run` tagged `triggered_by=manual` (+ `is_test` when launched from the editor), fully visible in Logs. **Confirm dialog before any destructive manual/test run** (destructive actions arrive in slice 09 — `storage.delete`, `entity.update/transition`).

14. **D14 — Node failure halts the run; email succeeds at enqueue.** A node throwing → `workflow_run_node.status=failed` (+ error), downstream `skipped`, `workflow_run.status=failed`. **No continue-on-error in v1** (backlog). A node with no outgoing edge = natural path end = `success`. **`email.send` "succeeds" when it ENQUEUES to the outbox**, not when SMTP delivers — actual delivery/failure shows in the Email log (plan 07), not the workflow run. The workflow run boundary ends at enqueue. Run-level **cancel** supported (atomic `UPDATE … WHERE status IN ('pending','running')`; worker checks the cancel flag between nodes).

15. **D15 — Frontend = house Resource shell + a workflow-specific canvas on shared primitives.** Menu `Workflows`. List: Name, Status (Active/Inactive), Trigger type, Last run, Updated; actions Edit/Run/Duplicate/Delete. The detail uses a tabbed ResourceForm: **Editor** (canvas) · **Logs** (runs) · **Settings**. The canvas is a NEW `components/platform/workflow-canvas/` reusing FlowCanvas's pan/zoom + dagre `layoutGraph` + edge geometry — but its OWN typed-node renderers, output ports, single-direction edges, and a left palette (FlowCanvas's status-node + bidirectional-OffsetEdge model is wrong for a directed ported flow). Right-side node config drawer reuses `merge-field-editor` + the D7 dynamic-content picker. **BL-064 (undo/redo + non-destructive Tidy) is built into this canvas from the start** (it was logged specifically because the workflow engine would inherit FlowCanvas's "stray Tidy nukes layout" bug).

16. **D16 — Logs tab + replay + n8n staleness-aware debug.** Logs = a Resource list of runs (server-paginated: status badge, trigger type, started_at, duration, actor; filter by status/date; tenant-scoped). Click a run → **read-only replay**: the run's pinned-version graph on a read-only canvas, each node tinted by execution status (success/failed/skipped), click a node → its `input_json`/`output_json`/`error`. **"Debug in editor"** → opens the Editor on that run's **version graph** (scratch, not the live draft) with captured per-node outputs injected as the run context.
    **Debug execution model (n8n staleness):** every node holds a cached output (seeded from the loaded run). Editing a node's config marks it **stale**. **One "Execute" button per node** = "make this node's inputs fresh, then run it": walk ancestor paths, re-run any **stale-or-uncached** node in topo order, **reuse cached fresh outputs** for the rest, run the target. ("Execute just this node" and "execute from here" are the same action — the engine recomputes the minimal stale set.) Plus a whole-flow **"Execute Workflow"** that re-runs from the trigger using the loaded run's captured `trigger_payload`. All debug executions are real + `is_test` + scratch (no draft mutation unless explicitly "Save to draft").

17. **D17 — `validate_definition` gate at publish.** Exactly one trigger node = root (no incoming); every node reachable from it (orphans → **block**). **Acyclic** — reject cycles (also blocked at connect-time on the canvas). Required config filled per node type. Every dynamic-content ref (`{{ nodes.<id>.* }}` / `{{ trigger.* }}`) resolves to a real upstream output key (no dangling refs — the picker makes this checkable). Connection-requiring actions with no resolvable connection → **warn, allow publish** (may be configured later; the run fails loudly if still missing).

18. **D18 — Run retention.** Reuse the dispatcher housekeeping pattern: prune `workflow_runs` (+ cascade `workflow_run_nodes`) older than `workflow_run_retention_days` (default 30). *Wired in slice 10 with the scheduler tick; 08 just lands the columns.*

---

## Data model (core `public`, Alembic migration)

> **camelCase wire** via Pydantic `Field(validation_alias=...)` + `ApiModel` base (datetime → Z). All datetimes `UTCDateTime`. Every query tenant-scoped.

- **`workflows`** — `id`, `tenant_id` (FK, required), `name`, `description`, `is_active bool default false`, `draft_definition_json JSON(none_as_null=True)`, `current_version_id` (FK → workflow_versions, nullable until first publish), **denormalized trigger** `trigger_type`, `trigger_entity_type` (nullable), `trigger_action` (nullable) [set on publish for fast matching — slice 09], `next_run_at UTCDateTime` (schedule only — slice 09), `created_by` (FK users), timestamps. Index `(tenant_id)`, `(trigger_type, trigger_entity_type, trigger_action) WHERE is_active`.
- **`workflow_versions`** — `id`, `workflow_id` (FK), `version_number int`, `definition_json JSON` (IMMUTABLE), `published_at`, `published_by` (FK users), `notes` (nullable). Unique `(workflow_id, version_number)`.
- **`workflow_runs`** — `id`, `tenant_id`, `workflow_id` (FK), `version_id` (FK workflow_versions), `status` (`pending|running|success|failed|cancelled`), `trigger_payload_json JSON`, `triggered_by` (`manual|schedule|event`), `is_test bool`, `triggered_by_run_id` (FK self, nullable — loop chain), `depth int default 0`, `actor_id` (synthetic/real), `published_by_id`, `started_at`, `finished_at`, `error` (nullable), `created_at`. Index `(tenant_id, workflow_id, created_at)`, `(status)`.
- **`workflow_run_nodes`** — `id`, `run_id` (FK, cascade), `node_id` (string — id within the definition), `node_type`, `status` (`pending|running|success|failed|skipped`), `input_json`, `output_json`, `error`, `started_at`, `finished_at`. Index `(run_id)`.

### `definition_json` wire shape (camelCase)
```jsonc
{
  "schemaVersion": 1,
  "nodes": [
    { "id": "trg_1", "kind": "trigger", "type": "manual",
      "config": { "inputs": [ { "key": "audienceRoleId", "label": "Audience role", "type": "string" } ] },
      "position": { "x": 0, "y": 0 } },
    { "id": "act_1", "kind": "action", "type": "email.send",
      "config": { "templateId": "tpl_…", "to": "{{ trigger.input.audienceEmail }}",
                  "subject": "Hello {{ trigger.input.name }}" },
      "position": { "x": 0, "y": 160 } }
    // slice 09 adds: { "kind": "if", "config": { "conditionsJson": {…} } } with true/false ports
  ],
  "edges": [ { "id": "e1", "source": "trg_1", "target": "act_1", "sourcePort": "out" } ]
}
```

---

## Backend shape (`app/workflow_engine/` + service/repo/router)

- **`registry.py`** — `TriggerDef`/`ActionDef` dataclasses + `register_trigger`/`register_action`/lookups (`lazy_once` core registration like the other engines). 08 registers `manual` + `email.send`.
- **`schemas.py`** — `validate_definition(doc, registry)` (D17 gate) + the Pydantic doc model (`WorkflowDefinition`, mirrors `types/workflows.ts`).
- **`context.py`** — flat run-context build/merge; `trigger.*` seeding; `nodes.<id>.*` writes; reference resolution for the picker output schemas.
- **`executor.py`** — `run_workflow(db, run_id)` topological walk (DAG-ready) writing `workflow_run_nodes`; `execute_to_node(db, run_id, target, cache, stale)` for the staleness-aware debug path (D16). Node failure halts (D14).
- **`actions/email_send.py`** — `executor(ctx, config, db) -> dict`: merge-render to/subject + resolve `templateId` via `render_email`/`render_by_key` → enqueue to outbox → return `{messageId, status:'queued'}`.
- **`worker.py`** — Celery task `run_workflow_task(run_id)` (own queue; eager in dev). Enqueued **after commit** via the session-buffered drain (the manual path enqueues directly post-commit; the event path arrives in slice 09).
- **`service.py` / `repository.py`** — workflow CRUD, publish (snapshot→version→set current→re-register), manual run (build run + enqueue), run/run-node reads for Logs, debug execute. **Router** (`api/v1/workflows.py`): `/workflows` CRUD + `/{id}/publish` + `/{id}/run` + `/{id}/runs` + `/runs/{id}` + `/runs/{id}/nodes` + `/{id}/debug/execute` (+ `/{id}/cancel-run/{run_id}`). All gated per D11. Router does HTTP only (no DB/SQL — layering rule).

---

## Frontend shape

- `app/(protected)/workflows/` — list page + `[id]` tabbed detail (Editor/Logs/Settings), cloning the Users Resource reference.
- `hooks/use-workflows.ts`, `hooks/use-workflow-runs.ts`; `services/workflow-service.ts` (→ api-client). UI → hook → service → api-client (layering rule; no axios in components).
- `components/platform/workflow-canvas/` — `WorkflowCanvas`, typed node renderers (`TriggerNode`/`ActionNode`; `IfNode` in 09), `NodePalette` (left, dnd-kit), `NodeConfigDrawer` (right; reuses `merge-field-editor` + new `DynamicContentPicker`), ported edges, **undo/redo + non-destructive Tidy (BL-064)**.
- `components/platform/workflow-runs/` — run list (Logs tab) + `RunReplay` (read-only canvas tinted by node status + node-data inspector) + debug controls (per-node Execute, Execute Workflow).
- `types/workflows.ts` — `WorkflowDefinition`/node/edge/run interfaces (explicit, no `any` — review rule); mirror of backend `schemas.py`.

---

## Phases (frontend-first per methodology)

- **Phase 0 — spike:** prove the workflow-canvas primitives (typed nodes + ports + palette drop + undo/redo) over FlowCanvas helpers; confirm Celery enqueue-after-commit + eager-dev path; confirm `render_email` SendEmail wiring end-to-end with a hand-built run.
- **Phase A — frontend (mock service):** list + Editor canvas (manual trigger + email action, drawer, dynamic-content picker, undo/redo/Tidy) + Logs/replay/debug UI + Settings + version-history, all states tunable on a mock `workflow-service.mock.ts`. Iterate UI to n8n standard.
- **Phase B — backend (TDD):** migration + registry + `validate_definition` + executor + email.send action + publish/version + manual run + run/run-node reads + debug execute; pytest first (executor matrix, validate_definition 422 matrix, publish/version snapshot, run-failure halt, enqueue-not-deliver, staleness-aware execute-to-node, tenant scoping, loop-chain columns). Swap mock → api-client at the service boundary.
- **Phase C — E2E (real clicks):** build a manual→email workflow by dragging palette nodes, configure with merge chips, publish, run with inputs, assert the run appears in Logs, open replay, debug-execute a node. Canvas connections are E2E-drivable (status-engine precedent: drop on the target handle); **dnd-kit palette drag asserted in Vitest** (Playwright mouse events don't drive dnd-kit pointer sensors — template-engine lesson). Test Execution Report per the orchestration guide. Spec provisions a **dedicated tenant** (mutates shared state — fullyParallel isolation rule); timestamp all created names.

---

## Out of scope (→ slice 09/10 or backlog)
- CRUD event bus + emit seam + status-change/schedule triggers + IF node + storage/transition/update actions + loop guard → **slice 09**.
- BL-081 (notification template picker), BL-064 final polish, run retention, audit-log seam handoff (BL-084) → **slice 10**.
- Parallel/merge/loop nodes, per-node retry/timeout, continue-on-error, dry-run mode, relative-to-record-date scheduling, in-app notification action, binary file load into context → **backlog**.
