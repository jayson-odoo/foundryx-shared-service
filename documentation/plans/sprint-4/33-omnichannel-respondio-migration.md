# 33 - Omnichannel respond.io migration tool (Developer API, CSV fallback, history + media + events)

> **Contract:** `33-omnichannel-respondio-migration-acceptance-criteria.md` (61 ACs). This plan fulfils it.
> **Program:** slice **A6** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gap G28,
> roadmap Q3 "message history migrates" and D12 "API first, CSV fallback").
> **Depends on:** plans 25 (A1), 26 (A2), 27 (A3), 28 (A8), 30 (A9), 31 (A5) and, if it lands first,
> 32 (A7a) - all merged to `main`. A6 is deliberately LAST in Phase A: it needs every other slice's
> data model to have somewhere to put respond.io's data.
> **Branch:** `sprint-4/33-respondio-migration`, worktree `.claude/worktrees/s33` cut off `main`
> AFTER the A5 / A7a merges. Lane ports: backend `:8009` on DB `foundryx_service_s33`, frontend
> `:3008`, `agent-browser --session s33`. Each worktree gets its OWN `npm ci` - never a shared
> `node_modules`.
> **Seams verified at `c25a97ff`** (origin/main, "Merge pull request #46"). File:line references in
> section 6 are pinned to that commit.

## 1. Why

The whole parity program exists to move ONE customer off respond.io. A1 to A9 rebuild the product;
A6 is the only slice that moves the customer's actual data. Without it the cut-over means an agent
opening a WhatsApp thread and seeing an empty conversation for a contact they have been talking to
for two years - which is the single most visible way a migration fails.

respond.io's Developer API v2 is a real, documented, SDK-backed surface (contacts, per-contact
message history with media URLs, custom fields, tags, lifecycle, channels, space users). It is good
enough to migrate the whole workspace, with three sharp edges this plan handles explicitly: message
items carry no top-level timestamp, there is no snippets endpoint, and there is no event or
assignment-log endpoint. The CSV exports are a genuinely degraded fallback (Enterprise-plan gated,
no media, no identities), so the plan treats them as such rather than as an equal path.

## 2. Architecture

```
connections (core public)                    provider "respondio", type "migration"
  config_json     { baseUrl, spaceLabel, timezone, requestsPerSecond }
  credentials_json Fernet { apiToken }                     one ACTIVE row per tenant

background_jobs (core public)  type = "omnichannel.respondio_migration"
  payload_json  { mode, source, connectionId, workspaceId, channelMap, userMap,
                  teamMap, lifecycleMap, messagesSince?, contactsOnly?, mappingHash }
  cursor_json   { phase, contactCursorId, contactIndex, messageContactId,
                  messageCursorId, counts, rate }
  result_json   { report: {...}, failures: {fileKey, rowCount} }

app_omnichannel.migration_refs   (source external id) -> (Foundryx local id)   THE idempotency index
contacts.migrated_from / conversation_messages.migrated_from                   descriptive markers

RespondIoClient ──▶ MigrationService ──▶ MigrationWriter ──▶ contacts / identities /
  (throttle,          (phases, cursor,      (the ONLY writer     conversation_messages /
   retry, cursor)      dry-run gate)         of migrated rows)    conversation_events / tags /
                                                                  contact_fields / quick_replies
```

The writer is deliberately NOT `MessageService` / `InboundService` / `ContactAdminService`. Those
paths publish to Redis, emit entity events, recompute the customer service window and bump unread -
every one of which is wrong for a backfill of two years of history. Everything the migration writes
is a **read-only history row**.

### 2.1 Backend pieces

| Piece | Where | Notes |
|---|---|---|
| Provider | `modules/omnichannel/respondio_provider.py` (new), registered in `bootstrap.register_providers` | `provider="respondio"`, `type="migration"`; `fields()` = `baseUrl`, `spaceLabel`, `timezone`, `requestsPerSecond` + secret `apiToken`; `test()` = `GET /space/channel` |
| API client | `modules/omnichannel/respondio/client.py` (new) | Bearer auth, self-throttle, `retry-after` honouring, 429 / 5xx backoff, `{items, pagination:{next, previous}}` cursor walking, typed `RespondIoError(code, message)` |
| Source shapes | `modules/omnichannel/respondio/shapes.py` (new) | Plain `pydantic.BaseModel` mirrors of the vendor's EXACT field names (`custom_fields`, `created_at`, `firstName`, ...) - the `Rio*` precedent: never fight `ApiModel` when matching an external spec |
| Channel map | `modules/omnichannel/respondio/channel_map.py` (new) | `SOURCE_TO_CHANNEL_TYPE` dict; the ONLY place a new A7 channel type plugs in |
| Model + migration | `modules/omnichannel/models.py`, `alembic/versions/0016_omni_migration_refs.py` | `MigrationRef`; `Contact.migrated_from`, `ConversationMessage.migrated_from`; idempotent inspector guards plus the `ADD COLUMN IF NOT EXISTS` mirror in `bootstrap.create_schema_and_tables` |
| Refs repo | `modules/omnichannel/repositories/migration_ref_repository.py` (new) | Batched `already_migrated(entity_type, external_ids) -> set`, `record(...)`, `local_for(...)`; every query tenant + workspace scoped |
| Service | `modules/omnichannel/services/migration_service.py` (new) | Phase orchestration, cursor writes, cooperative abort, dry-run gate, mapping hash, report assembly |
| Writer | `modules/omnichannel/services/migration_writer.py` (new) | The one place migrated rows are created; carries `writes_enabled` (dry run) and asserts the no-publish invariant |
| Media | `modules/omnichannel/services/migration_media.py` (new) | Capped fetch, `detect_upload_mime` sniff, `storage_for_tenant().save`, skip-and-report |
| Events backfill | inside `migration_writer`, calling `services/event_service.record()` | derived events only, source timestamps, `payload_json.migration.derived = true` |
| Job handler | `modules/omnichannel/services/migration_service.py` bottom | `JobHandlerDef("omnichannel.respondio_migration", run_migration, "respond.io migration")` via `register_job_handler`, registered from `bootstrap.register_engine_entities` |
| Routers | `modules/omnichannel/routers/migration.py` (new, manifest prefix `/omnichannel/migration`) | HTTP + Pydantic only: preflight, job create, job list, failure-file download |
| Schemas | `modules/omnichannel/schemas.py` | `MigrationPreflight`, `MigrationSourceChannel/User/Field`, `MigrationJobCreate`, `MigrationJobItem`, `MigrationReport`, `MigrationFailureRow`; datetime-bearing schemas inherit `ApiModel` |
| Permissions | `modules/omnichannel/permissions/permissions.csv` | += `omnichannel_migration,Data Migration,read,...` and `,manage,...` |
| Manifest + hooks | `modules/omnichannel/manifest.json`, `bootstrap.py` | version bump to `0.9.0` (see D-A6-21), the `migration` router declared, `update_tenant` handles the bump, `uninstall_tenant` wipes `migration_refs` |

