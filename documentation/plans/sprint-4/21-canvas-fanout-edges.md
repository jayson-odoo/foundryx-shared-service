# 21 - Workflow canvas fan-out edges

Contract: `21-canvas-fanout-edges-acceptance-criteria.md`. Backlog: BL-SS-034.

## 1. Why

A node's single output port currently allows one outgoing edge - `lib/workflow-doc.ts addEdge` filters out any existing edge on the same `(source, port)` before appending ("n8n reconnect"). The executor (`app/workflow_engine/executor.py run_workflow`) already fans out (`out_edges` is a list; a non-IF node adds ALL its targets to the active set, an IF adds all targets on the taken port), so the engine, the run-context, debug staleness (`taken_pred`), the React Flow edge render (keyed by edge id), edge deletion (`onEdgesDelete` -> `removeEdge`), and the cycle guard all already handle multiple edges. The ONLY thing blocking fan-out is `addEdge`'s replace step.

## 2. Design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | `addEdge` APPENDS instead of replacing on the same port. | Enables fan-out; the executor already runs all targets. |
| D2 | `addEdge` stays idempotent for an EXACT duplicate (same source+port+target). | Re-dragging an existing wire must not create a second identical edge. |
| D3 | Reconnect-by-replace is dropped; a wrong wire is removed by selecting the edge + Delete (already wired). | Can't both fan out and auto-replace from the same gesture; explicit delete is the n8n/most-canvas norm once fan-out exists. |
| D4 | No backend change - only add a test locking fan-out execution. | The active-set walk already fans out; a diamond re-converging node runs once. |
| D5 | Fix the `onEdgesDelete` stale-doc bug while here. | `deleted.forEach(e => emit(removeDocEdge(doc, e.id)))` recomputes each removal from the SAME captured `doc`, so deleting N selected edges only drops the last. Fold into one pass over the doc. |

## 3. Changes

- `service_frontend/lib/workflow-doc.ts` `addEdge`: drop the same-port filter; before appending, if an edge with the same `source` + `sourcePort` + `target` already exists, return the doc unchanged (idempotent). Keep `newId('e')` + port default.
- `service_frontend/components/platform/workflow-canvas/workflow-canvas.tsx` `onEdgesDelete`: remove all deleted edge ids in a single derived doc (e.g. reduce over `deleted` or a multi-id `removeEdges` helper) then one `emit`, so multi-select edge delete works (AC-FAN-05).
- (optional) `lib/workflow-doc.ts` add a `removeEdges(doc, ids[])` helper if it makes the above clean; otherwise inline.

## 4. Tests

- `[FE]` `lib/workflow-doc.test.ts`: rewrite the `addEdge` "replaces on same port" test to assert fan-out (two edges from `trg` to `act` + `act2` both kept) + a new idempotent-duplicate case. Add an IF-port fan-out case (two edges on `true`). If a `removeEdges` helper is added, unit-test it.
- `[BE]` `tests/test_workflow_engine.py` (or `test_workflow_triggers.py`): a workflow whose action node has TWO outgoing edges runs both downstream nodes (both produce `WorkflowRunNode` success); an IF with two `true`-port edges runs both true targets, zero false targets. (Locks AC-FAN-06 - executor already supports it.)
- `[E2E]` `e2e/canvas-fanout-edges.spec.ts`: build-via-clicks - wire one node to two targets, save/reload persists both, run executes both; 375 + 1280 no overflow. Report `21-...-test-report.md` keyed to the AC ids.

## 5. Risk

Low - one function + one handler. The only behavior change users may notice: dragging a new wire from a port that already has one no longer silently replaces it (it adds). Removing a wire is select-edge + Delete (already supported).
