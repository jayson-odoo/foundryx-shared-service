# 25 - Omnichannel contact data model (typed fields, tags, lifecycle on the status engine)

> **Contract:** `25-omnichannel-contact-data-model-acceptance-criteria.md` (43 ACs). This plan fulfils it.
> **Program:** slice A1 of `24-omnichannel-respondio-parity-roadmap.md`. Everything in Phase A hangs
> off this data model, so it lands first and backend-heavy.
> **Branch:** `sprint-4/25-contact-data-model`, worktree `.claude/worktrees/s25` off `origin/main`
> (`3bea800`). The main checkout carries the user's uncommitted docs refactor - never build there.
> Lane ports: backend `:8004` on DB `foundryx_service_s25`, frontend `:3003`, `agent-browser --session s25`.
> **Coordinates with:** plan 23 (design-language alignment, integration branch
> `sprint-4/23-design-language-alignment`) - the drawer and workspace form are restyled there; this
> plan adds new components next to them and accepts the merge cost (grill 2026-09-05).

## 1. Why

respond.io's Inbox, Contacts, Broadcasts, Workflows, Dashboard and Reports all key off three things
a contact carries: typed custom fields, tags and a lifecycle stage. Today our `contacts` row is the
thread with an untyped JSON blob and nothing else. A1 makes the contact a real entity: a
per-workspace field registry with typed validation on every write path, tags, and a lifecycle stage
that is a **scoped status machine** (one graph per workspace) so transitions, notifications, the
`entity.status_changed` workflow trigger and time-in-stage reporting come from the existing engine.

## 2. Architecture

```
app_omnichannel.workspaces ──1:N──▶ contact_fields   (registry, per workspace)
                            ──1:N──▶ contact_tags     (per workspace)
                            ──scope──▶ core statuses / status_transitions
                                       entity_type = omnichannel_contact_lifecycle, scope_id = workspace.id
contacts  + lifecycle_status_id (plain indexed column, core-table id, no cross-schema FK: BL-030)
          + language, country_code
          custom_fields_json[key] validated against contact_fields on EVERY write
contact_tag_links (contact_id, tag_id, tenant_id)
```

Write paths that must validate through ONE service (`ContactProfileService`): internal thread PATCH,
gateway contact PATCH, workflow `entity.update` (A5, whitelist only touches system columns), importer
(A2). Reads that must resolve tenant + workspace scoped: thread items, gateway shapes, webhook
payloads, `_users_by_id`-style lookups (polymorphic stored-id rule).

### 2.1 Backend pieces

