# Sprint 2 · Plan 01 - Status & State-Machine Engine

**Branch:** `sprint-2/status-engine`
**Closes/advances:** BL-027 (status engine). First of the four-engine foundation (BL-024 Template, BL-025 Workflow, BL-026 Rule are downstream).
**Defers (new backlog items):** BL-037 omnichannel migration, User.status migration, in-app notification inbox, node-canvas reuse for Workflow engine.

---

## Context

The repo already ships a thin core `statuses` table (plan 07) used only for tenant lifecycle, where **code branches on a fixed `category` enum** ("behavior binds to category, never label"). The product needs a real, tenant-configurable **state machine**: arbitrary statuses per entity, a branching transition graph, per-transition authorization, and notify-on-transition - reused across every domain table that has a status. This is the first of the four platform engines.

User intent (grilled to ground): maximum tenant flexibility (define any states), drag-reorder (no manual sort numbers), branching flows (one state → many, with loop-backs), per-transition role-gating, and **notification on transition handled by the engine itself** (no per-transition workflow authoring). UX is the top priority - a visual graph canvas, reusable later for the Workflow engine.

### Locked design decisions (from grilling)

1. **Scope = Status engine core + notify-on-transition dispatch (EMAIL only).** Workflow/Rule/Template engines remain separate future plans. In-app notifications are modeled but not dispatched.
2. **No `category` branching.** Flexibility is unlimited; behavior is **boolean trait flags** on the status row, never a named enum. Existing tenant lifecycle code is rewritten off `category`.
3. **Entity binding via a code-side registry** (like permissions.csv), flat `entity_type`, `status_id` FK on each table. UI entity picker is registry-driven.
4. **Strict transition graph, no wall-cut.** Status change only along a defined edge. Back = reverse edge. Branching (fan-out/fan-in/loops) is native. No wildcards, no self-loops, no admin override.
5. **Edge authorization = role list on the edge** (`transition_roles` M2M). `statuses.manage` gates who *configures*; edge roles gate who can *fire*.
6. **Notifications decoupled & generic.** Transition *references* a notification spec; recipients = polymorphic `USER` / `ROLE` / `DYNAMIC(actor|assignee|owner)`. Dispatch = email via plan-09 outbox + inline merge-field template. `IN_APP` channel modeled inert.
7. **Two-tier: platform defaults + tenant fork-per-entity override.** Platform seeds defaults (`tenant_id NULL`); a tenant forks the whole set for an entity on first edit (`tenant_id` set) which then overrides. System rows: label/color/order editable, behavior/key/delete locked.
8. **Validation:** block hard-delete if referenced → offer deactivate + migrate-records action; edits are forward-looking; `sort_order` is display-only; batch reorder endpoint.
9. **Migration scope this plan = engine + Tenant only.** Omnichannel (BL-037) and User.status = follow-up.
10. **UX = visual node-graph canvas** (`@xyflow/react`), built generic for Workflow-engine reuse, + companion plain Resource list.

---

## Data model (core `public`, Alembic migration)

### `statuses` (extend existing - `app/models/status.py`)
Add columns; keep `category` **nullable + cosmetic only** (no code branches on it anymore):
- `is_initial` Bool, `is_terminal` Bool, `is_active` Bool (default true)
- behavior flags: `blocks_access` Bool, `is_archived` Bool, `is_default` Bool
- `position_x` Float, `position_y` Float (canvas layout; nullable)
- keep: `entity_type`, `key`, `label`, `color`, `sort_order`, `is_system`, `tenant_id` (NULL=platform)
- unique `(entity_type, tenant_id, key)` stays.

### `status_transitions` (new)
- `id`, `entity_type`, `tenant_id`
- `from_status_id` FK → statuses, `to_status_id` FK → statuses
- `label` (button text: "Approve"/"Reject"/"Resubmit")
- `sort_order` (button ordering)
- constraint: `from != to`; `to` not allowed if `from.is_terminal`.

### `transition_roles` (new, M2M)
- `transition_id` FK, `role_id` FK, `tenant_id`. Actor must hold ≥1 to fire.

### `notification_specs` (new - generic, NOT transition-owned)
- `id`, `tenant_id`, `channel` enum (`EMAIL` | `IN_APP`), `template_subject`, `template_body` (inline merge fields), `template_key` (loose string, for future Template engine).

### `notification_spec_transitions` (link) + `notification_recipients` (new)
- transition → notification_spec link (a transition references N specs).
- recipients: `spec_id`, `target_type` (`USER`|`ROLE`|`DYNAMIC`), `target_id` (nullable), `dynamic_key` (`ACTOR`|`ASSIGNEE`|`RECORD_OWNER`).

> Two-tier resolution: reads for an entity_type return tenant rows if any exist for that entity_type, else platform (`tenant_id NULL`) rows.

---

## Backend (`service_backend/`)

