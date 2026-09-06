# 26 - Omnichannel Contacts module (list, segments, form, bulk, CSV import/export)

> **Contract:** `26-omnichannel-contacts-module-acceptance-criteria.md` (50 ACs). This plan fulfils it.
> **Program:** slice **A2** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gaps G4 + G5).
> **Depends on:** plan 25 / A1 merged to `main` (typed contact fields, tags, lifecycle on the scoped
> status engine, `ContactProfileService`, `lifecycle_service`, the `ThreadItem` shape).
> **Branch:** `sprint-4/26-contacts-module`, worktree `.claude/worktrees/s26` off `main` after the A1
> merge. Lane ports: backend `:8005` on DB `foundryx_service_s26`, frontend `:3004`,
> `agent-browser --session s26`. Each worktree gets its OWN `npm ci` (never a shared `node_modules`).
> **Coordinates with:** plan 23 (design-language alignment) - this slice adds new routes and reuses
> the existing shell, so the merge surface is the menu arrays plus the two omnichannel service files.

## 1. Why

respond.io's Contacts area is where an operator lives when they are not in the Inbox: one table of
every contact with lifecycle, tags, assignee and channel; saved **segments** down the left rail; add
and edit; bulk assign / tag / lifecycle; CSV import and async export. A1 gave the contact its data
model but no surface of its own - the only way to see a contact today is to open its thread in the
Inbox. A2 turns the A1 data model into a working module and, just as importantly, produces the two
seams the rest of Phase A needs: a **whitelisted contact column map** (A3 inbox filters, A4 broadcast
audiences, A9 report grouping) and a **stored segment** object (A3 custom inbox views, A4 broadcast
audience picker).

## 2. Architecture

```
app_omnichannel.workspaces --1:N--> contact_segments      (name + FilterGroup tree, per workspace)
contacts                    + phone_digits  (normalized, indexed; stitch + uniqueness key)
contact_channel_identities  -> ContactListItem.channels[]
core public.background_jobs  type = "omnichannel.contacts_export"  (CSV -> active storage connection)
core import engine           ImporterDef("omnichannel_contacts")   (two-phase, workspace context)
```

Every read path goes through ONE list service that composes: tenant + workspace scope ->
`translate_filter` over the whitelisted column map (segment tree ANDed with the ad-hoc filter) ->
whitelisted sort -> page -> the existing `ConversationService._thread_items` mapper. Every write path
goes through the A1 seams (`ContactProfileService.patch`, `lifecycle_service.move`,
`ConversationService.patch_thread`) - this slice adds no second way to mutate a contact.

### 2.1 Backend pieces

