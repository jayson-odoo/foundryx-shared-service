# 19 - Claude connector module (SS-CONNECTOR) - behaviour card

Status: **Plan stage. This card is under owner review (crew-ask on PR #117). No code until it is agreed.**
After agreement: UAC (`19-claude-connector-acceptance-criteria.md`) then the build plan, per the repo pipeline.

## 0. What already exists (verified, `service_backend/`)

| Fact | Where |
|---|---|
| No OAuth server, PKCE or MCP code anywhere | only `OAuth2PasswordBearer` for reading bearers, `app/dependencies.py:12,22` |
| Signed-user pattern to copy: product signs an HS256 assertion, SS verifies by connection id; tenant comes from the connection row, never the assertion | `modules/ideation/services/embed.py:241-309` |
| Stricter variant with a single-use `jti` ledger + `iat` skew + origin allow-list | `modules/omnichannel/services/embed_session_service.py:153-187,289-306` |
| Ideation embed has **no** replay protection and **no** throttle (we must not copy that gap) | `modules/ideation/services/embed.py` (no jti), `modules/ideation/routers/embed.py` |
| Secrets are Fernet-encrypted, fail closed on decrypt | `app/secrets.py:30-35`, `modules/ideation/services/embed.py:210-221` |
| Outbound to sorento today = static `X-API-Key`, not signed | `modules/autocount/sinks_sorento.py:203-204` |
| Only signed outbound pattern = `sha256=` HMAC over `{timestamp}.{body}` | `modules/omnichannel/services/webhook_delivery.py:61-69` |
| Module routers can be `"public": true` (no `require_module`), auth done in-endpoint | `app/module_loader.py:56-86` |
| Module hooks install/install_tenant/uninstall_tenant/register_* | `modules/ideation/bootstrap.py:28-178` |
| Activity log (Developer Logs console) - closed source tuple, never raises, redacts | `app/models/integration_activity.py:37-91`, `app/activity_log/service.py:110-181` |
| Throttle scopes (enforce/record pairs) | `app/services/throttle.py:51-88,221-283` |

**Not verified:** sorento-crm #1547 (`analytics_connector.py`, `sorento_analytics_mcp/cap.py`, `tools.py:102`). This
session's GitHub access is scoped to foundryx-shared-service only, so I cannot read sorento-crm. The design below
is written from the OAuth/MCP specs + the lane brief; I will port #1547's generic parts once access is granted (crew-note).

## 1. Rules

1. **One connector per product.** URL `https://<ss host>/mcp/<product>` (e.g. `/mcp/sorento`). Each product has its own
   OAuth issuer, sign-in, tool list and grants. One shared module (`modules/connector`, schema `app_connector`) behind all of them.
2. **Product key is globally unique** and the registry row is owned by exactly one SS tenant (the operator of that
   product). Grants, audit and admin all scope to that tenant.
3. **Identity = product login.** SS never asks for a password. The product signs an assertion of who logged in; the
   grant stores `(product, product_user_id)` + display name/email snapshot.
4. **Read-only.** The manifest may only declare tools with `readOnlyHint: true`; SS refuses to register any other
   (and only forwards `tools/list` + `tools/call`, no resources/prompts/sampling in v1).
5. **Product RBAC decides every call.** SS never caches data or permissions. Each call goes to the product as that user;
   a user whose role loses access sees it on the next call.
6. **Data rules (from the #1547 card):** raw message text allowed, phone numbers excluded, OTPs masked. The product is
   the authority (it knows its fields); SS adds caps (size/rows) and a defense-in-depth scrubber (Q3).
7. **Per-user OAuth only.** No static org token. Tokens are opaque random strings, stored hashed (SHA-256), never logged.
8. **Everything is audited**: consent, deny, token issue/refresh, every tool call (tool name, args hash, result size,
   truncated?, status, latency, error code). Never the response body.

## 2. Consent flow (step by step)

OAuth 2.1 + PKCE S256 + Dynamic Client Registration (RFC 7591) + Protected Resource Metadata (RFC 9728), which is
what claude.ai remote connectors use.

1. User in claude.ai adds custom connector `https://<ss>/mcp/sorento`.
2. Claude POSTs MCP `initialize` with no token → SS `401` + `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp/sorento"`.
3. Claude reads protected-resource metadata → authorization-server metadata (issuer `https://<ss>/mcp/sorento`).
4. Claude registers itself (`POST /mcp/sorento/oauth/register`). SS accepts only redirect URIs on an allow-list
   (`https://claude.ai/api/mcp/auth_callback`, `https://claude.com/api/mcp/auth_callback`; configurable). Throttled per IP.
5. Claude opens the browser at `/mcp/sorento/oauth/authorize?client_id&redirect_uri&code_challenge&state&...`.
   SS validates client + exact redirect URI + S256 challenge, stores a **pending request** (random id, 10 min TTL),
   and redirects to the product's configured login URL: `https://<sorento>/connector/consent?request=<id>`.
   (The return URL is fixed in the product's own config, never taken from the query, so it cannot be an open redirect.)
6. User logs in to sorento normally (its own MFA etc.). Sorento redirects back to
   `https://<ss>/mcp/sorento/oauth/callback?assertion=<jwt>`. Assertion = HS256 with the product's **assertion key**:
   `iss=sorento, aud=ss-connector:sorento, typ=connector-assertion, sub=<product user id>, name, email, role_label,
   nonce=<pending request id>, iat, exp (<=120 s), jti` (jti single-use ledger, like `EmbedJti`).
7. SS verifies signature, iss/aud/typ, exp/iat skew, nonce = a live pending request, jti unused. Then shows the
   **consent page** (SS-hosted, shared code, product-branded): "Claude wants read-only access to Sorento as
   *Aisha Tan (Sales Agent)*. It can: <tool list from manifest>. Allow / Deny".
8. Allow → create or reuse the grant for `(product, product_user_id, client_id)`, issue a single-use auth code
   (60 s, bound to client + redirect + PKCE challenge), redirect to Claude with `code&state`.
   Deny → redirect with `error=access_denied`.
9. Claude calls `/token` with code + verifier → access token (1 h) + refresh token (30 d, rotating; replaying an old
   refresh token revokes the whole grant = theft signal).
10. Tool calls: `POST /mcp/sorento` (JSON-RPC, Streamable HTTP, stateless) with Bearer. SS resolves token → grant →
    product (active?) → validates args against the manifest JSON Schema → signed POST to
    `{product api base}/connector/tools/{tool}` with headers `X-FX-Connector-Timestamp`, `-Nonce`, `-Grant`,
    `-User` (product user id), `-Signature: sha256=HMAC(call key, ts.nonce.method.path.sha256(body))`
    (same shape as the webhook signer, `webhook_delivery.py:61-69`, plus nonce + path binding). Product checks
    signature + 5 min skew + nonce, runs the tool **as that user with its own RBAC**, returns JSON.
11. SS applies caps (default 64 KB / 200 rows, per-tool override in the manifest), marks truncation, writes the
    audit row, returns an MCP `tools/call` result.

## 3. What an admin sees (SS tenant admin owning the product)

- **Connector › Products** (Resource list → form): key, display name, MCP URL (copy button), login URL, API base URL,
  assertion key + call key (write-only `SecretInput`, rotate action), status Active/Disabled, tool manifest
  (read-only list, "Refresh from product" action), last manifest fetch time.
- **Connector › Grants** (Resource list): product, user (name + product user id), client ("Claude"), granted at,
  last used, calls (30 d), status Active/Revoked. Segments Active|Revoked. Row + bulk action **Revoke** (typed
  confirm for bulk). Row → detail with an **Activity** tab = that grant's audit rows.
- Calls also appear in **Developer Logs** under a new source `connector` (`integration_activity.py:37-43`).
- Perms: `connector.read`, `connector.manage` (products + revoke). Grant sweep for existing Admins.

## 4. Revoke behaviour

- Admin revoke: grant → Revoked, all its access + refresh tokens deleted in the same transaction. The next Claude
  call gets `401 invalid_token`; claude.ai shows "reconnect", and reconnecting runs the full consent again (new grant).
- Claude-side disconnect: Claude may call `/oauth/revoke` (RFC 7009) → same result.
- Product disables the product (admin toggle Disabled) → every call 401 + consent page says "Sorento connector is
  turned off". Grants kept (re-enabling restores them).
- Product reports the user is gone (`error.code = user_inactive`) → SS auto-revokes that grant.
- Refresh-token replay → whole grant revoked (audited `refresh_reuse`).

## 5. Error states (what Claude/the user sees)

| Situation | SS behaviour | User sees |
|---|---|---|
| Product down / timeout (10 s) | tool result `isError: true`, audit `upstream_unavailable` | "Sorento is not reachable right now. Try again in a minute." |
| Product 5xx | same, `upstream_error` | "Sorento had an error answering this." |
| RBAC denies (product 403 `forbidden`) | tool result `isError: true` with product's message | "Your Sorento role can't see conversations of other teams." |
| Assertion expired / bad signature / replayed jti at callback | SS error page, no grant | "Sign-in took too long or was already used. Go back to Claude and connect again." |
| Pending request expired (>10 min) | error page | same text |
| Grant revoked / token expired | HTTP 401 `invalid_token` | Claude prompts to reconnect |
| Bad args (schema) | JSON-RPC `-32602` | Claude retries with fixed args |
| Response too big | truncated + `"truncated": true` note | Claude says it only sees the first N rows |
| Throttled | HTTP 429 + `Retry-After` | Claude waits |

**Product error shape (contract):** `{"error": {"code": "forbidden|not_found|invalid_args|user_inactive|internal", "message": "<safe for end user>"}}`.

## 6. Examples (role names are placeholders: I could not read sorento dev data from this sandbox, see note)

1. **Sales agent** "Aisha" connects; tool `list_conversations` returns only her assigned threads (sorento RBAC);
   message text visible, contact phone field absent, an OTP in a message shows as `OTP ••••••`.
2. **Supervisor** asks "how many chats did my team close this week" → `conversation_stats` returns team-wide numbers.
   Same question by Aisha → only her own numbers. SS code path identical; product decides.
3. Admin revokes Aisha's grant at 10:02 → her Claude call at 10:03 fails 401 → she reconnects → new grant row,
   old one stays Revoked in the list with its audit history.
4. Aisha's sorento account is deactivated → next call product answers `user_inactive` → SS revokes the grant and the
   grants list shows Revoked (reason: user inactive).
5. Sorento is being deployed (down 40 s) → Claude gets "Sorento is not reachable", audit row `upstream_unavailable`,
   grant untouched.

## 7. Contract for products (to agree with lane CLAUDE-CONNECTOR before code)

- `GET /connector/manifest` (signed like tool calls, no user header) → `{version, tools:[{name, title, description,
  inputSchema, readOnlyHint:true, maxBytes?, maxRows?}]}`.
- `GET /connector/consent?request=<id>` → product login → 302 to the SS callback with the assertion (section 2.6).
- `POST /connector/tools/{name}` signed (section 2.10) → `200 {result}` or the error shape (section 5).
- Product stores two keys (assertion key, call key) + the SS callback URL in its own DB config (ideation-embed pattern).
Full contract doc: `documentation/connector/product-contract.md` (written after this card is agreed).
