# 33 - Omnichannel respond.io migration tool - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/33-omnichannel-respondio-migration.md`.
> **Program:** slice **A6** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gap G28,
> roadmap decision D12 "try the Developer API first, CSV exports as fallback").
> **Depends on (all must be merged to `main` before A6 branches):** plan 25 / A1 (typed contact
> fields, tags, lifecycle on the scoped status engine, `ContactProfileService`), plan 26 / A2
> (contacts module, `phone_digits`, `ImporterDef("omnichannel_contacts")`, contacts export job),
> plan 27 / A3 (`conversation_events` + `event_service.record()`, close reasons, inbox views),
> plan 28 / A8 (core `teams`, omnichannel assignment), plan 30 / A9 (dashboard + reports that read
> the backfilled events), plan 31 / A5 (workflow parity - A6 must not fire any of it), plan 32 /
> A7a (Messenger + Instagram channel types, if it lands first).
> **Out of scope (stated, never silently missing):** workflows (re-authored by hand, respond.io has
> no export format we can consume), broadcasts and broadcast history, reports and analytics history,
> internal comments and closing-note text, AI agents and knowledge sources, the files library,
> growth widgets, blocked-contact flags, collaborators, contact merge history. The WABA number move
> is a documented runbook step, not code. The public gateway (`/api/v1/omnichannel/*`, `Rio*`
> schemas, `routers/api_v1.py`) is NOT touched by this slice.

IDs: `AC-MIG-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Definitions

- **Source** - one respond.io **Space** (their word for a workspace), reached through the
  Developer API v2 at `https://api.respond.io/v2` with a workspace access token
  (`Authorization: Bearer <token>`), or through a CSV export bundle when the customer's plan has
  no API access.
- **Target** - exactly ONE Foundryx `app_omnichannel.workspaces` row inside ONE tenant. A source
  space always migrates into a single target workspace; there is no fan-out.
- **Migration job** - one `background_jobs` row of type `omnichannel.respondio_migration`. Its
  `payload_json.mode` is `dry_run` or `run`. There is ONE job type and ONE handler; the mode is a
  flag on the same code path, never a second implementation.
- **Dry run** - a real run with every write suppressed and every media fetch skipped, executed
  inside a transaction that is rolled back at the end. It produces the **counts report**.
- **Counts report** - `result_json.report`: per entity `{fetched, wouldCreate, wouldUpdate,
  wouldSkip, errors}`, a `samples` block (at most 10 rows per entity), and a `blockers[]` list.
- **Mapping** - the operator-chosen `payload_json` blocks `channelMap`, `userMap`, `teamMap`,
  `lifecycleMap` that bind source ids to Foundryx ids before any run.
- **`migration_refs`** - the module table that records `(source external id) -> (Foundryx local
  id)` per entity type. It is the ONLY idempotency index: a re-run skips every external id already
  present. Marker columns (`contacts.migrated_from`, `conversation_messages.migrated_from`) are
  descriptive, never the key.
- **Read-only history row** - a `conversation_messages` row written by the migration writer:
  original timestamp, preserved `sender_type`, `external_message_id` left NULL, no realtime
  publish, no entity event, no consumer-webhook fan-out, no CSW recompute, no unread bump.
- **Backfilled event** - a `conversation_events` row derived from migrated history (respond.io has
  no event or assignment-log endpoint), stamped `payload_json.migration.derived = true` and carrying
  the SOURCE timestamp in `created_at`.
- **Migration writer** - the one service that writes migrated rows. It is not `MessageService`, not
  `InboundService`, and not `ContactAdminService`.

---

## Slice S0 - Frontend on the mock service

- **AC-MIG-01 [FE]** Given the omnichannel module is ACTIVE and the user holds
  `omnichannel_migration.read`, then a **Migration** entry appears under the Omnichannel settings
  group in ALL three menu arrays (`MENU_SIDEBAR`, `MENU_MEGA`, `MENU_MEGA_MOBILE`), tagged
  `module: 'omnichannel'` + `permission: 'omnichannel_migration.read'`; a tenant without the module
  or without the key sees no entry on any of the three surfaces.
- **AC-MIG-02 [FE]** Given `/omnichannel/settings/migration`, then the job history renders on the
  Resource shell cloned from Users (never a hand-rolled table) with columns Source, Target
  workspace, Mode, Status, Progress, Contacts, Messages, Failures, Started, Finished; server-side
  sort, filter and pagination through `useResourceList`; per-user column preferences under
  `viewKey` `omnichannel.migration.list`.
