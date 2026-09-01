# Sprint 1 · Plan 01 - Foundryx Shared Service Platform + Omnichannel · Acceptance Criteria

**Source plan:** `01-shared-service-platform-omnichannel.md`
**Product:** Foundryx Shared Service Platform - a central, Foundryx-operated multi-tenant service host. Omnichannel WhatsApp = **service #1** (bypass respond.io, use Foundryx's own approved Meta app to send/receive); LLM = future service #2. Built by duplicate-and-strip from the EMS repo (this tree is the duplicate; fresh git history).

Format: each AC is independently verifiable (Given / When / Then). Grouped by slice. `[BE]` backend · `[FE]` frontend · `[E2E]` real-click · `[T]` unit/integration test. The Playwright Test Execution Report keys back PASS/FAIL/DEFERRED per AC id. **AC ids are stable - never renumber.**

**Locked model (the contract):**
- Tenancy: **tenant = account (billing)** → **workspace (number-bound)** → **channel (WABA/phone)**. API key is issued **per workspace**. A consumer configures `workspace_id` + `api_key` (respond.io Channel-ID style).
- Product shape: a **headless gateway API** AND a **full platform** (durable store + agent inbox that visualizes every in/out message; tenants get their own inbox login + agents).
- Public API namespacing: `/api/v1/{service}/…`; a key is bound to `workspace → service`; cross-service misuse is rejected.
- Money/PII/creds house rules carry over from EMS (Fernet, UTCDateTime, tenant-scoped queries, Resource shell, foolproof-UI, responsive 375/1280, white-label - copy never says "Foundryx"/"EMS").

**Definition-of-Done gate (every slice):** (1) any phase-1 mock is swapped to the real backend + verified with real data; (2) a new column/engine on an existing entity ships a **backfill** migration, not seed-if-absent; (3) no code hardcode-looks-up a tenant-editable key; (4) a new permission gets a grant sweep for already-provisioned tenants; (5) verified end-to-end from the user's perspective at 375px AND 1280px on a fresh `rm -rf .next && npm run build`, correct ports (FE 3001 / BE 8001).

---

## Slice 1 - Platform shell: strip EMS domain, relabel App Store → Services

### AC-01-01 - EMS/CRM/finance backend modules removed, app boots clean [BE][T]
- **Given** the stripped tree, **when** inspecting `service_backend/modules/`, **then** `crm/`, `ems/`, `finance/` are **gone** and only `omnichannel/` remains.
- **Given** a fresh `python -m scripts.bootstrap_db` on an empty Postgres, **when** it runs, **then** it completes with **zero** import errors, migrates core + omnichannel only, and seeds the platform + default tenants. No dangling import of a stripped module anywhere (`grep -r "modules.ems\|modules.crm\|modules.finance"` returns nothing in live code).

### AC-01-02 - EMS/domain frontend routes removed, build is green [FE][T]
- **Given** the stripped frontend, **when** inspecting `app/(protected)/`, **then** the domain route groups `ems/`, `finance/`, `network/`, `public-profile/`, `reviews/`, `store-admin/`, `store-client/` are **gone**; `omnichannel/`, `app-store/`→`services/`, `settings/`, `user-management/`, `platform/`, `account/` remain.
- **Given** `rm -rf .next && npm run build`, **then** it succeeds with no missing-import / dangling-route errors and no dead menu entries pointing at a removed route.

### AC-01-03 - module catalog is "App Store" (tenant + operator surfaces) [FE][E2E]
> **DECISION (2026-07-04, user override):** the catalog keeps the name **"App Store"** for BOTH the internal route/component names AND the tenant-facing label - the earlier "Services" relabel was reverted. Route stays `/app-store`; nav + breadcrumbs + operator modules tab read "App Store". "Service" remains the conceptual term for an installable module in docs, but the surface is labelled "App Store".
- **Given** an authenticated tenant admin, **when** they open the catalog nav entry, **then** it reads **"App Store"** and lives at `/app-store`; the page lists installable modules (Omnichannel visible), reusing the existing card/Resource-shell config - **not** a hand-rolled grid.
- **Given** the platform operator on a tenant-detail console, **when** they open the modules tab, **then** it drives the same install/deactivate/uninstall lifecycle. **No** tenant-facing string says "Foundryx" or "EMS" (white-label). Verified 375px AND 1280px.

