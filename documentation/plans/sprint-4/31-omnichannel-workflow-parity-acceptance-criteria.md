# 31 - Omnichannel workflow parity v1 (triggers, steps, ask-a-question) - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/31-omnichannel-workflow-parity.md`.
> **Program:** slice **A5** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0), gaps G10 +
> G11, roadmap decisions D7 (ask-a-question runtime) and D11 (no separate AI builder).
> Split into **A5a** (triggers, simple steps, once-per-contact, builder) and **A5b** (ask a question,
> wait, business hours, HTTP request) inside this one contract.
> **Grill (2026-09-06):** decisions D-A5-1 .. D-A5-6, carried into §3 of the plan.
> **Depends on (merged at `58759ed`):** plan 25 (A1 contact fields / tags / lifecycle), plan 26 (A2
> contacts module, `ContactProfileService`), plan 27 (A3 `conversation_events`, `close_thread`,
> `add_internal_note`, `entity.shortcut`, `create_run_for_event`), plan 19 (serialized runs,
> `workflow_agent_states`, `redis.command`, `code.run`).
> **Merge points (not yet on main):** plan 29 (A4 broadcasts) supplies the `omnichannel_broadcast`
> `completed` entity event that AC-WFP-22 triggers on; plan 28 (A8 teams) supplies the
> `omnichannel.assign_conversation` action AC-WFP-23 extends.
> **Out of scope:** respond.io workflow import (A6 re-authors by hand), AI classification steps (C1),
> Slack / email notify steps (B3), calendar and scheduling steps, Jump-to-step, ads triggers,
> Conversions API events, Google Sheets (HTTP request covers it), `mark_unread`.

