# Test Execution Report — 08 App Store (per-tenant module lifecycle)

**Date:** 2026-06-04 · **Branch:** `sprint-1/app-store` · **Stack:** Next :3001 (prod build) → FastAPI :8001 → Postgres (bootstrapped via `python -m scripts.bootstrap_db`)

## Summary

| Suite | Result |
|---|---|
| Backend pytest (incl. new `tests/test_app_store.py`, 17 cases) | **102 / 102 passed** |
| Frontend Vitest (incl. mock-contract 10, hook 7, card 7) | **96 / 96 passed** |
| Playwright E2E `e2e/app-store.spec.ts` (live stack, real clicks) | **2 / 2 passed** (Phase A ran the same flows vs the mock, 4/4) |
| Full Playwright regression (30 specs) | **29 / 30 passed** — 1 pre-existing env failure (below) |
| `tsc --noEmit` / `eslint` / `npm run build` / Alembic `upgrade head` on Postgres | clean |

**Known unrelated failure:** `omnichannel.spec.ts › connects a channel via Embedded Signup` — `.env.local` carries a real `NEXT_PUBLIC_META_APP_ID`, so the wizard launches the real Meta SDK while the spec drives the simulated popup. Environmental (real Dev-Mode config), predates this branch; passes with Meta env unset.

**Isolation note:** the lifecycle spec provisions a **dedicated tenant** via the operator API before clicking through, so uninstalling omnichannel never disturbs the default tenant other suites use (an earlier draft on the default tenant broke a parallel workspaces spec — fixed by isolation, verified by a clean full-suite run).

## Scenarios (E2E — real user clicks)

| # | User story / Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|---|---|---|---|---|---|
| 1 | Fresh tenant starts uninstalled | Operator-provisioned tenant `e2e-store-<ts>` | New tenant's admin signs in at `<slug>.localhost:3001` | No Omnichannel menu block; App Store card shows "Not installed" + manifest version v0.1.0 | As expected | Catalog synced from `manifest.json` (title/description/icon/version) |
| 2 | Install | Signed in, storefront open | Click **Install** on the Omnichannel card | Badge → Active; Omnichannel menu block appears WITHOUT re-login; menu → Workspaces lists the seeded "General" workspace | As expected | D7 freshness: NextAuth `update()` re-pulls `/auth/me`; `install_tenant` seed + Admin grant verified |
| 3 | Deactivate | Module ACTIVE | **Deactivate** → confirm dialog (copy: data kept) → confirm | Badge → Inactive; menu block disappears | As expected | Backend 403 on module routes pinned by pytest (`test_deactivate_blocks_routes_keeps_data`) |
| 4 | Reactivate | Module INACTIVE | Click **Reactivate** | Badge → Active; menu block returns instantly | As expected | Grants were never removed — restore is free |
| 5 | Uninstall (typed confirm) | Module ACTIVE | **Uninstall** → dialog warns "permanently wipes all Omnichannel data"; confirm button disabled; type `omni` → still disabled; type `omnichannel` → click | Badge → "Not installed"; menu block gone | As expected | Per-tenant wipe isolation (other tenants untouched) pinned by pytest (`test_uninstall_wipes_only_that_tenant`) |
| 6 | Transitional backfill | Default tenant existed pre-App-Store with omnichannel data | Demo admin signs in at `localhost:3001` → App Store | Omnichannel card shows Active @ v0.1.0 (no manual install ever ran) | As expected | `bootstrap_modules` backfill via the module's `tenant_has_data` hook; platform tenant excluded (verified in Postgres) |

## Backend coverage highlights (`tests/test_app_store.py`)

- Catalog + installed endpoints; display fields synced from the manifest.
- Fresh tenant: module routes 403 "Module not installed" pre-install; install seeds the default workspace and is rejected (409) when repeated; unknown module 404.
- **Admin-grant model (plan 08 §5):** new tenant Admin = core keys only; install grants the module's keys; uninstall revokes module grants from ALL tenant roles (verified via login `permissions[]`).
- Deactivate 403s module routes but keeps data; reactivate restores; invalid transitions 409.
- Uninstall: typed-confirm mismatch 422; **two-tenant test proves only the acting tenant's rows are wiped** (module schema + other tenants intact); re-install reseeds.
- `GET /permissions` hides uninstalled modules' keys for tenant callers; `POST /roles` silently drops uninstalled-module keys (not grantable).
- Operator endpoints (`/platform/tenants/{id}/modules/*`): same lifecycle against any tenant; 403 for tenant admins; platform tenant itself can never install (409).
