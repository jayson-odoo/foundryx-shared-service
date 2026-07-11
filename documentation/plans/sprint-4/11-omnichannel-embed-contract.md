# Omnichannel Embed — Cross-Repo Interface Contract

**Status:** authored 2026-07-11 (grilled). This is the **interface both repos build against** — the EMS consumer (`dreamz_ems`, plan `sprint-4/11-omnichannel-embed-widget`) and the shared-service host (`foundryx-shared-service`, plan `sprint-4/11-omnichannel-embed-host`). A change here requires updating BOTH plans. Copy of this file lives in both repos' `documentation/plans/sprint-4/`.

## 1. Model

EMS embeds the shared service's conversation UI as a **chromeless, token-authed iframe widget** on lead pages. EMS stores **no conversation messages** — the shared service is the sole system of record. EMS keeps only a link (`Profile.shared_contact_id`) and reacts to inbound events. Supersedes the sprint-4/10 local-mirror decision.

Two actors, two origins:
- **Parent** = the EMS frontend (`https://<tenant>.<ems-domain>`), which mounts the iframe and mints assertions server-side.
- **Widget** = the shared-service embed page (`https://<shared-service-domain>/embed/omnichannel/*`), rendered inside the iframe.

## 2. Embed assertion (the SSO token EMS mints)

A short-lived JWT, **HS256**, signed with the connection's per-workspace `embedSecret` (see §8). Minted **server-side in EMS only** — never in the browser.

