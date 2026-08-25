# Sprint 4 · Plan 11 (Shared-service host) - Acceptance Criteria: Omnichannel Embed Host

Contract the **shared-service side** must satisfy so a consumer (EMS) can embed the conversation UI. Grouped by slice; each AC tagged `[BE]`/`[FE]`/`[E2E]`/`[T]`. QA report keys back to these ids.

References: the cross-repo interface `11-omnichannel-embed-contract.md` (authoritative); the consumer plan lives in the EMS repo (`dreamz_ems …/11-omnichannel-embed-widget.md`).

Foundation already present in this repo: workspaces, per-workspace API keys, the public `/api/v1/omnichannel/*` gateway, the protected inbox UI + conversation components, WS realtime. This plan adds a **token-authed, chromeless embed layer** reusing those components + an **external-agent identity** for federated attribution.

---

## Slice 1 - External-agent identity (federated attribution)

### AC-11H-01 - external_agent provisioning [BE][T]
- **Given** a verified embed assertion, **when** exchanged at `/embed/session`, **then** the shared service **upserts an `external_agent` record keyed by `(connection_id, sub)`** with `name/email/avatar_url` from the claims - no password, no login, provisioned on first use, updated on later assertions.

### AC-11H-02 - attribution on replies + assignment [BE][T]
- **Given** an embed agent, **when** they reply or a thread is assigned, **then** the message/assignment records the `external_agent` id + display name; the conversation and any list ("Mine"/"Unassigned") reflect that identity, distinct from native shared-service users.

### AC-11H-03 - cross-consumer isolation of identity [BE][T]
- **Given** two consumers whose agents share a `sub` value (e.g. both "u-1"), **when** both embed, **then** `(connection_id, sub)` keeps them distinct - Consumer A's agent can never appear as / act as Consumer B's.

---

## Slice 2 - `/embed/session` (assertion → access token)

### AC-11H-04 - verify + exchange [BE][T]
- **Given** `POST /embed/session { assertion }`, **when** the assertion is valid, **then** the shared service verifies **HS256 against the connection's `embedSecret`** (resolved by `iss`), checks `aud="omnichannel-embed"`, `exp` unexpired, `iat` skew ≤60s, and returns `{ accessToken, expiresIn, agent, workspace, scope, caps }` per the contract. **No cookie is set.**

### AC-11H-05 - single-use jti [BE][T]
- **Given** a replayed assertion (same `jti`), **when** re-posted, **then** the second call returns `401 replayed`; the jti ledger is retained ≥ the token TTL.

### AC-11H-06 - malformed / expired / wrong-aud rejected [BE][T]
- **Given** a tampered signature, an expired `exp`, a future `iat`, or `aud≠omnichannel-embed`, **when** posted, **then** each is rejected with the typed error (`invalid_assertion`/`expired`), nothing provisioned.

### AC-11H-07 - origin allow-list [BE][T]
- **Given** the request `Origin` header, **when** it is not in the connection's `allowedOrigins`, **then** `/embed/session` returns `origin_not_allowed`.

### AC-11H-08 - throttled [BE][T]
- **Given** the endpoint, **when** hammered, **then** it rides the platform throttle (per-connection/IP), returning `429 + Retry-After` over the limit.

---

## Slice 3 - Access-token authorization (scope + caps enforced)

### AC-11H-09 - Bearer accepted on omnichannel API + WS [BE][T]
- **Given** an access token from `/embed/session`, **when** the widget calls the omnichannel API or opens the WS with `Authorization: Bearer <accessToken>`, **then** the request authenticates as the external agent in the token's workspace - no session cookie required.

### AC-11H-10 - scope enforced server-side [BE][T]
- **Given** a `thread:<contactId>` token, **when** it requests any other contact's thread or the workspace inbox list, **then** the shared service returns `403` - the token cannot widen beyond its contact. An `inbox` token may list/read the whole workspace.

