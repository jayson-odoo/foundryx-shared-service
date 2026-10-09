# 29 - Omnichannel Broadcasts v1 (campaign model, builder, scheduled Celery fan-out, receipts)

> **Contract:** `29-omnichannel-broadcasts-acceptance-criteria.md` (55 ACs). This plan fulfils it.
> **Program:** slice **A4** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gap G9,
> roadmap D6 segments + D8 broadcast sending).
> **Depends on:** plan 25 / A1 AND plan 26 / A2 merged to `main`. A4 needs A2's `contact_segments`
> (a stored Resource-shell `FilterGroup`), `contact_filters.py` column map + `validate_filter_tree`,
> `contact_list_service` and `phone_digits`. **Prerequisite: do not branch before A2 merges.**
> **Branch:** `sprint-4/29-broadcasts`, worktree `.claude/worktrees/s29` off `main` AFTER the A2
> merge. Lane: backend `:8008` on DB `foundryx_service_s29`, frontend `:3007`,
> `agent-browser --session s29`. Each worktree gets its OWN `npm ci` (never a shared
> `node_modules`).
> **Code read at:** `origin/main` `d302ea7` (plan 23 + plan 25/A1), via the `s25` worktree.

## 1. Why

Broadcasts are the one respond.io surface with no Foundryx equivalent at all, and the customer uses
them weekly: pick a saved audience, pick an approved WhatsApp template, fill its variables from
contact data, schedule it, watch delivery land. Everything the send needs already exists - the ONE
`MessageService.send_message` path with template validation and Meta parameter building, the
`background_jobs` job engine with cooperative cancellation, the Celery workers, the delivery-receipt
webhook, the Resource shell. A4 adds the campaign OBJECT on top of them: who, what, when, and an
honest per-recipient ledger. It deliberately adds no second outbound path, no second scheduler and
no second job table.

## 2. Architecture

```
app_omnichannel.workspaces --1:N--> broadcasts --1:N--> broadcast_recipients
                                        |                      |
       audience (config, not a list)    |                      +-- message_id -> conversation_messages
         segment_id -> contact_segments (A2)                   +-- state queued|sent|delivered|read|failed|skipped
         filter_json -> FilterGroup, translated by A2's contact_filters map
         contact_ids_json -> explicit ids
                                        |
       channel_id -> channels (ACTIVE)  +-- template_id -> whatsapp_templates (APPROVED, no media header)
       status_id  -> app_omnichannel.statuses, NEW scope BROADCAST
       job_id     -> public.background_jobs (plain column, no cross-schema FK)

core public.background_jobs  type = "omnichannel.broadcast_send"   (snapshot -> chunked fan-out)
core workflow beat           task = "omnichannel.broadcasts_due"   (fires SCHEDULED broadcasts)
existing send path           MessageService.send_message(messageType="TEMPLATE", channel override)
existing receipt path        send_runner (SENT/FAILED) + inbound_service._handle_status (receipts)
existing realtime            realtime.publish(workspace_id, {...}) -> the inbox WS room
```

One rule holds the whole slice together: **a broadcast never sends; the send job does, one recipient
at a time, through the one existing send path.** Everything else (builder, list, status page) is
configuration and read model.

### 2.1 Backend pieces

