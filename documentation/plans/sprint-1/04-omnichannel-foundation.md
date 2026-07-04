# Sprint 1 · Plan 04 — Omnichannel BSP: Foundation (Schema + Channel Onboarding)

**Sprint:** 1
**Branch:** `sprint-1/omnichannel-foundation`
**Source spec:** `documentation/high_level_plan_from_gemini/Whatsapp_BSP_Omnichannel_Functional_Spec.md` (§1, §2)
**Source of truth for UI:** Dreamz design system + the Resource shell (`components/platform/`). Spec mermaid/wireframes are reference only.
**Module:** first real **App Store module** — schema `app_omnichannel`, own `manifest.json`, isolated Alembic history.

> This is one of three plans. **Plan 04 (this)** = module skeleton + *all* schema + channel onboarding. **Plan 05** = message processing (inbound/outbound) + inbox UI + Redis/Celery/WS infra. **Plan 06** = engine integration (deferred to backlog, paper contract only).

---

## 1. Goal

Stand up the omnichannel BSP module's foundation so a tenant admin can **connect a WhatsApp number** and the system has every table the messaging layer (Plan 05) will write to.

Deliver:
- A **module skeleton** under `/omnichannel/` conforming to the governance contract (`manifest.json`, `backend/{routers,services,repositories}`, `backend/permissions/permissions.csv`, `backend/alembic`, `frontend/`).
- The **complete `app_omnichannel` schema** (every table in spec §1, even those Plan 05 operates on) in one Alembic migration tracked in a per-module version table.
- **Channel onboarding via Meta Embedded Signup** end-to-end: "Connect with Facebook" → OAuth code → token exchange → auto-provision a `channels` row → auto-subscribe the webhook → "Connected" state. Plus a **Test Connection** ping.
- The module's **RBAC permission set** declared in CSV and synced.
- A **workspace** entity + auto-created default workspace per tenant, and **workspace membership** scoping.

> **Not in this plan:** receiving/sending messages, the inbox UI, Redis/Celery/WebSocket infra (all Plan 05). Onboarding here is synchronous OAuth and needs no queue.

---

## 2. Architecture decisions (grill outcomes)

