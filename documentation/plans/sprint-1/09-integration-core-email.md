# 09 — Integration Core & Email (SMTP)

**Sprint:** 1
**Branch:** `sprint-1/integration-core-email`
**Closes:** BL-006 (production mailer provider)
**Depends on:** sprint-1/07 (tenant-core — platform tenant owns the default connection), sprint-1/03 (RBAC), sprint-1/02 (Resource shell)
**Successor:** `sprint-1/10-auth-hardening.md` — consumes the working `EmailService`.

---

## 1. Goal

Two deliverables, deliberately coupled:

1. **Integration framework in core** — the reusable primitives every external-service
   integration (SMTP now; R2, ERP, OpenAI, … later) plugs into: a generic `connections`
   table, a core secrets-encryption helper, a "test connection" contract, and a guided
   connect-wizard shell. The framework is the *shell* (like the Resource shell);
   business integrations ship as separate App Store modules that consume it.
2. **SMTP email, production-grade** — replace the dev console-log `EmailService` with a
   generic SMTP adapter behind a durable **email outbox** (per-connection rate limiting,
   retry/backoff, tenant→platform fallback), branded Jinja2 templates, and a tenant-facing
   `/settings/integrations` page with a guided setup wizard + test-send.

Out of scope (deferred, see §10): email-log UI, user-editable email templates,
API-native mail adapters (Resend/SES REST), multi-connection-per-provider, Redis.

---

## 2. Decision record (from the grill session)

| # | Decision | Choice |
|---|----------|--------|
| D1 | SMTP placement | **Platform core with pluggable adapters** — never an App Store module. Core auth flows (reset/invite/verify) depend on email; governance forbids core→module dependencies. Same status as auth itself. |
| D2 | Integration architecture | **Separate module per business integration, shared core primitives.** Core owns: `connections` table, Fernet secrets helper, test-connection contract, connect-wizard shell. Infra integrations core itself needs (email; later blob storage) = core adapters registered in the same table. |
| D3 | Config scope | **Platform default + per-tenant override.** Platform tenant (plan 07) owns the default connection row (env-seeded at bootstrap — zero-touch on-prem); tenants connect their own SMTP via the wizard. |
| D4 | Adapter | **Generic SMTP** (host/port/user/pass/TLS via `smtplib`) — covers Gmail, SES, Resend, Mailgun SMTP endpoints with one adapter. API-native adapters = BL-046. |
| D5 | Delivery mechanics | **DB outbox + in-process dispatcher loop** — NOT fire-and-forget BackgroundTasks. Lesson learnt: low-spec SMTP servers get overwhelmed at event spikes → per-connection rate limit + durable queue + retry/backoff + fallback chain. Outbox doubles as sent-mail audit. |
| D6 | Fallback chain | tenant connection fails (after retries) → **platform connection** → mark failed. Resolution order per email: recipient-tenant connection → platform connection → dev-log (dev). |
| D7 | Secrets storage | **Split**: `config_json` plain (host/port/from — displayable/queryable) + `credentials_json` Fernet-encrypted (password). New core `FERNET_KEY` + `app/secrets.py` helper; omnichannel migrates onto it later (BL-042). |
| D8 | Uniqueness | **One connection per (tenant, provider)** for MVP. Multi-connection (marketing vs transactional) = BL-043. |
| D9 | Templates | **Jinja2 branded HTML + plain-text fallback** — one Dreamz base layout + invite/reset/verify children. Per-tenant branding + user-editable templates = BL-038 (ties BL-024 template engine). |
| D10 | Tenant UI | **New `/settings/integrations`** card grid + guided wizard (`integration-connect-wizard` shell in `components/platform/`), gated by new `integrations.read/manage` permission keys. Retrofitting omnichannel's channel wizard onto the shell = BL-045. |
| D11 | Counter/queue store | **Postgres, not Redis** — auth/email volume is low-QPS; on-prem stays one-service; outbox *wants* durability. Redis enters the stack when a feature genuinely needs it (BL-022 pub/sub) — BL-040. |

---

## 3. Data model (core `public`, Alembic migration)

### `connections` — generic integration registry

