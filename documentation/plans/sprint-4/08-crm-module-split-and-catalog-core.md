# sprint-4/08 — CRM module split, catalog→core, and CRM UX polish

**Status:** planned + grilled (2026-06-20)
**Re-architects:** `sprint-4/02-ems-cluster-b-crm-catalog-quotation.md` (cluster B was built as one `modules/ems/` blob; this splits it correctly **before merge**).
**Branch base:** `sprint-3/12-ems-cluster-b` (cluster-b worktree; unmerged).
**Grill decisions:** this doc is the source of truth; all branches resolved in the 2026-06-20 grill session.

---

## Why

Cluster B put leads/clients/quotations/products/categories inside `modules/ems/` (`app_ems`). Wrong boundary:
- **EMS = events** (profiles, project types/templates/projects/participants, ticketing). A vertical.
- **CRM = leads/clients/quotations/pipeline.** A different vertical; installs independently of events.
- **Products + Categories = horizontal catalog** → **core** (consumed by CRM quotations, EMS ticketing, future commerce).

Module-platform v2 (sprint-3/10 — deps, capabilities, soft-refs) was built for this. Restructure first; layer UX on the final shape.

---

## Locked decisions (grill 2026-06-20)

| # | Decision |
|---|----------|
| **Kind** | `product.kind` = extensible **registry** (`register_product_kind`), **metadata-only** — core never branches on it (cluster-b only used it as a validation tuple + export lambda). Core registers `good`/`service`; EMS registers `admission`/`add_on`/`merchandise`. On module uninstall its kinds are **hidden** (pickers fall back to core kinds); existing rows keep the raw value, rendered via humanized fallback. |
| **Lead↔project** | **1 lead → many projects, 1 project → 1 lead.** Link of record = **`project.lead_id`** (EMS, nullable soft-ref). **Drop `lead.project_id`.** `project.client_id` denormalized + **lead-independent** (events can be created directly for a client). **Create event is repeatable** (no "only once" gate). |
| **Cross-module (both ways)** | **CRM provides** `lead.resolve@1`, `client.resolve@1`. **EMS provides** `project.create_from_template@1`, `projects.by_lead@1`, `projects.by_client@1`. Cross-module tabs/links **hidden when the other module isn't installed** (capability returns None). |
| **Won vs event** | **Separate.** Win = pure status move Qualified→Won (no side-effect). Create event = separate, repeatable, capability-gated action on Won leads. Lead/client/quotation lists return `availableTransitionIds` (mirror `form_service.fireable_edge_ids`). |
| **Currency** | `tenant_settings.default_currency` (new table) + per-product `currency` **override**. Product price = **advisory prefill** (catalog list price), not a constraint. **1 currency per quotation**, lines inherit; on product/quote currency mismatch → **warn + let user change quotation currency + manually enter unit price** (no FX). Display via `Intl.NumberFormat` (code+symbol). Money columns **Float→Decimal**. |
| **Catalog→core** | `public.products` + `public.product_categories`. Adopt the (unused) core `products.*` perm; add `product_categories.*`; drop module `ems_products.*`/`ems_product_categories.*`. |
| **Product delete** | **Soft-delete only, blocked (409) while referenced** in any quotation (or future module ref) — via a **reference-guard registry** (modules register usage checkers; core stays module-ignorant). Line values are **snapshot-immutable** at add (editing catalog price never touches existing lines). |
| **Tree view-mode** | Reusable `tree` config block on `ResourceListConfig` → separate **`TreeList`** render path (not DataGrid). v1 = **whole-tree fetch** (design a `childrenFetcher` seam for later lazy-load). Client search + **auto-expand** matches. **dnd drag-to-reparent + reorder** (cycle-guard: no drop onto own descendant; persist `parent_id`+`sort` via PATCH) **and** form parent-edit fallback (mobile/a11y). |
| **Migration** | **Destructive reseed** (dev-only, no prod data): drop moved `app_ems` tables, recreate in `app_crm`/`public`, reseed. **Auto-backfill** `crm` ACTIVE + Admin grants for tenants that had CRM rows (App-Store `tenant_has_data` pattern). Richer demo seed (Acme Corp + lead + priced product). |
| **Nav** | **Catalog** = its own top-level **core** section (always visible, perm-gated). **CRM** = own module section (gated `crm` module + `crm_*`). Both **terminology-aware**. Tag every menu array (sidebar/mega/mega-mobile); `filterMenu` prunes. |
| **Quotation→project** | Optional CRM→EMS soft-ref (`quotation.project_id`), kept; resolved on display, ignored if EMS absent. |
| **Merge** | **Two merges:** (1) structural (A+B+C) finishes cluster-b → **main**; (2) UX (D+E) on fresh **`sprint-4/09`** off main. Code-review per slice + a real review before each merge. |

