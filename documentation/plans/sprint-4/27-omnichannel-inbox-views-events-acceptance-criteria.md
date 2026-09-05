# 27 - Omnichannel inbox views, conversation actions, conversation events - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/27-omnichannel-inbox-views-events.md`.
> **Program:** slice **A3** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0), and the
> **A9 prerequisite** (`omni_conversation_events`, roadmap D9 - A1 was meant to design it and did
> not, so A3 owns it).
> **Decisions (main session 2026-09-06):** D-A3-1 events table lives here, D-A3-2 view rail +
> saved views, D-A3-3 close reasons + notes, D-A3-4 reuse the existing internal-note path,
> D-A3-5 Shortcut button on a generic `entity.shortcut` trigger, D-A3-6 permission keys,
> D-A3-7 out of scope. See the plan's Decisions table for D-A3-8..D-A3-13 (planner additions).
> **Base:** `main` after the A1 merge (plan 25). No dependency on A2 beyond an optional reserved
> `segmentId` column. Lane: branch `sprint-4/27-inbox-views-events`, worktree `.claude/worktrees/s27`,
> backend `:8006` on DB `foundryx_service_s27`, frontend `:3005`, `agent-browser --session s27`.
> **Out of scope (later slices):** teams / team inbox (A8), dashboard + reports (A9), broadcasts
> (A4), collaborators + @mentions (B1/B2), auto-close beat job + AI closing notes (B2, roadmap G17),
> assign-to-team / assign-to-AI (A8/C1), advanced nested filter groups on the rule engine (A2/B1),
> plan 23 visual restyle.