| Piece | Where | Notes |
|---|---|---|
| Models | `modules/omnichannel/models.py` | `ContactField`, `ContactTag`, `ContactTagLink`; `Contact.lifecycle_status_id` (String, index), `Contact.language`, `Contact.country_code` |
| Migration | `modules/omnichannel/alembic/versions/0008_omni_contact_model.py` | idempotent (`inspector` guards, like 0004); `bootstrap.create_schema_and_tables` also ADD COLUMN IF NOT EXISTS for the three columns (the create_all deployments) |
| Field registry | `services/contact_field_service.py` + `repositories/contact_field_repository.py` | CRUD, reserved-key + regex + uniqueness + cap checks, `validate_values(workspace_id, partial: dict) -> (clean, fieldErrors)`, delete strips keys via one `UPDATE ... custom_fields_json = custom_fields_json - :key` (Postgres) with a Python fallback for SQLite tests |
| Tags | `services/contact_tag_service.py` | CRUD + `replace_links(contact, tag_ids)`; ids validated against the contact's workspace before any write |
| Lifecycle | `services/lifecycle_service.py` | `seed_graph()` (the seed set as `ScopeSeedStatus` / `ScopeSeedEdge`), `materialize_for_workspace(db, ws)` → `status_engine.scoped.materialize_scope`, `initial_status_id(db, tenant, ws)`, `move(db, contact, to_status_id, actor)` → `status_machine.transition(..., commit=False)`, `moves(db, contact)` → `fireable_edge_ids` |
| Registration | `bootstrap.register_engine_entities` | `register_status_entity(StatusEntity(entity_type="omnichannel_contact_lifecycle", scoped=True, scope_attr="workspace_id", ...))` with `count_records` / `migrate_records` over `Contact.lifecycle_status_id`; `register_workflow_entity(WorkflowEntity("omnichannel_contact", model=Contact, has_status=True, status_attr="lifecycle_status_id", ...))` |
| Contact profile | `services/contact_profile_service.py` | ONE `patch(contact, payload, actor)` used by both routers: system fields → field validation → tags → diff → `emit_entity_event("omnichannel_contact", "updated", changes=...)` before commit |
| Routers | `routers/contact_fields.py`, `routers/contact_tags.py` (mounted under `/omnichannel/workspaces/{id}/...`), `routers/conversations.py` (+ `POST /{id}/lifecycle`, `GET /{id}/lifecycle-moves`, PATCH gains `tagIds`, `language`, `countryCode`), `routers/api_v1.py` (PATCH gains `tags`, `lifecycle`, `language`, `countryCode`) | HTTP + Pydantic only |
| Schemas | `schemas.py` | `ContactFieldItem/Create/Update`, `ContactTagItem/Create/Update`, `LifecycleStage`, `LifecycleMove`, `ThreadItem` += `language`, `countryCode`, `customFields`, `tags[]`, `lifecycle`; `Rio*` mappers read from `ThreadItem` |
| Permissions | `permissions/permissions.csv` | `contacts.read`, `contacts.manage`, `contact_fields.manage`, `contact_tags.manage` |
| Tenant hooks | `bootstrap.install_tenant` (materialize for the default workspace), `update_tenant` (0.1.0 → 0.2.0 backfill), `uninstall_tenant` (delete core status rows for the entity + tenant) | manifest version → `0.2.0` |
| Workspace service | `services/workspace_service.py create()` | materialize in the same unit of work before commit |
| Contact creation | `inbound_service` stitch, gateway create, seed | set `lifecycle_status_id = initial` via `lifecycle_service.initial_status_id` |

### 2.2 Frontend pieces