| Piece | Where | Notes |
|---|---|---|
| Model + migration | `service_backend/modules/omnichannel/models.py`, `modules/omnichannel/alembic/versions/0009_omni_contacts_module.py` | `ContactSegment` (`id, tenant_id, workspace_id, name, description, filter_json JSON(none_as_null=True), created_by_user_id, created_at, updated_at`); `Contact.phone_digits` (String, index) + backfill; idempotent inspector guards like `0008`, plus the `ADD COLUMN IF NOT EXISTS` mirror in `bootstrap.create_schema_and_tables` |
| Column map | `modules/omnichannel/services/contact_filters.py` (new) | `CONTACT_FILTER_COLUMNS`, `CONTACT_SORT_COLUMNS`, `contact_filter_special(...)` (tags / lifecycle / assignee / channelType / `customFields.<key>`), `validate_filter_tree(db, tenant, workspace, tree)` - the ONE place A3/A4 will import |
| List repo | `modules/omnichannel/repositories/contact_repository.py` | new `list_contacts(...)` (Resource-shell shaped) beside the untouched `list_threads`; `find_by_phone_digits(...)` replaces the O(n) scan inside `find_by_phone_in_workspace` |
| List service | `modules/omnichannel/services/contact_list_service.py` (new) | compose scope + segment + filter + sort + page, then map through `ConversationService._thread_items` and decorate `channels[]` (one batched identity query) |
| Segments | `modules/omnichannel/services/contact_segment_service.py` (new) | CRUD, name uniqueness (ci), cap 100, save-time `validate_filter_tree`, `tree_for(db, tenant, workspace, segment_id)` |
| Create + bulk | `modules/omnichannel/services/contact_admin_service.py` (new) | `create(...)` (normalize phone -> `phone_digits`, uniqueness, initial lifecycle stage, `ContactProfileService`, `emit_entity_event(... "created")`), `bulk_assign/bulk_tags/bulk_lifecycle` -> bounded batches over the A1 services, `{ok, failed}` |
| Import | `modules/omnichannel/importers.py` (new), registered from `bootstrap.register_engine_entities` | `ImporterDef("omnichannel_contacts")` with set-based `create_rows` / `update_rows` / `existing_ids`, `validate_row`, `validate_prepared` (phone-in-table uniqueness), `context_keys=("workspaceId",)` |
| Export | `modules/omnichannel/services/contact_export_service.py` (new) | `JobHandlerDef(type="omnichannel.contacts_export", ...)` via `app/jobs/registry.py register_job_handler`; batched row stream -> CSV -> `storage_for_tenant(db, tenant).save(...)`; `result_json = {fileKey, rowCount, columns}`; status re-read per batch (cooperative abort) |
| Routers | `modules/omnichannel/routers/contacts.py` (new, manifest prefix `/omnichannel/workspaces`), `routers/contact_segments.py` (new, same prefix) | HTTP + Pydantic only; reads `require_permission("contacts.read")`, writes `contacts.manage`, segments `segments.manage`, import `contacts.import`, export `contacts.export` |
| Schemas | `modules/omnichannel/schemas.py` | `ContactListItem(ThreadItem)` += `channels: [ContactChannelRef]`; `ContactCreate`, `BulkAssignRequest`, `BulkTagsRequest`, `BulkLifecycleRequest`, `BulkResult`, `ContactSegmentItem/Create/Update`, `ContactExportRequest`. Datetime-bearing schemas inherit `ApiModel` |
| Permissions | `modules/omnichannel/permissions/permissions.csv` | += `segments.manage`, `contacts.import`, `contacts.export` (`contacts.read` / `contacts.manage` already exist from A1) |
| Manifest + hooks | `modules/omnichannel/manifest.json`, `modules/omnichannel/bootstrap.py` | version `0.2.0 -> 0.3.0`; the two new routers declared; `update_tenant` handles `0.2.0 -> 0.3.0` (no data backfill beyond the migration; `AppStoreService.update()` re-grants the three new keys to the tenant Admin) |

Reused unchanged: `services/contact_profile_service.py`, `services/contact_field_service.py`,
`services/contact_tag_service.py`, `services/lifecycle_service.py`,
`services/conversation_service.py` (`_thread_items`, `patch_thread`, `_publish_contact_updated`),
`app/services/filter_translator.py`, `app/import_engine/*`, `app/jobs/*`, `app/services/storage.py`.

### 2.2 Frontend pieces

| Piece | Where |
|---|---|
| Route | `service_frontend/app/(protected)/omnichannel/contacts/page.tsx` (list), `contacts/[id]/page.tsx` (detail), `contacts/new/page.tsx` (create) |
| List config | `app/(protected)/omnichannel/contacts/components/use-contacts-list-config.tsx` - a clone of `app/(protected)/user-management/users/components/use-users-list-config.tsx` |
| Cells | `components/contact-lifecycle-cell.tsx`, `contact-tags-cell.tsx` (wraps `components/platform/overflow-pills`), `contact-channels-cell.tsx` |
| Actions | `components/use-contact-actions.tsx` (row + bulk registry: Assign, Add tags, Remove tags, Move lifecycle, Delete is NOT in this slice) + `bulk-assign-dialog.tsx`, `bulk-tags-dialog.tsx`, `bulk-lifecycle-dialog.tsx` |
| Segments | `components/segment-picker.ts` (feeds `ResourceListConfig.segments`), `save-segment-dialog.tsx`, `manage-segments-dialog.tsx`, `segment-schema.ts` |
| Form | `components/use-contact-form.tsx` (`ResourceFormConfig`: tabs Details + Conversation), `contact-form-fields.tsx`, `contact-schema.ts`; Details reuses `components/platform/conversation-drawer/{contact-details-form,lifecycle-move,tag-chips}.tsx`; Conversation mounts `<ConversationDrawer contactId compact />` |
| Services | `services/contact-service.{ts,mock,real}.ts` (list, get, create, bulk, export), `services/contact-segment-service.{ts,mock,real}.ts` |
| Hooks | `hooks/use-contacts.ts`, `hooks/use-contact-segments.ts`, `hooks/use-contact-bulk.ts` |
| Types | `types/omnichannel.ts` += `ContactListItem`, `ContactChannelRef`, `ContactSegment`, `CreateContactInput`, `BulkResult` |
| Menu | `config/menu.config.tsx` - a Contacts entry after Inbox in `MENU_SIDEBAR`, `MENU_MEGA`, `MENU_MEGA_MOBILE` |

