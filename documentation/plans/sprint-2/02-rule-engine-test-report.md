# Test Execution Report - Sprint 2 · Plan 02 (Rule Engine)

**Branch:** `sprint-2/02-rule-engine` · **Date:** 2026-06-06 · **Stack:** live (FastAPI :8001 + Next prod build :3001, Postgres)

## Automated coverage

| Layer | Suite | Result |
|---|---|---|
| Backend | `tests/test_rule_engine.py` (28: evaluator matrix, fail-closed D5, cross-fact D4, depth guard, validate_tree 422 shapes, registry inference + core sources, prose, edge integration block/pass/hide, 409 prose, fireable-ids wire, /rule-facts, /rules agg + perm) | 28/28 ✅ |
| Backend | full suite (`python -m pytest -q`) | 230/230 ✅ |
| Frontend | Vitest (`npm test`) incl. RuleBuilder (9) + drawer read-only | 211/211 ✅ |
| E2E | `e2e/rule-engine.spec.ts` + regression `status-engine.spec.ts`, `tenants.spec.ts` | 11/11 ✅ |

## E2E scenarios (real clicks, per §6)

### 1. Edge condition: build → observe → enforce → cleanup
- **User story:** As a platform operator I gate a lifecycle transition behind a record condition so only qualifying records offer the action.
- **Precondition:** Live stack, seeded platform graph, operator login.
- **Steps:** provision timestamped tenant → Platform Engines ▸ Status Engine ▸ Tenant → Edit → click Suspend edge → drawer Conditions → Add condition → fact "Slug" (searchable picker, server facts) → operator "is not" → value = tenant slug → Save → reopen drawer (round-trip) → Platform Engines ▸ Rules → row "Tenant · Active → Suspended" with prose "Slug is not …" → row deep-links to canvas → Tenants console → non-qualifying row: Actions menu hides Suspend, keeps Archive → remove condition → Suspend returns.
- **Expected = Actual:** ✅ all assertions.
- **Remarks:** condition shape (`Slug is not <own-slug>`) keeps parallel specs unaffected (passes for every other record).

### 2. Tenant admin reaches Rules page
- **Steps:** demo admin login → Workspace Settings ▸ Rules.
- **Expected = Actual:** ✅ page renders (rules.read via Admin grant), empty list, no NoPermission.

## Defects found & fixed during verification
1. **Sidebar accordion** - deep-link navigation collapses other menu groups; spec helper expands before clicking (spec-side fix).
2. **Duplicate platform edge residue** - a second Active→Suspended "Suspend" edge existed on the platform tier (manual-testing residue). `uq_transition_edge(tenant_id, from, to)` does NOT enforce for `tenant_id NULL` rows (Postgres NULLS DISTINCT) - service-level dup check exists, but the constraint is non-binding on the platform tier. Logged as backlog (BL-065).
3. **E2E residue** - 41 `e2e-*` tenants crowded seeded rows off page 1, breaking `tenants.spec.ts` (documented plan-09 failure mode, BL-035). Purged manually.

## Known gaps (by design / deferred)
- Frontend mock fact `actor.status` options said `active/inactive`; real wire returns `ACTIVE/INACTIVE/BLOCKED/INVITED` (mock is test-only).
- Rule-blocked transition buttons are HIDDEN; "disabled with reason tooltip" polish = deferred per plan.
- Hybrid named-rules catalog = deferred per plan (D1).