```
connections
  id                     String PK (uuid)
  tenant_id              String FK→tenants.id (indexed)   -- platform tenant row = the platform default
  provider               String                            -- "smtp" now; "r2", "openai", … later
  type                   String                            -- category: "email" | "storage" | "llm" | …
  name                   String                            -- display, e.g. "Acme Mail Server"
  config_json            JSON                              -- non-secret: host, port, security, from_email, from_name
  credentials_json       Text                              -- Fernet-encrypted JSON: {password}
  status                 String                            -- "active" | "error" | "unverified"
  last_tested_at         DateTime NULL (UTC)
  last_error             Text NULL
  rate_limit_per_minute  Int default 30                    -- dispatcher throttle (low-spec SMTP guard)
  created_at / updated_at DateTime (UTC)
  UNIQUE(tenant_id, provider)
```

### `email_outbox` — durable queue + audit

```
email_outbox
  id               String PK (uuid)
  tenant_id        String (indexed)            -- recipient's tenant (drives connection resolution)
  connection_id    String NULL                 -- resolved at send time; NULL until first attempt
  to_email         String
  subject          String
  html_body        Text
  text_body        Text
  template_key     String                      -- "invite" | "password_reset" | "verification" | "test"
  status           String (indexed)            -- "pending" | "sending" | "sent" | "failed"
  attempts         Int default 0
  next_attempt_at  DateTime (UTC, indexed)
  last_error       Text NULL
  used_fallback    Boolean default false
  created_at / sent_at DateTime (UTC)
```

### Core secrets helper

`app/secrets.py`: `encrypt_secret(dict) -> str` / `decrypt_secret(str) -> dict` using new
`FERNET_KEY` setting (same ephemeral-key dev behavior as omnichannel's — stable key required in
prod, runbook note alongside BL-031). Omnichannel keeps `OMNICHANNEL_FERNET_KEY` until BL-042.

---

## 4. Integration framework contract (the "shell")

What core provides, what an integration implements:

- **`IntegrationProvider` protocol** (`app/integrations/base.py`):
  `provider: str`, `type: str`, `config_schema` (Pydantic — drives wizard fields),
  `test_connection(config, credentials) -> TestResult`. Registered in a core
  `provider_registry` (core registers `smtp`; App Store modules register theirs at load).
- **Connections service/repository** (tenant-scoped, Service-Repository layering):
  CRUD + `test(connection_id)` + status upkeep. Credentials write-only over the API
  (never echoed back; PATCH with empty password = keep existing).
- **Frontend wizard shell** `components/platform/integration-connect-wizard/`
  (modeled on `channel-connect-wizard`): stepper **provider → configure → test → done**,
  config-driven fields, inline test feedback. SMTP is the first consumer; modules
  ship their own steps into the same shell later (BL-045 retrofits omnichannel).

### Permissions (core CSV rows — add to `app/permissions/permissions.csv`)

```csv
integrations,Integrations,read,View integrations,Can view configured integrations
integrations,Integrations,manage,Manage integrations,Can connect, edit, test and remove integrations
```

Admin seed re-grant picks these up (existing bootstrap behavior).

---

## 5. EmailService redesign

`app/services/email_service.py` becomes a thin façade that **enqueues**:

- `send_invite/send_password_reset/send_verification(to_email, link, tenant_id)` →
  render Jinja2 template → insert `email_outbox` row (`pending`, `next_attempt_at=now`).
  Callers (`user_service`) pass the recipient's `tenant_id`.
- **Resolution** (at dispatch): recipient-tenant `smtp` connection → platform-tenant
  connection → if neither (or `FERNET_KEY`-less dev) **DevLog adapter** prints the link —
  local dev behavior unchanged, zero config.
- **Templates** `app/templates/email/`: `base.html` (Dreamz logo, orange `#FF5A00`,
  footer) + `invite.html` / `password_reset.html` / `verification.html` + `.txt` siblings.
  Jinja2 added to requirements (FastAPI already ships it transitively; pin explicitly).
- **Test-send** (wizard step): renders a `test` template and sends **inline**
  (bypasses outbox — user is waiting for the result), updating `status`/`last_tested_at`/`last_error`.

### Dispatcher (`app/services/email_dispatcher.py`)

- Asyncio task started in FastAPI lifespan (`main.py`); poll interval ~2s, batch claim via
  `SELECT … FOR UPDATE SKIP LOCKED` → multi-worker safe, no double-send.
- **Per-connection throttle**: respects `rate_limit_per_minute` (sent-count window per
  connection); excess mail stays `pending`.
- **Retry**: exponential backoff (1m → 5m → 25m), `max_attempts=3` per connection.
  Tenant connection exhausted → re-resolve to platform connection (`used_fallback=true`,
  attempts reset once) → exhausted again = `failed` + `last_error`.