| Piece | Where | Notes |
|---|---|---|
| Models | `service_backend/modules/omnichannel/models.py` | `Broadcast`, `BroadcastRecipient` (columns in section 5.3); `Channel.broadcast_rate_per_second` (Integer, nullable) |
| Migration | `modules/omnichannel/alembic/versions/0012_omni_broadcasts.py` | two tables + one column; inspector-guarded like `0004` / `0008`; Postgres-only, no-op under pytest; `bootstrap.create_schema_and_tables` mirrors the channel column with `ADD COLUMN IF NOT EXISTS`. **Re-check the real head + manifest version at branch time** (section 8, F1) |
| Statuses | `modules/omnichannel/services/statuses.py` | add scope `BROADCAST` to `DEFAULT_STATUSES` with keys `DRAFT, SCHEDULED, SENDING, SENT, CANCELLED, FAILED` (`is_terminal` on the last three); `ensure_statuses` already makes seeding idempotent |
| Broadcast service | `modules/omnichannel/services/broadcast_service.py` (new) | CRUD, save-time validation, duplicate, status transitions (`send` / `schedule` / `cancel`), test send, count recompute. All writes tenant + workspace scoped |
| Audience resolver | `modules/omnichannel/services/broadcast_audience.py` (new) | `preview_count(...)` and `iter_contact_ids(...)` composing A2's `contact_filters.CONTACT_FILTER_COLUMNS` + `translate_filter` + `contact_segment_service.tree_for`; explicit-ids branch validates workspace membership. **Never a Python-side scan** |
| Bindings | `modules/omnichannel/services/broadcast_bindings.py` (new) | `validate_bindings(db, tenant, workspace, template, bindings)` (count parity via `template_send.analyze_template`, field whitelist incl. registered `customFields.<key>`, fallback required, static text rejects token syntax) + `resolve(contact, bindings) -> (header_vars, body_vars, button_vars) | SkipMissingVariable` with Meta parameter sanitization |
| Send job | `modules/omnichannel/services/broadcast_send_service.py` (new) | `JobHandlerDef(type="omnichannel.broadcast_send", ...)` registered via `app/jobs/registry.register_job_handler`; phases snapshot -> chunk loop -> finalize; per-chunk status re-read (cooperative cancel); `JobService.set_total` / `advance` / `log` for progress |
| Chunk task | `modules/omnichannel/worker.py` | `@celery_app.task(name="omnichannel.broadcast_chunk")` that processes one chunk then self-schedules the next with a rate-derived `countdown` (the `deliver_webhook` self-reschedule pattern); eager dev loops inline in the handler instead |
| Due tick | `app/workflow_engine/worker.py` | `@celery_app.task(name="omnichannel.broadcasts_due")` + a 60s `beat_schedule` entry, guarded by `try: from modules.omnichannel... except ImportError` and failure-isolated - the exact `webhooks.retry_due` pattern (that worker is the sole beat host) |
| Receipts | `modules/omnichannel/services/broadcast_receipts.py` (new) | `record_delivery(db, message_row)` - one indexed lookup on `broadcast_recipients.message_id`, forward-only state advance, count recompute, realtime publish. Called from THREE existing sites (section 5.5), each wrapped in `try/except Exception: logger.exception(...)` |
| Reconciler | `broadcast_send_service.reconcile(db, broadcast_id)` | adopt-or-fail for claimed recipients with no `message_id`; runs at the end of the job and from the due tick for broadcasts stuck in `SENDING` |
| Repository | `modules/omnichannel/repositories/broadcast_repository.py` (new) | list / get / recipients page / set-based count aggregate / atomic claims (`UPDATE ... WHERE ...` rowcount) |
| Routers | `modules/omnichannel/routers/broadcasts.py` (new, manifest prefix `/omnichannel/workspaces`) | HTTP + Pydantic only; `require_permission` per route (section 5.1) |
| Schemas | `modules/omnichannel/schemas.py` | `BroadcastItem`, `BroadcastCreate`, `BroadcastUpdate`, `BroadcastSendRequest`, `BroadcastTestSendRequest`, `BroadcastRecipientItem`, `BroadcastAudience`, `TemplateBinding`, `BroadcastCounts` - all `ApiModel` where they carry a datetime |
| Workflow seam | `modules/omnichannel/workflow_nodes.py` | register the `omnichannel_broadcast` `WorkflowEntity` (read-only, `writable=()`); the job emits `emit_entity_event(..., "completed", ...)` |
| Permissions | `modules/omnichannel/permissions/permissions.csv` | `broadcasts.read`, `broadcasts.manage`, `broadcasts.send` |
| Manifest + hooks | `modules/omnichannel/manifest.json`, `modules/omnichannel/bootstrap.py` | version bump to `0.5.0` (review round 1, D-2 - see F1: `0.6.0` was a branch-time placeholder, corrected once the real numbering was checked), the new router declared, `update_tenant` calls `statuses.ensure_statuses` for the `BROADCAST` scope; `AppStoreService.update()` re-grants the three keys |

Reused unchanged: `services/message_service.py` (one additive kwarg, section 5.5),
`services/template_send.py`, `services/send_runner.py` (one hook call), `services/realtime.py`,
`services/contact_list_service.py` + `contact_filters.py` + `contact_segment_service.py` (A2),
`app/jobs/*`, `app/workflow_engine/entity_events.py`.

### 2.2 Frontend pieces

| Piece | Where |
|---|---|
| Routes | `service_frontend/app/(protected)/omnichannel/broadcasts/page.tsx` (list), `broadcasts/new/page.tsx`, `broadcasts/[id]/page.tsx` (detail + recipients) |
| List config | `.../broadcasts/components/use-broadcasts-list-config.tsx` - clone of `app/(protected)/user-management/users/components/use-users-list-config.tsx` |
| Builder | `.../broadcasts/components/use-broadcast-form.tsx` (`ResourceFormConfig`), `broadcast-form-sections.tsx` (Details / Audience / Channel / Message / Schedule / Review as grouped cards in ONE tab, the `channel-form-fields.tsx` pattern), `broadcast-schema.ts` |
| Audience | `.../components/audience-section.tsx` reusing the shell filter builder + a segment `SearchSelect` + the A2 contacts picker; `use-audience-preview.ts` |
| Variables | `.../components/binding-editor.tsx` (one row per template slot; source `SearchSelect`; contact-field `SearchSelect` fed by `useContactFields`) with the EXISTING `wa-bubble-preview.tsx` for the live preview (imported, not re-implemented) |
| Recipients | `.../components/use-recipients-list-config.tsx` (embedded `ResourceList`), `recipient-state.ts` (`StatusRegistry`, the `template-status.ts` pattern), errors via `ClampedText` |
| Status badge | `.../components/broadcast-status.ts` - `StatusRegistry` keyed on the six status keys |
| Actions | `.../components/use-broadcast-actions.tsx` - Send, Schedule, Cancel, Duplicate, Delete with `permission` + `isVisible` per status |
| Services | `services/broadcast-service.{ts,mock,real}.ts` |
| Hooks | `hooks/use-broadcasts.ts`, `hooks/use-broadcast.ts`, `hooks/use-broadcast-recipients.ts` |
| Realtime | reuse `hooks/use-conversation-socket.ts` + extend the `ConversationSocketEvent` union in `types/omnichannel.ts` with `broadcast.updated` (extend, never a parallel socket hook) |
| Types | `types/omnichannel.ts` += `Broadcast`, `BroadcastAudience`, `TemplateBinding`, `BroadcastCounts`, `BroadcastRecipient`, `BroadcastStatus` |
| Menu | `config/menu.config.tsx` - a Broadcasts entry after Contacts in every array that carries the Omnichannel block |

