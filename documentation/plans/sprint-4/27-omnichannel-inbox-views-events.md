# 27 - Omnichannel inbox views, conversation actions, conversation events

> **Contract:** `27-omnichannel-inbox-views-events-acceptance-criteria.md` (50 ACs). This plan fulfils it.
> **Program:** slice **A3** of `24-omnichannel-respondio-parity-roadmap.md`, plus the A9 prerequisite
> (roadmap D9 `omni_conversation_events` - A1 was supposed to design it and did not; A3 owns it).
> **Branch:** `sprint-4/27-inbox-views-events`, worktree `.claude/worktrees/s27` off `main` AFTER the
> plan-25 (A1) merge. Lane: backend `:8006` on DB `foundryx_service_s27`, frontend `:3005`,
> `agent-browser --session s27`. Each worktree gets its OWN `npm ci` (never a shared `node_modules`).
> **Independent of A2.** The only A2 seam is a reserved, unused `inbox_views.segment_id` column.
> **Coordinates with plan 23** (design-language alignment, branch `sprint-4/23-design-language-alignment`,
> not merged): it touches `inbox/page.tsx` (1 line), `inbox/components/thread-list.tsx` (cosmetic:
> `PRESSED_CLASS`, `text-2xs`, `TabsList variant`) and four drawer files cosmetically. A3 keeps new
> code in new files and accepts a small merge cost on those two inbox files.

## 1. Why

respond.io's inbox is a **view rail** (All / Mine / Unassigned / one entry per lifecycle stage /
saved custom inboxes) over a list with **Show + Sort + Unreplied**, and a conversation whose actions
are auditable: close with a **category and note**, internal **comments**, and a **Shortcut** button
that fires a workflow on the open thread. Foundryx has a flat list with three buckets and two bare
dropdowns, and closes a thread with no reason and no trace.

Underneath, every respond.io report and dashboard tile is an aggregate over conversation lifecycle
events. We have none: the thread row carries its CURRENT status and nothing about how it got there.
A3 therefore lands the append-only `conversation_events` table first and makes every existing
mutation path write it, so A9 (dashboard + reports) is a read model over data that already exists,
and A6 (migration) backfills history into the same shape.

## 2. Architecture

```
app_omnichannel.workspaces ──1:N──▶ close_reasons     (name, sort_order, is_active)
                           ──1:N──▶ inbox_views       (name, owner_user_id, is_shared, filter_json, segment_id?)
contacts (= the thread)
   + last_agent_message_at  (new, denormalized; powers Unreplied + Longest waiting + first reply)
   └──1:N──▶ conversation_events   (append-only; the A9 read model, the A6 backfill target)

writers (same unit of work as the mutation, never a post-commit hook):
   inbound_service.handle_message ....... opened | reopened | unsnoozed
   public_gateway_service.create_contact  opened
   conversation_service.patch_thread .... closed | reopened | snoozed | unsnoozed | assigned | unassigned
   conversation_service.close_thread .... closed (+ close_reason_id, note)
   lifecycle_service.move ............... lifecycle_changed
   message_service._mark_agent_message .. first_agent_reply
   message_service.add_internal_note .... comment_added
```

The thread list stays ONE repository query: filters and sorts are SQL, never Python. `viewId`
expands server-side so a saved view is one source of truth for the inbox today and for A2 segments
and A4 broadcast audiences later.

### 2.1 Backend pieces