---

## Part A — Module restructure (Merge 1)

### A1. Catalog → core
- **Models** `app/models/catalog.py`: `Product` (← `ProductMaster`), `ProductCategory`. `tenant_id`-scoped; `parent_id` self-FK on category; **soft-delete only** on product (no hard delete path); `currency` nullable override; `kind` = registry key (string, validated against active registry).
- **Kind registry** `app/catalog/kinds.py` (mirrors status/terminology registries): `register_product_kind(key, label, module)`; core seeds `good`/`service`; `active_kinds(db, tenant)` applies `is_visible(module, active)`. Humanized fallback for orphaned keys.
- **Reference-guard registry** `app/module_platform/reference_guards.py`: `register_reference_guard(entity_type, checker(db, tenant, id)->int)`; core catalog delete fans out `product` guards → any >0 ⇒ 409.
- **Currency**: `tenant_settings` table (PK `tenant_id`, `default_currency`, room to grow), `GET/PUT /settings/general` gated `settings.manage`. `lib/money.ts formatMoney(amount, currency)`.
- **Perms**: adopt core `products.*`; add `product_categories.*`. Sweep `tenant_admin_grant`.
- **Router/Service/Repo/Schemas**: `app/api/v1/catalog.py` (`/products`, `/product-categories`), `app/services/`, `app/repositories/`, `app/schemas/catalog.py` (camelCase, `ApiModel`, Decimal money).
- **Migration**: core Alembic — create `public.products`/`public.product_categories`/`tenant_settings`; money as `Numeric`. Drop `app_ems` catalog tables in the ems module migration.

### A2. CRM = new module `modules/crm/` (`app_crm`)
- **Structure (governance):** `modules/crm/{manifest.json, db.py (CrmBase/app_crm), bootstrap.py, models/, services.py, schemas.py, routers/, permissions/permissions.csv, alembic/}`.
- **Manifest:** `module_name: crm`, `version: 1.0.0`, `requires: ["core"]`, `optional: ["ems"]`. Routers `/crm/clients`, `/crm/leads`, `/crm/quotations`.
- **Perms:** `crm_clients.*`, `crm_leads.*`, `crm_quotations.*` (namespaced — grep core first per the name-collision lesson).
- **Models:** `Client`, `Lead` (no `project_id`), `Quotation` (keeps `currency`, optional soft-ref `project_id`), `QuotationLine`. Money = `Numeric`.
- **FKs:** intra-`app_crm` kept; `quotation_lines.product_id → public.products(id)` = real **module→core FK** (governance-sanctioned); `quotation.project_id` = soft-ref (plain col).
- **Capabilities provided:** `lead.resolve@1`, `client.resolve@1` (soft-ref `<entity>.resolve` pattern).
- **Reference guard registered:** `product` → count quotation_lines.
- **Status entities + importers + terminology** for client/lead/quotation re-homed here (`register_engine_entities`); status graphs seeded in `crm` `install_tenant`.
- **Alembic:** per-module baseline (`alembic_version_crm`, `app_crm`).

### A3. EMS slims (`2.0.0`)
- Keeps spine only. Manifest routers trimmed (CRM/catalog removed). Remove client/lead/quotation status-entity + importer + catalog registrations (re-homed). **Provides** `project.create_from_template@1` (← old `convert_lead` body), `projects.by_lead@1`, `projects.by_client@1`. Add nullable soft-ref cols `project.lead_id`/`project.client_id`. Drop `app_ems` CRM+catalog tables (module migration).

### A4. conftest / bootstrap
Wire `crm` like `ems` (schema_translate, `CrmBase.metadata.create_all`, import models, `AppStoreService.install(default, "crm")`). Core catalog via `Base.metadata`. Verify `resolve_install_order`: core → ems/crm.

---

## Part B — Won vs Create event (Merge 1)

