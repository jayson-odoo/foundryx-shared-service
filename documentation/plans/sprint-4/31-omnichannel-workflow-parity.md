# 31 - Omnichannel workflow parity v1 (A5a triggers + simple steps, A5b stateful steps)

> **Contract:** `31-omnichannel-workflow-parity-acceptance-criteria.md` (70 ACs). This plan fulfils it.
> **Program:** slice **A5** of `24-omnichannel-respondio-parity-roadmap.md` (gaps G10 + G11, roadmap
> D7 and D11). Supersedes BL-128.
> **Base:** `origin/main` at `58759ed` (plan 23 + A1 + A3 + A2). Every seam path below was read at
> that commit (worktree `.claude/worktrees/s26`, `7f627d1`, identical content).
> **Branch / lane:** `sprint-4/31-workflow-parity`, worktree `.claude/worktrees/s31`, backend `:8010`
> on DB `foundryx_service_s31`, frontend `:3009`, `agent-browser --session s31`. Port **8011 is the
> code runner and is never a lane port.** Each worktree gets its OWN `npm ci` (never a shared
> `node_modules`).
> **Merge points:** rebase onto `main` after plan 29 (A4) and plan 28 (A8) land. A4 supplies the
> `omnichannel_broadcast` `completed` event (AC-WFP-22) and closes BL-SS-084; A8 supplies
> `omnichannel.assign_conversation` (AC-WFP-23). Neither blocks S0-S2 - see §7.

## 1. Why

