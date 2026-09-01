# Sprint 2 · Plan 09 - Phase C Test Execution Report

Workflow engine triggers/actions breadth - full-stack QA (real clicks).

**Stack:** frontend `:3001` (prod build) + backend `:8001` (uvicorn, Celery
eager so event runs execute inline). Each spec provisions a **dedicated tenant**
via the operator API; names timestamped (methodology §7).

**Automated coverage backing this report:**
- Backend `tests/test_workflow_triggers.py` - 16 cases: IF true/false routing,
  emit→match→enqueue, field_changed refinement, loop-guard chain exclusion,
  cron `next_run_at` + timezone, the scheduler minute-tick, status_changed
  subscription, storage/transition/update executors, the metadata endpoint, and
  the datetime-fact dispatch regression. Full backend suite **410 passed**.
- Frontend `lib/workflow-doc.test.ts` / `lib/cron.test.ts` - doc helpers,
  validation (incl. duplicate-name + IF branching), replaceNodeType, cron
  compile/parse/describe.
- E2E `e2e/workflows.spec.ts` (slice 08, updated) + `e2e/workflow-triggers.spec.ts`
  (slice 09) - **3 passed**.

---

## US-1 - A real domain event fires a published workflow

| | |
|---|---|
| **User story** | As a tenant admin, when a record is created, a published workflow that triggers on `entity.created` runs automatically. |
| **Scenario** | `entity.created(role) → IF(always true) → email.send` |
| **Precondition** | Dedicated tenant provisioned; the workflow built + published + activated via the tenant-admin API (setup). |
| **Steps** | 1. Sign in as the tenant admin (UI). 2. Go to User Management → Roles → New role. 3. Fill a role name, **Save** (real clicks). 4. Open the workflow → **Logs**. 5. Open the run. |
| **Expected** | A new run appears with status **Success** (triggered by the event); opening it shows the replayed graph (IF true branch → email ran). |
| **Actual** | Run shows **Success** in Logs; run replay canvas opens. ✅ |
| **Remarks** | Earlier false-pass (loose `/roles/[^/]+` regex matched `/roles/new`) fixed by asserting navigation away from `/new`. The event path was independently confirmed via API (role create → 1 run). |

## US-2 - Build a workflow in the editor, publish, run

| | |
|---|---|
| **User story** | As a tenant admin, I build a workflow on the canvas, publish it, and run it. |
| **Scenario** | `manual → email.send (custom)` |
| **Steps** | New workflow → search palette → add Manual → declare an input → add Send email → **wire trigger→action by dragging handles** → configure custom email → name + Save → Publish → Run with an input. |
| **Expected** | Publish gate passes; the run logs **Success**. |
| **Actual** | Edge created by drag (1 edge asserted); publish clears the unpublished badge; run logs **Success**. ✅ |
| **Remarks** | Updated for slice-09 UX: palette sections are collapsed (search to surface), nodes drop **unwired** (no auto-connect → explicit handle drag), and the Email-type field is a searchable SearchSelect. |

## US-3 - Workflow lifecycle on the list

| | |
|---|---|
| **Scenario** | Archive a workflow from the list. |
| **Steps** | Workflows list → select the row → Bulk actions → Archive → switch to Archived view. |
| **Expected** | Gone from Active, present in Archived. |
| **Actual** | ✅ |

---

## Not driven via UI (covered by backend tests)

- **Scheduled trigger firing** - `schedule.cron` arms `next_run_at` on publish;
  the minute-tick (`run_due_workflows`) drains it. Not UI-triggerable (no Celery
  beat/worker in the eager dev stack) - covered by
  `test_scheduler_tick_fires_due_workflow` + `test_compute_next_run_at_respects_timezone`.
- **Loop guard** - a self-updating workflow doesn't storm; covered by
  `test_self_updating_workflow_does_not_storm` (chain-exclusion at depth 1).