- **AC-MIG-03 [FE]** Given "New migration", then the setup surface is a `ResourceForm` with ordered
  sections Source, Target, Channels, People, Lifecycle, Scope, Review - not a bespoke wizard - and
  the shell's global Edit toggle plus its AlertDialog dirty-guard apply.
- **AC-MIG-04 [FE]** Given the Channels section, then one `SearchSelect` renders per source channel;
  its options are only the target workspace's channels whose `channelType` matches the source
  `source` value, plus an explicit "Skip this channel" option; a source channel with no compatible
  target renders with "Skip this channel" preselected and no other option (foolproof-UI: the picker
  only offers valid targets).
- **AC-MIG-05 [FE]** Given the People section, then each source user renders a `SearchSelect` of the
  tenant's users prefilled with the email match when one exists and left empty otherwise, and each
  source team renders a `SearchSelect` of the tenant's teams; no free-text id entry exists anywhere.
- **AC-MIG-06 [FE]** Given the Lifecycle section, then each observed source lifecycle label renders
  a `SearchSelect` of the TARGET workspace's existing lifecycle stages; the surface never offers to
  create a stage, and an unmapped label is allowed (its contacts land with no lifecycle) and is
  reported as a blocker in the dry-run report.
- **AC-MIG-07 [FE]** Given the Review section, then the only enabled primary action is "Run dry
  run"; "Start migration" is disabled and stays disabled until a successful dry run for this exact
  mapping exists.
- **AC-MIG-08 [FE]** Given a job detail route `/omnichannel/settings/migration/{jobId}`, then it
  renders the job facts, a `Progress` bar, the milestone log, an `ActionMenu` carrying Abort while
  in flight and Retry when terminal, a counts-report card (one `DataGrid` per entity) and a
  per-entity failure table (`DataGrid`: Entity, Source id, Source label, Reason, Action taken) with
  a Download link for the full failure CSV; it polls while the job is in flight and stops when it
  is terminal.
- **AC-MIG-09 [FE]** Given the service trio `services/respondio-migration-service.{ts,mock,real}.ts`,
  then every surface above renders correctly against the mock for loading, empty, populated,
  in-flight, aborted, failed and `needs_review` states; no component calls `fetch`/`axios`
  directly and no `any` type appears.
- **AC-MIG-10 [FE]** Every surface in this slice is usable and non-clipped at 375px and at 1280px;
  every dropdown is a `SearchSelect`; no instructional or how-to copy appears anywhere; no
  tenant-facing string says "Foundryx".

## Slice S1 - Connection provider and preflight

- **AC-MIG-11 [BE]** Given the omnichannel module is installed, then an `IntegrationProvider` with
  `provider = "respondio"` and `type = "migration"` is registered from the module's bootstrap; its
  `fields()` declares plain config `baseUrl` (default `https://api.respond.io/v2`), `spaceLabel`,
  `timezone` (IANA, required) and `requestsPerSecond` (default 4, max 20), and the secret field
  `apiToken`.
- **AC-MIG-12 [BE]** Given a saved respond.io connection, then `apiToken` is Fernet-encrypted in
  `credentials_json`, never echoed on any read, and a PATCH that sends a blank `apiToken` keeps the
  stored value while a partial `config` PATCH merges rather than wipes.
- **AC-MIG-13 [BE]** Given "Test connection", then `test()` issues `GET /space/channel` with a 10
  second cap and returns a clean `TestResult`; a 401 reports that the token was rejected, a 403
  reports that the space's plan does not include the Developer API, and no vendor traceback, DSN or
  token fragment ever reaches the response or the logs.
- **AC-MIG-14 [BE]** Given the preflight route `GET /omnichannel/migration/preflight?connectionId=`,
  then it returns the source channels (`GET /space/channel`), source users with their team
  (`GET /space/user`), source custom fields (`GET /space/custom_field`) and a `apiAvailable`
  boolean; it performs ZERO writes, and it resolves the connection with an explicit
  `tenant_id` filter (never a bare `get_by_id`, never the platform fallback).
- **AC-MIG-15 [BE]** Given the API client, then it self-throttles to the connection's
  `requestsPerSecond`, honours a `retry-after` header exactly, reads `x-ratelimit-limit` and
  `x-ratelimit-remaining`, retries 429 and 5xx with exponential backoff and jitter up to 5 attempts,
  and halves its own rate for the remainder of a run after a fourth consecutive 429 (recorded as a
  milestone log line).