Reused unchanged: `components/platform/{resource-list,resource-form,resource-actions,search-select,multi-select,status-badge,clamped-text,jobs-drawer}`, `hooks/use-can.ts`, `hooks/use-datetime.ts`, `services/contact-service.*` + `contact-segment-service.*` (A2).

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D-A4-1 | Two module tables `broadcasts` + `broadcast_recipients` in `app_omnichannel`, unprefixed (the schema already namespaces, like every sibling table) | Brief D-A4-1; matches plan 27 D-A3-8 |
| D-A4-2 | The audience is stored as CONFIGURATION (segment id, or inline `FilterGroup`, or explicit ids) and SNAPSHOTTED into `broadcast_recipients` at SEND time, never at save | Brief D-A4-1. A segment is a live query; snapshotting at save would silently send to a stale list, and would make a scheduled broadcast lie about who it will reach. The snapshot instant is the auditable fact |
| D-A4-3 | Broadcast lifecycle rides the module's lightweight `statuses` table under a NEW `BROADCAST` scope, NOT the core status engine | Brief D-A4-1. These states are machine-driven and must never be tenant-editable; the core engine's value (editable graphs, edge auth, notifications) is a liability here. `ensure_statuses` gives the per-tenant seed AND the backfill for existing tenants for free. The `wa_templates` precedent (a plain column + a frontend badge registry) is the alternative; the statuses table wins only because a `status_id` FK keeps the list filter and the wire key consistent with every other omnichannel entity |
| D-A4-4 | Bindings are STRUCTURED (`{source: 'static', text}` or `{source: 'contactField', field, fallback}`), not free-form merge strings | **Deviation from the brief, flagged (F2).** A WhatsApp parameter is a single value SLOT, not a sentence, so a template renderer buys nothing and costs a rendering surface over tenant-authored strings. A structured binding means the server never renders a tenant string at all: it reads a whitelisted field, applies the fallback, sanitizes, done. `template_engine.merge.collect_tokens` is still used at SAVE time as the guard that a `static` text carries no token syntax. Anti-SSTI by construction; Jinja never enters the picture |
| D-A4-5 | A `contactField` binding REQUIRES a non-empty fallback | Meta rejects an empty parameter, and respond.io asks for the same default. Requiring it at save makes the empty-parameter runtime failure unreachable; the `missing_variable` skip stays only as a defence-in-depth path |
| D-A4-6 | Only APPROVED templates with NO media header are offered and accepted in v1 | Foolproof-UI ("a picker offers only choices that will work"). A media-header template needs per-send header bytes uploaded by id; doing that once per broadcast is its own design. Backlog BL-SS-083 |
| D-A4-7 | Sending is ONE `background_jobs` job (`omnichannel.broadcast_send`) whose handler snapshots then drives CHAINED chunk tasks (one chunk in flight per broadcast); eager dev/tests loop the same chunk function inline | Brief D-A4-2 + the house rule "new async worker job = `background_jobs` + `register_job_handler`". Chaining (rather than fanning N chunks out at once) is what makes the per-channel rate cap actually hold, and it gives a clean cooperative-cancel checkpoint per chunk |
| D-A4-8 | Per-recipient idempotency = an atomic CLAIM (`UPDATE broadcast_recipients SET attempted_at = now(), attempts = attempts + 1 WHERE id = :id AND attempted_at IS NULL`) before the send path is touched | Mirrors `send_runner`'s own QUEUED -> SENDING claim. A Celery retry, a duplicate delivery or a resumed job re-reads the row and skips it. **Never double-send** is the invariant, and it outranks "never lose a send" (a WhatsApp duplicate costs money and annoys the customer) |
| D-A4-9 | A recipient claimed but left without a `message_id` is RECONCILED by adopting a matching outbound TEMPLATE message to that contact created after the claim; if none exists it becomes `failed/send_result_unknown`. It is never re-sent | The only crash window is between the send path's commit and the recipient update. Adoption closes it in practice; the give-up branch keeps D-A4-8 absolute |
| D-A4-10 | Delivery/read receipts update recipients through ONE new `broadcast_receipts.record_delivery(db, message)` called from the three EXISTING delivery-status sites (section 5.5), each failure-isolated | The receipt seam already exists twice (`send_runner` stamps SENT/FAILED, `inbound_service._handle_status` applies Meta receipts). Adding a broadcast-aware branch inside those functions would couple them; a lazily imported hook that catches everything keeps the inbound pipeline's "a broadcast bug never drops a message" property |
| D-A4-11 | Counts are denormalized on `broadcasts` and recomputed set-based per chunk and at finalize; a test pins them against a live aggregate | The list must not run six sub-counts per row. Recomputing per chunk (not per recipient) keeps the write volume bounded |
| D-A4-12 | Rate tier = `channels.broadcast_rate_per_second` (nullable) falling back to a conservative global setting; pacing is computed per chunk inside the chained task | Brief D-A4-2. Two concurrent broadcasts on the SAME channel can still exceed the tier in v1 (accepted, documented); a per-channel Redis token bucket is BL-SS-084 and pairs with BL-SS-007 |
| D-A4-13 | Scheduled broadcasts fire from a new 60s tick on the WORKFLOW beat (`omnichannel.broadcasts_due`), guarded and failure-isolated | That worker is the sole beat host and already carries module ticks the same way (`webhooks.retry_due`, `meetings.*`, `autocount.etl_sweep`). A second beat process would be a new ops surface |
| D-A4-14 | Cancellation is cooperative at CHUNK granularity: the chunk re-reads the broadcast status from the DB before each batch; remaining `queued` recipients become `skipped/cancelled` | The house lesson from plan 10: eager mode hides a non-cooperative abort, so the status re-read must be a real DB read per checkpoint, and a test must assert the mid-run abort |
| D-A4-15 | Broadcasts write NO `conversation_events` (A3) rows | Brief D-A4-6. A broadcast is an outbound campaign, not a conversation; polluting the A9 read model with N campaign rows per contact would distort every conversation report |
| D-A4-16 | A4 EMITS the `omnichannel_broadcast` `completed` entity event and registers the read-only workflow entity, but does NOT add the `omnichannel.broadcast_completed` TRIGGER | **Deviation from the brief, flagged (F3).** A new module trigger needs TWO core edits (`entity_events._trigger_types_for` and the publish denormalization branch in `app/services/workflow_service.py`), which is A5's job. An emitted event with no mapping is inert and harmless (`_trigger_types_for` returns `[]`), so A4 ships the seam and A5 ships the two one-liners |
| D-A4-17 | NO public gateway surface for broadcasts in v1: `routers/api_v1.py`, the `Rio*` schemas and `documentation/omnichannel/consumer-integration-guide.md` are untouched | Brief D-A4-6. Consumers have no broadcast use case yet, and the guide is a contract: adding a surface means owning its shape forever. A guard test asserts no diff |
| D-A4-18 | Test send goes through the same send path and the same resolved bindings but creates NO recipient rows and touches no counts or status | Brief D-A4-3. A test send is a message, not a campaign event |
| D-A4-19 | `MessageService.send_message` gains ONE additive kwarg `metadata_extra: Optional[dict] = None` merged into `metadata_json` | The broadcast stamps `{"broadcast": {"id": ..., "recipientId": ...}}`, which makes D-A4-9's adoption exact and lets the inbox label a broadcast bubble later. Additive, defaulted, no existing caller changes |
| D-A4-20 | Skips for opted-out / blocked contacts are NOT implemented | Verified at `d302ea7`: `Contact` has no opt-out or blocked column (contact block lands in B2). The `skipReason` vocabulary reserves the value; BL-SS-085 |
| D-A4-21 | Labels are a plain `labels_json` string array on the broadcast, NOT `contact_tags` | respond.io broadcast labels are campaign metadata, unrelated to contact tags; reusing the tag table would make a tag deletion mutate campaign history |

