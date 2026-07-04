# F4 + Foundations — Grill Decision Record

**Status:** Decisions locked via `/grill-me` (2026-06-16). Not yet coded. Each numbered plan below gets its own grill+plan at pickup; this record is the shared baseline every one of them starts from.

**Scope of this grill:** establishing F4 (the EMS domain) surfaced three *new cross-cutting foundations* that must land first. F4 itself was re-scoped from "core domain" to "the first vertical **module**."

---

## 0. Headline decisions

1. **The EMS domain is a MODULE, not core.** Core stays strictly **horizontal substrate** (sellable as a bare platform / ERP base to non-EMS clients); verticals are modules. EMS = one `ems` module on schema `app_ems`.
2. Three new foundations fell out of F4 and must precede it: **F8 Import Engine**, **F9 Module Platform v2**, **F10 Terminology**.
3. **Participant ≠ staff user** — a separate `profiles` table (portal-scoped auth), never `public.users`.
4. **Two-tier validity** rides the status engine: tier-1 = profile/tenant status; tier-2 = per-event eligibility (scoped status machine, scope = Event).
5. **Financial ≠ access**: Ticket (money, per-seat) bridges Participant (access) ↔ Invoice (per-order); `invoice` is a status-engine entity; participant "paid?" derives through the bridge.

### Revised foundation sequence

| Order | Plan (proposed file) | Type | Gate / why here |
|-------|------|------|-----------------|
| 1 | **F10 Terminology** — `sprint-3/08-terminology.md` | core, small | Horizontal; every list title / menu / import-history page consumes it |
| 2 | **F8 Import Engine** — `sprint-3/09-import-engine.md` | core | Target Users first; needed before participant bulk-reg |
| 3 | **F9 Module Platform v2** — `sprint-3/10-module-platform.md` | core/governance | *Infra first* (per-module Alembic, BL-029) is the F4 prereq; dep-manifest + extension registry needed before the later EMS-comms slice |
| 4 | **F4 EMS domain spine** — `sprint-3/11-ems-domain-spine.md` | `ems` module | First vertical, on the proven foundations |
| 5+ | Clusters B–H, F5, F6, F7 | mixed | Mostly wiring |

*(Plan numbers continue the sprint-3 sequence; WABA took 06+07.)*

---

## 1. F8 — Import Engine (core, cross-cutting)

A 6th cross-cutting engine, same shape as F1–F3. Generic bulk import for **every** opt-in Resource list. 4th toolbar button beside Filters · Export · Columns.