### AC-11H-11 - caps enforced server-side [BE][T]
- **Given** a `read_only` (or cap-missing) token, **when** it attempts reply/assign/close/note/template, **then** the shared service returns `403` regardless of what the widget UI shows - the backend is the boundary.

---

## Slice 4 - Chromeless embed routes (reuse inbox components)

### AC-11H-12 - thread + inbox embed routes [FE][E2E]
- **Given** `/embed/omnichannel/thread` and `/embed/omnichannel/inbox`, **when** loaded, **then** each renders the **existing conversation/inbox React components** with **no app shell** (no sidebar/header), no login redirect, and boots bare - obtaining the assertion via the postMessage handshake, never from the URL.

### AC-11H-13 - postMessage handshake [FE][E2E]
- **Given** an embedded page, **when** it mounts, **then** it posts `ready`, accepts `init { assertion, theme, colorScheme }` (validating `event.origin` ∈ the assertion's `allowedOrigins`), exchanges the assertion at `/embed/session`, and paints the conversation; it posts `needToken` before token expiry and accepts `token`.

### AC-11H-14 - live theming + resize + activity [FE][E2E]
- **Given** an `init`/`theme` message, **when** received, **then** the widget applies the brand tokens + colorScheme as CSS vars (live on later `theme`); **and** posts `resize { height }` (inbox mode) and a coarse `activity { kind, contactId }` on send/receive/assign. No message content crosses the boundary in `activity`.

### AC-11H-15 - frame-ancestors clickjacking guard [BE][E2E]
- **Given** the embed routes, **when** served, **then** the response carries `Content-Security-Policy: frame-ancestors <connection.allowedOrigins>`; embedding from a non-allowed origin is blocked by the browser.

### AC-11H-16 - rich message parity in the widget [FE][E2E]
- **Given** the embed thread pane, **when** rendering, **then** it shows the full rich set the protected inbox already renders (text, media, location, contacts, interactive buttons, template, reaction, replies, internal notes) - it is the same components, not a reduced renderer.

### AC-11H-17 - responsive at both viewports [FE][E2E]
- **Given** the embed pages, **when** viewed at ~1280px AND ~375px, **then** they reflow with no horizontal scroll and scroll internally - the widget must look right inside a narrow side panel and on mobile.

---

## Slice 5 - Connection embed fields (host side)

### AC-11H-18 - embedSecret + allowedOrigins recognized [BE][T]
- **Given** a workspace/connection, **when** the operator sets `embedSecret` (write-only, encrypted) + `allowedOrigins`, **then** `/embed/session` verifies against that `embedSecret`, and the embed routes emit `frame-ancestors` from `allowedOrigins`. Rotating `embedSecret` invalidates outstanding assertions.

---

## Slice 6 - WABA management relocation (absorbed from EMS)

### AC-11H-19 - WABA config/profile/templates managed here [BE][FE][T]
- **Given** the shared service owns the Meta integration, **when** an operator/consumer manages a number, **then** WABA configuration, business profile, and template management live in the shared service (its own settings UI, embeddable if desired) - EMS no longer manages them; the public `GET /templates` continues to serve consumers for automation sends.

---

## Cross-cutting

### AC-11H-20 - Definition-of-Done gate [BE][FE][E2E]
- No unswapped mock; `external_agent` is a real provisioned identity (not a stub name); scope/caps/origin all enforced **server-side** (tests prove a bypassed widget still 403s); verified end-to-end with a real consumer embed at 375px + 1280px on a freshly rebuilt frontend; no regression to the existing protected inbox or the public gateway suites.

### AC-11H-21 - E2E: embedded thread round-trip [E2E]
- **Given** a test harness posing as a consumer parent (correct origin + a validly-signed assertion), **when** it mounts `/embed/omnichannel/thread` and drives it, **then** the conversation renders, a reply sends attributed to the external agent, a `read_only` token is refused server-side, and a wrong-origin embed is blocked - real interactions, report keyed to these ACs.