| Piece | Where |
|---|---|
| Services (trio) | `services/contact-field-service.{ts,mock,real}.ts`, `services/contact-tag-service.{ts,mock,real}.ts`, `services/conversation-service.*` += `moveLifecycle`, `lifecycleMoves`, PATCH fields |
| Hooks | `hooks/use-contact-fields.ts`, `hooks/use-contact-tags.ts`, `hooks/use-lifecycle-moves.ts` |
| Workspace tabs | `app/(protected)/omnichannel/settings/workspaces/components/`: `workspace-lifecycle-tab.tsx` (wraps `EntityFlow` + `useStatusGraph('omnichannel_contact_lifecycle', workspaceId)` exactly like `forms/components/form-flow-tab.tsx`), `workspace-contact-fields-tab.tsx` (+ `contact-field-dialog.tsx`, `contact-field-schema.ts`), `workspace-tags-tab.tsx` (+ `contact-tag-dialog.tsx`); registered in `use-workspace-form.tsx` `tabs` after Members |
| Contact panel | `components/platform/conversation-drawer/contact-panel.tsx` (+ `contact-details-form.tsx`, `lifecycle-move.tsx`, `tag-chips.tsx`); drawer header gets the toggle; `useMediaQuery(min-width: 1280px)` picks pane vs `Sheet` |
| Thread list row | `app/(protected)/omnichannel/inbox/components/thread-list.tsx` += lifecycle badge + tag chips |
| Types | `types/omnichannel.ts` += `ContactField`, `ContactTag`, `LifecycleStage`, `Thread.lifecycle/tags/customFields/language/countryCode` |

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Lifecycle = scoped status entity per workspace, seed materialized at workspace creation, edited on the existing canvas | Grill 2026-09-05; zero new editor code; edge auth + notifications + `status_changed` trigger for free |
| D2 | Won = `is_terminal`, lost = `is_archived`, initial = `is_initial`; no new columns | Explicit won flag chosen by the user; `is_terminal` already blocks outgoing edges. Reports (A9) read the flags |
| D3 | Emoji lives in the stage label text | No icon column on `statuses`; the canvas and badges render it as-is |
| D4 | Conversation status (OPEN / SNOOZED / CLOSED) stays on the module's lightweight `statuses` table | Roadmap D3; migrating it is unrelated to parity |
| D5 | Custom-field values stay in `custom_fields_json`, validated against the registry on write; partial merge semantics; unknown key = 422 | Roadmap D1; no EAV; one JSON read per contact |
| D6 | Field `key` + `type` immutable after create | Type changes would silently invalidate stored values; respond.io behaves the same |
| D7 | Delete field strips values synchronously | Registry caps (100 fields) and per-workspace contact counts keep it bounded; no background job |
| D8 | Tags: internal API by id (`tagIds` replace-set), gateway by name with auto-create | UI knows ids; external consumers speak names (respond.io parity); auto-create is workspace-scoped and capped |
| D9 | New permission resources `contacts`, `contact_fields`, `contact_tags` | None exist in core (grep 2026-09-05); `sync_permissions` is delete-by-module on a global key, so the names must stay unique |
| D10 | Lifecycle canvas keeps the core `statuses.manage` gate | The canvas routes are core; a per-workspace gate would need a new scope-aware dependency (backlog if a customer needs Manager-level lifecycle edits) |
| D11 | Entity events emitted from `ContactProfileService.patch` (one `updated` event with the full diff), lifecycle moves rely on the machine's generic `status_changed` emission | A5 gets Contact Field / Tag / Lifecycle Updated triggers from the existing `entity.*` triggers with entity = `omnichannel_contact`, gated by module visibility |
| D12 | `uninstall_tenant` must also delete the core `statuses` / `status_transitions` rows for `omnichannel_contact_lifecycle` | The generic loop only wipes `OmniBase` tables; without this the tenant would keep orphan graphs |
| D13 | `update_tenant` 0.1.0 → 0.2.0 backfill runs inline (materialize per workspace + one UPDATE per workspace for contacts) | Bounded by workspace count; idempotent by "scope has statuses" check |
| D14 | Contact panel = right pane ≥ 1280 / Sheet below; hidden in compact + embed modes | Embed consumers get their own panel later (backlog); keeps the embed contract untouched |
| D15 | Workflow `entity.update` on `omnichannel_contact` routes through `ConversationService.patch_thread`, which commits mid-run and announces (realtime + `contact.updated` webhook) immediately - including on a no-op re-set of the same value | Accepted trade-off, consistent with `WorkflowEntity.apply_update`'s documented "may commit" contract; a run-scoped deferral would need per-entity transaction plumbing the executor doesn't have today. Follow-up backlogged: suppress no-op fan-out / consider run-scoped deferral |

## 4. Slices (build order)

| Slice | Content | Executor |
|---|---|---|
| **S0 FE mock** | services trio (mock), types, workspace tabs (Lifecycle wraps the real canvas against the existing status-engine mock; fields + tags tabs on mock), contact panel + thread-list badges on mock data; agent-browser smoke at 375 + 1280 | coder (Sonnet, worktree s25) |
| **S1 BE fields + tags** | models, migration 0008, services, routers, permissions, `ContactProfileService.patch` + events, tests (AC-01..12, 22, 23, 28) | coder (Sonnet) TDD |
| **S2 BE lifecycle** | status-entity registration, seed, materialize on create / install, backfill, uninstall cleanup, move + moves routes, `ThreadItem.lifecycle`, tests (AC-13..21, 24) | coder (Sonnet) TDD |
| **S3 BE gateway** | default + rio shapes, gateway PATCH (tags by name, lifecycle), webhook payloads, **guide update in the same commit**, contract-drift tests (AC-25..27) | coder (Sonnet) |
| **S4 Wire + E2E** | swap mocks for real, WS updates, evidence run (AC-29..39, 42, 43), Test Execution Report | coder + tester (Sonnet) |
| **Review** | `reviewer` agent on **Opus** (tenant isolation + polymorphic ids + gateway contract = security-grade review), then `/codex-review` | reviewer |

