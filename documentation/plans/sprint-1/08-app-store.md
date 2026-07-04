# 08 — App Store (per-tenant module lifecycle)

**Sprint:** 1
**Branch:** `sprint-1/app-store`
**Closes:** BL-013 (sync_permissions lifecycle wiring), BL-016 (installer wiring for omnichannel), BL-014 partially (module menu items)
**Depends on:** `sprint-1/07-tenant-core.md` (platform tenant, statuses, provisioning)
**Still open after this plan:** BL-029 (per-module Alembic — schema DDL stays `create_all` here)

---

## 1. Goal

Each tenant gets its own **App Store**: install, update, deactivate (archive — data kept), uninstall (tenant data wiped) modules. Platform operator can perform the same actions from the console (support). The module loader generalizes from hardcoded omnichannel wiring to a manifest-driven contract.

---

## 2. Decision record (from the grill session)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Catalog source + visibility | **Global `modules` table synced from on-disk `manifest.json`** at bootstrap (same pattern as permission CSV sync). Every active tenant sees all `is_listed` modules. Per-tenant entitlements/pricing = BL-036. |
| D2 | Per-tenant install state | **`tenant_modules`** row per (tenant, module): INSTALL → ACTIVE; DEACTIVATE → INACTIVE (data kept, routes 403, perms grants kept-but-inert); REACTIVATE instant; UNINSTALL → wipe the tenant's rows from the module schema, revoke module perm grants from tenant roles, delete row. **Schema/global tables never dropped** — other tenants live there. |
| D3 | Update semantics | **Code is global; per-tenant "update" is a data-provisioning step.** `installed_version` tracks what the tenant was provisioned at; deploy bumps manifest version → "Update available" badge; Update runs `update_tenant(tenant_id, from_version)` (new seeds, backfills, re-grant new perms) and bumps the version. |
| D4 | Version pinning vs chargeable upgrades | **Version gating, not code pinning** (confirmed after grill). One deployment = one code version for everyone. `installed_version` gates feature access: v1.0 tenants don't see/use v1.1 features until they upgrade (the future billing hook attaches here, BL-036). |
| D5 | Migration discipline | **Shared module schema + add-first-delete-later (expand-contract).** Additive changes (new table/column) free within a major. Rename/delete/type-change: add replacement column first, dual-write, drop the old one only when no tenant's active version reads it. True breaking rewrite = new module listing (rare escape hatch). **Binding rule — goes into `EMS_Developer_Governance_Framework.md`; the future certifier rejects violating migrations.** |
| D6 | Store actors | **Tenant admin self-serve + platform operator override.** Tenant-side core perms `app_store.*` seeded to tenant Admin; operator path gated by `tenants.manage_modules` (platform key, plan 07). Same service layer, two entry points. |
| D7 | Frontend freshness | **`GET /app-store/installed` endpoint + NextAuth `update()` after actions** — acting admin's session perms refresh immediately; menu refilters; no stale store. |

---

## 3. Data model

```
modules                                 -- global catalog, synced from manifests
  id            String PK
  name          String UNIQUE           -- manifest module_name
  version       String                  -- current code version (manifest)
  title         String
  description   Text
  icon          String NULL
  is_listed     Boolean default true
  created_at / updated_at

tenant_modules                          -- per-tenant install state
  id                String PK
  tenant_id         String (indexed, FK tenants.id)
  module_id         String (FK modules.id)
  status            String              -- ACTIVE | INACTIVE
  installed_version String              -- what this tenant is provisioned at (gates features)
  installed_at / updated_at
  UNIQUE(tenant_id, module_id)
```

`manifest.json` gains `title`, `description`, `icon` (display fields). Bootstrap scans `modules/*/manifest.json` → upserts `modules` rows (delist removed dirs rather than delete, preserving FK history).

## 4. Module contract (loader generalization)

`app/module_loader.py` stops hardcoding omnichannel. Each module's `bootstrap.py` exports:

```python
install(engine, db)                       # global, idempotent: create schema + tables, sync permissions CSV
install_tenant(db, tenant_id)             # per-tenant seed (statuses, default workspace, ...)
update_tenant(db, tenant_id, from_version)# per-tenant data migration/backfill between provisioned versions
uninstall_tenant(db, tenant_id)           # DELETE the tenant's rows from every app_<module> table
```

- `load_modules(app)`: scan manifests → dynamic-import routers → `app.include_router(..., dependencies=[require_module(name)])`. **Module code untouched; the loader injects the gate.**
- `bootstrap_modules()`: run every module's global `install()` (schema DDL stays idempotent `create_all` — BL-029 unchanged) + sync the `modules` catalog.
- **Backfill migration:** existing tenants already have omnichannel data seeded → bootstrap creates `tenant_modules` rows ACTIVE at the current version for them (platform tenant excluded).
- Omnichannel `bootstrap.py` refactored onto the contract: per-tenant seeding moves from "loop all tenants at install" into `install_tenant`; the blanket Admin re-grant is replaced by per-tenant grant on install (see §5).

## 5. Lifecycle semantics

| Action | Effect |
|--------|--------|
| **Install** | Create `tenant_modules` ACTIVE @ current version → `install_tenant(tenant_id)` → grant the module's permission rows to the tenant's **Admin** role (other roles: admin assigns manually). |
| **Deactivate** | `status=INACTIVE`. Module routes 403 for the tenant (`require_module`), menu items hidden, **all data kept**, perm grants kept-but-inert. |
| **Reactivate** | `status=ACTIVE`. Instant; custom per-role grants restored for free (never removed). |
| **Update** | `update_tenant(tenant_id, from_version)` → re-grant any NEW module perms to Admin → bump `installed_version`. Only offered when `modules.version > installed_version`. |
| **Uninstall** | Typed-confirmation dialog ("type the module name") → `uninstall_tenant(tenant_id)` (wipe tenant rows in `app_<module>` tables) → revoke module perm grants from **all** the tenant's roles → delete the `tenant_modules` row. Irreversible for that tenant's data; schema + other tenants untouched. |

