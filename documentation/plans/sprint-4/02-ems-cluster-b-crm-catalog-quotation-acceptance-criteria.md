# Sprint 3 · Plan 12 - EMS Cluster B (CRM → Catalog → Quotation) · User Acceptance Criteria

**Plan:** `02-ems-cluster-b-crm-catalog-quotation.md` (Plan 12) · **Advances:** F4 Cluster B (first commercial vertical on `ems`)
**Design record:** `01-ems-commercial-domain-grill-decisions.md` (grilled 2026-06-18).
**Built in 3 slices:** ① CRM (Clients + Leads) → ② Product catalog (categories tree + master) → ③ Quotations.
Order is dependency-driven: client/lead referenced by quotation; products referenced by lines.

Format: **Given / When / Then**, traced to a locked decision (Dn, the plan's §"Locked design
decisions" 1-7) + pillars 🟢📈🧭✅. MET = named test green (UI at 375/1280 where it renders).

---

## 1. Functional commercial vertical - works end-to-end 🟢

- **AC-12-01 (demo) Full Cluster B net-demo passes.**
  *Given* a tenant with `ems` installed, *when* the operator creates Client "Acme Corp" (Active),
  logs Lead "Acme annual conference" (inline quick-creating the Client from the lead form), moves it
  New→Qualified→**Won** (Won spawns a Project from a chosen template, back-linking lead↔client↔project),
  builds a Product catalog (category tree Tickets ▸ Conference ▸ VIP; masters with `kind`), raises a
  Quotation against the Acme lead (lines referencing SERVICE products + free-form, derived total),
  attaches a PDF from Drive, revises it (clone + lineage), and moves it Draft→Sent→Accepted, *then*
  every step succeeds and the relabel "Client"→"Account" via Terminology propagates to every surface.

- **AC-12-02 (D1) Client = B2B account, separate from Profile.**
  *Given* `/ems/clients`, *then* it is a Resource list/form (`clients` table: name req, registration_no,
  contact person/email/phone), status-engine driven (Active→Inactive→Archived with reactivate/restore
  edges), soft-delete + Trash. Client is NOT a Profile and NOT a `public.users` row. Lead→Client is M:1.

- **AC-12-03 (D2) Lead = inquiry/opportunity with nullable client.**
  *Given* `/ems/leads`, *then* `leads.client_id` is **nullable** (a raw inquiry can exist pre-Client),
  status-engine driven (New→Contacted→Qualified→Won/Lost), Resource list/form (title req, source,
  contact name/email/phone, notes), soft-delete.

- **AC-12-04 (D2/D7) Won spawns + back-links a Project.**
  *Given* a Lead at any pre-Won stage, *when* the graph-driven **Won** edge fires (surfaced as a
  "Create event" action), *then* the operator picks a template, a workflow spawns a Project from it,
  and `lead.project_id` + `project.client_id` + `project.lead_id` are all set (the spine's reserved
  cols populated). The workflow is loop-safe.

- **AC-12-05 (D3) Product master + category tree.**
  *Given* the catalog, *then* `product_categories` is a self-referencing tree used for taxonomy/reporting
  **only** (code never branches on category), and `product_master` carries a behavioral `kind` enum
  {ADMISSION, ADD_ON, SERVICE, MERCHANDISE} that code DOES branch on, plus sku/default_price/tax/uom and
  an `is_active` flag (NOT the status engine). Category tree supports add/rename/reparent/delete; delete
  is guarded (no children + no products).

- **AC-12-06 (D4) Quotation against a Project, raised at Lead stage.**
  *Given* `/ems/quotations`, *then* a quotation carries `client_id`, nullable `lead_id`, nullable
  `project_id` (**≥1 of lead/project set**), `currency`, notes, status-engine driven
  (Draft→Sent→Accepted/Rejected→Expired), with `quotation_lines` (nullable `product_id` → master /
  free-form description, qty × unit_price → derived amount) and a header total derived from lines.

- **AC-12-07 (D4) Revise = new row with lineage, not an edge.**
  *Given* a quotation, *when* the operator **revises** it, *then* `POST /{id}/revise` clones the
  quotation + its lines into a new row with `parent_quotation_id` set and `revision_number+1` (a
  revision badge shows the lineage); revise is NOT a status transition.

- **AC-12-08 (D5) Document attach via Drive FileLink.**
  *Given* a quotation form, *when* the operator attaches a Drive file, *then* a `FileLink`
  (`entity_type='quotation'`, `entity_id`) is created via the NEW core `/documents/links` API
  (`POST` link · `GET ?entityType=&entityId=` list · `DELETE /{id}` unlink), polymorphic save-validated
  and tenant-scoped on resolve. Quotation is the first consumer of the seam.

## 2. Scalable architecture / multi-tenant 📈

- **AC-12-09 (D6) Pure engine registration - no new engine code.**
  *Given* the Cluster B entities, *then* each registers into existing engines via
  `register_engine_entities`: status entities (client/lead/quotation graphs), workflow triggerable
  (`client`/`lead`/`quotation` → created/updated/status_changed + the Won→create-Project handler), rule
  fact sources (lead source/status, client), importer configs (client/lead/product), terminology labels.
  No engine internals change.

- **AC-12-10 (house) New tables in `app_ems` via per-module Alembic; cross-schema rule honored.**
  *Given* the migration, *then* clients/leads/product_categories/product_master/quotations/quotation_lines
  land in `app_ems` via the next per-module Alembic revision after `0001_ems_baseline`; `status_id`,
  `tenant_id` and core refs stay **plain indexed columns, NOT DB FKs** (BL-030); intra-`app_ems` FKs
  (client/lead/category/product/quotation) are kept.

- **AC-12-11 (house) Every query tenant-scoped, Service-Repository layered.**
  *Given* any `/ems/*` or `/documents/links` endpoint, *then* repositories are tenant-scoped, no DB/raw
  SQL in routers, schemas are camelCase `ApiModel`, business logic in services.

- **AC-12-12 (D6) Importable + id-first export round-trip.**
  *Given* clients, leads, and products, *then* each exposes an `ImporterDef` + `ResourceListConfig.importer`,
  export includes the id column first, and export → edit → re-import(update) round-trips. The new module
  perms (clients/leads/product_categories/products/quotations × read/manage) are granted to tenant Admin
  on install.

- **AC-12-13 (D5) FileLink seam is polymorphic + tenant-safe by construction.**
  *Given* the `/documents/links` API, *then* a link's (`entity_type`,`entity_id`) is save-validated to
  belong to the caller's tenant, resolved tenant-scoped at use time (the FileLink discipline /
  polymorphic-target_id rule), and a cross-tenant or orphaned reference resolves to none, never a leak.

