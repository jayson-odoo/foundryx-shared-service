# Sprint 3 · Plan 12 - EMS Cluster B (CRM → Catalog → Quotation), the first commercial vertical

**Branch:** `sprint-3/12-ems-cluster-b`
**Advances:** F4 Cluster B (roadmap `sprint-3/00` §4). The first **commercial** vertical on the `ems` module. Design record: **`12-ems-commercial-domain-grill-decisions.md`** (grilled 2026-06-18) - the full B-H relational skeleton; this plan **builds the Cluster B subset only**.
**Builds on:** the live `ems` module (plan 11 - Profile / ProjectType / ProjectTemplate / Project / ProjectParticipant, `app_ems` schema, per-module Alembic, engine registries).
**Depends on:** Resource shell, status engine (+ `register_engine_entities` adoption pattern), workflow engine (Won→create-Project), Import engine (F8 - clients/leads/products importable), Terminology (F10), Drive **`FileLink`** polymorphic seam (F3 - exists, **no API yet**; this plan builds it), product-master + category seam.
**Spawns (forward contract, later clusters):** Offerings + `capacity_units` + Tickets + nomination (**D**) · unified Invoice + Payment + gateway provider + Settlement/give-back (**F**) · Review (**E**) · Agenda/Checkpoint (**G/H**) · Venue/Seating layout designer + stadium import (**Venue plan**). All modeled in the decisions doc; **not built here**.

---

## Context

The `ems` spine (plan 11) gives identity (Profile), the Type→Template→Project hierarchy, and the participant registration join. It is **attendee-side only** - `project.client_id` is a reserved-nullable column with no Client behind it. Cluster B builds the **commercial/buyer side** end-to-end: the B2B account (Client), the sales opportunity (Lead), the reusable Product **master + category tree**, and the **Quotation** (revisions, line items, document attach) - the first revenue stream (B2B service: Lead→Client→Project→Quotation→Invoice).

