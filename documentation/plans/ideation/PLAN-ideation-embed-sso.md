# PLAN — Ideation Embed SSO (iframe, DB-configurable)

**Status:** plan, pre-build. Fulfils `ideation-embed-sso-acceptance-criteria.md`.
**Classification:** MODULE extension (ideation) on both sides; config on core `RespondWorkspace`
(sorento) + a new embed-connection table (shared-service, `app_ideation` schema).
**Cross-repo:** sorento_crm (host + config) + foundryx-shared-service (SSO verify + iframe page).
**Owner note:** build in a FRESH focused session — this design is the handoff. Follow
grill→UAC→(this plan)→three-phase. UAC ids AC-E-1…14.

## Why / current state
Deferred embed framework. Sorento host side already built (`ideation_embed_service.py`,
`useIdeationEmbedSession.ts`, `IdeationEmbed.tsx`, `POST /api/v1/integrations/ideation_embed/*`).
Shared-service `POST /be/embed/session` route exists (422 to empty body) but no connection
verification and no `/embed/ideas` FE page; sorento config reads blank `.env`. Fix = DB config
(Req 1) + complete the SSO handshake + build the iframe page (Req 2). See UAC "Current state".

## The flow (target)
```
sorento user opens /ideas/{id}
 → FE useIdeationEmbedSession → POST /api/v1/integrations/ideation_embed/session {idea_id?}
 → sorento create_embed_session: read embed config from DEFAULT RespondWorkspace (DB, decrypt secret)
     → mint signed assertion (embed signing secret, aud "ideation-embed", connection_id)
     → POST {ideation_shared_service_url = …/be}/embed/session {connection_id, assertion, idea_id?}
 → shared-service /embed/session: look up connection by connection_id (DB registry), verify
     assertion sig+aud+exp against its secret → mint short-lived embed token (typ=embed, tenant-scoped)
 ← {token, expires_at}
 → sorento returns {iframe_url = {ideation_embed_fe_base_url}/embed/ideas[/{id}], token, expires_at}
 → IdeationEmbed iframes iframe_url#token=<token> (fragment, sandboxed)
 → shared-service /embed/ideas page: validate token → render chrome-less board/detail for that tenant
```

## Phase 1 — FE prototype (both sides, mocks)
- Sorento: the Ideas detail already renders `IdeationEmbed`; add the config fields to the admin modal
  as disabled mocks first; stub `create_embed_session` to return a fake `{iframe_url, token}` and
  point the iframe at a static shared-service `/embed/ideas` placeholder page to nail sizing/chrome.
- Shared-service: build `/embed/ideas` as a chrome-less route rendering the existing Ideas board
  component with mock data + a token-gate placeholder.
- Verify layout/states (loading, expired-token, not-configured) via Playwright MCP. No backend wiring.

## Phase 2 — Backend wiring, test-first

### Sorento (config → DB, AC-E-1..4)
1. **Migration** (chain onto current head): add to `respond_workspaces`
   `ideation_embed_connection_id VARCHAR(128)`, `ideation_embed_signing_secret_ciphertext TEXT`,
   `ideation_embed_fe_base_url VARCHAR(512)` (all nullable). Idempotent (`ADD COLUMN IF NOT EXISTS`).
2. **Model/schema/service** (`app/models/respond_workspace.py`, `app/schemas/respond_workspace.py`,
   `app/services/respond_workspace_service.py`): add the fields; encrypt the secret on write
   (`encrypt_secret`), mask on read (`_mask_optional_key`), add `decrypt_ideation_embed_secret(row)`
   — copy the `decrypt_ideation_api_key` pattern exactly.
3. **`ideation_embed_service.py`**: add `_resolve_embed_config(db)` reading the default
   `RespondWorkspace` (base_url, fe_base_url, connection_id, decrypted secret), `.env` per-field
   fallback (like `_resolve_ideation_config` in `ideation_turn_service.py`). `create_embed_session`
   takes `db`, uses the resolved config; `iframe_url` built from `fe_base_url` (AC-E-3);
   `mint_embed_assertion` takes the resolved secret+connection_id (not settings). Dormant → 4xx.
