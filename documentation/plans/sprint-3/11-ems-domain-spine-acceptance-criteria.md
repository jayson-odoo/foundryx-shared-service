# Sprint 3 · Plan 11 — EMS Domain Spine · User Acceptance Criteria

**Plan:** `11-ems-domain-spine.md` · **Advances:** F4 (first vertical, first big module `app_ems`)
**Gate role:** final of the continuous 08→11 run. Depends on 08 (Terminology), 09 (Import), 10
(Module Platform). Built in 3 slices (Profiles → Types/Templates/Projects → Participants).

Format: **Given / When / Then**, traced to a locked decision (Dn) + pillars 🟢📈🧭✅.
MET = named test green (UI at 375/1280 where it renders).

---

## 1. Functional SaaS — the EMS spine works end-to-end 🟢

- **AC-11-01 (demo) Full spine demo passes.**
  *Given* a tenant, *when* the operator installs `ems`, creates Project Type "Fun Run", a Template
  with its eligibility flow (Registered → Pending Payment → Eligible → Checked-in/Cancelled) +
  roles (Attendee/Volunteer) + segments (by distance), creates Project "City Run 2026" from the
  template (its own editable eligibility graph materializes), imports 200 profiles, and registers
  participants (add-one + bulk), *then* each participant carries a role/segment + an eligibility
  status that moves through the event's graph, and tier-1 + tier-2 both gate access.

- **AC-11-02 (D2) Profiles are admin-managed + importable, not staff users.**
  *Given* `/ems/profiles`, *then* it is a Resource list/form with `UNIQUE(tenant_id, lower(email))`
  dedup, soft-delete + Trash, and tier-1 status transitions; profiles are NOT `public.users` rows
  (no `roles[]`/`permissions[]`, kept off RBAC/impersonation surfaces). Auth columns exist but are
  unused in F4 (portal = Cluster D).

- **AC-11-03 (D4) Three-level hierarchy: Type → Template → Project.**
  *Given* the model, *then* `project_types` = light category; `project_templates` = many per type,
  each owning eligibility flow (scoped graph at `scope=template_id`) + roles + segments; `projects`
  are instances created from a template.

