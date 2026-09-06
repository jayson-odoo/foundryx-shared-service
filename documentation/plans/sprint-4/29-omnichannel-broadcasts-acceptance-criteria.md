# 29 - Omnichannel Broadcasts v1 - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/29-omnichannel-broadcasts.md`.
> **Program:** slice **A4** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gap G9,
> roadmap decisions D6 segments and D8 broadcast sending).
> **Depends on:** plan 25 / A1 (contact fields, tags, lifecycle, `ContactProfileService`) AND
> plan 26 / A2 (`contact_segments` storing a Resource-shell `FilterGroup`, `contact_filters.py`
> column map, `contact_list_service`, `GET /omnichannel/workspaces/{id}/contacts`, `phone_digits`)
> merged to `main`. A4 branches AFTER the A2 merge.
> **Out of scope (later slices):** A/B test variants, calendar view (Phase D), respond.io broadcast
> import (A6 decides), non-WhatsApp channels beyond what `MessageService.send_message` already
> supports (designed channel-agnostic, verified on WhatsApp only), public gateway surface for
> broadcasts (deliberately none in v1), broadcast analytics report (A9), snippets and file library
> in the composer (B2), the `omnichannel.broadcast_completed` workflow TRIGGER (A5 - A4 only emits
> the entity event).

