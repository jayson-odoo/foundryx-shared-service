# 20 - Read-only Agent State workflow node

Contract: `20-agent-state-read-node-acceptance-criteria.md`. Follows plan sprint-4/19. Backlog: BL-SS-033.

## 1. Why

Plan 19 shipped durable per-field Agent state (`workflow_agent_states`) that the AI Agent node loads and reduces every run - the AI already "remembers across turns." What is missing is a way to READ that accumulated state on the canvas WITHOUT running an AI Agent node: to branch on it, feed it to a Code/Send Message node, or inspect it. The Clear Agent State node already exists as the write-side lifecycle action; this adds the read side.

By product decision the node is **read-only**. A write node was deliberately rejected in plan 19 (line 29): direct writes would bypass the evidence-checked reducer that is the whole memory-safety contract. Writes stay through the AI Agent node; this node only reads. State remains per-field structured state keyed by the Correlation key - NOT last-N-turns transcript (out of scope, plan 19 D11 / line 434).

## 2. Design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | New action node `ai_agent.read_state` (core, category Actions), sibling of `ai_agent.clear_state`. | Reuses the existing agent-node picker, reachability set, namespace, and `AgentStateService`. No new table, permission, or engine. |
| D2 | Single config field `agentNodeId` (type `agentNode`), restricted to stateful `ai_agent.run` nodes that are STRUCTURAL ancestors. | Same picker + `reachableAgentNodes` restriction the Clear node uses; identity stays ID-based (D5 of plan 19). |
| D3 | Read-only: `AgentStateService.load` only. No CAS, no write, no commit, never creates a row. | The reducer stays the sole validated writer (plan 19 line 29). |
| D4 | Runtime guard is STRUCTURAL reachability (the referenced node is a stateful agent in the snapshot graph), NOT executed-this-pass. | A read is durable and safe regardless of branch/order; requiring the agent to have run this pass would defeat the read-on-a-branch use case. Differs deliberately from Clear (which is a mutation tied to a just-completed agent). |
| D5 | Outputs = the selected agent's accepted stateful fields flattened as `nodes.<id>.<field>`, plus reserved diagnostics `stateRevision` (int), `pendingField` (str\|null), `exists` (bool). | Mirrors how `ai_agent.run` exposes stateful outputs so IF / Send Message / Code reference `nodes.<readNode>.<field>` directly. Reserved keys mirror plan 19's `stateRevision`/`pendingField` diagnostics. |
| D6 | Namespace = `test` for manual/test/debug runs, `prod` otherwise. | Identical to the AI Agent and Clear nodes (D17 isolation). |
| D7 | Publish gate (FE+BE parity): `agentNodeId` must reference a stateful `ai_agent.run` node present in the graph. | Foolproof-UI: only valid targets; no arbitrary id. |

## 3. Backend

- `app/workflow_engine/actions/agent_state_actions.py`: add `read_agent_state(db, tenant_id, config, ctx)`:
  - `node_id = config["agentNodeId"]`; read `_workflow.workflowId`, `_workflow.correlationKey`, namespace (`_workflow.agentStateNamespace` else test/prod from `_workflow.isTest`) - same as `clear_agent_state`.
  - Guard: `node_id in ctx["_workflow.statefulAgentIds"]` (new structural set, see below) else `ActionError` (AC-ASR-07/11).
  - `row = AgentStateService(db).load(tenant, workflow, node_id, correlation_key, namespace=...)`.
  - Return `{**(row.state_json if row else {}), "stateRevision": row.state_revision if row else 0, "pendingField": row.pending_field if row else None, "exists": row is not None}`. Reserved keys win over a same-named accepted field (documented; same collision convention as plan 19 diagnostics).
- `app/workflow_engine/executor.py`: inject `ctx["_workflow.statefulAgentIds"] = sorted(stateful ids in the snapshot doc)` once, in both `run_workflow` and `debug_execute` (compute `{n.id for n in doc.nodes if _stateful_agent(n)}`). Structural, order-independent (D4).
- `app/workflow_engine/registry.py`: register `ActionDef(key="ai_agent.read_state", label="Read Agent State", icon="BookOpen", category="Actions", executor=read_agent_state, fields=[NodeField("agentNodeId", "Agent", "agentNode", required=True)], outputs=[NodeOutput("stateRevision",...), NodeOutput("pendingField",...), NodeOutput("exists",...)])`. Per-agent fields are dynamic (FE resolves, like `ai_agent.run`).
- `app/workflow_engine/schemas.py` `definition_issues`: a `ai_agent.read_state` node needs `agentNodeId` referencing a node that is a stateful `ai_agent.run` in the doc (AC-ASR-10).

## 4. Frontend

- `lib/workflow-catalog.ts`: catalog entry `ai_agent.read_state` (core), Actions, `agentNodeId` field `agentNode`, description "Read the current saved values from an earlier AI Agent." (identifies what, not how - AC-ASR-14). Comment that outputs are dynamic.
- `components/platform/workflow-canvas/node-config-drawer.tsx`:
  - `agentNode` field type already renders the picker (restrict list via the existing `reachableAgentNodes`).
  - New `readStateOutputParams(node, doc)`: resolve `config.agentNodeId` -> the referenced node's stateful `aiOutputParams` -> return those params; used in `upstreamGroups` and `aiFactsFor` so the read node exposes `nodes.<id>.<field>` + reserved diagnostics (AC-ASR-03/04).
- `lib/workflow-doc.ts` `validateDefinition`: mirror the publish gate (AC-ASR-10).
- Node renderer shows the selected agent's display name.

## 5. Tests

- `[BE]` `tests/test_agent_state_read_node.py`: load+flatten (fields + diagnostics), no-row -> `exists=false`/`stateRevision=0`, read-only (no row created, revision unchanged after read), namespace isolation (test vs prod), missing/removed agent -> `ActionError` downstream-skipped, structural reachability (reads without the agent running this pass), tenant scope.
- `[FE]` vitest: catalog entry + `agentNode` picker restriction; `readStateOutputParams` resolves the referenced agent's stateful keys into the picker/IF facts; publish-gate parity.
- `[E2E]` `e2e/agent-state-read-node.spec.ts`: build-via-clicks (or extend the seeded demo) - Read node after the AI Agent reports the accumulated task/status; IF on `nodes.<readNode>.exists` routes; 375 + 1280 no overflow. Report `20-...-test-report.md` keyed to the AC ids.

## 6. Out of scope

- Any WRITE/set-state node (rejected - safety contract). Transcript / last-N-turns memory (plan 19 D11). A drawer inspection panel (superseded by this node). MCP/tool attachment (BL-SS-031).
