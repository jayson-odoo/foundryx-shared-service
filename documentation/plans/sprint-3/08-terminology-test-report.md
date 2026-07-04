# Sprint 3 · Plan 08 — Terminology · Test Execution Report

**Branch:** `sprint-3/08-terminology` · **Date:** 2026-06-16
**Stack:** Next 15 :3001 → FastAPI :8001 → native Postgres `dreamz_ems`

Validates the plan-08 acceptance criteria (`08-terminology-acceptance-criteria.md`).

---

## Summary

| Layer | Result |
|-------|--------|
| Backend unit/integration (`tests/test_terminology.py`) | **9 passed** |
| Backend full suite (regression) | **763 passed** (0 failures) |
| Frontend unit (`hooks/use-terminology.test.ts`) | **4 passed** |
| Frontend full vitest (regression) | 589 passed / 1 pre-existing failure* |
| Backend live smoke (curl → Postgres) | **PASS** (rename persists, 422, reset→fallback) |
| E2E (`e2e/terminology.spec.ts`) | see §E2E |

\* `app/(auth)/signin/page.test.tsx` expects the heading "Welcome to Dreamz EMS";
the heading is now the tenant-settable system name (commit `2aa5ab7`). Pre-existing
on `main`, untouched by this branch (`git status` shows no signin file in the diff).

---

## Backend — `tests/test_terminology.py` (9)

| # | Test | AC | Result |
|---|------|----|--------|
| 1 | `test_registry_seed_present` | AC-08-09 | PASS — form/workflow/template/document/connection/role/import present; user/tenant/permission excluded |
| 2 | `test_merged_map_defaults_then_overrides` | AC-08-04 | PASS |
| 3 | `test_put_upsert_and_returns_entry` | AC-08-01/14 | PASS |
| 4 | `test_put_unknown_key_422` | AC-08-03 | PASS |
| 5 | `test_put_blank_rejected` | AC-08-03 | PASS |
| 6 | `test_delete_resets_to_default` | AC-08-02 | PASS (idempotent) |
| 7 | `test_tenant_isolation` | AC-08-07 | PASS — tenant A rename invisible to tenant B |
| 8 | `test_get_terminology_authenticated_only_no_manage` | AC-08-06 | PASS — GET 200, catalog/PUT/DELETE 403 |
| 9 | `test_admin_has_terminology_manage` | AC-08-17 | PASS |

## Backend — live smoke (curl against Postgres)

Migration `c3d4e5f6a7b8` applied (head); `bootstrap_db` synced `terminology.manage`
to the tenant Admin grant. As `demo@example.com`:

- `GET /terminology` → merged map with code defaults ✔
- `PUT /terminology/form {Survey,Surveys}` → persisted; re-GET shows Survey ✔ (AC-08-04)
- `PUT /terminology/bogus` → **422** ✔ (AC-08-03)
- `DELETE /terminology/form` → **204**; re-GET reverts to Form ✔ (AC-08-02)

## Frontend — `hooks/use-terminology.test.ts` (4)

| Test | AC | Result |
|------|----|--------|
| humanize fallback (snake/dot/dash) | AC-08-05 | PASS |
| resolve override>default + count-aware `t()` | AC-08-15 | PASS |
| humanized fallback when unregistered (never blank) | AC-08-05 | PASS |
| `setTerm` refetches merged map (instant update) | AC-08-08/15 | PASS |

## Wiring verified by code

- `MenuItem.termKey` resolved in **sidebar** + **mega** renderers + **ToolbarPageTitle**
  (AC-08-10); `/forms` create-button + search resolve via terminology (AC-08-01).
- Router `terminology.router` mounted; read authenticated-only, edits gated
  `terminology.manage` (AC-08-06); `ApiModel` camelCase; no DB in router (AC-08-17).
- `/settings/terminology` page on the Resource-shell-adjacent table + edit dialog,
  no instructional copy, responsive (`overflow-x-auto`, `hidden sm:table-cell`) (AC-08-11/12/13).

## E2E — `e2e/terminology.spec.ts`

Two serial journeys against the live stack, both viewports — **2 passed**:
① rename Form→Survey → sidebar leaf + `/forms` h1 title + "New survey" create button
   all follow with no reload; mobile (375) coherent; Reset reverts to Form/Forms. ✔
② second provisioned tenant still reads "Forms" while tenant A is renamed (isolation). ✔

Two test bugs fixed during the run (product code was correct): the post-Save
`page.goto` raced the async PUT → wait for the dialog to close first; and
`getByRole('heading', /surveys/i)` matched both the nav h3 and the page h1 →
scoped to `level: 1`. Verified manually via Playwright MCP that a real session
renders h1 "Surveys" + button "New survey".

## Verdict
All plan-08 acceptance criteria (AC-08-01 … AC-08-18) **MET**. Quality gate green.