IDs: `AC-WFP-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Definitions

- **Catalog entry** - one `TriggerDef` / `ActionDef` in `app/workflow_engine/registry.py` (backend)
  with its parity mirror in `service_frontend/lib/workflow-catalog.ts` (frontend).
- **Event-backed trigger** - a trigger whose firing rides an existing domain event through
  `emit_entity_event` / `notify_entity_event`; A5 adds no polling and no second event bus.
- **Registry-driven dispatch** - `_trigger_types_for(action)` and the publish trigger denormalization
  resolve from `TriggerDef.event_action` / `TriggerDef.event_entity_type` instead of a hardcoded
  if-chain (the generic support plan 29 flagged as F3).
- **Fire guard** - an optional `TriggerDef.fire_guard(db, workflow, config, event) -> bool` called
  once per candidate workflow at run creation; returning `False` suppresses the run. Backs
  "trigger once per contact".
- **Branching action** - an `ActionDef` declaring `ports=(...)`; its executor returns
  `{"branch": "<port>", ...}` and the walker activates ONLY the matching outgoing edges (the same
  rule the IF node already uses for `true` / `false`).
- **Parked run** - a run whose executing node asked the engine to suspend. The run row goes to status
  `waiting` carrying `paused_node_id` + `resume_state_json`; a resume flips it back to `pending` and
  re-dispatches through the existing serialized dispatch.
- **Wait row** - one `app_omnichannel.workflow_waits` row: the module-owned index from
  (tenant, workspace, contact) to a parked run, plus the answer spec, retry counters and deadline.
- **Answer type** - `text` | `choice` | `number` | `email` | `phone` (the five A5b types).
- **Business hours** - the per-workspace weekly open windows + IANA timezone stored on
  `app_omnichannel.omnichannel_settings` (a NULL `workspace_id` row is the tenant default).

---

# A5a - triggers and simple steps

## Slice S0 - Frontend: catalog and builder on a mock

- **AC-WFP-01 [FE]** Given the workflow editor palette, when the omnichannel Service is ACTIVE for the
  tenant, then the Triggers section additionally offers: Conversation opened, Conversation closed,
  Conversation assigned, Contact tag updated, Contact field updated, Lifecycle updated, Broadcast
  completed; the Actions section additionally offers: Assign conversation, Add tag, Remove tag,
  Update contact field, Update lifecycle, Open conversation, Close conversation, Add comment, Ask a
  question, Trigger another workflow, HTTP request (and Send message gains a template mode); the
  Logic section additionally offers Wait and Business hours. With the Service INACTIVE none of the
  omnichannel-tagged entries appear (existing `visibleEntries` module gate).
- **AC-WFP-02 [FE]** Given any new node's config drawer, then every picker is a `SearchSelect`
  (channel, workspace, tag, contact field, lifecycle stage, close reason, workflow, answer type,
  assign mode), no bare `<Select>` and no instructional / how-to copy on screen.
- **AC-WFP-03 [FE]** Given a picker whose options come from workspace-scoped data (tags, contact
  fields, lifecycle stages, close reasons, members), then it offers ONLY the options of the workspace
  chosen on that node, and while no workspace is chosen the dependent picker is disabled with an
  empty option set (foolproof-UI: never a list that would fail at run time).
- **AC-WFP-04 [FE]** Given a node with `showWhen` fields (assign mode, ask answer type, HTTP body
  mode, send-message template mode), then hidden fields are neither rendered nor required, and
  switching the controlling field clears the now-hidden values from `config`.
- **AC-WFP-05 [FE]** Given an Ask a question or Business hours node on the canvas, then it renders TWO
  labelled source handles (`answer` / `timeout`, `inside` / `outside`) exactly like the IF node's
  true / false handles, each independently connectable, and the edge stores its `sourcePort`.
- **AC-WFP-06 [FE]** Given a graph that contains an Ask a question node, then the frontend
  `validateDefinition` blocks publish unless `execution.mode = serialized` with a valid correlation
  key, naming the requirement; the backend `definition_issues` returns the SAME message (parity),
  pinned by a test. **Amended (review round 1, SF-4):** the backend half is deferred to S4 -
  `omnichannel.ask_question` has no backend `ActionDef`/registered node type until S4 lands (see
  B-4), so `definition_issues` cannot yet apply this rule to it; S1-S3 ship the FE-only half
  (pinned by `lib/workflow-doc.test.ts`) and S4 lands the backend rule alongside the node itself.

## Slice S1 - Backend: triggers, dispatch generalization, once-per-contact

- **AC-WFP-07 [BE]** Given the module boots, then `_trigger_types_for` and the publish trigger
  denormalization resolve module triggers from the registry (`event_action` / `event_entity_type`),
  the existing `form.submitted` and `omnichannel.message_received` behaviour is unchanged (their
  hardcoded branches are gone and the pre-existing tests stay green), and a newly registered module
  trigger needs NO further core edit.
- **AC-WFP-08 [BE]** Given a thread moves from any non-OPEN state to OPEN (inbound reopen, manual
  reopen, gateway, workflow step) or a contact's first conversation opens, then exactly ONE
  `omnichannel_contact` `conversation_opened` entity event is emitted in the SAME unit of work as the
  `conversation_events` row, and a published `omnichannel.conversation_opened` workflow starts a run
  whose context carries `trigger.contact.*`, `trigger.conversationId`, `trigger.workspaceId`,
  `trigger.isReopen`.
- **AC-WFP-09 [BE]** Given a thread is closed through `close_thread` (UI, gateway or workflow step),
  then ONE `conversation_closed` event is emitted and a published `omnichannel.conversation_closed`
  run's context carries `trigger.closeReasonId`, `trigger.closeReasonLabel`, `trigger.note`; a
  trigger configured with a specific close reason fires only for that reason, one configured with no
  reason fires for every close.
- **AC-WFP-10 [BE]** Given a thread's assignee changes (assigned, reassigned, unassigned) through
  `patch_thread`, then ONE `conversation_assigned` event is emitted and a published
  `omnichannel.conversation_assigned` run's context carries `trigger.assigneeUserId` (null when
  unassigned), `trigger.previousAssigneeUserId`, `trigger.assignedVia`; a no-op assign writes no event
  and starts no run.
- **AC-WFP-11 [BE]** Given a contact's tags change, then the EXISTING `omnichannel_contact` `updated`
  event is reused (no second emission) and `omnichannel.contact_tag_added` /
  `omnichannel.contact_tag_removed` fire by refining `changes["tags"] {from,to}`: configured with a
  tag id they fire only when THAT tag entered / left the set; configured with no tag they fire on any
  addition / removal; a change that only reorders the set fires neither.
- **AC-WFP-12 [BE]** Given a contact's registered custom field changes, then
  `omnichannel.contact_field_changed` fires by refining `changes["customFields.<key>"]`: a trigger
  bound to a field key fires only for that key, optionally narrowed by a configured new value; an
  unregistered or unknown key never matches.
- **AC-WFP-13 [BE]** Given a contact's lifecycle stage moves, then `omnichannel.lifecycle_changed`
  fires off the machine's EXISTING `entity.status_changed` emission on `omnichannel_contact` (no
  second emission), refined by optional from-stage and to-stage; a generic `entity.status_changed`
  workflow on the same entity still fires as it does today.
- **AC-WFP-14 [BE]** Given `omnichannel.message_received`, then its config additionally accepts
  `firstMessageOnly` (boolean) and `keywordContains` (string), and the inbound event payload carries
  `isFirstMessage`; a run starts only when every configured filter matches (channel AND first-message
  AND case-insensitive keyword substring of the message text; a message with no text never matches a
  keyword filter).
- **AC-WFP-15 [BE]** Given any A5 trigger with `triggerOncePerContact = true`, when its event fires
  for a contact for the first time, then a `workflow_contact_fires` row (tenant, workflow, contact) is
  claimed in the same transaction and the run is created; every later matching event for that contact
  and workflow creates NO run; the claim is per workflow (another workflow still fires); two
  concurrent events race to a single unique-constraint winner (exactly one run, the loser skipped
  silently and never surfacing as a request error); markers SURVIVE an unpublish or republish and are
  deleted with the workflow.
- **AC-WFP-16 [BE]** Given a tenant B user or a tenant B event, then no tenant A workflow is ever
  matched, no tenant A wait or marker row is read or written, and every new query filters `tenant_id`
  from the authenticated context, never from payload input.
- **AC-WFP-17 [BE]** Given any new emission point (opened / closed / assigned), then a failing or slow
  workflow NEVER breaks the triggering request: the emission is buffered and drained after commit,
  each event dispatches in its own isolated transaction, and an exception is logged only.
- **AC-WFP-18 [BE]** Given a workflow whose own step causes the event it triggers on (for example a
  Close conversation step inside a Conversation closed workflow), then the existing origin-chain guard
  prevents that workflow re-triggering itself, and a cross-workflow cascade stops at
  `MAX_RUN_DEPTH = 5`.
- **AC-WFP-19 [BE]** Given a published version that carries Code nodes without a `code_authorized_by`
  stamp, then none of the new triggers create a run for it (the existing fail-closed gate in
  `create_run_for_event` is inherited, not re-implemented).
- **AC-WFP-20 [BE]** Given each new trigger, then publish denormalizes `trigger_entity_type` to the
  registry-declared constant so the indexed candidate query matches, and unpublish clears it.
- **AC-WFP-21 [BE]** Given the workflow editor calls `GET /workflows/metadata`, then it additionally
  returns `omnichannelWorkspaces` and, per workspace, `contactTags`, `contactFields`,
  `lifecycleStages`, `closeReasons` and `members` - all tenant-scoped, all empty when the module is
  inactive, in the SAME single call.
- **AC-WFP-22 [BE]** Given plan 29 (A4) is merged and a broadcast completes, then the
  `omnichannel_broadcast` `completed` entity event matches a published
  `omnichannel.broadcast_completed` workflow via the registry dispatch of AC-WFP-07, with context
  `trigger.broadcastId`, `trigger.broadcastName`, `trigger.sent`, `trigger.failed`. If A4 is not
  merged at build time this AC is DEFERRED with a backlog row; no other AC depends on it.

## Slice S2 - Backend: simple steps

- **AC-WFP-23 [BE]** Given the Assign conversation step, then it assigns to a specific user, to a
  round-robin pick across the contact's workspace members, or unassigns; every path writes through
  `ConversationService.patch_thread` so the conversation event, realtime push and consumer webhook are
  identical to the UI path; outputs `assignedUserId`, `assigned`. If plan 28 (A8) is merged this
  EXTENDS its `omnichannel.assign_conversation` action with the `round_robin` workspace-member mode
  rather than defining a second action.
- **AC-WFP-24 [BE]** Given the round-robin mode, then the pick is deterministic and fair: eligible
  members are the workspace members that still resolve to a live user in the SAME tenant, ordered
  stably, and the next pick follows the workspace's stored cursor; a workspace with zero eligible
  members leaves the thread unassigned and the node SUCCEEDS (an empty roster never fails an
  automation).
- **AC-WFP-25 [BE]** Given the Add tag / Remove tag steps, then the tag is resolved within the
  contact's workspace and applied through `ContactProfileService`, adding an already-present tag (or
  removing an absent one) is a successful no-op that emits no change event, and a tag id from another
  workspace or tenant fails the node with a clear error and writes nothing.
- **AC-WFP-26 [BE]** Given the Update contact field step, then the value is merge-rendered from the
  run context and validated for the registered field's type (number numeric, checkbox boolean, email
  and url well formed, date `YYYY-MM-DD`, time `HH:MM`, list one of the options, text within the
  cap); an invalid value fails the node with the field error and writes nothing; an empty rendered
  value clears the key when the node is configured to clear.
- **AC-WFP-27 [BE]** Given the Update lifecycle step, then the move goes through
  `lifecycle_service.move`, so the edge graph, edge-role authorization, transition notifications, the
  `lifecycle_changed` conversation event and the `entity.status_changed` emission all apply; a missing
  edge fails the node with the machine's message and the stage is unchanged.
- **AC-WFP-28 [BE]** Given the Open conversation step, then a CLOSED or SNOOZED thread is reopened
  through `patch_thread` (event + realtime + webhook), and an already-OPEN thread is a successful
  no-op.
- **AC-WFP-29 [BE]** Given the Close conversation step, then it calls `close_thread` with a close
  reason (required, workspace-scoped, must be active) and an optional merge-rendered note; an
  already-closed thread fails the node with the same `ThreadAlreadyClosed` semantics the UI gets, and
  an inactive or foreign reason fails without writing.
- **AC-WFP-30 [BE]** Given the Add comment step, then the merge-rendered body is written through
  `MessageService.add_internal_note`, producing the same internal-note bubble, `comment_added` event
  and realtime push as the drawer; an empty rendered body fails the node.
- **AC-WFP-31 [BE]** Given the Send message step, then it additionally supports a template mode:
  choosing an approved WhatsApp template of the contact's channel plus per-placeholder values that are
  merge-rendered from the run context, sent through the ONE `MessageService.send_message` path;
  outputs `messageId` and `status`. Text mode behaves exactly as today.
- **AC-WFP-32 [BE]** Given a template that is not APPROVED, a placeholder count mismatch, or a closed
  24 hour window in text mode, then the node FAILS with the service's own rejection message, the run
  FAILS and downstream nodes skip; a step that already committed (send, close, assign) is NOT rolled
  back by a later node failure and the run trace records both facts (documented semantics, pinned by
  a test).
- **AC-WFP-33 [BE]** Given the Trigger another workflow step, then it starts the chosen PUBLISHED
  workflow of the same tenant for the same contact, passes the contact id and an optional
  merge-rendered payload into the child run's trigger context, records the parent run id so the
  existing loop guard and depth cap apply, and outputs the child `runId`; choosing an unpublished,
  archived, foreign-tenant or self workflow fails the node.
- **AC-WFP-34 [BE]** Given any A5 step, then it fails closed when the omnichannel Service is not
  ACTIVE for the tenant, and every contact / tag / field / stage / reason / workflow / member id it
  resolves is looked up tenant-scoped AND workspace-scoped, never with a bare id lookup.
- **AC-WFP-35 [BE]** Given a manual or test run (`sandboxOnly`), then Send message and Ask a question
  send sandbox-only messages exactly as today, and stateful side effects use the test namespace.

## Slice S3 - Wire and evidence (A5a)

- **AC-WFP-36 [FE]** Given the mock services are swapped for the real API, then the palette, drawers
  and pickers render live tenant data (workspaces, tags, fields, stages, reasons, members, channels,
  templates) with no mock left in the shipped path.
- **AC-WFP-37 [FE]** Given a user without `workflows.manage`, then the editor is read-only as today;
  given a user without `workflows.http`, then the HTTP request node cannot be added or edited in the
  drawer, and the API rejects a create / update / publish / run carrying one.
- **AC-WFP-38 [FE]** Given the workflow Logs tab, then a run started by a new trigger shows the
  trigger node's captured event data, each new step node shows its resolved (merge-rendered) input and
  its output, and a failed step shows its error.
- **AC-WFP-39 [E2E]** Recorded agent-browser run at 375 px AND 1280 px, real clicks from `/`, evidence
  under `documentation/plans/sprint-4/31-evidence/a5a/`: sign in, open Workflows, create a workflow,
  add the Conversation opened trigger, add Add tag then Update lifecycle then Send message, wire them,
  Publish, then from the Inbox close and reopen a demo thread and see the run in Logs with the tag and
  the stage applied on the contact panel.
- **AC-WFP-40 [E2E]** Same run: a second workflow with `triggerOncePerContact` fires once for a
  contact and not again on a second identical event (verified in Logs), and a tenant B session sees
  none of tenant A's workflows, runs or pickers.

---

# A5b - stateful steps

## Slice S4 - Backend: waits, ask a question, resume

- **AC-WFP-41 [BE]** Given an executing node asks the engine to suspend, then the run is parked: the
  run row goes to status `waiting` with `paused_node_id` and a JSON-safe `resume_state_json` holding
  the flat run context plus the active-edge set, the node's trace row records the park, downstream
  nodes are NOT marked skipped, and no further node executes.
- **AC-WFP-42 [BE]** Given a parked run is resumed with a node output, then the run returns to
  `pending`, is re-dispatched through the EXISTING dispatch path (serialized scopes keep their FIFO
  ordering and lease), and the walk continues from the parked node's outgoing edges with the restored
  context; nodes that already ran are not re-executed and their trace rows are preserved.
- **AC-WFP-43 [BE]** Given the Ask a question step runs, then it sends the configured message (text or
  approved template) through `MessageService.send_message`, writes ONE wait row keyed
  (tenant, workspace, contact) with the answer spec, retry count 0 and a deadline computed from the
  configured timeout, and parks the run.
- **AC-WFP-44 [BE]** Given a contact already has an open wait row and a second workflow reaches an Ask
  a question step for that contact, then the second Ask node fails cleanly with a stated reason (one
  open question per contact) and never overwrites the first wait row.
- **AC-WFP-45 [BE]** Given an inbound message arrives for a contact with an open wait row, then the
  inbound pipeline resumes that parked run BEFORE any `omnichannel.message_received` dispatch, the
  message is consumed by the resume, and NO `message_received` run is created for that message.
- **AC-WFP-46 [BE]** Given the inbound answer validates for the wait's answer type, then the wait row
  is deleted and the run resumes on the `answer` port with `nodes.<id>.answer` (the normalized value),
  `nodes.<id>.answerRaw` (the message text) and, for `choice`, `nodes.<id>.answerKey`.
- **AC-WFP-47 [BE]** Given the answer does NOT validate (not one of the choices, not a number, not a
  well-formed email or phone), then the run stays parked, the retry counter increments and the
  configured re-ask message is sent; once the retry cap is reached the wait is closed and the run
  resumes on the `timeout` port with `nodes.<id>.timedOut = true` and `nodes.<id>.reason = "invalid"`.
- **AC-WFP-48 [BE]** Given the `choice` answer type, then matching is case-insensitive and
  whitespace-trimmed against both the choice label and its numeric position, and the sent message
  lists the choices; the `text` answer type accepts any non-empty message.
- **AC-WFP-49 [BE]** Given the wait deadline passes, then the beat sweep closes the wait and resumes
  the run on the `timeout` port with `reason = "timeout"`; the sweep is idempotent, processes at most a
  bounded batch per tick, is tenant-scoped per row, never resumes the same wait twice, and discards
  (with a log) a row whose run no longer exists or whose contact belongs to another tenant.
- **AC-WFP-50 [BE]** Given the Wait step, then it parks the run with a wait row carrying only a
  deadline (duration in minutes / hours / days, capped), and the beat sweep resumes it on its single
  `out` port; an inbound message does NOT shorten a plain Wait.
- **AC-WFP-51 [BE]** Given a graph containing an Ask a question node, then publish is REFUSED unless
  `execution.mode = serialized` with a valid correlation key, and the run created by the trigger
  carries the resolved correlation key so same-contact runs never interleave.
- **AC-WFP-52 [BE]** Given a parked run, then run retention pruning never deletes a `waiting` run or
  its wait row; cancelling a `waiting` run marks it cancelled AND deletes its wait row; deleting or
  unpublishing a workflow leaves parked runs cancellable and their waits swept.
- **AC-WFP-53 [BE]** Given a manual or test run reaches an Ask a question node, then it parks the same
  way with the wait row flagged as test, the sent message is sandbox-only, and the test wait is swept
  at its deadline like any other.
- **AC-WFP-54 [BE]** Given the module is uninstalled for a tenant, then that tenant's wait rows and
  once-per-contact marker rows are deleted with the rest of the module's rows, and any run still
  `waiting` is cancelled.

## Slice S5 - Backend: business hours and HTTP request

- **AC-WFP-55 [BE]** Given a workspace, when a user with `workspaces.manage` saves business hours
  (IANA timezone plus per-weekday open windows, multiple windows per day allowed, overnight windows
  allowed), then they are stored on that workspace's `omnichannel_settings` row and returned by the
  workspace read; an invalid timezone, a malformed window or an end before a start returns 422 with
  field errors and nothing is written; a tenant B workspace id returns a uniform 404.
- **AC-WFP-56 [BE]** Given the Business hours step, then it evaluates "now" in the workspace's
  configured timezone against those windows and activates only its `inside` or `outside` port, with
  outputs `isOpen`, `checkedAt`, `timezone`; a workspace with NO configured hours resolves through the
  tenant-default row, and with neither configured the node fails with a stated missing-prerequisite
  error rather than guessing.
- **AC-WFP-57 [BE]** Given the HTTP request step, then it sends the configured method
  (GET / POST / PUT / PATCH / DELETE) to a merge-rendered URL with merge-rendered headers and body,
  under a bounded timeout and a bounded response read, and outputs `statusCode`, `ok`, `body`,
  `json.<path>` for a JSON response, and `durationMs`.
- **AC-WFP-58 [BE]** Given the HTTP request target, then the SSRF guard runs immediately BEFORE every
  request (not only at save): non-https schemes, localhost, `.local`, IP literals (dotted, decimal and
  hex) and hostnames that resolve to private, loopback, link-local, reserved, multicast or unspecified
  addresses are refused, the node fails with a uniform message, and NO request is sent. The guard is
  ONE shared implementation with the consumer-webhook delivery guard.
- **AC-WFP-59 [BE]** Given the HTTP request node's trace, then header VALUES are never stored or
  logged (names only), the rendered URL is stored, the response body is truncated at the cap, and a
  non-text response records size and content type only.
- **AC-WFP-60 [BE]** Given a non-2xx response or a transport error, then the node FAILS with the
  status code or error class in its message (no silent success), the run FAILS and downstream nodes
  skip; a "continue on error" option is NOT offered in v1.
- **AC-WFP-61 [BE]** Given `workflows.http`, then it is a new CORE permission key (no collision -
  verified 2026-09-06), granted to tenant Admin on core seed with a sweep for already-provisioned
  tenants, and it gates create / update / publish / manual run of any graph carrying an HTTP request
  node exactly the way `workflows.code` gates Code nodes (403 at the router, fail closed at publish).
- **AC-WFP-62 [BE]** Given a JSON body mode, then the merge-rendered body must parse as JSON before
  the request is sent; an unparseable rendered body fails the node with a clear message and sends
  nothing.

## Slice S6 - Wire and evidence (A5b)

- **AC-WFP-63 [FE]** Given the workspace form, then a Business hours tab (after Close reasons) edits
  the timezone and the weekly windows with the shell's Edit toggle and dirty guard, usable and
  non-clipped at 375 px and 1280 px, and read-only for a user without `workspaces.manage`.
- **AC-WFP-64 [FE]** Given the Ask a question drawer, then choosing an answer type reveals only that
  type's fields (choices editor for `choice`, retry count, re-ask message), the timeout is a duration
  input, and the node's two ports are wireable on the canvas; the dynamic-content picker lists
  `nodes.<id>.answer`, `answerRaw`, `answerKey`, `timedOut`, `reason`.
- **AC-WFP-65 [FE]** Given a run parked at an Ask a question node, then the Logs list shows it as
  Waiting with a distinct badge, the replay canvas shows the parked node with no phantom failures, and
  the run shows as Success after it resumes.
- **AC-WFP-66 [E2E]** Recorded agent-browser run at 375 px AND 1280 px, real clicks from `/`, evidence
  under `documentation/plans/sprint-4/31-evidence/a5b/`: build a workflow with the Incoming message
  trigger, an Ask a question node (choice, two options, 1 hour timeout), a Business hours branch and
  two Send message nodes; set serialized execution with the contact correlation key; Publish; drive a
  message into the demo thread through the dev-safe inbound; observe the question arriving in the
  Inbox; reply with a valid choice from the composer; observe the run resuming and the follow-up
  message landing in the thread.
- **AC-WFP-67 [E2E]** Same run: reply with an INVALID answer first and observe the re-ask, then a
  valid one; and add an HTTP request node pointing at `http://169.254.169.254/latest/meta-data` and
  observe the node failing with the refused-target error and NO request leaving the process.