respond.io's Workflows surface is the automation spine the customer runs their day on: ten triggers
and roughly twenty steps, with **Ask a Question** (a step that sends a message and then waits for the
contact's reply) as the piece that makes a workflow feel like a conversation rather than a fire-and-
forget rule. Today Foundryx has a full DAG engine, one omnichannel trigger (`message_received`), two
omnichannel actions (`get_contact`, `send_message`), IF, and plan 19's serialized-run machinery - but
no conversation triggers, no contact-mutation steps, no wait, no business hours, no HTTP request, and
no way to suspend a run.

A5 closes G10 and G11 by (a) making module trigger registration fully **registry-driven** so no
further core edit is needed per trigger, (b) adding conversation and contact triggers that ride
**existing** domain events wherever one exists, (c) routing every new step through the **one existing
write seam** per concern so a workflow write is indistinguishable from a UI write (same conversation
event, same realtime push, same consumer webhook), and (d) giving the executor a generic **park and
resume** capability that Ask a Question and Wait both consume, reusing plan 19's serialized FIFO for
per-contact ordering.

## 2. Architecture

### 2.1 Core vs module split

```
CORE (app/workflow_engine, app/services, app/permissions)
  registry.py         TriggerDef += event_action, event_entity_type, refine, fire_guard
                      ActionDef  += ports (branching), permission (mirrors workflows.code)
  entity_events.py    _trigger_types_for  -> registry-driven (entity.* stays hardcoded)
                      _passes_refine      -> delegates to TriggerDef.refine
                      _match_and_enqueue  -> calls TriggerDef.fire_guard before _create_run
                      build_event_trigger_payload -> generic payload["eventData"] = extra
  executor.py         _walk() extracted; park (WorkflowPaused) + resume_run(); branch ports
  schemas.py          definition_issues += "Ask a question requires serialized execution"
  serialization.py    unchanged (resume re-enters dispatch_persisted_run)
  models/workflow.py  RUN_WAITING; WorkflowRun += paused_node_id, resume_state_json
  actions/http_actions.py   NEW core action http.request   (gated workflows.http)
  services/url_guard.py     NEW shared SSRF guard (module webhook guard delegates to it)
  permissions.csv     + workflows,Workflows,http,...

MODULE (modules/omnichannel)
  workflow_nodes.py         7 new TriggerDefs + 11 new/extended ActionDefs
  services/workflow_actions.py   every executor (one write seam each)
  services/workflow_waits.py     NEW - wait rows, claim, resume, sweep
  services/event_service.py      + emit_entity_event for opened/closed/assigned
  services/inbound_service.py    + resume-before-trigger hook
  services/business_hours.py     NEW - evaluate(workspace, now)
  models.py                 workflow_waits, workflow_contact_fires,
                            omnichannel_settings += business_hours_json/business_timezone,
                            workspaces += round_robin_cursor
  alembic 0013_omni_workflow_waits
  worker.py                 celery task omnichannel.wait_sweep (beat, 60 s, module-guarded)
```

**Why the wait table is module-owned and the park is core-owned.** Parking is an engine concern
(status, context snapshot, resume dispatch) so it lives on `workflow_runs`. The *index from a contact
to a parked run*, the answer spec and the retry counters are omnichannel concerns, so they live in
`app_omnichannel.workflow_waits`. Core never imports the module; the module calls
`executor.resume_run(...)`. This is the same shape as `form.submitted` (core trigger, module-free) and
the capability seam.

### 2.2 The generic seams A5 adds to core (the reusable part)

| Seam | Signature | Replaces |
|---|---|---|
| `TriggerDef.event_action` | `Optional[str]` | the `_trigger_types_for` if-chain |
| `TriggerDef.event_entity_type` | `Optional[str]` | the publish denormalization if-chain (F3) |
| `TriggerDef.refine` | `(config, ev) -> bool` | the `_passes_refine` if-chain |
| `TriggerDef.fire_guard` | `(db, wf, config, ev) -> bool` | (new) once-per-contact |
| `ActionDef.ports` | `tuple[str, ...]` | the executor's `kind == "if"` special case |
| `ActionDef.permission` | `Optional[str]` | the hardcoded `workflows.code` gate |
| `WorkflowPaused` + `resume_run` | executor | (new) Ask a question, Wait |
| `app/services/url_guard.py` | `assert_public_https_url(url)` | the module-local SSRF guard |

The `entity.created/updated/deleted/status_changed` mapping stays hardcoded in `_trigger_types_for`
(it is the core entity bus, not a registry item); everything else resolves from the registry. A
parity test asserts `form.submitted` and `omnichannel.message_received` produce byte-identical
dispatch behaviour before and after the refactor.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D-A5-1 | Triggers ride EXISTING events wherever one exists. New emissions are added only for conversation **opened / closed / assigned**, from the ONE `event_service.record()` seam, allowlisted by event type | Audit at `58759ed`: `conversation_events` rows are written but no workflow entity event is emitted for them. Tags, custom fields and lifecycle already emit (`ContactProfileService`, `status_machine`) and are refined, never re-emitted |
| D-A5-2 | The conversation events are emitted with `entity_type = "omnichannel_contact"` and a new `action` (`conversation_opened` / `_closed` / `_assigned`) | Reuses the registered `WorkflowEntity` so `record_facts` populates `trigger.record.*` for free; a synthetic `omnichannel_conversation` entity would resolve zero facts |
| D-A5-3 | `omnichannel.lifecycle_changed` is a real TriggerDef bound to the machine's existing `status_changed` emission, NOT a frontend-only alias | A frontend alias over `entity.status_changed` would show an EMPTY status picker (`omnichannel_contact` is `has_status=False` because the machine is workspace-scoped) - a foolproof-UI violation. The TriggerDef carries its own workspace + stage pickers and refines on `extra.from_status_id/to_status_id`. Still zero new emissions |
| D-A5-4 | "Trigger once per contact" = a module table `workflow_contact_fires` claimed through the new `TriggerDef.fire_guard` seam, unique on (tenant_id, workflow_id, contact_id) | The claim must be atomic with run creation and must survive a republish; a unique-constraint insert is the only race-free form |
| D-A5-5 | Every step routes through the existing service seam: `patch_thread` (assign / open), `close_thread` (close), `lifecycle_service.move` (lifecycle), `ContactProfileService` (tags / fields), `MessageService.send_message` / `add_internal_note` (send / comment) | One write seam per concern is the house rule; it is also the only way a workflow write emits the same conversation event, realtime push and consumer webhook as the UI |
| D-A5-6 | Ask a question parks the run: core `WorkflowPaused` -> `workflow_runs.status = waiting` + `paused_node_id` + `resume_state_json`; resume flips back to `pending` and re-enters `dispatch_persisted_run` | Reusing the pending-dispatch path gives serialized FIFO, the Redis lease, the heartbeat and the crash recovery for free instead of a second scheduler |
| D-A5-7 | Publish REFUSES an Ask-bearing graph that is not `execution.mode = serialized` with a correlation key | Two runs answering the same contact would race the single wait row. Mirrors plan 19's stateful-AI rule exactly (same message shape, front and back parity) |
| D-A5-8 | An inbound message that resumes a parked wait is CONSUMED: `omnichannel.message_received` is not dispatched for it | Otherwise the reply that answers a question also starts a fresh run of the same workflow, which immediately asks again. Flagged (F2) as a semantic worth confirming |
| D-A5-9 | One open question per contact. A second Ask node for a contact that already has an open wait FAILS the node | Two concurrent waits on one contact have no deterministic owner for the next message. A queue is not v1 |
| D-A5-10 | Timeouts are swept by a 60 s beat task (`omnichannel.wait_sweep`), module-guarded in the core worker exactly like `webhooks.retry_due` | Precedent exists in `app/workflow_engine/worker.py`; no second beat host |
| D-A5-11 | `http.request` is a CORE action; the SSRF guard moves to `app/services/url_guard.py` and the module's `webhook_service.validate_callback_url` / `assert_deliverable` delegate to it | Core must not import a module. One guard, two callers - never a second copy that drifts |
| D-A5-12 | `http.request` is https-only and gated by the new core permission `workflows.http`, mirroring `workflows.code` | An API-key-free, tenant-authored outbound HTTP call is the same blast radius as a Code node. Plain http is a backlog item, not a v1 hole |
| D-A5-13 | Business hours = `omnichannel_settings.business_hours_json` + `business_timezone` (workspace row, tenant-default row when the workspace has none), edited on a new workspace-form tab | The settings table + the NULL-workspace default pattern already exist; a new table for two columns is waste |
| D-A5-14 | Branching actions declare `ports=(...)` and return `{"branch": ...}`; the walker generalizes its `kind == "if"` special case | Ask a question and Business hours both need it, and so will every future branching action; a per-node special case in the executor does not scale |
| D-A5-15 | Round-robin picks across WORKSPACE members with a cursor on `workspaces.round_robin_cursor`; A8's team round-robin stays A8's | No new pointer table; deterministic; A8's `team_assignment_service` is a different scope and is not duplicated |
| D-A5-16 | Send message gains a template mode over the SAME `MessageService.send_message` (`messageType="TEMPLATE"`), not a new action | The service already validates approval and placeholder counts; the action only exposes it |
| D-A5-17 | The answer is NOT auto-saved to a contact field. The author chains `omnichannel.update_field` with `{{ nodes.<id>.answer }}` | Composition over configuration; the update step already validates the field's type, which a hidden auto-save would have to duplicate |
| D-A5-18 | Answer types are exactly `text`, `choice`, `number`, `email`, `phone`. Date, url, rating and location are backlog | Five types cover the customer's audited use; each type is an 8-layer touch (catalog, drawer, validator, renderer, tests) |
| D-A5-19 | Palette placement: `Wait` and `Business hours` go in the **Logic** section (they are flow control), everything else in **Actions**. The palette derives the Logic section as `IF_CATALOG + actions whose category is 'Logic'` | Keeps the palette structure (searchable collapsed sections) with a one-line change, no parallel component |
| D-A5-20 | A5b adds ONE core Alembic migration (`workflow_runs.paused_node_id`, `resume_state_json`) | Deviation from the brief's "core migration = none", which addressed only the permission CSV. Flagged (F1) |

## 4. Slices (one Sonnet coder each, sequential on the branch)

| Slice | Content | Size | ACs |
|---|---|---|---|
| **S0 FE catalog + mock** | `lib/workflow-catalog.ts` entries for all 7 triggers + 13 actions; `types/workflows.ts` field types + ports + metadata additions; `node-config-drawer.tsx` new field-type branches; `workflow-node.tsx` generic multi-port handles; `node-palette.tsx` Logic-section derivation; `workflow-metadata-service.mock.ts` seeds workspaces / tags / fields / stages / reasons / members / templates; `lib/workflow-doc.ts` Ask-node serialized rule; vitest; agent-browser smoke at 375 + 1280 | M | 01-06 |
| **S1 BE triggers** | registry seams (`event_action`, `event_entity_type`, `refine`, `fire_guard`, `ports`, `permission`); `_trigger_types_for` / `_passes_refine` / publish denormalization refactor; `event_service.record` emissions; 7 TriggerDefs; `workflow_contact_fires` + claim; metadata endpoint additions; module migration `0013`; pytest | L | 07-22 |
| **S2 BE simple steps** | 9 new + 2 extended ActionDefs and executors, `workspaces.round_robin_cursor`, template send mode, `workflow.trigger` child-run action; pytest | L | 23-35 |
| **S3 Wire + E2E (A5a)** | swap mocks for real metadata, permission gating in the drawer, Logs rendering, evidence run, report rows | M | 36-40 |
| **S4 BE waits** | core park / resume (`WorkflowPaused`, `resume_run`, `_walk` extraction, `RUN_WAITING`, core migration); `workflow_waits` table + `workflow_waits.py`; `omnichannel.ask_question` + `omnichannel.wait`; inbound resume hook; beat sweep; cancel / retention behaviour; pytest | XL | 41-54 |
| **S5 BE business hours + http** | `url_guard.py` extraction + module delegation; `http.request` core action + `workflows.http` CSV + grant sweep; `business_hours.py` + settings columns + routes; pytest | M | 55-62 |
| **S6 Wire + E2E (A5b)** | Business hours workspace tab, Ask drawer, Waiting run badge, evidence run, Test Execution Report | M | 63-70 |
| **Review** | `reviewer` agent on **Opus** (new outbound HTTP surface + a new run state + new emission points + a new permission = security grade), then `/codex-review` | - | - |

S4 is the only slice that touches the core executor's walk; it must not be run in parallel with any
other slice.

## 5. Contracts

### 5.1 Registry additions (backend `app/workflow_engine/registry.py`)

```python
@dataclass(frozen=True)
class TriggerDef:
    ...
    event_action: Optional[str] = None          # domain-event action this trigger listens to
    event_entity_type: Optional[str] = None      # denormalized Workflow.trigger_entity_type
    refine: Optional[Callable[[Dict, Dict], bool]] = None          # (config, ev) -> bool
    fire_guard: Optional[Callable[[Session, Any, Dict, Dict], bool]] = None

@dataclass(frozen=True)
class ActionDef:
    ...
    ports: Tuple[str, ...] = ()                  # non-empty = branching
    permission: Optional[str] = None             # e.g. "workflows.http"
```

### 5.2 Triggers (module `omnichannel`, all `category="Triggers"`)

| key | event_action | event_entity_type | fields | refine |
|---|---|---|---|---|
| `omnichannel.conversation_opened` | `conversation_opened` | `omnichannel_contact` | `workspaceId?`, `channelId?`, `reopenOnly?` (bool), `triggerOncePerContact?` | workspace, channel, `extra.isReopen` |
| `omnichannel.conversation_closed` | `conversation_closed` | `omnichannel_contact` | `workspaceId?`, `closeReasonId?`, `triggerOncePerContact?` | workspace, `extra.closeReasonId` |
| `omnichannel.conversation_assigned` | `conversation_assigned` | `omnichannel_contact` | `workspaceId?`, `assigneeUserId?`, `onUnassign?` (bool), `triggerOncePerContact?` | workspace, assignee, unassign |
| `omnichannel.contact_tag_added` | `updated` | `omnichannel_contact` | `workspaceId?`, `tagId?`, `triggerOncePerContact?` | `changes["tags"]`: `tagId in to - from` |
| `omnichannel.contact_tag_removed` | `updated` | `omnichannel_contact` | as above | `changes["tags"]`: `tagId in from - to` |
| `omnichannel.contact_field_changed` | `updated` | `omnichannel_contact` | `workspaceId?`, `fieldKey` (required), `newValue?`, `triggerOncePerContact?` | `changes["customFields.<fieldKey>"]`, optional `to` match |
| `omnichannel.lifecycle_changed` | `status_changed` | `omnichannel_contact` | `workspaceId?`, `fromStageId?`, `toStageId?`, `triggerOncePerContact?` | `extra.from_status_id` / `to_status_id` |
| `omnichannel.broadcast_completed` (A4) | `completed` | `omnichannel_broadcast` | `workspaceId?` | workspace |
| `omnichannel.message_received` (extend) | `received` | `omnichannel_message` | `channelId?` **+ `firstMessageOnly?`, `keywordContains?`, `triggerOncePerContact?`** | existing channel + the two new filters |

Trigger context keys (flattened by the executor from `payload["eventData"]`, one nesting level,
camelCase preserved):

```
trigger.contact.id / .name / .phone        trigger.conversationId      trigger.workspaceId
trigger.record.<fact>                      trigger.action              trigger.actor.name / .email
conversation_opened   -> trigger.isReopen, trigger.channelId
conversation_closed   -> trigger.closeReasonId, trigger.closeReasonLabel, trigger.note
conversation_assigned -> trigger.assigneeUserId, trigger.previousAssigneeUserId, trigger.assignedVia
contact_tag_*         -> trigger.tagId, trigger.tagName
contact_field_changed -> trigger.fieldKey, trigger.fromValue, trigger.toValue
lifecycle_changed     -> trigger.fromStatus, trigger.toStatus, trigger.toStageLabel
broadcast_completed   -> trigger.broadcastId, trigger.broadcastName, trigger.sent, trigger.failed
message_received      -> (existing) + trigger.message.isFirstMessage
```

### 5.3 Actions

```
omnichannel.assign_conversation      (A8's if merged; else defined here)
  fields  contactId text req merge | mode select req [user|round_robin|unassign] (+ team from A8)
          userId text show_when(mode,user) merge | workspaceId omnichannelWorkspace show_when(mode,round_robin)
  outputs assignedUserId, assigned                 -> patch_thread

omnichannel.add_tag / omnichannel.remove_tag
  fields  contactId text req merge | tagId omnichannelTag req (scoped by workspaceId)
  outputs tags (list), changed (bool)              -> ContactProfileService.patch

omnichannel.update_field
  fields  contactId text req merge | workspaceId omnichannelWorkspace req
          fieldKey omnichannelContactField req | value text merge | clear select [no|yes]
  outputs fieldKey, value                          -> ContactProfileService.patch

omnichannel.update_lifecycle
  fields  contactId text req merge | workspaceId req | toStageId omnichannelLifecycleStage req
  outputs fromStageId, toStageId, stageLabel       -> lifecycle_service.move

omnichannel.open_conversation
  fields  contactId text req merge
  outputs status, changed                          -> patch_thread(status="OPEN")

omnichannel.close_conversation
  fields  contactId req merge | workspaceId req | closeReasonId omnichannelCloseReason req
          note textarea merge
  outputs status, closeReasonId                    -> close_thread

omnichannel.add_comment
  fields  contactId req merge | body textarea req merge
  outputs messageId                                -> MessageService.add_internal_note

omnichannel.send_message  (EXTEND)
  fields  contactId req merge | mode select req [text|template]
          message textarea show_when(mode,text) req merge
          templateId whatsappTemplate show_when(mode,template) req
          templateVariables templateParams show_when(mode,template) (each value mergeable)
  outputs messageId, status                        -> MessageService.send_message

omnichannel.ask_question           ports = ("answer","timeout")
  fields  contactId req merge | mode select [text|template] + the send fields above
          answerType select req [text|choice|number|email|phone]
          choices choiceList show_when(answerType,choice) req
          retryLimit select [0|1|2|3] (default 1) | retryMessage textarea merge
          timeoutValue text req | timeoutUnit select req [minutes|hours|days]
  outputs answer, answerRaw, answerKey, timedOut, reason

omnichannel.wait                   ports = ()  (single out)
  fields  waitValue text req | waitUnit select req [minutes|hours|days]
  outputs resumedAt

omnichannel.business_hours         ports = ("inside","outside")   category Logic
  fields  workspaceId omnichannelWorkspace req
  outputs isOpen, checkedAt, timezone

workflow.trigger                   (CORE action, category Actions)
  fields  workflowId workflowRef req | contactId text merge | payload textarea merge (JSON)
  outputs runId, workflowId

http.request                       (CORE action, permission "workflows.http")
  fields  method select req [GET|POST|PUT|PATCH|DELETE] | url text req merge
          headers keyValue (values mergeable, never traced)
          bodyMode select [none|json|text] | body textarea show_when(bodyMode,json|text) merge
          timeoutSeconds select [5|10|20|30]
  outputs statusCode, ok, body, json, durationMs
```

Caps (module constants, not tenant-configurable in v1): wait deadline <= 30 days, retry limit <= 3,
choices <= 10, HTTP timeout <= 30 s, HTTP response read <= 256 KB, traced body <= 8 KB.

### 5.4 Wait table (module schema `app_omnichannel`, migration `0013_omni_workflow_waits`)

```
workflow_waits
  id              String  pk
  tenant_id       String  not null  index
  workspace_id    String  not null  FK workspaces.id  index
  contact_id      String  not null  FK contacts.id
  run_id          String  not null            -- core workflow_runs.id, plain column (BL-030)
  workflow_id     String  not null
  node_id         String  not null
  kind            String  not null            -- 'question' | 'delay'
  answer_spec_json JSON(none_as_null=True)    -- {answerType, choices[], retryLimit, retryMessage}
  retry_count     Integer not null default 0
  deadline_at     UTCDateTime  not null  index
  is_test         Boolean not null default False
  created_at / updated_at  UTCDateTime
  UNIQUE (tenant_id, contact_id)              -- D-A5-9: one open wait per contact
  INDEX  (tenant_id, deadline_at)             -- the sweep's claim

workflow_contact_fires
  id, tenant_id (index), workflow_id, contact_id, created_at
  UNIQUE (tenant_id, workflow_id, contact_id)

omnichannel_settings  += business_hours_json JSON(none_as_null=True), business_timezone String
workspaces            += round_robin_cursor String (nullable)
```

`bootstrap.create_schema_and_tables` gets the matching `ADD COLUMN IF NOT EXISTS` mirrors for the
three added columns (a `scripts/init_db` database never runs module Alembic).

`business_hours_json` shape:
`{"mon": [{"from": "09:00", "to": "18:00"}], "tue": [...], ..., "sun": []}` - a window whose `to` is
lexically <= `from` is an overnight window ending the next day.

### 5.5 Core migration (A5b, one revision, id <= 32 chars)

`alembic revision -m "workflow run pause"` -> `revision = "wf_run_pause_s31"`:
`workflow_runs.paused_node_id` (String, nullable), `workflow_runs.resume_state_json`
(JSON, nullable). No backfill needed (both nullable, no existing row is parked). Add
`import app.models.utc_datetime` by hand if autogenerate emits UTCDateTime columns.

### 5.6 Park / resume contract (core)

```python
class WorkflowPaused(Exception):
    """An action asks the engine to suspend this run at the current node."""
    def __init__(self, *, output: dict | None = None): ...

# executor.py
def _walk(db, run, doc, ctx, active, start_index, completed_stateful) -> tuple[bool, int | None]
def run_workflow(db, run_id):      # start OR resume, chosen by run.resume_state_json
def resume_run(db, run_id, *, node_id, output, branch) -> WorkflowRun
```

- Park: catch `WorkflowPaused` inside the node loop -> `rn.status = NODE_SUCCESS` with
  `output_json = {"parked": True, **exc.output}`, `run.status = RUN_WAITING`,
  `run.paused_node_id = node.id`, `run.resume_state_json = {"ctx": json_safe(ctx), "active":
  sorted(active), "completedStateful": sorted(completed_stateful), "index": index}`, commit, return.
- Resume: `resume_run` re-reads the run `FOR UPDATE` (must be `waiting`), merges `output` into
  `ctx` via `set_node_output`, adds the taken port's targets to `active`, clears
  `resume_state_json` / `paused_node_id`, sets `status = RUN_PENDING`, then calls
  `dispatch_persisted_run`. `run_workflow` restores from the snapshot it left instead of
  `_ctx_from_payload`, and skips (without re-running) every node whose `WorkflowRunNode` row is
  already terminal.
- `_live_running_run_id` (serialization) is unchanged: `waiting` is not `running`, so a parked run
  never blocks its correlation scope forever.

### 5.7 Internal API

```
GET   /omnichannel/workspaces/{id}/business-hours   -> {timezone, windows}
PUT   /omnichannel/workspaces/{id}/business-hours   {timezone, windows}    (workspaces.manage)
GET   /workflows/metadata  += omnichannelWorkspaces: [{id, name, contactTags[], contactFields[],
        lifecycleStages[], closeReasons[], members[], templates[]}]
```

No public-gateway (`/api/v1/omnichannel/*`) surface changes in A5, so
`documentation/omnichannel/consumer-integration-guide.md` needs **no diff** - the reviewer should
confirm the diff contains no `Rio*` / `api_v1.py` change rather than demanding a guide edit.

### 5.8 Beat task

`omnichannel.wait_sweep`, 60 s, registered in `app/workflow_engine/worker.py::beat_schedule` next to
`retry-due-webhooks` and guarded the same way (a missing module import is a no-op). Batch <= 200 rows
per tick, claimed with `UPDATE ... WHERE deadline_at <= now() ... RETURNING` semantics (or the
existing guarded-claim pattern under SQLite tests).

## 6. Seam paths verified at `58759ed`

| Path | What it is | A5 touches |
|---|---|---|
| `service_backend/app/workflow_engine/registry.py` | `TriggerDef` / `ActionDef` / `NodeField(show_when, entity_filter)` | new fields (§5.1) |
| `.../entity_events.py:281 _trigger_types_for`, `:319 _passes_refine`, `:368 _match_and_enqueue`, `:398 build_event_trigger_payload`, `:589 create_run_for_event` | dispatch chain | registry-driven refactor + `fire_guard` |
| `.../executor.py:39 _ctx_from_payload`, `:142 _execute_node`, `:223 run_workflow` | the walk | generic port branching, park / resume |
| `.../serialization.py:201 _live_running_run_id`, `:349 dispatch_persisted_run` | serialized FIFO | reused unchanged |
| `.../schemas.py:128 definition_issues` | publish gate | Ask-node serialized rule |
| `app/models/workflow.py:20-24` run statuses, `:122` `WorkflowRun` | run row | `RUN_WAITING` + 2 columns |
| `app/services/workflow_service.py:333 publish` (trigger denorm at `:358-371`), `:245 assert_code_permitted`, `:658 metadata` | publish + metadata | registry denorm, `assert_http_permitted`, metadata additions |
| `app/permissions/permissions.csv:63-66` | `workflows.read/manage/run/code` | `+ workflows.http` |
| `modules/omnichannel/workflow_nodes.py` | 1 trigger + 2 actions today | all new defs |
| `modules/omnichannel/services/workflow_actions.py` | `omnichannel_get_contact`, `omnichannel_send_message` | all new executors |
| `.../services/conversation_service.py:473 patch_thread`, `:646 close_thread`, `:387 move_lifecycle` | the thread write seam | called, never bypassed |
| `.../services/message_service.py:278 send_message` (TEMPLATE branch at `:305`), `:736 add_internal_note` | the send seam | template mode exposed |
| `.../services/lifecycle_service.py move()` | edge-enforced stage move | called |
| `.../services/contact_profile_service.py:173 emit_entity_event` | the ONE `updated` emission with `changes` | refined, never duplicated |
| `.../services/event_service.py record()` | the ONE conversation-event seam | + allowlisted `emit_entity_event` |
| `.../services/inbound_service.py:251 notify_entity_event` | inbound dispatch | resume hook placed immediately BEFORE it |
| `.../services/webhook_service.py:66 validate_callback_url`, `:110 assert_deliverable` | the SSRF guard | delegates to the new core `url_guard` |
| `.../models.py:70 Workspace`, `:85 WorkspaceMember`, `:138 Contact`, `:357 ConversationEvent`, `:607 OmnichannelSettings` | module tables | 2 new tables + 3 columns |
| `.../alembic/versions/0010_omni_contacts_module.py` | current module head | `0013` parent = the head after A4 / A8 |
| `service_frontend/lib/workflow-catalog.ts` | FE registry mirror | new entries |
| `service_frontend/types/workflows.ts:113 NodeFieldDef`, `:252 WorkflowMetadata`, `:338 WorkflowRunStatus` | FE types | field types, metadata, `'waiting'` |
| `.../components/platform/workflow-canvas/node-config-drawer.tsx:1066` (`omnichannelChannel` branch) | drawer field switch | new branches modelled on it |
| `.../workflow-node.tsx:93-97` | IF's two handles | generic `ports` rendering |
| `.../node-palette.tsx:109` | 3 hardcoded sections | Logic section derivation |
| `.../lib/workflow-doc.ts:499 validateDefinition` | FE publish parity | Ask-node rule |

## 7. Risks and mitigations

- **Resume ordering vs `message_received` (the load-bearing one).** The resume hook sits in
  `InboundService._handle_message` immediately before the existing `notify_entity_event` block and
  inside its own try / except: a failure there must never drop a message. If a wait is claimed the
  `message_received` dispatch is skipped (D-A5-8). The claim is an atomic `UPDATE ... WHERE id = ...
  AND retry_count = :seen` style guard so two concurrent inbound messages cannot both resume one run.
- **Serialized lease vs a parked run.** A parked run is `waiting`, not `running`, so
  `_live_running_run_id` will happily start a NEXT pending run in the same correlation scope while
  one is parked. That is correct for the ask flow (the answering message is consumed, so no second
  run exists) but it is a genuine semantic edge for a workflow with BOTH an Ask node and a second
  trigger path. Pinned by a test; documented in the plan; backlog row for a "block the scope while
  parked" mode.
- **Timeout drift.** A 60 s beat means a "1 hour" timeout fires between 60:00 and 61:00. Stated in
  the AC as a deadline sweep, not a precise timer. Under eager dev there is no beat, so the E2E run
  calls the sweep function directly for the timeout journey (the same pattern
  `run_due_workflows` already uses).
- **SSRF.** `http.request` is the first tenant-authored outbound HTTP call in core. The guard is the
  existing, already-reviewed `validate_callback_url` logic moved verbatim into
  `app/services/url_guard.py` (https-only, IP-literal and DNS-resolution blocking) and called
  immediately before every request, not at save. Redirects must be DISABLED on the client
  (`follow_redirects=False`) - a 302 to `169.254.169.254` would otherwise bypass a pre-flight-only
  check. This is a reviewer hard-check.
- **Header secrets.** Header values are merge-rendered from the run context and may carry an API key.
  They are never written to `WorkflowRunNode.input_json` (names only) and never logged. The generic
  `_node_input_json` "resolved" map must therefore SKIP the `headers` field - a reviewer hard-check,
  because that helper renders every mergeable field by default.
- **A4 / A8 merge order.** S0-S2 do not depend on either. `omnichannel.broadcast_completed`
  (AC-WFP-22) is skipped and deferred if A4 has not merged; `assign_conversation` is DEFINED here
  only if A8 has not merged, otherwise EXTENDED. After the rebase, re-check: the module Alembic head
  (expect `0012`, so `0013`'s `down_revision` is A8's), the manifest version (expect `0.7.0` after
  A4's `0.5.0` and A8's `0.6.0`), and whether A8 already introduced a `team` NodeField type.
- **Executor refactor blast radius.** `_walk` extraction touches the single most load-bearing
  function in the engine. S4 keeps `run_workflow`'s external behaviour byte-identical for the
  non-parking path; the pre-existing `test_workflow_engine`, `test_workflow_triggers`,
  `test_serialized_workflow_runtime` and `test_stateful_ai_runtime` suites are the regression net and
  must be green before the park path is added.
- **New permission reaches nobody.** `workflows.http` needs the grant sweep for already-provisioned
  tenants (`tenant_admin_grant` re-run in the same migration as the CSV row lands), or the node is
  invisible for every existing tenant. Definition-of-Done item 4.
- **`create_all` never ALTERs.** The three added module columns need the idempotent
  `ADD COLUMN IF NOT EXISTS` mirror in `bootstrap.create_schema_and_tables`, and the two core columns
  need `bootstrap_db` (not `init_db`) on any local database used for verification.
- **Cross-tenant stored ids.** `workflow_waits.run_id` (a core row id held in a module table),
  `workflow_contact_fires.workflow_id`, the round-robin cursor's user id and every picker id are
  polymorphic stored ids: validated at save and resolved tenant-scoped at use. This class has leaked
  twice in this codebase; the reviewer treats an unscoped `get_by_id` as a hard fail.

## 8. Backlog candidates (register on close, `documentation/backlogs/backlog.md`)

| ID | Title | Priority |
|---|---|---|
| BL-SS-100 | Ask a question: date / url / rating / location answer types | Medium |
| BL-SS-101 | Ask a question: save the answer directly to a contact field from the node | Low |
| BL-SS-102 | Serialized scope: optional "block the correlation key while a run is parked" mode | Medium |
| BL-SS-103 | Wait queue: allow more than one open question per contact (ordered) | Low |
| BL-SS-104 | `http.request`: plain-http targets for an explicitly allowlisted host | Low |
| BL-SS-105 | `http.request`: continue-on-error branch (`success` / `error` ports) | Medium |
| BL-SS-106 | Business hours: holiday calendar and per-team hours | Medium |
| BL-SS-107 | Jump to another step (respond.io parity) | Low |
| BL-SS-108 | Workflow templates gallery seeded with the A5 patterns (feeds B3 / G12) | Medium |
| BL-SS-109 | Parked-run operator view: list and force-resume waiting runs from the Logs tab | Medium |
| BL-SS-110 | Generalize the wait table so a non-omnichannel module can park a run | Low |
| BL-SS-111 | Trigger once per contact: a reset action (clear the marker set) | Low |

BL-SS-084 (the `broadcast_completed` trigger A4 handed over) is CLOSED by AC-WFP-22 when A4 is
merged; BL-128 (respond.io-style conversation automation) is CLOSED by this slice.

## 9. Flagged for the user (decisions taken that deviate from, or extend, the brief)

- **F1 - A5b needs ONE core Alembic migration.** The brief said "core migration for `workflows.http`
  CSV = none (CSV sync)", which is correct for the permission. But parking a run needs
  `workflow_runs.paused_node_id` + `resume_state_json` (D-A5-20, §5.5). The alternative - stashing the
  engine's context blob inside the module's wait row - keeps core migration-free but makes a module
  table the custodian of an opaque core structure and hides a parked run from the core Logs view. I
  chose the core columns. Say the word and S4 flips to the module-blob variant.
- **F2 - a resuming inbound message is CONSUMED (D-A5-8).** `omnichannel.message_received` does not
  fire for the message that answers a question. Without this, a workflow that asks a question and is
  itself triggered by `message_received` would re-ask on every reply. The cost: a second, unrelated
  `message_received` workflow also misses that one message. The alternative (resume AND dispatch)
  needs a per-workflow "ignore messages that answered a wait" flag, which is more configuration than
  parity requires.
- **F3 - `omnichannel.lifecycle_changed` is a real TriggerDef, not a frontend-only catalog alias**
  (D-A5-3). The brief said "expose a friendly alias in the catalog". A pure frontend alias over
  `entity.status_changed` would render an EMPTY stage picker, because `omnichannel_contact` is
  registered `has_status=False` (the lifecycle machine is workspace-scoped, so there is no tenant-wide
  status list to resolve - see the comment block in `modules/omnichannel/workflow_nodes.py`). The real
  TriggerDef carries its own workspace + stage pickers. It still rides the SAME `status_changed`
  emission: no second event.
- **F4 - conversation opened / closed / assigned DO need new emissions.** Audited at `58759ed`:
  `conversation_events` rows exist (plan 27) but nothing calls `emit_entity_event` for them; only
  `contact_profile_service`, `contact_admin_service` and `inbound_service` emit. So A5 adds exactly
  three allowlisted emissions inside the existing `event_service.record()` seam, and reuses the
  existing `updated` / `status_changed` events for tags, fields and lifecycle.
- **F5 - the SSRF guard moves to core.** `assert_deliverable` lives in
  `modules/omnichannel/services/webhook_service.py:110`; a core `http.request` action cannot import
  it. It moves to `app/services/url_guard.py` and the module delegates. This is a refactor of
  reviewed security code - the reviewer should diff it for behaviour equality, and the existing
  gateway SSRF tests must pass untouched.
- **F6 - business hours did not exist** (grep for `business_hours` / `businessHours` at `58759ed`
  returns nothing anywhere in backend or frontend). Defined minimally on `omnichannel_settings` per
  the brief, with a workspace-form tab as the editor.
- **F7 - Send message already supports templates at the SERVICE layer**
  (`message_service.py:305`, `messageType="TEMPLATE"` with header / body / button variables and
  approval + placeholder-count validation). A5 only exposes it on the action, so the "extend with
  template + variables" decision costs a config schema, not a send path.
- **F8 - the wait sweep is a module-owned beat task in the core worker**, guarded like
  `webhooks.retry_due`. Core therefore names a module task string in `beat_schedule`. The precedent
  exists and is documented; the alternative (a second beat host) is worse.