IDs: `AC-IVE-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Definitions

- **Thread** - the `app_omnichannel.contacts` row (contact = thread). Its **conversation status** is
  the module's lightweight `statuses` table, scope `THREAD`, keys `OPEN` / `SNOOZED` / `CLOSED`
  (roadmap D3 - unchanged by this slice).
- **Event** - one append-only `app_omnichannel.conversation_events` row (the roadmap's
  `omni_conversation_events`; the module schema already namespaces, so the table name carries no
  `omni_` prefix - D-A3-8). Event types: `opened`, `closed`, `reopened`, `snoozed`, `unsnoozed`,
  `assigned`, `unassigned`, `first_agent_reply`, `lifecycle_changed`, `comment_added`.
- **Close reason** - a per-workspace `close_reasons` row (`name`, `sortOrder`, `isActive`). Seeded
  set: General Inquiry, Sales Inquiry, Payment Issue, Others.
- **Saved view** - an `inbox_views` row: `name`, `ownerUserId`, `isShared`, typed `filter` JSON,
  reserved `segmentId`. NOT a rule-engine tree (D-A3-2).
- **View rail** - the inbox left rail: All / Mine / Unassigned, then one entry per lifecycle stage
  (from the A1 workspace lifecycle graph), then saved views.
- **Show / Sort / Unreplied** - the list header controls: Show (`Open` / `Snoozed` / `Closed` /
  `All`), Sort (`Newest` / `Oldest` / `Unreplied first` / `Longest waiting`), Unreplied toggle.
- **Unreplied** - `last_incoming_message_at IS NOT NULL AND (last_agent_message_at IS NULL OR
  last_agent_message_at < last_incoming_message_at)`.
- **Comment** - an internal note: a `conversation_messages` row with `sender_type = "SYSTEM"`,
  `channel_id NULL`, never delivered to the contact (already shipped - audited 2026-09-06,
  `services/message_service.py add_internal_note`).
- **Shortcut** - a published workflow whose trigger is `entity.shortcut` with
  `entityType = omnichannel_contact`, fired by an agent from the conversation drawer.

---

## Slice A - Conversation events: table, writers, backfill

- **AC-IVE-01 [BE]** Given the module boots, then `app_omnichannel.conversation_events` exists with
  `id`, `tenant_id`, `workspace_id`, `contact_id`, `event_type`, `actor_user_id`,
  `actor_external_agent_id`, `from_value`, `to_value`, `close_reason_id`, `note`, `payload_json`
  (`JSON(none_as_null=True)`), `created_at` (`UTCDateTime`, aware-UTC, set explicitly in Python for
  microsecond ordering), and indexes on `(tenant_id, workspace_id, created_at)`,
  `(tenant_id, contact_id, created_at)`, `(tenant_id, event_type, created_at)`.
- **AC-IVE-02 [BE]** Given any event write, then it happens on the SAME session and unit of work as
  the mutation that caused it (no separate commit, no post-commit hook): if the mutation rolls back
  the event is gone, and if the event insert fails the mutation fails with it. An event write costs at most one extra
  indexed SELECT plus one INSERT on the hot inbound / send paths and is never swallowed.
- **AC-IVE-03 [BE]** Given a new thread is created by any path (inbound stitch, gateway
  `POST /api/v1/omnichannel/contacts`, demo seed), then exactly one `opened` event exists for it
  with `to_value` = the OPEN status id.
- **AC-IVE-04 [BE]** Given an inbound message arrives on a thread whose status is `CLOSED`, then the
  auto-reopen writes exactly one `reopened` event (`from_value` = CLOSED status id, `to_value` =
  OPEN); given the status was `SNOOZED`, it writes `unsnoozed`; given the status was already `OPEN`,
  it writes NO status event.
- **AC-IVE-05 [BE]** Given a status change through `PATCH /omnichannel/contacts/{id}` or
  `POST /omnichannel/contacts/{id}/close`, then exactly one event is written per actual change:
  `-> CLOSED` = `closed`, `CLOSED -> OPEN` = `reopened`, `OPEN -> SNOOZED` = `snoozed`,
  `SNOOZED -> OPEN` = `unsnoozed`; a PATCH that sets the status it already has writes nothing.
- **AC-IVE-06 [BE]** Given an assignee change, then `assigned` is written when the thread gains an
  assignee (`to_value` = the user id or external-agent id, `payload_json.assigneeKind` =
  `user` | `external_agent`) and `unassigned` when it loses one (`from_value` = the previous id);
  a PATCH that re-sends the same assignee writes nothing.
- **AC-IVE-07 [BE]** Given an agent (or embed agent) sends the first outbound message of the current
  open cycle (no `first_agent_reply` event newer than the latest `opened` / `reopened` event for
  that contact), then one `first_agent_reply` event is written with
  `payload_json.responseSeconds` = whole seconds between the thread's `last_incoming_message_at` and
  now (omitted when there is no inbound); subsequent outbound messages in the same cycle write none;
  an internal note NEVER counts as a reply.
- **AC-IVE-08 [BE]** Given a lifecycle move (internal route, gateway PATCH, or workflow), then one
  `lifecycle_changed` event is written from the ONE move seam (`services/lifecycle_service.move`)
  with `from_value` / `to_value` = core lifecycle status ids.
- **AC-IVE-09 [BE]** Given an internal note is added (internal route or gateway
  `POST /api/v1/omnichannel/contacts/{identifier}/comments`), then one `comment_added` event is
  written with `payload_json.messageId` = the created message id.
- **AC-IVE-10 [BE]** Given `actor_user_id` is set, then it was validated at save time to belong to
  the writing tenant, and every read resolves the display name tenant-scoped (never an unscoped
  `get_by_id`); an unresolvable actor renders as an empty author, never another tenant's user.
- **AC-IVE-11 [BE]** Given `contacts.last_agent_message_at` (new column), then it is maintained by
  the ONE outbound seam in `MessageService` (text, media, structured/template) and never by internal
  notes, and it is backfilled to `max(created_at)` of each contact's `AGENT` messages.
- **AC-IVE-12 [BE]** Given a tenant provisioned on an earlier module version with existing threads,
  when this slice's `update_tenant` backfill runs (and `install_tenant` self-healing), then every contact
  that has NO events yet gets: `opened` at its `created_at`; `closed` at its `updated_at` when its
  current status is CLOSED; `assigned` at its `updated_at` when it currently has an assignee - each
  carrying `payload_json.backfilled = true`; and `last_agent_message_at` is filled. Re-running is a
  no-op (contacts that already have events are skipped).
- **AC-IVE-13 [BE]** Given `GET /omnichannel/contacts/{id}/events`, then it returns that thread's
  events newest-first, paginated, each with `id`, `eventType`, `actorName`, `fromLabel`, `toLabel`,
  `closeReasonName`, `note`, `createdAt` (Z-suffixed), tenant-scoped; a contact of another tenant
  returns 404.
- **AC-IVE-14 [BE]** Given a tenant is uninstalled from the module, then its `conversation_events`
  and `close_reasons` and `inbox_views` rows are deleted with the rest of the module's tables, and
  no other tenant's rows are touched.

## Slice B - Inbox views: rail, saved views, Show / Sort / Unreplied

- **AC-IVE-15 [BE]** Given `GET /omnichannel/contacts` (thread list), then it accepts, in addition
  to today's params: `lifecycleStageIds` (CSV), `tagIds` (CSV), `channelIds` (CSV), `unreplied`
  (bool), `sort` (`newest` | `oldest` | `unreplied_first` | `longest_waiting`), `viewId`; ALL
  filtering and sorting happens in the repository (no Python post-filtering), and every query stays
  tenant-scoped from the JWT.
- **AC-IVE-16 [BE]** Given `sort`, then: `newest` = `last_message_at DESC NULLS LAST` (today's
  default), `oldest` = ascending, `unreplied_first` = unreplied threads first then
  `last_message_at DESC`, `longest_waiting` = unreplied first ordered by
  `last_incoming_message_at ASC` then the rest by `last_message_at DESC`; every ordering ends with
  `id ASC` so pagination is stable.
- **AC-IVE-17 [BE]** Given `viewId` names a saved view the caller may see, then the server expands
  that view's stored filter server-side; explicit `status` / `sort` / `unreplied` / `search` params
  sent alongside OVERRIDE the view's values; a `viewId` from another workspace or tenant returns 404.
- **AC-IVE-18 [BE]** Given the saved-view routes
  (`GET|POST /omnichannel/workspaces/{wsId}/inbox-views`,
  `PATCH|DELETE /omnichannel/workspaces/{wsId}/inbox-views/{id}`), then: the list returns the
  caller's own views plus shared views in `sortOrder`; create stores `ownerUserId` = the caller
  (server-resolved, never client input); the `filter` payload is a typed model that rejects unknown
  keys with 422; every id inside it (`lifecycleStageIds`, `tagIds`, `channelIds`,
  `assigneeUserIds`) is validated against the workspace at save time and 422s otherwise; name is
  required, unique per workspace case-insensitively, cap 50 views per workspace.
- **AC-IVE-19 [BE]** Given a saved view, then a user may edit / delete their OWN view with only
  `conversations.read`; creating, editing or deleting a SHARED view - or any view they do not own -
  additionally requires `inbox_views.manage` (403 otherwise).
- **AC-IVE-20 [FE]** Given the inbox at >= 1024px, then a left view rail shows: **All**, **Mine**,
  **Unassigned**; a **Lifecycle** section listing every stage of the workspace graph with its emoji
  label; a **Views** section listing saved views (own + shared, shared marked); selecting an entry
  filters the thread list and is reflected in the URL (`?view=`), so a reload restores it. A rail entry with no threads stays
  selectable and the list shows the existing empty state (no instructional copy).
- **AC-IVE-21 [FE]** Given the list header, then it carries a **Show** `SearchSelect` (Open /
  Snoozed / Closed / All), a **Sort** `SearchSelect` (Newest / Oldest / Unreplied first / Longest
  waiting) and an **Unreplied** switch; the pre-existing bare shadcn status + priority `<Select>`s
  are replaced by `SearchSelect` in the same pass (design mandate: every dropdown is searchable).
- **AC-IVE-22 [FE]** Given the current filter state, then a "Save view" control opens a dialog with
  Name and a Shared switch (the switch is hidden for a user without `inbox_views.manage`); saving
  adds the view to the rail and selects it; a saved view row offers Rename / Delete (and Share
  toggle with the permission), with the shell's confirm dialog on delete.

- **AC-IVE-23 [FE]** Given a live WS `contact.updated` / `message.created` event while a filtered
  view is active, then the list reconciles exactly as today (refetch under an active filter), and a
  thread that leaves the current view disappears without a manual refresh.
- **AC-IVE-24 [FE]** Given the inbox below 1024px, then the rail collapses into a single **View**
  `SearchSelect` above the list (same options, same selection state), and the shell shows ONE pane -
  the thread list, or the conversation with a back control once a thread is selected - with no
  horizontal scroll at 375px.

## Slice C - Close with reason + note

- **AC-IVE-25 [BE]** Given the close-reason routes under
  `/omnichannel/workspaces/{wsId}/close-reasons` (GET / POST / PATCH / DELETE), then reads are gated
  `conversations.read`, writes `close_reasons.manage`; `name` is required and unique per workspace
  case-insensitively (422); `sortOrder` and `isActive` are editable; cap 100 per workspace.
- **AC-IVE-26 [BE]** Given a close reason referenced by at least one event, when it is deleted, then
  409 `close_reason_in_use` and nothing is written; deactivating it (`isActive=false`) succeeds and
  it disappears from the close dialog while historical events still resolve its name.
- **AC-IVE-27 [BE]** Given a workspace is created (service path or `install_tenant`), then the four
  default close reasons (General Inquiry, Sales Inquiry, Payment Issue, Others) are materialized for
  it in the same unit of work; this slice's `update_tenant` backfills them for every pre-existing
  workspace that has none; re-running is a no-op. No code ever looks a reason up by name.
- **AC-IVE-28 [BE]** Given `POST /omnichannel/contacts/{id}/close {closeReasonId, note?}` from a
  user with `conversations.reply`, then the thread moves to CLOSED, one `closed` event is written
  carrying `close_reason_id` + `note` (note <= 2000 chars), the updated `ThreadItem` is returned, and
  the existing `contact.updated` fan-out (realtime WS + consumer webhook) fires exactly once.
- **AC-IVE-29 [BE]** Given `closeReasonId` is missing, inactive, or belongs to another workspace or
  tenant, then 422 / 404 and the thread stays open (no partial write). The close reason is stored on
  the event, never on the thread row.
- **AC-IVE-30 [FE]** Given the drawer header Close button, then it opens a Close dialog with a
  required reason `SearchSelect` (active reasons only, in `sortOrder`) and an optional note
  textarea; Close is disabled until a reason is picked; the reopen path is unchanged and keeps the
  history.
- **AC-IVE-31 [FE]** Given the workspace form, then a **Close reasons** tab (after Tags, hidden
  while creating) renders an embedded `ResourceList` (Name, Sort order, Active, Uses, Date added)
  with Create / Edit dialogs; the row menu offers Delete only when the reason has no events, and
  Deactivate / Activate otherwise; without `close_reasons.manage` the tab is read-only.

## Slice D - Internal comments (reuse audit outcome)

- **AC-IVE-32 [FE]** Given the drawer **Activities** tab, then it renders ONE merged, chronological
  feed of internal notes (existing SYSTEM bubbles) AND conversation events, visually distinct
  (note = authored bubble, event = compact system line with actor + timestamp in the user's
  timezone), and the note composer at the bottom is unchanged.
- **AC-IVE-33 [BE]** Given the internal-note path, then it keeps requiring `conversations.reply`
  (native) or the `note` embed cap, keeps publishing the realtime `message.created` event, and stays
  excluded from every channel send and from the public gateway's message reads - verified by test,
  not by inspection.
- **AC-IVE-34 [FE]** Given a comment is added by another agent while the drawer is open, then it
  appears live in the Activities feed via the existing WS push, and its `comment_added` event does
  not render as a duplicate line next to the note bubble.

## Slice E - Shortcut (run a workflow on this conversation)

- **AC-IVE-35 [BE]** Given the workflow registry, then a core trigger `entity.shortcut` exists
  (label "Shortcut", one required `entityType` entity field filtered to entities that declare
  `supports_shortcut`), `WorkflowEntity` carries `supports_shortcut`, `omnichannel_contact` sets it
  true, and `/workflows/metadata` advertises `supportsShortcut` per entity.
- **AC-IVE-36 [BE]** Given `GET /omnichannel/contacts/{id}/shortcuts`, then it lists the tenant's
  workflows that are active, published (`current_version_id` set), not archived, with
  `trigger_type = entity.shortcut` and `trigger_entity_type = omnichannel_contact`, each as
  `{workflowId, name}`; requires `conversations.read` AND `workflows.read`.
- **AC-IVE-37 [BE]** Given `POST /omnichannel/contacts/{id}/shortcuts/{workflowId}` from a user with
  `conversations.reply` AND `workflows.run`, then a run is created against the workflow's PUBLISHED
  version (never the draft) through the SAME helper the event bus uses, with
  `triggered_by = event`, `trigger.record.*` from the contact's registered facts,
  `trigger.actor.*` = the real actor (real admin under impersonation), and the response is
  `{runId, status}`.
- **AC-IVE-38 [BE]** Given the target workflow is unpublished / inactive / archived / of another
  tenant / not an `entity.shortcut` workflow / not bound to `omnichannel_contact`, then 404 or 409
  and no run is created; given its published version carries Code nodes without a
  `code_authorized_by` stamp, then 409 and no run is created (the fail-closed rule is preserved by
  reusing the shared helper).
- **AC-IVE-39 [FE]** Given the drawer header, then a **Shortcuts** control appears only when at
  least one shortcut workflow exists and the user has `workflows.run`; it is a `SearchSelect` of
  those workflows; running one shows a success toast linking to the run, and a failure shows the
  server message.
- **AC-IVE-40 [BE]** Given an embed (federated) principal, then the shortcut list and run routes are
  refused (no embed cap grants them) - 403, never a run.

## Slice F - Permissions, tenant isolation

- **AC-IVE-41 [BE]** Given the module permissions CSV, then it adds exactly `close_reasons.manage`
  and `inbox_views.manage` (no core collision - verified against `app/permissions/permissions.csv`
  2026-09-06), the manifest version is bumped, and `update_tenant` / the App Store update path
  grants the new keys to every already-provisioned tenant's Admin role.
- **AC-IVE-42 [BE]** Given a tenant B user or API key, when they call ANY new route
  (`close-reasons`, `inbox-views`, `contacts/{id}/events`, `contacts/{id}/close`,
  `contacts/{id}/shortcuts*`) with tenant A ids, then the response is a uniform 404 - never 403,
  never data, never a cross-tenant name resolved into a label.
- **AC-IVE-43 [FE]** Given a user lacking `close_reasons.manage` / `inbox_views.manage` /
  `workflows.run`, then the corresponding controls are hidden or read-only via `useCan()` while the
  API remains the real gate (a direct call still 403s).

## Slice G - Gateway and webhook impact

- **AC-IVE-44 [BE]** Given the public gateway, then conversation events are INTERNAL: no new
  `/api/v1/omnichannel/*` route, no new field on the default or `?format=rio` thread / contact
  shapes, and no new consumer-webhook event type; the existing `contact.updated` webhook still fires
  once per close / assign / lifecycle change.
- **AC-IVE-45 [BE] [T]** Given no gateway shape changes, then
  `documentation/omnichannel/consumer-integration-guide.md` needs NO diff in this slice, and the
  contract-drift tests in `tests/test_omnichannel_api_gateway.py` still pass unchanged - proving it.
  A gateway close-with-reason and an events read are backlog items, not A3.

## Slice H - Responsive and design mandates

- **AC-IVE-46 [FE]** Given every new or changed surface (view rail, list header, save-view dialog,
  close dialog, close-reasons tab, activities feed, shortcuts control), then each is usable and
  non-clipped at BOTH 375px and 1280px, uses only Tailwind / Metronic utilities (no `<style>`, no
  raw CSS, no `text-[Npx]`), every dropdown is a `SearchSelect`, truncated labels use
  `ClampedText` / `OverflowPills`, every icon-only control has an accessible label, and no
  instructional / how-to copy appears on screen. Tenant-facing copy never says "Foundryx" and every
  timestamp renders through `useDatetime()` in the user's timezone.

## Slice I - Tests and evidence

- **AC-IVE-47 [T]** pytest covers: one event row per action for each of the ten event types
  (including the no-op cases in AC-IVE-04 / 05 / 06), first-reply once-per-open-cycle plus the
  reopen-then-reply case, event rollback with its mutation, backfill correctness + idempotency,
  `last_agent_message_at` backfill, every list filter + the four sorts (including stable
  pagination), saved-view CRUD + typed-filter 422s + cross-workspace id rejection + own-vs-shared
  permission split, close route happy path + inactive / foreign reason rejection + in-use delete
  409, close-reason seeding on workspace create + backfill idempotency, shortcut list + run against
  the published version + every rejection in AC-IVE-38, embed principal 403s, permission gates
  (403 per write key), tenant isolation on every new route, gateway shapes unchanged.
- **AC-IVE-48 [T]** vitest covers: rail selection -> query params + URL sync, Show / Sort /
  Unreplied wiring, save-view dialog schema (name required, shared switch gated), close dialog
  (Close disabled until a reason is chosen, note optional, 422 mapping), close-reasons list actions
  (Delete vs Deactivate by `usesCount`), merged activities feed ordering + note-vs-event rendering,
  shortcuts control hidden when the list is empty or the permission is missing.
- **AC-IVE-49 [E2E]** Recorded agent-browser run (dedicated timestamped tenant + workspace, real
  clicks from `/`, evidence at 375 AND 1280 under
  `documentation/plans/sprint-4/27-evidence/<slice>/` with a README run log): Settings ->
  Workspaces -> open workspace -> **Close reasons** tab shows the four seeded reasons -> add
  "Refund <ts>" -> Inbox -> rail shows All / Mine / Unassigned + the lifecycle stages -> click a
  lifecycle stage -> list filters -> set Show=Open, Sort=Longest waiting, Unreplied on -> Save view
  "Waiting <ts>" (shared) -> reload -> the view is selected from the URL and the rail lists it ->
  open a thread -> add an internal note -> Activities tab shows the note plus the event lines ->
  Close -> pick "Refund <ts>" + note -> the row chip flips to Closed and the Activities feed shows
  the close with its reason -> Reopen -> the feed keeps both entries.
- **AC-IVE-50 [E2E]** Same run: create + publish a workflow whose trigger is Shortcut on
  Omnichannel Contact -> back in the inbox the drawer's **Shortcuts** control lists it -> run it ->
  a toast links to the run and the run detail shows `trigger.record.id` = the contact; and a second
  tenant sees none of tenant A's views / close reasons / events (API probe returns 404 or empty),
  while a tenant without the omnichannel module sees no new workspace tab.