- **AC-MIG-16 [BE]** Given a 4xx that is not 429, then the client raises a typed error carrying the
  respond.io `{code, message}` body; the caller maps it to a job failure or a per-entity report row
  and never to an unhandled 500.
- **AC-MIG-17 [T]** pytest covers: provider `fields()` shape, blank-secret-keeps-value, test()
  success and 401 and 403 branches, throttle pacing, retry-after honouring, backoff ceiling,
  pagination cursor walking over a stubbed transport, and tenant-scoped connection resolution.

## Slice S2 - Migration job, contacts phase, dry run

- **AC-MIG-18 [BE]** Given module Alembic revision `0017_omni_migration_refs` (renumbered at merge
  per the plan's merge rule - `down_revision` re-pointed at `main`'s then-current head,
  `0016_omni_business_hours`), then `app_omnichannel.migration_refs` exists with `(id, tenant_id,
  workspace_id, source, entity_type, external_id, local_id, created_at)`, a UNIQUE index on
  `(tenant_id, workspace_id, source, entity_type, external_id)` and an index on `(tenant_id,
  workspace_id, source, entity_type, local_id)`; `contacts.migrated_from` and
  `conversation_messages.migrated_from` are added as nullable indexed strings; the revision is
  idempotent (inspector guards) and `bootstrap.create_schema_and_tables` carries the matching
  `ADD COLUMN IF NOT EXISTS` mirror for `create_all` deployments.
- **AC-MIG-19 [BE]** Given `POST /omnichannel/migration/jobs` with `{connectionId, workspaceId,
  mode, channelMap, userMap, teamMap, lifecycleMap, messagesSince?, contactsOnly?}`, then a
  `background_jobs` row of type `omnichannel.respondio_migration` is created and enqueued through
  `JobService.create_and_enqueue`; the handler is registered via `register_job_handler` and no new
  bespoke job table is introduced.
- **AC-MIG-20 [BE]** Given a run in `run` mode with no successful dry run for the same
  `(connectionId, workspaceId, mapping hash)` inside the last 24 hours, then the request is refused
  `409 dry_run_required`; the frontend's Start control is disabled in exactly the same condition.
- **AC-MIG-21 [BE]** Given a non-terminal migration job already exists for the same
  `(tenant, workspace)`, then a second create is refused `409 migration_in_progress`.
- **AC-MIG-22 [BE]** Given the contacts phase, then the source is walked with
  `POST /contact/list` (body `{search?, timezone, filter}`, query `limit` + `cursorId`); the walk
  writes `cursor_json` after EVERY page, and a crash-resume (`status == running` at pickup)
  continues from the stored cursor without re-processing a completed page.
- **AC-MIG-23 [BE]** Given a source contact, then the target is resolved in this order:
  `migration_refs` hit, then `phone_digits` match inside the target workspace, then lowercased
  email match, then create. A matched contact is MERGED (only NULL system fields are filled, tags
  are unioned, an existing lifecycle stage is never moved, no Foundryx value is overwritten); a
  created contact gets its initial lifecycle stage from `lifecycle_service.initial_status_id` when
  no source stage maps.
- **AC-MIG-24 [BE]** Given source custom fields, then each `dataType` maps 1:1 onto our contact
  field types (`text | list | checkbox | email | number | url | date | time`) and a missing field is
  created through `ContactFieldService`; values arrive as `custom_fields: [{name, value}]` and are
  written through `ContactProfileService`-grade validation so an out-of-registry key is a reported
  row error, never a raw JSON write.
- **AC-MIG-25 [BE]** Given source tags (`contact.tags: string[]`), then each distinct name is
  find-or-created through `ContactTagService` inside the target workspace and linked; the source has
  no tag list endpoint, so tag colour, emoji and description are not migrated and that is stated in
  the report.
- **AC-MIG-26 [BE]** Given a source `assignee`, then it resolves to a `users` row by lowercased
  email filtered by `User.tenant_id == tenant_id`; no match leaves `assigned_user_id` NULL and adds
  one report row. The migration never creates a user, a role or a team.
- **AC-MIG-27 [BE]** Given `mode = "dry_run"`, then zero rows are written anywhere (contacts,
  identities, messages, events, tags, fields, quick replies, `migration_refs`, storage blobs), no
  media URL is fetched, and `result_json.report` carries per-entity counts, at most 10 samples per
  entity and the `blockers[]` list; the job finishes `done`.