| # | Decision | Choice |
|---|----------|--------|
| 1 | **Packaging** | App Store **module**, Postgres schema `app_omnichannel`, manifest + isolated Alembic (`alembic_version_omnichannel`). Cross-schema FK into core `public.users` / `public.tenants` only — never alter core tables. |
| 2 | **Workspace** | Real first-class entity (`app_omnichannel.workspaces`), tenant-owned. Auto-create one **default workspace** per tenant on first module use. `workspace_id` threaded through every module table from day one. |
| 3 | **Status model** | Static **`statuses` lookup table** + `status_id` FKs, seeded with fixed values. **No** state-machine/transition engine (deferred — see Plan 06). |
| 4 | **Workspace RBAC** | Core RBAC `omnichannel.*` keys (via this module's CSV) for *capability*; a thin **`workspace_members`** table (`user_id`, `workspace_id`) for *which workspaces a user can access*. **Drop** spec's `ADMIN/MANAGER/AGENT` enum. |
| 5 | **Channel scope** | **WhatsApp Cloud API only**, behind a `ChannelAdapter` interface so Messenger/IG/Douyin/XHS are later adapters. |
| 6 | **Onboarding** | **Embedded Signup only** — testable now in Meta **Dev Mode** with the owner's app + approved number. No manual paste-token path. |
| 7 | **Secrets** | `channels.credentials_json` **Fernet-encrypted at rest**, key from env/secret (rotatable). |

---

## 3. Module structure (governance contract)

```
omnichannel/
  manifest.json                 # module_name=omnichannel, version, author, required_core_version, entry routers
  backend/
    routers/                    # HTTP only (Pydantic in/out) — no DB, no raw SQL
    services/                   # business logic (ChannelService, OnboardingService, WorkspaceService)
    repositories/               # pure SQLAlchemy, every query workspace+tenant scoped
    permissions/permissions.csv # RBAC declarations (synced by installer / bootstrap)
    adapters/                   # ChannelAdapter interface + whatsapp_cloud.py
    alembic/                    # per-module migrations → alembic_version_omnichannel
  frontend/                     # wraps in Error Boundary; no global CSS, Metronic utilities only
```

`manifest.json` (skeleton):
```json
{
  "module_name": "omnichannel",
  "version": "0.1.0",
  "author": "Dreamz",
  "required_core_version": ">=1.0.0",
  "schema": "app_omnichannel",
  "alembic_version_table": "alembic_version_omnichannel",
  "routers": ["channels", "workspaces", "onboarding"],
  "permissions_csv": "backend/permissions/permissions.csv"
}
```

> **App-Store installer is not built yet (BL-013).** Until it lands, install this module manually: run the module's Alembic upgrade against `app_omnichannel`, and call `PermissionService.sync_permissions("omnichannel", rows)` from a bootstrap hook. Note this explicitly in §9.

---

## 4. Schema — all tables (single module migration, `app_omnichannel`)

> **Allocation decision:** *all* schema lands here (spec §1 is "schema" wholesale), even tables Plan 05 operates on (`contacts`, `conversation_messages`, `contact_channel_identities`). Plan 05 adds **zero** tables. Clean "schema then behavior" boundary.

All tables: `id UUID PK`, **`tenant_id` (FK `public.tenants`)** + **`workspace_id`** where workspace-scoped, `created_at`/`updated_at` **tz-aware UTC** (honor CLAUDE.md datetime rule + BL-012 from the start — `DateTime(timezone=True)`, serialize `Z`). camelCase Pydantic via `Field(validation_alias=...)`.

### 4.1 `statuses` (static lookup) *(decision 3)*
`id, tenant_id, scope (Enum: WORKSPACE|CHANNEL|THREAD), key (e.g. OPEN/SNOOZED/CLOSED, ACTIVE/INACTIVE), label, sort_order, is_terminal (bool)`. Seeded per tenant. THREAD scope seeds `OPEN, SNOOZED, CLOSED`.

### 4.2 `workspaces` *(decision 2)*
`id, tenant_id, name, status_id (→statuses), created_at, updated_at`. One default ("General") auto-created per tenant.

### 4.3 `workspace_members` *(decision 4)*
`id, tenant_id, workspace_id, user_id (→public.users)`. Unique (`workspace_id`,`user_id`). Drives inbox visibility (Plan 05). Capability comes from core RBAC, **not** from this table.

### 4.4 `channels`
`id, tenant_id, workspace_id, channel_type (Enum: WHATSAPP[, ...future]), name, credentials_json (Fernet-encrypted text), waba_id, phone_number_id, display_phone_number, is_active (bool), status_id (→statuses), webhook_verify_token, created_at, updated_at`.

### 4.5 `contacts` (consolidated profile + thread metadata) — *written by Plan 05*
`id, tenant_id, workspace_id, first_name?, last_name?, email?, phone?, avatar_url?, custom_fields_json?, assigned_user_id? (→public.users), status_id (→statuses, THREAD scope), priority (Enum LOW|MEDIUM|HIGH|URGENT), csw_expires_at?, last_incoming_message_at?, last_message_at?, created_at, updated_at`.

### 4.6 `contact_channel_identities` — *written by Plan 05*
`id, tenant_id, contact_id (→contacts), channel_id (→channels), external_user_id, profile_name?, created_at`. Unique (`channel_id`,`external_user_id`).

### 4.7 `conversation_messages` — *written by Plan 05*
`id, tenant_id, contact_id (→contacts), channel_id (→channels), sender_type (Enum AGENT|CONTACT|SYSTEM), sender_id?, message_type (Enum TEXT|IMAGE|AUDIO|VIDEO|DOCUMENT|TEMPLATE|INTERACTIVE), body?, media_url?, external_message_id?, delivery_status (Enum SENT|DELIVERED|READ|FAILED)?, error_code?, error_message?, metadata_json?, created_at`. Index (`contact_id`,`created_at`); unique `external_message_id` (idempotency, Plan 05).

### 4.8 `whatsapp_templates` — *populated by Plan 05 sync*
`id, tenant_id, channel_id (→channels), name, language, category, components_json, status (Meta approval status), synced_at, created_at`.

### 4.9 `quick_replies` — *used by Plan 05*
`id, tenant_id, workspace_id, shortcut, body, created_by (→public.users), created_at, updated_at`.

---

## 5. Channel onboarding — Embedded Signup *(decisions 5, 6)*

### 5.1 One-time Dreamz Meta-app setup (outside code — checklist)
Prerequisite for any Embedded Signup, done once at the Dreamz level (NOT per tenant):
1. Create a Meta Developer App; add **WhatsApp** + **Facebook Login for Business** products.
2. Create an **Embedded Signup configuration**; note the **config_id** + **app_id**.
3. Add yourself as a **tester** (Dev Mode) → the full flow works today with your approved number.
4. (Public launch, later) Business Verification + App Review for `whatsapp_business_management` + `whatsapp_business_messaging` Advanced Access → flips self-serve on for arbitrary tenants. Tracked as a backlog/ops task, **not blocking this plan's code**.

Env: `META_APP_ID`, `META_APP_SECRET`, `META_ES_CONFIG_ID`, `META_GRAPH_VERSION`, `OMNICHANNEL_FERNET_KEY`, `OMNICHANNEL_WEBHOOK_BASE_URL`.

### 5.2 Flow (frontend → backend → Meta)
1. Admin (holds `omnichannel.channels.manage`) opens Workspace Settings → **"Connect with Facebook"**.
2. Frontend loads Meta JS SDK, launches Embedded Signup with `config_id`; tenant logs into FB, picks WABA + phone *inside Meta's popup*, grants permission. SDK returns an **auth code** (+ WABA/phone IDs via the message event).
3. Frontend POSTs the code → `POST /omnichannel/onboarding/oauth-callback`.
4. **`OnboardingService`** (backend):
   - Exchanges code → **permanent system-user access token** (Graph API).
   - Fetches WABA details, phone number ID, display number.
   - Encrypts token + IDs (Fernet) → creates/updates a `channels` row (`is_active=true`, status ACTIVE).
   - **Subscribes the app to the WABA's webhooks** (Graph API `subscribed_apps`) pointed at this module's webhook URL (handler itself = Plan 05).
   - Returns the channel summary → frontend shows green **"Connected Successfully"**.
5. **Test Connection** button → `POST /omnichannel/channels/{id}/test` → lightweight `GET graph.facebook.com/{phone_number_id}` → updates status badge.

### 5.3 `ChannelAdapter` interface *(decision 5)*
```
class ChannelAdapter(Protocol):
    def exchange_code(code) -> CredentialBundle
    def fetch_account_meta(creds) -> ChannelMeta            # waba/phone/display
    def subscribe_webhook(creds, callback_url) -> None
    def test_connection(creds) -> ConnectionStatus
    # send()/parse_inbound()/fetch_media() added in Plan 05
```
`WhatsAppCloudAdapter` implements it. Onboarding/Channel services depend on the interface, resolved per `channel_type`.

---

## 6. RBAC permissions (module CSV) *(decision 4)*

`omnichannel/backend/permissions/permissions.csv`:
```csv
resource,resource_label,action,action_label,description
workspaces,Omnichannel Workspaces,read,View workspaces,Can view omnichannel workspaces
workspaces,Omnichannel Workspaces,manage,Manage workspaces,Can create/edit workspaces & members
channels,Omnichannel Channels,read,View channels,Can view connected channels
channels,Omnichannel Channels,manage,Manage channels,Can connect/disconnect & configure channels
conversations,Conversations,read,View conversations,Can view threads & messages
conversations,Conversations,reply,Reply to conversations,Can send messages
conversations,Conversations,assign,Assign conversations,Can assign/reassign threads
```
> `conversations.*` keys declared now; enforced on the endpoints Plan 05 adds. Implied-read applies (core RBAC normalizes `manage`/`reply`/`assign` ⇒ `read`).

Endpoint gates this plan:

| Endpoint | Gate |
|---|---|
| `GET /omnichannel/workspaces`, `/workspaces/{id}` | `workspaces.read` |
| `POST/PATCH /omnichannel/workspaces`, member add/remove | `workspaces.manage` |
| `GET /omnichannel/channels` | `channels.read` |
| `POST /omnichannel/onboarding/oauth-callback`, `POST /channels/{id}/test`, disconnect | `channels.manage` |
| Webhook receiver (Plan 05) | **public** (Meta-signature-verified, no JWT) |

---

## 7. Frontend (layering: UI → hook → service → api-client)

Reuse: Resource shell for the **Channels list** + **Workspaces list** (clone Users). New shared component built in the library first (component-library discipline): **`<ChannelConnectWizard>`** (Embedded Signup launcher + status states: idle / popup-open / exchanging / connected / failed).

- Routes (under `app/(protected)/omnichannel/`): `settings/channels` (list + connect wizard), `settings/workspaces` (list + members), gated via `<RequirePermission>`.
- Hooks: `useChannels`, `useWorkspaces`, `useConnectChannel`. Services: `channel-service`, `workspace-service`, `onboarding-service`.
- All Embedded Signup SDK interaction lives in the wizard component + `useConnectChannel`; the service boundary swaps mock→real in one line.

---

## 8. Build order — 3 phases

### Phase A — Frontend prototype (mock, no backend)
- Build `<ChannelConnectWizard>` + Channels/Workspaces lists against a **mock service** (mock Embedded Signup result, mock channel/workspace data). Tune all states (idle/connecting/connected/failed, empty/loading/error lists).
- Vitest: wizard state machine, list rendering, permission gating.
- Playwright (against mock): real-click through connect flow → "Connected" state; create workspace + add member.

### Phase B — Backend (wire real, TDD)
- Alembic module migration creates the full `app_omnichannel` schema (§4) in its schema + `alembic_version_omnichannel`.
- Seed `statuses`; auto-create default workspace per tenant; sync `omnichannel` permissions CSV.
- Implement `ChannelAdapter` + `WhatsAppCloudAdapter` (exchange/fetch/subscribe/test), `OnboardingService`, `ChannelService`, `WorkspaceService`, repositories (workspace+tenant scoped). Fernet encryption helper.
- pytest (httpx): oauth-callback happy path (mock Graph API), test-connection, workspace CRUD + membership, perm gating (403s).
- Swap mock→real services on the frontend (one line at the service boundary).
- Playwright re-run against live backend in **Meta Dev Mode** with the real app + approved number.

### Phase C — Review + merge
- Code-review agent (hard-fail rules: no DB in routers, no fetch-in-component, no `any`, no raw CSS, no core-table alteration; **plus** module-governance: tables only in `app_omnichannel`, cross-schema FK only into core).
- Test Execution Report (User Story / Scenario / Steps / Expected / Actual). Merge to `main`.

---

## 9. CLAUDE.md / docs updates required
- Add an **"App Store modules"** note: `omnichannel` is the first real module; schema `app_omnichannel`; manual install until BL-013.
- Document new env vars (§5.1).
- Note Embedded-Signup Dev-Mode-now / App-Review-for-public posture.

## 10. Backlog spawned (add to `backlog.md`)
- **App-Store installer wiring for `omnichannel`** (depends BL-013) — auto-run module migration + `sync_permissions` on install/uninstall.
- **Meta App Review + Business Verification** (ops) — unlock public-tenant Embedded Signup beyond Dev Mode.
- **Additional channel adapters** — Messenger / Instagram / Douyin / Xiaohongshu.
- **Multi-workspace switcher UI** — MVP auto-creates one default workspace; full multi-workspace management later. Pairs with BL-004.
- **Manual channel setup fallback** — paste-token path behind `ProvisioningStrategy`, if ever needed for non-Meta-popup edge cases.
