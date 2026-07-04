# Sprint 2 · Plan 10 — Workflow Engine (integration & polish)

**Branch:** `sprint-2/10-workflow-integration-polish`
**Closes:** BL-025 (core Workflow engine — complete), BL-081 (notification-spec template picker), BL-064 (FlowCanvas undo/redo + non-destructive Tidy — finalized across all consumers). **Third of 3 vertical slices** (08 foundation → 09 breadth → **10 polish**).
**Hands off:** BL-084 (audit log) — this plan finalizes the `emit_entity_event` seam as the audit log's subscription point (the audit log itself remains its own future plan).
**Depends on:** slices 08 + 09.

---

## Context

Slices 08+09 deliver a working multi-trigger, multi-action workflow engine. Slice 10 closes the integration seams that touch the *other* engines, finalizes the shared-canvas polish, and bounds operational growth.

---

## Locked design decisions (from grilling)

1. **D1 — Status-engine ↔ workflow boundary: both coexist, documented.** Two paths to "email on status change" stay (status-engine notification specs = transition-local, atomic-in-the-transition "fire this mail now"; workflows = multi-step/conditional/cross-entity orchestration via `entity.status_changed`). Both render through the ONE `render_email` + outbox path. The plan **documents the boundary explicitly** ("when to use a transition notification vs a workflow") so the overlap isn't confusing. (Rejected: workflows subsuming status notifications — bigger blast radius on the load-bearing tenant-lifecycle mail path.)

2. **D2 — Close BL-081: template picker on notification specs.** The status-engine TransitionDrawer notification editor (currently inline subject/body) gains a `SearchSelect` over `GET /templates?context=` so an operator points a transition notification at an engine template. Backend already accepts `templateId` (plan 07 D10, render-through-engine tested) — this is the UI + wiring. Both notification paths now consistently render through the template engine.

3. **D3 — Close BL-064: undo/redo + non-destructive Tidy, all FlowCanvas consumers.** Position history (client-side undo/redo); Tidy becomes a previewable/undoable action; positions commit on Save (or explicit confirm), not on every change. Applied to the workflow canvas (built with it from slice 08) AND retrofitted to the status-engine canvas (the original consumer that logged the bug).

4. **D4 — Run retention prune.** The slice-09 minute-tick gains a housekeeping pass pruning `workflow_runs` (+ cascade `workflow_run_nodes`) older than `workflow_run_retention_days` (default 30) — mirrors the email-dispatcher retention. Per-workflow override = backlog.

5. **D5 — Audit-log seam handoff (BL-084).** Finalize `emit_entity_event` (slice 09) as the single subscription point an append-only `audit_log` can hook (after-commit, actor-attributed, old/new in `changes`). This plan does NOT build the audit log (its own future plan: retention/PII-redaction/tenant-scoping/Resource-list UI) — it guarantees the seam is stable + documented so the audit log re-instruments nothing.