- **AC-MIG-28 [BE]** Given a running job whose status is set to `aborted` on another session, then
  the handler re-reads its OWN status from the database at every batch checkpoint and bails BEFORE
  the terminal step, leaving the job `aborted` with its cursor and partial counts intact; a later
  re-run resumes from `migration_refs` and creates no duplicates.
- **AC-MIG-29 [T]** pytest covers: `migration_refs` uniqueness and re-run skip, cursor resume,
  cooperative abort (with a control proving the same call in real mode does write), contact match
  ladder including the merge rules, custom-field type map, tag find-or-create cap, assignee email
  match including a foreign-tenant email that must NOT match, dry-run write absence on a savepoint
  fixture paired with a real-mode control, and the `dry_run_required` and `migration_in_progress`
  guards.

## Slice S3 - Channel identities and message history

- **AC-MIG-30 [BE]** Given a mapped source channel, then `GET /contact/{identifier}/channels` yields
  the contact's per-channel identity and a `contact_channel_identities` row is written with
  `channel_id` = the mapped Foundryx channel and `external_user_id` derived from the source
  identity; when a real external id cannot be derived the identity row is SKIPPED and reported -
  a fabricated external id is never written (it would poison the live inbound stitch).
- **AC-MIG-31 [BE]** Given `SOURCE_TO_CHANNEL_TYPE`, then every respond.io `ChannelSource` value
  (`whatsapp`, `whatsapp_cloud`, `360dialog_whatsapp`, `twilio_whatsapp`,
  `message_bird_whatsapp`, `nexmo_whatsapp`, `facebook`, `instagram`, `telegram`, `line`, `viber`,
  `wechat`, `twitter`, `custom_channel`, `gmail`, `other_email`, `twilio`, `message_bird`, `nexmo`)
  is present in the map; adding a future channel type is a dict row plus a `channels.channel_type`
  value and requires NO schema change (pinned by a test that asserts the map covers the documented
  source list).
- **AC-MIG-32 [BE]** Given a contact's message history, then it is walked with
  `GET /contact/{identifier}/message/list` (`limit` + `cursorId`) and each item is written as a
  read-only history row: `sender_type` = `CONTACT` for `traffic == "incoming"`, `AGENT` for
  `traffic == "outgoing"`, with `sender_id` set only when `sender.source == "user"` and the user id
  maps to a tenant user; every other outgoing source keeps `sender_id` NULL and records
  `payload_json.migration.senderSource`.
- **AC-MIG-33 [BE]** Given a migrated message row, then `external_message_id` is NULL, no
  `realtime.publish` is called, no `emit_entity_event` or `notify_entity_event` is called, no
  consumer webhook is enqueued, `csw_expires_at` is not recomputed and the thread's unread state is
  not raised (pinned by a test that asserts each of those seams is never invoked during a run).
- **AC-MIG-34 [BE]** Given message timestamps, then `created_at` is `min(status[].timestamp)` when a
  status array exists; otherwise it is interpolated between the nearest bracketing known timestamps
  of the same contact; otherwise it falls back to the source `contact.created_at`. Every inferred
  timestamp sets `payload_json.migration.timestampInferred = true` and increments a report counter.
  Thread ordering always follows the source `messageId`, never the resolved timestamp.
- **AC-MIG-35 [BE]** Given each source message `type`, then it maps as: `text` to `TEXT`;
  `attachment` to `IMAGE | VIDEO | AUDIO | DOCUMENT` by `attachment.type`; `quick_reply` to
  `INTERACTIVE` with the replies in `payload_json`; `whatsapp_template` to `TEXT` carrying the
  rendered body plus `payload_json.template`; `email` to `TEXT` plus `payload_json.email`;
  `custom_payload` to `TEXT` plus `payload_json.custom`. An unrecognised `type` is written as `TEXT`
  with `payload_json.migration.unmappedType` and a report row - a message is never dropped.
- **AC-MIG-36 [BE]** Given delivery status, then the last `status[].value` maps onto
  `QUEUED | SENT | DELIVERED | READ | FAILED`; an inbound message with no status array leaves
  `delivery_status` NULL.
- **AC-MIG-37 [BE]** Given a contact's message phase completes, then exactly ONE recompute per
  contact sets `last_message_at`, `last_incoming_message_at` and `last_agent_message_at` to the
  maxima over existing plus migrated rows, and sets `agent_last_read_at` to `last_message_at` so a
  backfilled thread does not arrive as a wall of unread; `csw_expires_at` is left untouched.