| Claim | Type | Meaning |
|---|---|---|
| `iss` | string | the EMS↔shared-service **connection id** — identifies the consumer + workspace that minted it |
| `aud` | string | **`"omnichannel-embed"`** — the shared service rejects any token with a different `aud` |
| `sub` | string | the EMS agent's user id — stable per agent; `(iss, sub)` is the federated identity key |
| `workspaceId` | string | target shared-service workspace |
| `scope` | string | **`"inbox"`** (whole workspace) or **`"thread:<contactId>"`** (single thread) |
| `name` | string | agent display name (attribution / "sent by") |
| `email` | string? | agent email (optional) |
| `avatarUrl` | string? | agent avatar (optional) |
| `caps` | string[] | capabilities from EMS RBAC — subset of `["reply","assign","close","note","send_template"]`, or `["read_only"]` |
| `allowedOrigins` | string[] | the parent origins permitted to embed + postMessage (mirrors the connection's `allowedOrigins`) |
| `iat` | number | issued-at (epoch seconds) |
| `exp` | number | expiry — **`iat + 900`** (15 min) |
| `jti` | string | unique id — **single-use** at the shared service |

## 3. `POST /embed/session` (shared service exchanges assertion → access token)

The widget, after its postMessage handshake receives the assertion, exchanges it here. **No cookies** — the response body carries the access token, held in widget JS memory.

**Request:** `{ "assertion": "<jwt>" }`

**Verification (fail closed on any):**
1. Decode header, require `alg=HS256`; resolve the connection by `iss`; verify signature with that connection's `embedSecret`.
2. `aud == "omnichannel-embed"`, `exp` not passed, `iat` not in the future (>60s skew rejected).
3. `jti` not seen before (single-use ledger, retained ≥ token TTL) → else `401 replayed`.
4. The connection is active for its tenant and `workspaceId` belongs to it.

**On success:** provision/load the **external agent** keyed by `(iss, sub)` (name/email/avatar upserted), then:
```json
{
  "accessToken": "<opaque or JWT, ~15 min>",
  "expiresIn": 900,
  "agent":     { "id": "<external-agent-id>", "name": "...", "avatarUrl": "..." },
  "workspace": { "id": "...", "name": "..." },
  "scope":     "thread:<contactId>" | "inbox",
  "caps":      ["reply","assign", ...]
}
```
The **access token embeds `workspaceId`, `scope`, `caps`, and the external-agent id**, and is the credential for §4 API/WS calls.

**Errors** (uniform `{ "error": { "code", "message" } }`): `invalid_assertion`, `replayed`, `expired`, `origin_not_allowed`, `workspace_not_found`.

## 4. Access-token usage + embed routes

- **API/WS auth:** the widget sends `Authorization: Bearer <accessToken>` on every shared-service omnichannel API + WS call. The shared service **enforces `scope` and `caps` server-side** on every request: a `thread:<contactId>` token may only read/act on that contact; a `read_only` (or missing-cap) token is rejected on any write (reply/assign/close/note/template). Widget-side control hiding is UX only.
- **Embed routes (chromeless, no app shell, no login redirect):**
  - `GET /embed/omnichannel/thread` — single conversation pane (scope `thread:<contactId>`).
  - `GET /embed/omnichannel/inbox` — full workspace inbox (scope `inbox`).
  - Both reuse the existing inbox React components; both **boot bare** and obtain the assertion via the postMessage handshake (§5) — the assertion is **never** placed in the URL.

## 5. postMessage protocol (v1)

Envelope: `{ "v": 1, "type": "<type>", "payload": { ... } }`. **Every handler validates `event.origin`** — the parent accepts only the shared-service embed origin; the widget accepts only an origin in the assertion's `allowedOrigins`. No `*`.

**Parent → widget:**
| type | payload | when |
|---|---|---|
| `init` | `{ assertion, theme, colorScheme }` | response to `ready` — starts the session + first paint |
| `theme` | `{ theme, colorScheme }` | live re-skin (dark toggle / rebrand) |
| `token` | `{ assertion }` | silent refresh (response to `needToken`) |

**Widget → parent:**
| type | payload | when |
|---|---|---|
| `ready` | `{}` | widget mounted, requesting `init` |
| `needToken` | `{}` | access token near expiry — mint a fresh assertion |
| `resize` | `{ height }` | content height changed (full-inbox mode) |
| `activity` | `{ kind, contactId }` | coarse "something happened" (message sent/received/assigned) so EMS can refresh the lead's last-contacted; NOT message content |

`theme` = the whitelisted brand primitives (`{ primary, surface, text, bubbleIn, bubbleOut, radius, ... }`); `colorScheme` = `"light" | "dark"`. Business deep-links (create-X-from-conversation) are **deferred to v2** via the same `type` seam.

## 6. `message.received` webhook (the react bridge)

Unchanged from the sprint-4/10 consumer webhook — the shared service already emits `message.inbound` on `POST /webhooks/omnichannel` (HMAC `X-Fx-Signature`, `X-Fx-Event-Id` dedup). EMS adds an `omnichannel.message_received` **workflow trigger** that consumes the inbound event and flattens it to the run context:
`trigger.workspaceId`, `trigger.contactId`, `trigger.profileId`, `trigger.message.{type,body,mediaUrl}`, `trigger.contact.{name,phone}` (substitution-only, anti-SSTI). **Inbound-only** (from-contact) → no send-loop. Delivery receipts / `contact.updated` do not drive business workflows in v1.

## 7. Connection config — two new fields

On the core `connections` row (provider `omnichannel_shared`), added by the consumer:
- **`embedSecret`** — per-workspace HMAC secret for minting/verifying assertions. Fernet-encrypted at rest, write-only over the API. **Separate from `signingSecret`** (webhook-verify) — key separation.
- **`allowedOrigins`** — string[] of parent origins permitted to embed (drives `frame-ancestors` + the assertion's `allowedOrigins` claim + `/embed/session` origin check).

## 8. Security posture (server-enforced at the shared service)

1. **Replay:** `jti` single-use, retained ≥ TTL; short 15-min assertion TTL.
2. **Scope enforced, not cosmetic:** thread-scoped token cannot widen to the workspace.
3. **Caps enforced on every write** (backend is the boundary).
4. **Blast radius = one consumer:** `embedSecret` per workspace, rotatable; a leak forges agents for that workspace only.
5. **Clickjacking:** `Content-Security-Policy: frame-ancestors` = the connection's `allowedOrigins`; the embed refuses to load elsewhere.
6. **postMessage origin-checked both directions** (no `*`).
7. **`/embed/session` + widget API throttled** via the shared service's existing throttle.

## 9. Versioning

The postMessage envelope carries `v`. The assertion `aud` pins the token purpose. Breaking either bumps `v` / a new `aud` and updates this contract + both plans in lockstep.
