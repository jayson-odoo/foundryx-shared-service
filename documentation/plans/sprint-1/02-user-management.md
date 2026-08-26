# Sprint 1 · Plan 02 - User Management (List + Form) & the Resource Design Language

**Status:** 🟢 Phase A (frontend prototype) ✅ · Phase B (backend) ✅ · Phase C (review + merge) - review pending. Tests: 33 backend · 16 frontend · 12 E2E, all green ([report](./02-user-management-test-report.md)).
**Branch:** `sprint-1/user-management`
**Route:** `/user-management/users` (list) · `/user-management/users/new` (create) · `/user-management/users/[id]` (form)
**Depends on:** Plan 01 (auth, `public.users`, tenant groundwork).
**Design source:** **No Figma** for this feature (Figma Make output didn't conform to the design system). Build **directly to the Foundryx design system** - tokens (`css/foundryx-tokens.css`, primary orange `#FF5A00`), Poppins/Inter, **Metronic demo1** components - with the two provided screenshots as **layout reference only**. Per-feature divergence from the methodology's "Figma first" step.

---

## 1. Goal

Ship the **User Management** list + form, and in doing so **establish the reusable
"Resource" design language** (list view + form view) that every future entity in the
system replicates. Frontend-first against a mock service, then wire the real
FastAPI Service-Repository, TDD both layers, Playwright real-click E2E, code review.

Two deliverables, deliberately separated:
- **(A) The Resource shell** - platform **core component library** (`components/platform/...`), consumed by everything. NOT an App Store module.
- **(B) User Management** - a **core feature** (operates on core `public.users`, which modules may not alter), the reference implementation proving the shell.

## 2. Architecture decision (the module question)

User Management is **core, not a module**. Governance forbids modules from touching
core `public` tables; `users` is core (auth depends on it). The reusable list/form
shell is **core platform infrastructure**, not a feature module either. Future App
Store modules **consume** the shell (via config + slots) but cannot alter `public.users`.

```
components/platform/resource-list/   <- shell (core lib): ResourceList + toolbar/filter/export/columns
components/platform/resource-form/   <- shell (core lib): ResourceForm + record-nav/tabs/action-bar
components/platform/status-badge/    <- shared uniform status pill
app/(protected)/user-management/users/...   <- core feature (configs + custom cells/tabs)
backend: app/services/user_service.py, role_service.py, ...  (core)
         app/api/v1/users.py, roles.py, me.py                (core)
```

## 3. The Resource design language (system-wide contract)

**Shell model = Hybrid: config + slots.** Opinionated `ResourceList` / `ResourceForm`
driven by a thin per-entity config for the common 80%, with render-prop/slot escape
hatches for custom cells, tabs, and actions. New entity = write a config + a few custom cells.

**System design principles (Phase A review):**
- **Full-width / dynamic to screen size.** List + form fill the viewport (`Container width="fluid"`); content adapts to width, never boxed in a narrow centered column.
- **Growing tag sets fit one row.** Multi-value cells use `OverflowPills` - fits as many pills as the column width allows, rest in a width-aware `+N` popover (recomputes on resize). Row height stays fixed.
- **Pick-many = dropdown + pills.** `MultiSelect` (searchable, **Select all / Clear all**, selected shown as removable pills) everywhere a field/filter picks from a growing list (roles now). No inline chip rows.
- **Required fields = unified `*`** via shell `FormRow`.
- **Fixed columns stay put.** Select (far-left) + actions (far-right) are non-reorderable (`meta.reorderable=false`) and pinned to their slots; only data columns drag-reorder. Order persists per user.
- **Overlays render frontmost.** Popovers are portaled (never clipped by table/scroll containers).

### 3a. List view (every list in the system)
- **Toolbar:** general **Search** (left) · **Filters** · **Export** · **Columns** · **`+ Create`** (primary orange, right).
- **Status segmented control** above rows: `Active | Trashed` (default Active; excludes trashed).
- **Rows:** every row **clickable → form view**. Selection checkbox (pinned left) never navigates.
- **Columns:** **resizable**, **reorderable (DnD)**, **show/hide** - all **remembered per user** (backend-persisted, see §6). `User` column pinned left by default.
- **Per-row `...` menu** = the full entity **action registry** (see §3c).
- **Bulk toolbar** (when rows selected) = multi-capable subset: **Export · Send invitation · Trash**.
- **Status cell** = uniform `StatusBadge` pill (colored), consistent across the whole system.
- **Pagination:** server-side; default **25**, options **10 / 25 / 50 / 100**.

### 3b. Form view (every form in the system)
- **Breadcrumb:** `Home › User Management › Users › {name}`.
- **Identifier header:** avatar (initials) + **name** + email - the key identifier.
- **Top-right cluster:** **record-nav** `[< 1/247 >]` (circular wrap) · **primary button** · **`...` actions**.
- **Tabs (with icons):** entity-specific (User: **Profile · Security · Activity**).
- **Read by default; global Edit toggle:** primary button = `Edit` (read) → flips **all tabs** editable → `Save` (single PATCH) + `Cancel`. Dirty-guard on leave / record-switch.
- **Record-nav context** travels **encoded in the URL** (`?ctx=<b64 query>&i=<index>`): prev/next re-runs the same server query at `index±1` (`LIMIT 1 OFFSET`); refresh/share-safe; nav hidden when ctx absent. `N` = total matching the active filter.

### 3c. Action registry (one set, three surfaces)
One action set per entity, surfaced consistently in: **form top-right** (primary `Edit` + `...` secondary), **per-row `...`**, and **bulk** (multi subset).

| Action | Form | Row | Bulk | Notes |
|---|---|---|---|---|
| Edit | primary | ✓ | - | row Edit opens form in edit mode |
| Send invitation | `...` | ✓ | ✓ | only INVITED-eligible users |
| Reset password | `...` | ✓ | - | single-record |
| Resend verification | `...` | ✓ | - | single-record |
| Trash | `...` (red+confirm) | ✓ | ✓ | soft delete; bulk shows count |
| Restore | (in Trashed view) | ✓ | - | replaces Trash when `is_trashed` |

## 4. Decisions (grill outcomes)

| # | Decision |
|---|----------|
| Module vs core | Shell = core component library; User Management = core feature. Neither is an App Store module; modules later **consume** the shell. |
| Field scope | Screenshots are **layout reference only**. Use real Foundryx fields. List: User(avatar+name+email) · Role · Status · Joined(`created_at`) · Last Sign In. Form tabs: Profile · Security · Activity(stub). |
| Roles | New core **`roles`** table + **`user_roles`** junction - **many-to-many both directions**. Seed Admin, Member. List renders multiple role pills; form Profile multi-select. RBAC/permissions → backlog. |
| Auth contract | **Replace `roleId` with `roles[]`** - JWT + NextAuth session carry `roles:[{id,name}]`. Touches `security.py`, `auth-options.ts`, session/`next-auth` types, login response. `role_id` column dropped. |
| Column prefs | **Backend-persisted** per user: core `user_view_preferences` (`user_id, tenant_id, view_key, prefs JSON`). `GET/PATCH /me/preferences/{view_key}`. Cross-device. Shell passes a `view_key` (e.g. `users.list`). |
| List ops | **Server-side** pagination + sort + filter + search. 25/req, debounced search 300ms. |
| Search | General `ILIKE` across `name` + `email` (AND-combined with active filter). Each list declares searchable fields. |
| Filter | **Full nested AND/OR query builder.** Contract = recursive `{combinator,'and'|'or', rules:[condition|group]}`, condition `{field,op,value}`. Backend recursively → SQLAlchemy on **whitelisted fields only**, with a depth cap. Lists declare filterable fields+types. Saved filters → backlog. |
| Filter fields (users) | name, email, role, status, joined(`created_at`), last_sign_in. |
| Export | If rows selected → those; else **entire current filtered set** (server-side). Column-picker (whitelisted DB cols). **CSV** streamed from `GET /users/export`. XLSX → backlog. |
| Edit model | **Full-page form**, read-by-default + **global Edit toggle** (all tabs, single PATCH, dirty-guard). Create = blank same form at `/new`. This is the standard for rich entities; modals reserved for trivial ones - **diverges from inherited CRUD-as-modals** (update CLAUDE.md). |
| Delete | **Soft trash + restore** (`is_trashed`). List hides trashed by default; `Active\|Trashed` toggle; Trashed view shows Restore. Perma-delete from trash → backlog. **Diverges from inherited hard-delete** (update CLAUDE.md). |
| Actions UI | All secondary/destructive in the **`...` dropdown** (destructive red + confirm). **No Danger Zone card.** |
| Create flow | **Invite email** - admin enters name/email/roles; status `INVITED`; system emails an invite link; user sets own password. |
| Mailer | **`EmailService` abstraction** + **dev adapter logs the link** to console (returns it in dev API). SMTP/provider adapter behind env → prod/backlog. Adds `invite_tokens` (token,user_id,expires) + `INVITED` status + **set-password page** reusing the `(auth)/reset-password` scaffold (`/set-password?token=`). |
| Avatar | **Initials only** (colored, from name); render image if `avatar` URL present. No upload (no blob storage). Upload → backlog. |
| Email | **Read-only after create** (stable login identity). Editable only at create. Change-email flow → backlog. |
| Record-nav context | **URL-encoded** (`?ctx=&i=`), refresh/share-safe, nav hidden when absent. |
| Status pill | Shared `StatusBadge` on Metronic `Badge`, fed by per-entity registry (value→{label,tone}). User: ACTIVE=green · INACTIVE=gray · BLOCKED=red · INVITED=amber. |
| Status editing | Profile select: ACTIVE / INACTIVE / BLOCKED. **INVITED is system-managed** (set by create, cleared on set-password) - shown read-only, not manually selectable. |
| Pagination | Default 25; options 10/25/50/100. |
| Migrations | **Adopt Alembic for core now** (diverges from CLAUDE.md create_all guidance - update it). Baseline existing `tenants`+`users`, then migration: +`roles`,+`user_roles`,+`user_view_preferences`,+`invite_tokens`, **drop `users.role_id`**, `INVITED` status. Use `batch_alter_table` for the `role_id` drop (SQLite-safe, no-op on PG). `bootstrap_db` runs `alembic upgrade head` then seeds (roles Admin/Member; demo user → Admin). |
| Database | **Postgres everywhere - drop SQLite entirely.** Local = native Postgres (no Docker; app runs native `uvicorn --reload` for instant reload). Prod/on-prem = Postgres (Docker for the app there). Dedicated role `foundryx` + db `foundryx_service`, local mirrors prod: `DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service`. `database_url` becomes a required Postgres URL. Forced by module schema-isolation (`CREATE SCHEMA app_*`) which SQLite cannot do. |
| DB bootstrap | **Idempotent auto-bootstrap for zero-touch on-prem deploy.** `scripts/bootstrap_db.py`: connect as admin (`POSTGRES_ADMIN_URL` → `postgres` db) → ensure role `foundryx` exists → ensure db `foundryx_service` exists → connect via `DATABASE_URL` → `alembic upgrade head` → idempotent seed (default tenant, roles, demo user). Same command handles a blank server and an upgrade; re-runnable. On-prem = set admin creds in `.env`, run once. Replaces the old `init_db` create_all + delete-db dev loop. |
| Routing/menu | `/user-management/users[/new|/[id]]`; add `User Management > Users` to Metronic sidebar menu config. |
| Frontend-first | Build shell + user UI against a **mock service** (all states tunable), then swap to real `api-client` at the service boundary (one-line). |
| Tests | Vitest + RTL (component/validation) · `@playwright/test` real-click E2E · pytest + httpx (backend). TDD red-green-refactor. |
| Git | Branch `sprint-1/user-management`; merge to `main` after review. |

## 5. Backend (Service-Repository, tenant-scoped)

### 5a. Schema (Alembic core migration)
- `roles` (`id, tenant_id, name`) - tenant-scoped, unique `(tenant_id, name)`.
- `user_roles` (`user_id, role_id, tenant_id`) - M2M, PK `(user_id, role_id)`.
- `user_view_preferences` (`id, user_id, tenant_id, view_key, prefs JSON`) - unique `(user_id, view_key)`.
- `invite_tokens` (`token, user_id, tenant_id, expires_at, used_at`).
- `users`: **drop `role_id`**; `UserStatus` += `INVITED`.

### 5b. Endpoints (`api/v1`, routers do validation+response only)
- `GET /users` - server-side list: `page,size,sort,q,filter(JSON)`, `status_view=active|trashed`. → `{data, total, page}`.
- `POST /users` - create + invite (status INVITED, issue token, `EmailService.send_invite`).
- `GET /users/{id}` · `PATCH /users/{id}` (single global save).
- `GET /users/{id}/neighbor?ctx=&dir=` *(or)* list `offset` reuse for prev/next.
- `POST /users/{id}/trash` · `POST /users/{id}/restore` · bulk variants.
- `POST /users/{id}/invite` (resend) · `POST /users/{id}/reset-password` · `POST /users/{id}/resend-verification`.
- `GET /users/export?filter=&cols=&ids=` - streamed CSV.
- `GET/PATCH /me/preferences/{view_key}` - column prefs.
- `GET /roles` - for the multi-select.
- `POST /auth/set-password` (token) - public, reuses password policy; clears INVITED → ACTIVE.
- Auth contract: `/auth/login` returns `roles:[{id,name}]`; JWT carries `roles`.

### 5c. Filter translation
Recursive walk of `{combinator, rules}`; only whitelisted `(field→column, type)` allowed;
type-aware operators (text: contains/eq; enum: is/in; date: between/before/after; bool); depth cap.

## 6. Frontend (layering: UI → hook → service → api-client)

- `components/platform/resource-list/` - `ResourceList`, `ListToolbar`, `SearchBar`, `FilterBuilder`, `ExportDialog`, `ColumnsMenu` (wraps existing Metronic `data-grid*`).
- `components/platform/resource-form/` - `ResourceForm`, `RecordNav`, `FormTabs`, `ActionBar`, dirty-guard.
- `components/platform/status-badge/` - `StatusBadge` + registry type.
- `hooks/` - `useResourceList(config)`, `useViewPreferences(view_key)`, `useRecordNav(ctx)`, `useUsers*`.
- `services/` - `user-service` (+ `user-service.mock`), `preferences-service`, `roles-service`.
- `app/(protected)/user-management/users/` - `users.list.config.ts`, `users.form.config.ts`, custom cells (UserCell, RolePills), page wiring.

Reuse existing Metronic primitives: `data-grid`, `data-grid-table` (`columnsResizable`,
`getCanResize`), `data-grid-column-visibility`, `data-grid-pagination`, `sortable` (DnD), `badge`, `tabs`, `breadcrumb`.

## 7. Build order - 3 phases (mirrors plan 01)

**Gate between phases: UI/UX must be approved before any backend work.**

### Phase A - Frontend prototype (mock, no backend)
Goal: nail the Resource design language + user list/form UI/UX against a mock service, all states tunable.
1. Branch `sprint-1/user-management`.
2. Build the **Resource shell** (core lib, to Foundryx design system + Metronic demo1): `ResourceList` + toolbar (Search/Filters/Export/Columns/Create), `FilterBuilder` (AND/OR), `ExportDialog`, `ColumnsMenu`, `Active|Trashed` segmented, `StatusBadge`; `ResourceForm` + `RecordNav` (URL ctx), `FormTabs`, `ActionBar` (Edit toggle + `...`), dirty-guard.
3. **User configs + custom cells** (`users.list.config.ts`, `users.form.config.ts`, UserCell, RolePills) wired to `user-service.mock` (loading/error/empty/success, paginated, filterable). Sidebar menu entry.
4. **Iterate UI/UX until friendly** (the prototype loop - this is the priority).
5. **Vitest + RTL** component/validation tests. **Playwright real-click E2E** against the mock.
6. ✋ **Gate:** UI/UX approved → proceed to B.

### Phase B - Backend (wire real, TDD)
7. **DB switch** - drop SQLite; native Postgres `foundryx`/`foundryx_service`; `database_url` required PG; `scripts/bootstrap_db.py` (idempotent ensure-role/db → upgrade → seed).
8. **Schema + Alembic** - adopt core Alembic, baseline `tenants`+`users`, migration (+roles,+user_roles,+user_view_preferences,+invite_tokens, drop `role_id` via `batch_alter_table`, `INVITED`), seed (roles + demo→Admin).
9. **Auth contract** - `roleId` → `roles[]` (security.py JWT, auth-options, session types, login response).
10. **Service-Repository** - `UserService`/`RoleService` + repos + recursive filter translator (whitelist) + `EmailService` (dev-log adapter) + invite/set-password + prefs (`/me/preferences`) + CSV export endpoint.
11. **Swap mock → api-client** at the service boundary (one-line). **pytest + httpx** TDD. Re-run **Playwright real-click E2E** against the live stack.

### Phase C - Review + merge
12. **Code-review agent** (hard-fail rules: no DB in routers, no fetch in components, no `any`, no raw CSS, no module altering core tables). Fix findings.
13. Test Execution Reports (frontend + backend) per orchestration guide. Merge → `main`.

## 8. CLAUDE.md updates required

- CRUD-as-modals → **full-page Resource form for rich entities** (modals only for trivial).
- Hard-delete-with-confirm → **soft-trash + restore** for users (hard-delete still default elsewhere unless stated).
- Core migrations: **Alembic now adopted for core** (supersedes "no Alembic for core / create_all" note).
- Auth contract: `roleId` → **`roles[]`**.
- **Database = Postgres everywhere; SQLite dropped.** Local = native Postgres (no Docker, app native for instant reload); prod/on-prem = Postgres. Update the Backend command block: `DATABASE_URL` required PG, `python -m scripts.bootstrap_db` replaces `init_db` + the delete-db-and-reinit loop. Note module schema-isolation requires Postgres.

## 9. Backlog spawned

- Prod mailer provider (SMTP/Resend/SES) behind `EmailService`.
- Avatar upload + blob storage.
- Change-email flow + re-verification on email change.
- RBAC / permissions per role.
- Saved filters + OR/group presets UI; XLSX export; permanent delete from trash.
- Keyset pagination if the table ever grows large.