This is **mostly wiring**: domain entities + Resource shell + engine registration, exactly what the platform was built to make cheap. No new engine. The one genuinely new build surface is the **FileLink API** (Drive's deferred polymorphic attach seam) - first consumed by quotation documents.

**Net demo at end of plan 12:** on a tenant with `ems` installed - create a **Client** "Acme Corp" (status Active); log a **Lead** "Acme annual conference" (inline quick-create the Client from the lead form), move it New→Qualified→**Won** → the Won action **spawns a Project** (pick a template) and back-links lead↔client↔project; build a **Product catalog** (category tree: Tickets ▸ Conference ▸ VIP; master products with `kind`); raise a **Quotation** against the Acme lead (lines referencing SERVICE products + free-form, derived total), **attach a PDF** from Drive, **revise** it (clone + lineage), move Draft→Sent→Accepted; relabel "Client"→"Account" via Terminology and every surface follows. All importable (clients/leads/products), id-first export round-trip.

---

## Locked design decisions (from the decisions doc; recap of what this plan implements)

1. **Client = new B2B entity, separate from Profile.** `clients` table; status-engine entity (Active→Inactive→Archived). Lead→Client M:1.
2. **Lead = inquiry/opportunity**, `client_id` **nullable** (raw inquiry pre-client). Status-engine (New→Contacted→Qualified→Won→Lost). **Won → workflow spawns a Project** (links `project.lead_id`, `project.client_id`).
3. **Product master + category tree.** `product_categories` self-referencing tree (taxonomy/reporting **only**). `product_master` tenant catalog with **behavioral `kind` enum** {ADMISSION, ADD_ON, SERVICE, MERCHANDISE} - code branches on `kind`, never on category. `is_active` (no status engine).
4. **Quotation against a Project, raised at Lead stage.** `quotations` (`client_id`, `lead_id` nullable, `project_id` **nullable** - at least one of lead/project set; links on win), `revision_number` + `parent_quotation_id` lineage, status-engine (Draft→Sent→Accepted→Rejected→Expired). `quotation_lines` (product_id nullable → master / free-form, qty×unit_price, derived total).
5. **Document attach = Drive `FileLink`** (`entity_type='quotation'`, `entity_id`) - build the link CRUD API + attach UI (first consumer of the seam).
6. **Engine registration is the work:** status entities (client/lead/quotation), workflow triggerable (`client`/`lead`/`quotation` → created/updated/status_changed; Won→create-Project handler), rule fact sources (lead source/status, client), importer configs (client/lead/product), terminology labels. No new engine code.
7. **Inline quick-create** Client from the Lead form (new small reuse pattern - see §Reuse). **Convert action** = graph-driven Won edge surfaces a "Create event" action (mirrors the tenant-console graph-driven action pattern).

---

## Data model (`app_ems` schema additions)

```
clients                                                     # B2B buyer account
  id, tenant_id, name (req), registration_no, contact_person, contact_email, contact_phone
  status_id FK statuses                                     # status engine (Active/Inactive/Archived)
  is_deleted, deleted_at/by, created_at, updated_at

leads                                                       # inquiry / opportunity
  id, tenant_id, client_id (NULLABLE) FK clients
  title (req), source, contact_name, contact_email, contact_phone, notes
  status_id FK statuses                                     # status engine (New→Contacted→Qualified→Won→Lost)
  project_id (NULLABLE) FK projects                         # set when Won spawns/links a Project
  is_deleted, created_at, updated_at

product_categories                                          # self-referencing tree (taxonomy only)
  id, tenant_id, parent_id (NULLABLE, self-FK), name, sort
  is_deleted, created_at, updated_at

product_master                                              # tenant catalog
  id, tenant_id, category_id (NULLABLE) FK product_categories
  name (req), sku, kind ENUM(ADMISSION|ADD_ON|SERVICE|MERCHANDISE), default_price, tax, uom
  is_active, is_deleted, created_at, updated_at

quotations                                                  # B2B service quote
  id, tenant_id, client_id FK clients
  lead_id (NULLABLE) FK leads, project_id (NULLABLE) FK projects   # ≥1 of lead/project set
  revision_number (int, default 1), parent_quotation_id (NULLABLE, self-FK)
  currency, notes
  status_id FK statuses                                     # status engine (Draft→Sent→Accepted→Rejected→Expired)
  is_deleted, created_at, updated_at

quotation_lines
  id, tenant_id, quotation_id FK quotations
  product_id (NULLABLE) FK product_master                   # typically SERVICE; or free-form
  description, qty, unit_price, amount, sort
  # header total derived from lines (no stored total v1; or denormalized subtotal - confirm in Phase B)

# project.client_id / project.lead_id: populate the spine's reserved cols (lead Won → set both).
# FileLink (core Drive): entity_type='quotation', entity_id=quotation.id  → build the API.
```

**Cross-schema rule (BL-030):** `status_id`, `tenant_id` and any future core refs stay plain indexed columns, NOT DB FKs. Intra-`app_ems` FKs (client/lead/category/product/quotation) kept. New tables via the **per-module Alembic** revision (next after `0001_ems_baseline`).

---

## Status-engine entities (seeded in `install_tenant`, registered in `register_engine_entities`)

| Entity | Graph (unscoped, tenant-level) | Edges of note |
|--------|--------------------------------|---------------|
| `client` | Active → Inactive → Archived | reactivate/restore edges |
| `lead` | New → Contacted → Qualified → Won / Lost | **Won fires the create-Project workflow** |
| `quotation` | Draft → Sent → Accepted / Rejected → Expired | revise = new row (lineage), not an edge |

(`product_master` = simple `is_active`, NOT engine. `invoice` deferred to F.)

---

## API (`modules/ems/routers/...`, module routers - Service-Repository layered, every query tenant-scoped)

- `/ems/clients` - Resource CRUD + import config + export (id-first) + status transitions.
- `/ems/leads` - Resource CRUD + import + export + status transitions; **`POST /ems/leads/{id}/convert`** (or the graph-driven Won transition handler) → creates/links a Project from a chosen template, sets `lead.project_id` + `project.client_id`/`lead_id`.
- `/ems/product-categories` - tree CRUD (list by `parent_id`, create/rename/reparent/delete; delete guard = no children + no products).
- `/ems/products` - Resource CRUD + import + export; `kind` + category picker; `is_active` toggle.
- `/ems/quotations` - Resource CRUD; `quotation_lines` nested save; **`POST /{id}/revise`** (clone + `parent_quotation_id` + `revision_number+1`); status transitions; raised-against-lead (project_id nullable).
- **Core: `/documents/links`** (NEW) - `POST` link a Drive file to (`entity_type`,`entity_id`); `GET ?entityType=&entityId=` list; `DELETE /{id}` unlink. Polymorphic save-validate + tenant-scoped resolve (the `FileLink` discipline). Quotation form is the first caller.

Module perms CSV (grep core first - no collisions: core owns `templates`/`emails`/`forms`/`workflows`, not these): `clients`, `leads`, `product_categories`, `products`, `quotations` × `read/manage` → granted to tenant Admin on install (`tenant_admin_grant` / `install_tenant`). Core perm for links rides existing `documents.*` or a new `attachments.*` (confirm in Phase B).

---

## Slices (each: frontend-first → backend → TDD → E2E → review → merge)

- **Slice 1 - CRM: Clients + Leads.** Two Resource list/form entities; status engine (client + lead graphs seeded). **Inline quick-create Client** from the Lead form (SearchSelect + "+ New" dialog). **Won → "Create event"** graph-driven action: pick a template → spawn Project → link lead/client/project. Importable (client + lead), id-first export. Triggerable + rule fact sources registered. Terminology (Client/Lead).
- **Slice 2 - Product catalog: categories tree + master.** Category **tree editor** (reuse Drive `FolderTree`/`tree.tsx` pattern, no dnd needed v1 - add/rename/reparent/delete). Product master Resource list/form (`kind` enum, category SearchSelect, price/tax/sku/uom, `is_active`). Importable. Terminology (Product/Category).
- **Slice 3 - Quotations.** Resource list/form; **`quotation_lines` editor** (reuse `RepeaterField`: product SearchSelect → master / free-form description, qty × unit_price → derived amount + header total); **revise** action (clone + lineage, revision badge); status engine; **F3 document attach** (build `/documents/links` + an attach panel on the form); raised against a Lead (`project_id` nullable, back-linked on the lead's Won). Triggerable + terminology.

**Order is dependency-driven:** CRM (client/lead referenced by quotation) → catalog (products referenced by lines) → quotations.

---

## Phase pattern (per slice)

- **A (frontend-first, mock):** Resource list/form on a mock `ems-service` extension; all states (loading/empty/error/success); responsive **375 + 1280**; status segments + action registry; inline quick-create (s1) / tree editor (s2) / line-item repeater + attach panel (s3).
- **B (backend):** new `app_ems` tables via **per-module Alembic** revision; Service-Repository per entity (tenant-scoped); seed status graphs in `install_tenant`; register status/triggerable/fact/importer/terminology in `register_engine_entities`; the **Won→create-Project** workflow handler; the core **FileLink API**; swap mock→real at the service boundary.
- **C (TDD + E2E):** backend - CRUD + tenant isolation; lead Won spawns+links a Project (workflow, loop-safe); quotation revise clones with lineage + line copy; line total derivation; product `kind` behavior; category tree guards (delete with children/products); import round-trip (client/lead/product); FileLink polymorphic save-validate + tenant-scoped resolve; new-perm grant on install. E2E - the net-demo journey (real clicks: create client → lead → quick-create client → Won→create event → catalog → quotation+lines+attach+revise → transitions → Terminology relabel). Per-slice acceptance-criteria + test-report docs (mirror plan 11's `*-acceptance-criteria.md` / `*-test-report.md`).

---

## Reuse map (extend, don't rebuild - per mandate)

| Need | Reuse |
|------|-------|
| List + form per entity | Resource shell (`use-X-list-config.tsx` + `X-detail.tsx`), clone `ems/profiles` + `ems/events` |
| Status transition actions | graph-driven action pattern (`profile-detail.tsx` moves; tenant console `use-tenant-actions.tsx`) |
| Import button | `ResourceListConfig.importer = { entityType, writePermission, context? }` |
| Line items editor | `components/platform/form-renderer/repeater-field.tsx` (`RepeaterField`) |
| Category tree | `components/platform/document-drive/folder-tree.tsx` / `components/ui/tree.tsx` |
| Sub-row add/delete (fallback) | `event-templates/[id]/child-list-editor.tsx` (`ChildListEditor`) |
| Dropdowns | `SearchSelect` / `MultiSelect` (every dropdown searchable - mandate) |
| Document attach | Drive `FileLink` model (build the API + a small attach panel; `file-input.tsx` for staging) |
| Inline quick-create | **NEW small pattern** - SearchSelect + adjacent "+ New" → create-dialog → re-select (no existing precedent; build minimally, generalize later) |

---

## Out of scope / backlog (each gets its own grill+plan at pickup)

- **Offerings + capacity_units + Tickets + nomination** → Cluster D.
- **Unified Invoice + invoice_lines + Payment + gateway provider + integration-log + Settlement/give-back** → Cluster F (also activates `project.commercial_mode`/fee terms).
- **Review (review_assignments/config, reviewer=Profile)** → Cluster E (needs Profile portal auth, Cluster D).
- **Agenda/Session/Checkpoint** → G/H. **Venue/Seating layout designer + stadium import** → Venue plan.
- Quotation **PDF render** (F2 binding) - lands with the Invoice/F2 plan, not here.
- Multi-client per project (co-organizers/sponsors), inline-quick-create generalization, category dnd reorder, quotation approval workflow templates.

## New backlog candidates to log
- BL-1xx **FileLink entity-attach API** generalized (any entity, not just quotation) + a reusable `<EntityAttachments>` panel.
- BL-1xx **Inline quick-create** reusable primitive (SearchSelect create-new mode).
- BL-1xx **Lead→Project convert** picks/clones tasks/checklist (Cluster B tasks materialization, deferred from plan 11).