## 3. Guided UX 🧭

- **AC-12-14 (D7) Inline quick-create Client from the Lead form.**
  *Given* the Lead form's Client field (a `SearchSelect`), *when* the desired client is absent, *then* a
  "+ New" action opens a create-dialog, creates the Client, and re-selects it inline - no navigation
  away from the lead.

- **AC-12-15 (D7) Won is a graph-driven action, not a hardcoded button.**
  *Given* a Lead, *then* the convert action surfaces from the status graph's Won edge (mirrors the
  tenant-console graph-driven action pattern); the button label is the bare target status name (house
  mandate - no "Move to" prefix).

- **AC-12-16 Quotation line-item editor reuses RepeaterField.**
  *Given* the quotation form, *then* lines are edited via `RepeaterField`: a product `SearchSelect`
  (→ master) or free-form description, qty × unit_price → derived amount per line + a derived header total.

- **AC-12-17 Category tree editor reuses the Drive tree pattern.**
  *Given* the catalog, *then* the category tree is edited via the Drive `FolderTree`/`tree.tsx` pattern
  (no dnd v1 - add/rename/reparent/delete), not a hand-rolled tree.

- **AC-12-18 (D6/F10) Terminology relabel follows everywhere.**
  *Given* seeded labels (Client/Account, Lead, Product, Category, Quotation), *when* a tenant relabels
  "Client"→"Account", *then* every surface (lists, menus, breadcrumbs, buttons, search) follows via plan-08.

- **AC-12-19 (house) Every dropdown searchable; reuse over rebuild.**
  *Given* every picker on these surfaces (client, lead, product, category, template), *then* it is a
  `SearchSelect`/`MultiSelect`; lists/forms clone the Resource shell (`ems/profiles`/`ems/events`), and
  no parallel components are built where an existing one extends.