## 4. Slices (build order)

Each slice is sized for ONE Sonnet coder in the `s29` lane, sequential on the same branch.

| Slice | Content | Size | ACs |
|---|---|---|---|
| **S0 FE mock** | types, `broadcast-service` trio (mock only), menu entries in every array carrying the Omnichannel block, list route + config (columns, status segments, actions), builder route with the six sections, binding editor + `WaBubblePreview`, detail route with Overview + Recipients, dialogs, `useCan` gating; vitest for the schema; agent-browser smoke at 375 + 1280 | L | 01-14 |
| **S1 BE model + CRUD** | models + migration `0012`, `BROADCAST` status scope + tenant hooks, `broadcast_repository`, `broadcast_service` CRUD + duplicate, `broadcast_audience` (preview + resolve), `broadcast_bindings` (validate), router reads/writes, schemas, permissions CSV + manifest bump, pytest | L | 15-25 |
| **S2 BE send engine** | `broadcast_send_service` (job handler, snapshot, chunk loop, finalize, reconcile), `worker.broadcast_chunk` chained task, rate pacing, `broadcast_bindings.resolve` + sanitization, `send_message` `metadata_extra` kwarg, `broadcast_receipts` + the three hook call sites, cancel, test send, `omnichannel.broadcasts_due` beat tick, pytest | XL | 26-42 |
| **S3 BE events + polish** | `omnichannel_broadcast` workflow entity, `completed` entity event, `broadcast.updated` realtime on every state/count change, jobs-drawer progress, `uninstall_tenant` assertion, gateway no-diff guard test, wire hygiene sweep, pytest | M | 43-50 |
| **S4 Wire + E2E** | swap the mock for the real service at the one service-boundary line, WS event wiring, vitest completion, recorded agent-browser evidence run at 375 + 1280, Test Execution Report keyed to the AC ids | M | 51-55 |
| **Review** | `reviewer` agent on **Opus** (tenant isolation across a new route family, the double-send invariant, an outbound path that costs money, the filter surface reused as an audience) then `/codex-review` | - | - |

S2 is the only oversized slice. If it needs splitting: **S2a** = job + snapshot + chunk loop + send +
idempotency + cancel (ACs 26-38), **S2b** = receipts + reconciler + finalize + beat tick + test send
(ACs 39-42 plus 35 and 36 verification).

## 5. Contracts

### 5.1 Internal API (camelCase; datetimes Z-suffixed via `ApiModel`)

