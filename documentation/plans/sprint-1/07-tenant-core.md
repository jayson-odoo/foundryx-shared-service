# 07 - Tenant Core & Platform Console

**Sprint:** 1
**Branch:** `sprint-1/tenant-core`
**Closes:** BL-004 (multi-tenancy groundwork → real model; public self-signup spun out to BL-032), BL-015 (association `tenant_id`)
**Depends on:** sprint-1/03 (RBAC), sprint-1/02 (Resource shell)
**Successor:** `sprint-1/08-app-store.md` (per-tenant module install) - depends on this plan.

---

## 1. Goal

Turn the single-tenant groundwork into a real multi-tenant SaaS core:

- A **platform operator** concept (reserved platform tenant + platform RBAC) able to administer tenants.
- **Tenant lifecycle** (active / suspended / archived) on a new **core `statuses` foundation**.
- **Tenant resolution by subdomain slug** at login (BL-004's open question, resolved).
- **Tenant provisioning service** - operator creates a tenant; tenant gets seeded roles + a first admin user.
- A **Platform Console UI** (`/platform/tenants`) on the Resource shell.
- Fix **BL-015** (association `tenant_id` written explicitly) - mandatory before tenant #2 exists.

Out of scope (deferred, see §10): public self-signup, invite emails, custom domains, tenant hard-delete/GDPR purge, billing.

---

## 2. Decision record (from the grill session)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Where does the platform-operator concept live? | **Reserved platform tenant** (`is_platform=true`, slug `platform`), seeded at bootstrap. No god-flag on users; no separate admin app. |
| D2 | How are platform endpoints gated? | **Permission keys + tenant guard**: `require_platform_permission(key)` = `require_permission(key)` AND `user.tenant_id == platform tenant`. Double lock - a tenant role holding the key is still blocked. |
| D3 | Tenant creation scope | **Operator-created only** this plan. Provisioning service built so self-signup (BL-032) later just calls it. |
| D4 | Tenant resolution at login | **Subdomain slug** (`acme.foundryxems.com`). Frontend derives slug from hostname → sends in login payload (+ `X-Tenant-Slug` header on all API calls, defense-in-depth). Dev fallback `NEXT_PUBLIC_TENANT_SLUG` → `default`. |
| D5 | Tenant lifecycle states | **Hybrid status foundation**: new core `statuses` table; tenant lifecycle = 3 system rows (active/suspended/archived). Code branches on fixed `category`, labels/colors editable (operator only). Full configurable engine stays BL-027. |
| D6 | First admin credentials | **Operator-set temp password**, handed out-of-band. Invite-email flow = BL-033 (the `EmailService` console adapter from sprint-1/02 can be reused as a fast-follow). |
| D7 | Console placement | **Same app**: `/platform/tenants` route group, "Platform" menu section visible only to platform-tenant users with `tenants.read`. Resource shell clone (Users = reference). |

---

## 3. Core `statuses` foundation (D5)

New `public.statuses` table - the seed of the future status engine (BL-027), deliberately thin here:

```
statuses
  id            String PK
  entity_type   String  (indexed)   -- "tenant" now; modules/core entities adopt later
  key           String              -- machine key, e.g. "active"
  category      String              -- FIXED machine semantic; code branches ONLY on this
  label         String              -- display, editable
  color         String              -- display, editable
  sort_order    Int
  is_system     Boolean             -- system rows: key/category immutable, non-deletable
  tenant_id     String NULL         -- NULL = platform-owned (tenant lifecycle rows are NULL)
  UNIQUE(entity_type, tenant_id, key)
```

Seeded rows (`entity_type="tenant"`, `tenant_id=NULL`, `is_system=true`):

| key | category | label | color |
|-----|----------|-------|-------|
| `active` | `active` | Active | green |
| `suspended` | `suspended` | Suspended | amber |
| `archived` | `archived` | Archived | gray |

Rules:
- **Behavior binds to `category`, never to `label`** - labels are cosmetic and editable by the operator.
- Tenants do **not** configure tenant-lifecycle statuses (platform-scoped, `tenant_id NULL`).
- Migrating omnichannel's per-tenant `statuses` onto this table + a status management UI = follow-up (BL-027 / BL-037).

## 4. Tenant model changes

`tenants` gains:

```
status_id       String FK → statuses.id   (replaces is_active; migration maps is_active→active/archived)
custom_domain   String NULL UNIQUE        (schema-ready; CNAME/infra wiring = BL-034)
contact_name    String NULL
contact_email   String NULL
notes           Text NULL
is_platform     Boolean default false     (exactly one seeded row true)
```

Slug rules:
- lowercase kebab, `^[a-z0-9](-?[a-z0-9])*$`, 3-63 chars.
- **Immutable after creation** (it is the tenant's URL).
- **Reserved list** (rejected at create): `www, api, app, admin, platform, default, mail, ftp, assets, static, docs, status, support, billing`.

Lifecycle semantics:

| Status (category) | Login | Existing sessions | Operator list |
|---|---|---|---|
| `active` | ✅ | ✅ | shown |
| `suspended` | ❌ 403 "This workspace is suspended. Contact support." | ❌ - `get_current_user` re-checks tenant status per request, kills live sessions | shown |
| `archived` | ❌ same as suspended | ❌ | hidden by default (filterable), data intact |

Hard data wipe is **not** a status - it's a future explicit operator action (BL-035).

## 5. Platform tenant + platform RBAC (D1, D2)

- Bootstrap seeds: platform tenant (`slug=platform`, `is_platform=true`, fixed `PLATFORM_TENANT_ID` constant) + **Platform Admin** role + platform admin user (`platform@example.com` / seeded password - change in prod).
- New permission CSV rows declared under **module `platform`** (separate CSV at `app/permissions/platform_permissions.csv`, synced at bootstrap like core):

```csv
resource,resource_label,action,action_label,description
tenants,Tenant Management,read,View tenants,Can view tenant records
tenants,Tenant Management,create,Create tenants,Can provision new tenants
tenants,Tenant Management,update,Edit tenants,Can edit tenant details
tenants,Tenant Management,suspend,Suspend tenants,Can suspend/reactivate tenants
tenants,Tenant Management,archive,Archive tenants,Can archive tenants
tenants,Tenant Management,manage_modules,Manage tenant modules,Can operate a tenant's app store (plan 08)
```

- **`require_platform_permission(key)`** in `app/dependencies.py`: resolves `require_permission(key)` **and** asserts `user.tenant_id == PLATFORM_TENANT_ID`. All `/platform/*` endpoints use it.
- **Catalog leak prevention:** `GET /permissions` excludes `module='platform'` rows unless the caller is in the platform tenant - tenant role editors never see (or grant) platform keys.
- Platform tenant is special: it has no app store (plan 08 hides it), is excluded from "tenant" business flows, and cannot be suspended/archived (service guard).

## 6. Tenant resolution at login (D4)

- **Frontend:** `lib/tenant.ts` derives slug from `window.location.hostname` (first label of `*.foundryxems.com`-style hosts); fallback chain → `NEXT_PUBLIC_TENANT_SLUG` env → `"default"`. NextAuth `authorize()` includes `tenantSlug` in the login POST; `lib/api-client.ts` attaches `X-Tenant-Slug` on every request (defense-in-depth - backend may cross-check vs JWT claim, JWT remains source of truth post-login).
- **Backend:** `POST /auth/login {email, password, tenantSlug?}` → resolve slug→tenant (missing slug = `default`, preserving current behavior); unknown slug or non-active tenant → uniform 403 path; auth proceeds tenant-scoped exactly as today. JWT `tenant_id` claim unchanged.
- `get_current_user` additionally loads the tenant and rejects when its status category ≠ `active` (suspension takes effect on next request).
- Local dev / tests keep working with zero config (default fallback). Wildcard DNS + per-tenant subdomains = infra-level, runbook note only.

## 7. Provisioning service (D3, D6)

`TenantProvisioningService.provision(name, slug, contact, admin_email, admin_name, temp_password)` - **one transaction**:

1. Validate slug (format, reserved list, uniqueness) → create tenant (status `active`).
2. Seed the standard system roles for the tenant (same set/factory the default tenant gets - extracted from `seed.py` into a reusable `seed_tenant_roles(db, tenant_id)`).
3. Grant tenant Admin role the **core** permission set (module perms arrive via app-store install, plan 08).
4. Create first admin user (ACTIVE, Admin role, bcrypt temp password).

Failure anywhere = full rollback (no half-provisioned tenants). Self-signup (BL-032) will call this same service.

## 8. BL-015 fix (mandatory)

`user_roles.tenant_id` / `role_permissions.tenant_id` currently written via column default (`DEFAULT_TENANT_ID`) - wrong the moment tenant #2 exists. Fix: set explicitly on assignment (association object or `before_insert` listener sourcing the owning row's tenant), plus a one-off data migration correcting existing rows. Add regression test: assign role in non-default tenant → association row carries that tenant.

## 9. API & Frontend

### Backend endpoints (all `require_platform_permission`)

```
GET    /platform/tenants            paginated list (Resource list contract: sort/filter/search/export)
POST   /platform/tenants            provision (→ §7)
GET    /platform/tenants/{id}       detail
PATCH  /platform/tenants/{id}       update editable fields (name, contact, notes, custom_domain)
POST   /platform/tenants/{id}/suspend | /reactivate | /archive
GET    /platform/tenants/at         (record-nav ctx, mirrors /roles/at)
```

Schemas camelCase via `validation_alias`; filter via the entity-agnostic `translate_filter` with a tenants column map; statuses joined for badge rendering.

### Frontend

- `app/(protected)/platform/tenants/` - list + detail form, **Resource shell clone** (Users = reference): `useTenantListConfig()`, `useTenantForm()`.
  - List columns: Name, Slug, Status (StatusBadge), Contact, Created. Archived hidden by default (status filter).
  - Form tabs: **Details** (name, slug read-only, contact, notes, custom domain) · **Modules** (placeholder panel - "App Store lands in plan 08") · actions: Suspend/Reactivate/Archive via action registry with confirm dialogs.
  - Create dialog/page collects tenant fields + first-admin fields (email, name, temp password).
- "Platform" menu section in `menu.config.tsx`, rendered only when `session.user.tenantId === platform tenant` AND `can("tenants.read")` (needs `isPlatform` or platform-tenant id exposed via login response/`/auth/me` - add `isPlatformTenant: boolean` to the session user).
- Services: `tenant-admin-service.{ts,mock.ts,real.ts}` behind the service-layer mock/real swap.
- Suspended-tenant UX: login shows the suspension message (distinct from invalid-credentials).

---

## 10. Phases (mandatory methodology)

- **Phase A - frontend-first:** statuses/tenant types, tenant-admin mock service, Platform console list/form/create/suspend flows, menu gating, Vitest component tests, Playwright real-click E2E against mock.
- **Phase B - backend:** TDD (pytest+httpx): statuses table+seed, tenant model migration (Alembic), platform tenant/role/user seed, platform CSV sync, `require_platform_permission`, login slug resolution + status enforcement, provisioning service, BL-015 fix, endpoints. Swap mock→real at the service boundary.
- **Phase C - E2E + report:** full stack Playwright (operator logs in → creates tenant → suspends → suspended tenant's user blocked at login → reactivate), Test Execution Report per orchestration guide §6.

## 11. Deferred → backlog

| New ID | Item |
|--------|------|
| BL-032 | Public tenant self-signup (calls `TenantProvisioningService`; needs email verification, abuse protection, slug-collision UX) |
| BL-033 | First-admin invite email + force-password-change-on-first-login (reuse `EmailService`; pairs BL-006) |
| BL-034 | Custom domain support (CNAME verification, infra routing; column ships now) |
| BL-035 | Tenant hard-delete / GDPR purge (per-module purge hooks; operator action with typed confirm) |
| BL-037 | Status engine management UI + migrate omnichannel per-tenant statuses onto core `statuses` (pairs BL-027) |