Reused unchanged: `app/jobs/{registry,service,worker}.py`, `app/import_engine/readers.py`,
`app/import_engine/sanitize.py`, `app/services/storage.py`, `app/uploads.py`,
`app/integrations/base.py`, `modules/omnichannel/services/{event_service,contact_field_service,
contact_tag_service,lifecycle_service,contact_profile_service}.py`,
`modules/omnichannel/repositories/contact_repository.py`, `modules/omnichannel/phone.py`,
`modules/omnichannel/importers.py`.

### 2.2 Frontend pieces

| Piece | Where |
|---|---|
| Routes | `app/(protected)/omnichannel/settings/migration/page.tsx` (job history), `migration/new/page.tsx` (setup form), `migration/[jobId]/page.tsx` (detail + report + failures), plus `loading.tsx` per segment |
| List config | `.../migration/components/use-migration-list-config.tsx` - a clone of `app/(protected)/omnichannel/contacts/components/use-contacts-list-config.tsx` |
| Setup form | `.../migration/components/use-migration-form.tsx` (`ResourceFormConfig`, one tab, ordered sections), `migration-form-fields.tsx`, `migration-schema.ts` |
| Mapping rows | `.../migration/components/channel-map-row.tsx`, `user-map-row.tsx`, `lifecycle-map-row.tsx` - each is a labelled `SearchSelect`, never a free-text id |
| Report | `.../migration/components/migration-report-card.tsx` (one `DataGrid` per entity), `migration-failures-table.tsx` (`DataGrid` + authed CSV download) |
| Status | `.../migration/components/migration-status.ts` - a frontend `StatusBadge` registry over the job statuses (the `template-status.ts` / `channel-status.ts` precedent) |
| Services | `services/respondio-migration-service.{ts,mock,real}.ts` (name grepped 2026-09-06: no collision in `service_frontend/services/`) |
| Hooks | `hooks/use-respondio-migration.ts` (preflight + create + poll), reusing `services/jobs-service` for abort / retry |
| Types | `types/omnichannel.ts` += `MigrationPreflight`, `MigrationSourceChannel`, `MigrationSourceUser`, `MigrationJob`, `MigrationReport`, `MigrationFailureRow` |
| Menu | `config/menu.config.tsx` - a Migration entry inside the Omnichannel settings group in ALL three arrays |

