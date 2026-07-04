# HANDOFF — FoundryX Shared Service Platform

> You are Claude Code working in `~/Documents/foundryx/foundryx-shared-service`. This repo was just forked+stripped from the Dreamz EMS codebase in another session. This doc is your full context. Read `PRINCIPLES.md` (governs) + `CLAUDE.md` (deep reference) after this.

## What this product is

A **central, multi-tenant shared-service platform** FoundryX hosts. Each installable module = a **Service**. **Service #1 = omnichannel** (WhatsApp-as-a-service, a respond.io replacement). Future **Service #2 = LLM**. Goal: bypass respond.io and use FoundryX's own approved/published Meta app to send/receive WhatsApp, exposing a public gateway API + webhooks that consumer apps (EcoHub, Sorento, Fujiaire, EMS) integrate against with an **API key + workspace_id**.

It is a duplicate-and-strip from EMS. The whole EMS platform backbone (auth, RBAC, multi-tenant, module platform, all core engines, StorageService, Fernet, omnichannel) is KEPT. Only the EMS *domain* (events/CRM/finance/portal/reviews) was stripped.

## Repo state (already done — do NOT redo)

- Local: `~/Documents/foundryx/foundryx-shared-service`. Remote: `github.com/jayson-odoo/foundryx-shared-service`. Branch `main`.
- Commits: `05bb11f` EMS baseline import → `30d0dbd` **S1: strip + rename** (pushed).
- **Dirs renamed:** `service_backend/` + `service_frontend/` (were dreamz_ems_*). Python package roots stay `app` / `modules` (generic — unchanged).
- **Full brand scrub done:** ZERO `dreamz` anywhere. DB role/name = `foundryx` / `foundryx_service`. CSS = `service_frontend/css/foundryx-tokens.css`. Brand copy = FoundryX. Demo `@example.com` emails intentionally left.
- **Stripped:** backend `modules/{crm,ems,finance}`; frontend routes `app/(protected)/{ems,finance,network,public-profile,reviews,store-admin,store-client}` + `app/(portal)`; 15 EMS test files; `scripts/seed_slice3_scenario.py`. Kept omnichannel + all engine UIs (forms/imports/workflows/documents/settings/user-management/app-store/omnichannel/platform/account/auth).
- **App Store → "Services"** relabel (user-facing strings + menu; route/component names unchanged).
- **Docs rebranded:** CLAUDE.md, PRINCIPLES.md, DEPLOY.md, per-dir CLAUDE.md — a "## What this is (shared-service fork)" section prepended.
- **Boot verified:** `import app.main` OK, 321 routes, only omnichannel module discovered. Frontend NOT built yet (node_modules absent).
- **UAC + plan + backlog exist:** `documentation/plans/sprint-1/01-shared-service-platform-omnichannel-acceptance-criteria.md` (38 ACs `AC-01-01..38`), `...01-shared-service-platform-omnichannel.md` (plan, slices S1–S5), `documentation/backlogs/backlog.md` (`BL-SS-001..007`). **READ THESE — they are the contract.**

## Locked design decisions (grilled + final — do NOT relitigate)