### AC-01-04 - core engines + module platform + storage survive the strip [BE][T]
- **Given** the stripped backend, **when** the test suite runs, **then** core auth/RBAC/tenant/user, the module platform (capability registry, per-module Alembic orchestrator), StorageService, Fernet secrets, and the retained core engines still pass their suites. Removing the three domain modules did **not** break a core engine (no domain module was a hidden core dependency).

### AC-01-05 - services catalog is data-driven from on-disk manifests [BE][T]
- **Given** `bootstrap_modules()`, **when** it syncs the catalog, **then** only `modules/omnichannel/manifest.json` is discovered; the `modules` table lists exactly `omnichannel` (title/description/icon from its manifest). A future LLM module dropped into `modules/` would appear with **zero** core-code changes (registry-driven, not hardcoded).

### AC-01-06 - fresh git history + rebrand of ops identifiers [BE][T]
- **Given** the repo, **when** inspecting git, **then** history is fresh (origin = `github.com/jayson-odoo/foundryx-shared-service.git`).
- **Given** deploy/config defaults, **then** the DB/role/image names and env prefixes read as the Foundryx shared service (no user-facing "foundryx-ems" branding); internal package paths may stay `app`/`service_backend` (accepted debt, backlogged) so long as nothing tenant-facing shows the old brand.

---

## Slice 2 - Omnichannel wired + inbox working in the stripped platform

### AC-01-07 - omnichannel installs + seeds in the stripped platform [BE][T]
- **Given** a freshly provisioned tenant, **when** an operator (or bootstrap backfill) installs the omnichannel service, **then** `install_tenant` seeds the workspace statuses + a default "General" workspace, and the tenant Admin role is granted the omnichannel permission keys (`workspaces.*`, `channels.*`, `conversations.*`, `wa_templates.*`).
- **Given** an already-provisioned tenant that predates the grant, **then** the grant sweep re-runs `tenant_admin_grant` so the inbox is not silently 403'd (DoD gate #4).

### AC-01-08 - inbox renders + realtime works end-to-end [FE][E2E]
- **Given** a tenant agent with a connected (dev-cred) channel and seeded demo conversations, **when** they open the inbox, **then** threads + message bubbles render; opening a thread loads its messages; the list search matches name/phone/message-body.
- **Given** an inbound message arrives (simulated webhook), **then** the bubble appears **live** via the Redis pub/sub WS without a manual refresh. Verified 375px AND 1280px (list⇄detail two-pane stacks on mobile).

### AC-01-09 - agent reply + CSW enforcement intact [BE][FE][T]
- **Given** an open 24h window, **when** an agent sends a free-form reply, **then** it is accepted, persisted as an outbound bubble, and dispatched via the WA adapter (dev-stubbed in dev).
- **Given** the window is closed (`csw_expires_at` past), **when** the agent tries a free-form reply, **then** it is **rejected** with the CSW message and only an approved template send is offered (foolproof-UI: the composer only offers valid options).

### AC-01-10 - channel connect (Embedded Signup + manual) works [FE][E2E]
- **Given** an operator/agent with `channels.manage`, **when** they connect a number, **then** the Embedded Signup wizard runs (simulated popup when the Meta env is unset) OR the manual-token fallback accepts a System-User token + Phone Number ID; on success a `Channel` row is created and the WABA is subscribed to the app webhooks.

### AC-01-11 - template + profile management tabs intact [FE][E2E]
- **Given** a connected channel, **when** the agent opens the channel form, **then** Configuration · Templates · Profile tabs work: Sync pulls Meta identity, templates list/draft/submit round-trips (dev-promotes PENDING→APPROVED), profile write-through saves. Namespaced perms `wa_templates.*` are used (no collision with any core `templates.*`).

---

## Slice 3 - API-key auth + `workspace_api_keys` + public send + idempotency

### AC-01-12 - `workspace_api_keys` table + hashed storage [BE][T]
- **Given** the Slice-3 migration ran, **when** inspecting the schema, **then** `workspace_api_keys` exists with `(id, tenant_id, workspace_id, name, key_prefix, key_hash, last_used_at, revoked_at, created_by, created_at)`; the key is stored **only** as a SHA-256 `key_hash` + 8-char `key_prefix` - **no plaintext key column** exists.