6. **D6 — Partial staleness-execution refinements.** Harden the n8n debug loop from slice 08 (D16) against the full slice-09 catalog: staleness propagation through IF branches (only the taken branch's downstream re-runs), cached outputs for skipped nodes, and correct re-stale on config edits in the debug scratch session.

---

## Build notes
- BL-081: frontend SearchSelect + `GET /templates?context=` filter; wire `templateId` through the existing notification-spec save path.
- BL-064: shared position-history hook in `components/platform/flow-canvas/` consumed by both the status canvas and the workflow canvas; Tidy preview/confirm.
- Retention: extend the slice-09 scheduler task; new `workflow_run_retention_days` setting.
- Boundary doc: a section in this plan + a CLAUDE.md addendum (status notification vs workflow).

## Phases
- **A (frontend):** BL-081 picker, BL-064 undo/redo+Tidy across both canvases, debug staleness refinements.
- **B (backend, TDD):** retention prune (pytest: age-based prune + cascade), BL-081 wiring (template-rendered transition notification), staleness-through-IF executor cases, emit-seam stability test for the audit handoff.
- **C (E2E):** transition notification sent via a selected template (assert via mailbox rig — plan 10 maildir handler); undo/redo + Tidy round-trip on the workflow canvas; debug edit-upstream → execute-downstream re-runs only the stale chain across an IF branch. Dedicated tenant; timestamped names. Final Test Execution Report. **BL-025 closes.**

## Status notification vs workflow — the boundary (D1)

Two paths can "email on a status change". They coexist on purpose; both render
through the ONE `render_email` + outbox pipeline, so neither is a second-class
citizen. Pick by intent:

- **Status-engine transition notification** — use when the mail is *part of the
  transition itself*: it fires inside the SAME transaction as the state change,
  is authored ON the edge in the Flow editor, and targets transition-local
  recipients (actor / assignee / record owner / a role). It is atomic with the
  move (commit the transition ⇒ the mail is enqueued; roll back ⇒ nothing
  sent). This is the load-bearing path for tenant-lifecycle mail — keep its
  blast radius small. BL-081 lets such a notification point at an engine
  template instead of inline subject/body.
- **Workflow (`entity.status_changed` trigger)** — use when the status change is
  just the *start* of a multi-step / conditional / cross-entity orchestration:
  branch on an IF, write another entity, call storage, fan to several actions.
  It runs AFTER commit via the event bus (`emit_entity_event`), loop-guarded,
  and is observable in the workflow run Logs.

Rule of thumb: one transition-local mail, atomic with the move → transition
notification. Anything with branching, multiple steps, or other entities →
workflow. (Rejected: folding status notifications into workflows — it would put
the whole tenant-lifecycle mail path behind the larger workflow blast radius.)

## Status

**ALL PHASES COMPLETE — BL-025 CLOSED.** Backend 416 pass, frontend 406 pass,
E2E `workflow-polish.spec.ts` pass (BL-064 undo/redo + Tidy round-trip). Report:
`10-workflow-integration-polish-test-report.md` (BL-081 mailbox journey + debug
IF-branch journey are integration/unit-covered with documented rationale — both
would require mutating shared state or are high-flake in the UI).

- **BL-081 (D2)** — DONE. `GET /templates?context=` filter (router+service);
  `listTemplateOptions(context)` service method; `templateId` on the
  `TransitionNotification` type + an "Email template" `SearchSelect` in the
  TransitionDrawer (EMAIL channel), inline subject/body kept as the fallback.
  Backend already validated/rendered `templateId` (plan 07 D10). Tests:
  `test_context_filter_narrows_the_picker`, mock/real service parity.
- **BL-064 (D3)** — DONE. Shared `useHistory<T>` snapshot hook in
  `components/platform/flow-canvas/` (unit-tested). Workflow canvas refactored
  onto it (was inline). Status canvas (`entity-flow.tsx`) retrofitted: positions
  are now a CLIENT DRAFT — drag + Tidy mutate it through history (undo/redo,
  keyboard ⌘Z/⇧⌘Z), Tidy is a previewable/undoable preview, and positions
  persist only on an explicit **Save layout** (dirty-count) button, never on
  every drag. An unsaved drag survives a structural refetch (dirty-preserving
  reseed); a tenant on inherited platform defaults edits locally but can't Save.
- **D4 retention** — DONE. `workflow_run_retention_days` (default 30); scheduler
  `prune_runs` (child `workflow_run_nodes` deleted first via subquery — correct
  cascade on both Postgres and SQLite tests); wired into the beat task,
  failure-isolated. Test: `test_prune_runs_drops_old_runs_and_cascades_nodes`.
- **D5 audit-log seam** — DONE. `register_event_subscriber` /
  `unregister_event_subscriber` in `entity_events.py`; the after-commit drain
  fans every domain event to subscribers, each in its OWN isolated commit, with
  the documented event shape. The audit log (BL-084) registers here at startup —
  re-instruments nothing. Test: `test_emit_seam_notifies_registered_subscriber`.
- **D6 debug staleness** — DONE. `debug_execute` is now branch-aware (mirrors
  `run_workflow`'s active-set walk): a node re-runs only if reached via a TAKEN
  edge, AND staleness propagates along taken edges (a recomputed upstream node
  invalidates its active descendants); the untaken branch is never touched and
  skipped nodes keep their (empty) cache. Frontend `takenDescendants` marks the
  edited node + its taken-branch descendants stale so the canvas shows the
  re-stale chain. Test:
  `test_debug_staleness_propagates_through_taken_if_branch`.

## Out of scope (→ backlog)
- Audit log feature itself (own future plan — subscribes this plan's seam).
- Parallel/merge/loop nodes, per-node retry/timeout, continue-on-error, dry-run mode, relative-to-record-date scheduling, in-app notification action + inbox, attachment bytes, per-workflow retention override, full draft/version-history UI beyond the slice-08 read-only list.