| Piece | Where | Notes |
|---|---|---|
| Models | `modules/omnichannel/models.py` | `ConversationEvent`, `CloseReason`, `InboxView`; `Contact.last_agent_message_at` (`UTCDateTime`, index) |
| Migration | `modules/omnichannel/alembic/versions/00NN_omni_conversation_events.py` (next free number after `main`; A2 also adds one - D-A3-16) | three tables + one column + the data backfill; inspector-guarded like `0004` / `0008`; Postgres-only, no-op under pytest. `bootstrap.create_schema_and_tables` also does ADD COLUMN IF NOT EXISTS for `last_agent_message_at` (the `create_all` deployments) |
| Event writer | `services/event_service.py` (new) | `record(db, contact, event_type, *, actor=None, actor_id=None, external_agent_id=None, from_value=None, to_value=None, close_reason_id=None, note=None, payload=None) -> ConversationEvent` - validates `actor_id` belongs to the tenant, adds to the SAME session, NEVER commits. Plus `is_first_reply_pending(db, contact)`, `list_for_contact(...)`, `backfill_tenant(db, tenant_id)` |
| Close reasons | `services/close_reason_service.py` + `routers/close_reasons.py` | CRUD, per-workspace unique name (case-insensitive), cap 100, `seed_for_workspace(db, ws)`, `uses_count` per reason, delete blocked while referenced |
| Saved views | `services/inbox_view_service.py` + `routers/inbox_views.py` | CRUD, own + shared visibility, typed `InboxViewFilter` (Pydantic `extra="forbid"`), id validation against the workspace, cap 50, `expand(view) -> filter kwargs` |
| Thread list | `repositories/contact_repository.py list_threads` | new kwargs `lifecycle_stage_ids`, `tag_ids`, `channel_ids`, `unreplied`, `sort`; tag filter via an `EXISTS` over `contact_tag_links`; channel filter via `EXISTS` over `contact_channel_identities`; every ordering ends `Contact.id.asc()` |
| Close + events routes | `routers/conversations.py` | `POST /{contact_id}/close`, `GET /{contact_id}/events`, `GET /{contact_id}/shortcuts`, `POST /{contact_id}/shortcuts/{workflow_id}` |
| Shortcut core seam | `app/workflow_engine/registry.py` (`entity.shortcut` TriggerDef), `app/workflow_engine/entities.py` (`WorkflowEntity.supports_shortcut`), `app/workflow_engine/entity_events.py` (extract `create_run_for_event`), `app/services/workflow_service.py` (`list_shortcuts`, `run_shortcut`, metadata `supportsShortcut`) | see D-A3-10 |
| Module registration | `modules/omnichannel/workflow_nodes.py _register_contact_entity` | `supports_shortcut=True` on `omnichannel_contact` |
| Permissions | `modules/omnichannel/permissions/permissions.csv` | `close_reasons.manage`, `inbox_views.manage` |
| Tenant hooks | `bootstrap.install_tenant` (seed close reasons + self-healing backfill), `update_tenant` (from whatever version is on `main`), `workspace_service.create()` (seed reasons in the same unit of work); manifest version -> the NEXT patch after `main` (`0.3.0` if A3 merges before A2, `0.4.0` if A2 landed first - plan 26 also claims `0.3.0`, D-A3-16) | uninstall is already generic over `OmniBase` tables |

### 2.2 Frontend pieces