- **AC-MIG-38 [T]** pytest covers: identity derivation and the skip-on-underivable rule, the source
  map coverage test, sender mapping for all six `sender.source` values, timestamp resolution
  (explicit, interpolated, fallback) and its inferred counter, every message-type branch including
  the unmapped one, delivery-status mapping, the per-contact recompute maths, and the
  no-publish / no-event / no-webhook assertions.

## Slice S4 - Media, derived events, quick replies

- **AC-MIG-39 [BE]** Given a message with `attachment.url`, then the blob is fetched with a 30
  second timeout and a capped read using the workspace's `omnichannel_settings` per-type byte caps,
  sniffed with `app/uploads.detect_upload_mime` (the declared content type is ignored), and stored
  via `storage_for_tenant(db, tenant_id).save(...)` under a migration-scoped key; the resulting
  storage key lands in `conversation_messages.media_key` with `media_mime`, `media_size` and
  `media_filename`.
- **AC-MIG-40 [BE]** Given any media failure (404, timeout, oversize, rejected mime, storage
  hiccup), then the MESSAGE row is still written with its caption or text, `media_url` retains the
  original source URL, `payload_json.migration.mediaError` records the reason, `progress_failed` is
  incremented and one failure row is recorded; the job is NEVER aborted by a media failure.
- **AC-MIG-41 [BE]** Given a contact's history is migrated, then derived `conversation_events` rows
  are written through `event_service.record()` on the same session: `opened` at the first migrated
  message, `first_agent_reply` at the first outgoing message after it (honouring the once-per-cycle
  rule), `closed` at the last message when the source `contact.status == "close"`, `assigned` when
  an assignee mapped, and `lifecycle_changed` when a stage mapped.
- **AC-MIG-42 [BE]** Given a derived event, then `created_at` is the SOURCE timestamp (never
  `now()`), and `payload_json.migration.derived` is `true` so A9 reports can exclude backfilled
  activity; no `reopened`, `snoozed`, `unsnoozed` or `comment_added` event is fabricated (the source
  exposes no data for them).
- **AC-MIG-43 [BE]** Given a migration into a workspace whose A9 dashboard is open, then the
  "conversations opened" chart shows the migrated conversations on their ORIGINAL dates, not on the
  migration date.
- **AC-MIG-44 [BE]** Given a quick-replies CSV upload (columns `shortcut`, `body`), then rows are
  read through `app/import_engine/readers.py` and created as `quick_replies` rows in the target
  workspace, de-duplicated by `shortcut`; the report states that respond.io exposes no snippets
  endpoint on the Developer API so this path is CSV or manual only.
- **AC-MIG-45 [T]** pytest covers: media size cap, sniff rejection, oversize skip, storage failure
  continue-on-error, key format, event derivation for open-only / open-and-closed / assigned /
  lifecycle threads, the once-per-cycle first-reply rule against `is_first_reply_pending`, explicit
  event `created_at`, and quick-reply de-duplication.

## Slice S5 - CSV fallback

- **AC-MIG-46 [BE]** Given the preflight reports `apiAvailable = false`, then the setup surface
  offers the CSV path: contacts are handed to the EXISTING contacts import wizard
  (`ImporterDef("omnichannel_contacts")`) and the migration form links to it rather than
  re-implementing contact parsing.
- **AC-MIG-47 [BE]** Given a migration job with `payload.source = "csv"` and an uploaded message
  export, then rows are read through `app/import_engine/readers.py read_rows` (magic-byte sniffed,
  capped, formula-sanitized), mapped through an operator-chosen header map, and written by the SAME
  migration writer with the same `migration_refs` idempotency.
- **AC-MIG-48 [BE]** Given CSV mode, then the report states up front, before the run, that no media
  is migrated and no channel identity is created (the export carries neither), and the dry-run
  `blockers[]` carries both facts; neither is discovered mid-run.
- **AC-MIG-49 [T]** pytest covers: CSV header mapping, the reader's row cap, formula sanitization on
  the failure export, CSV-mode idempotency and re-run skip, and the two CSV-mode blockers.

## Cross-cutting - security, tenancy, permissions