- **Shape:** core `app/import_engine/` + a registry of **`ImporterDef` per entity** (mirrors exporter / StatusEntity / TriggerDef). Frontend `ResourceListConfig.importer` — Import button renders only when present.
- **Opt-in, declared per module** (a module ships its importer config in its own code, like its `permissions.csv`). Many lists must NOT be importable (Email log, Audit log, Workflow runs, Tenants).
- **Importable columns = the server-writable whitelist only** (reuse the `entity.update` writable discipline) — the template can never offer a column the server rejects.
- **Configurable template = pick-from-catalog.** `ImporterDef` declares a column catalog (required + optional, each tagged). User toggles which **optional** columns to include in the download (required always in) — like the Columns visibility chooser. **No invented columns** (that needs a future custom-field engine). Selection **persisted per-user-per-view** via the existing `view_preferences` table.
- **Mapping (Odoo-style step):** Upload (modal) → **Map** → **Review/Test** → **Commit**. Left = detected file headers, right = `SearchSelect` of catalog columns (+ "Don't import"); auto-mapped by normalized header match (clean template round-trip = 100% pre-selected). Mapping persisted on the job. Multi-sheet workbook → a **sheet picker** appears at Map (default = first sheet).
  - **Unmapped semantics:** file-col→nothing = warning (ignored); optional-col←nothing = warning (proceed); **required-col←nothing = proceed + per-row error** (user's chosen model — every row fails that field; *not* a hard block).
- **Modes (explicit, chosen in the modal), all entities:** Create-only · Update-only · Create-or-update (upsert). `ImporterDef.match_on` = ordered unique fields (system `id` always available + a natural key, e.g. Profile→email). Partial update (only present columns written; absent untouched); **required enforced create-only**. Key-present-no-match in update = row error; in upsert = create. **In-file duplicate match-keys = both error.**
- **Per-column model = declarative `ImportColumn`** (the consuming model declares it): `type` (string/integer/decimal/boolean/date/datetime/enum, coerced; bad parse = cell error), `required`, `unique`, **`resolver`** (FK/reference, **tenant-scoped** — name→id; unresolvable = cell error), **`multiValue`** (delimited cell, per-item resolve), `validators` (regex/min/max/length, reuse existing helpers), `transform` (trim/normalize). One imperative escape hatch: **`ImporterDef.validate_row(row, ctx)`** for cross-column rules. FK error message caps option-listing at small sets (≤25), else "no match."
- **Execution:** two-phase **Validate (dry-run, zero writes) → Commit**, **server-authoritative** (client only does trivial pre-checks). **`import_jobs` table** = source of truth (mirrors `download_jobs`): file storage key, entity_type, mode, mapping, status (`PENDING→VALIDATING→VALIDATED→IMPORTING→DONE/FAILED`), counts, error report. **Celery** (decoupled; eager-inline in dev via `celery_task_always_eager`). **Commit re-validates per row.** **Persistent import history.**
- **Results page** (dedicated route, not modal): summary counts, **failed rows only** with offending cells highlighted + per-cell message; **downloadable annotated error file** (original + `_error` column). **Reupload = a NEW job.** **Partial commit default** = import valid, skip+report invalid ("Import 320 valid rows (5 skipped)"); opt-in checkbox **"Abort if any row is invalid."** Inline cell-edit on the results page = deferred. (No inline edit v1.)
- **Imports drawer** top-right (reuse F3 `ActivityTriggers` universal-drawer pattern, beside notifications) — recent jobs, status, timestamp, polls like Downloads, click → results page. `/imports` page = full history.
- **Formats:** accept **xlsx, xlsm, xls, csv** behind a **single magic-byte-sniffing adapter** (`readers.py`) → uniform `list[dict]`; format-blind downstream. Libs: **openpyxl** (xlsx+xlsm), **xlrd** (xls only — the fragile legacy path), stdlib **csv** + **charset-normalizer** (encoding). `.xlsm` macros never execute server-side (cell-read only). **Template download = xlsx** with data-validation dropdowns for enum / small reference sets + styled header; CSV offered secondarily.
- **Caps:** row cap (default 10k) + file-size cap (default 10MB), **per-tenant configurable from day one** via an `import_settings` table (mirrors `workflow_settings`); fail-fast at upload.
- **Permissions:** import gated by the entity's **write perm** (no new per-entity key); 1 core key **`imports.read_all`** for the cross-actor audit view (else own jobs only).
- **Undo:** none auto (updates are destructive); job records **created + updated ids** for trace. Full undo = backlog.
- **Export↔import symmetry:** export can include the `id` match-key so **export → edit → reimport (update mode)** round-trips.

---

## 2. F9 — Module Platform v2 (core / governance)

First-class inter-module dependencies + 3rd-party extensibility. Extends the App Store.

- **Two dependency kinds in the manifest:**
  - **`requires` (hard):** topo install order + install-blocked-if-absent + uninstall guard. Used only when a module truly can't function without another.
  - **`optional` / `enhances` (soft):** **no install guard.** Consumer discovers the capability at runtime; if no provider present+active, the enhanced feature **self-disables/hides** (foolproof-UI warn, never silent runtime error). *EMS optional-depends on omnichannel* — installed → "Send WhatsApp" action appears; not → EMS runs fully without it.
- **Cross-module calls = a provider/consumer service registry, never direct imports.** Module B publishes named **versioned capabilities** (e.g. omnichannel `messaging.send`); module A resolves at runtime via the registry. A 3rd party can ship an alternative provider of the same capability.
- **Cross-module data references = soft refs, not DB FKs.** Store `(module, entity_type, id)`, resolve via the provider's service (tenant-scoped). **No `app_ems → app_omnichannel` FK** (preserves independent uninstall + schema isolation; generalizes the BL-030 deviation).
- **Extensibility = the registry pattern, opened to modules.** Any module can register into core (and published) extension catalogs (TriggerDef/ActionDef/StatusEntity/website-blocks/menu/ImporterDef/terminology). The registry *is* the public extension API; interfaces **versioned** (breaking = major bump, enforced by `depends_on` ranges).
- **Infra prerequisite for F4:** **per-module Alembic (closes BL-029)** + schema isolation proven for a big module. This is the F4 gate; the dep/extension features are needed only when EMS first crosses a module boundary (a later EMS-comms slice).

---

## 3. F10 — Terminology (core, small, general)

Per-tenant entity relabeling (Dreamz "Event" vs Sorento "Project"). Multi-tenant → must be per-tenant config, not build-time.

- **General system-wide mechanism** (any entity relabelable), seeded with EMS entities.
- Each registered entity declares a default **`{singular, plural}`** label; **`terminology_overrides`** table (tenant_id, entity_key, singular, plural) holds renames.
- Resolved labels ship to the frontend via a **cached config** (like permissions/branding); **`useTerminology()`** hook resolves them in menus, list titles, breadcrumbs, button text.
- **DB table + code names stay fixed** (`projects`) — immutable contract; only the display label changes.
- Surfaced on **Settings → Terminology**. Orthogonal to future language i18n.

---

## 4. F4 — EMS domain spine (`ems` module, `app_ems`)

### 4.1 Identity & validity
- **`profiles`** = participant person identity, tenant-scoped, **separate from `public.users`**. Auth-capable (portal login/set-password/change-email) by the **module calling core auth utilities** (`security.py`/throttle/token helpers) — core never learns about `profiles`; issues a **portal-scoped** session, not a staff JWT. F4 builds profiles **admin-managed + importable**; the participant **portal is deferred** (Cluster D + website builder F5 — the milo-run/coway-run registration site).
- **Two-tier validity, both on the status engine:**
  - Tier-1 (tenant access) = `Profile.status_id` — tenant-level graph (Active/Suspended/Blacklisted).
  - Tier-2 (event access) = the participant's eligibility, a **scoped status machine, scope = Event** (`scope_attr = project_id`, reusing the form-engine scoped-status extension — zero new engine code). Graph **materialized by copying the Project Type's default flow at event creation** (Option A: per-event editable copies, not live-inherit).
  - Checkpoint gate = tier-1 AND tier-2 both valid.

### 4.2 Entities & naming
- **`project_types`** = master-data config (template). Carries default eligibility flow, default roles, default segments (+ checklist/forms defaults as stubs for later clusters).
- **`projects`** (UI display label "Event") = instance of a type; dates, `domain_name` placeholder, `client_id` **nullable** until Cluster B. Internal/admin face = "Project" (has tasks/checklist/quotation); participant face = "Event". One row, two faces. Display label is terminology-controlled (F10).
- **`project_participants`** = the registration join (renamed from BRD `User_Project_Roles`; name correlates with parent `projects`). One row per (profile, project) v1 (multi-role per person → backlog). Carries `profile_id`, `project_id`, `role`, `segment`, tier-2 `status_id`. **Role + segment = Project-Type master data**; **segment exposed as a rule fact** (reviewer allocation, eligibility conditions). Registered as scoped-status entity + triggerable entity + fact source + import config.

### 4.3 Hierarchy (levels)
```
Tenant
├── Profile ............. tier-1 status
├── Project Type ........ master-data config
└── Project ("Event") ... instance; dates, domain, eligibility graph
    ├── Project Participant (role, segment, tier-2 eligibility)
    │   ├── Submission ... wraps core form_submission        [E]
    │   └── Check-in ..... per checkpoint                    [H]
    ├── Agenda → Session                                     [G]
    ├── Event Day → Checkpoint                               [H]
    ├── Task / Checklist (materialized from type)            [B]
    ├── Ticket / Product                                     [F]
    └── Quotation (refs Project + Lead + Client)             [B]
```

### 4.4 Financial vs access (locked now, tables built in Cluster F)
- **Ticket** = per-seat financial unit: `purchaser_profile_id`, `attendee_participant_id` (1:1 to participant), `invoice_id`, `product_id`, status.
- **Invoice** = per-order (one invoice → many tickets in a bulk buy); **`invoice` is a status-engine entity** (tenant-level: Draft→Issued→Partially Paid→Paid→Overdue→Refunded/Void). **Payment** → invoice.
- Participant **"paid?" derives** through `participant → ticket → invoice.status` — **no denormalized payment column** (read live through the bridge; no second status to drift).
- **Nomination/transfer** swaps `attendee_participant_id` on the ticket; invoice + payments never move (US-08).
- Post-payment **workflow** (US-14) listens for invoice→`Paid` and transitions the participant's tier-2 eligibility to `Eligible`. Comp/free participant = no ticket → eligibility flips directly.

### 4.5 Submissions binding
- EMS **Submission** (Cluster E) = a thin domain wrapper (project_id + participant_id + review/revision) **pointing at a core `form_submission`** for the answer data — not a parallel capture store. `subject_type = project_participant`.

### 4.6 Slicing (each: frontend-first → backend → TDD → E2E → review → merge)
- **Slice 1 — Profiles:** model, admin Resource list/form, tier-1 status, auth fields (no portal), import config, terminology. Reference EMS entity.
- **Slice 2 — Project Types + Projects:** type master data (default eligibility-flow editor on the status canvas, default roles/segments); project instance (create-from-type → materialize scoped eligibility graph); list/form + Flow tab.
- **Slice 3 — Project Participants:** registration join (role/segment/tier-2 eligibility); admin add-one + bulk import (F8); embedded participants list under a Project; fact source + triggerable.

### 4.7 Deferred (designed-for, not built in F4)
Client/Lead/Quotation + Tasks/Checklist → B · Submission wrapper → E · Ticket/Invoice/Payment (+ invoice status entity + bridge FKs) → F · Agenda/Session → G · Event Day/Checkpoint/Badge → H · Participant portal → D + F5.

---

## 5. Backlog spawned
- Multi-role per participant per event (multiple `project_participants` rows).
- Import: inline cell-edit on results page; full undo (before-image capture); custom-field columns (needs custom-field/EAV engine).
- Module Platform: module **suite** with declared inter-module deps (3rd-party building *on* EMS) once one-big-module strains.
- (Confirm IDs + log in `documentation/backlogs/backlog.md` when each plan is written.)
