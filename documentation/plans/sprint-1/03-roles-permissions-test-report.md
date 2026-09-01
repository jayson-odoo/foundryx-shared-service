# 03 - Roles & Permissions + Impersonation - Test Execution Report

**Sprint:** 1 · **Branch:** `sprint-1/roles-permissions` · **Plan:** [03-roles-permissions](./03-roles-permissions.md)
**Stack under test:** Next 15 (:3001) → FastAPI (:8001) → Postgres. Seed: `python -m scripts.bootstrap_db`.
**Demo data:** `demo@example.com` = Admin (all 43 perms); `demo@kt.com` (KT Demo) = Member (0 perms).

## Automated coverage summary

| Layer | Tool | Tests | Result |
|------|------|-------|--------|
| Backend | pytest (in-memory SQLite) | 58 | ✅ pass |
| Frontend unit | Vitest + RTL | 38 | ✅ pass |
| E2E | Playwright (real clicks, live stack) | 6 | ✅ pass |

Backend highlights: role CRUD tenant-scoped; blanket implied-read normalization on save; `is_system`
delete guard; `require_permission` 403/200; effective-keys union; catalog sync idempotency;
impersonation gate + header-honored-only-with-active-session + effective/real split + **no-escalation
(impersonator must hold ⊇ target's permissions)**.
Frontend unit: implied-read lock helpers, role schema, impersonation store.

---

## E2E scenarios (Playwright - `e2e/roles-permissions.spec.ts`)

### US-1 - Browse roles
**Scenario:** Admin views the roles list.
**Precondition:** Logged in as Admin.
**Steps:** Sidebar → User Management → Roles.
**Expected:** List shows seeded roles with descriptions + computed counts.
**Actual:** "Full system access…" + "Read-only access…" rows visible. **Result: ✅**

### US-2 - Search by assigned user + permission
**Scenario:** Admin searches roles by an assigned user's name and by a permission key.
**Precondition:** Admin holds `orders.approve` + has the demo user assigned.
**Steps:** On Roles, search "Demo"; then "orders.approve".
**Expected:** Both match Admin; a role lacking the permission (Viewer) is excluded.
**Actual:** Admin shown for both; Viewer excluded for the permission search. **Result: ✅**

### US-3 - Open role form (tabs + record nav)
**Scenario:** Admin opens a role to inspect it.
**Steps:** Click the Viewer role row.
**Expected:** Permissions / Assigned Users / Settings tabs + circular `N / M` record-nav.
**Actual:** All three tabs + pager visible. **Result: ✅**

### US-4 - Permission catalog renders
**Scenario:** Admin views a role's permissions.
**Steps:** Open Admin → Permissions tab.
**Expected:** Catalog grouped by resource, incl. custom-action resources (Orders & Delivery,
Reports & Analytics).
**Actual:** Both resource rows visible. **Result: ✅**

### US-5 - Create then delete a role
**Scenario:** Admin creates a custom role and deletes it.
**Steps:** Add role → (Settings opens first) name "E2E Temp Role" → Create → `…` → Delete role →
confirm.
**Expected:** Detail shows the new role; after delete, returns to list and the role is gone.
**Actual:** Heading shown on create; row absent after delete. **Result: ✅**

### US-6 - Impersonation → no-access page → exit
**Scenario:** Admin impersonates a 0-permission user to verify the access gating, then exits.
**Precondition:** KT Demo is an active Member with no permissions.
**Steps:** Users → search "kt" → KT Demo `…` → Impersonate → confirm.
**Expected:** Amber banner ("You are impersonating …, recorded under your own account"); the current
page shows the friendly **"You don't have access to this page"**; Exit restores the list.
**Actual:** Banner shown; no-access page shown; Exit restored the Users list. **Result: ✅**

---

## Manual / visual confirmation (Playwright screenshots during build)
- Roles list (counts, System badge), detail Permissions tab (read pills + edit dropdowns with the
  implied-read lock), Assigned Users (search + assign + remove, name→user-form link), Settings
  `is_system` toggle, searchable-fields hint, impersonation banner collapse/expand.

## Notes / known limitations
- Sessions issued before `permissions[]` existed require one re-login (deploy-time, documented).
- Core catalog groups under a single "CORE" section by design (module = owning App-Store module).
- Frontend `can()` is UX-only; `require_permission` is the security boundary (backend-tested).
