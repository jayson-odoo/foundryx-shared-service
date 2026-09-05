# 25 - Omnichannel contact data model (typed fields, tags, lifecycle) - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/25-omnichannel-contact-data-model.md`.
> **Program:** slice **A1** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0).
> **Grill (2026-09-05):** roadmap D1 (typed registry over the JSON blob), D2 (lifecycle on the status
> engine), D3 (conversation status stays separate); A1 grill: lifecycle edited on the **existing
> status-engine canvas** (scoped to the workspace), fields / tags / lifecycle are **per workspace**,
> the **contact side panel ships in A1**, the won stage is an **explicit flag** (`is_terminal`).
> **Out of scope (later slices):** Contacts module list + import / export (A2), inbox views + close
> notes (A3), workflow catalog entries for contact triggers / steps (A5 - A1 only emits the events),
> segments (A2), teams (A8), contact merge / block (B2).

IDs: `AC-CDM-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Definitions

- **Workspace** - the omnichannel workspace (`app_omnichannel.workspaces`). Every registry in this
  slice hangs off a workspace, never the tenant directly (tenant isolation still applies on top).
- **Contact** - the `contacts` row (contact = thread today). Gains `lifecycle_status_id`,
  `language`, `country_code`.
- **Contact field** - a registered custom field (`contact_fields` row): `key`, `label`,
  `description`, `type`, `options`, `visibility`, `sort_order`. Values live in
  `contacts.custom_fields_json[key]`.
- **System fields** - `firstName`, `lastName`, `phone`, `email`, `language`, `countryCode`,
  `tags`, `lifecycle`, `profilePic`: real columns / relations, never registry rows; their keys are
  reserved.
- **Field types** - `text`, `list` (dropdown, needs `options`), `checkbox`, `email`, `number`,
  `url`, `date` (`YYYY-MM-DD`), `time` (`HH:MM`).
- **Tag** - `contact_tags` row (`name`, `emoji`, `color`, `description`); attached to contacts via
  `contact_tag_links`.
- **Lifecycle** - the status-engine entity `omnichannel_contact_lifecycle`, **scoped** per
  workspace (`scope_id = workspace_id`). A **stage** = one `Status` row; **won** = `is_terminal`,
  **lost** = `is_archived`, **initial** = `is_initial`. Any other stage is an "active" stage.
- **Seed graph** - the default set materialized for a new workspace: 🆕 New Lead (initial, default)
  → 🔥 Hot Lead → 💵 Payment → 🤩 Customer (won); 😔 lost stage 🧊 Cold Lead. Edges: every active
  stage ↔ every other active stage, every active stage → Customer, every active stage → Cold Lead,
  Cold Lead → New Lead. Emoji is part of the label text (no schema for icons).
- **Move** - a lifecycle change executed by `status_machine.transition` (edge graph enforced).

---

## Slice 1 - Backend: contact fields registry

- **AC-CDM-01 [BE]** Given a workspace, when a user with `contact_fields.manage` creates a field
  with `key`, `label`, `type` (and `options` for `list`), then the field is stored for that
  workspace only and `GET /omnichannel/workspaces/{id}/contact-fields` lists it in `sort_order`.
- **AC-CDM-02 [BE]** Given a create payload whose `key` is a reserved system key, is not
  `^[a-z][a-zA-Z0-9_]{0,39}$`, or already exists in the workspace (case-insensitive), or whose
  `type` is not one of the eight field types, or is `list` without at least one option, then the
  API returns 422 with `{fieldErrors}` naming the offending field.
- **AC-CDM-03 [BE]** Given an existing field, when it is updated, then `label`, `description`,
  `options`, `visibility`, `sort_order` change and `key` + `type` are immutable (422 if sent
  changed).
- **AC-CDM-04 [BE]** Given an existing field with values on N contacts, when it is deleted, then
  the registry row is gone AND the key is stripped from every contact's `custom_fields_json` in that
  workspace (no orphan values), other workspaces untouched.
- **AC-CDM-05 [BE]** Given a workspace at the cap of 100 fields, when another is created, then 422.
- **AC-CDM-06 [BE]** Given a contact PATCH (internal `PATCH /omnichannel/contacts/{id}` or gateway
  `PATCH /api/v1/omnichannel/contacts/{identifier}`) carrying `customFields`, then every key must be
  a registered field of the contact's workspace and every value must validate for its type
  (`number` numeric, `checkbox` boolean, `email` / `url` well-formed, `date` `YYYY-MM-DD`, `time`
  `HH:MM`, `list` one of `options`, `text` string ≤ 2000 chars); violations return 422
  `{fieldErrors: {"customFields.<key>": "..."}}` and nothing is written. `null` clears one key;
  keys omitted are left unchanged (partial merge, NOT replace).
- **AC-CDM-07 [BE]** Given a contact PATCH carrying `language` (BCP-47 tag, ≤ 16 chars) or
  `countryCode` (ISO-3166 alpha-2, upper-cased), then the columns are written; invalid values 422.
- **AC-CDM-08 [BE]** Given a tenant B user, when they call any contact-fields route with a tenant
  A workspace id, then 404 (uniform), never 403 or data.

## Slice 2 - Backend: tags

- **AC-CDM-09 [BE]** Given a workspace, when a user with `contact_tags.manage` creates a tag with
  `name` (+ optional `emoji`, `color`, `description`), then it is listed by
  `GET /omnichannel/workspaces/{id}/contact-tags`; `name` is unique per workspace
  case-insensitively (422 on duplicate); cap 500 tags per workspace (422).
- **AC-CDM-10 [BE]** Given a contact PATCH carrying `tagIds: [...]`, then the contact's tag set is
  REPLACED by exactly those tags; any id not belonging to the contact's workspace → 422 and no
  write (polymorphic stored-id rule: validated at save, resolved tenant + workspace scoped at read).
- **AC-CDM-11 [BE]** Given a tag attached to contacts, when the tag is deleted, then its links are
  removed and the contacts remain otherwise unchanged.
- **AC-CDM-12 [BE]** Given a thread list / thread detail read, then each item carries
  `tags: [{id, name, emoji, color}]` resolved for the caller's tenant.

## Slice 3 - Backend: lifecycle on the status engine

- **AC-CDM-13 [BE]** Given the omnichannel module boots, then the status entity
  `omnichannel_contact_lifecycle` is registered (scoped, `scope_attr = "workspace_id"`,
  `scope_label = "Workspace"`, `scope_exists` = workspace exists in the caller's tenant, module
  `omnichannel`, `status_attr = "lifecycle_status_id"`, `required_flags = ["is_initial",
  "is_terminal", "is_archived"]`) and `GET /api/v1/statuses?entityType=omnichannel_contact_lifecycle&scopeId=<workspaceId>`
  returns that workspace's graph.
- **AC-CDM-14 [BE]** Given a workspace is created (service path or `install_tenant` default
  workspace), then the seed graph is materialized for it in the same transaction, and the created
  rows carry `(tenant_id, scope_id = workspace.id)`.
- **AC-CDM-15 [BE]** Given a tenant provisioned on module version 0.1.0 with workspaces and
  contacts, when `update_tenant` runs for 0.2.0, then every workspace without a lifecycle graph gets
  the seed graph and every contact with `lifecycle_status_id IS NULL` is set to its workspace's
  initial stage; re-running is a no-op.
- **AC-CDM-16 [BE]** Given a new contact is created by any path (inbound stitch, gateway create,
  manual), then `lifecycle_status_id` = the workspace's `is_initial` stage.
- **AC-CDM-17 [BE]** Given a contact and a target stage, when
  `POST /omnichannel/contacts/{id}/lifecycle {toStatusId}` is called by a user with
  `contacts.manage`, then the move goes through `status_machine.transition` (edge must exist from
  the current stage, edge-role auth applies, transition notifications fire); a missing edge → 409
  with the machine's error; a stage from another workspace or tenant → 404.
- **AC-CDM-18 [BE]** Given a contact, when `GET /omnichannel/contacts/{id}/lifecycle-moves` is
  called, then it returns the fireable outgoing edges `[{edgeId, toStatusId, label}]` for that
  contact (empty for a won stage, since `is_terminal` has no outgoing edges).
- **AC-CDM-19 [BE]** Given a thread list / detail read, then each item carries
  `lifecycle: {statusId, key, label, color, isWon, isLost} | null`.
- **AC-CDM-20 [BE]** Given a workspace lifecycle graph edited on the canvas (add stage, rename,
  add / remove edge, reorder, deactivate), then edits apply directly to the scoped rows (no platform
  fork), a stage with contacts cannot be deleted without `migrate-records` (existing engine rule),
  and exactly one `is_initial` stage is enforced.
- **AC-CDM-21 [BE]** Given a tenant is uninstalled from the module, then its
  `omnichannel_contact_lifecycle` status + transition rows in the CORE `statuses` /
  `status_transitions` tables are deleted along with the module rows.

## Slice 4 - Backend: workflow-engine seam + gateway contract

- **AC-CDM-22 [BE]** Given the module boots, then the workflow entity `omnichannel_contact`
  (model `Contact`, `has_status = True`, `status_attr = "lifecycle_status_id"`,
  `fact_attrs` = first / last name, phone, email, language, country code, priority, assignee,
  csw / last-message timestamps; `writable` = `firstName`, `lastName`, `email`, `language`,
  `countryCode`, `priority`) is registered and `record:omnichannel_contact` facts resolve.
- **AC-CDM-23 [BE]** Given a contact PATCH changes system fields, custom fields or tags, then ONE
  `omnichannel_contact` `updated` entity event is emitted after commit with `changes` keyed
  `firstName` / `customFields.<key>` / `tags` (`{from, to}`), and the triggering request never fails
  because of workflow dispatch.
- **AC-CDM-24 [BE]** Given a published workflow with trigger `entity.status_changed` on entity
  `omnichannel_contact`, when a contact's lifecycle is moved, then a run is created with
  `trigger.record.*` + from / to status in the context (the machine's generic emission).
- **AC-CDM-25 [BE]** Given the default gateway shape (`GET /api/v1/omnichannel/contacts*`, thread
  reads, webhook `contact` objects), then it carries `language`, `countryCode`, `customFields`
  (registered keys only), `tags: [{id, name, emoji, color}]`, `lifecycle: {...}`; `?format=rio`
  carries `language`, `countryCode`, `custom_fields: [{name: <key>, value}]`, `tags: [<name>]`,
  `lifecycle: <stage label>`. Both are derived from the same internal `ThreadItem`.
- **AC-CDM-26 [BE]** Given gateway `PATCH /api/v1/omnichannel/contacts/{identifier}`, then it
  accepts `language`, `countryCode`, `customFields` (AC-06 rules), `tags: [<name>]` (replaces the
  set; unknown names are auto-created in the workspace, respond.io parity), `lifecycle: <stage key
  or label>` (a move via the machine; no edge → 409 `lifecycle_move_not_allowed`).
- **AC-CDM-27 [BE] [T]** Given `documentation/omnichannel/consumer-integration-guide.md`, then the
  same commit updates §Contacts (shape + PATCH) and the contract-drift tests in
  `tests/test_omnichannel_api_gateway.py` pin the new fields (default AND rio).
- **AC-CDM-28 [BE]** Given permissions, then the module CSV adds `contacts.read`,
  `contacts.manage`, `contact_fields.manage`, `contact_tags.manage` (no core collision - verified
  2026-09-05), tenant Admin receives them on install / update, and: reading registries requires
  `conversations.read` OR `contacts.read`; writing a contact's fields / tags / lifecycle requires
  `contacts.manage`; editing the lifecycle canvas keeps the core `statuses.manage` gate.

## Slice 5 - Frontend: workspace settings tabs (mock first, then real)

- **AC-CDM-29 [FE]** Given the workspace form (`/omnichannel/settings/workspaces/{id}`), then it
  shows three new tabs after Members: **Lifecycle**, **Contact fields**, **Tags** (hidden while
  creating a workspace).
- **AC-CDM-30 [FE]** Given the Lifecycle tab, then it renders the existing `EntityFlow` canvas for
  `omnichannel_contact_lifecycle` scoped to the workspace, read-only until the form's global Edit
  toggle is on (same pattern as the form Flow tab), dirty-guarded by the shell.
- **AC-CDM-31 [FE]** Given the Contact fields tab, then it is an embedded `ResourceList`
  (columns Name, Field ID, Description, Type, Visibility, Date added; row actions Edit / Delete;
  "Add custom field" opens a dialog with Name, Field ID (auto-slugged from Name, editable until
  save), Description, Type `SearchSelect`, Options editor when type = list, Visibility); 422
  `fieldErrors` map onto the dialog fields; Delete asks for confirmation naming the count of
  contacts holding a value.
- **AC-CDM-32 [FE]** Given the Tags tab, then it is an embedded `ResourceList` (Emoji + Name,
  Colour swatch, Description, Contacts count, Date added; Create / Edit dialog; Delete with
  confirmation naming the attached-contacts count).
- **AC-CDM-33 [FE]** Given a user without `contact_fields.manage` / `contact_tags.manage`, then
  the tabs render read-only (no Add / Edit / Delete controls) - `useCan()` is UX only, the API is
  the gate.

## Slice 6 - Frontend: contact side panel in the conversation drawer

- **AC-CDM-34 [FE]** Given the inbox drawer at ≥ 1280 px, then a **Contact** panel is available
  as a right pane (toggle button in the drawer header, open state remembered in `localStorage`);
  below 1280 px the same content opens as a Sheet from the same button. Hidden in compact / embed
  modes.
- **AC-CDM-35 [FE]** Given the panel, then it shows: **Details** (first / last name, phone, email,
  language, country + every registered custom field whose visibility is `always`, in `sort_order`,
  typed inputs per field type), **Lifecycle** (current stage badge with emoji label + a "Move to"
  `SearchSelect` listing only the fireable moves), **Tags** (chips with emoji + colour, remove ×,
  "Add tag" `SearchSelect` over the workspace tags).
- **AC-CDM-36 [FE]** Given Details, then an Edit toggle switches inputs on; Save sends ONE
  PATCH with only changed keys (system fields + `customFields` partial merge), 422 `fieldErrors`
  map to the inputs; Cancel restores; the drawer's own dirty-guard covers unsaved edits.
- **AC-CDM-37 [FE]** Given a lifecycle move from the panel, then the stage badge, the thread list
  row and any open Contact panel update via the existing WS thread-updated push (no manual
  refresh); a 409 from the machine shows the error toast with the machine message.
- **AC-CDM-38 [FE]** Given tag add / remove, then the chips update optimistically and reconcile
  with the PATCH response; errors revert.
- **AC-CDM-39 [FE]** Given the thread list rows, then each shows the lifecycle emoji + label as a
  small badge and up to two tag chips (+N) - the data is already in `ThreadItem`, no extra call.

## Slice 7 - Tests + evidence

- **AC-CDM-40 [T]** pytest covers: field CRUD + validation matrix (every type, reserved keys,
  immutability, delete strips values), tag CRUD + link replace + cross-workspace id rejection,
  seed materialization on create + `install_tenant`, `update_tenant` backfill idempotency, new
  contact gets the initial stage, transition happy path + no-edge 409 + cross-tenant 404,
  fireable moves, uninstall cleans core status rows, entity event emission (updated +
  status_changed) with the change diff, published `entity.status_changed` workflow runs on a move,
  gateway default + rio shapes, gateway PATCH tags-by-name auto-create + lifecycle move, permission
  gates (403 for each write key), tenant isolation on every new route.
- **AC-CDM-41 [T]** vitest covers: field dialog schema (slug derivation, list needs options),
  contact panel typed inputs + fieldErrors mapping, lifecycle move select shows only fireable
  moves, tag chips optimistic add / remove, workspace tabs gated by permission.
- **AC-CDM-42 [E2E]** Recorded agent-browser run (dedicated timestamped tenant / workspace, real
  clicks from `/`, 375 + 1280 evidence under
  `documentation/plans/sprint-4/25-evidence/<slice>/`): Settings → Workspaces → open workspace →
  Lifecycle tab shows the seed graph → Edit → add stage "Nurture" + edge from New Lead → Save →
  Contact fields tab → add `list` field "Source" with options → Tags tab → create tag "VIP" →
  Inbox → open demo thread → Contact panel → set Source, add VIP, move New Lead → Hot Lead → thread
  row shows the new stage + tag → reload keeps everything.
- **AC-CDM-43 [E2E]** Same run: a second tenant cannot see tenant A's fields / tags / stages
  (API probe with tenant B's token returns 404 / empty), and the omnichannel-inactive tenant's
  workspace form has no new tabs.