## Tests

- **AC-WFP-68 [T]** pytest covers, per AC: registry-driven `_trigger_types_for` and publish
  denormalization (including the unchanged `form.submitted` / `message_received` behaviour), each new
  trigger's match and refine matrix, once-per-contact claim and race, tenant isolation on every new
  route and query, loop guard and depth cap on the self-triggering step, every simple step's happy
  path plus its rejection path, template send, round-robin fairness and empty roster, park and resume
  round trip (including "nodes already run are not re-run"), answer validation matrix and retry
  exhaustion, timeout sweep idempotency, one-open-question-per-contact, retention and cancel
  behaviour on `waiting`, business-hours evaluation across timezone and overnight windows, HTTP
  request success, non-2xx, SSRF refusal (literal IP, decimal IP, DNS-resolving host), header
  redaction, and the `workflows.http` gate at create / update / publish / run.
- **AC-WFP-69 [T]** vitest covers: catalog parity with the backend registry for the new entries
  (labels, field keys, required flags, `showWhen`, ports), the two-port node rendering, the
  workspace-scoped picker gating, `validateDefinition`'s serialized-mode requirement for the Ask node,
  the business-hours form schema, and the HTTP node hidden without `workflows.http`.
- **AC-WFP-70 [T]** A Test Execution Report keyed to every AC id (PASS / FAIL / DEFERRED) with the
  agent-browser evidence path cited per `[E2E]` id, at
  `documentation/plans/sprint-4/31-omnichannel-workflow-parity-test-report.md`.