- **Entity registry** - `app/status_engine/registry.py`: `STATUS_ENTITIES` list (`entity_type`, `label`, owning module, default-status seed, required-semantic hints). Core registers `tenant`. Module-extensible (modules append at install, mirroring permissions.csv pattern). Backs `GET /status-entities`.
- **Models** - extend `app/models/status.py`; add `status_transition.py`, `notification_spec.py`, etc. to `app/models/`.
- **Migration** - Alembic autogen revision (`alembic/versions/`), env already wired to `Base.metadata`. Backfill: seed platform-default statuses + tenant lifecycle flags (`active.is_initial=true`, `suspended.blocks_access=true`, `archived.is_terminal=true & is_archived=true`).
- **Repositories** - `repositories/status_repository.py`, `status_transition_repository.py` (pure SQLAlchemy, tenant-scoped, two-tier resolution).
- **Services**
  - `services/status_service.py` - status/transition/notification CRUD, reorder, deactivate, migrate-records, two-tier fork-on-edit, validation (graph warnings; terminal-with-outgoing = block; block-delete-if-referenced).
  - `services/status_machine.py` - **the shared executor**: `transition(entity_type, record, to_status_id, actor)` → resolve edge (strict) → check edge roles → write `status_id` → dispatch notifications → `emit("StatusTransitioned", payload)`.
  - `services/notification_dispatch.py` - resolve recipients (incl. DYNAMIC) → render inline template → enqueue to plan-09 `email_outbox` (EMAIL only; IN_APP = no-op + log).
- **Event seam** - `app/events.py`: minimal in-process emit/subscribe. `StatusTransitioned` emitted, no subscribers yet (Workflow engine plugs in later).
- **Routers** - `api/v1/statuses.py`: status/transition/notification CRUD, `GET /status-entities`, `POST /statuses/reorder` (batch), `POST /statuses/{id}/migrate-records`. Thin per-entity transition endpoints delegate to `status_machine` (e.g. tenant transition in `api/v1/tenants.py`).
- **Permissions** - add to `app/permissions/permissions.csv`: `statuses.read`, `statuses.manage`. Re-grant Admin at seed.
- **Tenant lifecycle rewrite** - replace every `category`-based branch (login gating, suspend/archive checks) with flag reads (`status.blocks_access`, `status.is_archived`). Grep `TENANT_STATUS_SUSPENDED`/`ARCHIVED`/`category` in `app/services/`, `app/dependencies.py`, tenant service/repo.

## Frontend (`service_frontend/`)

- **Dep:** `@xyflow/react` (v12, React 19-safe), `npm i --force`.
- **Generic canvas** - `components/platform/flow-canvas/` (`<FlowCanvas>`): nodes, edges, drag-create edges, node/edge selection → drawer. Built generic so the Workflow engine reuses it.
- **Status-engine pages** - `app/(protected)/platform/status-engine/`:
  - entity selector (from `GET /status-entities`) → loads that entity's graph.
  - canvas: node = status (drawer: label/color/flags), edge = transition (drawer: label, roles via `MultiSelect`, notification specs sub-form: channel, recipients, inline template).
  - companion **Resource list** (`useStatusesListConfig`) for tabular scan/export/display-reorder via existing `DataGridTableDndRows`.
- **Services** - `services/status-engine-service.ts` (+ `.real.ts`) through `lib/api-client` (JWT + tenant + impersonation headers automatic).
- **Status registry** - statuses now dynamic (from API), so `StatusBadge` consumes server-provided `{label,color}` instead of a hardcoded registry for engine-driven entities (keep static registries for not-yet-migrated entities).
- **Menu** - two surfaces in `config/menu.config.tsx`: operator defaults under **Platform** (`platformOnly`), tenant under **Settings**. Gate with `statuses.read` / `statuses.manage` + `<RequirePermission>`.

---

## TDD

- **Backend (pytest):** registry resolution; two-tier fork+override; strict transition reject (no edge); edge-role auth (allow/deny); branching (fan-out + loop-back); block-delete-if-referenced → deactivate → migrate-records; flag-based tenant suspend/archive (login blocked when `blocks_access`); notification recipient resolution (USER/ROLE/DYNAMIC) + email enqueued to outbox; `StatusTransitioned` emitted.
- **Frontend (Vitest + RTL):** canvas renders nodes/edges from data; edge-create writes transition; drawer validation; terminal node has no outgoing handle; permission gating hides manage controls.
- **E2E (Playwright, real clicks):** operator opens Status Engine → picks entity → adds statuses → draws Pending→Approved + Pending→Rejected + Rejected→Pending → sets edge roles + email notification → fires a transition as a permitted user (allowed) and a non-permitted user (blocked) → verify email enqueued. Test Execution Report per orchestration guide §6.

---

## Verification (end-to-end)

1. `python -m scripts.bootstrap_db` (migration + seed); `uvicorn app.main:app --reload --port 8001`.
2. `python -m pytest -q` green.
3. Frontend: `npm i --force` (adds `@xyflow/react`), `npm run build && npm start`.
4. Manual: log in as Admin → Platform ▸ Status Engine → build the Pending/Approved/Rejected graph on a test entity → confirm strict enforcement (no arrow = no move), role-gated fire, and email lands in `email_outbox`.
5. Confirm tenant suspend/archive still gates login (flag-driven, category removed).

---

## Follow-up backlog (log in `backlog.md`)

- **BL-037** omnichannel `statuses` → core engine migration (3 entity_types).
- User.status enum → engine adoption.
- In-app notification inbox (channel `IN_APP` dispatch + bell UI).
- Node-canvas reuse for Workflow engine (BL-025).
- Template engine (BL-024) swaps the inline renderer; backfill `template_key`.
