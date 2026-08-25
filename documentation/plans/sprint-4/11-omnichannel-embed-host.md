# Sprint 4 · Plan 11 (Shared-service host) - Omnichannel Embed Host

**Repo:** `foundryx-shared-service`. **Branch:** `sprint-4/11-omnichannel-embed-host`.
**UAC:** `11-omnichannel-embed-host-acceptance-criteria.md` (the contract; slices below fulfil it).
**Interface:** `11-omnichannel-embed-contract.md` (cross-repo, authoritative - do not diverge without updating the EMS plan too).
**Consumer counterpart:** EMS repo `…/11-omnichannel-embed-widget.md`.

## Why

Let any consumer (EMS first) embed this platform's conversation UI as a chromeless, token-authed iframe, with a federated agent identity so replies/assignments are attributed to the consumer's agents - without those agents having shared-service logins. Build once here; every consumer reuses it. This is the respond.io "embedded inbox" pattern.

## Foundation already in this repo (reuse, don't rebuild)
Workspaces, per-workspace API keys, the public `/api/v1/omnichannel/*` gateway (`api_v1.py` + `api_auth.py`), the protected inbox UI + conversation components (`(protected)/omnichannel/inbox`), WS realtime (`routers/ws.py`), template management. This plan adds a **token-authed embed layer** on top of those exact components + an **external-agent identity**.

## Slices

### Slice 1 - External-agent identity (AC-11H-01/02/03)
- New `external_agent` table in `app_omnichannel`: PK id, `connection_id`, `sub`, `name`, `email`, `avatar_url`, timestamps; **UNIQUE(connection_id, sub)**. (`connection_id` = the consumer link; if consumers aren't first-class rows yet, key on `(workspace_id, issuer)` - but prefer a `consumer`/connection concept so one consumer spans workspaces.)
- Provision-or-load on `/embed/session`. Thread messages + assignments reference `external_agent_id` (add a nullable sender/assignee external-agent column alongside the existing native-user columns; the conversation mapper resolves display name/avatar from whichever is set).
- "Mine"/"Unassigned" filters honor external-agent assignment.

### Slice 2 - `/embed/session` (AC-11H-04..08)
- `POST /embed/session { assertion }` (a new **unauthenticated-but-signed** router, sibling of the consumer-webhook receiver):
  1. Decode header (require HS256); resolve the connection by `iss`; verify signature with its **decrypted `embedSecret`**.
  2. `aud=="omnichannel-embed"`; `exp` unexpired; `iat` skew ≤60s.
  3. `jti` single-use ledger (`embed_jti` table or reuse a generic nonce store), retained ≥ TTL → else `401 replayed`.
  4. `Origin` ∈ connection `allowedOrigins` → else `origin_not_allowed`.
  5. Provision/load the external agent (Slice 1).
  6. Mint an **access token** (JWT or opaque) embedding `workspaceId`, `scope`, `caps`, `external_agent_id`, ~15 min; return the contract §3 body. **No cookie.**
- Rides the platform throttle (AC-11H-08).

### Slice 3 - Access-token authorization (AC-11H-09/10/11)
- A new auth dependency `embed_principal` accepted **alongside** the existing API-key + session auth on the omnichannel conversation API + WS: `Authorization: Bearer <accessToken>` → resolve the embed principal (external agent, workspace, scope, caps).
- **Enforce scope**: a `thread:<contactId>` principal is authorized only for that contact's read/act endpoints; workspace-list / other-contact → `403`. `inbox` principal → whole workspace.
- **Enforce caps** on every mutating endpoint (reply/assign/close/note/template) → `403` when the cap is absent. Backend is the boundary; never trust the widget.

### Slice 4 - Chromeless embed routes (AC-11H-12..17)
- Frontend: `app/embed/omnichannel/thread/page.tsx` + `.../inbox/page.tsx` - **outside** the `(protected)` group (no auth layout, no sidebar/header). Each renders the SAME conversation/inbox components used by the protected inbox, wrapped in an embed shell that:
  - boots bare, posts `ready`, waits for `init` (validate `event.origin` ∈ assertion `allowedOrigins`), exchanges the assertion at `/embed/session`, holds the access token in memory, calls the API/WS with it.
  - applies `theme`/`colorScheme` as CSS vars (live on later `theme`); posts `resize` (inbox) + coarse `activity` on send/receive/assign.
  - refreshes via `needToken`→`token` before expiry.
- Backend: the embed route responses carry `Content-Security-Policy: frame-ancestors <connection.allowedOrigins>` (AC-11H-15).
- Rich types render via the existing components (AC-11H-16); responsive 375+1280 (AC-11H-17).

### Slice 5 - Connection embed fields (AC-11H-18)
- Recognize `embedSecret` (write-only, Fernet) + `allowedOrigins` on the workspace/connection config used by `/embed/session` + the embed routes. Rotating `embedSecret` invalidates outstanding assertions (they fail signature).

### Slice 6 - WABA management relocation (AC-11H-19)
- Absorb WABA configuration + business profile + template management here (its own settings UI in the protected app, embeddable later). EMS drops its copies. The public `GET /templates` still serves consumers for automation sends. (May be split into its own sub-plan if scope warrants.)

## Layering / rules (this repo's CLAUDE.md)
- Router→Service→Repository; module lives in `app_omnichannel` schema; per-module Alembic; new permissions via the module CSV (grep core for key collisions first). Every query workspace/tenant-scoped. `render_as_batch`/`UTCDateTime` conventions.
- The embed frontend reuses inbox components - no parallel renderer (component-library discipline).

## Testing (TDD)
- **Backend:** `/embed/session` verify matrix (bad sig/expired/future-iat/wrong-aud/replay/origin), external-agent upsert + cross-consumer isolation, scope enforcement (thread token can't widen), caps enforcement (read_only 403 on writes), throttle.
- **Frontend:** embed shell handshake (ready→init→session→paint), origin rejection, theme apply, needToken refresh.
- **E2E (AC-11H-21):** a test parent posts a signed assertion + correct origin, mounts `/embed/omnichannel/thread`, renders + replies (attributed), a read_only token is refused, a wrong-origin embed is blocked.

## Definition of Done (AC-11H-20)
No unswapped mock; external_agent is a real provisioned identity; scope/caps/origin enforced **server-side** (a test bypassing the widget still 403s); no regression to the protected inbox or the public gateway; verified with a real consumer embed at 375+1280 on a rebuilt frontend.

## Sequencing
Slices 1-3 (identity + session + authz) unblock the EMS consumer's backend; Slice 4 (embed routes) unblocks the EMS widget mount. Ship 1-4 first; 5 is small; 6 (WABA) can trail as a sub-plan. Coordinate the contract file with the EMS repo - any interface change updates both.
