# Test Execution Report — Sprint 2 · Plan 08 (Workflow Engine, foundation slice)

**Date:** 2026-06-09
**Branch:** `sprint-2/08-workflow-engine`
**Scope:** Phase C E2E (real clicks, live stack) over the foundation slice — manual trigger + email.send (template + bare-email), publish/versioning, run-the-draft, run logs, list bulk archive. Triggers/actions breadth = slice 09.

## Environment
- Frontend `:3001` (production build, `npm start`), Backend `:8001` (`uvicorn --reload`), Postgres, Celery **eager** (runs inline) — plan-08 branch, migrated (`0b0a96337c3d`) + seeded.
- `workflows.read/manage/run` in the core permissions CSV, granted to the tenant Admin.
- Playwright `@playwright/test`, chromium, real clicks; spec `e2e/workflows.spec.ts`.

## Isolation
Per methodology §7, building + running workflows mutates tenant state, so the suite provisions a **dedicated tenant** (`e2e-wf-<timestamp>`) via the operator API (setup only); the flows under test are real clicks. All created names are timestamped.

## Backend automated coverage (pytest)
`tests/test_workflow_engine.py` — **13 cases, all green** (full backend suite: **394 passed**):
validate gate (complete graph, missing trigger, orphan + missing required config, two triggers, custom-mode requires subject/body + hides template), topological order, full API lifecycle (create → publish-empty 422 → set draft → publish v1 → run success → logs → run detail/replay nodes), run-enqueues-email, custom (bare) email validates + runs + enqueues `workflow.custom` with merged values, edit-after-publish → unpublished → publish v2 → unpublish, archive/restore views, debug execute, tenant scoping, permission gate (401).

Frontend unit: `lib/workflow-doc.test.ts` — **12 cases green** (node factory, edge replace-on-port, cycle guard, topo order, validate matrix).

---

## E2E Scenarios

### US — As an admin, I build an automation that emails on demand.

| # | Scenario | Precondition | Steps | Expected | Actual | Result |
|---|----------|--------------|-------|----------|--------|--------|
| 1 | Build a manual → custom-email workflow, publish, run, see the log | Dedicated tenant provisioned; admin can sign in | Sign in → /workflows → **New workflow** → click palette **Manual** → on the trigger add input `email`/`Email` → click palette **Send email** (auto-connects) → set **Email type = Write a custom email** → fill Subject/Body/To (`{{ trigger.input.email }}`) → Settings → name it → **Save** → Editor → **Publish** → **Run** → enter `e2e@example.com` → **Logs** | Workflow saves; publish passes the validate gate (no "unpublished changes" badge after); run executes inline; Logs shows a **Success** run | As expected — node added via click-to-add, auto-connected; custom-email fields appeared on toggle; published cleanly; run succeeded; Logs two-pane shows Success | ✅ Pass (3.3s) |
| 2 | Workflow appears in the list and can be archived (bulk) | Workflow from #1 exists | /workflows → find the row → tick its checkbox → **Actions ▸ Archive** → switch to **Archived** view | Row leaves the Active view and appears under Archived | As expected — bulk archive removed it from Active; visible in Archived | ✅ Pass (1.8s) |

**Suite:** 2 passed (7.5s).

## Selector notes (for future specs)
- Canvas nodes target by `[data-node-type="manual"]` / `[data-node-type="email.send"]` (stable; the per-id testid is dynamic).
- **Click-to-add** is the E2E path (dnd-kit palette drag isn't drivable by Playwright); actions **auto-connect** from the current leaf, so no handle-drag is needed.
- Conditional fields (`showWhen`) drive the bare-email toggle; the mode select is `field-mode` (Radix → `getByRole('option', …)`).
- Bulk actions are ONE dropdown (`button[aria-label="Bulk actions"]` → `menuitem`); the Active|Archived control is a Radix ToggleGroup (`getByRole('radio', …)`).

## Known follow-ups (not regressions)
- Triggers/actions breadth (entity/status/schedule triggers, storage/transition/update actions, IF node) + the CRUD event bus → **slice 09**.
- BL-081 (notification template picker), BL-064 final polish, retention, audit-log seam → **slice 10**.
- Dedicated E2E tenants accumulate (`e2e-wf-*`) — BL-069 teardown applies.
- `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning (codebase-wide, pre-existing).
