# Sprint 1 · Plan 01 - Foundryx Shared Service Platform + Omnichannel

**UAC (the contract):** `01-shared-service-platform-omnichannel-acceptance-criteria.md` - every slice below is "done" only when its AC ids pass.
**Repo:** `github.com/jayson-odoo/foundryx-shared-service.git` (fresh history). Duplicated from EMS; this plan STRIPS the domain modules and layers the shared-service gateway on the retained backbone.
**Design is LOCKED (already grilled)** - this plan is the design that fulfils the UAC, not a re-grill.

## 0. Product framing & what we keep vs strip

Foundryx runs ONE central multi-tenant instance. It is simultaneously (a) a **headless gateway API** for programmatic send/receive, and (b) a **full platform** with a durable store + agent inbox. Omnichannel WhatsApp is **service #1**; an LLM module is the planned service #2 (sibling module: own `/api/v1/llm/*`, own webhooks, consumes the message stream + calls the send API - NOT built here, only the seams).

**Tenancy model (locked):** `tenant` (account = billing) → `workspace` (bound to one WhatsApp number) → `channel` (WABA/phone). The public API key is issued **per workspace**. A consumer integrates by configuring `workspace_id` + `api_key` (respond.io Channel-ID pattern).

**KEEP (≈60% ports intact):** core auth/RBAC/tenant/user, module platform (capability registry + per-module Alembic), StorageService, Fernet secrets, all retained core engines, and `modules/omnichannel` in full - CSW logic, webhook ingress/dedup/HMAC, WA Cloud adapter, template + profile management, inbox/contacts/conversations, realtime WS.

**STRIP:** backend `modules/{crm,ems,finance}`; frontend `app/(protected)/{ems,finance,network,public-profile,reviews,store-admin,store-client}`. Relabel `app-store` → `services`.

**NET-NEW:** API-key auth + `workspace_api_keys`, public `/api/v1/{service}/*`, consumer webhook subscriptions + signed delivery outbox, `phone_number_id` UNIQUE, idempotency store, Redis Streams internal bus behind an interface, "Services" relabel, platform-settings config UI, the full deploy stack (Compose + Caddy + CI).

**Build order:** S1 (shell) → S2 (omnichannel verified in the stripped shell) → S3 (API-key send) → S4 (webhooks + bus) → S5 (deploy + go-live). Each slice: frontend-first behind a mock where UI is involved → real backend swap → TDD both layers → Playwright real-click report keyed to AC ids.

---

## Slice 1 - Platform shell: strip EMS domain, relabel App Store → Services
**Fulfils AC-01-01…06.**

### 1.1 Backend strip [BE]
- Delete `service_backend/modules/{crm,ems,finance}/` (dirs + their alembic version tables are module-owned, so removal leaves core clean - never touches `public`).
- Grep-and-remove every live import of the stripped modules (`modules.ems|modules.crm|modules.finance`), including any `conftest.py` install/schema-translate wiring, seed references, capability registrations, and status/terminology/import registry entries they added. Retain the omnichannel `messaging.send` capability provide.
- `bootstrap_modules()` now discovers only `modules/omnichannel/manifest.json`. Verify `python -m scripts.bootstrap_db` on empty Postgres migrates core + omnichannel and seeds platform + default tenants with zero import errors (AC-01-01).
- Ops rename (config defaults / `.env.example` / DB role + db name / image name / Compose service names) so nothing **tenant-facing** carries "foundryx-ems". Internal Python package paths (`app`, `service_backend`) may remain to bound blast radius - **log as backlog** (BL-SS-001 rename internal package). (AC-01-06)

### 1.2 Frontend strip [FE]
- Delete `app/(protected)/{ems,finance,network,public-profile,reviews,store-admin,store-client}/` and their services/hooks/types/components that are domain-only. Keep `omnichannel`, `settings`, `user-management`, `platform`, `account`, and the catalog route.
- Prune every menu array (`MENU_SIDEBAR`, `MENU_MEGA`, `MENU_MEGA_MOBILE`) of removed routes (all copies - filtering shifts indices; resolve sections by title). `rm -rf .next && npm run build` must be green (AC-01-02).