4. **Router** (`app/api/v1/integrations/ideation_embed.py`): pass `db`; add the module guard for
   consistency (review finding). Keep the graceful 4xx/502 mapping (AC-E-4).
5. **Admin FE** (`RespondWorkspacesAdmin.tsx` + `respondWorkspaceService.ts`): add the 3 embed fields
   to the Ideation section (connection id text; signing secret password/write-only masked; FE base
   URL text). Reuse the existing masked-key pattern.
6. Tests (pytest): config resolution DB-first + `.env` fallback + dormant; assertion minted with DB
   secret; secret never returned plaintext. (vitest): admin fields render + mask.

### Shared-service (SSO + iframe, AC-E-5..9)
7. **Embed-connection registry** — new table `app_ideation.embed_connections`
   `{id/connection_id, tenant_id, signing_secret_ciphertext, allowed_origins[], product_id?, is_active}`.
   Seed via module install + admin CRUD (App Store / a small admin page). Secret encrypted.
8. **`POST /embed/session`**: look up connection by `connection_id`; verify the assertion
   (signature against the connection secret, `aud="ideation-embed"`, `exp`, `iss="sorento"`); on
   success mint a short-lived embed token (`typ=embed`, `tenant_id` from the connection, `exp` ≤ few
   min); 401/403 on any verification failure (AC-E-6/7). Never log secrets.
9. **`GET /embed/ideas` + `/embed/ideas/{id}` FE page** — a chrome-less route (no shell/nav) that
   reads the token from the URL fragment, validates it (calls a `/embed/validate` or verifies
   locally), resolves tenant, and renders the existing Ideas board/detail components scoped to that
   tenant. Invalid/expired → "session expired, refresh" (AC-E-8/9). Serve at the FE root so
   `ideation_embed_fe_base_url` points there.
10. Tests (pytest): connection verify happy + tamper/expired/wrong-secret rejected; token tenant
    scope; cross-tenant denied. (vitest/playwright): embed page renders with a valid token, expired
    state, no cross-tenant leak.

### Wire-up (AC-E-10..11)
11. `IdeationEmbed.tsx`: token in fragment (`#token=`) not query; `sandbox` attribute; loosen
    `expires_at` type to `string | null` (review nit). Verify end-to-end via Playwright MCP:
    sorento login → Ideas → Detail → shared-service board renders in-iframe, correct tenant, no
    second login; click-through inside the iframe.

## Phase 3 — Review + gated deploy
- `/code-review` per repo. Deploy shared-service first (SSO + page), then sorento (config + wiring),
  per the blue/green flow already used. Then set the config from the FE admin (connection on
  shared-service with matching secret + connection_id; the 3 fields on the sorento workspace).

## Config values to set post-deploy (from the FE, per Req 1 — no .env)
- Shared-service admin: create an embed connection → note `connection_id` + `signing_secret`,
  allowed origin = `https://fe-sorento.foundryx.my`.
- Sorento Respond Workspaces (default): `ideation_shared_service_url = https://chat.foundryx.my/be`
  (backend, existing), `ideation_embed_fe_base_url = https://chat.foundryx.my` (FE root),
  `ideation_embed_connection_id` + `ideation_embed_signing_secret` = the connection's values.

## Risks / notes
- **URL split is the #1 gotcha** — one host serves FE at root + backend under `/be` (Caddy). Keep
  backend-base and fe-base as separate config values (AC-E-3); don't collapse them.
- Token in fragment (not query) + sandboxed iframe + allow-listed origin (AC-E-10/12).
- `module tables via create_all` on shared-service — new `embed_connections` needs the migration to
  actually run OR a manual `CREATE TABLE`/seed (see the deploy lesson: stamp-path can skip module
  migrations; verify on prod, like pg_trgm + idea statuses this session).
- Additive + dormant-safe (AC-E-13): nothing else changes until configured.