**Admin-grant model change (from sprint-1/03):** seed/`install()` no longer blanket-grants Admin *every* catalog key. Tenant Admin = core keys + keys of modules **installed for that tenant**. (`permissions` catalog stays global; grants become install-aware.) Platform-module keys remain platform-only (plan 07 §5).

## 6. Enforcement

- **`require_module(name)`** (`app/dependencies.py`): per-request lookup — `tenant_modules` ACTIVE for the current user's tenant, else 403 `"Module not installed"`. Same fresh-from-DB philosophy as `require_permission`. Injected by the loader at `include_router` time.
- **Version gating helper** for module code: `module_version(db, tenant_id, name) -> str` + `requires_version(name, ">=1.1")` dependency for endpoints introduced after 1.0 — v1.0 tenants get 403/hidden features until they update. (Omnichannel is all-1.0 today; the helper ships, first real use comes with the first 1.1 feature.)
- **Catalog visibility for tenant role editors:** `GET /permissions` additionally excludes module keys for modules not installed for the caller's tenant (uninstalled modules' perms aren't grantable or visible).

## 7. API

Tenant-side (gated by `app_store.*` core perms, seeded to tenant Admin):

```
GET    /app-store/modules                     catalog (listed modules + this tenant's state + updateAvailable flag)
GET    /app-store/installed                   lightweight active list {module, status, version} (menu gating)
POST   /app-store/modules/{name}/install
POST   /app-store/modules/{name}/deactivate | /reactivate | /update
POST   /app-store/modules/{name}/uninstall    body: {confirmName} must equal module name
```

Operator-side (gated by `tenants.manage_modules`, platform guard):

```
GET    /platform/tenants/{id}/modules         same shape, for any tenant
POST   /platform/tenants/{id}/modules/{name}/install|deactivate|reactivate|update|uninstall
```

Both route sets call one `AppStoreService` (router → service → repository per layering).

New core permission CSV rows (module `core`):

```csv
resource,resource_label,action,action_label,description
app_store,App Store,read,View app store,Can view the tenant app store
app_store,App Store,install,Install modules,Can install and update modules
app_store,App Store,deactivate,Deactivate modules,Can deactivate/reactivate modules
app_store,App Store,uninstall,Uninstall modules,Can uninstall modules and wipe their data
```

## 8. Frontend

- **`/app-store`** (`app/(protected)/app-store/`) — **card grid storefront, not a Resource list**: card = icon, title, description, version, StatusBadge (Not installed / Active / Inactive / Update available) + action buttons per `app_store.*` perms. Deactivate/uninstall behind confirm dialogs (uninstall = typed module name + red copy "wipes all <module> data for this workspace").
- **Console tenant detail → Modules tab** (placeholder from plan 07 becomes real): same cards/actions against the operator endpoints.
- **Menu gating (lands BL-014 for module items):** menu items gain optional `module: "<name>"`; nav filters on the `useInstalledModules()` hook (`GET /app-store/installed`) AND `can(key)`. Omnichannel menu block tagged `module: "omnichannel"`.
- **Freshness:** after any store action → NextAuth `update()` (re-pull `/auth/me` → fresh `permissions[]` in session) + refetch installed list. Other users converge on next request/login; backend 403 is the real boundary.
- Services: `app-store-service.{ts,mock.ts,real.ts}`; hook `use-app-store.ts`; types in `types/app-store.ts`.

---

## 9. Phases (mandatory methodology)

- **Phase A — frontend-first:** types + mock service (all states: not installed/active/inactive/update available), storefront page, confirm dialogs, menu gating, console Modules tab, Vitest tests, Playwright real-click E2E vs mock.
- **Phase B — backend:** TDD: `modules`/`tenant_modules` Alembic migration, manifest sync, loader generalization + omnichannel contract refactor + backfill, `require_module` + version helper, Admin-grant model change, `AppStoreService` + both endpoint sets, perms CSV rows. Tests cover: install seeds + grants; deactivate 403s module routes but keeps data; uninstall wipes ONLY that tenant's rows (two-tenant test) + revokes grants; update bumps version + re-grants. Swap mock→real.
- **Phase C — E2E + report:** full-stack Playwright: tenant admin installs omnichannel → menu appears → deactivates → menu gone + API 403 → reactivates → uninstalls (typed confirm) → data gone for that tenant only. Test Execution Report.

## 10. Deferred → backlog

| New ID | Item |
|--------|------|
| BL-036 | Per-tenant module entitlements + billing (chargeable installs/upgrades; attach to install/update actions + version gating) |
| — | BL-029/BL-030 remain open (per-module Alembic; cross-schema FKs) — this plan keeps `create_all` |

## 11. Governance doc update (part of this plan)

Add to `EMS_Developer_Governance_Framework.md`:
- The module contract hooks (`install` / `install_tenant` / `update_tenant` / `uninstall_tenant`) as a certification requirement.
- The **migration discipline rule (D5)**: within a major version, migrations must be additive; destructive changes only via add-first-delete-later; breaking rewrite = new module listing.
- Manifest display fields (`title`, `description`, `icon`).