S1 and S2 can run in parallel lanes on the same branch only if they touch disjoint files; default is sequential (S2 depends on S1's `ContactProfileService`).

## 5. Contracts

### 5.1 Internal API

```
GET    /omnichannel/workspaces/{id}/contact-fields            -> ContactFieldItem[]
POST   /omnichannel/workspaces/{id}/contact-fields            {key,label,description?,type,options?,visibility?} -> 201
PATCH  /omnichannel/workspaces/{id}/contact-fields/{fieldId}  {label?,description?,options?,visibility?,sortOrder?}
DELETE /omnichannel/workspaces/{id}/contact-fields/{fieldId}  -> 204 (strips values)
GET    /omnichannel/workspaces/{id}/contact-tags              -> ContactTagItem[] (+ contactsCount)
POST   /omnichannel/workspaces/{id}/contact-tags              {name,emoji?,color?,description?}
PATCH  /omnichannel/workspaces/{id}/contact-tags/{tagId}
DELETE /omnichannel/workspaces/{id}/contact-tags/{tagId}
GET    /omnichannel/workspaces/{id}/lifecycle                 -> LifecycleStage[] (statusId,key,label,color,sortOrder,isInitial,isWon,isLost,isActive)
PATCH  /omnichannel/contacts/{id}      += language, countryCode, customFields (partial), tagIds (replace)
POST   /omnichannel/contacts/{id}/lifecycle          {toStatusId} -> ThreadItem   (409 lifecycle_move_not_allowed)
GET    /omnichannel/contacts/{id}/lifecycle-moves    -> [{edgeId,toStatusId,label}]
GET    /api/v1/statuses?entityType=omnichannel_contact_lifecycle&scopeId={workspaceId}   (existing core canvas API)
```

`ThreadItem` += `language`, `countryCode`, `customFields: {key: value}`, `tags: [{id,name,emoji,color}]`,
`lifecycle: {statusId,key,label,color,isWon,isLost} | null`. 422 shape = `{fieldErrors: {path: message}}`
with paths `customFields.<key>`, `tagIds`, `language`, `countryCode`.

### 5.2 Public gateway (guide §Contacts, same commit)

Default shape mirrors `ThreadItem`. `?format=rio`: `language`, `countryCode`,
`custom_fields: [{name,value}]`, `tags: [name]`, `lifecycle: label`. PATCH accepts `language`,
`countryCode`, `customFields`, `tags: [name]` (replace, auto-create), `lifecycle: key|label`.
Webhook `contact` objects use the default shape. Contract tests pin every new field in both shapes.

### 5.3 Seed graph (materialized per workspace)

| key | label | flags | color |
|---|---|---|---|
| new_lead | 🆕 New Lead | is_initial, is_default | blue |
| hot_lead | 🔥 Hot Lead | | orange |
| payment | 💵 Payment | | amber |
| customer | 🤩 Customer | is_terminal (won) | green |
| cold_lead | 🧊 Cold Lead | is_archived (lost) | slate |

Edges: mesh among `new_lead` / `hot_lead` / `payment`; each of them → `customer`; each of them →
`cold_lead`; `cold_lead` → `new_lead`. Labels = "Move to <stage>". `trigger_mode = manual`.

## 6. Risks + mitigations

- **Cross-schema id** - `lifecycle_status_id` points at a core-table row from a module table. Plain
  column + app-side integrity (BL-030 pattern); `scope_exists` + tenant filters on every resolve.
- **Canvas for a module entity** - first module-owned scoped entity on the core canvas. The router
  resolves entities via the registry, so registration at module boot is enough; the E2E run proves
  it. If the canvas assumes `module == "core"` anywhere, fix it generically (not a special case).
- **Plan 23 merge** - drawer header + workspace form change on both branches. New code lives in
  new files; only the tab array + header toggle touch shared lines.
- **SQLite tests vs Postgres JSON ops** - value stripping uses a dialect switch; both paths tested.
- **Gateway contract** - the guide diff is part of S3's definition of done; the reviewer must reject
  a `Rio*` / `api_v1.py` diff without it.

## 7. Backlog candidates (register on close)

- Embed-mode contact panel for consumer hosts.
- Workspace-scoped lifecycle edit permission (Manager-level canvas edits).
- Field-level history / audit for custom fields.
- Stage icon column on `statuses` if other entities want emoji outside the label.