- **AC-MIG-50 [BE]** Given the new permission keys `omnichannel_migration.read` and
  `omnichannel_migration.manage` in the module CSV, then reads are gated by `.read`, every mutating
  route by `.manage`, implied-read normalization forces `.read` alongside `.manage`, and an
  already-provisioned tenant receives the keys through the manifest version bump plus
  `update_tenant` (so the feature never silently 403s or hides). No existing key is reused.
  **Disclosed deviation (review round 1 nit):** `GET .../preflight` is gated `.manage`, not `.read`
  as this AC's own wording implies - preflight is the FIRST call the setup form makes and always
  precedes a write, so gating it at the stricter permission spends no extra token in practice and
  keeps "can see this respond.io space's data" and "can start a migration" as one grant. Pinned by
  `test_preflight_requires_manage_permission`.
- **AC-MIG-51 [BE]** Given any migration route or job step, then every query is scoped by the
  tenant id taken from the JWT (or from the job row for the worker) and never from client input;
  `workspaceId`, `connectionId` and every mapped user, team, channel and stage id is re-validated
  against that tenant at USE time, not only at save time.
- **AC-MIG-52 [BE]** Given tenant A holds a respond.io connection, then tenant B can neither read it,
  reference it in a job payload, nor observe its existence: a foreign `connectionId` returns the
  same `404` as a missing one, and the token is never resolved through the platform-tenant
  fallback.
- **AC-MIG-53 [BE]** Given the failure export route, then it is an AUTHED streaming download (the
  `imports` errors-file precedent), gated by `omnichannel_migration.read`, tenant and job-type
  checked, served `private, no-store` - never a bearer-less signed capability URL, because the file
  contains contact names, phones and emails.
- **AC-MIG-54 [BE]** Given a module uninstall for a tenant, then `uninstall_tenant` deletes that
  tenant's `migration_refs` rows along with the rest of the module's rows, and leaves core
  `background_jobs` retention to handle the job rows.
- **AC-MIG-55 [BE]** Given the whole slice, then `git diff` touches neither
  `modules/omnichannel/routers/api_v1.py` nor the `Rio*` schemas nor
  `documentation/omnichannel/consumer-integration-guide.md`; a guard test asserts the gateway
  contract files are unchanged.

## Slice S6 - Wire, evidence, runbook, report

- **AC-MIG-56 [FE]** Given S6, then every mock service call is swapped for the real `api-client`
  call at the service boundary only (one line per method); no phase-1 in-memory service survives,
  and the surfaces render real data from the backend.
- **AC-MIG-57 [FE]** Given the job detail page during a live run, then progress, milestone logs and
  counts update by polling and the page stops polling on a terminal status; Abort is offered only
  while in flight and takes effect within one poll cycle.
- **AC-MIG-58 [T]** vitest covers: the setup form schema (required connection, required workspace,
  channel map completeness, mapping hash stability), the Start-disabled-until-dry-run rule, the
  status badge registry, the failure-table renderer, `useCan` gating of Start and Abort, and every
  mock service state.
- **AC-MIG-59 [E2E]** Recorded `agent-browser --session s33` run (real clicks from `/`, never a
  typed URL, evidence at 375px AND 1280px under
  `documentation/plans/sprint-4/33-evidence/<slice>/` with a README run log), against a dedicated
  timestamped tenant and a stub respond.io transport: sidebar to Omnichannel to Settings to
  Migration, New migration, pick the connection, Test, pick the target workspace, map one channel,
  map one user, map one lifecycle label, Run dry run, read the counts report, Start migration,
  watch progress to `done`, then open Inbox and confirm a migrated thread shows its history in
  original order with the original dates and no unread badge.
- **AC-MIG-60 [E2E]** Same run: re-running the identical migration reports zero creates and zero
  duplicates; aborting a running migration leaves it `aborted` with partial counts and a later
  re-run resumes; a user whose role lacks `omnichannel_migration.manage` sees no Start control and
  the API refuses the call; a second freshly provisioned tenant sees none of tenant A's migration
  jobs.
- **AC-MIG-61 [T]** A Test Execution Report (`33-omnichannel-respondio-migration-test-report.md`,
  `AI_Agent_Orchestration_Guide.md` section 6 format) records PASS / FAIL / DEFERRED per AC id and
  cites the evidence run for every `[E2E]` id; deferred items are registered in
  `documentation/backlogs/backlog.md` with a link back to this plan; and
  `documentation/omnichannel/respondio-cutover-runbook.md` ships in the same slice, covering the
  customer prerequisites, the WABA number move (Embedded Signup re-onboarding plus template
  re-sync) and the cut-over order.