- Lead Win edges = plain status moves (no action side-effect). Frontend lead row actions render each fireable outgoing edge by **bare target status name** ("Won", "Lost") driven by `availableTransitionIds`.
- "Create event" = separate action, visible only on **Won** leads **and** only when `project.create_from_template@1` resolves; opens template-pick → capability call (same db session/txn; stamps `project.lead_id`/`client_id`). Repeatable.
- Add `availableTransitionIds` to lead/client/quotation list responses + frontend types.

---

## Part C — Currency (Merge 1)

- `tenant_settings.default_currency` + picker (settings, `settings.manage`).
- `Product.currency` nullable; effective = product.currency ?? tenant default.
- Float→Decimal on `default_price`/`unit_price`/`amount`/`tax`.
- `formatMoney` everywhere money renders (no bare price numbers).
- Quotation currency defaults to tenant default; mismatch UX = warn + change-currency + manual unit price.

---

## Part D — Tree view-mode + categories form (Merge 2)

- `ResourceListConfig.tree` block → `TreeList` component: whole-tree fetch + client build from `parent_id`; expand/collapse (persist per `viewKey`); client search + auto-expand; dnd drag-to-reparent + reorder (cycle-guard, PATCH `parent_id`+`sort`); row "…" actions; segment/perm plumbing. `childrenFetcher` seam reserved for lazy-load.
- Categories on the shell (tree mode) + dedicated `/product-categories/new` + `/[id]` form (name, parent SearchSelect w/ cycle-guard, sort). Delete guards (no children / referenced products → 409) kept.

---

## Part E — CRM UX polish (Merge 2)

1. Lead detail → client **hyperlink** (`/crm/clients/{id}`).
2. Client detail → **Leads** tab + **Quotations** tab (embedded `ResourceList` filtered by clientId) + **Events** tab (EMS `projects.by_client@1`, hidden if EMS absent).
3. Lead detail → **Events** tab (`projects.by_lead@1`, hidden if EMS absent).
4. EMS event detail → **originating lead/client** (resolved via `lead.resolve@1`/`client.resolve@1`, hidden if CRM absent).
5. **Quick-create client** on the dedicated lead **create** form (reuse existing `QuickCreateClientDialog`).
6. **Dedicated create pages, no popups** across CRM + catalog (`/new` Resource forms, users/roles parity).

---

## Guardrails / testing

- Router thin → Service → Repository; tenant-scoped queries; camelCase wire; `UTCDateTime`; `JSON(none_as_null=True)`.
- No module alters core public; catalog→core is the sanctioned module→core FK target.
- No `<style>`/raw CSS; SearchSelect/MultiSelect only dropdowns; ClampedText; responsive 375 + 1280 (tree indent must not overflow mobile; dnd has form fallback).
- **TDD** both layers (catalog CRUD + currency resolution + reference-guard 409 + kind registry; CRM CRUD + status moves + `availableTransitionIds`; capability resolve present/absent → hidden; install-order + crm install/uninstall grants; money Decimal; tree expand/search/reparent).
- **E2E (real clicks):** create Client "Acme Corp" (Active) → create Lead via dedicated create page (quick-create/select client) → lead→client link → client Leads tab shows lead → Qualify → **Won** (explicit) → **Create event** (capability) spawns project, repeatable → event detail shows originating lead/client → categories tree expand/collapse/search/drag-reparent + create via dedicated page → product w/ currency override renders formatted price. Test Execution Report per orchestration guide §6.
- Code-review per slice; real review before each merge.

## Slices

**Merge 1 (cluster-b → main):**
1. Boundaries — scaffold `modules/crm/` + core catalog (models/registries/migrations); deps + conftest; destructive reseed + backfill. Backend green.
2. Cross-module — capabilities both ways; Won/event separation (B); `availableTransitionIds`.
3. Currency (C) — `tenant_settings`, Decimal, formatter, mismatch UX.

**Merge 2 (`sprint-4/09` off main):**
4. Tree view-mode + categories form (D).
5. CRM UX (E). E2E + report.

## Risks / backlog

- Cross-schema FK `app_crm → public.products`: verify alembic ordering (core before module) on Postgres.
- ems `1.1.0→2.0.0` removes routers → old `/ems/clients` etc. 404; frontend repoints to `/crm/*`; backfill installs crm. Document in release note.
- **New BL:** document-drive folder-tree adopts the Resource-shell tree mode.
- Per-line currency / FX / multi-currency totals = finance cluster (sprint-4/07), out of scope.