Reused unchanged: `components/platform/resource-list`, `resource-form`, `resource-actions`,
`search-select`, `multi-select`, `overflow-pills`, `status-badge`, `import-wizard`, `jobs-drawer`,
`services/import-service.*`, `services/jobs-service.*`, `hooks/use-can.ts`, `hooks/use-datetime.ts`.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D-A2-1 | Route `/omnichannel/contacts`, menu entry "Contacts" next to Inbox, gated `module: omnichannel` + `contacts.read` in all three menu arrays. Contact = the A1 `contacts` row | Roadmap D10; no new entity, no second identity to reconcile with the thread |
| D-A2-2 | List = Resource shell cloned from Users; columns Name, Phone, Email, Lifecycle, Tags, Assignee, Channel, Last message, Created; server search / sort / filter / paginate | House mandate: never hand-roll a table; Users is the reference clone |
| D-A2-2a | Row click opens a contact DETAIL PAGE (`/omnichannel/contacts/{id}`) on the Resource form, tabs Details + Conversation; the Conversation tab mounts the existing `<ConversationDrawer>` | The drawer is already self-contained (`contactId` + `compact` props) and the A1 panel components are already built and unit-tested; a detail page also buys record-nav and the dirty-guard for free |
| D-A2-3 | A **segment stores a `FilterGroup`** (the exact shape the Resource shell's filter builder emits), validated at save by a dry-run `translate_filter` against the whitelisted column map, and applied in SQL | **Deviation from the brief, flagged.** The brief said "rule tree + `validate_tree`", but the rule engine (`evaluate` / `validate_tree`) is the IN-MEMORY family keyed on fact sources, while the same decision requires SQL evaluation ("never Python-side filtering"). Storing the shell's own filter shape gives: the existing Filters UI as the segment editor ("save current filters as a segment", exactly respond.io's flow), one translator, no fact-key-to-column mapping layer, and a shape A3 (custom inbox views) and A4 (broadcast audiences) can consume directly. In-memory membership ("is contact X in segment S?") stays available as a one-row `WHERE id = X AND <clause>` |
| D-A2-4 | Create form = Resource form; phone required + create-only; manual create sets the initial lifecycle stage via `lifecycle_service.initial_status_id` and emits the `omnichannel_contact` `created` event through `ContactProfileService` | Matches A1's write seam; the wizardless single form keeps the surface foolproof |
| D-A2-5 | Bulk actions iterate the A1 services per record in bounded batches with a per-record result `{ok, failed:[{id, error}]}`, capped at 500 ids; never a raw `UPDATE` | Lifecycle moves must go through the machine (edges, roles, notifications, `status_changed`); tag / assignee writes must go through the validating profile seam. Uniform `not_found` for missing / foreign / other-workspace ids so the response is not an existence oracle |
| D-A2-6 | CSV import via `ImporterDef("omnichannel_contacts")` on the core import engine, workspace passed as import `context` | Two-phase Test then Import, all-or-nothing, `id`-only matching and the whole wizard UI already exist |
| D-A2-6a | Export = a `background_jobs` job (`omnichannel.contacts_export`) that writes ONE CSV to the active storage connection; the frontend `exporter` creates the job, polls `GET /jobs/{id}` briefly, then downloads the file through an AUTHED streaming route; if the job has not finished inside the wait window the user is pointed at Jobs | Keeps the shell's `exporter(query, columns, ids) => Promise<string>` contract with ONE code path (eager mode in dev finishes inline), and reuses `background_jobs` + the Jobs drawer / `/jobs/{id}` page |
| D-A2-6b | The export file is served by an **authed** route (`imports.errors-file` precedent) rather than a signed capability URL | **Deviation from the brief, flagged.** The omnichannel signed-URL helper (`security.py signed_media_url`) binds a single MESSAGE id and exists so a chat image opens on a raw browser click. A bearer-less, replayable link to a CSV of an entire contact database (names, phones, emails, custom fields) is a different risk class. `apiFetchBlob` already carries the Bearer for in-UI downloads |
| D-A2-7 | Permissions: reuse `contacts.read` / `contacts.manage`; add `segments.manage`, `contacts.import`, `contacts.export`. Grant path for existing tenants = manifest bump to `0.3.0` + `update_tenant` (A1 pattern) | Collision grep 2026-09-06: core owns `reports.*` (not used here); `segments`, `contacts.import`, `contacts.export` are unclaimed in `app/permissions/permissions.csv`, `platform_permissions.csv` and every module CSV. Implied-read normalization forces `contacts.read` alongside the new action keys |
| D-A2-8 | "Customize View" column chooser = the Resource shell's existing Columns button + per-user prefs by `viewKey` (`omnichannel.contacts.list`) - IN SCOPE, no new code | Verified present in `components/platform/resource-list/resource-list.tsx` (`useViewPreferences`, Columns menu, column drag) |
| D-A2-9 | `contacts.phone_digits`: a normalized, indexed column maintained on every write path, with a backfill migration; NO unique DB index | Phone uniqueness per workspace is required by the create form AND by the importer's "unique checked against the TABLE at Test", and today the only comparison is an O(n) Python scan over every contact in the workspace (`find_by_phone_in_workspace`). A UNIQUE index would fail the migration on any tenant that already has duplicates, so uniqueness is service-enforced and a dedupe + index is a backlog item |
| D-A2-10 | Workspace scope resolves exactly like the Inbox (default workspace first); a workspace `SearchSelect` renders in the page header only when the tenant has more than one workspace | Mirrors `app/(protected)/omnichannel/inbox/page.tsx`; the segment control is already occupied, so the workspace picker is a header control, not a segment |
| D-A2-11 | `ContactListItem` is a SUBCLASS of `ThreadItem` adding `channels[]`; `/api/v1` shapes and the `Rio*` mappers are untouched | Keeps the consumer-guide contract frozen for this slice. The Channel column must come from `contact_channel_identities`, not from the last message's channel (a manually created contact has no message and would otherwise render a fabricated WHATSAPP) |
| D-A2-12 | The list endpoint is NEW and workspace-scoped (`GET /omnichannel/workspaces/{id}/contacts`); the inbox thread list (`GET /omnichannel/contacts`) is untouched | The two have different search semantics (the inbox searches message bodies) and different query vocabularies; overloading one endpoint would make both worse |
| D-A2-13 | The IMPORTER sets a lifecycle stage directly (a bulk data load, like `migrate_records`); the BULK ACTION moves through `lifecycle_service.move` | **Flagged.** A created row has no prior stage for the machine to transition from, and a set-based import cannot run N transitions without losing its set-based property. Direct assignment therefore emits no transition notification and no `status_changed` run for imported rows; the interactive bulk path keeps full machine semantics |
| D-A2-14 | The export blob key lives in `background_jobs.result_json.fileKey`, not in a new `*_key` column | No new table, and the storage-migration drift test (which reflects `*_key` COLUMNS) stays meaningful. Export CSVs are short-lived artefacts, explicitly NOT part of a bucket migration; blob GC is a backlog item |
| D-A2-16 | The menu edit also fixes the pre-existing `MENU_MEGA` gap (Omnichannel block untagged: no `module`, no per-child `permission`) and adds the missing Omnichannel block to `MENU_MEGA_MOBILE` | Verified 2026-09-06: `filterMenu` only prunes what is tagged, so the header mega menu currently exposes omnichannel paths to tenants without the module, and the mobile mega menu shows no omnichannel entries at all. Tagging Contacts in only one array would repeat exactly the leak the house rule exists to prevent |
| D-A2-15 | Delete / merge / block a contact is NOT in this slice | Roadmap puts merge + block in B2; a destructive contact delete needs its own decision (thread history) |
| D-A2-17 | The contact detail form has NO outer global Edit toggle; the reused A1 contact panel's per-section edit affordances (Details/lifecycle/tags, each already gated `contacts.manage`) are the only way to edit | Review round 1, 2026-09-06. **Deviation from the house Resource-form invariant, flagged and ACCEPTED.** A second outer toggle over fields the panel ALREADY edits inline would be a redundant, confusing second way to enter edit mode on the SAME fields - the opposite of foolproof-UI. Amends AC-CTM-07/13 |
| D-A2-18 | Segment delete rides the CORE deferred (grace-window) engine (`contact_segments.delete`, `deferred_actions.py`) instead of a confirm `AlertDialog` | Review round 1, 2026-09-06. The hand-rolled `AlertDialog` in `manage-segments-dialog.tsx` was a design-language hard-fail (every other destructive action in this module already rides the deferred engine - channels, webhooks, quick replies, API keys). Amends AC-CTM-06 |

## 4. Slices (build order)

Each slice is sized for ONE Sonnet coder in the `s26` lane, sequential on the same branch.

| Slice | Content | Rough size | Executor |
|---|---|---|---|
| **S0 FE mock** | types, `contact-service` + `contact-segment-service` trios (mock), menu entries in all three arrays, list route + config (columns, search, filters, segments, Columns), detail route (Details + Conversation tabs), create route, bulk dialogs, segment dialogs, export/import buttons; agent-browser smoke at 375 + 1280. ACs 01-13 | L | coder (Sonnet) |
| **S1 BE list + segments** | migration `0009` (ContactSegment + `phone_digits` + backfill), `contact_filters.py` column map + `validate_filter_tree`, `list_contacts` repo, `contact_list_service`, `contact_segment_service`, routers `contacts.py` (GET) + `contact_segments.py`, `ContactListItem`, permissions CSV + manifest bump, pytest. ACs 14-23, 43 (partial) | L | coder (Sonnet) TDD |
| **S2 BE create + bulk** | `contact_admin_service` (create + 3 bulk routes), phone normalization + uniqueness + stitch equivalence, `phone_digits` maintained on every write path, `_publish_contact_updated` fan-out on create/bulk, pytest. ACs 24-33 | M | coder (Sonnet) TDD |
| **S3 BE import + export** | `importers.py` (`ImporterDef` + set-based hooks + drift-guard test), `contact_export_service` (job handler + CSV writer + cooperative abort), export routes, pytest. ACs 34-43 | L | coder (Sonnet) TDD |
| **S4 Wire + E2E** | swap mocks for real at the service boundary, export poll-then-Jobs fallback, vitest, recorded agent-browser evidence run, Test Execution Report keyed to the AC ids. ACs 44-50 | M | coder + tester (Sonnet) |
| **Review** | `reviewer` agent on **Opus** (tenant isolation on five new route families, the filter whitelist as an injection boundary, the export blob as a PII egress path), then `/codex-review` | reviewer |

S1 must land before S2 (the create path needs `phone_digits` and the list shape) and before S3 (the
export reuses the list query builder).

## 5. Contracts

### 5.1 Internal API (all camelCase, datetimes Z-suffixed via `ApiModel`)

```
GET    /omnichannel/workspaces/{wsId}/contacts
         ?page=&pageSize=&search=&sortBy=&sortDir=&filter=<json FilterGroup>&segment=<segmentId>
         -> { data: ContactListItem[], total, page }
POST   /omnichannel/workspaces/{wsId}/contacts
         { firstName?, lastName?, phone, email?, language?, countryCode?,
           lifecycleStatusId?, tagIds?: [id], customFields?: {key: value} }   -> 201 ContactListItem
POST   /omnichannel/workspaces/{wsId}/contacts/bulk/assign     { ids[], assigneeUserId|null } -> BulkResult
POST   /omnichannel/workspaces/{wsId}/contacts/bulk/tags       { ids[], mode: "add"|"remove", tagIds[] } -> BulkResult
POST   /omnichannel/workspaces/{wsId}/contacts/bulk/lifecycle  { ids[], toStatusId } -> BulkResult
POST   /omnichannel/workspaces/{wsId}/contacts/export
         { columns[], ids?, search?, filter?, segment?, sortBy?, sortDir? }   -> { jobId }
GET    /omnichannel/workspaces/{wsId}/contacts/export/{jobId}/file            -> text/csv attachment

GET    /omnichannel/workspaces/{wsId}/contact-segments            -> ContactSegmentItem[]
POST   /omnichannel/workspaces/{wsId}/contact-segments            { name, description?, filter } -> 201
PATCH  /omnichannel/workspaces/{wsId}/contact-segments/{id}       { name?, description?, filter? }
DELETE /omnichannel/workspaces/{wsId}/contact-segments/{id}       -> 204

(unchanged, reused) GET/PATCH /omnichannel/contacts/{id}, POST /omnichannel/contacts/{id}/lifecycle,
GET /omnichannel/contacts/{id}/lifecycle-moves, GET /omnichannel/workspaces/{wsId}/contact-fields,
GET /omnichannel/workspaces/{wsId}/contact-tags, GET /jobs/{jobId}
```

Wire shapes:

```
ContactListItem = ThreadItem (plan 25) + {
  channels: [{ channelId, channelType, name }]     // from contact_channel_identities, [] when none
}
ContactSegmentItem = { id, workspaceId, name, description, filter: FilterGroup,
                       createdAt, updatedAt }
BulkResult         = { ok: [contactId], failed: [{ id, error }] }
```

422 bodies keep the house shape `{fieldErrors: {path: message}}` with paths `phone`,
`customFields.<key>`, `tagIds`, `language`, `countryCode`, `filter`, `name`.

### 5.2 Filter + sort column map (`contact_filters.py`)

| Filter field | Type | Resolution |
|---|---|---|
| `name` | text | `coalesce(first_name,'') || ' ' || coalesce(last_name,'')` |
| `firstName`, `lastName`, `email`, `language`, `countryCode`, `priority` | text / enum | plain columns |
| `phone` | text | matched against `phone_digits` with the input reduced to digits |
| `assignee` | enum | special: `assigned_user_id` in ids, or the sentinel `unassigned` (both assignee columns NULL) |
| `channelType` | enum | special: `EXISTS` over `contact_channel_identities` joined to `channels` |
| `lifecycle` | enum | special: `lifecycle_status_id` in the ids of the workspace's stages resolved by key (never by label) |
| `tags` | enum (multi) | special: `EXISTS` over `contact_tag_links` for tag ids of THIS workspace |
| `lastMessageAt`, `createdAt` | date | plain columns |
| `customFields.<key>` | derived from the registry | special: `Contact.custom_fields_json[key].as_string()` (dialect-portable across Postgres and the SQLite test engine); the key must be registered for the workspace or 422 |

Sort whitelist: `name`, `phone`, `email`, `lifecycle` (by the stage's `sort_order`), `assignee`,
`lastMessageAt`, `createdAt`. Anything else is 422.

`validate_filter_tree` performs a dry-run `translate_filter` with the same map plus the workspace's
registered custom-field keys, so a segment can never store a tree the list would later reject.

### 5.3 Importer spec (`ImporterDef("omnichannel_contacts")`)

| Column key | Label | Type | Notes |
|---|---|---|---|
| `id` | ID | string | match key (universal, D5 of the import engine); absent = create |
| `phone` | Phone | string | required on create, normalized to `+<digits>`, unique per workspace checked against the TABLE at Test; NEVER written on update |
| `firstName`, `lastName`, `email` | | string | plain |
| `language` | Language | string | BCP-47 shape, same gate as `ContactProfileService` |
| `countryCode` | Country | string | ISO-3166 alpha-2, upper-cased |
| `priority` | Priority | enum | LOW / MEDIUM / HIGH / URGENT |
| `lifecycle` | Lifecycle | enum | resolver `find` over the workspace's stages by key or label; set directly (D-A2-13) |
| `tags` | Tags | string (multi-value) | delimiter `,`; resolver `find_or_create` within the workspace tag cap |
| `cf_<fieldKey>` | the field's label | from the registry | one column per registered contact field; typed exactly like `ContactFieldService.validate_values` |

`context_keys = ("workspaceId",)`; `write_permission = "contacts.import"`; `module = "omnichannel"`.
Drift-guard test: every column's attribute is inside the `omnichannel_contact` workflow `writable`
set plus the documented import-only set `{id, phone, lifecycle, tags, cf_*}`.

### 5.4 Export job

```
type    : "omnichannel.contacts_export"
payload : { workspaceId, columns[], ids?, search?, filter?, segment?, sortBy?, sortDir? }
result  : { fileKey, rowCount, columns[] }
handler : batches of 500 rows through the SAME list query builder S1 ships;
          re-reads its own status per batch (cooperative abort);
          writes one CSV via storage_for_tenant(db, tenant_id).save(...);
          progress_total set from the first count, progress_done advanced per batch.
```

The CSV always leads with `id` so export then edit then re-import (update mode) round-trips.

## 6. Risks + mitigations

- **Filter whitelist is an injection boundary.** `customFields.<key>` is the first place a client
  value reaches a JSON path. The key is matched against the workspace's registry rows before it is
  used, never interpolated raw, and the accessor is SQLAlchemy's typed JSON comparator (bound
  parameters, no string SQL).
- **`phone_digits` touches A1 write paths** (inbound stitch, gateway create, profile patch). The
  stitch is the load-bearing one: a regression test pins that the new indexed lookup returns exactly
  what the old digit-comparison scan returned, including the empty-digits no-match rule, before the
  scan is deleted.
- **Duplicate phones may already exist** in a live workspace (the stitch is best-effort and the
  gateway could create). Hence no unique index; uniqueness is enforced going forward at create and at
  import Test, and a dedupe pass is a backlog item.
- **Export is a PII egress path.** Authed streaming route, tenant + workspace + job-type checked,
  `contacts.export` gated, private cache, no signed capability URL (D-A2-6b).
- **Bulk endpoints could become an existence oracle.** Missing, cross-tenant and cross-workspace ids
  all report the same `not_found` reason.
- **Menu arrays drift.** The three arrays are separate copies and are already out of sync for
  omnichannel (D-A2-16); the mega-menu renderers resolve sections by TITLE, not index, so a new entry
  must not be positioned by index.
- **Plan 23 merge.** The only shared lines are the three menu arrays and the two omnichannel service
  files; everything else is new files under a new route.
- **Gateway contract.** This slice must not touch `routers/api_v1.py` or the `Rio*` schemas. If it
  does, the consumer guide diff ships in the same commit (AC-CTM-45).

## 7. Backlog candidates (register on close)

- Contact phone dedupe pass + a partial unique index on `(tenant_id, workspace_id, phone_digits)`.
- GC for export CSV blobs when their `background_jobs` row is pruned (today the blob outlives the row).
- Blocked-contacts view + contact delete / merge (B2).
- Segment membership counts on the segment list (currently computed only when a segment is applied).
- Import: run lifecycle changes through the status machine for UPDATE rows so imported moves fire
  notifications and `status_changed` workflows (D-A2-13 deliberately does not).
- Saved segment sharing / per-user private segments (workspace-wide only in v1).
