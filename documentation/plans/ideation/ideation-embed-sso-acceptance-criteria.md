# Ideation Embed SSO — Acceptance Criteria (UAC)

**Status:** contract, pre-build. Written FIRST per PRINCIPLES (UAC → plan → build).
**Scope:** cross-repo — sorento (`sorento_crm`) + shared-service (`foundryx-shared-service`).
**Goal:** a logged-in sorento user opens **Ideas → Detail** (and the board) and sees the
shared-service Ideas UI rendered **inside sorento via an iframe**, authenticated by SSO — no
second login. Today it errors "Couldn't open the Ideas workspace / couldn't start a secure session"
because the embed framework was deferred and the config lives in `.env` (blank on prod).

**Two hard requirements from the user (2026-07-20):**
1. **NO `.env` for embed config.** All embed settings are **DB-driven and configurable from the
   frontend** (mirror the turn-endpoint workspace config already shipped).
2. **Real iframe both sides:** shared-service **provides** the iframe page + SSO; sorento **renders** it.

Current state (verified on prod 2026-07-20): sorento host side built (`IdeationEmbed`,
`useIdeationEmbedSession`, `ideation_embed_service.create_embed_session`,
`POST /api/v1/integrations/ideation_embed/*`). Shared-service `POST /be/embed/session` route
exists (returns 422 to an empty body) but the **connection verification + the `/embed/ideas` FE
page are not built**, and sorento's embed config reads blank `.env` settings → mint is dormant.

---

## A. Config is DB-driven + FE-configurable (Requirement 1)

**AC-E-1** — Embed config lives on the `RespondWorkspace` row (same row as the turn-endpoint
config), NOT in `.env`: `ideation_embed_connection_id` (plain), `ideation_embed_signing_secret`
(Fernet-encrypted at rest, column `..._ciphertext`), `ideation_embed_fe_base_url` (the FE root for
the iframe page). `ideation_shared_service_url` (existing) is reused as the **backend** base for
`POST /embed/session`.
- **Given** the Respond Workspaces admin modal, **when** an admin edits the default workspace,
  **then** all embed fields are present + editable in the Ideation section; the signing secret
  input is write-only (shows `••••` masked when set, blank keeps current) — never returned plaintext.

**AC-E-2** — `ideation_embed_service.create_embed_session` resolves config **DB-first** from the
default `RespondWorkspace` (decrypting the secret); `.env` is a last-resort fallback only.
- **Given** the three embed fields are set on the workspace, **when** a user opens Ideas,
  **then** the mint uses the DB values (no `.env` needed).

**AC-E-3** — URL split fixed: the backend `POST /embed/session` uses `ideation_shared_service_url`
(`…/be`); the iframe `iframe_url` uses `ideation_embed_fe_base_url` (FE root). One value never
serves both.

**AC-E-4** — Dormant-safe: when any required embed field is blank, the mint raises
`IdeationEmbedNotConfigured` → the router returns a clean 4xx (never 500); the FE shows a
configuration-needed state, not a crash.

## B. SSO handshake (Requirement 2 — shared-service verifies)

**AC-E-5** — Shared-service has an **embed-connection registry** (DB, admin-configurable): each
connection = `{connection_id, signing_secret, allowed tenant/product, allowed origins}`.
- **Given** a connection registered with the SAME `connection_id` + `signing_secret` sorento holds,
  **when** sorento POSTs a signed assertion to `/embed/session`, **then** shared-service verifies
  the assertion signature + audience (`ideation-embed`) + expiry against that connection and mints
  a short-lived **embed token** (`typ="embed"`, scoped to the connection's tenant).

**AC-E-6** — A tampered / expired / wrong-secret assertion is rejected with 401/403 (never mints a
token); the failure is logged WITHOUT the assertion/secret/token.

**AC-E-7** — The embed token is short-lived (≤ a few minutes), single-audience, and carries the
tenant scope; it is NOT the app JWT.

## C. Iframe page (Requirement 2 — shared-service provides, sorento renders)

**AC-E-8** — Shared-service serves `GET {fe_base}/embed/ideas` and `…/embed/ideas/{id}` — a
**chrome-less** Ideas board / detail (no shared-service nav/shell), sized for embedding.
- **Given** a valid embed token, **when** the page loads, **then** it validates the token, resolves
  the tenant from it, and renders the board/detail for that tenant only (no cross-tenant leak).

**AC-E-9** — An invalid/absent/expired token on the embed page renders a clean "session expired —
refresh" state, never the full app and never another tenant's data.

**AC-E-10** — Sorento's `IdeationEmbed` iframes `iframe_url` and supplies the token per the embed
contract; the iframe is `sandbox`-scoped; the token travels in the URL **fragment** (`#token=`),
not a query param (keep it out of logs/Referer).

**AC-E-11** — End-to-end: a logged-in sorento user clicks **Ideas** (and **Ideas → a row →
Detail**) → the shared-service board/detail renders inside sorento, no second login, correct
tenant, **within the retry-free happy path**. Clicking into an idea in the embed navigates within
the iframe.

## D. Security / non-regression

**AC-E-12** — The signing secret is never in logs, API responses (masked only), or the client
bundle. The iframe origin is allow-listed by the connection.
**AC-E-13** — The feature is additive: with embed unconfigured, the rest of sorento + shared-service
are unaffected (Ideas page shows the config/retry state; nothing else changes).
**AC-E-14** — No `.env`-only path remains required: a fresh deployment can enable the embed entirely
through the FE admin + shared-service connection admin.

---

## Test report keys back to AC-E-1 … AC-E-14 (PASS/FAIL/DEFERRED), authored in Phase 2.
