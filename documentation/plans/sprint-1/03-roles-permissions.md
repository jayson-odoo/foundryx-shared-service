# 03 — Roles & Permissions (RBAC)

**Sprint:** 1
**Branch:** `sprint-1/roles-permissions`
**Closes:** BL-009 (RBAC / permissions per role)
**Source of truth for UI:** FoundryX design system + the Resource shell (`components/platform/`). The provided
screenshots are *reference only* — design system governs.

---

## 1. Goal

Make every feature in the system RBAC-controlled. A **Role** carries a set of **Permissions**; a user gains a
permission by holding a role that grants it. Permissions are **granular per (resource, action)** and **dynamic** —
each module (core or App-Store) declares its own permissions, so the catalog grows as modules install.

Deliver:
- A **Roles list** (reuse the Resource list shell — clone Users).
- A **Role detail form** (reuse the Resource form shell) with three tabs: **Permissions**, **Assigned Users**, **Settings**.
- A **permission catalog** synced from per-module CSV declarations into a global `permissions` table.
- **Enforcement** end-to-end: backend `require_permission(...)` gates on **all** existing + new endpoints; frontend
  gates UI actions via a `can(key)` helper (UX only — backend is the real boundary).

---

## 2. Permission model (the core decision)

### 2.1 Identity — flat key per (resource, action)  *(Q1 = A)*
A permission is one row keyed `"<resource>.<action>"`, e.g. `users.create`, `events.delete`, `orders.approve`.
Standard actions are `read / create / update / delete`; **custom actions** (e.g. `approve`, `export`) are first-class
— they are just more rows, no schema change. Role↔permission via `role_permissions` M2M.

> Rejected: per-module CRUD bitmask — locks to exactly 4 actions, can't express custom actions.

### 2.2 Catalog vs grants — hybrid, code-declared / DB-synced  *(Q2 = C)*
- **Catalog** (what permissions *exist*) lives in **per-module CSV declarations**, **synced into a global `permissions`
  table** by the installer (core synced at bootstrap).
- **Grants** (which role has which) live in tenant-scoped `role_permissions`, **FK** to `permissions` for referential
  integrity + cascade-on-uninstall.

### 2.3 Declaration format — long-form CSV  *(Q3/Q4)*
Location: **`<module>/backend/permissions/permissions.csv`**. Core declares the same way at
**`service_backend/app/permissions/permissions.csv`** (core = "module zero", synced by `bootstrap_db`/`seed.py`).

One row per permission, **explicit labels** (no fragile auto-derivation):

```csv
resource,resource_label,action,action_label,description
users,User Management,read,View users,Can view user records
users,User Management,create,Create users,Can add new users
users,User Management,update,Edit users,Can edit existing users
users,User Management,delete,Delete users,Can trash/restore users
orders,Orders & Delivery,approve,Approve orders,Can approve submitted orders
reports,Reports & Analytics,read,View reports,Read-only dashboards
```

Installer, per row → upsert a `permissions` row:
- `key = "<resource>.<action>"`
- `module = <manifest module_name>` (auto-injected at install; core CSV rows belong to module `core`)
- `resource`, `resource_label` → matrix **row** grouping + heading
- `action`, `action_label` → option label in the resource dropdown
- `description` → help text