| Piece | Where |
|---|---|
| Services (trio) | `services/inbox-view-service.{ts,mock,real}.ts`, `services/close-reason-service.{ts,mock,real}.ts`; `services/conversation-service.{ts,mock,real}.ts` += `closeThread`, `listEvents`, `listShortcuts`, `runShortcut`, and the new list query params |
| Hooks | `hooks/use-inbox-views.ts`, `hooks/use-close-reasons.ts`, `hooks/use-thread-events.ts`, `hooks/use-shortcuts.ts`; `hooks/use-conversations.ts` gains `lifecycleStageIds` / `tagIds` / `channelIds` / `unreplied` / `sort` / `viewId` in `ConversationFilters` + URL sync |
| Rail + header | `app/(protected)/omnichannel/inbox/components/inbox-view-rail.tsx`, `inbox-filter-bar.tsx`, `inbox-view-dialog.tsx`; `inbox/page.tsx` gains the rail column + the below-`lg` single-pane switch; `thread-list.tsx` loses its two bare `<Select>`s to the filter bar |
| Drawer | `components/platform/conversation-drawer/close-thread-dialog.tsx`, `shortcut-menu.tsx`, `activity-feed.tsx`; `conversation-drawer.tsx` header wires Close -> dialog and adds the Shortcuts control; the Activities tab renders `ActivityFeed` instead of the filtered message list |
| Workspace tab | `app/(protected)/omnichannel/settings/workspaces/components/workspace-close-reasons-tab.tsx` + `close-reason-dialog.tsx` + `use-close-reason-list.tsx`, registered in `use-workspace-form.tsx` after Tags (clone `workspace-tags-tab.tsx` exactly) |
| Types | `types/omnichannel.ts` += `ConversationEvent`, `CloseReason`, `InboxView`, `InboxViewFilter`, `ThreadSort`, `ShortcutWorkflow`; `ThreadListQuery` += the new params |

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D-A3-1 | The append-only events table lands in A3, written by the services that already mutate threads, backfilled for existing rows | Main session 2026-09-06. A9 must not invent history; A6 backfills into the same shape |
| D-A3-2 | View rail = All / Mine / Unassigned + one entry per lifecycle stage + saved views; saved view = typed JSON filter on `inbox_views`, NOT a rule tree; Show / Sort / Unreplied are query params on the existing list route, filtered server-side | Main session. A rule tree is A2's job (`contact_segments`, roadmap D6); a typed filter is testable and cheap |
| D-A3-3 | Close with a required reason (`close_reasons` per workspace, seeded) + optional note, stored on the `closed` EVENT, not on the thread | Main session. Reopening keeps history; a thread column would be overwritten on the next close |
| D-A3-4 | **Internal comments already exist - reuse, do not build.** A3 only adds the `comment_added` event and the merged Activities feed | Audit 2026-09-06, see §3.1 |
| D-A3-5 | Shortcut = a workflow run on the current thread, on a NEW generic `entity.shortcut` core trigger | Audit 2026-09-06, see §3.2 |
| D-A3-6 | New permission keys `close_reasons.manage`, `inbox_views.manage` (grep of `app/permissions/permissions.csv` 2026-09-06: no collision; existing core resources are `ai_agents ai_traces app_store branding dashboard documents emails events finance forms imports integration_logs integrations inventory numbering orders procurement product_categories products reports resource reviews roles rules settings statuses submissions templates terminology users vendors workflows`) | `sync_permissions` is delete-by-module on a GLOBAL unique key |
| D-A3-7 | Out of scope: teams inbox (A8), dashboard / reports (A9), broadcasts (A4), auto-close + AI closing notes (B2), collaborators / @mentions, plan-23 restyle | Main session |
| D-A3-8 | Table names are `conversation_events`, `close_reasons`, `inbox_views` inside `app_omnichannel` - no `omni_` prefix | The schema already namespaces and every sibling table (`contacts`, `conversation_messages`, `contact_tags`) is unprefixed. The roadmap's `omni_conversation_events` = `app_omnichannel.conversation_events` |
| D-A3-9 | Columns are `from_value` / `to_value` (wire `fromValue` / `toValue`) | `from` is a Python keyword; the decision's `from`/`to` naming survives on the wire in spirit without an alias dance |
| D-A3-10 | The shortcut executes the PUBLISHED version through the SAME helper the event bus uses: extract `entity_events._create_run` into `create_run_for_event(session, wf, ev, *, depth, ...) -> WorkflowRun | None` and have both `_create_run` and the new `WorkflowService.run_shortcut` call it | `WorkflowService.run()` executes the DRAFT (by design, it is the builder's Run button) - a shortcut must not. The shared helper preserves the fail-closed Code-node authorization check (`has_code_nodes` + `code_authorized_by`), `assign_run_correlation` and `dispatch_persisted_run` for free, and returns the run so the UI can toast a link |
| D-A3-11 | A user may create / edit / delete their OWN saved view with `conversations.read`; `inbox_views.manage` is required only for SHARED views or someone else's view | Refines D-A3-6. A personal view is a preference, not an admin act - respond.io lets any agent save a custom inbox. Gating it behind a manage key would make the feature invisible to the people who use the inbox |
| D-A3-12 | `contacts.last_agent_message_at` is a new denormalized column (maintained by the one outbound seam, backfilled), not a correlated subquery | Unreplied + Longest waiting are list-level filters and sorts; a per-row subquery over `conversation_messages` would not index |
| D-A3-13 | Deleting a close reason that is referenced by any event is a 409; the UI offers Deactivate instead | History must resolve its reason name forever. `is_active=false` removes it from the close dialog without rewriting the past |
| D-A3-14 | No gateway or webhook change in A3. Events are internal; the consumer guide needs no diff | Keeps the guide-is-the-contract rule honest: a `Rio*` / `api_v1.py` diff without a guide diff is a reject, so A3 simply does not touch them. Gateway close-with-reason + events read = backlog |
| D-A3-15 | Below `lg` the inbox is ONE pane (list, or conversation with a back control) and the rail becomes a View `SearchSelect` | Today at 375px the shell is `grid-cols-[320px_1fr]` with the drawer clipped off-screen (plan-23 T6 evidence `16-mobile-inbox-page-375.png`). Adding a rail without this makes 375 unusable, and the responsive mandate is non-negotiable |
| D-A3-16 | Plan 26 (A2) ALSO bumps the module manifest to `0.3.0`, adds `segments.manage` / `contacts.import` / `contacts.export`, and adds `list_contacts` to `contact_repository.py`. Whichever slice merges second takes the next version and rebases its `update_tenant` guard + its migration `down_revision` | Both lanes branch off the same `main`; a duplicated `0.3.0` or two migrations claiming the same parent is a merge break, not a conflict git can see |
| D-A3-17 | An A2 segment stores the Resource shell's `FilterGroup` (plan 26 D-A2-3), NOT a rule tree; `inbox_views.segment_id` therefore resolves through `translate_filter` over A2's whitelisted contact column map when A2 exists, and is simply unused until then | Keeps one filter vocabulary across inbox views, contacts segments and A4 broadcast audiences |

### 3.1 Audit outcome - internal comments EXIST (D-A3-4)

Verified in the plan-25 worktree on 2026-09-06:

- `service_backend/modules/omnichannel/services/message_service.py` -> `MessageService.add_internal_note(contact_id, tenant_id, actor_user_id, body, *, external_agent_id=None)` writes a `ConversationMessage` with `sender_type="SYSTEM"`, `channel_id=None`, `message_type="TEXT"` and publishes the realtime `message.created` event.
- `service_backend/modules/omnichannel/routers/conversations.py` -> `POST /{contact_id}/notes`, gated `principal.require(native_perm="conversations.reply", embed_cap="note")`.
- `service_backend/modules/omnichannel/routers/api_v1.py` -> `POST /contacts/{identifier}/comments` -> `PublicGatewayService.add_comment` -> the same `add_internal_note`.
- Never sent to a channel: SYSTEM rows are excluded from the last-message preview (`repositories/contact_repository.py`, `sender_type != "SYSTEM"`) and are not produced by any send path.
- Frontend: `components/platform/conversation-drawer/message-bubble.tsx` renders SYSTEM as a centred internal note; `conversation-drawer.tsx` has an **Activities** tab filtering `senderType === 'SYSTEM'` and a note-mode composer; `hooks/use-messages.ts addNote`; `services/conversation-service.real.ts` -> `/omnichannel/contacts/{id}/notes`.

**Therefore A3 adds no note model, no new message type, and no new permission.** It adds: the
`comment_added` event on the existing seam, and the merged Activities feed (notes + events) so the
events are visible to a human before A9 exists. @mention of workspace members -> backlog.

### 3.2 Audit outcome - no manual/shortcut trigger for a record (D-A3-5)

- `app/workflow_engine/registry.py` has `manual` (a builder Run button with free-form `inputs`), the
  five `entity.*` triggers, `schedule.cron`, `form.submitted`; the omnichannel module adds
  `omnichannel.message_received`. **None binds a record + an agent-fired button.**
- `POST /api/v1/workflows/{id}/run` (`workflows.run`) executes `wf.draft_definition_json` - the
  builder's Run/Test path, not a production fire.
- Publish already denormalizes `trigger_entity_type` from `trigger.config.entityType`
  (`app/services/workflow_service.py publish`), so `entity.shortcut` needs no special-casing there.
- The canvas renders `NodeField(type="entity")` generically through a `SearchSelect`
  (`components/platform/workflow-canvas/node-config-drawer.tsx` L1006), so the new trigger needs no
  canvas work beyond one `entityFilter === 'shortcut'` branch.

**Therefore A3 defines ONE generic core trigger `entity.shortcut`** (any entity that declares
`supports_shortcut` may use it; `omnichannel_contact` is the first), a core `run_shortcut` on the
shared published-run helper (D-A3-10), and module routes that own the per-record permission gate.

## 4. Slices (build order - one Sonnet coder lane each)

| Slice | Content | Size | AC ids |
|---|---|---|---|
| **S0 FE mock** | types, service trios (mock only), `use-conversations` filter/URL extension, view rail + filter bar + save-view dialog, close dialog, merged activities feed, shortcuts control, close-reasons workspace tab, single-pane below `lg`; vitest for every new component; agent-browser smoke at 375 + 1280 against the mock | M | 20-24, 30-32, 34, 39, 43, 46, 48 |
| **S1 BE events** | models + the new migration + `last_agent_message_at`, `event_service`, the nine writer call sites (§5.3), `GET /{id}/events`, backfill in the migration + `update_tenant` + `install_tenant`, manifest bump (D-A3-16), pytest | M | 01-14, 33, 42 |
| **S2 BE views + close reasons + close route** | `close_reason_service` + routes + seeding, `inbox_view_service` + routes + typed filter, repository filters + sorts, `POST /{id}/close`, permissions CSV + grant sweep, pytest | M | 15-19, 25-29, 41, 42 |
| **S3 BE shortcut** | `entity.shortcut` trigger, `WorkflowEntity.supports_shortcut` + metadata, `create_run_for_event` extraction, `WorkflowService.list_shortcuts` / `run_shortcut`, module routes, canvas `entityFilter` branch, pytest; confirm NO gateway/guide diff (44, 45) | S | 35-38, 40, 44, 45 |
| **S4 Wire + E2E** | swap all mocks for real, verify WS reconciliation under the new filters, evidence run at 375 + 1280, Test Execution Report keyed to the AC ids | M | 47-50 |
| **Review** | `reviewer` agent on **Opus** (tenant isolation on five new routes + a new core workflow-run entry point = security-grade), then `/codex-review` | - | - |

S1 and S2 both touch `conversation_service.patch_thread` and `routers/conversations.py`; run them
sequentially on the branch. S3 is disjoint (core workflow engine) and may run in parallel with S2.

## 5. Contracts

### 5.1 Internal API

```
GET    /omnichannel/workspaces/{wsId}/close-reasons        -> CloseReasonItem[]           (conversations.read)
POST   /omnichannel/workspaces/{wsId}/close-reasons        {name, sortOrder?, isActive?}  (close_reasons.manage)
PATCH  /omnichannel/workspaces/{wsId}/close-reasons/{id}   {name?, sortOrder?, isActive?}
DELETE /omnichannel/workspaces/{wsId}/close-reasons/{id}   -> 204 | 409 close_reason_in_use

GET    /omnichannel/workspaces/{wsId}/inbox-views          -> InboxViewItem[]             (conversations.read)
POST   /omnichannel/workspaces/{wsId}/inbox-views          {name, isShared, filter}       (own: conversations.read; shared: + inbox_views.manage)
PATCH  /omnichannel/workspaces/{wsId}/inbox-views/{id}     {name?, isShared?, filter?, sortOrder?}
DELETE /omnichannel/workspaces/{wsId}/inbox-views/{id}     -> 204

GET    /omnichannel/contacts                               += lifecycleStageIds, tagIds, channelIds,
                                                              unreplied, sort, viewId
POST   /omnichannel/contacts/{id}/close                    {closeReasonId, note?} -> ThreadItem   (conversations.reply)
GET    /omnichannel/contacts/{id}/events                   ?page&pageSize -> ConversationEventItem[]  (conversations.read)
GET    /omnichannel/contacts/{id}/shortcuts                -> ShortcutItem[]   (conversations.read + workflows.read)
POST   /omnichannel/contacts/{id}/shortcuts/{workflowId}   -> {runId, status}  (conversations.reply + workflows.run)
```

Wire shapes (camelCase, `ApiModel` for datetimes):

```
CloseReasonItem       {id, workspaceId, name, sortOrder, isActive, usesCount, createdAt}
InboxViewItem         {id, workspaceId, name, ownerUserId, ownerName, isShared, filter, sortOrder, createdAt}
InboxViewFilter       {statuses?: ["OPEN"|"SNOOZED"|"CLOSED"], assignee?: "all"|"me"|"unassigned"|"user",
                       assigneeUserIds?: [id], lifecycleStageIds?: [id], tagIds?: [id], channelIds?: [id],
                       priority?: "ALL"|"URGENT"|"HIGH"|"MEDIUM"|"LOW", unreplied?: bool,
                       sort?: "newest"|"oldest"|"unreplied_first"|"longest_waiting", segmentId?: id|null}
                      (Pydantic extra="forbid" -> 422 on any unknown key)
ConversationEventItem {id, eventType, actorName, actorUserId, fromValue, fromLabel, toValue, toLabel,
                       closeReasonId, closeReasonName, note, payload, createdAt}
ShortcutItem          {workflowId, name}
```

`fromLabel` / `toLabel` resolve tenant-scoped: THREAD status ids -> their label, user ids -> the
user's display name (never an unscoped `get_by_id`), lifecycle status ids -> the core stage label.

### 5.2 Data model

```
conversation_events(id pk, tenant_id idx, workspace_id fk workspaces, contact_id fk contacts,
  event_type, actor_user_id null, actor_external_agent_id null, from_value null, to_value null,
  close_reason_id null fk close_reasons, note text null, payload_json JSON(none_as_null=True),
  created_at UTCDateTime not null)
  ix (tenant_id, workspace_id, created_at) | (tenant_id, contact_id, created_at) | (tenant_id, event_type, created_at)

close_reasons(id pk, tenant_id idx, workspace_id fk, name, sort_order int, is_active bool default true,
  created_at, updated_at)                       -- name unique per workspace, app-enforced (lower())

inbox_views(id pk, tenant_id idx, workspace_id fk, name, owner_user_id, is_shared bool,
  filter_json JSON(none_as_null=True), segment_id null, sort_order int, created_at, updated_at)

contacts += last_agent_message_at UTCDateTime null idx
```

### 5.3 Exact event-writer call sites

| Event | File | Function / anchor |
|---|---|---|
| `opened` (new thread) | `services/inbound_service.py` | the contact-creation branch (the `Contact(...)` build around L338-355, next to `initial_status_id`) |
| `opened` (gateway create) | `services/public_gateway_service.py` | `create_contact` (the `Contact(...)` build around L516-525) |
| `reopened` / `unsnoozed` (auto) | `services/inbound_service.py` | `handle_message`, capture the previous status key BEFORE `contact.status_id = ... "OPEN"` (L194) and write before the `self.db.commit()` at L199 |
| `closed` / `reopened` / `snoozed` / `unsnoozed` (manual) | `services/conversation_service.py` | `patch_thread`, in the `if status is not None:` block (L~449) - capture previous, write before the single `self.db.commit()` at the end |
| `assigned` / `unassigned` | `services/conversation_service.py` | `patch_thread`, in the `if assigned_user_id is not ...:` block (L~419), both the native and the embed/external branch |
| `closed` with reason + note | `services/conversation_service.py` | new `close_thread(contact_id, tenant_id, close_reason_id, note, actor)` -> validates the reason, delegates to the same status mutation + `_publish_contact_updated` |
| `lifecycle_changed` | `services/lifecycle_service.py` | `move()` - the ONE lifecycle write seam, already shared by `ConversationService.move_lifecycle`, `patch_thread` and the gateway PATCH |
| `first_agent_reply` | `services/message_service.py` | new private `_mark_agent_message(contact, now)` replacing the three bare `contact.last_message_at = now` assignments (send text L~367, send media L~433, structured/template L~484); sets `last_message_at` + `last_agent_message_at` and writes the event when `event_service.is_first_reply_pending(db, contact)` |
| `comment_added` | `services/message_service.py` | `add_internal_note`, before its `self.db.commit()` (L~709). The gateway `add_comment` delegates here, so both paths are covered by the one call |

`is_first_reply_pending` = one indexed query: latest row for `(tenant_id, contact_id)` where
`event_type IN ('opened','reopened','first_agent_reply')` ordered `created_at DESC` - pending iff it
is not already `first_agent_reply`.

### 5.4 Backfill

Runs in three places, all calling the same `event_service.backfill_tenant` / a set-based SQL twin:

1. The new Alembic revision (Postgres, after the DDL): `INSERT INTO conversation_events (... 'opened', created_at, payload_json='{"backfilled": true}') SELECT ... FROM contacts c WHERE NOT EXISTS (SELECT 1 FROM conversation_events e WHERE e.contact_id = c.id)`, then the CLOSED and assigned variants, then `UPDATE contacts SET last_agent_message_at = (SELECT max(created_at) FROM conversation_messages m WHERE m.contact_id = contacts.id AND m.sender_type = 'AGENT')`.
2. `bootstrap.update_tenant` for the new version (the ORM twin, per tenant) + close-reason seeding for every workspace that has none. The version guard must be `from_version < <new>` style, not an equality on `0.2.0`, so it still runs for a tenant that A2 already moved to `0.3.0`.
3. `bootstrap.install_tenant` calls the same function unconditionally (self-healing, exactly like `lifecycle_service.backfill_tenant` does today).

Idempotency guard: "this contact has no events yet". Re-running is a no-op.

### 5.5 Seeded close reasons

`General Inquiry` (0), `Sales Inquiry` (1), `Payment Issue` (2), `Others` (3) - the respond.io
default set (`24-evidence/respondio-survey/set-conversations.png`). All editable and deletable; no
code path looks one up by name (DoD rule 3).

### 5.6 Shortcut run context

```
trigger.triggeredBy = "event"        trigger.action = "shortcut"
trigger.recordId    = <contact id>   trigger.record.* = the omnichannel_contact fact_attrs
trigger.actor.{id,name,email}        = the real actor (real admin under impersonation)
```
A shortcut workflow reaches the thread with the existing `omnichannel.send_message` action by
merge-rendering `{{trigger.record.id}}` into its `contactId` field - no new action needed.

## 6. Risks + mitigations

- **A new core workflow-run entry point.** `run_shortcut` is the first non-bus way to start a
  published run. Mitigation: it must go through the extracted `create_run_for_event`, never a fresh
  copy - that is what preserves the Code-node authorization gate, correlation assignment and the
  serialized-run dispatch. Reviewer: reject a duplicated `WorkflowRun(...)` construction.
- **WS publish on every new mutation path.** `POST /{id}/close` and the shortcut route must reuse
  `_publish_contact_updated` (realtime + consumer webhook) - the omnichannel invariant is "every
  mutation path publishes". A close that only writes an event would leave other agents' inboxes stale.
- **Plan 23 merge.** Overlap is `inbox/page.tsx` and `thread-list.tsx` (cosmetic on 23's side).
  Keep the rail, filter bar and dialogs in NEW files; do not reflow `thread-list.tsx` beyond
  removing the two `<Select>`s. Never introduce `text-[Npx]`, `transition-all`, or an unlabelled
  icon button - those are plan-23 hard-fails and will land on this code after the merge.
- **Event volume on the hot path.** One extra indexed SELECT + one INSERT per inbound / send.
  Acceptable; the indexes are the ones A9 needs anyway. Retention pruning -> backlog.
- **Sort correctness under pagination.** Every ordering must end with `Contact.id.asc()`; a test
  pins page 0 + page 1 for each of the four sorts.
- **Two Phase-A lanes on one module.** A2 (`.claude/worktrees/s26`) edits `contact_repository.py`, `permissions.csv`, `manifest.json` and `bootstrap.update_tenant` in the same files A3 does. Keep A3's repository work inside `list_threads` (A2 adds a separate `list_contacts`), and re-check the manifest version + Alembic `down_revision` at merge time.
- **Shared Postgres across worktrees.** Lane s27 owns `foundryx_service_s27`; reseed only from the
  branch you are serving (`sync_permissions` is delete-by-module).
- **`create_all` never ALTERs.** `last_agent_message_at` needs the ADD COLUMN IF NOT EXISTS guard in
  `bootstrap.create_schema_and_tables` as well as the migration, or dev DBs silently lack it.

## 7. Backlog candidates (proposed ids - the lane coder registers them in `documentation/backlogs/backlog.md` on close, each linking back to this plan)

`BL-SS-051..056` are taken by plan 26, so this slice's ids start at 057.

| Proposed id | Title | Priority |
|---|---|---|
| BL-SS-057 | Omnichannel: @mention a workspace member in an internal comment (notification + `mention` event) | P2 |
| BL-SS-058 | Omnichannel: advanced filter groups on the rule engine + respond.io-parity "save as view" popover (needs A2 `contact_segments`) | P2 |
| BL-SS-059 | Omnichannel: per-view unread / thread counts on the inbox rail (cheap aggregate; A9 territory) | P2 |
| BL-SS-060 | Omnichannel: `conversation_events` retention pruning + archive job | P1 |
| BL-SS-061 | Omnichannel gateway: close-with-reason on `PATCH /api/v1/omnichannel/contacts/{identifier}` + a read-only events endpoint (consumer-guide diff required) | P1 |
| BL-SS-062 | Omnichannel: auto-close after N days of inactivity + AI-generated closing notes (roadmap G17 / phase B2) | P1 |
| BL-SS-063 | Workflow engine: shortcut with run inputs (prompt the agent for a value before firing) | P2 |
| BL-SS-064 | Workflow engine: surface `entity.shortcut` for core entities (a Shortcuts entry on the Resource form's `...` menu) | P2 |
| BL-SS-065 | Omnichannel: full inbox mobile polish beyond the single-pane switch (thread search, drawer header wrapping at 375px) | P1 |

## 8. Flagged for the user (planner deviations from the 2026-09-06 decision set - none are blocking)

1. **Table naming (D-A3-8).** The decision said `omni_conversation_events`; every sibling table in
   `app_omnichannel` is unprefixed, so the plan uses `conversation_events` (plus `close_reasons`,
   `inbox_views`). Same table, different literal name.
2. **`from` / `to` columns (D-A3-9)** are `from_value` / `to_value` - `from` is a Python keyword.
3. **Saved-view permission split (D-A3-11).** D-A3-6 implied `inbox_views.manage` for all view
   writes; gating a personal view behind a manage key would hide the feature from the agents who
   live in the inbox, so personal views need only `conversations.read` and `inbox_views.manage`
   gates shared views. Say the word and it reverts to one key.
4. **Close-reason delete is a 409 when referenced (D-A3-13)**, with Deactivate as the UI answer.
   The alternative (cascade the reason off historical events) loses report history.
5. **The Activities feed and `GET /{id}/events` are a scope addition.** The decision set did not ask
   for an events UI, but without one the whole events table is invisible until A9 and the E2E run
   has nothing to click. It is one route plus one component.
6. **The inbox goes single-pane below `lg` (D-A3-15)** - more than "add a rail". At 375px today the
   shell is a fixed `grid-cols-[320px_1fr]` with the conversation clipped off-screen, so a rail on
   top of that would be unusable and would fail the responsive mandate.
7. **The shortcut trigger is named `entity.shortcut`, not `omnichannel.shortcut`**, and it required
   extracting `create_run_for_event` out of core `app/workflow_engine/entity_events.py`. That is a
   core refactor inside a module slice; it is the only way to fire a PUBLISHED version without
   duplicating the Code-node authorization gate.
8. **Shortcut permissions - DECIDED (main session, 2026-09-06).** The plan originally reused
   `workflows.run` per D-A3-5, but a typical Agent-level user will not hold it, so the Shortcuts
   control would be invisible for most inbox users until the tenant grants it. Decision: a new
   `conversations.shortcut` key gates BOTH `GET /shortcuts` and `POST /shortcuts/{workflowId}`
   (superseding the `conversations.read`+`workflows.read` / `conversations.reply`+`workflows.run`
   pairs) - the workflow itself stays admin-authored (Publish is still gated `workflows.manage`).
   AC-IVE-36/37/41 amended to match.
9. **`contacts.last_agent_message_at` is a new denormalized column** (D-A3-12), not in the decision
   set. Unreplied and Longest waiting cannot be indexed without it.
10. **Manifest version collision with plan 26** (both A2 and A3 bump to `0.3.0`) - D-A3-16 says the
    second lane to merge takes the next number and rebases its migration parent.
11. **No `resolved` event type.** Roadmap D9 listed "resolved" alongside closed; `closed` +
    `close_reason_id` carries the same information, so the plan keeps the ten types from D-A3-1.
12. **`POST /{id}/close` on an already-CLOSED thread - DECIDED (review round 1, 2026-09-06).**
    Previously a no-op 200 that silently dropped the supplied reason/note (`patch_thread`'s
    `closed` write only fires on an actual status change). Now `409 {code: "already_closed",
    message}` - reopen then close again is the way to change the reason. `ThreadAlreadyClosed`
    (`services/conversation_service.py`), mapped in the router.

### Review round 1 - frontend follow-ups (pending)

Backend-focused review round 1 (2026-09-06) also found frontend gaps, out of scope for the backend
coder that closed the findings above - queued here for the next frontend pass on this branch:

5. **Confirm dialogs → deferred actions.** The saved-view delete (`inbox-view-rail.tsx`) and the
   close-reason delete (`workspace-close-reasons-tab.tsx`) use hand-rolled confirm `AlertDialog`s;
   every other module delete on this branch goes through the deferred-actions grace-window pattern
   (undo toast). Register both deletes as deferred-action handlers
   (`modules/omnichannel/deferred_actions.py`) and swap the dialogs for `DeferredActionButton`.
8. **Missing `DialogDescription`.** `inbox-view-dialog.tsx` and `close-thread-dialog.tsx` render a
   `DialogTitle` with no `DialogDescription` (a11y - Radix warns on this).
9. **Dead `comment_added` branch.** `activity-feed.tsx` has a rendering branch for the
   `comment_added` event type that can never fire in practice (internal notes render as authored
   bubbles, not activity-feed lines) - drop it or gate it behind an actual code path.
12. **Shortcut success toast has no link.** AC-IVE-39 says "running one shows a success toast
    linking to the run"; the shipped toast does not link anywhere - wire it to the run's route.
