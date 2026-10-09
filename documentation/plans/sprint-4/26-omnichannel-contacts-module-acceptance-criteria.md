# 26 - Omnichannel Contacts module (list, segments, form, bulk, import/export) - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/26-omnichannel-contacts-module.md`.
> **Program:** slice **A2** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0, gaps G4 + G5).
> **Builds on:** plan 25 / slice A1 (typed contact fields, tags, lifecycle on the scoped status
> engine, `ContactProfileService`, `lifecycle_service`, `ThreadItem` shape). A2 adds NO new contact
> entity - the contact is still the A1 `contacts` row.
> **Decisions carried in (main session, 2026-09-06):** D-A2-1..D-A2-8 (see the plan §3).
> **Out of scope (later slices):** inbox views + close notes (A3), broadcasts (A4), workflow
> triggers/steps for contact events (A5), teams (A8), merge / block / blocked-contacts view (B2),
> reports (A9), collaborators (B1).

IDs: `AC-CTM-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Definitions

- **Workspace** - `app_omnichannel.workspaces`. Every route, segment, tag, field and contact in this
  slice hangs off ONE workspace; tenant isolation applies on top of that.
- **Contact** - the A1 `contacts` row (contact = thread). No new table, no new identity.
- **Contacts module** - the `/omnichannel/contacts` Resource-shell list + `/omnichannel/contacts/{id}`
  detail + the create form, distinct from the Inbox (`/omnichannel/inbox`), which is unchanged.
- **System column** - a real `contacts` column or A1 relation surfaced on the list: name, phone,
  email, lifecycle, tags, assignee, channel, last message, created.
- **Custom-field column** - a registered A1 `contact_fields` row, addressed on the wire as
  `customFields.<key>`; values live in `contacts.custom_fields_json`.
- **Segment** - a saved, named filter tree on a workspace (`contact_segments`), stored in the SAME
  `FilterGroup` shape the Resource shell's filter builder emits and applied in SQL through
  `services/filter_translator.py translate_filter`. A3 (inbox views) and A4 (broadcast audiences)
  consume the same row.
- **Bulk action** - assign / add tags / remove tags / move lifecycle over a selected id set, executed
  by iterating the A1 services per record inside bounded batches (never a raw `UPDATE`).
- **Export job** - a `background_jobs` row of type `omnichannel.contacts_export` whose handler writes
  ONE CSV to the tenant's active storage connection.
- **Importer** - `ImporterDef("omnichannel_contacts")` on the core import engine (two-phase
  Test then Import, all-or-nothing, `id`-only matching).

---

## Slice 0 - Frontend on the mock service

- **AC-CTM-01 [FE]** Given the `omnichannel` module is ACTIVE and the user holds `contacts.read`,
  then a **Contacts** entry appears in the Omnichannel menu block directly after Inbox, tagged with
  `module: 'omnichannel'` + `permission: 'contacts.read'` in **all three** menu arrays
  (`MENU_SIDEBAR`, `MENU_MEGA`, `MENU_MEGA_MOBILE`); a tenant without the module, or a user without
  `contacts.read`, sees no Contacts entry on any menu surface. Two pre-existing gaps are closed in
  the same edit (verified 2026-09-06 in `config/menu.config.tsx`): the `MENU_MEGA` Omnichannel block
  carries no `module` tag and no `permission` on its children (so it leaks omnichannel paths to
  tenants without the module), and `MENU_MEGA_MOBILE` has no Omnichannel block at all.
- **AC-CTM-02 [FE]** Given `/omnichannel/contacts`, then it renders a full-width Resource-shell list
  cloned from Users (`components/platform/resource-list`) with the columns Name, Phone, Email,
  Lifecycle (StatusBadge-style chip with the stage label + colour), Tags (`OverflowPills`), Assignee,
  Channel, Last message, Created, plus the leading `select` column and the trailing row `...` action
  menu; no hand-rolled table markup exists in the route.
- **AC-CTM-03 [FE]** Given the list, then the search box carries hints Name / Phone / Email and every
  search, sort, filter, segment and page change issues ONE server request (no client-side filtering
  of the page), and the Columns chooser persists visibility per user under the view key
  `omnichannel.contacts.list`.
- **AC-CTM-04 [FE]** Given the Filters builder, then it offers the system fields plus one entry per
  registered custom field of the active workspace (label = the field label, type derived from the
  field type), and offers no field that the server would reject.
- **AC-CTM-05 [FE]** Given saved segments exist, then the list renders an N-way `segments`
  `SearchSelect` (All contacts + one entry per segment, resolved for the active workspace); switching
  segment clears row selection and re-queries; the selected segment id rides `ListQuery.segment`.
- **AC-CTM-06 [FE]** Given a user with `segments.manage`, then the list offers "Save as segment" for
  the current filter tree (name dialog) and a segment manage dialog (rename, edit filter, delete);
  without `segments.manage` neither control renders. **Amended 2026-09-06 (review round 1):** delete
  goes through the deferred grace window (`contact_segments.delete`, `useDeferredAction` +
  `deferredToast`) - no confirmation dialog; Cancel withdraws it while the window is open, matching
  every other destructive action in this module (a hand-rolled `AlertDialog` here was a
  design-language hard-fail).
- **AC-CTM-07 [FE]** Given a row click, then `/omnichannel/contacts/{id}` opens as a Resource **form**
  (dirty-guard, circular `N / M` record-nav carried from the list ctx) with tabs **Details** (reusing
  the A1 `contact-details-form`, `lifecycle-move` and `tag-chips` components) and **Conversation**
  (mounting the existing `<ConversationDrawer>`); no second chat implementation is written. **Amended
  2026-09-06 (review round 1):** the detail page reuses the A1 contact panel's per-section edit
  affordances (each gated `contacts.manage`) - there is no outer global Edit toggle, since that would
  be a second, redundant way to enter edit mode over the same fields.
- **AC-CTM-08 [FE]** Given "Add contact", then the create route renders the same Resource form with
  First name, Last name, Phone (required, create only), Email, Language, Country, Lifecycle stage
  (defaulted to the workspace initial stage), Tags and every registered custom field with a typed
  input; on an existing contact the Phone input is read-only.
- **AC-CTM-09 [FE]** Given rows are selected, then the bulk toolbar offers Assign, Add tags, Remove
  tags and Move lifecycle; each opens a dialog whose picker is a `SearchSelect` / `MultiSelect`; on
  completion a toast reports `N updated` and, when any record failed, the per-record reasons are
  listed (never a bare "something went wrong").
- **AC-CTM-10 [FE]** Given the list toolbar, then Import (import-engine wizard, entity type
  `omnichannel_contacts`, context = the active workspace) and Export are both present; Export
  downloads a CSV of the current query, and when the export has not finished inside the wait window
  the user is told it continues in Jobs (with the Jobs surface reachable), never left with a silent
  failure.
- **AC-CTM-11 [FE]** Given every new surface (list, detail tabs, create form, segment dialogs, bulk
  dialogs, import entry), then at ~375 px and ~1280 px there is no horizontal page scroll, no clipped
  or overlapping control, tabs scroll rather than blow out the layout, and dialogs are usable at both
  widths.
- **AC-CTM-12 [FE]** Given any picker in this slice, then it offers only valid options - assignee =
  the workspace's members, tags = that workspace's tags, lifecycle = that workspace's stages, custom
  field `list` = the field's registered options - and no instructional / how-to copy is rendered on
  any of these surfaces.
- **AC-CTM-13 [FE]** Given a user without `contacts.manage`, then Add contact, the bulk actions, the
  detail form's per-section edit affordances (Details/lifecycle/tags) and Import are not rendered
  (`useCan` is UX only, the API stays the real gate); the list itself still reads with `contacts.read`.
  **Amended 2026-09-06 (review round 1):** "the Edit toggle on the detail form" -> "the detail form's
  per-section edit affordances" (see AC-CTM-07's amendment - there is no outer Edit toggle).

## Slice 1 - Backend: list, filter, sort, segments

- **AC-CTM-14 [BE]** Given `GET /omnichannel/workspaces/{workspaceId}/contacts`, then it returns
  `{data, total, page}` of `ContactListItem`, scoped to the caller's tenant AND that workspace,
  ordered by `lastMessageAt` desc nulls last then `createdAt` desc by default, with `pageSize`
  capped at 200 (422 above).
- **AC-CTM-15 [BE]** Given `search`, then it matches first name, last name, the concatenated full
  name, phone (digits-insensitive to formatting) and email, case-insensitively, and NEVER message
  bodies (that behaviour stays on the inbox thread list, which is untouched).
- **AC-CTM-16 [BE]** Given `filter`, then it is translated by `translate_filter` over a whitelisted
  column map (name, firstName, lastName, phone, email, language, countryCode, priority, assignee,
  channelType, lifecycle, tags, lastMessageAt, createdAt, plus `customFields.<key>`); an unknown
  field returns 422 naming the field, and a tree deeper than `MAX_GROUP_DEPTH` returns 422.
- **AC-CTM-17 [BE]** Given a `customFields.<key>` filter, then it resolves only for a key registered
  on THAT workspace (unregistered or cross-workspace key returns 422), and the comparison runs in SQL
  through a dialect-portable JSON accessor so the same test passes on Postgres and on the SQLite test
  engine.
- **AC-CTM-18 [BE]** Given `sortBy`, then only whitelisted sort keys are accepted (422 otherwise) and
  `sortDir` accepts `asc` / `desc` only.
- **AC-CTM-19 [BE]** Given a `ContactListItem`, then it carries every `ThreadItem` field (A1 shape,
  including `lifecycle`, `tags`, `customFields` restricted to registered keys) PLUS
  `channels: [{channelId, channelType, name}]` resolved tenant-scoped from
  `contact_channel_identities`; a contact with no identity returns `[]` and never a defaulted
  channel type.
- **AC-CTM-20 [BE]** Given segments, then `GET/POST/PATCH/DELETE
  /omnichannel/workspaces/{workspaceId}/contact-segments` manage per-workspace rows with a
  case-insensitively unique `name` (422 on duplicate), a cap of 100 per workspace (422), and a
  save-time validation of the stored filter tree against the SAME whitelisted column map (422 naming
  the offending field, nothing written).
- **AC-CTM-21 [BE]** Given `segment=<id>` on the list, then the stored tree is applied in SQL, ANDed
  with any ad-hoc `filter` from the caller (never evaluated in Python over fetched rows), and a
  segment id belonging to another workspace or tenant returns a uniform 404.
- **AC-CTM-22 [BE]** Given permissions, then list + detail reads require `contacts.read`, segment
  writes require `segments.manage`, and a tenant B caller hitting any route in this slice with a
  tenant A workspace id or contact id gets a uniform 404 (never 403, never data).
- **AC-CTM-23 [BE]** Given a page of N contacts, then tags, channel identities, lifecycle stages, the
  custom-field registry and assignee names are each resolved in ONE batched query for the whole page
  (a query-count test pins it) - no per-row lookups.

## Slice 2 - Backend: create / update / bulk

- **AC-CTM-24 [BE]** Given `POST /omnichannel/workspaces/{workspaceId}/contacts` by a user with
  `contacts.manage`, then the contact is created through `ContactProfileService` (typed
  `customFields` + `tagIds` validation, 422 `{fieldErrors}` with nothing written), gets the
  workspace's `is_initial` lifecycle stage via `lifecycle_service.initial_status_id`, thread status
  OPEN and priority MEDIUM, emits ONE `omnichannel_contact` `created` entity event after commit, and
  returns 201 with the `ContactListItem`.
- **AC-CTM-25 [BE]** Given a create payload, then `phone` is required and normalized to `+<digits>`,
  and a phone whose digits already exist on another contact in that workspace returns 422 on the
  `phone` field with nothing written.
- **AC-CTM-26 [BE]** Given a contact created manually, when an inbound message later arrives from
  that number on a channel of the same workspace, then `InboundService._resolve_contact` stitches
  onto the existing row (no duplicate contact) - the create path normalizes phone exactly the way the
  stitch compares it, and a regression test pins the pair.
- **AC-CTM-27 [BE]** Given `contacts.phone_digits` is introduced, then a migration adds the column,
  backfills every existing row from `phone`, the column is maintained on every write path (manual
  create, gateway create, inbound stitch, profile patch, importer), the workspace phone lookup uses
  an indexed query instead of scanning every contact, and a test asserts the new lookup returns the
  SAME contact the old digit-comparison scan did (including the empty-digits no-match rule).
- **AC-CTM-28 [BE]** Given `PATCH /omnichannel/contacts/{id}` (the A1 route) receives a `phone` that
  collides with another contact in the same workspace, then it returns 422 on `phone` and writes
  nothing; the Contacts module UI never exposes phone editing.
- **AC-CTM-29 [BE]** Given `POST /omnichannel/workspaces/{workspaceId}/contacts/bulk/assign`
  `{ids, assigneeUserId|null}` with `contacts.manage`, then each id is resolved tenant + workspace
  scoped and assigned through the existing service path, and the response is
  `{ok: [id], failed: [{id, error}]}`; an id that does not exist, belongs to another tenant, or
  belongs to another workspace is reported with the SAME uniform `not_found` reason (no existence
  oracle).
- **AC-CTM-30 [BE]** Given `.../bulk/tags` `{ids, mode: add|remove, tagIds}`, then the tag ids are
  validated once up-front against that workspace (422 for any foreign id, nothing written) and each
  record's tag set is recomputed and replaced through `ContactProfileService`, yielding the same
  `{ok, failed}` shape.
- **AC-CTM-31 [BE]** Given `.../bulk/lifecycle` `{ids, toStatusId}`, then every move runs through
  `lifecycle_service.move` (edge graph, edge-role auth, transition notifications, the generic
  `entity.status_changed` emission); a record whose current stage has no edge to the target is
  reported in `failed` with the machine's message while the rest still move.
- **AC-CTM-32 [BE]** Given any bulk route, then `ids` is capped at 500 (422 above), the work commits
  in bounded batches so a later failure never discards earlier successes, and each route is gated
  `contacts.manage` and tenant-scoped (tenant B ids are simply never resolved).
- **AC-CTM-33 [BE]** Given a create or a bulk mutation, then each mutated contact publishes the same
  `contact.updated` realtime + consumer-webhook fan-out the single PATCH publishes, through the ONE
  shared publisher (open inboxes update without a refresh).

## Slice 3 - Backend: import + export

- **AC-CTM-34 [BE]** Given the module boots, then `ImporterDef("omnichannel_contacts")` is registered
  with `module="omnichannel"`, `write_permission="contacts.import"` and
  `context_keys=("workspaceId",)`, and a tenant without the module active gets a uniform 404 from
  every import route for that entity type.
- **AC-CTM-35 [BE]** Given the importer, then its columns are: `id` (match key), `phone` (required,
  create-only), `firstName`, `lastName`, `email`, `language`, `countryCode`, `priority`, `lifecycle`
  (stage key or label of that workspace), `tags` (multi-value, delimited, find-or-create within the
  workspace tag cap), plus one column per registered custom field keyed `cf_<fieldKey>` and typed
  from the registry.
- **AC-CTM-36 [BE]** Given Test (phase 1), then it writes NOTHING and reports per-row errors for: a
  value that fails its registry type, an unknown lifecycle stage for that workspace, a phone
  duplicated within the file, a phone already present in the contacts TABLE for that workspace, an
  `id` absent in update-only mode, an `id` present in create-only mode, and a missing required
  `phone` on create.
- **AC-CTM-37 [BE]** Given Import (phase 2), then the whole valid set commits in ONE transaction
  (all-or-nothing), created contacts get the workspace initial lifecycle stage unless the row carries
  a `lifecycle` value, a row's `phone` is never changed on update, and `trigger_automations` off
  emits no workflow events while on emits the per-row `created` / `updated` events with a change
  diff.
- **AC-CTM-38 [BE] [T]** Given a drift-guard test, then every importer column's attribute is within
  the `omnichannel_contact` workflow `writable` whitelist plus the documented import-only identity /
  relation columns (`id`, `phone`, `lifecycle`, `tags`, `cf_*`), and the test names why each
  exception is allowed.
- **AC-CTM-39 [BE]** Given `POST /omnichannel/workspaces/{workspaceId}/contacts/export`
  `{columns, ids?, search?, filter?, segment?, sortBy?, sortDir?}` with `contacts.export`, then a
  `background_jobs` row of type `omnichannel.contacts_export` is created and enqueued via
  `register_job_handler`, the handler streams matching rows in bounded batches, writes ONE CSV
  through the tenant's active storage connection, and records `{fileKey, rowCount}` in
  `result_json`.
- **AC-CTM-40 [BE]** Given a running export job, then the handler re-reads its own status from the
  DB at every batch checkpoint and stops before the terminal step when the job was aborted, and the
  job's progress counters advance per batch.
- **AC-CTM-41 [BE]** Given `GET /omnichannel/workspaces/{workspaceId}/contacts/export/{jobId}/file`,
  then it serves the CSV only for a job of this type belonging to the caller's tenant and workspace
  (uniform 404 otherwise), requires `contacts.export`, sets a `Content-Disposition` attachment
  filename, and is never immutable-cached.
- **AC-CTM-42 [BE]** Given the export, then it honours the EXACT query it was given (search + filter
  + segment + sort, or an explicit `ids` selection) and the requested column set with `id` first, so
  export then edit then re-import (update mode) round-trips the same records.
- **AC-CTM-43 [BE]** Given permissions, then the module CSV adds `segments.manage`,
  `contacts.import` and `contacts.export` (no core collision - verified against
  `app/permissions/permissions.csv` and every module CSV), the manifest version is bumped, and
  `update_tenant` runs so an EXISTING tenant's Admin role receives the new keys without a re-provision.

## Slice 4 - Wire, tests and evidence

- **AC-CTM-44 [FE]** Given the slice is complete, then every Contacts-module service call goes
  through the real backend (`*-service.real.ts`) at the service boundary and no `PHASE 1 MOCK`
  implementation is reachable from the shipped route.
- **AC-CTM-45 [BE] [T]** Given this slice touches no `/api/v1/omnichannel` shape, then
  `modules/omnichannel/routers/api_v1.py` and the `Rio*` schemas are unchanged and the gateway
  contract-drift tests stay green; if a change becomes necessary, the same commit updates
  `documentation/omnichannel/consumer-integration-guide.md`.
- **AC-CTM-46 [T]** pytest covers: list + search + sort + filter matrix (system, tags, lifecycle,
  assignee, `customFields.<key>`, unknown-field 422, depth 422), segment CRUD + apply + cross-tenant
  404, batched-query counts, create + phone normalization + duplicate 422 + stitch equivalence +
  `phone_digits` backfill, the three bulk routes (happy path, partial failure, id cap, uniform
  not-found, permission 403, tenant isolation), importer Test/Import matrix + drift guard, export job
  (query fidelity, cancellation, tenant-scoped download, storage key), and a 403 case per new route
  for a user missing each new key.
- **AC-CTM-47 [T]** vitest covers: the list config (columns, viewKey, segments, importer wiring),
  the segment save dialog schema, the create-contact schema (phone required, typed custom-field
  inputs, 422 `fieldErrors` mapping), the bulk dialogs (only valid options, failure summary), and the
  export wait-then-Jobs fallback.
- **AC-CTM-48 [E2E]** Recorded agent-browser run (dedicated timestamped tenant + workspace, real
  clicks from `/`, evidence at 375 px AND 1280 px under
  `documentation/plans/sprint-4/26-evidence/<slice>/` with a README run log): sidebar Contacts ->
  list renders -> create a contact (phone, name, email, a custom field, a tag, lifecycle) -> it
  appears in the list with the right lifecycle badge and tag chip -> filter by that tag -> save the
  filter as a segment -> switch to the segment -> select two rows -> bulk Move lifecycle -> the rows
  update -> open the contact -> Conversation tab shows the thread -> back to the list keeps the
  segment.
- **AC-CTM-49 [E2E]** Same run: Import a CSV of two contacts through the wizard (upload, map, Test
  shows zero errors, Import commits) and the rows appear in the list; then Export the current query
  and the downloaded CSV contains those rows with `id` first.
- **AC-CTM-50 [E2E]** Same run: tenant isolation and gating - a second tenant's token gets 404 on
  tenant A's contacts / segments / export-file routes, a user without `contacts.manage` sees the
  list but no Add / bulk / Edit controls, and a tenant without the omnichannel module has no
  Contacts menu entry on any menu surface.
