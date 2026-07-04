# Sprint 1 · Plan 05 — Omnichannel BSP: Message Processing (Inbound + Outbound + Inbox UI)

**Sprint:** 1
**Branch:** `sprint-1/omnichannel-message-processing`
**Source spec:** `documentation/high_level_plan_from_gemini/Whatsapp_BSP_Omnichannel_Functional_Spec.md` (§3, §4, §5)
**Depends on:** Plan 04 (module skeleton + full `app_omnichannel` schema + connected channel).
**Module:** `omnichannel` (schema `app_omnichannel`).

> **Plan 05 adds zero tables** — all schema landed in Plan 04. This plan adds **behavior + infra**: the zero-loss webhook pipeline, contact resolution, outbound sending, delivery receipts, the inbox UI, and the Redis/Celery/WebSocket infrastructure.

---

## 1. Goal

Make conversations actually work: receive WhatsApp messages reliably, resolve them to contacts, push them live to the agent's browser, and let agents reply (free-form inside the 24h window, template outside it).

Deliver:
- **Zero-loss webhook pipeline** (§3): fast ACK → Redis queue → Celery worker → parse/normalize/persist, with idempotency + exponential-backoff retries.
- **Contact resolution & identity stitching** (§4).
- **Outbound send** + **delivery receipts** (sent/delivered/read/failed) + **CSW enforcement** + **media** handling.
- The **inbox UI** (§5): reusable `<ConversationDrawer>` + thin inbox host page, with internal notes (Activities/Messages tabs), quick replies, snooze/close.
- **Infra bootstrap:** Redis broker, Celery worker process, FastAPI WebSocket + Redis pub/sub fan-out, `StorageService` (S3-compatible prod + local-disk dev).

---

## 2. Architecture decisions (grill outcomes)