```
GET    /omnichannel/workspaces/{wsId}/broadcasts
         ?page=&pageSize=&search=&sortBy=&sortDir=&filter=<json FilterGroup>&segment=<statusKey>
         -> { data: BroadcastItem[], total, page }                       broadcasts.read
GET    /omnichannel/workspaces/{wsId}/broadcasts/audience-preview
         ?segmentId=|filter=<json FilterGroup>                           broadcasts.read
         -> { count }
POST   /omnichannel/workspaces/{wsId}/broadcasts                         broadcasts.manage
         { name, labels?, channelId, audience, templateId, bindings, scheduledAt? } -> 201 BroadcastItem
GET    /omnichannel/workspaces/{wsId}/broadcasts/{id}                    broadcasts.read
PATCH  /omnichannel/workspaces/{wsId}/broadcasts/{id}                    broadcasts.manage
DELETE /omnichannel/workspaces/{wsId}/broadcasts/{id}      -> 204        broadcasts.manage
POST   /omnichannel/workspaces/{wsId}/broadcasts/{id}/duplicate -> 201   broadcasts.manage
POST   /omnichannel/workspaces/{wsId}/broadcasts/{id}/send               broadcasts.send
         { scheduledAt?: string|null }  -> BroadcastItem (SENDING or SCHEDULED)
POST   /omnichannel/workspaces/{wsId}/broadcasts/{id}/cancel             broadcasts.send
         -> BroadcastItem (CANCELLED)   409 broadcast_not_cancellable
POST   /omnichannel/workspaces/{wsId}/broadcasts/{id}/test-send          broadcasts.send
         { contactId } -> { messageId }
GET    /omnichannel/workspaces/{wsId}/broadcasts/{id}/recipients         broadcasts.read
         ?page=&pageSize=&state=&search=  -> { data: BroadcastRecipientItem[], total, page }

(reused, unchanged) GET /omnichannel/workspaces/{wsId}/contacts, .../contact-segments,
.../contact-fields, GET /omnichannel/channels, GET /omnichannel/channels/{id}/templates,
GET /jobs/{jobId}
```

Typed 409 reasons: `broadcast_not_editable`, `broadcast_not_cancellable`, `broadcast_already_sending`.
422 bodies keep `{fieldErrors: {path: message}}` with paths `name`, `channelId`, `templateId`,
`audience`, `audience.segmentId`, `audience.filter`, `audience.contactIds`,
`bindings.<group>.<index>.text|field|fallback`, `scheduledAt`.

### 5.2 Wire shapes

```
BroadcastItem = {
  id, workspaceId, name, labels: string[],
  channelId, channelName,
  audience: BroadcastAudience,
  templateId, templateName, templateLanguage,
  bindings: { header: TemplateBinding[], body: TemplateBinding[], buttons: TemplateBinding[] },
  status: 'DRAFT'|'SCHEDULED'|'SENDING'|'SENT'|'CANCELLED'|'FAILED', statusLabel,
  scheduledAt, startedAt, finishedAt,
  counts: { total, sent, delivered, read, failed, skipped },
  jobId, error,
  createdByUserId, createdByName, createdAt, updatedAt
}
BroadcastAudience   = { kind: 'segment'|'filter'|'contacts',
                        segmentId?, segmentName?, filter?: FilterGroup, contactIds?: string[] }
TemplateBinding     = { source: 'static', text: string }
                    | { source: 'contactField', field: string, fallback: string }
BroadcastRecipientItem = { id, contactId, contactName, phone,
                           state: 'queued'|'sent'|'delivered'|'read'|'failed'|'skipped',
                           skipReason?, errorCode?, errorText?, messageId?, attemptedAt }
```

`TemplateBinding.field` whitelist: `firstName`, `lastName`, `phone`, `email`, `language`,
`countryCode`, `lifecycle`, `customFields.<key>` where `<key>` is a field registered on THIS
workspace (A1 registry). Anything else is 422 at save and unreachable at send.

### 5.3 Tables

```
broadcasts(
  id pk, tenant_id idx, workspace_id fk workspaces idx,
  name, labels_json JSON(none_as_null),
  channel_id fk channels idx,
  audience_kind, audience_segment_id fk contact_segments null,
  audience_filter_json JSON(none_as_null), audience_contact_ids_json JSON(none_as_null),
  template_id fk whatsapp_templates, template_name, template_language,
  bindings_json JSON(none_as_null),
  status_id fk statuses idx, scheduled_at UTCDateTime null,
  started_at UTCDateTime null, finished_at UTCDateTime null,
  total_count, sent_count, delivered_count, read_count, failed_count, skipped_count (Integer, 0),
  job_id null, error Text null, created_by_user_id null,
  created_at, updated_at)

broadcast_recipients(
  id pk, tenant_id idx, broadcast_id fk broadcasts idx, contact_id fk contacts idx,
  message_id fk conversation_messages null idx,
  state, skip_reason null, error_code null, error_text Text null,
  attempts Integer default 0, attempted_at UTCDateTime null, created_at,
  UNIQUE(broadcast_id, contact_id))
```

`job_id` and `created_by_user_id` point at CORE rows and are plain indexed columns, no cross-schema
FK (the BL-030 pattern the module already uses for `lifecycle_status_id`). Every stored user id is
re-resolved TENANT-SCOPED at use time (the polymorphic stored-id rule).

### 5.4 Send job

```
type    : "omnichannel.broadcast_send"
payload : { broadcastId }
result  : { total, sent, failed, skipped, cancelled: bool }
handler :
  0. load broadcast tenant-scoped; not SENDING -> finish done (idempotent re-entry)
  1. PREFLIGHT: channel still ACTIVE + template still APPROVED + bindings still valid
       -> otherwise broadcast FAILED with `error`, job failed, zero sends
  2. SNAPSHOT (resumable, skipped when recipients already exist for this broadcast):
       resolve the audience in SQL, batch-insert broadcast_recipients (ON CONFLICT DO NOTHING),
       write skipped/no_identity + skipped/channel_inactive rows in the same pass,
       JobService.set_total(total)
  3. CHUNK LOOP (chunk = 100):
       re-read broadcast.status  -> CANCELLED: mark remaining queued as skipped/cancelled, stop
       re-read job.status        -> aborted: same
       per recipient: atomic claim -> resolve bindings -> MessageService.send_message(...)
                      -> store message_id + state from the returned delivery status
                      -> SendRejected: state failed + errorText (never abort the run)
       recompute counts, JobService.advance(...), realtime publish,
       eager: next chunk inline | prod: broadcast_chunk.apply_async(countdown = pacing)
  4. FINALIZE: reconcile() -> all recipients terminal-for-dispatch -> broadcast SENT + finished_at,
       emit_entity_event("omnichannel_broadcast", "completed", ...), job done
```