IDs: `AC-BRD-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Definitions

- **Broadcast** - one `broadcasts` row: a named, scheduled or immediate, one-way send of ONE
  approved WhatsApp template to a resolved audience on ONE channel, inside ONE workspace.
- **Audience** - the CONFIGURATION of who receives it: exactly one of a saved segment
  (`contact_segments`, A2), an inline `FilterGroup`, or an explicit list of contact ids. The
  audience is configuration only; it is never a stored recipient list until send time.
- **Recipient** - one `broadcast_recipients` row, materialized at SEND time (the audience
  snapshot). States: `queued` (in the snapshot, not yet handed to the send path), `sent` (accepted
  by the send path), `delivered`, `read` (receipt-driven), `failed`, `skipped`.
- **Skip** - a contact in the resolved audience that will never be sent to, recorded with a
  `skipReason`: `no_identity` (no `contact_channel_identities` row on the chosen channel),
  `duplicate` (same contact resolved twice), `channel_inactive` (channel deactivated or trashed
  between save and send), `cancelled` (the broadcast was cancelled before this recipient's turn),
  `missing_variable` (a contact-field binding resolved empty AND its fallback was empty - a state
  the save-time gate normally makes unreachable).
- **Broadcast status** - a row in the module's own lightweight `statuses` table under the NEW scope
  `BROADCAST`, keys `DRAFT`, `SCHEDULED`, `SENDING`, `SENT`, `CANCELLED`, `FAILED`. Machine-driven
  (never user-edited), rendered by a frontend `StatusBadge` registry exactly like `wa_templates`.
- **Binding** - how one WhatsApp template parameter slot is filled:
  `{source: 'static', text}` (verbatim text, no token syntax allowed) or
  `{source: 'contactField', field, fallback}` where `field` is one of the whitelisted
  `firstName | lastName | phone | email | language | countryCode | lifecycle |
  customFields.<registeredKey>`.
- **Send path** - the ONE `MessageService.send_message` in
  `service_backend/modules/omnichannel/services/message_service.py`. Broadcasts add no second
  outbound path.
- **Send job** - the `background_jobs` row of type `omnichannel.broadcast_send` that snapshots the
  audience and drives the chunked fan-out.

---

## Slice S0 - Frontend on the mock service

- **AC-BRD-01 [FE]** Given the omnichannel module is ACTIVE and the user holds `broadcasts.read`,
  then a **Broadcasts** entry appears after Inbox (and after Contacts, from A2) in ALL menu arrays
  that carry the Omnichannel block (`MENU_SIDEBAR`, `MENU_MEGA`, `MENU_MEGA_MOBILE`), tagged
  `module: 'omnichannel'` + `permission: 'broadcasts.read'`; a tenant without the module or without
  the key sees no entry in any of the three surfaces.
- **AC-BRD-02 [FE]** Given `/omnichannel/broadcasts`, then the list is the Resource shell cloned
  from Users (never a hand-rolled table): columns Name, Labels, Channel, Audience, Recipients
  (total), Status, Scheduled / Sent at, Sent / Delivered / Read / Failed, Created by, Created;
  server-side search, sort, filter and pagination through `useResourceList`; per-user column prefs
  under `viewKey` `omnichannel.broadcasts.list`.
- **AC-BRD-03 [FE]** Given the list, then the status views render as the shell's N-way `segments`
  control (a `SearchSelect`, not a segmented toggle): All, Draft, Scheduled, Sending, Sent,
  Cancelled, Failed; switching a segment clears row selection.
- **AC-BRD-04 [FE]** Given "Create broadcast", then the builder is a `ResourceForm` whose steps
  render as ordered sections in one tab: **Details** (name, labels), **Audience**, **Channel**,
  **Message** (template + variables), **Schedule**, **Review**; the shell's global Edit toggle and
  its AlertDialog dirty-guard apply; no instructional or how-to copy appears on the surface.
- **AC-BRD-05 [FE]** Given the Audience section, then the source is a `SearchSelect` offering
  Segment / Filter / Selected contacts (mutually exclusive); Segment lists the workspace's saved
  segments (A2); Filter reuses the Resource shell filter builder over the contact filter fields;
  Selected contacts uses the existing contacts picker; the resolved recipient COUNT is shown and
  refreshes whenever the source or its value changes.
- **AC-BRD-06 [FE]** Given the Channel section, then only ACTIVE, non-trashed channels of the
  current workspace are offered; given the Message section, then only templates that are APPROVED
  on the chosen channel AND carry no media header are offered (foolproof-UI: a picker offers only
  choices that will work); changing the channel clears the template and its bindings.
- **AC-BRD-07 [FE]** Given a chosen template, then the variables editor renders EXACTLY the slots
  the template declares (header text vars, body vars, dynamic URL-button vars) with per-slot source
  `SearchSelect` (Static text | Contact field); a Contact field binding requires a non-empty
  fallback; a live `WaBubblePreview` renders the filled message against a sample contact.
- **AC-BRD-08 [FE]** Given the Schedule section, then the choice is Send now or Schedule for, the
  datetime input is rendered and parsed in the user's timezone via `useDatetime()` and sent as a
  Z-suffixed UTC instant; a past instant is rejected inline.
- **AC-BRD-09 [FE]** Given the Review section, then it shows a read-only summary (audience count,
  channel, template, schedule) plus **Test send** (pick ONE contact) and the primary Send or
  Schedule action; the primary action is disabled while any required piece is missing and the
  incomplete section is marked, without hint copy.
- **AC-BRD-10 [FE]** Given a saved broadcast at `/omnichannel/broadcasts/{id}`, then the detail is a
  `ResourceForm` with tabs **Overview** (the same sections, read-only once the broadcast has left
  Draft) and **Recipients** (an embedded `ResourceList`: Contact, Phone, State, Error, Attempted at;
  filterable by state; error text rendered through `ClampedText`, never a bare truncate).
- **AC-BRD-11 [FE]** Given the action registry, then **Cancel** is offered only while the status is
  Scheduled or Sending (confirmation dialog), **Duplicate** is always offered (opens a prefilled
  create form with a distinct name), **Delete** only while Draft; the same registry serves row, bulk
  and form surfaces.
- **AC-BRD-12 [FE]** Given `useCan()`, then a user without `broadcasts.manage` sees the list and
  detail read-only (no Create / Edit / Duplicate / Delete), and a user without `broadcasts.send`
  sees no Send, Schedule, Test send or Cancel control; the backend remains the real gate.
- **AC-BRD-13 [FE]** Given the mock service trio (`broadcast-service.{ts,mock,real}.ts`), then the
  whole surface is exercisable with no backend: loading, empty, error, a Draft, a Scheduled, a
  Sending broadcast whose counts advance, a Sent broadcast with failures, and a Cancelled one.
- **AC-BRD-14 [FE]** Given every new surface (list, builder sections, recipients table, dialogs)
  at ~375px AND ~1280px, then nothing clips or overlaps, there is no horizontal page scroll, the
  sections stack, every action stays reachable, and the tenant-facing copy never says "Dreamz" or
  "Foundryx" and carries no instructional or teaching text.

## Slice S1 - Backend: model, builder CRUD, audience

- **AC-BRD-15 [BE]** Given the module migration runs on Postgres, then `broadcasts` and
  `broadcast_recipients` exist in `app_omnichannel` with `UNIQUE(broadcast_id, contact_id)` on
  recipients, an index on `broadcast_recipients.message_id`, and the new
  `channels.broadcast_rate_per_second` column; the revision is inspector-guarded (idempotent),
  its id is <= 32 chars, `bootstrap.create_schema_and_tables` mirrors the new column with
  `ADD COLUMN IF NOT EXISTS`, and every datetime column is `UTCDateTime`.
- **AC-BRD-16 [BE]** Given `install_tenant` (new tenant) and `update_tenant` (existing tenant),
  then the `BROADCAST` status scope is seeded with the six keys, re-running is a no-op, and a tenant
  provisioned before this slice gets them without a manual step.
- **AC-BRD-17 [BE]** Given `POST /omnichannel/workspaces/{wsId}/broadcasts` with a valid payload by
  a user holding `broadcasts.manage`, then a broadcast is created in `DRAFT` for that tenant and
  workspace, `createdByUserId` is the ACTOR (the real admin under impersonation, never the target),
  and all counts are 0.
- **AC-BRD-18 [BE]** Given a create or update payload, then the server returns 422
  `{fieldErrors: {path: message}}` when: `name` is empty or > 200 chars; `channelId` is not an
  active, non-trashed channel of THIS workspace; the audience is not exactly one of
  segment / filter / contactIds; the segment does not belong to this workspace; the inline filter
  fails A2's `validate_filter_tree`; a contact id is not in this workspace; `templateId` is not an
  APPROVED template of the chosen channel; the template carries a media header; the binding count
  for header / body / buttons does not match the template shape from `analyze_template`; a
  `contactField` binding names a field outside the whitelist (or an unregistered
  `customFields.<key>` for this workspace) or has an empty `fallback`; a `static` binding contains
  `{{` or `}}`; `scheduledAt` is in the past.
- **AC-BRD-19 [BE]** Given a saved broadcast, then the audience is stored as CONFIGURATION only -
  no `broadcast_recipients` row exists until the send job runs (the send-time snapshot, slice S2).
- **AC-BRD-20 [BE]** Given `GET /omnichannel/workspaces/{wsId}/broadcasts`, then results are tenant
  AND workspace scoped, searchable by name, filterable and sortable only over the whitelisted map
  (name, status, channel, scheduledAt, createdAt, createdBy - anything else 422), paginated, and
  each item carries the denormalized counts.
- **AC-BRD-21 [BE]** Given `PATCH` or `DELETE`, then edits are allowed only while `DRAFT`, and
  `scheduledAt` may additionally be changed while `SCHEDULED`; any other status returns 409 with a
  typed reason and no write; `DELETE` is allowed only while `DRAFT`.
- **AC-BRD-22 [BE]** Given `POST .../broadcasts/{id}/duplicate`, then a NEW `DRAFT` is created with
  the same audience, channel, template and bindings, a distinct name, zeroed counts, no schedule and
  NO recipients copied.
- **AC-BRD-23 [BE]** Given `GET .../broadcasts/audience-preview?segmentId=|filter=`, then the count
  is computed in SQL by the A2 `contact_list_service` query builder (never a Python scan) for this
  tenant and workspace, and an unknown segment or an invalid filter returns 404 / 422 rather than a
  silent 0.
- **AC-BRD-24 [BE]** Given a caller from tenant B using any tenant A id (broadcast, workspace,
  segment, channel, template, contact, recipient), then the response is a uniform 404 - never 403,
  never data, on every route in this slice.
- **AC-BRD-25 [BE]** Given permissions, then reads require `broadcasts.read`, writes require
  `broadcasts.manage`, and send / schedule / test-send / cancel require `broadcasts.send`; each
  route returns 403 for a user missing its key (verified per route, not per resource).

## Slice S2 - Backend: send job, fan-out, receipts, cancellation

- **AC-BRD-26 [BE]** Given `POST .../broadcasts/{id}/send`: with no `scheduledAt` the status moves
  `DRAFT|SCHEDULED -> SENDING` under an atomic claim, ONE `background_jobs` row of type
  `omnichannel.broadcast_send` is created and enqueued, its id is stored on the broadcast, and a
  second concurrent call returns 409 without creating a second job; WITH a future `scheduledAt` the
  status becomes `SCHEDULED`, the instant is stored in UTC and no job is created yet.
- **AC-BRD-27 [BE]** Given the job's snapshot phase, then the audience is resolved ONCE at that
  moment into `broadcast_recipients` (batched inserts, `UNIQUE(broadcast_id, contact_id)`), the
  broadcast's `total` count is set from it, and a contact that joins the segment AFTER the snapshot
  is not sent to.
- **AC-BRD-28 [BE]** Given the snapshot, then a contact with no `contact_channel_identities` row on
  the chosen channel is written `skipped/no_identity`, a contact resolved twice yields ONE row
  (`duplicate` never sends twice), and skipped rows are counted in `skipped` and never handed to the
  send path.
- **AC-BRD-29 [BE]** Given the job's preflight, when the template is no longer APPROVED or the
  channel is no longer active, then the broadcast ends `FAILED` with a stored `error`, ZERO
  recipients are sent to, and the job finishes `failed`.
- **AC-BRD-30 [BE]** Given the fan-out, then recipients are processed in bounded chunks through
  Celery tasks (chained so at most one chunk per broadcast is in flight), and in eager dev / tests
  the handler loops the same chunk function inline - one code path, two dispatch modes.
- **AC-BRD-31 [BE]** Given a recipient, then the worker CLAIMS it atomically
  (`UPDATE ... SET attempted_at, attempts = attempts + 1 WHERE id = :id AND attempted_at IS NULL`,
  rowcount 1 wins) BEFORE calling the send path; re-running the same chunk (job retry, duplicate
  task delivery, resumed job) sends NOTHING a second time - a test that executes the chunk twice
  asserts exactly one `conversation_messages` row per recipient.
- **AC-BRD-32 [BE]** Given a claimed recipient, then the send goes through
  `MessageService.send_message` with `messageType = TEMPLATE`, the resolved header / body / button
  variables, and `channelIdOverride` = the broadcast's channel; the actor is the broadcast's
  `createdByUserId` resolved TENANT-SCOPED at use time (a deleted or foreign user resolves to no
  actor, never to another tenant's user).
- **AC-BRD-33 [BE]** Given an approved template send, then the 24-hour customer service window is
  NOT consulted (verified in `message_service.send_message`: the CSW guard sits on the free-form
  branch only) - a contact whose window closed still receives the broadcast.
- **AC-BRD-34 [BE]** Given a binding resolution, then a `static` binding is emitted verbatim, a
  `contactField` binding reads the contact's value and falls back to the configured `fallback` when
  the value is empty; every emitted parameter is sanitized for Meta's rules (no newline or tab, no
  run of 4+ spaces, capped length) and is never empty; a value that is still empty after the
  fallback marks the recipient `skipped/missing_variable` instead of sending a blank parameter.
- **AC-BRD-35 [BE]** Given a channel with a configured `broadcast_rate_per_second` (else the
  conservative global default), then a chunk paces its sends so the per-channel rate is not
  exceeded, and the pacing is asserted by a test that measures the computed delay (not by sleeping
  in the suite).
- **AC-BRD-36 [BE]** Given a send failure, then a TRANSIENT provider error leaves the message row on
  its existing retry path and the recipient `queued` (bounded retries), while a PERMANENT rejection
  records `failed` on that recipient with `errorCode` / `errorText`; one failed recipient never
  aborts the run and never rolls back other recipients.
- **AC-BRD-37 [BE]** Given a delivery status change on a broadcast message (the `send_runner`
  SENT / FAILED stamp and the inbound `_handle_status` receipt), then the matching
  `broadcast_recipients` row and the broadcast's denormalized counts are updated, receipts only move
  FORWARD (`queued -> sent -> delivered -> read`; a late `sent` after `read` is ignored), and a
  failure inside this hook is caught and logged - it never breaks the send path or the inbound
  webhook pipeline.
- **AC-BRD-38 [BE]** Given a recipient claimed but left with no `message_id` (a crash between the
  send commit and the recipient update), then the reconciler first ADOPTS a matching outbound
  template message for that contact created after the claim, and only if none exists marks the
  recipient `failed/send_result_unknown` - it NEVER re-sends.
- **AC-BRD-39 [BE]** Given every recipient has reached a terminal-for-dispatch state, then the
  broadcast moves to `SENT` with `finishedAt` set, the denormalized counts equal a live count over
  `broadcast_recipients` (invariant test), and the job finishes `done`.
- **AC-BRD-40 [BE]** Given `POST .../broadcasts/{id}/cancel` while `SCHEDULED`, then the status
  becomes `CANCELLED` and no send ever happens; while `SENDING`, the job stops at the NEXT chunk
  boundary (cooperative cancellation: the chunk re-reads the broadcast status from the DB each
  chunk), remaining `queued` recipients become `skipped/cancelled`, already-sent recipients keep
  their state and their receipts still apply; while `SENT`, `FAILED` or `CANCELLED`, the call
  returns 409.
- **AC-BRD-41 [BE]** Given `POST .../broadcasts/{id}/test-send {contactId}` by a user with
  `broadcasts.send`, then exactly one message is sent to that contact through the same send path
  with the same resolved bindings, NO `broadcast_recipients` row is created, the counts and the
  status are unchanged, and a contact outside this workspace returns 404.
- **AC-BRD-42 [BE]** Given the beat tick `omnichannel.broadcasts_due` (registered on the workflow
  beat, the sole beat host), then every `SCHEDULED` broadcast whose `scheduledAt` has passed is
  claimed with a guarded UPDATE and enqueued exactly once; a tick that runs after downtime still
  fires overdue broadcasts; the tick is failure-isolated and is a no-op when the module is absent.

## Slice S3 - Backend: events, realtime, permissions, contract hygiene

- **AC-BRD-43 [BE]** Given a broadcast reaches `SENT`, `FAILED` or `CANCELLED`, then exactly ONE
  `omnichannel_broadcast` `completed` entity event is emitted with the final status and counts, the
  emission is failure-isolated (a workflow-dispatch problem never fails the job), and no
  `conversation_events` row is written (a broadcast is not a conversation).
- **AC-BRD-44 [BE]** Given the module boots, then the workflow entity `omnichannel_broadcast` is
  registered (facts: name, status, channel, template, the six counts, scheduledAt; `writable` is
  EMPTY - a workflow can read a broadcast, never mutate one) so `record:omnichannel_broadcast` facts
  resolve for A5.
- **AC-BRD-45 [BE]** Given any broadcast state or count change (created, scheduled, sending, each
  chunk's count advance, terminal), then a `broadcast.updated` event is published to the workspace
  realtime room best-effort, carrying the broadcast id, status and counts; a dead Redis never fails
  the job.
- **AC-BRD-46 [BE]** Given this whole slice, then `routers/api_v1.py`, the `Rio*` schemas and
  `documentation/omnichannel/consumer-integration-guide.md` are UNCHANGED (broadcasts have no public
  gateway surface in v1) and the existing gateway contract-drift tests stay green.
- **AC-BRD-47 [BE]** Given permissions, then the module CSV gains `broadcasts.read`,
  `broadcasts.manage`, `broadcasts.send` (no core or module collision - verified 2026-09-06),
  implied-read normalization pulls `broadcasts.read` alongside the action keys, and existing
  tenants' Admin role receives them through the manifest version bump plus `update_tenant`.
- **AC-BRD-48 [BE]** Given `uninstall_tenant`, then this tenant's `broadcasts` and
  `broadcast_recipients` rows are removed by the generic `OmniBase` loop and another tenant's rows
  are untouched.
- **AC-BRD-49 [BE]** Given the wire, then every field is camelCase, every datetime-bearing schema
  inherits `ApiModel` and serializes Z-suffixed UTC, and every 422 uses the house
  `{fieldErrors: {path: message}}` shape.
- **AC-BRD-50 [BE]** Given the send job, then it appears in the Jobs surfaces (`GET /jobs/{id}` and
  the Jobs drawer) with `progress_total` = audience size and `progress_done` / `progress_failed`
  advancing per chunk, and its handler is registered through `register_job_handler` (no bespoke job
  table).

## Slice S4 - Wire-up, tests and evidence

- **AC-BRD-51 [T]** pytest covers: the create / update / delete 422 matrix (every branch
  of the validation AC), status-gated edits, duplicate, audience preview, audience snapshot including the
  join-after-snapshot case, all five skip reasons, preflight failure, per-recipient idempotency
  (chunk executed twice), CSW exemption for approved templates, actor resolution incl. the deleted
  and foreign user cases, binding resolution and sanitization, rate pacing computation, transient vs
  permanent failure handling, receipt forward-only updates from BOTH seams, reconciler adopt and
  give-up paths, count invariant, cancel from scheduled and mid-sending, scheduled beat claim,
  test-send creating no recipients, entity-event emission shape, realtime publish, permission gates
  per route, tenant isolation per route, uninstall cleanup, and a guard test that no gateway file
  changed.
- **AC-BRD-52 [T]** vitest covers: builder schema (audience exactly-one, binding count derived from
  the template shape, required fallback, past-schedule rejection, static text rejecting token
  syntax), template picker excluding non-approved and media-header templates, status badge registry
  mapping, recipient state filter, `useCan` gating of Send / Cancel, and the mock service states.
- **AC-BRD-53 [E2E]** Recorded `agent-browser --session s29` run (real clicks from `/`, never a
  typed URL, evidence at 375px AND 1280px under
  `documentation/plans/sprint-4/29-evidence/<slice>/` with a README run log), against the dev
  tenant's seeded sandbox channel `chn-demo` so every send is simulated by the dev-safe adapter:
  sidebar -> Omnichannel -> Broadcasts -> Create -> name `E2E broadcast <UTC timestamp>` -> audience
  = the 5 demo contacts -> channel Demo WhatsApp (sandbox) -> template `booking_update` -> bind slot
  1 to Contact field First name (fallback `there`) and slot 2 to static text -> Review -> Test send
  to one contact -> Send now -> the list shows Sending then Sent -> the detail Recipients tab lists
  every recipient with its state -> the counts match -> the Inbox thread of one recipient shows the
  template message.
- **AC-BRD-54 [E2E]** Same run: a SCHEDULED broadcast (a few minutes out) can be Cancelled from the
  list row action and lands in `Cancelled` with zero sends; a second, freshly provisioned tenant
  cannot see tenant A's broadcasts (API probe with tenant B's token returns 404 / empty); and a user
  whose role lacks `broadcasts.send` sees no Send control while the API still refuses the call.
- **AC-BRD-55 [T]** A Test Execution Report
  (`29-omnichannel-broadcasts-test-report.md`, `AI_Agent_Orchestration_Guide.md` section 6 format)
  records PASS / FAIL / DEFERRED per AC id and cites the evidence run for every `[E2E]` id;
  deferred items are registered in `documentation/backlogs/backlog.md` with a link back to this
  plan.
