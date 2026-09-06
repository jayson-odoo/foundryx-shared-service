# 28 - Teams (core table) + omnichannel team assignment, team inbox, assign action

> **Contract:** `28-teams-core-and-omnichannel-assignment-acceptance-criteria.md` (50 ACs). This plan fulfils it.
> **Program:** slice **A8** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gap G13,
> roadmap D4 "CORE `teams` table"). Access-level presets (D5) stay in B1; reports by team stay in A9.
> **Branch:** `sprint-4/28-teams`, worktree `.claude/worktrees/s28`. Lane: backend `:8007` on DB
> `foundryx_service_s28`, frontend `:3006`, `agent-browser --session s28`. Each worktree gets its OWN
> `npm ci` (never a shared `node_modules`).
> **Base:** planned against `origin/main` `d302ea7` (plan 23 + plan 25/A1 content). **Rebase before
> S1:** this slice must branch off `main` AFTER plan 26 (A2) and plan 27 (A3) have merged - its module
> migration is `0011`, its manifest version is `0.5.0`, and S2/S4 write plan-27's
> `conversation_events` and extend plan-27's inbox view rail. See §6 "Merge order".

## 1. Why

respond.io groups users into **Teams** and then uses that grouping everywhere an operator works: a
Team Inbox per team, "assign to a user in a team" with round-robin in the workflow builder, a team
column on the assignment log, and a leaderboard grouped by team. Foundryx has roles and workspace
members but no grouping at all: the only assignment target is a single user, so a thread that nobody
has claimed has no owning group, and every "who should pick this up" answer is manual.

A8 lands teams as a **core** concept (roadmap D4): a team is a grouping of tenant users next to
roles, platform-wide, so any future Service can use it. Omnichannel is the first consumer: it stores
an assigned team on the thread, picks a member by a per-team strategy, exposes a Teams section on the
inbox rail, and gains the assign action the workflow parity slice (A5) will reuse. The module never
touches the core tables directly - it goes through the capability registry, which is also what keeps
"teams" reusable by the next Service without a second implementation.

## 2. Architecture

```
CORE (public schema)                        MODULE (app_omnichannel)
teams(id, tenant_id, name, description,     contacts + assigned_team_id  (plain indexed String,
      is_active, sort_order, ts)                       a CORE team id, no cross-schema FK)
  |                                         team_assignment_settings(workspace_id, team_id,
  +--1:N--> team_members(team_id, user_id,       strategy, last_assigned_user_id)
            tenant_id FROM THE TEAM, role)
                    ^
                    |  capability registry (the ONLY seam)
                    |     team.resolve@1     -> {id, name, isActive} | None
                    |     teams.list@1       -> [{id, name, isActive}]
                    |     teams.members@1    -> [{userId, role, name}] | None
                    |     teams.of_user@1    -> [{id, name}]
                    |
                    +-- reference guard ("team", "conversations", checker)
                        core asks "is this team referenced?" before DELETE -> 409
```

Assignment flows through ONE write seam - `ConversationService.patch_thread` - exactly as plan 25
made the profile patch flow through `ContactProfileService`. The manual drawer assign, the workflow
action, the gateway PATCH and (later) A2's bulk assign all land there, so realtime publish, the
consumer webhook and the plan-27 event row happen once, in one place.

### 2.1 Core pieces (all verified present at `d302ea7`)