### AC-01-13 - key minted once, shown once, live-only [BE][FE][E2E]
- **Given** an operator on a workspace, **when** they mint an API key, **then** the full `fxw_live_…` value is returned **once** in the create response and never again (subsequent reads show only the prefix). Keys are live-only (no test/sandbox scope) and carry **no** granular scopes.
- **Given** the same workspace, **then** **multiple active keys** may coexist (rotation) and any one can be independently **revoked** (`revoked_at` set); a revoked key immediately 401s.

### AC-01-14 - Bearer key resolves workspace + service, tenant-scoped [BE][T]
- **Given** a request with `Authorization: Bearer fxw_live_…`, **when** it hits a public `/api/v1/omnichannel/…` endpoint, **then** the key is looked up by prefix + hash-compared (constant-time), the **workspace + tenant are derived from the key** (never from the body/query), `last_used_at` is stamped, and every downstream query is tenant+workspace scoped.
- **Given** a revoked/unknown/malformed key, **then** a uniform **401** with a structured `{error:{code,message}}` body (no key/tenant enumeration).

### AC-01-15 - cross-service key misuse rejected [BE][T]
- **Given** a key bound to `workspace → omnichannel`, **when** it is presented to a different service's `/api/v1/{other}/…` namespace (or the workspace lacks that service active), **then** it is **rejected** (403 `service_not_enabled`) - a key can't reach a service its workspace isn't entitled to.