- **Tenancy:** tenant=account(billing) → workspace(number-bound) → channel(WABA/phone). **API key per workspace.** Consumer configures `workspace_id` + `api_key` (respond.io Channel-ID style).
- **Shape:** BOTH headless gateway API AND full platform (durable store + agent inbox showing every in/out message). Tenants get their own inbox login + agents.
- **API key:** `Authorization: Bearer fxw_live_...`; store SHA-256 hash + 8-char lookup prefix (never plaintext; shown once at mint); live-only; no scopes; multiple active keys/workspace (rotation). New table `workspace_api_keys(id, tenant_id, workspace_id, name, key_prefix, key_hash, last_used_at, revoked_at, created_by, created_at)`.
- **Send API:** `POST /api/v1/omnichannel/messages` — workspace from key, async **202** + our message id, `Idempotency-Key` header (Redis dedup 24h), types text+template+media (interactive deferred), CSW 24h enforced (free-form in-window else approved-template-only → 409 `csw_window_closed`), structured errors `{error:{code,message,details}}`. Every send also lands in the platform inbox as outbound.
- **Receive:** **outbound webhooks** per workspace — consumer registers callback URL; on inbound msg / status receipt we POST HMAC-signed (`X-Fx-Signature` = HMAC-SHA256 body w/ workspace signing secret) with retry+backoff+dead-letter (durable outbox, mirror the email-dispatcher pattern). Backfill via `GET /api/v1/omnichannel/messages?since=<cursor>`. NO consumer WebSocket v1. Redis pub/sub stays internal-only for the built-in inbox realtime. New table `webhook_subscriptions(workspace_id, callback_url, signing_secret, events[], is_active)`.
- **Media:** reuse `StorageService` (S3/R2), durable both directions. Inbound: fetch from Meta → store → webhook carries short-lived signed URL + stable `mediaId`; `GET /api/v1/omnichannel/media/{id}` re-fetch. Outbound: consumer uploads bytes (store + push to Meta) OR passes a public URL; keep a stored copy. Do NOT hard-bind GCS (design doc said GCS; overruled).
- **Provisioning:** FoundryX-operated v1 — super-admin: create tenant → workspace → connect number (Embedded Signup under FoundryX's ONE Meta app; manual token fallback) → mint api key + signing secret → hand over. Reuse the existing platform-operator/tenant-provisioning console.
- **Templates:** authored in platform UI (already built); `GET /api/v1/omnichannel/templates` read-only via API; send via the messages API.
- **Scale (build lean, scale-ready seams — do NOT build Kafka):** stateless API replicas + independent worker pool; per-number rate-limit token bucket (respect Meta ~80–1000/s/number tier); dedup + idempotency in Redis; **Redis Streams** durable internal event bus (consumer groups + replay-from-offset, at-least-once) behind an interface so Kafka is a later drop-in. Webhook ingress = thin (verify HMAC → push to Redis → 200 in <200ms; workers drain). Send API = validate → enqueue → 202. Reason: Meta per-number caps mean you never reach Kafka scale; even Discord doesn't Kafka its message path.
- **Constraint:** `channels.phone_number_id` must be **UNIQUE service-wide** (O(1) inbound routing). Currently nullable/non-unique → S3 must add a duplicate-reconcile migration (DoD backfill gate).
- **API namespacing:** public API `/api/v1/{service}/...`; key bound to workspace→service; cross-service key misuse rejected. Meta creds + bucket + domain = platform-level super-admin config UI (Meta app is ONE, FoundryX-owned).
- **LLM (future):** sibling module, own API/webhooks, consumes the message stream + calls the send API. No scaffolding now beyond clean seams.
- **EMS:** stays native for now (phased approach A). Ignore EMS migration. End-state (later): the central service owns ALL WhatsApp traffic (one number's webhook → one callback URL), EMS becomes a consumer.

## Deploy

- Repo pushed. Hostinger VPS. **`docker-compose.yml` + `.github/workflows/deploy.yml` ALREADY EXIST** (blue/green + `worker_omni` + beat + redis + Caddy referenced in comments) → S5 = *adapt Caddy into compose + reconcile*, NOT build-from-zero.
- Domain `icp-demo.foundryx.my` (configurable). Frontend behind Caddy on the VPS. User HAS Meta app creds + an S3/R2 bucket ready; these must be configurable via a platform-settings UI.
- `.env.example` present (already scrubbed to foundryx). No `.env` in repo — user provisions secrets (`DATABASE_URL`, `JWT_SECRET`, `FERNET_KEY`, Meta `META_*`, `REDIS_URL`, storage creds).
- Minor: `IMAGE_REPO` still `foundryx-ems` in compose/.env.example — rename to `foundryx-service` when convenient.

## Slices

- **S1 — DONE** (strip + rename + Services relabel + docs + UAC/plan).
- **S2** — verify omnichannel + inbox + CSW work end-to-end inside the stripped shell (frontend build + backend run + seed).
- **S3** — `workspace_api_keys` (SHA-256 + prefix, one-time reveal, `get_api_workspace` Bearer dependency, service-binding reject) + public `POST /api/v1/omnichannel/messages` (202 + our id, `Idempotency-Key` Redis dedup, reuse existing CSW/send logic) + **`phone_number_id` UNIQUE migration with duplicate-reconcile**.
- **S4** — `webhook_subscriptions` + durable signed-delivery outbox (`X-Fx-Signature`, retry→dead-letter) + `GET .../messages?since=` backfill + Redis-Streams `EventBus` behind an interface + per-number token bucket.
- **S5** — full Compose+Caddy+CI + platform-settings super-admin config UI + provisioning runbook + connect a live number.

## Immediate TODO (start here)

1. **Frontend build verify** — `cd service_frontend && npm install --force && npm run build`. NOT run yet since the strip; expect to fix leftover imports.
2. **Orphan cleanup** (coder flagged, dead-but-compiling EMS residue — safe to delete, ~50+ interdependent files): the portal layer (`providers/portal-*`, `hooks/use-portal-*`, `lib/portal-*`, `services/portal-*`, `types/portal-*`, `components/platform/portal-invite-button*`, `app/api/portal-auth/`), review surfaces (`components/platform/review/`, `hooks/use-*review*`, `services/*review*`/`staff-review*`), and EMS/finance/CRM service files (`event-billing-service`, `checkout-service`, `persona-service`, `profile-preferences-service`, `ems-service.*`, etc.). NOTE `components/.../review` may include a generic core `review-engine` — keep core, drop EMS-specific. Also clean dead demo menu arrays `MENU_SIDEBAR_CUSTOM/COMPACT/ROOT` in `config/menu.config.tsx` (feed non-active demo2/3/6/10 layouts, point at deleted routes).
3. Then build **S3** (the actual respond.io-bypass core: API-key auth + public send API). This is the highest-value next feature.

## Working rules (from PRINCIPLES.md / CLAUDE.md — still apply)

Service→Repository backend layering (no DB/raw-SQL in routers). Frontend: UI→hook→service→api-client (no fetch in components). No `any`. Every query tenant-scoped. `UTCDateTime` columns only. New permission = CSV row + `tenant_admin_grant` re-run for existing tenants. New column on existing entity = backfill migration. Alembic revision id ≤32 chars. Reuse the Resource shell + existing components — don't hand-roll. Follow the methodology: **UAC-first, then plan, then frontend-first (mock), then backend, then TDD, then Playwright E2E real-clicks, then code review before merge.** Verify at 375px AND 1280px. Branch `sprint-<N>/<feature>`, merge to main only after review.

Local dev ports (from EMS convention, adjust as needed): backend `uvicorn app.main:app --reload --port 8001`, frontend `npm run dev` (3001). Postgres role/db now `foundryx`/`foundryx_service`. Redis native. `CELERY_TASK_ALWAYS_EAGER=true` for inline tasks in dev.
