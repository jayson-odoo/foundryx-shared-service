# 28 - Teams (core) + omnichannel team assignment - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/28-teams-core-and-omnichannel-assignment.md`.
> **Program:** slice **A8** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gap G13,
> roadmap decision D4 "CORE `teams` table").
> **Decisions (main session, 2026-09-06):** D-A8-1 core `teams` + `team_members` in `public`,
> D-A8-2 core Resource-shell admin UI, D-A8-3 omnichannel consumes teams through the capability
> registry and stores `contacts.assigned_team_id` with a per-team pick strategy, D-A8-4 Team Inbox
> entries on the plan-27 rail, D-A8-5 a new `omnichannel.assign_conversation` workflow action,
> D-A8-6 gateway exposure of the team on the thread shape.
> **Depends on:** plan 25 (A1) merged; plan 27 (A3) merged for `conversation_events` and the inbox
> view rail; plan 26 (A2) merged for the module manifest / migration chain.
> **Out of scope (D-A8-7):** access-level presets Owner / Manager / Agent (D5, phase B1), reports and
> leaderboards by team (A9), broadcasts (A4), respond.io migration of team membership (A6),
> team-shared saved views beyond the `teamIds` filter key, AI-agent assignees (C1).

IDs: `AC-TEM-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Definitions

- **Team** - a core `public.teams` row: `id`, `tenant_id`, `name`, `description`, `is_active`,
  `sort_order`, `created_at`, `updated_at`. Tenant-scoped, platform-wide, shared by every Service.
- **Team member** - a core `public.team_members` row: `id`, `tenant_id` (derived from the owning
  TEAM, never from the payload), `team_id`, `user_id`, `role` (`member` | `lead`), `created_at`.
- **Lead** - a team member whose `role` is `lead`. Zero or more per team. A lead is a label in this
  slice: it carries no extra permission and no assignment priority (B1 owns access levels).
- **Teams capability** - the core-provided capability family the omnichannel module resolves at
  runtime: `team.resolve@1`, `teams.list@1`, `teams.members@1`, `teams.of_user@1`. Every handler
  tenant-scopes internally and returns `None` / `[]` for a foreign or unknown id.
- **Assigned team** - `app_omnichannel.contacts.assigned_team_id`: a plain indexed String holding a
  CORE team id (no cross-schema FK, the `lifecycle_status_id` / BL-030 pattern). Validated at save
  through `team.resolve@1`, resolved tenant-scoped at read.
- **Eligible member** - a member of the team who is ALSO a `WorkspaceMember` of the contact's
  workspace and whose core `User.status` is `ACTIVE`. Nobody else can be picked by a strategy.
- **Strategy** - how a team assignment picks a user: `round_robin` (default) or `least_open`. Stored
  per (workspace, team) on the module-side `team_assignment_settings` row, keyed by the core team id.
- **Cursor** - `team_assignment_settings.last_assigned_user_id`: the persisted round-robin position.
- **Open thread** - a contact whose THREAD status key is `OPEN` (`SNOOZED` and `CLOSED` do not count).
- **Team Unassigned** - a thread with `assigned_team_id` set and `assigned_user_id` NULL.

---

## Slice A - Core backend: teams + membership

- **AC-TEM-01 [BE]** Given a user with `teams.manage`, when they `POST /teams`
  `{name, description?, isActive?, sortOrder?, members: [{userId, role}]}`, then the team and its
  member rows are stored for the caller's tenant only, `team_members.tenant_id` is copied from the
  TEAM (never read from the payload), and `GET /teams` lists the team with its members.
- **AC-TEM-02 [BE]** Given a create or update payload whose `name` is blank, longer than 120 chars,
  or duplicates an existing team of the same tenant case-insensitively, then the API returns 422
  `{fieldErrors: {name: "..."}}` and nothing is written. Two tenants may hold the same team name.
- **AC-TEM-03 [BE]** Given a `members` list containing a `userId` that does not exist, belongs to
  another tenant, or is a platform-tenant user, then the API returns 422
  `{fieldErrors: {members: "..."}}` and NOTHING is written (no partial team, no partial membership).
- **AC-TEM-04 [BE]** Given a `members` entry whose `role` is not `member` or `lead`, then 422; a team
  may have zero, one or many `lead` members and a lead is always also a member row (one row, one role).
- **AC-TEM-05 [BE]** Given an existing team, when `PATCH /teams/{id}` sends `members`, then the
  membership set is REPLACED in one transaction (adds inserted, removals deleted, role changes
  updated) and a foreign user id in the new set rolls the whole PATCH back.
- **AC-TEM-06 [BE]** Given `DELETE /teams/{id}`, then it returns 204 when no registered reference
  guard reports a usage, and 409 `{error: "team_in_use", counts: {"<source>": n}}` when any guard
  reports a positive count; on 409 nothing is deleted.
- **AC-TEM-07 [BE]** Given a team with `isActive = false`, then it is still readable and editable,
  it is excluded from `teams.list@1` when the caller asks for active only, and it can no longer be
  chosen as an assignment target (422 `assignedTeamId` on the omnichannel PATCH, absent from every
  picker).
- **AC-TEM-08 [BE]** Given `GET /teams`, then it supports `q` (name contains), `sort`
  (`name` | `sortOrder` | `createdAt`), `page`, `pageSize`, returns `{data, total}`, and EVERY query
  is scoped by the tenant from the JWT (never from a query param or body). `GET /teams/mine` returns
  only the caller's own teams and needs an authenticated session but NOT `teams.read`, so an inbox
  agent can render the Team rail.
- **AC-TEM-09 [BE]** Given a tenant B user, when they call any `/teams` route with a tenant A team
  id, then the response is a uniform 404 - never 403, never data, never an existence oracle.
- **AC-TEM-10 [BE]** Given permissions, then `app/permissions/permissions.csv` gains exactly
  `teams.read` and `teams.manage` (collision grep 2026-09-06: core resources are
  `ai_agents ai_traces app_store branding dashboard documents emails events finance forms imports
  integration_logs integrations inventory numbering orders procurement product_categories products
  reports reviews roles rules settings statuses submissions templates terminology users vendors
  workflows` and no module CSV declares a `teams` resource); reads require `teams.read`, writes
  require `teams.manage`, a caller with neither gets 403, and implied-read normalization means
  `teams.manage` alone still passes the read routes.
- **AC-TEM-11 [BE]** Given a tenant that was provisioned BEFORE this slice, when the standard
  bootstrap runs (`PermissionService.sync_core()` then `seed.sweep_tenant_admin_grants(db)` in
  `scripts/bootstrap_db.py`), then its Admin role holds `teams.read` + `teams.manage` without any
  slice-specific grant script, and re-running the bootstrap is a no-op.
- **AC-TEM-12 [BE]** Given the new core Alembic revision, then `alembic upgrade head` creates
  `teams` + `team_members` with the tenant indexes, the `(team_id, user_id)` unique constraint and a
  Postgres functional unique index on `(tenant_id, lower(name))`; `downgrade` drops both cleanly;
  the revision id is <= 32 chars, its `down_revision` is the single head verified at build time, and
  a collision grep over every existing revision id (including files using `revision: str = ...`)
  passed.

## Slice B - Core: capability seam, reference guard, terminology

- **AC-TEM-13 [BE]** Given the API process boots AND given a worker process boots through
  `app.module_loader.boot_module_hooks()`, then `team.resolve@1`, `teams.list@1`, `teams.members@1`
  and `teams.of_user@1` are registered with `provider_module="core"` and resolve for every tenant
  (core is implicitly always active); registration is idempotent across repeated boots.
- **AC-TEM-14 [BE]** Given `teams.members@1` called with a team of the caller's tenant, then it
  returns `[{userId, role, name}]` resolved tenant-scoped; called with an unknown, deleted or
  foreign-tenant team id it returns `None` and never another tenant's users. `team.resolve@1` returns
  `{id, name, isActive}` or `None` under the same rules. Amended 2026-09-06 (review round 1): the
  omnichannel module's actual save-time gate is `team_directory.validate_assignable` (`modules/
  omnichannel/services/team_directory.py`) - it resolves the SoftRef via `resolve_soft_ref` (through
  `team_directory.resolve`) AND additionally requires `isActive` (`resolve_active`), so a valid-but-
  inactive team is rejected at save just like an unknown/foreign one; it does not call the generic
  `validate_soft_ref` helper directly.
- **AC-TEM-15 [BE]** Given the teams capability is NOT registered (a boot path that never ran the
  core registration), then every omnichannel team code path degrades instead of failing: no 500, the
  team pickers return empty, an attempt to set `assignedTeamId` returns 422, and an already stored
  `assigned_team_id` still round-trips as an id with a `null` name.
- **AC-TEM-16 [BE]** Given the omnichannel module boots, then it registers a reference guard
  `("team", "conversations", checker)` whose checker counts, tenant-scoped, the contacts holding that
  `assigned_team_id`; a tenant with no such threads yields 0 so the core delete succeeds, and a
  broken checker never wedges the delete decision.
- **AC-TEM-17 [BE]** Given terminology, then `TermDef("team", "Team", "Teams", group="Access")` is
  registered in the core registry, `GET /terminology` returns it, and a tenant override relabels
  every core Teams surface including the menu entry and the list/form headers.

## Slice C - Module backend: team assignment + strategies

- **AC-TEM-18 [BE]** Given the module migration `0011_omni_team_assignment`, then it adds
  `contacts.assigned_team_id` (String, nullable, indexed) and creates `team_assignment_settings`
  (`id`, `tenant_id`, `workspace_id`, `team_id`, `strategy`, `last_assigned_user_id`, `created_at`,
  `updated_at`; unique `(workspace_id, team_id)`); it is inspector-guarded and idempotent, its
  `down_revision` is the module head on `main` at build time, `bootstrap.create_schema_and_tables`
  mirrors the column with `ADD COLUMN IF NOT EXISTS`, and the manifest version becomes `0.5.0`.
- **AC-TEM-19 [BE]** Given `PATCH /omnichannel/contacts/{id}` with `{assignedTeamId}` by a caller
  holding `conversations.assign`, then the id is validated through the teams capability and an
  unknown, foreign-tenant or inactive team returns 422
  `{fieldErrors: {assignedTeamId: "..."}}` with nothing written.
- **AC-TEM-20 [BE]** Given a valid team assign with strategy `round_robin`, then the service picks the
  next eligible member AFTER the persisted cursor in a deterministic order, sets `assigned_team_id`
  AND `assigned_user_id`, clears `assigned_external_agent_id`, and advances + persists the cursor in
  the SAME transaction as the assignment.
- **AC-TEM-21 [BE]** Given a team with three eligible members, when four team assignments happen in
  sequence, then the picked users are A, B, C, A; the rotation is read from the stored cursor, so a
  fresh service instance (new process / new session) continues the rotation instead of restarting it.
- **AC-TEM-22 [BE]** Given strategy `least_open`, then the picked member is the eligible member with
  the fewest OPEN threads in THAT workspace counted tenant-scoped (SNOOZED and CLOSED threads, other
  workspaces and other tenants are excluded); ties are broken by the same deterministic order the
  round-robin uses and the cursor still advances.
- **AC-TEM-23 [BE]** Given a team member who is not a `WorkspaceMember` of the contact's workspace, or
  whose core user is not `ACTIVE`, then no strategy ever picks them, in either strategy. Amended
  2026-09-06 (review round 1): "active" means core `User.status == ACTIVE` **AND** `User.is_trashed
  is False` - a trashed user is never eligible even if their status column still reads `ACTIVE`.
- **AC-TEM-24 [BE]** Given a team with NO eligible member, when a thread is assigned to it, then the
  call succeeds (200), the thread is stored team-assigned with `assigned_user_id` NULL, and it appears
  in that team's Unassigned queue. This is not an error path.
- **AC-TEM-25 [BE]** Given one PATCH carrying BOTH `assignedUserId` and `assignedTeamId`, then the
  explicit user wins over the strategy iff that user is a member of that team; otherwise 422
  `{fieldErrors: {assignedUserId: "..."}}`. Given a PATCH carrying only `assignedUserId` for a user
  who is NOT a member of the thread's currently assigned team, then `assigned_team_id` is cleared.
- **AC-TEM-26 [BE]** Given `assignedUserId: null`, then only the user assignee clears and the team
  stays (Team Unassigned). Given `assignedTeamId: null`, then only the team clears and the user
  assignee stays.
- **AC-TEM-27 [BE]** Given an embed principal (external-agent token), then sending `assignedTeamId`
  returns 403 (teams are a native-only surface in this slice) and the existing external-agent assign
  path is unchanged.
- **AC-TEM-28 [BE]** Given `GET /omnichannel/workspaces/{wsId}/team-settings` and
  `PUT /omnichannel/workspaces/{wsId}/team-settings/{teamId} {strategy}`, then read requires
  `conversations.read`, write requires `conversations.assign`, the default when no row exists is
  `round_robin`, a strategy outside the enum returns 422, and a team id that fails `team.resolve@1`
  returns 404. Amended 2026-09-06 (review round 1, finding 4/5/6): the GET now returns one row per
  ACTIVE core team (resolved via `team_directory.list_active`, capability `teams.list@1` - no
  `teams.read` permission needed), not just previously-configured rows, so a `conversations.read`
  holder without `teams.read` can still populate the full team-assignment tab; each row carries
  `isConfigured` and a nullable `updatedAt` (null for a never-configured team).
- **AC-TEM-29 [BE]** Given any thread read (list, detail, gateway, webhook payload), then
  `ThreadItem` carries `assignedTeamId` and `assignedTeamName`; the name is resolved through the
  tenant-scoped capability in ONE batched call per list render, and a stale, deleted or foreign team
  id renders `assignedTeamName: null` - never another tenant's team name.
- **AC-TEM-30 [BE]** Given `GET /omnichannel/contacts?teamId=<id>`, then the list filters on
  `assigned_team_id` within the tenant + workspace scope; combined with `assignee=unassigned` it
  returns exactly that team's Unassigned queue; an unknown or foreign team id returns an empty page
  (never 404, never an existence oracle) and every ordering still ends with `Contact.id.asc()`.

## Slice D - Module backend: events + workflow action

- **AC-TEM-31 [BE]** Given an assignment change, then the plan-27 `conversation_events` row carries
  the team: `assigned` when the thread gains a user and/or a team, `unassigned` when it loses BOTH;
  `payload_json` carries `teamId`, `teamName`, `assignedVia` (`manual` | `team_strategy` |
  `workflow`) and `change` (`user` | `team` | `both`). A PATCH that re-sends the same team and the
  same assignee writes no event.
- **AC-TEM-32 [BE]** Given the module boots, then the action `omnichannel.assign_conversation` is
  registered with fields `contactId` (mergeable, required), `mode` (`user` | `team` | `unassign`),
  `userId` (`show_when` mode = user), `teamId` (`show_when` mode = team, new `team` field type) and
  `strategy` (`show_when` mode = team, optional override), outputs `assignedUserId`,
  `assignedTeamId`, `assigned`; the executor routes through `ConversationService.patch_thread` so the
  realtime push, the consumer webhook and the event row all happen exactly as on the manual path.
- **AC-TEM-33 [BE]** Given a tenant without the omnichannel module active, then the action is absent
  from the workflow catalog and the event-bus match (the `active_modules` filter), and a run can
  never assign a contact belonging to another tenant.
- **AC-TEM-34 [BE]** Given `GET /workflows/metadata`, then it exposes `teams: [{id, name}]` for the
  caller's tenant so the `team` NodeField renders a `SearchSelect`; a caller without `teams.read`
  receives an empty list (an empty picker, never another tenant's teams).
- **AC-TEM-35 [BE]** Given a workflow run with `mode = team` on a team with no eligible member, then
  the run SUCCEEDS with `assigned = false`, `assignedTeamId` set and `assignedUserId` null - a team
  with an empty roster never fails a workflow.

## Slice E - Public gateway + consumer guide

- **AC-TEM-36 [BE]** Given the default gateway shapes (`GET /api/v1/omnichannel/contacts`,
  `GET /api/v1/omnichannel/contacts/{identifier}`, the `contact` object inside
  `contact.updated` webhook deliveries), then they carry `assignedTeamId` and `assignedTeamName`
  derived from the same internal `ThreadItem` (one data path).
- **AC-TEM-37 [BE]** Given `?format=rio`, then `RioContactItem` carries `assignedTeamId` and
  `assignedTeamName` in its Foundryx-extensions block (the read shape stays lossless versus the
  internal item; respond.io has no team field on a contact, so these are extensions, not parity
  fields). Given gateway `PATCH /api/v1/omnichannel/contacts/{identifier}`, then it accepts
  `assignedTeamId` BY ID ONLY - never by name, never auto-creating a team - and an unknown id is 422.
- **AC-TEM-38 [BE] [T]** Given any `api_v1.py` / `Rio*` diff in this slice, then the SAME commit
  updates `documentation/omnichannel/consumer-integration-guide.md` (contact shape, PATCH field
  table, the rio field-mapping table, the `contact.updated` trigger note) and the contract-drift
  tests in `tests/test_omnichannel_api_gateway.py` pin the two new keys in BOTH shapes.

## Slice F - Frontend: core Teams admin surface

- **AC-TEM-39 [FE]** Given `teams.read`, then the Teams list is a Resource-shell list cloned from
  Users (`ResourceListConfig` via `useTeamsListConfig`) with columns Name, Description, Members,
  Status, Created; search, sort, filter and pagination are served by the API; row click opens the
  team form; no hand-rolled table exists anywhere in the diff.
- **AC-TEM-40 [FE]** Given the team form, then it is a `ResourceFormConfig` (Users clone) whose
  Members control is the existing `MultiSelect` over the tenant's users and whose Leads control only
  ever offers the users currently selected as Members (foolproof-UI: a picker never offers an invalid
  option); removing a member removes them from Leads; unsaved edits hit the shell's dirty-guard
  AlertDialog.
- **AC-TEM-41 [FE]** Given the menu, then a Teams entry sits next to Roles in `MENU_SIDEBAR`,
  `MENU_MEGA` and `MENU_MEGA_MOBILE`, each tagged `permission: 'teams.read'` and `termKey: 'team'`;
  a user without `teams.read` sees it in none of the three surfaces.
- **AC-TEM-42 [FE]** Given a user with `teams.read` but not `teams.manage`, then the list and form
  render read-only (no Add, no row actions, no Save) via `useCan`, and a delete blocked by a
  reference guard surfaces the per-source counts as the FAILED deferred-action toast's message.
  No instructional or hint copy appears on any Teams surface, and no tenant-facing string
  says "Dreamz".
  - **Amended 2026-09-06 (review round 1, finding 3; round 2 N2):** team delete is a deferred
    action (`teams.delete`, destructive grace window), not a confirmation dialog. The destructive
    call fires at COMMIT (end of the window, or "run now"); a reference-guard hit (`TeamInUse`)
    lands as a `failed` pending-action row whose `error_text` carries the per-source counts
    ("This team is still assigned to 3 contacts and cannot be deleted."), surfaced by the shared
    deferred toast's `onFailed`. Nothing is deleted on a guard hit, and Cancel inside the window
    fires no call at all.
- **AC-TEM-43 [FE]** Given every Teams surface, then it is verified at ~375px AND ~1280px: the list
  scrolls without horizontal overflow, the form fields stack, and the MultiSelect popover stays
  inside the viewport at both widths.

## Slice G - Frontend: Team Inbox + assign-to-team

- **AC-TEM-44 [FE]** Given the plan-27 inbox view rail at >= 1024px, then it gains a **Teams**
  section listing the caller's teams (from `GET /teams/mine`) plus an **All teams** entry for holders
  of `teams.read`; each team entry has a nested **Unassigned** entry; selecting one sets
  `?team=<id>` (plus `&assignee=unassigned`) in the URL so a reload restores it. Below 1024px the
  same entries appear inside the plan-27 View `SearchSelect` - no new layout is introduced.
  - **Amended 2026-09-06 (review round 1, finding 4/5/6; round 2 N3):** "All teams" was originally
    pinned to `conversations.assign`, but its data source `GET /teams` is gated `teams.read`
    server-side, so the group is gated on `teams.read` (never offer a control that will 403).
    `conversations.assign` still gates the assign WRITE (`PATCH {assignedTeamId}`, the drawer's
    Teams group), and "My teams" (`GET /teams/mine`, authenticated-only) needs neither.
- **AC-TEM-45 [FE]** Given the conversation drawer assignee dropdown, then it gains a **Teams** group
  under the existing member list; picking a team sends `assignedTeamId` and the header then shows the
  team name plus the resolved member, or the team name plus "Unassigned" when no member was eligible.
- **AC-TEM-46 [FE]** Given a saved inbox view, then `InboxViewFilter` gains `teamIds?: [id]`
  validated against the tenant at save time; views saved before this slice keep working unchanged and
  `extra="forbid"` still 422s an unknown key.
  - **Implementation note (review round 1, finding 9):** each id validates through the module's
    `team_directory.resolve` (core `team.resolve@1`, tenant-scoped) in `InboxViewService.
    _validate_filter_ids`, mirroring every other embedded id on this filter. `ContactRepository.
    list_threads` gains `team_ids: Optional[List[str]]` alongside the existing singular `team_id`
    (an `IN` filter, mutually exclusive with the singular one); the thread-list route merges them
    with the SAME override rule AC-IVE-17 uses for every other dimension - an explicit `?teamId=`
    query param always wins, a saved view's `teamIds` only applies when none was sent. The rail
    captures the currently-selected team (if any) into `teamIds: [teamId]` when a view is saved
    (the rail only ever selects ONE team at a time - `teamIds` is plural for forward-compatibility,
    not because the UI can pick several today), and `expandViewFilter` restores `filters.teamId`
    from `teamIds[0]` on reload/re-selection.
- **AC-TEM-47 [FE]** Given a team assign, then the thread row, the rail counts (if present) and the
  drawer header update over the existing `contact.updated` WS push with no manual refresh; a 422
  reverts the optimistic state and shows the server message.
- **AC-TEM-48 [FE]** Given the inbox with the Teams section, then it is verified at ~375px AND
  ~1280px, and the plan-23 hard-fails are respected in every new file (no `text-[Npx]`, no
  `transition-all`, no unlabelled icon button, no raw CSS or `<style>`).

## Slice H - Tests + evidence

- **AC-TEM-49 [T]** pytest covers: team CRUD + ci-unique name + member validation rollback + member
  `tenant_id` derivation, delete 204 / 409 via the reference guard, `GET /teams/mine` without
  `teams.read`, tenant isolation on every `/teams` route, permission 403 matrix, migration
  upgrade/downgrade, capability resolution in an API boot AND a `boot_module_hooks()` boot,
  foreign-tenant capability calls returning None, the capability-absent degrade path, round-robin
  rotation across THREE fresh service instances, `least_open` counting only OPEN threads of that
  workspace and tenant, eligibility filtering (non-member of the workspace, inactive user), the
  empty-roster team-assigned path, user-vs-team precedence and the clearing rules, embed 403,
  team-settings CRUD, `teamId` list filter + pagination ordering, event payload contents, the
  workflow action (registration, module gating, cross-tenant refusal, empty-roster success), and the
  gateway default + rio shapes plus the guide-drift test.
- **AC-TEM-50 [T] [E2E]** vitest covers: teams list config columns, team form Leads-options-derive-
  from-Members, permission-gated read-only rendering, the rail Teams section (selection -> query
  params -> URL), the drawer Teams group, and the optimistic-revert on 422. The recorded
  agent-browser run (dedicated timestamped tenant, real clicks from `/`, evidence at 375 AND 1280
  under `documentation/plans/sprint-4/28-evidence/<slice>/` with a README run log) is: sign in ->
  User Management -> Teams -> create "Support <ts>" with two members and one lead -> open the team ->
  edit members -> Inbox -> open a thread -> Assign -> Teams -> "Support <ts>" -> header shows the
  team + a member -> rail Teams section shows "Support <ts>" -> click it -> the thread is listed ->
  click its Unassigned entry -> empty -> unassign the user from the drawer -> the thread now appears
  under Unassigned -> reload keeps the view from the URL -> a second tenant's session sees neither
  the team nor the thread (API probe returns 404 / empty) -> a tenant without `teams.read` has no
  Teams menu entry in any of the three menu surfaces.