- **AC-11-04 (D4) Create-from-template copies the eligibility graph.**
  *Given* a Project created from a template, *when* created, *then* `copy_scope(db,
  'project_participant', tenant, from=template_id, to=project_id)` materializes the project's own
  editable graph (Option A — per-project copy, not live-inherit); roles/segments stay template-level
  shared (participant FKs point at the template's rows, not copied).

- **AC-11-05 (D6) Participant registration join + one-step bulk.**
  *Given* a Project's participants tab, *when* the admin adds one or bulk-imports, *then* a
  `project_participants` row (one per profile+project v1, `UNIQUE(tenant_id, profile_id, project_id)`)
  is created with role_id/segment_id (→ template rows) + tier-2 status; bulk import is project-scoped
  (`project_id` from import context) and the profile column uses **find-or-create-by-email** (existing
  → link, never update the shared profile; new → create a minimal profile).

## 2. Scalable architecture / multi-tenant 📈

- **AC-11-06 (D1) EMS is a module, not core.**
  *Given* `ems`, *then* it lives in `app_ems` schema with per-module Alembic
  (`alembic_version_ems`), installs/uninstalls cleanly (per-tenant uninstall wipes that tenant's rows
  only), `optional`-deps omnichannel, and `provides` `profile.resolve@1` + `participant.resolve@1`.

- **AC-11-07 (D3) Two-tier validity, both on the status engine, three surfaces.**
  *Given* the engines, *then*: tier-1 = `Profile.status_id` (tenant-level graph Active/Suspended/
  Blacklisted); project lifecycle = `projects.status_id` (tenant-level Draft→…→Completed/Cancelled);
  tier-2 = participant eligibility (scoped machine, `scope_attr=project_id`, reusing the form-engine
  scoped extension — **zero new engine code**). Checkpoint access (Cluster H) = tier-1 AND tier-2 valid.

- **AC-11-08 (D9) Pure registration into existing engines, no new engine code.**
  *Given* the spine entities, *then* each registers into status (tier-1, tier-2), workflow
  triggerable (`profile`/`project`/`project_participant` → created/updated/status_changed), rule fact
  sources (segment/role/eligibility), importer configs (profile + participant), and terminology labels
  — clusters B–H get automation for free.

- **AC-11-09 (house) Every query tenant-scoped, Service-Repository layered.**
  *Given* any `/ems/*` endpoint, *then* repositories are tenant-scoped, no DB/raw SQL in routers,
  schemas are camelCase `ApiModel`.

- **AC-11-10 (D5/D7) Future seams reserved without building them.**
  *Given* the tables, *then* `projects.client_id` is nullable (Cluster B), `domain_name` is a
  placeholder (F5), and financial (ticket/invoice) columns are absent in F4 — "paid?" is designed to
  derive `participant → ticket → invoice.status` with no denormalized payment column.

## 3. Guided UX 🧭

- **AC-11-11 (D5/F10) "Event" label via Terminology, relabel follows everywhere.**
  *Given* the seeded labels (project→"Event", project_type→"Event Type", project_template→"Event
  Template", project_participant→"Participant", profile→"Profile"), *when* a tenant relabels
  "Event"→"Race", *then* every surface (lists, menus, breadcrumbs, buttons) follows via plan-08.

- **AC-11-12 Eligibility flow editor is the status canvas.**
  *Given* a template's/project's Flow tab, *then* the eligibility graph is edited via `EntityFlow`
  (scopeId = template_id / project_id), gated by the Edit toggle, with graph-driven row transitions
  (`fireable_edge_ids` batched) on the participants list.

- **AC-11-13 Bulk participant registration is one guided step** (BRD Excel upload) launched from the
  Project's participants tab — not a separate disconnected screen.

- **AC-11-14 (house mandate) Responsive** at 375px and 1280px across all EMS lists, forms, Flow tabs,
  and the embedded participants list.

## 4. Validated quality ✅

- **AC-11-15 Backend tests green** (per slice): scoped-graph materialization on project create
  (`copy_scope`) · tier-1 + tier-2 transitions through the one executor · participant uniqueness ·
  profile email dedup · import round-trip (incl. find-or-create + project context) · tenant isolation
  · module install grants perms · the full pre-existing status-engine suite stays green (tenant
  lifecycle untouched — load-bearing).

- **AC-11-16 E2E green** (real clicks, both viewports, dedicated tenant): create type → create event →
  import profiles → register participants → move eligibility; relabel Event via Terminology. Reports
  filed per slice.

- **AC-11-17 (D6/D9) Find-or-create + project-context import verified against the live F8 engine** (the
  first real consumer beyond Users) — exercises plan-09 AC-09-23 (D17/D18) end-to-end.

- **AC-11-18 (governance/D1) Module governance honored:** `manifest.json` (module_name, schema,
  alembic_version_table, optional[omnichannel], provides[…]) · permissions CSV
  (profiles/project_types/project_templates/projects/participants × read/manage) granted to tenant
  Admin on `install_tenant` · no core-table alteration · no cross-schema FK into another module.

- **AC-11-19 Code review approved** per slice before merge to `main`.

---

## Delivery note (2026-06-16)
Backend spine **complete, tested (8 + full 804 green), live-verified** end-to-end (per-module
Alembic fresh-upgrade → `app_ems`; type→template→project copy_scope; tier-1/tier-2 transitions;
find-or-create participant import; tenant isolation). Frontend: Profiles + Events list pages
(create + profile bulk-import + create-from-template) + module-gated Events menu — live-verified
via Playwright MCP. **Deferred** (documented, backend-supported, primitives exist): the tabbed
detail-page **Flow tab** (reuse `EntityFlow`) + **embedded participants tab** with graph-driven
transitions/bulk-import UI (AC-11-12/13 detail surfaces). All other AC MET. See
`11-ems-domain-spine-test-report.md`.

## Management-UI follow-up (2026-06-18) — deferred surfaces now SHIPPED
The deferred detail surfaces are **built + live-verified via Playwright** (branch
`sprint-3/ems-management-ui`, merged to `main`). First iteration of the spine UI is complete.
- **Event Types + Event Templates** on the Resource shell (create/edit/delete; backend gained
  PATCH/DELETE + delete guards). **AC-11-03 met in UI.**
- **Event Template detail** = Details · **Roles** · **Segments** · **Eligibility-flow editor**
  (`EntityFlow`, scope = template_id). Fixed the participant `scope_exists` guard to accept a
  template *or* project scope owner (the template's graph 404'd otherwise). **AC-11-01/12 met.**
- **Event detail** = **Participants** (role/segment assign + graph-driven status moves shown as the
  available next states off the graph; bulk import) · **Eligibility-flow editor** (scope = project_id).
  **AC-11-12/13 met.** Roles/segments are template-owned, validated cross-template.
- **Profiles** get a detail/form view + tier-1 status change in the list row, the form, and **bulk**.
- **Status engine gates participation (AC-11-07 deepened):** a `blocks_access` profile
  (Suspended/Blacklisted) is refused as a participant — add + bulk import (422) — and withheld from
  the Add picker. Tests +6 (14 ems green; status-engine suite stays green).
- Generic win: the **Resource shell gained a card/list view toggle** (`cardRender`/`defaultView`,
  persisted per `viewKey`), and the **App Store migrated onto the Resource shell** (card default,
  storefront + console) with a module detail/form view — closes sprint-3/10 AC-10-12/13.

## Definition of Done (plan 11 / F4 spine)
All AC-11-* MET across the 3 slices · suites green (incl. unchanged status-engine suite) · E2E
reports filed · reviewer approved · merged to `main`. The EMS spine is ready for clusters B–H to
wire onto (Money/Submissions/Agenda/Portal designed-for, not built).

---

## Cross-plan continuity & philosophy gates (08 → 11)

The objective is to complete 08→11 **continuously, validated at each step**. The chain holds only
if each plan's outputs feed the next:

| Gate | Producer | Consumer | Verifying AC |
|------|----------|----------|--------------|
| Terminology registry is module-extensible | 08 | 11 seeds `project`/`profile` labels | AC-08-09, AC-11-11 |
| Import context + find-or-create resolver | 09 | 11 participant bulk-reg | AC-09-23, AC-11-17 |
| Per-module Alembic (BL-029) | 10 slice 1 | 11 `app_ems` schema | AC-10-03, AC-11-06 |
| Optional-dep + capability registry | 10 | 11 `optional` omnichannel + `provides` resolve | AC-10-01/08, AC-11-06 |
| `active_modules` filter across catalogs | 10 | 11 EMS catalog items gate per-tenant | AC-10-06, AC-11-08 |

**Philosophy pass (every plan):** 🟢 a working net demo · 📈 multi-tenant + server-authoritative +
no per-row/per-tenant explosion · 🧭 self-evident guided UI, no instructional copy, responsive at
375/1280 · ✅ backend + frontend + E2E suites green, reviewer approved, test report filed, merged.
**No plan starts until the prior plan's Definition of Done is met.**