| # | Decision | Choice |
|---|----------|--------|
| 8 | **Queue/worker** | Redis broker + **Celery** worker, autoretry with exponential backoff (5s / 30s / 2m / 10m per spec §3.3). |
| 9 | **Realtime** | FastAPI **WebSocket** (browser ⇄ FastAPI, room per workspace/contact) + **Redis pub/sub** fan-out so the separate Celery process & multiple uvicorn workers all reach the right sockets. |
| 10 | **Media** | `StorageService` interface — **S3-compatible** (S3/MinIO/R2) prod adapter + **local-disk** dev adapter. Worker downloads Meta media via Graph API → stores → `media_url`. (Closes BL-007's interface.) |
| 11 | **Templates** | **Sync/mirror read-only** from Meta into `whatsapp_templates`; agent picks an approved template + fills variables. **Full template authoring/submission → backlog.** |
| 12 | **Assignment** | **Manual** assign/reassign (`assigned_user_id`) + **Unassigned** queue + **self-claim** ("Assign to me"). No auto-routing (that's the deferred Rule engine, Plan 06). |
| 13 | **Inbox extras** | All IN: internal notes (SYSTEM bubbles) + Activities/Messages tabs, quick replies, delivery-receipt ticks, Snooze/Close lifecycle. |
| 14 | **CSW** | **Backend-enforced** — reject free-form send once `csw_expires_at` passed; permit approved template only. UI lock mirrors the rule. |
| 15 | **Stitching** | Phone/email dedup is **within-workspace** (contacts are workspace-scoped). |
| 17 | **Events** | **No event bus yet.** Future engines add emit-points when built (Plan 06 = paper contract). |

---

## 3. Infra bootstrap

- **Redis:** new infra dep. Local = native `redis-server` (no Docker, consistent with the native-Postgres stance); on-prem = documented. Env `REDIS_URL`.
- **Celery:** worker process alongside uvicorn (`celery -A omnichannel.worker worker`). Broker + result backend = Redis. Task `process_inbound_webhook(channel_id, raw_payload)` with `autoretry_for`, `retry_backoff`, `retry_backoff_max`, `max_retries`.
- **WebSocket + Redis pub/sub:** FastAPI WS endpoint `WS /omnichannel/ws?workspace_id=...` (JWT-authenticated on connect; membership-checked against `workspace_members`). Worker `PUBLISH omnichannel:ws:{workspace_id}` events; a FastAPI-side subscriber relays to connected sockets. Channels: `message.created`, `message.status`, `contact.updated`.
- **StorageService:** interface + `S3Adapter` + `LocalDiskAdapter`; selected by env. Dev needs no cloud.

---

## 4. Inbound pipeline (§3 + §4)

### 4.1 Fast ACK (FastAPI, public endpoint)
`POST /omnichannel/webhooks/{channel_id}` (+ `GET` for Meta's verify handshake):
1. Verify **Meta signature** (`X-Hub-Signature-256` against app secret) + request-size guard.
2. **Within ~50ms** return `200 OK`.
3. `PUSH` raw payload + `channel_id` to Redis (enqueue Celery task). Nothing else synchronous.

### 4.2 Worker: parse → resolve → persist → broadcast
1. **Normalize** the WhatsApp payload via `WhatsAppCloudAdapter.parse_inbound()` → canonical inbound shape.
2. **Idempotency:** `SELECT ... WHERE external_message_id = X`; if exists, skip (no duplicate bubble).
3. **Contact resolution (§4):**
   - Match `contact_channel_identities` by (`channel_id`, `external_user_id`) → existing `contact_id`.
   - Else **within-workspace** stitch: match `contacts.phone == external_user_id` (WhatsApp) → link new identity row.
   - Else create new `contacts` (raw profile name/avatar) + identity row.
4. **Media:** if media message, `fetch_media()` (Graph media-ID → bytes) → `StorageService.put()` → `media_url`.
5. **Insert** `conversation_messages` (`sender_type=CONTACT`, `delivery_status=READ`).
6. **Re-open thread + CSW:** set `status_id=OPEN`, `last_incoming_message_at`/`last_message_at = now`, `csw_expires_at = now + 24h`.
7. **Broadcast** `message.created` via Redis pub/sub → WS → browsers.
8. **Resilience:** DB down/locked → Celery retry with exponential backoff; payload safe in Redis until success.

---

## 5. Outbound (§5)

`POST /omnichannel/contacts/{id}/messages` (`conversations.reply`):
- **CSW check (backend-enforced, decision 14):** if `csw_expires_at` in the past → reject free-form; require `message_type=TEMPLATE` with an **approved** template from `whatsapp_templates`. If within window → free-form TEXT/media allowed.
- Send via `WhatsAppCloudAdapter.send()` → Graph API; persist `conversation_messages` (`sender_type=AGENT`, `sender_id=actor`, `delivery_status=SENT`, store returned `external_message_id`).
- Update `last_message_at`; broadcast `message.created`.

**Delivery receipts (decision 13):** Meta status webhooks arrive on the same `/webhooks/{channel_id}` → worker matches `external_message_id` → updates `delivery_status` (SENT→DELIVERED→READ / FAILED + `error_code`/`error_message`) → broadcast `message.status`. UI shows ticks / failed-send error.

**Templates (decision 11):** `GET /omnichannel/channels/{id}/templates` returns synced approved templates; sync job pulls from Graph API on demand + on send-time refresh. No in-app authoring (backlog).

---

## 6. Inbox UI (§5) — reusable drawer + thin host

Per component-library discipline, build the **`<ConversationDrawer>`** component first, then host it:
- **`<ConversationDrawer>`** (the reusable piece, later docks into CRM forms): chat header (channel icon, contact name, assign/reassign dropdown, **Activities | Messages** tabs), thread window (CONTACT left / AGENT right / SYSTEM centered yellow internal-only notes), composer (rich text + paste-to-upload, **★ Quick Replies/templates** button, **CSW lock** banner + template picker when window closed).
- **Inbox host page** (`app/(protected)/omnichannel/inbox/`): thread list (filter by assignee / status / priority, **Unassigned** bucket, self-claim) + the drawer. Workspace-scoped via `workspace_members`.
- **Realtime:** `useConversationSocket(workspaceId)` subscribes to WS; appends `message.created`, updates ticks on `message.status`.
- **Lifecycle (decision 13):** Snooze / Close actions hit `PATCH /contacts/{id}` (status transition over the `statuses` table). Close-triggers-survey is the deferred workflow bit (Plan 06).

Layering: UI → `useConversations`/`useMessages`/`useConversationSocket` → `conversation-service` → api-client. No component touches fetch/axios.

---

## 7. RBAC (declared in Plan 04, enforced here)

| Endpoint | Gate |
|---|---|
| `GET /omnichannel/contacts`, `/contacts/{id}`, `/contacts/{id}/messages` | `conversations.read` |
| `POST /omnichannel/contacts/{id}/messages` | `conversations.reply` |
| `PATCH /omnichannel/contacts/{id}` (assign/status/priority) | `conversations.assign` (assignment) / `conversations.reply` (status) |
| `WS /omnichannel/ws` | authenticated + `workspace_members` check + `conversations.read` |
| `POST /omnichannel/webhooks/{channel_id}` | **public** (Meta-signature-verified) |

Security invariant: outbound writes attributed to the **actor** (real agent), workspace scoping enforced server-side, never from client input.

---

## 8. Build order — 3 phases

### Phase A — Frontend prototype (mock, no backend)
- Build `<ConversationDrawer>` + inbox host against a **mock conversation-service** (mock threads, messages, a mock WS emitter that fires `message.created`/`message.status` on a timer). Tune: empty inbox, loading, live-append, CSW-locked composer + template picker, internal-note bubbles, delivery ticks, snooze/close, assign/unassigned.
- Vitest: bubble rendering by sender_type, CSW-lock logic, tick states, quick-reply insertion.
- Playwright (mock): real-click — open thread, send (free-form), see CSW lock + pick template, add internal note, assign-to-me, snooze/close.

### Phase B — Backend (wire real, TDD)
- Stand up Redis + Celery worker + WS pub/sub + StorageService (§3).
- Implement webhook receiver (fast ACK + signature), `process_inbound_webhook` task (parse/idempotency/resolve/media/persist/broadcast), outbound send + CSW enforcement, status-receipt handling, template sync, contact resolution repo logic (within-workspace stitch).
- Extend `WhatsAppCloudAdapter`: `parse_inbound`, `send`, `fetch_media`.
- pytest (httpx + fakeredis / eager Celery): idempotency skip, new-contact vs stitch vs existing-identity paths, CSW rejection past window, template-only outside window, delivery-status transitions, signature rejection, perm gating.
- Swap mock→real conversation-service + real WS client (one line at the service boundary).
- Playwright re-run against live backend in Meta Dev Mode: send from real WhatsApp → message appears live; reply lands on the phone; receipts tick.

### Phase C — Review + merge
- Code-review agent (core hard-fails + module governance: tables only in `app_omnichannel`, no core-table writes, cross-schema FK into core only; worker has no router/DB-in-router violations; WS auth + workspace scoping present).
- Test Execution Report. Merge to `main`.

---

## 9. CLAUDE.md / docs updates required
- Add **Redis + Celery + WebSocket** to backend commands/run instructions (start worker; `REDIS_URL`).
- Document `StorageService` env (S3 vs local-disk) — note it also closes BL-007's interface.
- Note the realtime model (WS rooms + Redis pub/sub) and the zero-loss pipeline contract.

## 10. Backlog spawned (add to `backlog.md`)
- **Full WhatsApp template management** — in-app authoring + submission to Meta + approval-status tracking (MVP is read-only sync).
- **Auto-assignment / smart routing** — round-robin + content-based routing; belongs to the deferred Rule engine (Plan 06).
- **Avatar/media upload polish** — closes BL-007 fully once StorageService is consumed UI-side.
- **WS scale-out hardening** — presence, reconnect/backfill on socket drop, message backfill since last_seen.
- **Additional message types** — INTERACTIVE (buttons/lists) compose UI; MVP renders inbound interactive, compose is later.
