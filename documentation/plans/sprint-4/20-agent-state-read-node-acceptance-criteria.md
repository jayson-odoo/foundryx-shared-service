# 20 - Read-only Agent State workflow node - User Acceptance Criteria

Contract for `20-agent-state-read-node.md`. Follows plan sprint-4/19 (stateful AI runtime). Backlog: BL-SS-033.

The feature adds ONE generic canvas node - **Read Agent State** (`ai_agent.read_state`) - that outputs the current accepted Agent state for the run's Correlation key so a builder can inspect it and route it into IF / Code / Send Message WITHOUT running an AI Agent node. It is READ-ONLY by decision (2026-08-30): writes stay exclusively through the evidence-checked AI Agent reducer (plan 19 line 29). It pairs with the existing `ai_agent.clear_state` node. State stays per-field structured state keyed by conversationId - NOT last-N-turns transcript (transcript memory is out of scope per plan 19 D11 / line 434).

Tags: `[BE]` backend, `[FE]` frontend, `[E2E]` end-to-end, `[T]` test.

## Slice - Read Agent State node

### Catalog + palette

- **AC-ASR-01 [FE]** The node palette lists a **Read Agent State** action (category Actions) alongside Clear Agent State. It is a core node (visible to every tenant, no module gate).
- **AC-ASR-02 [FE]** The node's only config is an **Agent** picker (`agentNodeId`, field type `agentNode`) that lists ONLY the stateful AI Agent nodes that are structural ancestors of this node (same restriction the Clear Agent State picker uses). A workflow with no upstream stateful agent shows an empty picker + a warning, never a free-text id.

### Dynamic outputs

- **AC-ASR-03 [FE]** Once an Agent is selected, the dynamic-content picker (`{ }`) and IF fact list expose the selected agent's stateful field keys as `nodes.<readNodeId>.<field>`, plus the reserved diagnostics `nodes.<readNodeId>.stateRevision`, `nodes.<readNodeId>.pendingField`, `nodes.<readNodeId>.exists`.
- **AC-ASR-04 [FE]** Changing the selected Agent updates the exposed output keys to the newly selected agent's stateful fields. Selecting no agent exposes only the reserved diagnostics.

### Execution (read-only, durable, scoped)

- **AC-ASR-05 [BE]** At run time the node loads the accepted state for `(tenant, workflow, agentNodeId, correlationKey, namespace)` via `AgentStateService.load` and flattens it to outputs: each accepted field as `nodes.<id>.<field>`, plus `stateRevision` (int, 0 when no row), `pendingField` (string or null), `exists` (bool).
- **AC-ASR-06 [BE]** The node NEVER writes: no row is created, no revision bump, no compare-and-swap, no commit of state. Reading state for a Correlation key that has no row yet yields `exists=false`, `stateRevision=0`, no field outputs, and the run continues (downstream nodes decide).
- **AC-ASR-07 [BE]** State is tenant- and workflow-scoped; the node can only read the state of a stateful AI Agent node that exists in THIS workflow's published/snapshot graph (validated), never an arbitrary or cross-workflow node id.
- **AC-ASR-08 [BE]** Test/manual runs read the `test` namespace and event/scheduled runs read `prod`, identical to the AI Agent and Clear nodes (D17 isolation preserved) - a debug read never sees live conversation state and vice versa.
- **AC-ASR-09 [BE]** Reading does not require the referenced agent to have executed on the current run (structural reachability, not executed-this-pass): a branch that does not run the agent can still read the durable accumulated state.

### Validation / publish gate

- **AC-ASR-10 [BE][FE]** Publish is blocked (parity: FE `validateDefinition` and BE `definition_issues`) when a Read Agent State node has no `agentNodeId`, or references a node that is not a stateful `ai_agent.run` node present in the graph.
- **AC-ASR-11 [BE]** A run whose Read Agent State node references a missing/removed agent (e.g. draft run after an edit) fails only that node cleanly (`ActionError`, downstream skipped), never a 500.

### Logs / inspection

- **AC-ASR-12 [FE]** The run-node inspector shows the read node's output (the accepted fields + diagnostics) so a builder can see the state a run observed.

### Cross-cutting

- **AC-ASR-13 [E2E]** In the seeded progress-update demo (or a built-via-clicks workflow), a Read Agent State node placed after the AI Agent reports the same accumulated `task`/`status` the AI Agent holds; an IF configured on `nodes.<readNode>.exists` routes correctly. Verified at 375px and 1280px with no document overflow.
- **AC-ASR-14 [FE]** No instructional/hint copy is added to the canvas (foolproof-UI); the node's one-line description identifies what it is, not how to use it.
- **AC-ASR-15 [T]** A Playwright Test Execution Report keyed to these AC ids (PASS/FAIL/DEFERRED) ships with the slice.
