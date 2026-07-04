# Sprint 3 · Plan 11 — EMS Domain Spine (the `ems` module — Profiles · Project Types · Projects · Participants)

**Branch:** `sprint-3/11-ems-domain-spine`
**Advances:** F4 (roadmap `sprint-3/00`; grill record `F4-foundations-grill-decisions.md` §4). The **first vertical**, and the first big **module** (`app_ems`). BRD baseline: `documentation/preliminary_planning/EMS_Project_Plan.md` (`Profiles`, `Projects(Events)`, `User_Project_Roles`, `Submission_Entries`, `Event_Tickets`, `Quotations`). **Consumed by** every cluster B–H.
**Spawns:** BL-1xx multi-role per participant per event (multiple `project_participants` rows) · BL-1xx participant portal auth surface (Cluster D / F5) · BL-1xx Client/Lead/Quotation (Cluster B) · BL-1xx Submission wrapper over `form_submission` (Cluster E) · BL-1xx Ticket/Invoice/Payment + `invoice` status entity (Cluster F) · BL-1xx tasks/checklist materialization (Cluster B).
**Depends on:** **F10 Terminology** (project→"Event" label), **F8 Import Engine** (participant bulk-reg), **F9 Module Platform** (per-module Alembic + EMS-as-module + the omnichannel `optional` dep), the **scoped status engine** (form-engine `statuses.scope_id` / `scoped.py` — reused verbatim for per-event eligibility), status/rule/workflow registries, Resource shell, generalized auth ceremonies (`security.py`/throttle/token helpers — the module calls them for portal-scoped `profiles` auth).

---

## Context

The platform spine is done; the EMS domain is empty. This plan lays the **foundation entities** every cluster wires onto — built as the **`ems` module** (grill decision: EMS is a module, not core, so the platform stays a horizontal base sellable to non-EMS clients and the App Store has a flagship + 3rd-party room). It is the spine only: identity (Profile), the event template (Project Type), the event (Project), and the registration join (Project Participant) — with two-tier validity on the status engine. Money, submissions, agenda, badges, portal = later clusters, **designed-for but not built here**.

**Key identity decision:** a participant is **not** a staff `public.users` row. A separate **`profiles`** table holds participant identity (auth-capable for the *portal*, but issuing a portal-scoped session, never a staff JWT with `roles[]`/`permissions[]`). This resolves the form-engine rule ("create a participant record, never an auth User" = never a *staff* user) and keeps 50k attendees out of the RBAC/impersonation surfaces. F4 manages profiles from the **admin** side + makes them **importable**; the participant-facing portal lands in Cluster D + the website builder (F5) — the milo-run/coway-run registration site.

**Net demo at end of plan 11:** install the `ems` module on a tenant; create a **Project Type** "Fun Run" (edit its default eligibility flow on the status canvas: Registered → Pending Payment → Eligible → Checked-in / Cancelled; default roles Attendee/Volunteer; default segment by distance); create a **Project** (UI "Event") "City Run 2026" from that type → its **own** editable eligibility graph is materialized (Flow tab); **import 200 profiles** via the Import Engine; **register** some as Project Participants (admin add-one + bulk), each with a role/segment and an eligibility status that moves through the event's graph; a participant's tier-1 (tenant) + tier-2 (event) status both gate access. The tenant relabels "Event" → "Race" via Terminology and every surface follows.

---

## Locked design decisions (from grill record §4)

1. **D1 — `ems` module, `app_ems` schema, per-module Alembic** (F9). `optional`-deps omnichannel (WhatsApp action self-disables if omnichannel absent). Registers into core catalogs: status entities, triggerable entities, rule fact sources, importer configs, terminology labels.

2. **D2 — `profiles` ≠ `users`; identity core only.** Participant identity, tenant-scoped, separate table. Auth-capable via the module **calling core auth utilities** (`security.py` hashing, throttle, token helpers) — core never learns about `profiles`; portal-scoped session, not a staff JWT. F4 = **admin-managed + importable**; **portal deferred** (Cluster D + F5). **Profile = stable identity core** (`full_name`, `email`, `phone`, + a small common set `country`/`organization`/`title`) — **event-specific data lives in form submissions, NOT profile columns** (the profile is the person across events). Tenant-defined **custom profile fields = backlog** (needs a custom-field engine). **Dedup = `email` required + `UNIQUE(tenant_id, lower(email))`** (email = portal login + comms primary = the identity key); phone optional. **Auth columns reserved-not-used** in F4 (`password_hash`/`email_verified_at`/`last_login_at` exist; no flow — Cluster D adds no migration). Soft-delete + Trash.

