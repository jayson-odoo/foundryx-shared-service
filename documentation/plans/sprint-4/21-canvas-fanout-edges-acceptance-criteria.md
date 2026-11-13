# 21 - Workflow canvas fan-out edges - User Acceptance Criteria

Contract for `21-canvas-fanout-edges.md`. Backlog: BL-SS-034.

Today a workflow node's output port allows only ONE outgoing edge - drawing a second from the same port REPLACES the first (`addEdge` "n8n reconnect" behavior). The executor already fans out (a non-IF node activates ALL downstream targets; an IF activates all targets on the taken port), so this is a purely frontend limitation. This slice lets one output port drive MULTIPLE downstream nodes.

Tags: `[FE]` frontend, `[BE]` backend, `[E2E]` end-to-end, `[T]` test.

## Slice - fan-out edges

- **AC-FAN-01 [FE]** Dragging a second (and third, ...) edge from the same node output port ADDS an edge; it no longer removes the existing one. One source port can connect to N distinct targets.
- **AC-FAN-02 [FE]** An exact duplicate edge (same source, same port, same target) is not added twice - `addEdge` is idempotent for an identical connection (no duplicate edge id, no double-render).
- **AC-FAN-03 [FE]** Fan-out works from every port kind: an action's `out` port and an IF node's `true` / `false` ports can each fan out to multiple targets.
- **AC-FAN-04 [FE]** The cycle guard still holds - a connection that would create a loop is still rejected (unchanged).
- **AC-FAN-05 [FE]** A wrong wire is removable: selecting an edge and pressing Delete/Backspace (or the existing edge-delete path) removes that specific edge and only it. Deleting multiple selected edges at once removes all of them (fixes a stale-doc bug where only the last was removed).
- **AC-FAN-06 [BE]** A published/run workflow whose node has two outgoing edges executes BOTH downstream branches (already supported by the executor - locked with a test). An IF node with two edges on its `true` port runs both true-branch targets and neither false-branch target.
- **AC-FAN-07 [FE][BE]** Publish validation is unchanged and correct for fan-out: a diamond (two paths re-converging on one node) publishes; reachability + orphan checks still pass; a node reached by two edges is not flagged.
- **AC-FAN-08 [E2E]** In a built-via-clicks workflow, one node's output is wired to two downstream nodes; both render, both persist through save/reload, and a run executes both. Verified at 375px and 1280px with no document overflow.
- **AC-FAN-09 [T]** A Playwright Test Execution Report keyed to these AC ids ships with the slice.

## Out of scope

- Auto-layout/Tidy aesthetics for wide fan-out (dagre already handles DAGs; no bespoke layout work). Edge labels/styling beyond what exists. Merge/join semantics (a re-converging node already runs once via the active-set walk).