- **AC-12-20 (house mandate) Responsive** at 375px and 1280px across all Cluster B lists, forms, the
  quotation line editor, the category tree editor, the attach panel, and the inline quick-create dialog.

## 4. Validated quality ✅

- **AC-12-21 Backend tests green** (per slice): client/lead/product/quotation CRUD + tenant isolation ·
  lead Won spawns + links a Project (workflow, loop-safe) · quotation revise clones with lineage + copies
  lines · line-amount + header-total derivation · product `kind` behavior · category tree delete guards
  (children/products) · import round-trip (client/lead/product) · FileLink polymorphic save-validate +
  tenant-scoped resolve · new-perm grant on install · the pre-existing status-engine suite stays green.

- **AC-12-22 Frontend tests green** (per slice): Resource list/form configs, line-item repeater derivation,
  category tree ops, inline quick-create, attach panel states (loading/empty/error/success).

- **AC-12-23 E2E green** (real clicks, both viewports, dedicated tenant): the net-demo journey - create
  client → lead → inline quick-create client → Won→create event → catalog → quotation + lines + attach +
  revise → transitions → Terminology relabel. Per-slice test-report filed.

- **AC-12-24 (governance) Module governance honored:** new module perms in the EMS permissions CSV (grep
  core first - no collisions: core owns `templates`/`emails`/`forms`/`workflows`, not these), granted to
  tenant Admin on `install_tenant`; no core-table alteration; no cross-schema FK into another module. The
  one new core surface (`/documents/links`) rides existing `documents.*` or a new `attachments.*` perm
  (confirmed in Phase B).

- **AC-12-25 Code review approved** per slice before merge to `main`.

---

## Delivery note (2026-06-18)
**All AC-12-* MET** across the 3 slices on branch `sprint-3/12-ems-cluster-b` (worktree, served
:3003/:8003). Per-slice phasing held: frontend UI/UX live-verified (Playwright, desktop + mobile
375px) → backend (Service-Repository, tenant-scoped) → TDD → E2E real-clicks → independent code
review with all blockers/majors/actionable-minors fixed.
- **Backend:** full suite **845 passed** (0 regressions). New: `test_ems_cluster_b.py` (12),
  `test_ems_catalog.py` (10), `test_ems_quotations.py` (9). Per-module Alembic 0002-0004.
- **Frontend:** eslint clean across `app/(protected)/ems`. E2E `e2e/ems-cluster-b.spec.ts` (6 specs).
- **Net demo verified:** Client → Lead (inline quick-create Client) → Won→Create-event (links +
  scoped graph copy) → category tree + product catalog → Quotation + lines + derived total + revise
  + document attach (Drive FileLink seam) → status transitions.
- **Notable:** core already owns `products.*` → product perms namespaced **`ems_products.*`** (the
  plan's "no collision" note missed this). The **FileLink API already existed**
  (`/documents/file-links`, ShareService, tenant-scoped) - **consumed, not rebuilt**. See test report.
- **Pending (operator action):** merge `sprint-3/12-ems-cluster-b` → `main` after final review (held
  back - two other developers are active on the shared checkout).

## Definition of Done (plan 12 / Cluster B)
All AC-12-* MET across the 3 slices · suites green (incl. unchanged status-engine suite) · E2E reports
filed per slice · reviewer approved · merged to `main`. Cluster B is the first commercial vertical
(Lead→Client→Project→Quotation) and reserves the forward contract for clusters D/E/F (Tickets, Review,
Invoice/Payment/Settlement) - designed-for, not built here.

## Out-of-scope guard (NOT acceptance criteria for this plan)
Offerings/capacity_units/Tickets/nomination (Cluster D) · Invoice/Payment/gateway/Settlement (Cluster F) ·
Review (Cluster E) · Agenda/Checkpoint (G/H) · Venue/Seating designer · Quotation **PDF render** (F2
binding, lands with Invoice/F2) · multi-client per project · inline-quick-create generalization · category
dnd reorder · quotation approval workflow templates. Each gets its own grill+plan at pickup.

## New backlog candidates to log (from the plan)
- BL-1xx **FileLink entity-attach API** generalized (any entity) + reusable `<EntityAttachments>` panel.
- BL-1xx **Inline quick-create** reusable primitive (SearchSelect create-new mode).
- BL-1xx **Lead→Project convert** picks/clones tasks/checklist (deferred from plan 11).