Pacing: `countdown = max(0, chunk_size / rate_per_second - elapsed)` with
`rate_per_second = channel.broadcast_rate_per_second or settings.omnichannel_broadcast_rate_per_second`
(new setting, conservative default). The computation is a pure function so a test asserts it without
sleeping.

### 5.5 Seams touched in existing files (verified at `d302ea7`)

| File | Change |
|---|---|
| `modules/omnichannel/services/message_service.py` | `send_message(..., metadata_extra: Optional[Dict[str, Any]] = None)` merged into `metadata` next to the existing `WORKFLOW_TEST_METADATA_KEY` branch. Nothing else. The TEMPLATE branch already validates approval, builds Meta components and **does not consult the CSW** (the window guard sits on the free-form branch); AC-BRD-34 pins that behaviour so a future refactor cannot silently break broadcasts |
| `modules/omnichannel/services/send_runner.py` | after the `SENT` commit (the `row.delivery_status = "SENT"; db.commit()` block) and inside `_fail(...)` after its commit: `broadcast_receipts.record_delivery(db, row)` in a `try/except Exception: logger.exception(...)` |
| `modules/omnichannel/services/inbound_service.py` | in `_handle_status`, after `self.db.commit()`: the same guarded call. It must sit AFTER the commit and BEFORE the consumer-webhook `enqueue_event`, and must never raise |
| `modules/omnichannel/services/statuses.py` | `DEFAULT_STATUSES["BROADCAST"]` |
| `modules/omnichannel/bootstrap.py` | `update_tenant` calls `statuses.ensure_statuses(db, tenant_id)` (idempotent) so existing tenants get the new scope; `uninstall_tenant` needs no change (the generic `OmniBase` loop covers both new tables) |
| `modules/omnichannel/worker.py` | the `omnichannel.broadcast_chunk` task on the existing `omni` queue |
| `app/workflow_engine/worker.py` | the `omnichannel.broadcasts_due` task + its `beat_schedule` entry, guarded on ImportError, failure-isolated |
| `service_frontend/config/menu.config.tsx` | the Broadcasts entry in every array carrying the Omnichannel block, tagged `module` + `permission` |

### 5.6 Recipient state machine

```
                       claim + send accepted
queued ──────────────────────────────────────▶ sent ──▶ delivered ──▶ read
   │                                             ▲
   │ send rejected (permanent)                   │ receipts only move FORWARD
   ├────────────────────────────────▶ failed ────┘ (a late `sent` after `read` is ignored)
   │
   └─ snapshot/skip rules, or cancel ─▶ skipped (no_identity | duplicate | channel_inactive |
                                                 cancelled | missing_variable)
```

A transient provider error leaves the recipient `queued` with the message row on its existing retry
path; the reconciler resolves anything still ambiguous at finalize.

## 6. Risks and mitigations

- **Double-send is the expensive failure.** Every path into the send path is guarded by the atomic
  `attempted_at` claim, and the reconciler adopts rather than retries. The test that matters runs
  ONE chunk twice and asserts exactly one `conversation_messages` row per recipient.
- **Rate limits.** Meta throttles per number; a fast fan-out gets 429s and, worse, quality-rating
  damage. Chunk chaining plus per-channel pacing bounds a single broadcast; two concurrent
  broadcasts on one channel are an accepted v1 gap (BL-SS-084, pairs with BL-SS-007).
- **Template variable safety.** Bindings are structured, so no tenant string is ever rendered as a
  template; a `static` text is rejected at save if it carries token syntax, and every emitted
  parameter is sanitized for Meta's newline / tab / repeated-space / length rules. There is no path
  from tenant input to a template engine.
- **The audience filter is the same injection boundary A2 built.** A4 reuses
  `contact_filters.validate_filter_tree` and `translate_filter` verbatim, including the
  `customFields.<key>` registry check; it introduces no second column map.
- **Plan 26 / 27 merge order.** A2 (segments, contacts list, `phone_digits`) is a hard prerequisite;
  A3 (plan 27) touches `bootstrap.update_tenant`, `permissions.csv`, `manifest.json` and adds its
  own migration. Whichever of A3 / A8 / A4 merges later takes the next free Alembic number and the
  next manifest version, and rebases its `update_tenant` guard to a `from_version <` comparison
  rather than an equality (plan 27 D-A3-16 established this).
- **Cooperative cancellation is invisible in eager mode.** The plan-10 lesson applies exactly: the
  chunk MUST re-read the broadcast status from the DB per batch, and the test must commit the
  cancel on a second session between chunks.
- **The receipt hook runs on the inbound hot path.** One indexed lookup on
  `broadcast_recipients.message_id`, wrapped so any failure is logged and swallowed. A broadcast bug
  must never drop an inbound WhatsApp message.
- **New column on an existing table.** `channels.broadcast_rate_per_second` is added by the
  migration AND mirrored with `ADD COLUMN IF NOT EXISTS` in `create_schema_and_tables`, because
  `create_all` never ALTERs an existing table. Deploy and reset with `bootstrap_db`, never
  `init_db`.
- **Permission grant sweep.** Three new keys reach existing tenants only through the manifest bump
  plus `update_tenant` and `AppStoreService.update()`. Without the bump the whole feature silently
  403s for every existing tenant.