- SMTP send via `smtplib` with `security` from config (`starttls` | `ssl` | `none`),
  hard timeout (10s). Connection `status="error"` set on repeated transport failures.
- Housekeeping piggyback: delete `sent` rows older than N days (setting, default 90).

### Settings (`app/config.py` + `.env.example`)

```
FERNET_KEY                      # core secrets key (prod: required, stable)
PLATFORM_SMTP_HOST / PORT / USER / PASSWORD / SECURITY / FROM_EMAIL / FROM_NAME
EMAIL_OUTBOX_RETENTION_DAYS=90
```

`bootstrap_db` upserts the **platform tenant's** `smtp` connection row from these
env vars when set (idempotent; plan 07's platform UI edits the same row later).
Unset = no row = dev-log fallback.

---

## 6. API

All tenant-scoped, `require_permission`:

```
GET    /integrations/providers              available providers + config schemas (integrations.read)
GET    /integrations/connections            current tenant's connections (integrations.read; credentials never returned)
POST   /integrations/connections            create (integrations.manage; encrypts credentials)
PATCH  /integrations/connections/{id}       update (integrations.manage; empty password = keep)
DELETE /integrations/connections/{id}       remove (integrations.manage)
POST   /integrations/connections/{id}/test  inline test-send / test-connection (integrations.manage)
```

Schemas camelCase via `validation_alias`; repository tenant-scoped (platform default
row is **not** visible to tenants — it belongs to the platform tenant).

## 7. Frontend

- **`app/(protected)/settings/integrations/`** — card grid of available integrations
  (SMTP/Email first; future providers appear as modules register). Card states:
  not-connected → "Connect" (wizard) · connected → status badge, host/from summary,
  actions Edit / Test / Disconnect (confirm).
- **Wizard** (`integration-connect-wizard` shell): provider → configure (host, port,
  security, username, password, from email/name, rate limit advanced field) → test
  (default = plain CONNECTION CHECK — connect + authenticate, no recipient; optional
  "send a test email instead" link for a targeted send) → done. Card "Test" = inline
  connection check + toast (no dialog). [Reworked on user feedback during Phase A.]
- Sidebar: "Settings → Integrations" entry in `menu.config.tsx`, gated `integrations.read`.
- Layering: `integration-service.{ts,mock.ts,real.ts}` + `hooks/use-integrations.ts`,
  mock-first per methodology.

---

## 8. Phases (mandatory methodology)

- **Phase A — frontend-first:** integration types, mock service (configurable
  loading/error/success + simulated test-send failure), `/settings/integrations` grid +
  wizard shell + all states, menu gating, Vitest component tests, Playwright real-click
  E2E against mock (navigate via sidebar — no direct URLs).
- **Phase B — backend (TDD, pytest+httpx):** migration (`connections`, `email_outbox`),
  secrets helper, provider registry + SMTP provider, connections service/repo/endpoints,
  EmailService façade + Jinja2 templates, dispatcher (throttle, retry, fallback —
  tested with a fake SMTP transport), bootstrap env-seed, permissions CSV rows.
  Swap mock→real at the service boundary.
- **Phase C — E2E + report:** full stack (login → Settings → Integrations → connect
  SMTP via wizard against a local debug SMTP server (`aiosmtpd`) → test-send arrives →
  trigger user-invite → mail lands via outbox), Test Execution Report per §6.

## 9. Risks / invariants

- **Never log or return credentials**; `credentials_json` write-only over the API.
- Dispatcher must be a no-op crash-wise: any exception logged, loop survives.
- Dev with no `FERNET_KEY`/SMTP env = identical behavior to today (console links).
- Outbox is the only send path for product mail (test-send excepted) — no direct
  `smtplib` calls from services.

## 10. Deferred → backlog

| New ID | Item |
|--------|------|
| BL-038 | Email-template management + per-tenant email branding (user-editable templates; ties BL-024 template engine) |
| BL-040 | Adopt Redis (pub/sub for BL-022, cache, throttle/outbox stores) when scale demands |
| BL-042 | Migrate omnichannel secrets onto core `FERNET_KEY` (re-encryption pass; retires `OMNICHANNEL_FERNET_KEY`) |
| BL-043 | Multiple connections per provider per tenant (e.g. marketing vs transactional SMTP) |
| BL-044 | Email log page — Resource-shell list over `email_outbox`, manual retry, per-tenant view |
| BL-045 | Retrofit omnichannel `channel-connect-wizard` onto the core integration wizard shell |
| BL-046 | API-native mail adapters (Resend REST, SES SDK) in the provider registry |
