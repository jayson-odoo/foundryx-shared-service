# Test Execution Report - 07 Tenant Core & Platform Console

**Date:** 2026-06-04 · **Branch:** `sprint-1/tenant-core` · **Stack:** Next :3001 → FastAPI :8001 → Postgres (bootstrapped via `python -m scripts.bootstrap_db`)

## Summary

| Suite | Result |
|---|---|
| Backend pytest (incl. new `tests/test_tenants.py`, 15 cases) | **84 / 84 passed** |
| Frontend Vitest (incl. slug-lib + tenant-schema units) | **70 / 70 passed** |
| Playwright E2E `e2e/tenants.spec.ts` (live stack, real clicks) | **5 / 5 passed** |
| Full Playwright regression (28 specs) | **27 / 28 passed** - 1 pre-existing env failure (below) |
| `npm run lint` / `npm run build` / Alembic `upgrade head` on Postgres | clean |

**Known unrelated failure:** `omnichannel.spec.ts › connects a channel via Embedded Signup` - `.env.local` carries a real `NEXT_PUBLIC_META_APP_ID`, so the wizard launches the real Meta SDK while the spec drives the simulated popup. Environmental (real Dev-Mode config), predates this branch; passes with Meta env unset.

## Scenarios (E2E - real user clicks)

| # | User story / Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|---|---|---|---|---|---|
| 1 | Operator sees the Platform Console | Seeded platform tenant + operator (`platform@example.com`) | Sign in at `platform.localhost:3001` → sidebar → Tenant Management → Tenants | Platform menu visible; list shows seeded tenants; platform row badged | As expected | Subdomain tenant resolution (plan 07 §6) |
| 2 | Tenant admin has no console | Demo Admin (default tenant) | Sign in at `localhost:3001` | No Platform menu section | As expected | Platform keys never granted to tenant roles |
| 3 | Platform tenant protected | Operator signed in | Open platform row `…` menu | No Suspend/Archive items; Edit only | As expected | Backend also 409s (pytest) |
| 4 | Provision → suspend → reactivate → archive lifecycle | Operator signed in | Add tenant (`e2e-<ts>`, first admin + temp password) → new admin signs in at `<slug>.localhost` → operator suspends → admin login blocked → reactivate → login works → archive → row leaves Active view, appears in Archived view | Full lifecycle enforced end-to-end | As expected | Suspension kills live sessions per-request (pytest covers `/auth/me` 403) |
| 5 | Reserved slug rejected | Operator on New tenant form | Slug `platform` → Create | Inline "This slug is reserved."; stays on form | As expected | Mirrors backend 422 |

## Backend coverage highlights (`tests/test_tenants.py`)

- `require_platform_permission` double lock (tenant admin 403 even before grant check fails).
- Uniform 401 for unknown tenant slug (no enumeration); per-tenant login isolation (demo user can't log in via `platform` slug).
- Provisioning transaction: tenant + 7 seeded system roles + first admin (Admin role, core-only grant - no platform keys).
- Suspend blocks login (403 "suspended") AND kills live JWT sessions; reactivate restores both.
- Archive → `status_view=trashed`; invalid transitions + platform-tenant protection → 409.
- Permission catalog hides `module=platform` rows from tenant callers.
- **BL-015 regression:** `user_roles.tenant_id` / `role_permissions.tenant_id` carry the owning role's tenant for a freshly provisioned tenant.