- **Menu drift.** The three menu arrays are separate copies and, at `d302ea7`, `MENU_MEGA` and
  `MENU_MEGA_MOBILE` carry NO Omnichannel block at all. If A2 has added it, A4 appends Broadcasts to
  all three; if not, A4 adds the block properly tagged (`module` + per-child `permission`) rather
  than tagging only the sidebar. Mega-menu sections resolve by TITLE, never by index.

## 7. Backlog candidates (register on close; ids reserved from BL-SS-082)

| Id | Title | Priority |
|---|---|---|
| BL-SS-082 | Broadcast calendar view (respond.io Table / Calendar toggle) - deferred to Phase D | Low |
| BL-SS-083 | Broadcasts with media-header templates (upload the header blob once, reuse the media id across the run) | Medium |
| BL-SS-084 | Per-channel Redis token bucket so CONCURRENT broadcasts share one rate tier (pairs with BL-SS-007) | Medium |
| BL-SS-085 | Skip opted-out / blocked contacts once the B2 contact block flag exists (the `skipReason` value is already reserved) | Medium |
| BL-SS-086 | `omnichannel.broadcast_completed` workflow TRIGGER (the two core one-liners A5 owns) | Medium |
| BL-SS-087 | Broadcast analytics in Reports (A9): per-broadcast delivery funnel, per-template performance | Medium |
| BL-SS-088 | Retry the failed recipients of a finished broadcast as a new run (respond.io has no equivalent, the customer will ask) | Low |
| BL-SS-089 | Per-channel rate tier editable in the Channel Configuration tab (v1 is a DB / env value only) | Low |
| BL-SS-090 | Broadcast recipients export (CSV through `background_jobs`, reusing the A2 export job pattern) | Low |
| BL-SS-091 | Label a broadcast-originated bubble in the Inbox using the `metadata_json.broadcast` marker this slice stamps | Low |
| BL-SS-092 | `broadcast_recipients` retention / archival for large campaigns (pairs with BL-SS-060) | Low |
| BL-SS-093 | A crashed/stuck chunk chain that leaves `queued` recipients unclaimed (the beat's stuck-SENDING repair reconciles claimed-but-ambiguous rows, S2b D-A4-9, but does not RESUME a chain whose next `broadcast_chunk.apply_async` was never enqueued) - a broadcast can wedge in SENDING with never-attempted recipients until an operator re-runs the job. Needs a beat-driven "stalled SENDING" detector (last count-advance older than N minutes) that re-enqueues the next chunk, not just the finalize path `run_due_broadcasts` already covers | Medium |
| BL-SS-118 | Review round 1, S7 - `BroadcastService.cancel()`'s SENDING branch deliberately delegates the ledger sweep to the job's NEXT chunk checkpoint (`run_one_chunk`'s `current_status == "CANCELLED"` branch calls `repo.skip_remaining_queued` + finalizes), but `run_due_broadcasts`'s stuck-sweep only scans `Status.key == "SENDING"` - if the chunk chain has already DIED (crashed process, lost Celery task) before that checkpoint runs, a CANCELLED broadcast keeps `queued`/unclaimed recipients forever with `finished_at = NULL`. Fix needs its OWN branch (not a bare extension of the SENDING stuck-sweep, whose `has_dispatchable_recipients` early-`continue` is wrong for a cancelled broadcast - those queued rows are abandoned, not "real work still queued"): a "stuck CANCELLED" scan that unconditionally calls `repo.skip_remaining_queued(reason="cancelled")` then `reconcile_broadcast` + `finalize_broadcast`. | Medium |

## 8. Flagged for the user

- **F1 - migration number and manifest version are assumptions (resolved, D-2).** The brief assigns
  `0012_omni_broadcasts` and manifest `0.6.0` (A3 = 0009/0.3.0, A2 = 0010/0.4.0, A8 = 0011/0.5.0),
  but at `d302ea7` the head is `0008_omni_contact_model` and the manifest is `0.2.0`, and plan 26 as
  written still claims `0009`/`0.3.0` for itself. The coder re-read `modules/omnichannel/alembic/
  versions/` and `manifest.json` at branch time and took the next free number and minor version:
  migration `0011_omni_broadcasts`, manifest `0.5.0` (NOT `0.6.0`, a stale placeholder from before
  the real numbers were checked - corrected in the "Backend pieces" table above). **Merge-order
  rule (review round 1, D-2):** A4 merges to main BEFORE A8 by decision - main is at `0.4.0` when
  A4 lands, so the manifest bump to `0.5.0` genuinely fires `AppStoreService`'s Update path for
  every existing tenant (the tester's local s29 lane DB had ALREADY bootstrapped at `0.5.0` before
  this round's testing began, which is why the Update action looked unreachable there - an
  artifact of lane setup order, not a product defect; on `main` the mechanism fires as designed).
  Whichever of A4/A8 merges SECOND must re-check both numbers again and take the next free ones -
  this file's own numbers stop being facts the moment the other one merges first instead.
- **F2 - bindings are structured, not a merge-string micro-render (D-A4-4).** The brief said
  "`{{contact.firstName}}` style via the existing micro-renderer". A WhatsApp parameter is a single
  value slot, so this plan stores `{source, field, fallback}` and never renders a tenant string at
  all (`collect_tokens` is used only as the save-time guard that a static text carries no token
  syntax). If mixed sentences inside one parameter are genuinely wanted, add a third
  `source: 'template'` that runs `render_tokens(text, facts, mode='send', escape=False)` over the
  SAME whitelisted fact dict - one extra branch, no new surface.
- **F3 - no `broadcast.completed` workflow trigger in A4 (D-A4-16).** A4 emits the event and
  registers the read-only entity; the trigger needs two edits in CORE files
  (`app/workflow_engine/entity_events.py::_trigger_types_for` and the publish denormalization branch
  in `app/services/workflow_service.py`), which belongs to A5. Until then the emission is inert.
- **F4 - lifecycle on the module `statuses` table, not the core status engine (D-A4-3).** Followed
  the brief. The `wa_templates` precedent (plain column + frontend badge registry) would avoid a
  per-tenant seed entirely; say the word and it is a one-column change.
- **F5 - the E2E send journey runs on the dev tenant's seeded sandbox channel** (`chn-demo`, dev
  credentials, so the adapter stubs every send), not on a freshly provisioned tenant: a new tenant
  has no channel, no approved template and no contacts, so the journey would not exist. The run
  still timestamps every created broadcast name, and the tenant-isolation probe (AC-BRD-54) does
  provision its own tenant. Sending to the demo threads appends messages to them, which is additive
  and non-destructive.
- **F6 - "never double-send" outranks "never lose a send" (D-A4-8 / D-A4-9).** A crash in the
  millisecond window between the message commit and the recipient update, where adoption also fails,
  leaves a recipient marked `failed/send_result_unknown` even though the message may have gone out.
  The alternative (retry on ambiguity) risks charging the customer twice and messaging their
  contacts twice. Flagging the choice, not asking to change it.
- **F7 - two concurrent broadcasts on one channel can exceed the rate tier** (D-A4-12). v1 paces per
  broadcast; the global per-channel bucket is BL-SS-084.
- **F8 - review round 1 fix pass (B1-B3, S1-S6 fixed; S7 + nits below flagged/backlogged).**
  B1/B2/B3 and S1-S6 landed as code fixes with new tests (see the round-1 test report / commit).
  Deferred rather than fixed in this pass:
  - **S7** (a CANCELLED broadcast whose chunk chain already died keeps a dangling `queued` ledger
    forever) needs its OWN stuck-sweep branch, not a bare extension of the SENDING one - backlogged
    as **BL-SS-118** rather than risked as a rushed fix.
  - **Nit "duplicate not counted in `skipped_count`"** - confirmed correct-by-design (a duplicate
    contact writes NO row, so it can never contribute to a persisted count); clarified with a
    docstring, no behavior change.
  - **Nit "finalize's reconcile adopts a still-QUEUED message as `sent`"** - by design (F6's own
    trade-off: adoption over ambiguity), now called out explicitly here rather than only in the
    reviewer's notes.
  - **Nit "`key_to_id["SENT"|"FAILED"]` KeyErrors if a tenant lacks BROADCAST-scope statuses"** -
    fixed (`_require_status_id` raises a named `RuntimeError` instead of a bare `KeyError`).
  - **Nits "pacing always uses `CHUNK_SIZE`/`elapsed=0`" and "migration uses `sa.DateTime(timezone=
    True)` not `UTCDateTime`"** - reviewed, no action: both were already confirmed harmless /
    DDL-identical by the reviewer.
  - **Explanation-copy nit** (`use-broadcast-form.tsx` subtitle, `TestSendDialog`'s
    `DialogDescription`) - reviewed against the foolproof-UI carve-out (a one-line WHAT-is-this
    description is allowed; only procedural HOW-TO copy is banned) - both are short identifying
    descriptions, not instructions, so left as-is.
- **F9 - tester defects D-1..D-6 (E2E test report, round 1) - all fixed except D-5 (already covered
  by F8's S4) - two tester observations backlogged.**
  - **D-1** (no list row-actions column, AC-BRD-11/54) - fixed: `use-broadcasts-list-config.tsx`
    gained the trailing `id: 'actions'` column exactly as `use-users-list-config.tsx`'s.
  - **D-3/D-4** (the Audience Filter branch was a hardcoded non-functional stub, AND an empty/
    malformed filter silently resolved to "every contact in the workspace") - D-3 was already fixed
    by F8's B3 (`useContactFilterFields`) landing in the same round; D-4 is the NEW server-side
    guard this round - `has_leaf_condition` (recursive, `app/schemas/filters.py`) + `extra="forbid"`
    on `FilterCondition`/`FilterGroup`, wired into both `audience-preview` and create/update via
    `BroadcastValidationError` (`{fieldErrors}`, not a bare string).
  - **D-2** (manifest version deviation) - resolved as a doc-only fix; manifest STAYS `0.5.0` (see
    the corrected "Backend pieces" table row and F1 above) - A4 merges before A8 by decision.
  - **D-6** (no vitest for the template picker's non-approved/media-header exclusion, no vitest for
    `broadcast-service.mock.ts`) - fixed: `broadcast-form-sections.test.tsx` (4 tests) +
    `services/broadcast-service.mock.test.ts` (10 tests, states + error paths). The mock file itself
    stays a cleanup candidate (AC-BRD-13's own remark: dead code, no importer since S4).
  - **Observation "the SENDING claim and job creation aren't atomic"** - investigated, NOT fixed:
    `BroadcastRepository.claim_status` commits internally (mirrors `BackgroundJobRepository.claim`),
    so the real fix needs an optional `commit=False` on that shared primitive, touching all three of
    its call sites' atomicity guarantees - backlogged as **BL-SS-119** with the current (buggy)
    behavior pinned by a test, not silently left undocumented.
  - **Observation "a `broadcasts.read`-only role sees an empty list"** - backlogged as **BL-SS-120**
    (same class as BL-SS-081 for contacts).