### AC-01-16 - public send: 202 async + our message id [BE][T]
- **Given** a valid workspace key, **when** it `POST /api/v1/omnichannel/messages` with `{to, type:"text", text:{body}}`, **then** the response is **202 Accepted** with **our** durable message id (not Meta's wamid); the send is enqueued (not sent synchronously in the request) and the message immediately appears in the platform inbox as an **outbound** bubble on the matching contact thread.
- Types **text**, **template**, **media** are accepted; **interactive** is deferred (returns a structured `unsupported_type` error). Structured errors everywhere: `{error:{code,message,details}}`.

### AC-01-17 - CSW enforced on the public send API [BE][T]
- **Given** a contact whose 24h window is **closed**, **when** a public **free-form text** send is attempted, **then** **409** `csw_window_closed`; a **template** send to the same contact is accepted (the same CSW logic as the agent path, one code path).

### AC-01-18 - idempotency dedup per workspace [BE][T]
- **Given** two identical `POST /api/v1/omnichannel/messages` with the same `Idempotency-Key` header from the same workspace within 24h, **when** processed, **then** the **second returns the first's stored message id + 202** and creates **no** second message/send (dedup key = workspace + Idempotency-Key, stored in Redis with 24h TTL).
- **Given** the same `Idempotency-Key` used by a **different** workspace, **then** it is treated as distinct (dedup is workspace-scoped).

### AC-01-19 - read-only templates over the API [BE][T]
- **Given** a workspace key, **when** it `GET /api/v1/omnichannel/templates`, **then** it returns the workspace channel's approved templates (read-only mirror); template authoring stays in the platform UI (no create/submit over the public API v1).

### AC-01-20 - `phone_number_id` is UNIQUE service-wide [BE][T]
- **Given** the Slice-3 migration, **when** inspecting `channels`, **then** `phone_number_id` carries a **service-wide UNIQUE** constraint (nullable allowed for un-provisioned rows, but any two connected channels can't share a number) enabling **O(1)** inbound routing by number.
- **Given** an attempt to connect a number already bound to another tenant's channel, **then** it is **rejected** (409 `phone_number_in_use`). Existing duplicate rows (if any) are reconciled by the migration before the constraint is added (DoD gate #2).

### AC-01-21 - API-keys management UI (Resource shell) [FE][E2E]
- **Given** an operator/tenant-admin on a workspace, **when** they open its API keys surface, **then** it is the **Resource-shell** list (name, prefix `fxw_live_••••abcd`, created, last used, status) with Mint / Revoke in the action registry - **not** a hand-rolled table. Minting shows the one-time full-key dialog with a copy affordance; the full key is never re-shown. Verified 375px AND 1280px.

---

## Slice 4 - Consumer webhooks + delivery outbox + backfill + Redis Streams bus

### AC-01-22 - `webhook_subscriptions` table + management [BE][FE][T]
- **Given** the Slice-4 migration, **when** inspecting the schema, **then** `webhook_subscriptions` exists `(id, tenant_id, workspace_id, callback_url, signing_secret, events[], is_active, created_at, …)`; a workspace can register/edit/disable its callback URL + event set via the platform UI (Resource shell) or an operator.
- The `signing_secret` is generated server-side, Fernet-at-rest, and shown for copy on creation (used by the consumer to verify signatures).

### AC-01-23 - signed outbound delivery on inbound + status [BE][T]
- **Given** a workspace with an active subscription, **when** an inbound message OR a delivery-status receipt is processed, **then** a delivery is enqueued to the durable outbox and POSTed to `callback_url` with header **`X-Fx-Signature: sha256=HMAC-SHA256(body, signing_secret)`** and a JSON event `{event, workspaceId, data, occurredAt}`.
- **Given** the consumer's endpoint, **when** it recomputes the HMAC over the raw body, **then** it matches (parity-pinned test with a golden payload+secret).

### AC-01-24 - delivery outbox: retry + backoff + dead-letter [BE][T]
- **Given** a callback that returns 5xx/times out, **when** delivery runs, **then** it retries with exponential backoff (email-dispatcher pattern: durable rows, lease-claimed, crash-safe reclaim); after N exhausted attempts the row moves to **dead-letter** (status FAILED, attempts preserved) and is inspectable/replayable - a failing consumer never blocks inbound processing or loses events.
- **Given** a callback that returns 2xx, **then** the row is marked delivered and pruned per retention.

### AC-01-25 - inbound is thin: verify → enqueue → <200ms [BE][T]
- **Given** the Meta webhook ingress `POST /omnichannel/webhooks/{channel_id}`, **when** a signed payload arrives, **then** it verifies the HMAC, pushes the raw event onto the internal bus, and returns **200 in <200ms** doing no DB parse synchronously (fast-ACK contract preserved from EMS). An invalid signature → 403; the GET handshake still echoes `hub.challenge` on token match.

### AC-01-26 - backfill cursor endpoint [BE][T]
- **Given** a workspace key, **when** it `GET /api/v1/omnichannel/messages?since=<cursor>&limit=`, **then** it returns messages (in + out) after the cursor in stable order with a next-cursor, so a consumer that missed webhooks can catch up. Tenant+workspace scoped; capped page size (≤200). No consumer WebSocket in v1 (documented).

### AC-01-27 - Redis Streams internal event bus behind an interface [BE][T]
- **Given** the internal event bus, **when** inbound events and outbound-delivery jobs flow, **then** they pass through a **Redis Streams**-backed bus (consumer groups + replay-from-offset, at-least-once) accessed through an `EventBus` interface so Kafka is a later drop-in (NOT built now). Workers drain the stream; a worker crash re-processes un-acked entries (at-least-once, idempotent handlers dedup by external id).
- **Given** `CELERY_TASK_ALWAYS_EAGER=true` (dev/tests), **then** the bus runs inline so no worker/Redis process is needed for tests.

### AC-01-28 - media durable both directions [BE][T]
- **Given** an inbound media message, **when** processed, **then** the bytes are fetched from Meta, stored via StorageService (S3/R2/local), and the outbound webhook carries a **short-lived signed URL** + a **stable `mediaId`**; `GET /api/v1/omnichannel/media/{id}` re-fetches (re-signs) with tenant/workspace scoping.
- **Given** an outbound send with media, **when** the consumer either uploads bytes (`POST /api/v1/omnichannel/media`) or passes a public URL, **then** we push to Meta AND keep a stored copy (durable both ways). Presigned URLs are never immutable-cached.

### AC-01-29 - per-number rate-limit token bucket [BE][T]
- **Given** a channel/number with a Meta tier throughput (~80-1000 msg/s), **when** the worker dispatches sends, **then** a per-number **token-bucket** limiter paces dispatch to stay under the number's cap; excess is queued (not dropped) and drained as tokens refill. The limiter is per `phone_number_id` (keyed off the now-unique column).

---

## Slice 5 - Deploy stack + live number + platform-settings config UI

### AC-01-30 - full Docker Compose stack [BE][T]
- **Given** the repo, **when** `docker compose up`, **then** it brings up **api + worker + beat + postgres + redis + caddy** (adapting the inherited compose; the domain services stripped, worker set = omnichannel + the delivery/bus workers). Each service has a healthcheck; api waits on postgres+redis.

### AC-01-31 - Caddy auto-HTTPS on the configurable domain [BE][T]
- **Given** the Caddy service, **when** deployed, **then** it terminates TLS (auto-HTTPS / ACME) for the configurable domain (default `icp-demo.foundryx.my`) and reverse-proxies the frontend + `/api` + `/omnichannel/webhooks/*` to the backend, setting `X-Forwarded-*` so the auth throttle sees real client IPs. The domain is env-configurable (not hardcoded).

### AC-01-32 - GitHub Actions CI/CD [BE][T]
- **Given** a push to `main` on `github.com/jayson-odoo/foundryx-shared-service`, **when** CI runs, **then** it runs backend pytest + frontend vitest + build, builds images, and (on the deploy job) ships to the Hostinger VPS. A failing test blocks deploy. The workflow is adapted from the inherited `deploy.yml` (not left EMS-branded).

### AC-01-33 - platform-settings config UI (super-admin) [FE][E2E]
- **Given** the Foundryx super-admin (platform tenant), **when** they open Platform Settings, **then** a config surface lets them view/set the **single Foundryx-owned Meta app** creds (App ID/Secret/verify-token - secrets write-only with eye toggles), the default storage bucket/connection, per-number rate-tier defaults, and the public webhook domain. These are **platform-level** (one Meta app service-wide), hidden from tenant callers. Verified 375px AND 1280px.

### AC-01-34 - provisioning runbook: tenant → workspace → number → keys [BE][FE][E2E]
- **Given** the super-admin, **when** they follow the provisioning flow, **then** they can: create a tenant (account) → create a workspace (number-bound) → connect a number (Embedded Signup under the Foundryx Meta app, manual-token fallback) → mint an API key + a webhook signing secret → hand `workspace_id` + `api_key` to the consumer. Each step is a real-click surface.

### AC-01-35 - live number send + receive (go-live smoke) [E2E]
- **Given** a real connected number and a public callback URL, **when** a consumer `POST /api/v1/omnichannel/messages` (text/template) with a valid key, **then** the message is delivered to the recipient's WhatsApp AND appears outbound in the inbox; **when** the recipient replies, **then** the inbound arrives in the inbox live AND the consumer's webhook fires with a valid `X-Fx-Signature`. (May be DEFERRED to a manual runbook step if no live number is available at test time - recorded in the report.)

---

## Cross-cutting / non-functional

### AC-01-36 - structured API error envelope everywhere [BE][T]
- **Given** any public `/api/v1/*` endpoint, **when** it errors, **then** the body is `{error:{code, message, details?}}` with a stable machine-readable `code` (`csw_window_closed`, `unsupported_type`, `service_not_enabled`, `invalid_api_key`, `phone_number_in_use`, `idempotency_replay`…) and the correct HTTP status. Internal inbox endpoints keep their existing shapes.

### AC-01-37 - every query tenant+workspace scoped (isolation) [BE][T]
- **Given** any public or inbox endpoint reached via a workspace key or a user session, **when** it reads/writes, **then** the tenant + workspace come from the auth context (key or JWT) and every repository query is scoped - a key for workspace A can never read/write workspace B's contacts, messages, keys, templates, or subscriptions (cross-tenant isolation test).

### AC-01-38 - responsive + white-label sweep [FE][E2E]
- **Given** every new/changed surface (Services catalog, API-keys list + mint dialog, webhook-subs list, platform settings, inbox), **when** viewed at 375px AND 1280px, **then** no horizontal scroll / clipped controls; no tenant-facing string says "Foundryx"/"EMS"/"App Store"; all dropdowns are `SearchSelect`/`MultiSelect`; truncated text is recoverable (`ClampedText`/`OverflowPills`).