3. **D3 — Two-tier validity, both on the status engine. THREE status surfaces.**
   - **Tier-1 (tenant access):** `Profile.status_id` — **tenant-level (unscoped)** graph (Active / Suspended / Blacklisted + reactivate edges).
   - **Project lifecycle:** `projects.status_id` — **tenant-level (unscoped)** graph (Draft → Planning → Active → Completed / Cancelled). Per-template project lifecycle = backlog.
   - **Tier-2 (event access):** the participant's eligibility — a **scoped status machine, scope = Project** (`scope_attr = project_id`, reusing the form-engine scoped extension — **zero new engine code**), **materialized by copying the TEMPLATE's eligibility flow at Project creation** (Option A: per-project editable copies, *not* live-inherit).
   - Checkpoint/access gate (Cluster H) = tier-1 **AND** tier-2 valid.

4. **D4 — THREE-level hierarchy: Type → Template → Project.** **`project_types`** = light **category** master data (classify/filter/report). **`project_templates`** = reusable presets, **MANY per type** (Standard / VIP / Hybrid Conference); each **owns the configurable defaults** — eligibility **flow** (a scoped graph at `scope = template_id`, edited on the *template's* Flow tab via `EntityFlow`), **roles**, **segments**. **`projects`** = instances created **from a template**. Create-from-template **copies** the template's eligibility graph via a new **`copy_scope(db,'project_participant',tenant,from=template_id,to=project_id)`** helper (added to `scoped.py`); the flow diverges per project, while **roles/segments stay template-level shared** (participant FKs point at the template's role/segment rows — not copied). So **one `entity_type` (`project_participant`), two scope tiers**: template (template) + project (instance).

5. **D5 — `projects` canonical table; UI label "Event" via Terminology.** Internal/admin face = Project (tasks/checklist/quotation later); participant face = Event. One row, two faces. `template_id` FK (+ `type_id` denormalized via template); `client_id` **nullable** until Cluster B; `domain_name` placeholder (F5). Table + code names immutable (F10 rule).

6. **D6 — `project_participants` = the registration join** (renamed from BRD `User_Project_Roles`; name correlates with parent `projects`). **One row per (profile, project)** v1 (multi-role → backlog). Carries `profile_id`, `project_id`, **`role_id`/`segment_id` FKs to the TEMPLATE's role/segment sub-tables**, tier-2 `status_id`. **Segment exposed as a rule fact** (reviewer allocation BRD §147). **Bulk registration = ONE step** (BRD Excel upload): the participants importer is **project-scoped** (launched from the Project's participants tab → `project_id` from import context); the **profile reference uses a find-or-create-by-email resolver** (existing email → link, **never update** the shared profile; new email → create a minimal profile from the row). Registered as: scoped-status entity (`scope_attr=project_id`), triggerable entity, rule fact source, importer config. *(Requires two F8 additions — import context + find-or-create resolver mode — logged into plan 09.)*

7. **D7 — Financial ≠ access (locked now, tables built in Cluster F).** A **Ticket** (per-seat: `purchaser_profile_id`, `attendee_participant_id` 1:1, `invoice_id`, `product_id`) bridges Participant (access) ↔ Invoice (per-order). **`invoice` will be a status-engine entity** (Draft→Issued→Partially Paid→Paid→Overdue→Refunded/Void). A participant's **"paid?" derives** through `participant → ticket → invoice.status` — **no denormalized payment column**. Nomination/transfer swaps `attendee_participant_id`; money untouched (US-08). Post-payment **workflow** (US-14) flips tier-2 eligibility on invoice→Paid; comp/free = no ticket, eligibility flips directly. *F4 only reserves the FK seams; no ticket/invoice tables yet.*

8. **D8 — Submission binding (Cluster E, designed-for).** EMS Submission = a thin wrapper (project_id + participant_id + review/revision) **pointing at a core `form_submission`** (`subject_type=project_participant`), not a parallel capture store.

9. **D9 — Engine wiring is the whole point.** Each spine entity registers into the existing engines so clusters get automation free: status (tier-1 profile, tier-2 scoped participant), workflow triggerable (`profile`, `project`, `project_participant` → `entity.created/updated/status_changed`), rule fact sources (segment/role/eligibility), importer configs (profile + participant bulk-reg), terminology labels. No new engine code — pure registration.

---

## Data model (`app_ems` schema)

```
profiles
  id, tenant_id, email (req), phone, full_name, country, organization, title
  password_hash, email_verified_at, last_login_at         # RESERVED, not used in F4 (Cluster D)
  status_id      FK statuses                                # tier-1 (tenant-level graph)
  is_deleted, deleted_at/by, created_at, updated_at
  UNIQUE(tenant_id, lower(email))                           # tenant-scoped dedup

project_types                                               # light CATEGORY
  id, tenant_id, name, description, is_deleted, created_at, updated_at

project_templates                                           # reusable preset, MANY per type
  id, tenant_id, type_id FK, name, description, is_deleted, created_at, updated_at
  # eligibility flow = statuses/edges rows at entity_type='project_participant', scope_id=template_id

project_template_roles      id, tenant_id, template_id FK, name, sort
project_template_segments   id, tenant_id, template_id FK, name, sort

projects                                                    # UI "Event"
  id, tenant_id, template_id FK, type_id (denorm), title, brief, notes
  client_id (nullable, Cluster B), domain_name (placeholder, F5)
  start_date, end_date, event_validity_end (UTCDateTime)
  status_id FK statuses                                     # project lifecycle (tenant-level graph)
  is_deleted, created_at, updated_at

project_participants                                        # the registration join
  id, tenant_id, profile_id FK, project_id FK
  role_id FK project_template_roles, segment_id FK project_template_segments
  status_id FK statuses                                     # tier-2 eligibility (scoped, scope_id = project_id)
  is_deleted, created_at, updated_at
  UNIQUE(tenant_id, profile_id, project_id)                 # one row per (profile, project) v1

# NO financial columns in F4. Cluster F adds: ticket(purchaser_profile_id, attendee_participant_id, invoice_id, product_id), invoice (status entity)
```

Scoped-status: `project_participant` registered `scope_attr='project_id'`. Template flow = rows at `scope_id=template_id`; **`copy_scope(...)` materializes the project graph from the template at Project creation**. Capabilities provided: **`profile.resolve@1`** + **`participant.resolve@1`** (for future cross-module soft-refs; the F9 provider reference). Manifest: `module_name=ems`, `schema=app_ems`, `alembic_version_table=alembic_version_ems`, `optional:[omnichannel]` (active WhatsApp consumption = a later EMS-comms slice), `provides:[profile.resolve, participant.resolve]`. Terminology defaults: project→"Event", project_type→"Event Type", project_template→"Event Template", project_participant→"Participant", profile→"Profile".

## API (`modules/ems/backend/...`, module routers)
- `/ems/profiles` — Resource CRUD + import config + tier-1 transitions (status-graph driven). Admin-side.
- `/ems/project-types` — Resource CRUD (category).
- `/ems/project-templates` — Resource CRUD + eligibility-flow editor (status canvas, scopeId=template_id) + roles/segments sub-tables.
- `/ems/projects` — Resource CRUD; create-from-template `copy_scope`s the eligibility graph; Flow tab (scopeId=project_id); project-lifecycle transitions.
- `/ems/projects/{id}/participants` — embedded participants list; add-one + **project-scoped bulk import** (find-or-create profile); graph-driven row transitions; `fireable_edge_ids` batched.
Service-Repository layered, every query tenant-scoped (house). Module perms CSV: `profiles`, `project_types`, `project_templates`, `projects`, `participants` × `read/manage` → tenant Admin on install (`install_tenant`).

## Slices (each: frontend-first → backend → TDD → E2E → review → merge)

- **Slice 1 — Profiles.** Model + admin Resource list/form, tier-1 status engine, reserved auth columns (no portal UI), **import config** (first real consumer of F8 beyond Users), terminology labels. The reference EMS entity.
- **Slice 2 — Types + Templates + Projects (3 entities).** Type (category) master data; Template (preset) with the eligibility-flow editor (status canvas, scope=template_id) + roles/segments sub-tables; Project instance (create-from-template → **`copy_scope`** the eligibility graph) + project-lifecycle status; list/form + **Flow tab** (per-project eligibility canvas).
- **Slice 3 — Project Participants.** Registration join (role_id/segment_id/tier-2 eligibility); admin add-one **+ one-step project-scoped bulk import (find-or-create profile)**; participants embedded under a Project; register fact source + triggerable + scoped-status.

## Phase pattern (per slice)
- **A (frontend-first, mock):** Resource list/form (+ Flow tab for slice 2, embedded participants for slice 3) on a mock service; all states; responsive 375/1280.
- **B (backend):** `app_ems` tables via **per-module Alembic** (F9); registries (status/trigger/fact/importer/terminology); module install/uninstall hooks (`install`, `install_tenant`, `uninstall_tenant`); swap mock→real.
- **C (TDD + E2E):** backend (scoped-graph materialization on project create; tier-1/tier-2 transitions; participant uniqueness; import round-trip; tenant isolation; module install grants perms) + E2E (create type → create event → import profiles → register participants → move eligibility; relabel Event via Terminology). Reports per slice.

## Deferred (designed-for, not built)
Client/Lead/Quotation + tasks/checklist → **B** · Submission wrapper → **E** · Ticket/Invoice/Payment (+ `invoice` status entity + bridge FKs) → **F** · Agenda/Session → **G** · Event Day/Checkpoint/Badge → **H** · Participant **portal** → **D** + F5.

---

## Out of scope / backlog
Multi-role per participant per event · per-template project lifecycle (v1 = one tenant graph) · per-project role/segment divergence (v1 = template-shared) · tenant-defined custom profile fields (needs a custom-field engine) · portal auth surface · the deferred clusters above. Each gets its own grill+plan at pickup.