### 1.3 App Store → Services relabel [FE]
- **Reuse, don't rebuild:** rename the route `app-store` → `services` and relabel copy only; keep the shared `useModuleListConfig` Resource-shell/card config, `buildModuleActions`, and the operator console modules tab - just change the visible strings to "Services" and the nav entry/termKey. No parallel catalog. (AC-01-03, AC-01-05)
- White-label sweep: no tenant-facing "App Store" / "Foundryx" / "EMS" strings remain (AC-01-03, AC-01-38).

### 1.4 Verify core survives [BE][T]
- Run the full retained backend + frontend suites; fix any test that referenced a stripped module. Confirm no core engine depended on a domain module (AC-01-04).

**DoD gate:** clean boot, green builds/suites, real-data verify of the Services catalog at 375/1280.

---

## Slice 2 - Omnichannel wired + inbox working in the stripped platform
**Fulfils AC-01-07…11.** Mostly a verification + grant-sweep slice (the module ports intact).

### 2.1 Install + grant sweep [BE]
- Confirm `AppStoreService.install(tenant, "omnichannel")` seeds workspace statuses + default workspace and grants the module perms to Admin. Ship a **grant sweep** (re-run `tenant_admin_grant`) for tenants provisioned before the sweep so the inbox isn't silently 403'd (DoD gate #4, AC-01-07).
- Keep `seed_demo_conversations` (dev-only) so the inbox + E2E have day-one content; ensure `chn-demo` dev-cred channel seeds (sends stay stubbed).

### 2.2 Inbox + realtime verify [FE][E2E]
- Verify inbox list/detail, list search (name/phone/message-body EXISTS subquery), in-thread search, and the Redis pub/sub WS live-append at 375/1280 (list⇄detail stacks on mobile) (AC-01-08).
- Verify agent reply + CSW rejection path + template-only re-engage offer (foolproof composer) (AC-01-09).
- Verify channel connect (Embedded Signup simulated + manual token) (AC-01-10) and the Configuration/Templates/Profile tabs incl. namespaced `wa_templates.*` perms (AC-01-11).

*No new schema this slice.* If the WS/realtime path needs any wiring change post-strip, keep it a one-file fix.

---

## Slice 3 - API-key auth + public send + idempotency
**Fulfils AC-01-12…21.** The first net-new gateway slice.

### 3.1 Data model + migration [BE]
- New table **`workspace_api_keys`** in `app_omnichannel` (module-owned; per-module Alembic): `id, tenant_id, workspace_id, name, key_prefix(8), key_hash(sha256 hex), last_used_at, revoked_at, created_by, created_at`. Index `key_prefix`; unique `(key_prefix)` is not required (prefix collisions resolved by hash compare), but index it for O(1) lookup.
- **`channels.phone_number_id` → service-wide UNIQUE** (partial/nullable-safe): migration first **reconciles any existing duplicates** (log + null the losers) THEN adds `UNIQUE(phone_number_id) WHERE phone_number_id IS NOT NULL` (Postgres partial unique). Connect flow raises 409 `phone_number_in_use` on conflict (AC-01-20). DoD gate #2 (backfill/reconcile, not just add-constraint).

### 3.2 Key issuance + auth dependency [BE]
- `ApiKeyService`: `mint(workspace)` → generate `fxw_live_<32+ url-safe random>`, store `sha256(key)` + first-8 `key_prefix`, return the full key **once** (AC-01-13). `revoke(key_id)` sets `revoked_at`. Multiple active keys per workspace (rotation).
- **`get_api_workspace` dependency** (sibling of `get_current_user`, for public routes): parse `Authorization: Bearer fxw_live_…` → look up by `key_prefix` → constant-time `compare_digest` on hash → reject if revoked/missing → stamp `last_used_at` → return `(tenant_id, workspace_id, service)`. Uniform 401 `invalid_api_key`, no enumeration (AC-01-14). Enforce the key's service binding: a key reaching a `/api/v1/{other}/*` namespace or a workspace without that service active → 403 `service_not_enabled` (AC-01-15).

### 3.3 Public API namespace + send [BE]
- New router package `app/api/public/` (or `modules/omnichannel/routers/api_v1.py`) mounted at **`/api/v1/omnichannel`**, dependency = `get_api_workspace` (NOT the module `require_module` gate - the key IS the auth; but re-check service-active inside the dep).
- `POST /api/v1/omnichannel/messages` - validate `{to, type: text|template|media, …}` (interactive → structured `unsupported_type`), enforce **`Idempotency-Key`** header (dedup per `workspace+key` in Redis, 24h TTL; replay → return stored message id + 202, `idempotency_replay` note; AC-01-18), resolve/create the contact by `to` + workspace channel, **run the SAME CSW check** as the agent path (closed free-form → 409 `csw_window_closed`; template allowed - reuse `MessageService._window_open`/send logic, refactor the CSW gate into one shared function; AC-01-17), create the durable outbound message row (status QUEUED), **enqueue** the actual Meta send onto the internal bus, and return **202 + our message id** (AC-01-16). The message lands in the inbox as an outbound bubble immediately (realtime publish).
- `GET /api/v1/omnichannel/templates` - read-only approved-template list for the workspace's channel (AC-01-19).
- **Structured error envelope** middleware/handler for `/api/v1/*`: `{error:{code,message,details?}}` (AC-01-36).

### 3.4 Frontend - API keys management [FE]
- **Frontend-first behind a mock** (`api-keys-service.mock.ts` → real swap). Resource-shell list under the workspace/channel settings: columns name, masked prefix (`fxw_live_••••abcd` via `ClampedText`), created, last used (tz-rendered), status. Actions: **Mint** (opens a one-time full-key dialog with copy; never re-shown) + **Revoke** (typed/confirm). (AC-01-21) Verified 375/1280 (AC-01-38).

### 3.5 Tests [T]
- Backend pytest: key mint/hash/revoke, Bearer resolution + constant-time, cross-service reject, send 202 + inbox bubble, CSW-on-API, idempotency replay (same/different workspace), `phone_number_id` UNIQUE + reconcile migration, tenant isolation (AC-01-37). Frontend vitest: api-keys service + mask + mint-dialog once-only. E2E: mint key → (via API client) send → bubble appears in inbox (real clicks for the UI parts).

---

## Slice 4 - Consumer webhooks + delivery outbox + backfill + Redis Streams bus
**Fulfils AC-01-22…29.**

### 4.1 Data model + migration [BE]
- New table **`webhook_subscriptions`** (`app_omnichannel`): `id, tenant_id, workspace_id, callback_url, signing_secret (Fernet at rest), events (json/array), is_active, created_at, updated_at`. `signing_secret` generated server-side, shown once for copy.
- New table **`webhook_deliveries`** (the durable outbox, email-dispatcher pattern): `id, tenant_id, workspace_id, subscription_id, event_type, payload_json, status (PENDING|DELIVERED|FAILED), attempts, next_attempt_at, leased_until, last_error, created_at`.

### 4.2 Redis Streams event bus behind an interface [BE]
- **`EventBus` interface** (`app/services/event_bus.py`): `publish(stream, event)`, `consume(group, consumer)`, `ack(...)`. **`RedisStreamsBus`** impl (consumer groups + replay-from-offset + at-least-once); a **Kafka drop-in** is possible later (NOT built). Under `CELERY_TASK_ALWAYS_EAGER` the bus runs **inline** so tests need no Redis/worker (AC-01-27).
- Two internal streams: `omnichannel.inbound` (raw Meta events) and `omnichannel.deliveries` (consumer-webhook jobs). Workers drain; handlers are **idempotent** (dedup inbound by wamid - existing `uq_message_external_id`; dedup delivery by row id) so at-least-once re-processing is safe.

### 4.3 Thin ingress + fan-out [BE]
- Keep `POST /omnichannel/webhooks/{channel_id}` **thin**: verify `X-Hub-Signature-256`, push raw event to the `omnichannel.inbound` stream, return 200 **<200ms**, NO synchronous DB parse (AC-01-25). The existing GET handshake stays.
- **Inbound routing by number:** the worker resolves the channel via the now-UNIQUE `phone_number_id` (O(1)) rather than the URL `channel_id` where possible (keep `channel_id` as fallback for compatibility).
- After the InboundService persists a message/status, it enqueues a **consumer-webhook delivery** onto `omnichannel.deliveries` for every active subscription of that workspace whose `events` include the event type (AC-01-23).

### 4.4 Signed delivery outbox + retry [BE]
- **`WebhookDeliveryService`** (email-dispatcher clone): lease-claim PENDING rows, POST `callback_url` with `X-Fx-Signature: sha256=HMAC-SHA256(body, signing_secret)` + body `{event, workspaceId, data, occurredAt}`; 2xx → DELIVERED; 5xx/timeout → exponential backoff (1m/5m/25m…), attempts++, eventually **dead-letter** (FAILED, attempts preserved, replayable) - never blocks inbound (AC-01-24). Retention prune of DELIVERED/old-FAILED. Runs as a lifespan/worker daemon (like `email_dispatcher`).

### 4.5 Backfill cursor + media [BE]
- `GET /api/v1/omnichannel/messages?since=<cursor>&limit=` (workspace key) → in+out messages after the cursor, stable order, next-cursor, page cap ≤200 (AC-01-26). No consumer WS in v1 (documented).
- **Media durable both ways** (AC-01-28): inbound fetch-from-Meta → StorageService store → webhook payload carries a short-lived signed URL + stable `mediaId`; `GET /api/v1/omnichannel/media/{id}` re-signs (tenant/workspace scoped, never immutable-cached). Outbound: `POST /api/v1/omnichannel/media` accepts bytes (store + push to Meta) OR the send accepts a public URL (we still keep a stored copy).
- **Per-number token-bucket** rate limiter (Redis) keyed on `phone_number_id`, paced to the number's Meta tier; excess queued not dropped (AC-01-29).

### 4.6 Frontend - webhook subscriptions [FE]
- Frontend-first mock → real. Resource-shell list of subscriptions per workspace (callback URL via `ClampedText`, events as `MultiSelect`, active toggle, signing-secret shown-once dialog). Optional dead-letter/deliveries inspector list (reuse the email-log surfacing pattern). 375/1280.

### 4.7 Tests [T]
- Backend: HMAC signature golden (AC-01-23), retry→dead-letter, ingress <200ms/no-sync-DB, cursor pagination + isolation, media round-trip both ways, token-bucket pacing, EventBus at-least-once replay. Frontend vitest: subs service + secret-once. E2E: register a subscription → simulate inbound → local receiver asserts a valid `X-Fx-Signature` (mock the consumer endpoint).

---

## Slice 5 - Deploy stack + live number + platform-settings config UI
**Fulfils AC-01-30…35.**

### 5.1 Docker Compose full stack [BE]
- Adapt the inherited `docker-compose.yml`: services **api + worker (omnichannel + delivery/bus) + beat + postgres + redis + caddy**; drop the stripped-domain workers; healthchecks; api waits on postgres+redis (AC-01-30). Keep Fernet/env wiring.

### 5.2 Caddy auto-HTTPS [BE]
- Add a **Caddy** service (Caddyfile) terminating TLS via ACME for the **env-configurable** domain (default `icp-demo.foundryx.my`), reverse-proxying frontend + `/api/*` + `/omnichannel/webhooks/*` to the backend, setting `X-Forwarded-*` (so the auth throttle + `trust_proxy_headers` see real IPs) (AC-01-31). The inherited compose assumes host-nginx - **reconcile to Caddy-in-compose** per the locked decision.

### 5.3 GitHub Actions CI/CD [BE]
- Adapt `.github/workflows/deploy.yml`: on push to `main` run backend pytest + frontend vitest + build, build images, deploy to the Hostinger VPS (SSH/registry). Failing tests block deploy. De-EMS-brand the workflow (AC-01-32).

### 5.4 Platform-settings config UI [FE]
- New **Platform Settings** surface (platform tenant / super-admin only, `require_platform_permission`): the single Foundryx-owned **Meta app** creds (App ID/Secret/verify-token - secrets write-only, eye toggles, `secret-input`), default storage bucket/connection, per-number rate-tier defaults, public webhook domain. Platform-level, hidden from tenant callers (AC-01-33). Reuse the integrations/secret-input + Resource-form patterns. 375/1280.

### 5.5 Provisioning runbook + go-live [FE][E2E]
- Real-click provisioning flow: super-admin creates tenant → workspace (number-bound) → connect number (Embedded Signup under Foundryx Meta app / manual token) → mint API key + webhook signing secret → hand off `workspace_id` + `api_key` (AC-01-34).
- **Go-live smoke** (AC-01-35): with a real number + public callback, consumer `POST …/messages` delivers to WhatsApp + shows outbound in inbox; a reply arrives live in the inbox AND fires the consumer webhook with a valid signature. **May DEFER** to a manual runbook step if no live number is available at test time (record in the report + write a `documentation/plans/sprint-1/01-…-runbook.md`).

---

## Layering, reuse & house-rule compliance (applies to every slice)
- **Backend:** Router (HTTP/Pydantic only) → Service → Repository; every query tenant+workspace scoped from the auth context (AC-01-37); Pydantic v2 camelCase (`validation_alias`, `ApiModel` for datetime); UTCDateTime columns; Fernet for `signing_secret`/credentials.
- **Frontend:** UI → hook → service → `api-client`; **frontend-first behind a mock, one-line real swap** (tag mocks `PHASE 1 MOCK` + backlog); **Resource shell** for every list (API keys, webhook subs, services catalog) - no hand-rolled tables; **SearchSelect/MultiSelect** for every dropdown; `ClampedText`/`OverflowPills` for truncation; **white-label** (no "Foundryx"/"EMS"/"App Store" tenant-facing); responsive verified 375 AND 1280.
- **Module governance:** all new tables live in `app_omnichannel` (module-owned, per-module Alembic) - **never** ALTER core `public` tables; new permission keys via the module CSV (grep core for key + `*-service.ts` collisions first); grant sweep for existing tenants on any new perm.
- **Anti-SSTI / security:** no eval/Jinja on consumer content; constant-time key compare; sniff-gated media; presigned URLs never immutable-cached.

## Test strategy
- **Backend pytest + httpx** precede impl (TDD). **Frontend Vitest + RTL** for services/hooks/dialogs. **Playwright real-click** E2E per slice, run against the mock then the live stack; each slice produces a **Test Execution Report keyed to the AC ids** (PASS/FAIL/DEFERRED). Isolation: E2E that mutate shared tenant state provision a **dedicated tenant**; timestamp E2E-created names.

## Backlog (deferred - log to `documentation/backlogs/backlog.md`)
- **BL-SS-001** - rename internal Python package `service_backend`/`app` + image/DB identifiers to Foundryx (cosmetic, non-tenant-facing). Source: Slice 1.
- **BL-SS-002** - interactive (button/list) message type on the public send API (deferred from AC-01-16). Source: Slice 3.
- **BL-SS-003** - consumer-facing WebSocket stream (v1 is webhook + `?since=` backfill only). Source: Slice 4.
- **BL-SS-004** - Kafka `EventBus` implementation (interface built now; Redis Streams is the v1 impl). Source: Slice 4.
- **BL-SS-005** - LLM as service #2 (sibling module `/api/v1/llm/*`; seams only in this plan). Source: §0.
- **BL-SS-006** - API-key granular scopes / test-mode keys (v1 = live-only, no scopes). Source: Slice 3.
- **BL-SS-007** - per-workspace rate-tier auto-detection from Meta (v1 = super-admin default). Source: Slice 4/5.