| Piece | Where | Notes |
|---|---|---|
| Models | `service_backend/app/models/team.py` (new) | `Team`, `TeamMember`; `UTCDateTime` columns; `TeamMember.tenant_id` is set from the owning `Team`, never from the payload (house rule: an association's `tenant_id` derives from the owning role) |
| Migration | `service_backend/alembic/versions/<rev>_teams_core.py` (new) | `down_revision = "b7c1d2e3f4a5"` (the SINGLE head verified 2026-09-06 by walking every `revision`/`down_revision` in `alembic/versions/`; re-verify at build time). Revision id <= 32 chars, collision-grepped against every existing id incl. the `revision: str = ...` files. Add `import app.models.utc_datetime` by hand. Postgres functional unique index `ix_teams_tenant_name_lower ON teams (tenant_id, lower(name))` created in the migration only; case-insensitive uniqueness is ALSO enforced in the service so the sqlite test path behaves identically |
| Repository | `service_backend/app/repositories/team_repository.py` (new) | `list(tenant_id, q, sort, page, page_size)`, `get(id, tenant_id)`, `by_ids(ids, tenant_id)`, `members_for(team_ids, tenant_id)`, `teams_for_user(user_id, tenant_id)`, `member_user_ids(team_id, tenant_id)`. EVERY method takes `tenant_id` and filters on it - there is no unscoped getter to misuse |
| Service | `service_backend/app/services/team_service.py` (new) | create/update/delete, ci-name uniqueness, member-set replace with per-user tenant validation, lead subset validation, delete guarded by `reference_counts(db, tenant_id, "team", team_id)` -> 409 |
| Router | `service_backend/app/api/v1/teams.py` (new), mounted `app.include_router(teams.router, prefix="/teams", tags=["teams"])` in `app/main.py` next to `roles` | HTTP + Pydantic only. `GET /teams`, `GET /teams/mine`, `GET /teams/{id}`, `POST`, `PATCH`, `DELETE`. `GET /teams/mine` is declared BEFORE `/{id}` so the literal path wins |
| Schemas | `service_backend/app/schemas/team.py` (new) | `TeamItem`, `TeamListResponse`, `TeamCreate`, `TeamUpdate`, `TeamMemberRef` - camelCase wire, datetime-bearing schemas inherit `ApiModel` |
| Permissions | `service_backend/app/permissions/permissions.csv` | two rows: `teams,Teams,read,Read,View teams` and `teams,Teams,manage,Manage,Create, edit and delete teams`. Grant path is the EXISTING core path, no new code: `PermissionService.sync_core()` upserts the rows delete-by-module on the global unique key, then `app.seed.sweep_tenant_admin_grants(db)` (already called by `scripts/bootstrap_db.py` after the permission sync) recomputes `tenant_admin_grant` = core keys + installed-module keys for every non-platform tenant's Admin role |
| Terminology | `service_backend/app/terminology/core_terms.py` | `TermDef("team", "Team", "Teams", group="Access", ...)` next to the existing `role` term |
| Capabilities | `service_backend/app/services/team_capabilities.py` (new) + calls from `app/main.py` lifespan AND from `app/module_loader.py` (`load_modules` and `boot_module_hooks`, both at the head, before module boot) | `ensure_team_capabilities()` is idempotent and registers the four `provider_module="core"` defs. Core is implicitly always active (`module_platform/active.py` returns `{CORE_MODULE} | ...`), so a core capability resolves for every tenant; the None path is "not registered in this process", which is why registration must exist on the worker seam too |

### 2.2 Module pieces (omnichannel)

| Piece | Where | Notes |
|---|---|---|
| Model + migration | `modules/omnichannel/models.py`, `modules/omnichannel/alembic/versions/0011_omni_team_assignment.py` (new) | `Contact.assigned_team_id` (String, nullable, index); `TeamAssignmentSetting` (`id, tenant_id, workspace_id FK workspaces, team_id String idx, strategy, last_assigned_user_id, created_at, updated_at`, unique `(workspace_id, team_id)`). Inspector-guarded like `0004` / `0008`; `bootstrap.create_schema_and_tables` mirrors the column with `ADD COLUMN IF NOT EXISTS assigned_team_id VARCHAR` |
| Teams gateway | `modules/omnichannel/services/team_directory.py` (new) | The module's ONLY door to core teams: `resolve(db, tenant, team_id)` (via `validate_soft_ref` / `resolve_soft_ref` with `SoftRef("core", "team", id)`), `list_active(db, tenant)`, `members(db, tenant, team_id)`, `names(db, tenant, team_ids)` (batched, used by `_thread_items`). Every method returns an empty/None result when `resolve_capability` gives `None` - the self-disable path |
| Assignment | `modules/omnichannel/services/team_assignment_service.py` (new) | `settings_for(ws, team_id)` (default `round_robin`), `eligible_members(...)`, `pick(...)` (see §5.3), `assign(contact, team_id, actor, strategy_override=None)` |
| Write seam | `modules/omnichannel/services/conversation_service.py` | `patch_thread` gains `assigned_team_id: Optional[str] = ...`; the assignee block is reworked per §5.2; `_thread_items` gains one batched `team_directory.names(...)` call; `_publish_contact_updated` unchanged (it already fans out realtime + webhook) |
| Repository | `modules/omnichannel/repositories/contact_repository.py` | `list_threads` gains `team_id: Optional[str] = None` filtering on `Contact.assigned_team_id`, composed with the existing `assignee` filter; ordering unchanged (still ends `Contact.id.asc()`) |
| Routers | `modules/omnichannel/routers/conversations.py` (PATCH accepts `assignedTeamId`, `GET /omnichannel/contacts` accepts `teamId`), `modules/omnichannel/routers/team_settings.py` (new, manifest prefix `/omnichannel/workspaces`) | `assignedTeamId` rides the existing `conversations.assign` gate; embed principals are refused (native-only) |
| Schemas | `modules/omnichannel/schemas.py` | `ThreadItem` += `assignedTeamId`, `assignedTeamName`; `ThreadPatch` += `assignedTeamId`; `RioContactItem` += the same two keys in the Foundryx-extensions block; `TeamAssignmentSettingItem` / `...Update` |
| Events | plan-27 `modules/omnichannel/services/event_service.py` call sites in `conversation_service.patch_thread` | the `assigned` / `unassigned` writes gain `payload={"teamId", "teamName", "assignedVia", "change"}` |
| Workflow node | `modules/omnichannel/workflow_nodes.py`, `modules/omnichannel/services/workflow_actions.py` | new `omnichannel.assign_conversation` `ActionDef` + `omnichannel_assign_conversation` executor |
| Reference guard | `modules/omnichannel/bootstrap.py::register_engine_entities` | `register_reference_guard("team", "conversations", _count_threads_for_team)` - the FIRST production use of `app/module_platform/reference_guards.py` |
| Manifest + hooks | `modules/omnichannel/manifest.json`, `modules/omnichannel/bootstrap.py` | version -> `0.5.0`; the new `team_settings` router declared; `update_tenant` needs NO data backfill (nullable column + empty settings table read correctly); `AppStoreService.update()` re-grants the module catalog as usual; `uninstall_tenant` is already generic over `OmniBase` tables |
| Metadata | `service_backend/app/services/workflow_service.py::metadata` + `app/api/v1/workflows.py` | `include_teams=<caller holds teams.read>` mirrors the existing `include_ai_agents` gate; adds `teams: [{id, name}]` |

### 2.3 Frontend pieces

| Piece | Where |
|---|---|
| Core route | `service_frontend/app/(protected)/user-management/teams/page.tsx`, `teams/[id]/page.tsx`, `teams/new/page.tsx` |
| List config | `app/(protected)/user-management/teams/components/use-teams-list-config.tsx` - a clone of `../users/components/use-users-list-config.tsx` |
| Form | `.../components/use-team-form.tsx` (`ResourceFormConfig`, clone of `use-user-form.tsx`), `team-form-fields.tsx`, `team-schema.ts`, `use-team-actions.tsx`, `paths.ts`, `member-pills.tsx` (wraps the existing `components/platform/overflow-pills`) |
| Services | `services/team-service.{ts,mock,real}.ts` (list, mine, get, create, update, remove) |
| Hooks | `hooks/use-teams.ts`, `hooks/use-my-teams.ts` |
| Types | `types/team.ts` (`Team`, `TeamMemberRef`, `CreateTeamInput`) |
| Menu | `config/menu.config.tsx` - a Teams entry after Roles in `MENU_SIDEBAR`, `MENU_MEGA` and `MENU_MEGA_MOBILE`, each tagged `permission: 'teams.read'` + `termKey: 'team'` |
| Inbox rail | plan-27's `app/(protected)/omnichannel/inbox/components/inbox-view-rail.tsx` gains a Teams section; `hooks/use-conversations.ts` `ConversationFilters` gains `teamId` + URL sync; the below-`lg` View `SearchSelect` gains the same entries |
| Drawer | `components/platform/conversation-drawer/conversation-drawer.tsx` assignee dropdown gains a Teams group (the existing `DropdownMenu` at the header, no new component) |
| Canvas | `components/platform/workflow-canvas/node-config-drawer.tsx` gains a `field.type === 'team'` branch mirroring the `omnichannelChannel` branch at L1062; `types/workflows.ts` `NodeFieldType` += `'team'` and `WorkflowMetadata` += `teams`; `services/workflow-metadata-service.mock.ts` seeds two teams |

Reused unchanged: `components/platform/{resource-list,resource-form,resource-actions,multi-select,search-select,overflow-pills,status-badge}`, `hooks/use-can.ts`, `hooks/use-datetime.ts`, `components/common/require-permission.tsx`, `lib/api-client.ts`.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D-A8-1 | CORE `public.teams` + `public.team_members`; tenant-scoped; name unique per tenant case-insensitively (Postgres functional index + a service-level check); core Alembic revision | Main session 2026-09-06 / roadmap D4. A team is a grouping of core users next to roles, usable by every Service |
| D-A8-2 | Core admin UI = Resource-shell list + form cloned from Users; members via `MultiSelect`; white-label; terminology key `team` | House mandate: never hand-roll a table or form; Users is the reference clone. The terminology registry already carries `role` in group "Access", so `team` fits with no new engine work |
| D-A8-3 | The module consumes teams ONLY through the capability registry (`team.resolve@1`, `teams.list@1`, `teams.members@1`, `teams.of_user@1`) and stores `contacts.assigned_team_id` as a plain indexed String validated at save + resolved tenant-scoped at read | Main session. Keeps the module free of a core-table join, gives a single tenant-scoped resolution point for a polymorphic stored id, and lets teams move house later without touching the consumer |
| D-A8-4 | Team Inbox = a Teams section on the plan-27 view rail (`?team=<id>`, nested Unassigned), plus a Teams group in the drawer assignee picker | Main session. No new inbox surface, no second list query - one repository filter |
| D-A8-5 | No assign action exists today (audit 2026-09-06, see §3.1), so this slice DEFINES `omnichannel.assign_conversation` with `mode = user | team | unassign`, a `team` field type and a strategy override; A5 reuses it | Roadmap G11 needs an Assign step; building it once here avoids A5 re-deriving it |
| D-A8-6 | `assignedTeamId` + `assignedTeamName` on the default gateway shape AND on `?format=rio` (in its Foundryx-extensions block); gateway PATCH accepts the team by ID only | Deviation from the brief, flagged in §8. respond.io has no team field on a contact, but CLAUDE.md's gateway rule is "read shapes stay lossless vs the internal items", and `RioContactItem` already carries an explicit Foundryx-extensions block for exactly this case. By-name would mean auto-creating teams from an API key, which is a governance change, not a parity feature |
| D-A8-7 | Out of scope: access-level presets (B1), reports/leaderboards by team (A9), broadcasts (A4), team membership migration (A6), team-shared saved views, AI-agent assignees (C1) | Main session |
| D-A8-8 | The strategy pick order is deterministic: eligible members sorted by `user_id` ascending, with the persisted `last_assigned_user_id` as the cursor. `least_open` sorts by (open count asc, that same order) so ties are stable and both strategies advance the cursor | A random pick is untestable and produces "why did it skip me" support tickets. A persisted cursor is the only way AC-TEM-21 (rotation survives a restart) can hold |
| D-A8-9 | The cursor row is locked for the duration of a pick (`SELECT ... FOR UPDATE` on `team_assignment_settings`, a no-op under sqlite) and updated in the SAME transaction as the assignment | Two concurrent inbound assignments to one team would otherwise both read the same cursor and pick the same member |
| D-A8-10 | Eligible member = team member AND `WorkspaceMember` of the contact's workspace AND core `User.status == "ACTIVE"` | A team is tenant-wide; a workspace is not. Assigning a thread to somebody who cannot open that workspace's inbox is a dead end |
| D-A8-11 | A team with no eligible member is a SUCCESS: `assigned_team_id` set, `assigned_user_id` NULL, the thread lands in that team's Unassigned queue | Main session D-A8-3. An empty roster must never fail an inbound automation or a workflow run |
| D-A8-12 | Precedence: an explicit `assignedUserId` beats the strategy but must be a member of the team sent in the same PATCH (else 422); assigning a user who is not a member of the thread's CURRENT team clears the team; `assignedUserId: null` keeps the team (Team Unassigned); `assignedTeamId: null` keeps the user | The four combinations are otherwise ambiguous and each of them shows up in the UI. Written as ACs (AC-TEM-25/26) so the behaviour is pinned, not inferred |
| D-A8-13 | `assignedTeamId` is native-only: an embed (external-agent) token gets 403 | Federated assignees are the consumer's own agents; a core team is not a concept the embed contract exposes. Mirrors the plan-25 profile-edit refusal |
| D-A8-14 | Team assignment reuses the existing `conversations.assign` permission; the per-team strategy setting reuses `conversations.read` / `conversations.assign` | Flagged in §8. Adding `team_assignment.manage` would be a fourth key nobody grants; assigning and configuring how assignment picks are the same operator act |
| D-A8-15 | Core team DELETE is guarded by `app/module_platform/reference_guards.py` (409 with per-source counts), not by a cascade or a soft delete | The registry exists for exactly this and has no production consumer yet. A cascade would silently unassign live threads; a soft delete would leave a second "inactive" concept next to `is_active` |
| D-A8-16 | `teams.read` is NOT required to see your own teams: `GET /teams/mine` needs only an authenticated session | An inbox agent must see their Team Inbox entries. Gating it behind an admin read key would make the whole feature invisible to the people who use it (the same reasoning as plan 27's D-A3-11 personal saved views) |
| D-A8-17 | `lead` is a label only in this slice: no permission, no assignment priority | Access levels are B1 (roadmap D5). Storing the role now means B1 does not need a second migration |
| D-A8-18 | Teams live under **User Management**, not Settings: route `/user-management/teams`, menu entry next to Roles | Deviation from D-A8-2's wording, flagged in §8. `Role` sits there, the terminology group is "Access", and the form is a literal clone of the Users form in the sibling folder |
| D-A8-19 | Menu, route, permission and terminology are the ONLY core surfaces this slice adds. No dashboard tile, no team column on the Users list | Keeps the core diff auditable; a Teams column on Users is a backlog candidate |
| D-A8-20 | The rail's "My teams" section KEEPS inactive teams (`/teams/mine` has no `is_active` filter); only WRITE surfaces are active-only - the drawer's Teams group and the team-settings tab skip `!isActive` | Post-approval ruling 2026-09-06. A read filter on a deactivated team's queue is still legitimate (its threads did not vanish), whereas assigning INTO one 422s. A muted "(inactive)" affordance is BL-SS-104 |
| D-A8-21 | Saved views keep dangling `teamIds` by design: `expand()` passes them through and the tenant-scoped `IN` narrows to zero rows - it can never widen. Save-time validation (422) is the only gate | Post-approval ruling 2026-09-06, same rule as the pre-existing `tagIds`/`channelIds` degrade (plan 27 round-3 B11). Pruning at expansion is BL-SS-102 |
| D-A8-22 | The team reference guard has exactly ONE source, `conversations` (`contacts.assigned_team_id`); `team_assignment_settings` rows are configuration, not references, and never block a delete | Post-approval ruling 2026-09-06. A strategy row for a team with no assigned threads must not make the team undeletable; orphan cleanup is BL-SS-103 |

### 3.1 Audit outcome - there is no assign action today (D-A8-5)

Verified in the `s25` worktree on 2026-09-06:

- `service_backend/modules/omnichannel/workflow_nodes.py` registers exactly one trigger
  (`omnichannel.message_received`) and two actions (`omnichannel.get_contact`,
  `omnichannel.send_message`). There is no assign action.
- The `omnichannel_contact` `WorkflowEntity` `writable` whitelist is
  `{first_name, last_name, email, language, country_code, priority}` - `assigned_user_id` is a FACT
  attribute but is deliberately NOT writable, so `entity.update` cannot assign either.
- `ConversationService.patch_thread` (`services/conversation_service.py` L395+) already validates a
  native assignee against `User.tenant_id`, keeps the native and federated assignee columns mutually
  exclusive, and calls `_publish_contact_updated` (realtime + consumer webhook) exactly once.

**Therefore the new action wraps `patch_thread`** rather than writing the column, and
`assigned_user_id` stays out of the `entity.update` whitelist (an assign has side effects that
`entity.update`'s generic setattr path must not acquire).

### 3.2 Audit outcome - the capability seam is core-provided for the first time

`app/module_platform/active.py::active_modules` returns `{"core"} | <active module names>`, so a
`CapabilityDef(provider_module="core", ...)` resolves for every tenant. The existing consumer
example (`app/services/payment_gateway_service.py` resolving `finance.apply_payment_event@1`) is
core-consumes-module; this slice is the first module-consumes-core capability. Nothing in the
registry needs to change - but the registration must run in EVERY process that resolves it, which is
why `ensure_team_capabilities()` is called from the FastAPI lifespan and from both
`app/module_loader.py` entry points (`load_modules` for the API, `boot_module_hooks` for Celery).

## 4. Slices (build order - one Sonnet coder lane each, sequential on the branch)

| Slice | Content | Size | AC ids |
|---|---|---|---|
| **S0 FE mock** | `types/team.ts`, `team-service` trio (mock only), Teams route + list config + form (Members / Leads controls) + actions, menu entries in all three arrays, `hooks/use-teams.ts` / `use-my-teams.ts`; drawer assignee Teams group and rail Teams section against the mock; canvas `team` field type + mock metadata; vitest for every new component; agent-browser smoke at 375 + 1280 | M | 39-43, 45, 48 (mock), 50 (vitest half) |
| **S1 Core BE teams + capability** | models, the core Alembic revision, repository, service, router + `main.py` mount, schemas, permissions CSV rows, `TermDef`, `team_capabilities.py` + the three registration call sites, pytest | M | 01-14, 17, 49 (core half) |
| **S2 Module BE assignment** | migration `0011` + manifest `0.5.0`, `team_directory.py`, `team_assignment_service.py` (both strategies + the locked cursor), `patch_thread` rework, `_thread_items` team names, `list_threads` `teamId`, `team_settings` router, reference guard registration, capability-absent degrade path, pytest | L | 15, 16, 18-30, 49 (module half) |
| **S3 Module BE events + workflow action** | the plan-27 event payload additions on the two assign call sites, `omnichannel.assign_conversation` ActionDef + executor, `workflow_service.metadata` `include_teams`, pytest | M | 31-35 |
| **S4 Gateway + guide** | `ThreadItem` -> default gateway shape, `RioContactItem` extensions, gateway PATCH `assignedTeamId`, **consumer-guide diff in the same commit**, contract-drift tests | S | 36-38 |
| **S5 Wire + E2E** | swap the mocks for real at the service boundary, rail + drawer + saved-view `teamIds` against the real API, WS reconciliation, recorded agent-browser evidence run, Test Execution Report keyed to the AC ids | M | 44-48, 50 |
| **Review** | `reviewer` agent on **Opus** (a new core table + a new core route family + a cross-module seam + a new workflow write path = security-grade), then `/codex-review` | - | - |

S1 must land before S2 (the module cannot resolve a capability that does not exist). S3 depends on
S2's write seam. S4 depends on S2's `ThreadItem`. S0 is independent and should start first so the
UI is reviewable while the backend lands.

## 5. Contracts

### 5.1 Core API (internal, unprefixed - the public gateway is the only `/api/v1` surface)

```
GET    /teams               ?q&sort&page&pageSize  -> {data: TeamItem[], total}   (teams.read)
GET    /teams/mine                                 -> TeamItem[]                  (authenticated)
GET    /teams/{id}                                 -> TeamItem                    (teams.read)
POST   /teams               {name, description?, isActive?, sortOrder?, members[]} (teams.manage)
PATCH  /teams/{id}          {name?, description?, isActive?, sortOrder?, members?} (teams.manage)
DELETE /teams/{id}                                 -> 204 | 409 team_in_use       (teams.manage)

TeamItem      {id, name, description, isActive, sortOrder, members: TeamMemberRef[],
               memberCount, createdAt, updatedAt}
TeamMemberRef {userId, name, email, role}          role = "member" | "lead"
409 body      {error: "team_in_use", counts: {"conversations": 12}}
422 body      {fieldErrors: {name|members|...: "..."}}
```

### 5.2 Module API + the `patch_thread` assignee rules

```
PATCH /omnichannel/contacts/{id}     += assignedTeamId (string | null)      (conversations.assign)
GET   /omnichannel/contacts          += teamId                              (conversations.read)
GET   /omnichannel/workspaces/{wsId}/team-settings          -> TeamAssignmentSettingItem[]
PUT   /omnichannel/workspaces/{wsId}/team-settings/{teamId}  {strategy}      (conversations.assign)

ThreadItem += assignedTeamId: string | null, assignedTeamName: string | null
TeamAssignmentSettingItem {teamId, teamName, strategy, lastAssignedUserId, updatedAt}
```

Assignee resolution inside `patch_thread`, in this order (all inside the ONE existing transaction):

| `assignedTeamId` | `assignedUserId` | Result |
|---|---|---|
| omitted | omitted | unchanged |
| `<id>` | omitted | validate team -> pick by strategy -> set team + picked user (or team + NULL user when the roster has nobody eligible) |
| `<id>` | `<user>` | 422 unless the user is a member of that team; otherwise set both, no strategy pick, cursor untouched |
| `<id>` | `null` | set the team, clear the user (Team Unassigned) |
| `null` | omitted | clear the team, keep the user |
| omitted | `<user>` | set the user; clear `assigned_team_id` when the user is not a member of the currently assigned team |
| omitted | `null` | clear the user, keep the team |

`assigned_external_agent_id` is cleared on any native assignment (existing mutual-exclusion rule).
An embed principal sending `assignedTeamId` gets 403 before any of the above runs.

### 5.3 Strategy algorithm

```
eligible(ws, team) = [ u for u in teams.members@1(team)
                       if u.userId in WorkspaceMember(ws).user_ids
                       and core User(u.userId).status == "ACTIVE" ]
                     sorted by userId asc                       # deterministic order

round_robin: lock the settings row; i = index(cursor) if cursor in eligible else -1
             pick = eligible[(i + 1) % len(eligible)]
least_open:  counts = SELECT assigned_user_id, count(*) FROM contacts
                      JOIN statuses ON contacts.status_id = statuses.id
                      WHERE tenant_id = :t AND workspace_id = :ws
                        AND statuses.key = 'OPEN'
                        AND assigned_user_id IN :eligible
                      GROUP BY assigned_user_id
             pick = min(eligible, key=(counts.get(u, 0), round_robin_position(u)))

both: settings.last_assigned_user_id = pick ; same transaction as the assignment
empty eligible -> pick = None (team assigned, user NULL, cursor untouched)
```

### 5.4 Event payload additions (plan 27 `conversation_events`)

```
assigned    payload_json {teamId, teamName, assigneeKind, assignedVia, change}
unassigned  payload_json {teamId, teamName, assignedVia, change}
assignedVia = "manual" | "team_strategy" | "workflow"
change      = "user" | "team" | "both"
```

`assigned` is written when the thread gains a user and/or a team; `unassigned` only when it loses
BOTH. A no-op PATCH writes nothing (plan-27 AC-IVE-06 stays true).

### 5.5 Workflow action

```
key         omnichannel.assign_conversation
label       Assign Conversation
category    Actions      module omnichannel      destructive False
fields      contactId  text      required  mergeable
            mode       select    required  [user | team | unassign]
            userId     text      show_when ("mode","user")   mergeable
            teamId     team      show_when ("mode","team")
            strategy   select    show_when ("mode","team")    [default | round_robin | least_open]
outputs     assignedUserId, assignedTeamId, assigned (bool)
executor    -> ConversationService.patch_thread(...)   (one write seam; realtime + webhook + event)
```

`metadata.teams` feeds the new `team` NodeField type; the canvas branch mirrors
`omnichannelChannel` (`node-config-drawer.tsx` L1062) and renders a `SearchSelect`.

### 5.6 Consumer guide diff (S4, same commit as any `api_v1.py` / `Rio*` change)

`documentation/omnichannel/consumer-integration-guide.md`: the contact JSON sample (around L699), the
PATCH field list (L372-381), the rio field-mapping table (L839), the `contact.updated` webhook note
(L497) and the endpoint summary row (L1152) all gain the team fields. A diff without this is a
review reject.

## 6. Risks + mitigations

- **Merge order (the biggest one).** A8 sits behind two lanes on the same module. Plan 27 (A3) owns
  `conversation_events` + the view rail; plan 26 (A2) owns `contact_repository.list_contacts`, the
  manifest bump and the previous migration. **Rebase onto `main` after both merge**, then re-check:
  the module migration number (expect `0011`, parent `0010`), the manifest version (expect `0.5.0`),
  the `update_tenant` version guard style (`from_version <` , not an equality), and plan-27's
  `InboxViewFilter` (add `teamIds` and extend its `extra="forbid"` 422 test rather than replacing it).
  If A3 has NOT merged when S3 starts, the event-payload work is blocked - do not invent a second
  events table.
- **Capability None path.** `resolve_capability` returns `None` when the provider is not registered
  in THIS process. Because the provider is core, that can only happen on a boot path that skipped
  `ensure_team_capabilities()` - which is exactly why it is wired into the lifespan AND both
  `module_loader` entry points, and why AC-TEM-15 pins the degrade behaviour (empty pickers, 422 on
  write, ids still round-trip) instead of a 500. Reviewer: reject any `handler(...)` call that is not
  preceded by a `None` check.
- **Polymorphic stored id.** `assigned_team_id` is a stored id resolved into a NAME that is rendered
  to the caller, including on the key-authed public gateway - the exact class that leaked twice
  before. Validation at save (`validate_soft_ref`) and tenant-scoped batched resolution at read
  (`team_directory.names`) are both mandatory; a foreign id must render `null`, never a name.
- **Concurrent picks.** Two inbound assignments to the same team in the same second would both read
  the same cursor. Mitigated by the row lock (D-A8-9); a test drives two sessions against Postgres.
  Under sqlite the lock is a no-op and the test asserts sequential behaviour only.
- **`create_all` never ALTERs.** `contacts.assigned_team_id` needs the `ADD COLUMN IF NOT EXISTS`
  mirror in `bootstrap.create_schema_and_tables`, or every `scripts/init_db` dev database silently
  lacks it while the ORM thinks it exists.
- **Core migration head.** `b7c1d2e3f4a5` was the single head on 2026-09-06; other lanes may add core
  revisions before this one merges. Re-derive the head at build time and never guess a parent.
- **Shared Postgres across worktrees.** Lane s28 owns `foundryx_service_s28`; reseed only from the
  branch you are serving (`sync_permissions` is delete-by-module, so seeding from another branch
  strips this branch's keys).
- **Plan 23 restyle.** The drawer header and the inbox files are restyled on
  `sprint-4/23-design-language-alignment`. Keep new code in new files; the only shared lines are the
  assignee dropdown block and the rail's section array. Never introduce `text-[Npx]`,
  `transition-all` or an unlabelled icon button - those are plan-23 hard-fails.
- **Reference guard is new in production.** `register_reference_guard` has no existing consumer, so
  its behaviour under a real delete is unproven. The 409 path gets a dedicated test with the guard
  registered AND a control test with it absent.

## 7. Backlog candidates (proposed ids - the lane coder registers them in `documentation/backlogs/backlog.md` on close, each linking back to this plan; ids start at 082 because main's max is BL-SS-081 (post plan-26/27 merge))

| Proposed id | Title | Priority |
|---|---|---|
| BL-SS-082 | Teams: per-team saved inbox views shared with the team (needs plan-27 `inbox_views.team_id`) | P1 |
| BL-SS-083 | Teams: a Teams column + filter on the core Users list, and a Teams tab on the user form | P2 |
| BL-SS-084 | Omnichannel: business-hours-aware assignment (skip members outside their working hours) | P1 |
| BL-SS-085 | Omnichannel: capacity-based strategy (max open threads per member, overflow stays Team Unassigned) | P2 |
| BL-SS-086 | Omnichannel: auto-assign an inbound thread to a team by channel or lifecycle rule (no workflow authoring needed) | P1 |
| BL-SS-087 | Teams: import teams + membership through the core import engine (`ImporterDef("teams")`) for the A6 migration | P1 |
| BL-SS-088 | Omnichannel gateway: assign by team NAME with an explicit opt-in flag (never auto-create) | P2 |
| BL-SS-089 | Teams: bulk reassign every thread of a team before deleting it (turn the 409 into a guided migration, like the status engine's `migrate-records`) | P1 |
| BL-SS-090 | Workflow engine: expose the `team` field type to core entities (assign a core record to a team) | P2 |
| BL-SS-091 | Teams: team avatar / colour for the rail and the assignment log | P2 |

**Registered on close (review rounds 1-2 + the post-approval read, 2026-09-06).** Provisional ids in
the worktree `backlog.md` - they are renumbered from main's then-max at merge (A9/A4 land first):

| Registered id | Title | Source |
|---|---|---|
| BL-SS-101 | Teams form Members/Leads picker capped at the first 200 tenant users (no async-options `MultiSelect`) | round 1, nit 17 |
| BL-SS-102 | Saved views: prune unresolvable `teamIds` / `tagIds` / `channelIds` at expansion so a view degrades to no-scope, not no-results | post-approval read |
| BL-SS-103 | Orphan `team_assignment_settings` rows survive a core team delete - cleanup in the `teams.delete` handler or a sweep | post-approval read |
| BL-SS-104 | Rail entry for an inactive "My teams" team is indistinguishable - muted "(inactive)" affordance (see D-A8-20) | post-approval read |
| BL-SS-105 | Full-suite timer flakes `timezone-card` / `resource-form.deferred` (D5 class) | round 2 |
| BL-SS-106 | Plan-27 default agent role: Inbox renders nothing without `workspaces.read` | post-approval read |
| BL-SS-107 | `teamService.remove()` unreferenced by production code after the deferred switch - ruling: keep, the sync `DELETE /teams/{id}` stays the API contract | post-approval read |

## 8. Flagged for the user (planner deviations from the 2026-09-06 decision set - none are blocking)

1. **Menu placement (D-A8-18).** The decision said "Settings -> Teams"; this plan puts Teams under
   **User Management**, next to Roles, at `/user-management/teams`. Reasons: `Role` lives there, the
   terminology registry groups `role` under "Access", the form is a literal clone of the sibling
   Users form, and a team is a grouping of users, not a system setting. Reverting is one route move
   plus three menu entries.
2. **The rio shape DOES get the team fields (D-A8-6).** The decision said "rio only if respond.io
   exposes a team field" - it does not (`RioContactItem` has `assignee` only; only
   `RioMessageSender.teamId` exists, and it is hardcoded `None` today). But CLAUDE.md's gateway rule
   is that read shapes stay lossless versus the internal item, and `RioContactItem` already has an
   explicit "Foundryx extensions (no respond.io equivalent)" block for `cswExpiresAt`, `priority`,
   `unreadCount` and friends. The two team keys go there. Say the word and they are dropped from rio.
3. **No new permission key for the strategy setting (D-A8-14).** Configuring a team's pick strategy
   rides `conversations.assign` rather than a new `team_assignment.manage`. One fewer key nobody
   remembers to grant; if strategies should be admin-only, that is a one-line change.
4. **`GET /teams/mine` needs no `teams.read` (D-A8-16).** Otherwise an Agent-level user cannot see
   their own Team Inbox entries, which is the whole point of the slice. It returns only the caller's
   own teams, so it is a self-read, not a directory.
5. **The four assignee combinations are decided here (D-A8-12).** The decision set covered
   "team + no eligible member" but not "user + team in one call", "user who is not a member of the
   current team", or what `null` on each side clears. The table in §5.2 is the answer; every row is
   an AC so it is easy to overrule.
6. **`lead` carries no behaviour (D-A8-17).** The column is stored so B1 does not need a second
   migration, but nothing in this slice reads it apart from the UI label. If a lead should be
   preferred by the strategy, say so and it is one clause in the sort key.
7. **Team delete is a 409, not a cascade (D-A8-15)**, and it is the first production consumer of
   `app/module_platform/reference_guards.py`. The alternative (unassign every thread on delete) loses
   assignment history silently; BL-SS-089 offers the guided middle ground.
8. **`RioMessageSender.teamId` stays `None`.** Populating it with the sending agent's team would be
   a second, message-level team concept. Out of scope; flagging it because the field already exists
   in the rio shape and a reviewer will notice.
9. **A8 must rebase behind A2 and A3.** The lane brief pins the base at `origin/main` `d302ea7`, but
   the migration number (`0011`), the manifest version (`0.5.0`) and the event + rail work all assume
   plan 26 and plan 27 have merged first. Building on `d302ea7` directly would produce a migration
   parent that does not exist on `main` by merge time.
10. **The `team` NodeField type is a core canvas addition** (`types/workflows.ts` plus one branch in
    `node-config-drawer.tsx`) made from inside a module slice, exactly like `omnichannelChannel` was.
    It is generic, so BL-SS-090 can reuse it for core entities.