Reused unchanged: `components/platform/{resource-list,resource-form,resource-actions,search-select,
multi-select,page-header,status-badge,clamped-text,skeletons}`, `components/ui/data-grid*`,
`lib/toast`, `hooks/{use-can,use-datetime}`, `app/(protected)/jobs/[id]/page.tsx` as the
polling-detail reference.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D-A6-1 | Primary source = the respond.io **Developer API v2** (`https://api.respond.io/v2`, `Authorization: Bearer <token>`). CSV exports are a degraded fallback, not an equal path | The API is the only source that carries message history WITH media URLs and per-channel identities. Plan gate corrected: the vendor's own help page says the Developer API needs **Growth plan and above** (the roadmap said "Business" - see F1). Messages Data Export is **Enterprise only**, so for a Growth-plan customer the API is the ONLY message source |
| D-A6-2 | Connection = a module-registered `IntegrationProvider` `respondio`, `type = "migration"`, token Fernet-encrypted and write-only. ONE ACTIVE respond.io connection per tenant | Reuses the whole connections spine (encryption, blank-to-keep, Test, the integrations Resource form) for free. A brand-new `type` value is inert for `resolve_for_type` (storage / email keep their determinism) and the existing `uq_connection_tenant_provider` partial index already gives one-active-per-tenant. Migrating a SECOND space = retire the first (`is_active=false`) and add another, which that index already permits. Adding `"migration"` to core's `EXEMPT_FROM_ONE_PER_TYPE` is a CORE index change and stays a backlog item |
| D-A6-3 | Idempotency = ONE `migration_refs` mapping table. `conversation_messages.external_message_id` is NEVER used, and marker columns are descriptive only | `models.py:450` carries `UniqueConstraint("external_message_id", name="uq_message_external_id")` - a GLOBAL, cross-tenant unique owned by the WhatsApp wamid dedupe. Writing `rio:<id>` there would (a) collide the moment two tenants migrate the same space and (b) let a later real receipt in `inbound_service._handle_status` match a migrated row. A mapping table also covers the six other entity types (fields, tags, identities, quick replies, users, channels) without six new columns, and it is what makes "re-run skips what is already migrated" a single batched `IN` query |
| D-A6-4 | Phase order is fixed: space preflight, custom fields, lifecycle map, tags, contacts, identities, messages, media, events, quick replies. Each phase is independently resumable | Every later phase needs the earlier phase's local ids. Lifecycle stages are mapped, never auto-created (D-A6-12), so they must be resolved before contacts land |
| D-A6-5 | Rate limiting is header-driven, not a hardcoded number: honour `retry-after`, read `x-ratelimit-limit` / `x-ratelimit-remaining`, self-throttle at a configurable `requestsPerSecond` (default 4), exponential backoff with jitter on 429 and 5xx, and halve our own rate after a fourth consecutive 429 | respond.io publishes no numeric Developer-API limit; the headers are the documented signal (verified in the vendor's own SDK, `src/client.ts`). A hardcoded guess would either crawl or trip the limit. The 20 requests/second figure that circulates belongs to Custom Channels, a different surface |
| D-A6-6 | Resume = `background_jobs.cursor_json` written after EVERY page; abort = re-read our OWN status from the DB at every batch checkpoint and bail BEFORE the terminal step | The storage-migration build lesson verbatim (`docs/reference/integrations-email-storage.md`): eager mode in dev/test runs the handler inline with no interleave, so an abort-does-not-stop-the-worker bug is INVISIBLE to the suite unless the check is explicit |
| D-A6-7 | Media failure policy = skip the blob, keep the MESSAGE, report the row. Never abort the job | A two-year history has dead attachment URLs in it. Losing one image is a report line; losing the run at 60% is a re-run of everything. `media_url` keeps the original source URL so the row is still self-describing, and `media_url_wire` already prefers `media_key` when present |
| D-A6-8 | "Read-only history row" is a hard, tested invariant: `external_message_id` NULL, no `realtime.publish`, no `emit_entity_event` / `notify_entity_event`, no consumer-webhook fan-out, no CSW recompute, no unread bump. ONE recompute per contact at the end of its message phase, and `agent_last_read_at` is set to `last_message_at` | Publishing 200k backfilled messages onto the WS bus would hammer every open inbox (the "no WS storms" requirement), firing entity events would launch a workflow run per migrated message (plan 31's triggers are live by then), and recomputing CSW would re-open 24h free-form windows that were closed years ago. Setting `agent_last_read_at` is what stops the migration from marking every historical thread unread |
| D-A6-9 | Message timestamps: `min(status[].timestamp)` when present, else interpolate between the nearest bracketing known timestamps of the same contact, else fall back to the source `contact.created_at`. Inferred timestamps are FLAGGED and COUNTED. Thread ordering always follows the source `messageId`, never the resolved timestamp | Verified against the vendor SDK's `GetMessageResponse` (`src/types/message.ts`): a message item has NO top-level timestamp - only `status[].timestamp` - and `status` is receipt-driven, so INBOUND messages routinely carry none. This is the same lossy-ness our own gateway got wrong and had to fix (`docs/reference/omnichannel.md`, the `RioMessageItem.timestamp` restore). Ordering by `messageId` means a bad inference can never reorder a conversation |
| D-A6-10 | Channel identity mapping is a per-job `channelMap` over a `SOURCE_TO_CHANNEL_TYPE` dict; a source channel with no compatible target is explicitly "Skip" and its messages become channel-less history (`channel_id` NULL, already legal - SYSTEM notes use it). An identity row whose real external id cannot be derived is SKIPPED and reported, never fabricated | A7 plugs in by adding one dict row plus a `channels.channel_type` value: **no schema change**, because `contact_channel_identities` is already generic (`channel_id` + `external_user_id`). A fabricated `external_user_id` would poison the LIVE inbound stitch (`inbound_service._resolve_contact`) - the exact class of bug this codebase keeps paying for |
| D-A6-11 | Contact matching ladder: `migration_refs` hit, then `phone_digits` inside the target workspace, then lowercased email, then create. A match MERGES (fills NULLs, unions tags, never overwrites, never moves an existing lifecycle stage) | `phone_digits` + `find_by_phone_digits` is exactly the key the live stitch uses, so a migrated contact and a later inbound message converge on the same row. Name matching is deliberately absent - it produces false merges |
| D-A6-12 | Lifecycle stages are MAPPED to existing stages, never auto-created; tags and custom fields ARE find-or-created | The lifecycle machine is a user-owned scoped status graph (plan 25 D1). Auto-minting stages would fork the graph behind the operator's back and break the foolproof-UI mandate. Tags and fields are flat registry rows with caps, so find-or-create is safe |
| D-A6-13 | Conversation events are DERIVED from migrated history, not fetched, and stamped `payload_json.migration.derived = true` with the SOURCE timestamp in the explicit `created_at` | respond.io exposes no event or assignment-log endpoint (verified across the SDK's whole client surface). Using `now()` would spike A9's "conversations opened, last 14 days" chart on migration day; the `derived` flag lets a report exclude backfilled activity |
| D-A6-14 | Dry run = the SAME handler with `writes_enabled=False`, inside a transaction rolled back at the end, media fetches skipped. A `run` is REFUSED `409 dry_run_required` without a successful dry run for the same mapping hash inside 24h | One code path or the two drift, and the dry run stops being evidence. Skipping media in dry run is not an accuracy loss (the counts are known from the message items) and avoids downloading tens of gigabytes to produce a report. The 24h + mapping-hash gate is the foolproof-UI form of "counts report BEFORE the real run" |
| D-A6-15 | ONE job type (`omnichannel.respondio_migration`), TWO modes | The `/jobs` list and drawer resolve one honest label; a Mode column carries the distinction. Two registrations would duplicate the handler wiring for no gain |
| D-A6-16 | Permissions: NEW module resource `omnichannel_migration` with `read` + `manage`. NOT a reuse of `contacts.import` | Collision grep 2026-09-06 across `app/permissions/permissions.csv`, `platform_permissions.csv` and every module CSV: no `migration*` resource exists anywhere; core owns `integrations.migrate_storage` as an ACTION on `integrations`, which does not collide. Reusing `contacts.import` would hand a bulk-import operator an external API token plus write access to messages, identities, events, tags and fields - the wrong blast radius |
| D-A6-17 | UI = the Resource shell at `/omnichannel/settings/migration` (list + `ResourceForm` setup + `/jobs/[id]`-style detail), NOT a bespoke wizard | The storage-migration wizard is a 3-step dialog for one bucket swap; A6 has five mapping blocks, a report and a failure table, which is a record, not a dialog. The shell gives dirty-guard, record nav, column prefs and 375/1280 behaviour for free |
| D-A6-18 | CSV fallback: contacts go through the EXISTING `ImporterDef("omnichannel_contacts")` wizard (zero new parsing code); message CSV rides `app/import_engine/readers.py` with an operator header map; quick replies ride the same reader | The import engine already owns magic-byte sniffing, caps, formula sanitization, header auto-map and the two-phase Test/Import UX. Re-implementing any of it for one migration is the parallel-component anti-pattern |
| D-A6-19 | Snippets are CSV or manual only | Verified against the SDK's `src/clients/space.ts`: the Space API exposes users, custom fields, closing notes, channels, templates and tags - and tags only as create / update / delete. There is NO snippets endpoint and NO tag LIST endpoint |
| D-A6-20 | The WABA number move is a RUNBOOK, not code | Moving a phone number between BSPs is a Meta-side ceremony (deregister, re-onboard through Embedded Signup, re-sync templates). Automating it would mean driving Meta's business-management API through a state we do not own |
| D-A6-21 | Module Alembic `0016_omni_migration_refs`, manifest `0.9.0` - TENTATIVE. Merge-renumber rule below | `main` at `c25a97ff` holds `0010`; in-flight lanes hold `0011` (s28 teams AND s29 broadcasts - already colliding), `0013` + `0014` (s31), with `0012`/`0015` reserved for plan 32. A6 is last in Phase A, so it renumbers rather than being renumbered |
| D-A6-22 | `messagesSince` date floor is optional and applies to MESSAGES only; contacts are never floored | A contact with no recent traffic still has to exist for the inbox to work. Message pages walk newest-first, so the floor is a cheap early stop per contact |
| D-A6-23 | The failure export is an AUTHED streaming download, never a signed capability URL | The plan-26 D-A2-6b ruling verbatim: the omnichannel signed-URL helper binds a single MESSAGE id so a chat image opens on a raw click. A bearer-less, replayable link to a CSV of contact names, phones and emails is a different risk class |
| D-A6-24 | Message-type mapping table is explicit (section 5.4) and an unrecognised type is written as `TEXT` with `payload_json.migration.unmappedType` plus a report row | A dropped message is invisible; a flagged one is auditable. Same principle as the import engine's per-row errors |

### Merge-renumber rule (binding for whoever merges A6)

`0016` and `0.9.0` are placeholders. Before merging, re-check `modules/omnichannel/alembic/versions/`
on the then-current `main`:

1. Rename the revision file and its `revision` id to `00NN` where `NN = max(existing) + 1`.
2. Re-point `down_revision` at the then-current head (if two lanes left two heads, add a merge
   revision the way `0007_omni_merge_heads.py` did - do not silently pick one).
3. Set `manifest.json` `version` to `0.<max existing minor + 1>.0`.
4. Write `update_tenant`'s branch as a TUPLE comparison over the parsed `from_version`
   (`if _v(from_version) < (0, 9, 0)`), never an equality check on one literal string - the literal
   is the thing that breaks when the number moves.
5. Revision ids stay <= 32 chars, and grep ALL existing ids for a collision (some files declare
   `revision: str = ...`).

## 4. Slices (one Sonnet coder each, sequential on the branch)

| Slice | Content | Size | AC ids |
|---|---|---|---|
| **S0 FE mock** | types, `respondio-migration-service` trio (mock), menu entries in all three arrays, list route + config, setup `ResourceForm` with the five mapping sections, detail route with report + failure table + polling, status badge registry; agent-browser smoke at 375 + 1280 | M | 01-10 |
| **S1 Connection + preflight** | `RespondIoProvider`, `RespondIoClient` (auth, throttle, retry, cursor walk), `shapes.py`, `channel_map.py`, `GET /omnichannel/migration/preflight`, permissions CSV rows, pytest against a stubbed transport | M | 11-17 |
| **S2 Job + contacts + dry run** | migration `0016`, `MigrationRef` + markers, refs repo, `MigrationService` phases + cursor + abort + mapping hash, `MigrationWriter` (contacts, fields, tags, assignee), dry-run report + `dry_run_required` gate, job routes, pytest TDD. **This is the thinnest end-to-end slice: a contacts-only dry run then a contacts-only real run** | L | 18-29 |
| **S3 Identities + messages** | identity derivation + skip rule, message writer, timestamp resolution, type mapping, delivery status, per-contact recompute, the no-publish invariant tests | L | 30-38 |
| **S4 Media + events + quick replies** | `migration_media.py` (cap, sniff, store, skip-report), derived `conversation_events`, quick-reply CSV, failure-row plumbing | M | 39-45 |
| **S5 CSV fallback + failure export** | `source="csv"` mode over `read_rows`, header map, the two CSV-mode blockers, authed failure-CSV route, contacts-path handoff to the existing import wizard | M | 46-49 |
| **S6 Wire + E2E + runbook** | swap mocks for real at the service boundary, polling + abort wiring, vitest, recorded agent-browser evidence run, `documentation/omnichannel/respondio-cutover-runbook.md`, Test Execution Report keyed to the AC ids | M | 50-61 |
| **Review** | `reviewer` agent on **Opus** (an external API token, a cross-tenant-shaped write path, a PII egress file and a bulk writer that bypasses four safety seams = security-grade review), then `/codex-review` | | |

S1 must land before S2 (the phases need the client). S2 before S3 (messages need contact local ids).
S3 before S4 (events derive from migrated messages).

## 5. Contracts

### 5.1 Source API (respond.io Developer API v2 - exact vendor field names)

Base `https://api.respond.io/v2`, header `Authorization: Bearer <apiToken>`. Rate-limit signal:
`x-ratelimit-limit`, `x-ratelimit-remaining`, `retry-after`. Pagination: query `limit` (1-100,
default 10) + `cursorId`; response envelope `{items: [...], pagination: {next, previous}}`.
Contact identifier is `id:{number}` | `email:{string}` | `phone:{string}`.

| Call | Path | Used for |
|---|---|---|
| List contacts | `POST /contact/list` body `{search?, timezone, filter:{$and?|$or?}}` | the contacts walk (`timezone` is REQUIRED, hence the connection field) |
| Get contact | `GET /contact/{identifier}` | targeted re-fetch on a retry |
| List contact channels | `GET /contact/{identifier}/channels` | identity rows |
| List messages | `GET /contact/{identifier}/message/list` | history walk |
| List space channels | `GET /space/channel` | preflight + `test()` |
| List space users | `GET /space/user` | user + team map |
| List custom fields | `GET /space/custom_field` | field registry map |
| List closing notes | `GET /space/closing_notes` | close-reason map (best effort, see F5) |

Vendor shapes we consume (verbatim names, mirrored in `shapes.py`):

```
Contact          { id:int, firstName, lastName?, phone?, email?, language?, profilePic?,
                   countryCode?, custom_fields?: [{name, value}], status?: "open"|"close",
                   tags?: [string], assignee?: {id, firstName, lastName, email},
                   lifecycle?: string|null, created_at: int (epoch seconds) }
ContactChannel   { id:int, name, source: ChannelSource, meta?: {...},
                   lastMessageTime?: int, lastIncomingMessageTime?: int, created_at: int }
CustomField      { id:int, name, description, dataType:
                   "text"|"list"|"checkbox"|"email"|"number"|"url"|"date"|"time",
                   allowedValues?: [string] }
SpaceUser        { id:int, firstName, lastName, email, role: "agent"|"manager"|"owner",
                   team: {id, name}|null, restrictions: [...] }
SpaceChannel     { id:int, name, source: ChannelSource, created_at: int }
Message item     { messageId:int, channelMessageId, contactId:int, channelId:int,
                   traffic: "incoming"|"outgoing", message: <union>,
                   status?: [{value: "pending"|"sent"|"delivered"|"read"|"failed",
                              timestamp:int, message?}],
                   sender?: {source: "user"|"ai_agent"|"workflow"|"api"|"echo"|"broadcast",
                             userId?, teamId?, workflowId?, broadcastHistoryId?} }
Message union    text | attachment{type: image|video|audio|file, url} | custom_payload |
                 quick_reply{title, replies[]} | email{text, subject?, cc?, bcc?, attachments[]} |
                 whatsapp_template{template:{name, languageCode, components[]}}
ChannelSource    whatsapp | whatsapp_cloud | 360dialog_whatsapp | twilio_whatsapp |
                 message_bird_whatsapp | nexmo_whatsapp | facebook | instagram | telegram |
                 line | viber | wechat | twitter | custom_channel | gmail | other_email |
                 twilio | message_bird | nexmo
Error            { code:int, message:string }
```

Sources (cited because the Stoplight reference is JS-rendered and un-fetchable by an agent, so the
vendor's own SDK is the authoritative machine-readable contract):
`https://developers.respond.io/`,
`https://github.com/respond-io/typescript-sdk` (`src/types/{contact,message,space,common}.ts`,
`src/clients/{contact,messaging,space}.ts`, `src/client.ts`),
`https://respond.io/help/integrations/developer-api` (plan gate, token generation),
`https://respond.io/help/workspace-settings/data-export` (export types, 7-day file validity, 365-day
range, one export per workspace, 15-minute dismissal),
`https://respond.io/help/contacts/contact-import` (identify-by rules, 20 MB, 200k rows).

### 5.2 Internal API (camelCase; datetimes Z-suffixed via `ApiModel`)

```
GET  /omnichannel/migration/preflight?connectionId=&workspaceId=
       -> { apiAvailable, spaceLabel, channels: [MigrationSourceChannel],
            users: [MigrationSourceUser], fields: [MigrationSourceField],
            targetChannels: [{id, name, channelType}], targetStages: [{statusId, label}],
            warnings: [string] }
POST /omnichannel/migration/jobs
       { connectionId, workspaceId, mode: "dry_run"|"run", source: "api"|"csv",
         channelMap: [{sourceChannelId, targetChannelId|null}],
         userMap:    [{sourceUserId, targetUserId|null}],
         teamMap:    [{sourceTeamId, targetTeamId|null}],
         lifecycleMap:[{sourceLabel, targetStatusId|null}],
         messagesSince?, contactsOnly? }                      -> 201 MigrationJobItem
       409 dry_run_required | 409 migration_in_progress | 422 {fieldErrors}
GET  /omnichannel/migration/jobs?page=&pageSize=&status=      -> { data: [MigrationJobItem], total, page }
GET  /omnichannel/migration/jobs/{jobId}                      -> MigrationJobItem (report inline)
GET  /omnichannel/migration/jobs/{jobId}/failures.csv         -> text/csv attachment (authed, private, no-store)
(reused, unchanged) POST /jobs/{jobId}/abort, GET /jobs/{jobId}
```

```
MigrationJobItem = { id, mode, source, connectionId, spaceLabel, workspaceId, workspaceName,
                     status, progressTotal, progressDone, progressFailed,
                     report: MigrationReport|null, failureCount,
                     startedAt, finishedAt, createdAt, actorUserName }
MigrationReport  = { entities: { contacts|fields|tags|identities|messages|media|events|quickReplies:
                                 { fetched, wouldCreate, wouldUpdate, wouldSkip, errors } },
                     messagesWithInferredTimestamp, blockers: [string],
                     samples: { contacts: [...], messages: [...] } }
MigrationFailureRow = { entity, sourceId, sourceLabel, reason, action }
```

422 bodies keep the house shape `{fieldErrors: {path: message}}` with paths `connectionId`,
`workspaceId`, `channelMap.<i>`, `lifecycleMap.<i>`, `messagesSince`.

### 5.3 `migration_refs` (module schema `app_omnichannel`)

```
id            String  pk
tenant_id     String  not null, index
workspace_id  String  not null, index
source        String  not null            -- "respondio"
entity_type   String  not null            -- contact|message|identity|tag|field|quick_reply|user|channel|event
external_id   String  not null            -- stringified vendor id
local_id      String  not null
created_at    UTCDateTime not null
UNIQUE (tenant_id, workspace_id, source, entity_type, external_id)
INDEX  (tenant_id, workspace_id, source, entity_type, local_id)
```

Plus `contacts.migrated_from` and `conversation_messages.migrated_from` (String, nullable, indexed,
value `"respondio"`) as descriptive markers so a migrated row is self-describing without a join.

### 5.4 Message mapping table

| Source `message.type` | `message_type` | `body` | `payload_json` | media |
|---|---|---|---|---|
| `text` | `TEXT` | `text` | - | - |
| `attachment` (`image`) | `IMAGE` | null | - | fetch `attachment.url` |
| `attachment` (`video`) | `VIDEO` | null | - | fetch |
| `attachment` (`audio`) | `AUDIO` | null | - | fetch |
| `attachment` (`file`) | `DOCUMENT` | null | - | fetch |
| `quick_reply` | `INTERACTIVE` | `title` | `{buttons: replies}` | - |
| `whatsapp_template` | `TEXT` | rendered body component text | `{template: {name, languageCode, components}}` | header media fetched when the component carries a link |
| `email` | `TEXT` | `text` | `{email: {subject, cc, bcc, attachments}}` | attachments fetched |
| `custom_payload` | `TEXT` | null | `{custom: payload}` | - |
| anything else | `TEXT` | null | `{migration: {unmappedType: "<type>"}}` | - |

Sender: `traffic == "incoming"` -> `sender_type = CONTACT`. `traffic == "outgoing"` ->
`sender_type = AGENT`, with `sender_id` set only when `sender.source == "user"` AND `userMap`
resolves `sender.userId` to a tenant user; every other source keeps `sender_id` NULL and records
`payload_json.migration.senderSource`.

Delivery: last `status[].value` -> `pending:QUEUED, sent:SENT, delivered:DELIVERED, read:READ,
failed:FAILED`; no status array -> NULL.

### 5.5 Derived events

| Event | When | `created_at` | `to_value` |
|---|---|---|---|
| `opened` | always, once per migrated contact with >= 1 message | first migrated message | the OPEN thread status id |
| `first_agent_reply` | first outgoing message after `opened`, honouring `is_first_reply_pending` | that message | null |
| `closed` | source `contact.status == "close"` | last migrated message | the CLOSED thread status id, `close_reason_id` NULL |
| `assigned` | `userMap` resolved an assignee | last migrated message | our user id |
| `lifecycle_changed` | `lifecycleMap` resolved a stage | last migrated message | our stage status id |

All carry `payload_json = {"migration": {"jobId": ..., "derived": true}}`. Not derived:
`reopened`, `snoozed`, `unsnoozed`, `comment_added` (no source data).

### 5.6 CSV fallback column map (respond.io Contacts export -> the plan-26 importer)

| Source column | Importer column | Note |
|---|---|---|
| `Contact ID` | (unused) | our importer matches on OUR `id` only; a respond.io id is not ours |
| `First Name`, `Last Name` | `firstName`, `lastName` | |
| `Phone` | `phone` | must carry the country code with `+`; normalized to digits |
| `Email` | `email` | lowercased for matching |
| `Language` | `language` | BCP-47 gate |
| `Country` | `countryCode` | ISO-3166 alpha-2, upper-cased |
| `Lifecycle` | `lifecycle` | resolver matches an existing stage by key or label |
| `Tags` | `tags` | comma-delimited, find-or-create within the tag cap |
| `Assignee` | (not importable) | assignment is a bulk action after import |
| any custom field | `cf_<fieldKey>` | one column per registered field, auto-mapped by LABEL |

Exact headers are NOT hardcoded: the import wizard's existing header-mapping step is the mapping UI,
so a vendor header rename is a mapping click, not a code change. Messages CSV mode declares its two
blockers up front (no media, no identities) and is Enterprise-plan gated on the customer's side.

## 6. Seam paths verified at `c25a97ff` (origin/main)

| Path | What A6 uses it for |
|---|---|
| `service_backend/modules/omnichannel/models.py:138` `class Contact` | `phone_digits:156`, `custom_fields_json:163`, `lifecycle_status_id:180`, `last_message_at:183`, `agent_last_read_at:186`, `last_agent_message_at:191` - the columns the per-contact recompute touches; `migrated_from` is added here |
| `service_backend/modules/omnichannel/models.py:198` `class ContactChannelIdentity` | identity rows; `channel_id` + `external_user_id` are already generic, which is why A7 needs no schema change |
| `service_backend/modules/omnichannel/models.py:402` `class ConversationMessage` | history rows; `media_key:424`, `payload_json:430`, `metadata_json:435`, `media_url_wire` property |
| `service_backend/modules/omnichannel/models.py:450` `UniqueConstraint("external_message_id", ...)` | the GLOBAL unique that D-A6-3 refuses to overload |
| `service_backend/modules/omnichannel/models.py:357` `class ConversationEvent` | backfilled events; `created_at` is explicit (no server default), which is what lets us stamp source timestamps |
| `service_backend/modules/omnichannel/models.py:592` `class QuickReply` | snippet import target |
| `service_backend/modules/omnichannel/services/event_service.py:48` `record(...)` | the ONE event seam; adds + flushes, never commits |
| `service_backend/modules/omnichannel/services/inbound_service.py:337` `_resolve_contact` | the live stitch A6 must stay compatible with (identity, then `phone_digits`) |
| `service_backend/modules/omnichannel/services/inbound_service.py:392` `_store_media` | the media-store pattern A6 mirrors (sniff, cap, `storage_for_tenant().save`, continue on failure) |
| `service_backend/modules/omnichannel/repositories/contact_repository.py:461` `find_identity` / `:473` `find_by_phone_digits` | the match ladder |
| `service_backend/modules/omnichannel/phone.py:17` `digits_only` | the ONE normalization both the stitch and A6 must share |
| `service_backend/modules/omnichannel/services/contact_field_service.py:180` `create` / `:321` `validate_values` | custom-field creation and typed validation |
| `service_backend/modules/omnichannel/services/contact_tag_service.py:40` `ContactTagService.list` | tag find-or-create |
| `service_backend/modules/omnichannel/services/lifecycle_service.py:33` `ENTITY_TYPE` / `:190` `initial_status_id` / `:222` `stages_for_workspace` | stage resolution and the default stage for a created contact |
| `service_backend/modules/omnichannel/services/contact_export_service.py:41` `EXPORT_JOB_TYPE` / `:337` `JobHandlerDef(...)` | the in-module `background_jobs` handler precedent (batching, cooperative abort, CSV to storage) |
| `service_backend/modules/omnichannel/bootstrap.py:111` `create_schema_and_tables` / `:414` `install` / `:424` `install_tenant` / `:469` `update_tenant` / `:54` `register_engine_entities` | migration mirror, handler + provider registration, grant path |
| `service_backend/modules/omnichannel/importers.py:42` `register_importer` | the contacts CSV path A6 hands off to |
| `service_backend/app/jobs/registry.py:44` `register_job_handler` | job registration |
| `service_backend/app/jobs/service.py:174` `run_job` | claim, isolation, crash-resume semantics |
| `service_backend/app/import_engine/readers.py:114` `read_rows` | CSV-mode reader |
| `service_backend/app/integrations/base.py:50` `IntegrationProvider` | the provider contract |
| `service_backend/app/services/storage.py:244` `storage_for_tenant` | media blobs |
| `service_backend/app/uploads.py:44` `detect_upload_mime` | magic-byte sniff (declared type ignored) |
| `service_frontend/app/(protected)/jobs/[id]/page.tsx` | the polling job-detail reference the migration detail clones |
| `service_frontend/app/(protected)/omnichannel/contacts/components/use-contacts-list-config.tsx` | the Resource-list clone source |
| `service_frontend/components/platform/{resource-list,resource-form,page-header,search-select,status-badge}` | the primitives roster (`docs/reference/design-language.md` section 4) |

In-flight lane seams (read-only, at their branch heads on 2026-09-06):

- `.claude/worktrees/s28` (`sprint-4/28-teams`, migration `0011_omni_team_assignment`) - core `teams`
  + membership. A6's `teamMap` binds respond.io `SpaceUser.team` to a Foundryx team; if s28 has not
  merged when A6 branches, `teamMap` ships as an accepted-but-inert payload block and the AC for it
  is DEFERRED rather than the whole slice blocking.
- `.claude/worktrees/s29` (`sprint-4/29-broadcasts`, migration `0011_omni_broadcasts` - collides with
  s28, one of them renumbers) - **broadcast history is NOT migrated.** respond.io's Developer API has
  no broadcast endpoint, and a migrated broadcast would have to fabricate recipient states. Stated in
  the runbook and the report.
- `.claude/worktrees/s30` (`sprint-4/30-dashboard-reports`, no new migration) - the reports read
  `conversation_events`, which is why A6 stamps SOURCE timestamps and the `derived` flag.
- `.claude/worktrees/s31` (`sprint-4/31-workflow-parity`, migrations `0013`, `0014`) - **workflows are
  re-authored by hand.** A6 must additionally guarantee it fires NONE of s31's triggers during a
  backfill (D-A6-8), which is why the writer bypasses `emit_entity_event` entirely.
- plan 32 / A7a (Messenger + Instagram) is being written in parallel - A6's `SOURCE_TO_CHANNEL_TYPE`
  already carries `facebook` and `instagram` rows so those channels light up the moment A7a's
  `channel_type` values exist, with no A6 change.

## 7. Customer prerequisites (the runbook's first section)

Before ANY run, the customer must have done all of the following. The setup form's Review section
refuses to enable "Run dry run" until the preflight confirms the first three.

1. **Plan check.** The respond.io Developer API needs **Growth plan or above**. Confirm it in
   Workspace Settings before anything else - a Starter/Team workspace has no API path and drops
   straight to CSV mode (contacts only, no media, no identities, no message history unless they are
   also on Enterprise for the Messages export).
2. **Access token.** Workspace Settings -> Integrations -> Developer API -> Add Access Token. One
   token per space. Paste it into the Foundryx respond.io connection; it is stored Fernet-encrypted
   and never echoed back.
3. **Workspace timezone.** The `POST /contact/list` body REQUIRES a timezone; capture the space's
   own timezone (shown on the respond.io dashboard) and put it on the connection.
4. **Target workspace exists** in Foundryx with its channels connected (A7 / Embedded Signup), its
   lifecycle stages already authored on the workspace Lifecycle canvas, and its close reasons set
   up. A6 maps to these; it never creates them.
5. **Users exist** in Foundryx with the SAME email addresses as the respond.io agents. Email is the
   only join key; a mismatch means unassigned threads.
6. **Export bundle taken anyway** (belt and braces, valid 7 days): Contacts export, Conversations
   export, Messages export (Enterprise) and Failed Messages export, plus screenshots of Contact
   Fields, Tags, Lifecycle, Snippets, Teams and the Workflow list. The snippets screenshot is not
   optional - there is no snippets API, so quick replies come from that or from a hand-made CSV.
7. **Freeze window agreed.** New respond.io traffic during a run lands after the cursor and needs a
   second incremental run; agree a window in which the customer stops replying in respond.io.
8. **WABA number move planned** (the ceremony A6 does NOT automate): keep respond.io live until the
   history run finishes, then deregister the number from respond.io's BSP, re-onboard it through
   Foundryx Embedded Signup, re-sync WhatsApp templates on the channel's Templates tab, re-point any
   click-to-chat links and QR codes, and only then point inbound traffic at Foundryx. Budget for
   template re-approval - Meta re-reviews templates under the new BSP.
9. **Volume estimate.** Contact count and rough message count, so the dry run's numbers can be
   sanity-checked against what the customer believes they have.

## 8. Backlog candidates (register on close; ids reserved from BL-SS-120)

| ID | Title | Priority |
|---|---|---|
| BL-SS-120 | Add `"migration"` to core `EXEMPT_FROM_ONE_PER_TYPE` so a tenant can hold several respond.io connections and migrate more than one space without retiring the first (core index change plus migration) | Low |
| BL-SS-121 | Incremental top-up run: re-run a completed migration for messages newer than the last cursor, so the freeze window can be minutes instead of hours | Medium |
| BL-SS-122 | Migrate internal comments once respond.io exposes a comment LIST endpoint (today only `POST /comments` exists) | Low |
| BL-SS-123 | Migrate closing-note text and map respond.io conversation categories onto A3 close reasons (the `GET /space/closing_notes` map is best-effort in v1) | Low |
| BL-SS-124 | Re-fetch failed media as a standalone retry job driven by the failure table, instead of re-running the whole migration | Medium |
| BL-SS-125 | GC for migration failure-CSV blobs when their `background_jobs` row is pruned (the blob outlives the row - same gap as the contacts export, plan 26) | Low |
| BL-SS-126 | Generic "external system migration" shell: A6's job + mapping + dry-run-report + failure-table pattern is the third `background_jobs` consumer with the same shape (storage migration, AutoCount ETL, this) | Low |
| BL-SS-127 | Contact-merge history: respond.io merges contacts, and a merged source id currently resolves to one target with no record of the other | Low |
| BL-SS-128 | Migrate blocked-contact flags once A6-era Foundryx has a block flag (B2 / G24) | Low |
| BL-SS-129 | Re-verify `SOURCE_TO_CHANNEL_TYPE` against the vendor's live channel catalog on a schedule; a new respond.io channel source currently falls through to "Skip" silently rather than warning | Low |

**Review round 1 nit - id collision (provisional, flagged for merge):** two DIFFERENT backlog items
actually landed in `backlog.md` under `BL-SS-129`/`BL-SS-130` during the S6 close - "Retry route has
no real backend route" and "job-history list search/sort/filter runs in Python" - NOT the
`SOURCE_TO_CHANNEL_TYPE` re-verify row reserved above. The `SOURCE_TO_CHANNEL_TYPE` row was never
actually registered. This whole table's ids are provisional against THIS lane's cut of `main`
(worktree s33) - per the merge checklist (D-A6-21), whoever merges A6 must re-derive every id from
`main`'s then-current max (139 at review time) rather than trust the numbers printed here, and
should register the `SOURCE_TO_CHANNEL_TYPE` row for real at that point if it is still open.

## 9. Risks and mitigations

- **The vendor reference is JS-rendered and un-fetchable by an agent.** Field names in section 5.1
  come from respond.io's OWN published SDK (types + clients), not from guesswork, and every shape is
  mirrored in `shapes.py` with `extra="ignore"` so an added vendor field never 500s a run. S1's first
  task is to hit the live API with the customer's token and diff the real payloads against
  `shapes.py`; a mismatch is a `shapes.py` fix, not a redesign.
- **Missing message timestamps** (D-A6-9). The mitigation is ordering by `messageId` plus a counted,
  flagged inference. If the customer's data turns out to be mostly inferred, the report says so
  BEFORE the real run and the operator can decide to buy the Enterprise Messages export instead.
- **A backfill that touches a live seam.** The single biggest failure mode is the writer accidentally
  calling `MessageService`/`InboundService` and publishing 200k WS events, firing 200k workflow runs
  and re-opening every CSW. Mitigation is structural (a separate writer) plus tested (AC-MIG-33
  asserts each seam is never invoked) plus reviewed (the Opus reviewer's first check).
- **`external_message_id` collision.** Guarded by D-A6-3 and by a test that writes a migrated row and
  then processes a real inbound webhook with a colliding-looking id, asserting no match.
- **Rate limiting is a guess until we see the customer's headers.** The client is header-driven and
  self-degrading, and the whole run is resumable, so the worst case is a slow run, never a lost one.
- **Media volume.** Two years of WhatsApp images can be tens of gigabytes into the tenant's storage
  connection. The dry-run report includes a media byte estimate from `attachment` counts so the
  operator can check bucket capacity first; media is the last phase, so aborting it still leaves a
  complete text history.
- **Partial run leaves a half-migrated workspace.** Acceptable and designed for: `migration_refs`
  makes the next run a no-op over what already landed, and the inbox is usable with partial history.
  There is deliberately no rollback - deleting migrated rows would risk deleting live ones.
- **Cross-tenant token reuse.** The connection is resolved with an explicit tenant filter and the
  platform fallback is deliberately NOT used. Pinned by AC-MIG-52.
- **PII egress.** The failure CSV carries names, phones and emails; authed streaming route, `private,
  no-store`, `omnichannel_migration.read` gated (D-A6-23).
- **Migration numbering collision.** Two lanes already both hold `0011`. Section 3's merge-renumber
  rule is binding and the merger must re-check, not trust `0016`.
- **Gateway contract.** This slice must not touch `routers/api_v1.py`, the `Rio*` schemas, or the
  consumer guide. AC-MIG-55 is a guard test, not a hope.
- **Review round 1 nit - flagged for the storage-migration owner (pre-existing, NOT introduced by
  this slice or its review fixes).** `bootstrap.py` registers a CORE table's `StorageKeyLocation`s
  (`BackgroundJob.payload_json`/`result_json`) from the omnichannel module (`register_storage_key_
  location(StorageKeyLoc(model=BackgroundJob, json_column=..., module=MODULE_NAME))`), commented as
  deliberate - but it means an A→B storage-connection migration now rewrites `conn:` keys embedded
  inside EVERY job type's `payload_json`/`result_json`, not only omnichannel's own (e.g. AutoCount ETL
  job payloads, storage-migration's own job rows). Confirm this is intended before the next storage
  migration ships, or move the registration to a core location file instead.

## 10. Flagged for the user (decisions taken that deviate from, or extend, the brief)

- **F1 - the plan gate in roadmap D12 is wrong.** The roadmap says the Developer API needs the
  **Business** plan. respond.io's own help page says **Growth plan and above**
  (`https://respond.io/help/integrations/developer-api`). More consequentially, the **Messages Data
  Export is Enterprise only** and the Contacts-module CSV export caps at 2500 rows, so the "CSV
  fallback" is much weaker than the roadmap implies: for a Growth-plan customer the API is not the
  preferred path, it is the ONLY path to message history. Prerequisite 1 in section 7 makes this the
  first thing anyone checks.
- **F2 - respond.io message items carry no timestamp.** This is the sharpest surprise in the whole
  slice and it changes the shape of "original timestamps" from a copy into an inference (D-A6-9).
  If you would rather have no timestamp than an inferred one, say so and S3 writes NULL plus a
  source-order-only thread; I chose inference because our own `ThreadItem` and the inbox both assume
  a `createdAt`.
- **F3 - snippets have no API.** The brief asked for "snippets -> quick replies" as part of the API
  job. Verified against the vendor SDK's whole Space client: there is no snippets endpoint (and no
  tag LIST endpoint either). Quick replies therefore ride a 2-column CSV. Prerequisite 6 asks the
  customer for the Snippets screenshot precisely so someone can produce that CSV.
- **F4 - conversation events are derived, not imported.** respond.io exposes no event or
  assignment-log endpoint, so A9's "assignment log" report cannot be historically accurate. A6
  backfills five event types it can defend from message data and stamps them `derived: true`. The
  alternative (leave events empty) makes every A9 report start on migration day, which is worse.
- **F5 - close reasons are best-effort.** `GET /space/closing_notes` returns
  `{category, description}` with no id we can key on, and the source contact object carries no
  closing-note reference. Backfilled `closed` events therefore set `close_reason_id` NULL. Mapping
  categories onto A3 close reasons is BL-SS-123.
- **F6 - new permission resource rather than reusing `contacts.import`.** The brief left this open.
  I chose `omnichannel_migration.read` / `.manage` (D-A6-16): the job holds an external API token and
  writes six entity families, which is not what a contacts-import key is scoped for.
- **F7 - the setup surface is a `ResourceForm`, not a wizard.** The brief said "admin UI (connection
  + mapping + dry-run report + run + progress + per-entity error table, on the Resource shell +
  `PageHeader`)", which is what this is; I am flagging it because the storage-migration precedent is
  a dialog wizard and a reader might expect that instead. Five mapping blocks plus a report plus a
  failure table is a record, not a dialog.
- **F8 - the real run is HARD-gated on a fresh dry run** (D-A6-14, `409 dry_run_required`, 24h,
  mapping-hash bound). The brief said "dry-run + counts report BEFORE the real run"; I made it an
  enforced precondition rather than a recommended sequence, because a migration is not undoable.
- **F9 - `teamMap` may ship inert.** If plan 28 has not merged when A6 branches, the payload block is
  accepted and ignored and its AC is DEFERRED. A6 does not block on A8.
- **F10 - no rollback, by design.** There is no "undo migration" action. Deleting migrated rows would
  mean deleting rows a live conversation may already reference. Re-running is safe; undoing is not.
  If you want an undo, the honest version is "migrate into a fresh workspace and delete the
  workspace", which I would rather offer explicitly than fake with a delete sweep.