### 2.4 Implied-read — write implies read, normalized on save  *(Q5 = B, blanket)*
Any granted non-read action on a resource forces `<resource>.read` into the grant set. Enforced as a **storage
guarantee** in `RoleService` on every create/update (so a malformed client payload can't grant write-without-read).
Blanket: **every** action implies read, including custom (`approve` ⇒ `read`). Enforcement (`require_permission`)
stays literal — no inference at check time.

---

## 3. Enforcement

### 3.1 Resolution — per-request from DB  *(Q6 = B)*
JWT keeps `roles[]` only (no permission claim — RBAC edits must take effect immediately, not on token refresh; also
avoids token bloat). `get_current_user` already eager-loads `user.roles` (selectin); add **`selectin` on
`role.permissions`** so effective keys resolve in the same query. Effective key set = **union** of all the user's
roles' permission keys. Cache on request state.

### 3.2 `require_permission(key)` dependency  *(Q16)*
FastAPI dependency factory → resolves effective keys → `403` if missing. **No superuser bypass** *(Q16a)* — Admin
simply holds all keys via seed, so checks pass naturally (one code path, no magic).

### 3.3 Gating — all existing + new endpoints  *(Q16c/Q18)*
Not live yet, so gating everything now is safe (non-admin users don't exist in prod). Map:

| Endpoint | Gate |
|---|---|
| `POST /auth/login`, `POST /auth/signup`, `POST /auth/set-password` | **public** |
| `GET /auth/me` | authenticated, no perm (self) |
| `GET/PATCH /me/preferences/{view_key}` | authenticated, no perm (personal UI state) |
| `GET /users`, `/users/at`, `/users/{id}`, `POST /users/export` | `users.read` |
| `POST /users`, `POST /users/invite` | `users.create` |
| `PATCH /users/{id}`, `POST /users/{id}/reset-password`, `POST /users/{id}/resend-verification` | `users.update` |
| `POST /users/trash`, `POST /users/restore` | `users.delete` |
| `GET /roles` + new CRUD | `roles.read/create/update/delete` |
| `POST/DELETE /roles/{id}/users` (assign/remove) | `roles.update` |
| `GET /permissions` (catalog) | `roles.read` |
| `GET /health` | **public** |

### 3.4 Frontend delivery + gating  *(Q6-fe / Q6a)*
- Login response + `GET /auth/me` return the flattened **effective permission key set**.
- A perms context/provider holds it; `can(key)` hook reads it.
- Resource shell action descriptors gain an optional `permission: string`; shell **hides/disables** the action when
  `!can(perm)`. List "Add" gated by `<resource>.create`; whole route gated by `<resource>.read`.
- **Frontend gating is UX only — backend §3.3 is the security boundary.**

---

## 4. Catalog sync  *(Q15)*

`sync_permissions(csv_rows, module_name)` — **idempotent upsert** keyed by `key`; **deletes** rows for that module no
longer present in the CSV (orphan grants cascade via FK). Ownership tracked by `permissions.module`.

- **Core:** run in `seed.py` → invoked by `bootstrap_db` (core = module zero). Editing the CSV + re-running bootstrap
  re-syncs.
- **Module lifecycle:** App-Store installer calls the same parametrized fn on **install / update** (upsert) and
  **uninstall** (`DELETE WHERE module = X` + cascade grants). Build the fn now (parametrized); installer wiring
  deferred to the App-Store epic (backlog).

---

## 5. Data model / migrations  *(Q7, Q12d, Q14, Q19)*

**One** Alembic migration (`rbac permissions`) bundling:

1. `roles`: add `description` (text, null), `is_system` (bool, default false).
2. `user_roles`: add `assigned_at` (datetime, server_default `now()`).
3. New **`permissions`** table — **global** (no `tenant_id`): `id, key (unique, global), module, resource,
   resource_label, action, action_label, description, created_at`.
4. New **`role_permissions`** M2M: `role_id FK, permission_id FK, tenant_id`, PK(`role_id`,`permission_id`),
   `ondelete=CASCADE` both sides.

**Seed:** Admin role seeded with **all** permission keys; other seed roles **empty** (tune via UI). All seeded roles
marked `is_system = true`.

`is_system` blocks **delete only** *(Q14a)* — name/description/permissions all remain editable.

---

## 6. Roles list  *(Q7)*

Clone the Users list config → `useRolesListConfig()`:
- Columns: **Role** (name), **Description**, **Users** (`userCount`), **Permissions** (`permissionCount`), **Created**.
  - **No icon/color** *(Q7b)* — follow design system.
  - Counts are **computed** server-side (COUNT joins, tenant-scoped) — never stored *(Q7c)*.
- `viewKey="roles"`, `rowHref` → detail, server-side sort/search/paginate via `useResourceList`.
- `searchPlaceholder="Search roles…"`, `createLabel="Add role"`.
- **Export = yes** *(Q7d)* — `exporter` + `exportColumns`.
- No filter chips (search-only).

---

## 7. Role detail form  *(Q8–Q14)*

Reuse `ResourceForm` shell. Header detail level **aligned to the Users form** (not the screenshot) *(Q8d)*.
Record-nav (`fetchAt`/`buildHref`, circular `N/M` in URL) reused from the shell *(Q8c)*.

### 7.1 Create flow — blank full detail page  *(Q8b/Q9)*
Same as Users create (no modal). On create:
- **Settings + Permissions** tabs live.
- **Assigned Users** tab shows a hint — *"Users can be assigned after the role is created."*
- Save: `POST /roles { name, description, permissionKeys: string[] }` → creates role + `role_permissions` in one
  transaction, applies blanket implied-read normalization server-side.

### 7.2 Edit — global Edit toggle, single PATCH  *(Q9c)*
`PATCH /roles/{id} { name?, description?, permissionKeys? }` — `permissionKeys` **replaces** the full grant set (diff
server-side, re-normalize implied-read). Assigned-users mutations go through their own tab actions, **not** the PATCH.

### 7.3 Permissions tab — per-resource dropdowns (NOT a matrix)  *(Q10/Q11)*
- Layout: **module-section header** → **one row per resource** → resource label + an **actions `MultiSelect`** (reuse
  `components/platform/multi-select` — search + select-all + pills).
- Options per dropdown = that resource's actions; option label = `action_label`. Selected = granted.
- **Implied-read locked in UI** *(Q11b)*: selecting any write action auto-selects `read` and disables deselecting it
  while a write is selected; deselecting all writes unlocks `read`.
- **No access** = empty dropdown, clear empty state *(Q11c)*.
- Built from catalog (`GET /permissions`, grouped) for **structure** + role grants for **selection** *(Q10d/Q11d)*.
- Read-only resource (only `read` declared) = single-option dropdown.

### 7.4 Assigned Users tab  *(Q12)*
- List: `GET /roles/{id}/users` — paginated, tenant-scoped, server-side search; returns `id, name, email, avatar,
  status, assignedAt`. Lightweight embedded list (not the full Resource shell).
- **Assign:** "Assign user" → `MultiSelect` of tenant users not already holding the role → `POST /roles/{id}/users
  { userIds: [] }` (multi-assign in one go).
- **Remove:** `✕` per row → `DELETE /roles/{id}/users/{userId}`. Allowed even if it leaves the user role-less *(Q12c)*.
- Symmetric with the Users form (both write `user_roles`) — *see roles from users, see users from role* *(Q12e)*.

### 7.5 Settings tab  *(Q13/Q14)*
- Role **name + description** — read + global Edit toggle (shell convention). No danger zone here.
- **Delete** lives in the top-right `…` action menu *(Q13a)*, not in Settings. Hard delete + warning dialog *(Q13b)*
  ("users assigned will have their role unset; cannot be undone"). Cascades `user_roles` + `role_permissions`. Delete
  action hidden/disabled when `is_system`.

---

## 8. Backend structure  *(Q19c)* — Service-Repository

- `models/permission.py` — `Permission` + `role_permissions` table.
- `repositories/role_repository.py` — role CRUD, counts, assigned-users, grant read/write (tenant-scoped).
- `repositories/permission_repository.py` — catalog read + sync upsert/delete.
- `services/role_service.py` — CRUD, blanket implied-read normalization, `is_system` delete-guard, assign/remove users.
- `services/permission_service.py` — catalog fetch (grouped) + `sync_permissions(csv_rows, module_name)`.
- `schemas/role.py` (extend) — `RoleItem` (w/ counts), `RoleDetail`, `RoleCreate`, `RoleUpdate`, `AssignUsers`;
  `schemas/permission.py` — `PermissionOut`, grouped catalog. All camelCase exposure (`validation_alias` + `from_attributes`).
- `api/v1/roles.py` (extend) — full CRUD + `/{id}/users` sub-resource; `api/v1/permissions.py` — catalog.
- `dependencies.py` — `require_permission(key)` factory + effective-perms resolver (union of roles).

---

## 9. Frontend structure  *(Q20a)* — mirror Users

- `types/role.ts` — extend `Role` (`description`, `isSystem`, `userCount`, `permissionCount`, `createdAt`); catalog
  types (`Permission`, grouped resource/action), `RolePermissionGrant`, create/update inputs. Explicit interfaces (no `any`).
- `services/roles-service.ts` — full CRUD + `assignUsers` / `removeUser` / `getAssignedUsers` / `exportCsv`.
- `services/permissions-service.ts` — catalog fetch + source for `can()`.
- `app/(protected)/user-management/roles/` — `page.tsx`, `[id]/page.tsx`, `components/{use-roles-list-config,
  use-role-form,role-schema,role-form-fields}.tsx` (Permissions / Assigned Users / Settings tabs).
- Perms context/provider + `can(key)` hook fed by login + `/me`.

Layering enforced: UI → hook → service → `lib/api-client` → FastAPI. No component calls `fetch`/axios directly.

---

## 10. Methodology  *(Q20b/Q20c)*

Follow CLAUDE.md mandatory order:
1. **Frontend-first** against a **mock** roles/permissions service behind the service layer — tune loading/error/empty/
   success states for list, matrix-dropdowns, assigned-users. Iterate until UI/UX satisfactory.
2. **Backend** (Service-Repository) — model, migration, sync, endpoints, `require_permission`.
3. **Swap** mock → real `api-client` (one-line change at the service boundary).
4. **TDD** red-green-refactor both layers.

### Tests
- **Vitest:** role-schema validation, implied-read UI lock logic, catalog→per-resource-dropdown mapping, grants→
  selection mapping, `can()` gating.
- **pytest:** role CRUD tenant-scoped, blanket implied-read normalization on save, `is_system` delete-guard,
  `require_permission` 403/200, `sync_permissions` upsert+delete idempotency, effective-keys union over multi-role user.
- **Playwright (real clicks):** create role → set permissions via dropdowns → assign user → verify the assignment from
  the **Users** side → unassign → delete role. Run against mock, then live backend. Produce the Markdown Test Execution
  Report.

### Review & branch
Code-review agent must approve (hard-fail rules: no DB in routers, no component fetch, no `any`, no raw CSS, no module
altering core tables). Branch `sprint-1/roles-permissions` → merge to `main` only after review.

---

## 11. Deferred → backlog
- **BL-013** App-Store installer → `sync_permissions` lifecycle wiring (install/update/uninstall hooks).
- **BL-014** Sidebar / nav-item visibility gated by `can(key)` (route + action gating ships here; menu pruning later).

**Closes BL-009.**

---

## 12. Frontend permission gating — `can()` (built)

§3.4 realized. Backend delivers flattened effective `permissions[]` in the login + `/auth/me`
response; NextAuth carries them into the session (`authorize` → `jwt` → `session`, typed in
`types/next-auth.d.ts`).

- **`useCan()`** (`hooks/use-can.ts`) → `{ can(key), ready, permissions }`, reads the session
  (and the impersonation store, §13). UX only — backend `require_permission` is the boundary.
- **Action gating** — `ResourceAction.permission?` + `ResourceListConfig.createPermission?` +
  `ResourceFormConfig.editPermission?`. The shell (`ActionMenu`, `BulkActions`, `ResourceList`
  Add button, `ResourceForm` Edit toggle) hides/disables when `!can(...)`.
- **Route gating** — `<RequirePermission permission="…">` wraps each list page + form page; on
  lack it renders the friendly **`NoPermission`** page (`components/common/no-permission.tsx`) —
  never a raw 403/technical error.
- Users gates: list `users.read`, Add `users.create`, edit/reset/resend `users.update`,
  trash/restore `users.delete`. Roles gates: list `roles.read`, Add `roles.create`, edit
  `roles.update`, delete `roles.delete`.
- **Deploy note:** sessions issued before `permissions[]` existed lack the field → re-login once.

---

## 13. Impersonation (extension — to test permission gating as another user)

**Goal.** An authorized admin browses the system with a target user's *effective permissions*, to
verify the gating + the NoPermission page from the target's seat. **Security invariant: the
effective user (permissions/view) is the target; the actor (audit / any `created_by`) stays the
real admin — records never get attributed to the impersonated user.** (Pattern mirrors sorento_crm.)

### 13.1 Decisions
1. **Who may impersonate** — new RBAC permission **`users.impersonate`** (custom action; added to
   the core CSV). `/impersonation/start` gated by it. Admin holds all → can.
2. **Valid targets** — not self; not a user who also holds `users.impersonate`; same tenant; target
   must be `ACTIVE`.
3. **Frontend perms while impersonating** — `start` returns the **target's** effective keys;
   stored client-side; `useCan()` uses target keys while a session is active (so the UI gates
   exactly as the target sees it). Backend enforces target perms via the header.
4. **Actor attribution** — `get_actor_user_id(request, current_user)` returns the real admin.
   foundryx has no `created_by` columns yet, so today writes are tenant-scoped only; the helper is
   baked in so any future owned/audit column uses the real admin, never the target.
5. **Banner** — collapsible amber top bar (expand → "Exit impersonation"; collapse → small pill so
   it never blocks controls), Metronic utilities, mounted in the protected layout. One active
   session per admin.

### 13.2 Backend
- **Model** `impersonation_sessions` (`id, admin_user_id, target_user_id, tenant_id, started_at,
  ended_at, started_ip, started_user_agent`); partial-unique active session per admin
  (`ended_at IS NULL`). One Alembic migration.
- **Catalog** — add `users,User Management,impersonate,Impersonate,Impersonate this user` to the
  core CSV (sync picks it up; Admin re-granted all on seed).
- **Dependencies** — `IMPERSONATE_HEADER = "X-Impersonate-User-Id"`; `get_real_user` (JWT → user,
  ignores the header — used by the impersonation endpoints so a session can't end/start its own);
  `_maybe_apply_impersonation(request, db, real_user)` swaps to the target **only** when the real
  user holds `users.impersonate` AND an active session row matches (admin,target); stashes
  `request.state.real_user`. `get_current_user` now applies it and returns the effective user.
  `get_actor_user_id` returns the real admin.
- **Endpoints** (`/impersonation`, `get_real_user`): `POST /start {targetUserId}` (validates rule 2,
  ends any prior active session, returns session + target effective keys), `POST /stop`,
  `GET /current`.

### 13.3 Frontend
- `lib/impersonation-store.ts` — localStorage-backed store (`useSyncExternalStore`) holding
  `{ sessionId, startedAt, targetUser, permissions }`.
- `services/impersonation-service.ts` (start/stop/current) + `hooks/use-impersonation.ts`.
- `lib/api-client.ts` — attaches `X-Impersonate-User-Id` from the store on every request.
- `useCan()` — when a session is active, answers from the store's target keys.
- `components/impersonation/impersonation-banner.tsx` — collapsible amber bar + Exit; mounted in
  `app/(protected)/layout.tsx`.
- Users list action **Impersonate** (`…` menu, `permission: 'users.impersonate'`, confirm dialog) →
  `start` → reload; banner Exit → `stop` → reload.

### 13.4 Tests
- pytest: start requires `users.impersonate` (403 without); can't impersonate self / another
  impersonator / inactive; header honored only with an active row; `get_current_user` returns
  target while `get_actor_user_id` stays admin; stop ends the session.
- vitest: store set/clear; `useCan` prefers impersonation keys when active.
- Playwright (real clicks): admin → Users `…` → Impersonate a limited user → confirm → banner shows
  → navigate to Roles → **NoPermission page** appears → Exit → access restored.
