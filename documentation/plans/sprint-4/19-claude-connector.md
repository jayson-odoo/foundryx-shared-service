# 19 - Claude connector module (SS-CONNECTOR) - behaviour card r2

Status: **Build. Card r2 agreed (answers in section 7). Backend red-first in progress; admin UI waits for the mock.**
r1 answers (crew, 9 Oct): Q1 (b) the PRODUCT shows consent, SS shows none; Q2 (a) two secrets, one per direction;
Q3 (a) the product is the only authority for OTP/phone masking, no SS scrubber; Q4 (a) access 1 h, refresh 30 d
rotating, grant idle-expires at 90 d; Q5 (a) product serves a signed manifest.

**Contract source of truth:** sorento-crm `documentation/plans/analytics/CONTRACT-claude-connector-ss-09oct.md`
(branch `claude/analytics-connector-e2jret`, head 76659f561, sections 0-9). SS builds to it exactly; any change
goes through a crew-note with lane CLAUDE-CONNECTOR first. This card only adds what the contract leaves to SS.

## 0. Facts (verified)

| Fact | Where |
|---|---|
| SS has no OAuth server, PKCE or MCP code; bearer reading only | `service_backend/app/dependencies.py:12,22` |
| Signed-user pattern (product signs HS256, SS verifies by connection) | `service_backend/modules/ideation/services/embed.py:241-309`; sorento side `sorento_crm_backend/app/services/ideation_embed_service.py:161` |
| Single-use `jti` ledger + skew pattern to reuse | `service_backend/modules/omnichannel/services/embed_session_service.py:153-187,289-306` |
| Module routers may be `"public": true` (auth in-endpoint) | `service_backend/app/module_loader.py:56-86` |
| Developer Logs `record()` is failure-isolated (never raises) -> cannot be the fail-closed audit | `service_backend/app/activity_log/service.py:105-181` |
| sorento verifies calls: claims list, 60 s lifetime, 5 s skew, 120 s replay, 4096-char token cap | `sorento_crm_backend/app/services/analytics_connector/access.py:36-46` |
| sorento req_hash + sent-order canonical query (SS must produce byte-identical) | `access.py:92-101` |
| sorento manifest: 34 reused + 5 chat tools, `version` = hash of tools | `sorento_crm_backend/app/services/analytics_connector/manifest.py:1-8,30-110` |
| `analytics.connector.use` granted to NO role, no admin bypass | `sorento_crm_backend/app/rbac/permission_registry.py:938-947` |
| chat tools also need `system.chat_history.view` | `permission_registry.py:388`, `access.py:47-55` |
| sorento roles in dev data: Salesperson, Admin, Project Customer Service, Warehouse Manager, Purchasing, ... | `select name from user_roles` on local `sorento_acm_dev`; Salesperson seeded at `alembic/versions/identity_0001_s0_model.py:47` |

## 1. Rules

1. **One connector per product**: `https://<ss>/mcp/<product>` (first: `/mcp/sorento`). Own OAuth issuer, tool list,
   grants. Shared module `modules/connector`, schema `app_connector`.
2. **Product registry = env** (contract section 1 says secrets are env only): per product `connection_id`, owning SS
   tenant slug, consent URL, API base URL, the two secrets, audiences. Admin sees it read-only (Q1).
3. **Identity = product login.** SS never sees a password. The grant stores `(product, product_user_id = sub)`,
   name + email snapshot, `consented_at = assertion iat` (so a consent signed before a sorento revoke-all cannot
   outlive it; sorento security note 2).
4. **Consent is the product's screen** (r1 Q1 b). SS only redirects to it and receives the form-POST.
5. **Browser binding**: `/authorize` sets an HttpOnly Secure `SameSite=None` cookie holding a random binding value
   (hash stored on the pending request). The assertion form-POST is accepted only with that cookie for that
   `request_id` (stops the mailed-link consent phishing, sorento security note 1). `SameSite=None` is required
   because the POST comes cross-site from sorento.
6. **DCR redirect URIs exact-match an allow-list**, default only `https://claude.ai/api/mcp/auth_callback`.
7. **Read-only.** SS registers only manifest tools whose `annotations.readOnlyHint` is true and
   `destructiveHint` false; MCP methods served: `initialize`, `notifications/initialized`, `ping`, `tools/list`,
   `tools/call`. Nothing else.
8. **Args validated** against the tool's `input_schema` with `additionalProperties: false`; only the manifest's
   `query_params` are sent, in manifest order; path params percent-encoded `safe=""`; `path_template` used verbatim
   (trailing slash kept); POST body = the remaining args. Body cap 1 MB (contract 9.4).
9. **Every call signed** with a fresh call JWT (contract section 3 claims, `exp = iat + 60`, new `jti`).
10. **Product RBAC decides every call**; SS caches no data and no permissions.
11. **Caps**: response text 120 000 chars, list rows 1000; over -> cut + `truncated: true` note. No SS scrubber
    (r1 Q3 a).
12. **Tokens** opaque, stored SHA-256 hashed, never logged. Access 1 h, refresh 30 d rotating; replay of a used refresh
    token revokes the whole grant. Grant unused 90 d -> expired (r1 Q4 a).
13. **Fail-closed audit**: one `app_connector.call_log` row per `tools/call` (user, tool, args capped 4 KB, status,
    ms, rows, chars, error code) written and committed BEFORE the result is returned; if that write fails Claude
    gets a tool error and no data. Grant lifecycle rows (consented, denied, refreshed, revoked + reason).

## 2. Consent flow

1. User adds custom connector `https://<ss>/mcp/sorento` in claude.ai.
2. Claude calls MCP with no token -> `401` + `WWW-Authenticate: Bearer resource_metadata="<ss>/.well-known/oauth-protected-resource/mcp/sorento"`.
3. Claude reads protected-resource metadata, then authorization-server metadata (issuer `<ss>/mcp/sorento`).
4. Claude registers (`POST /mcp/sorento/oauth/register`, RFC 7591). Exact redirect allow-list; throttled per IP.
5. Browser -> `GET /mcp/sorento/oauth/authorize` (client_id, redirect_uri, PKCE S256 challenge, state). SS checks
   them, stores a pending request (10 min), sets the binding cookie, and 302s to
   `https://<sorento>/connect/claude?req=<consent_request JWT>` (contract 2.1 claims; `return_url` =
   `<ss>/mcp/sorento/oauth/consent-return`).
6. sorento handles login, inspect, Allow/Deny (contract 2.2-2.4). Allow -> the page form-POSTs `request_id` +
   `assertion` to `return_url`; Deny -> `request_id` + `error=access_denied`.
7. SS `consent-return`: binding cookie matches the request, request live and unused, assertion HS256 with the
   product->SS secret, `typ/iss/aud/connection_id/request_id`, `exp-iat <= 120`, jti unused (ledger). Then
   create or reuse the grant `(product, sub, client_id)`, mint a single-use auth code (60 s, bound to client,
   redirect, challenge), 302 to Claude with `code&state`. Deny -> 302 with `error=access_denied&state`.
8. Claude `POST /mcp/sorento/oauth/token` (code + verifier) -> access + refresh.
9. `POST /mcp/sorento` (Streamable HTTP, stateless JSON) with Bearer -> token -> grant -> product -> validate args ->
   signed call -> map errors -> cap -> audit (committed) -> MCP result.

## 3. What an admin sees (SS tenant admin of the product's owning tenant)

- Menu **Settings > Claude connector** with two tabs:
  - **Grants** (Resource list): user name, product user id, product, client, granted, last used, calls 30 d, status
    (Active/Revoked/Expired). Segments Active|Revoked|Expired. Row + bulk **Revoke** (typed confirm on bulk).
    Row -> detail with an **Activity** tab (that grant's call_log + lifecycle rows).
  - **Products** (read-only): key, MCP URL (copy), consent URL, API base, manifest version + fetched-at, tool count,
    secrets shown only as "set / missing". Action **Refresh manifest**.
- Perms `connector.read` (lists) and `connector.manage` (revoke, refresh), core-CSV-style module CSV, granted to
  tenant Admin on install + a grant sweep for existing Admins.

## 4. Revoke behaviour

- Admin revoke -> grant Revoked + all its tokens deleted in one transaction -> next Claude call 401 -> claude.ai
  asks to reconnect -> full consent -> NEW grant row (old stays Revoked with its history).
- Claude disconnect -> `/oauth/revoke` (RFC 7009) -> same.
- sorento answers 403 `connector_access_removed` / `user_inactive` / `reconsent_required` -> SS revokes the grant
  (reason = the code) and returns a tool error; the call after that gets 401.
- Refresh-token replay -> grant revoked (`refresh_reuse`).
- 90 d idle -> Expired by the beat prune.

## 5. Error states (contract section 5 mapping)

| sorento answer | SS does | Claude/user sees |
|---|---|---|
| 401 `invalid_signature` / `token_expired` / `replayed` / `wrong_audience` | retry ONCE with a fresh token; then tool error + log `upstream_auth` | "The Sorento connection is misconfigured. An admin has been notified." |
| 403 `connector_access_removed` / `user_inactive` / `reconsent_required` | revoke grant, tool error | "Your Sorento access for Claude was removed. Reconnect the connector." |
| 403 `chat_history_not_permitted` / `route_not_allowed` / `permission_required` / `param_not_allowed` | tool error, grant stays | sorento's message, e.g. "You do not have permission to view chat history." |
| 404 / 422 | tool error | sorento's message |
| 413 | tool error | "That request is too large." |
| 429 / 5xx / timeout 15 s / connection refused | tool error, grant stays | "Sorento is not reachable right now. Try again in a minute." |
| consent-return: bad/expired/replayed assertion, missing binding cookie, expired request | SS error page, no grant | "Sign-in took too long or did not start in this browser. Go back to Claude and connect again." |
| grant revoked / token expired | HTTP 401 `invalid_token` | Claude prompts reconnect |
| args fail schema | JSON-RPC `-32602` | Claude retries |
| response > 120 000 chars or > 1000 rows | cut + `truncated: true` | Claude says it saw part of the data |
| audit write fails | tool error, no data | "The call could not be recorded, so no data was returned." |

## 6. Examples (sorento roles from dev data; no person data)

1. A **Salesperson** (role seeded at `identity_0001_s0_model.py:47`) adds the connector. `analytics.connector.use` is
   granted to no role by default (`permission_registry.py:938-947`), so sorento's consent page shows the
   no-permission view, only Deny works, SS receives `error=access_denied`, no grant row is created.
2. An admin gives the **Project Customer Service** role `analytics.connector.use` + `system.chat_history.view`. A user
   with that role connects; `chat_query` grouped by month returns counts; SS stores grant (sorento, `sub`),
   `consented_at` = assertion iat; the call shows on the Grants detail Activity tab.
3. A **Warehouse Manager** user holds `analytics.connector.use` but not `system.chat_history.view`: a reused stock read
   tool works; `chat_search_messages` returns 403 `chat_history_not_permitted` -> tool error, grant stays Active.
4. An **Admin** user (no bypass) does "log out other devices": sorento stamps `users.connector_revoked_at`; the next
   call gets 403 `reconsent_required`; SS marks the grant Revoked (reason reconsent_required); the call after that is
   401 and claude.ai asks to reconnect.
5. sorento is redeploying for 40 s: calls time out -> "Sorento is not reachable", call_log status `upstream_unavailable`,
   grant untouched.

## 7. r2 answers (crew a59366446, 9 Oct) - all (a)

1. **Registry = env per product**, admin view read-only (contract section 1).
2. **Grants visible to the owning SS tenant admin**, perms `connector.read` / `connector.manage`.
3. **call_log retention default 180 days** (beat prune). Owner may override; the value is a setting
   `CONNECTOR_CALL_LOG_RETENTION_DAYS` (default 180).
4. **Manifest cached 15 min + Refresh**; when the product is down the last good copy is served and the admin
   Products view marks it **stale** (fetch error + last good fetched-at).
5. **Claude IP allowlist: proxy rule at deploy, plus an app-level env gate (owner e2e plan, 10 Oct).** Range verified:
   Anthropic outbound IPv4 `160.79.104.0/21` ("stable IP addresses that Anthropic uses for outbound requests, for example
   when making MCP tool calls"), source https://platform.claude.com/docs/en/api/ip-addresses (fetched 9 Oct 2026).
   - App gate: `CONNECTOR_ALLOWED_CLIENT_CIDRS` (comma list, empty = off, any invalid entry = fail closed) checked before
     auth on the Claude-facing endpoints only (`POST /mcp/{p}`, `/oauth/register`, `/oauth/token`, `/oauth/revoke`);
     browser endpoints (`/oauth/authorize`, `/oauth/consent-return`, `/.well-known/*`) exempt. Client IP comes from the
     throttle resolver (X-Forwarded-For only with `TRUST_PROXY_HEADERS=true`). It is what makes a time-boxed tunnel safe.
   - `CONNECTOR_PUBLIC_BASE_URL` overrides `PUBLIC_BASE_URL` for the issuer, both metadata documents, WWW-Authenticate,
     the consent return_url, the MCP URL in the admin view and the binding-cookie path, so a tunnel URL needs no code change.
   - **Owner deploy step (complementary):** Caddy rule allowing only that range on the same Claude-facing paths.
   - **Do not enable the allowlist in prod until issue #118 / BL-SS-303 is fixed** (client IP resolution behind Cloudflare: forged first XFF hop through tunnels; prod likely sees Cloudflare edge IPs).

## 7a. Accepted risks (review round 1)

- consent-return with `error=access_denied` carries no product signature, only the binding cookie (`SameSite=None`).
  A cross-site POST that knows a live `request_id` can cancel that user's own in-flight connect. Impact = the user
  retries; no grant, token or data is issued. Accepted; a signed denial would need a contract change with sorento.
- Prune runs inside the `workflows.run_due` beat tick (own try/rollback); its own beat task = BL-SS-302.

## 8. Build order after answers

UAC `19-claude-connector-acceptance-criteria.md` -> tester red tests (crypto/call JWT, OAuth endpoints, consent-return
binding, MCP tools/call forwarding, error mapping, caps, fail-closed audit) -> coder -> reviewer + security review ->
mock for Settings > Claude connector -> UI -> joint run against sorento `claude/analytics-connector-e2jret` locally.

## 9. Build design - fixed interfaces (tests are written against these)

Module `service_backend/modules/connector/` (mirror `modules/ideation/`): `manifest.json` (schema `app_connector`,
version table `alembic_version_connector`, public routers), `db.py` (`ConnectorBase`, `CONNECTOR_SCHEMA`),
`models.py`, `bootstrap.py`, `permissions/permissions.csv` (`connector.read`, `connector.manage`), `alembic/`.

**crypto.py** (pure; replaces the r1 HMAC `sign_call`/`verify_call` and the r1 `verify_assertion` signature):
- `pkce_verify(verifier, challenge, method) -> bool`, `redirect_allowed(uri, allowed) -> bool`,
  `new_token() -> str`, `hash_token(token) -> str` (kept).
- `canonical_query(query: str) -> str`, `request_hash(method, raw_path, query, body: bytes) -> str` (byte-identical
  to sorento `access.py:92-101`).
- `sign_call(secret, *, connection_id, audience, sub, grant_id, consented_at: int, tool, method, raw_path, query,
  body: bytes, now: int | None = None) -> str` (HS256, `iss="foundryx-ss"`, `typ="connector_call"`, `exp=iat+60`).
- `sign_consent_request(secret, *, connection_id, audience, request_id, client_name, redirect_host, return_url,
  now: int | None = None, ttl: int = 600) -> str`.
- `verify_assertion(token, secret, *, issuer, connection_id, request_id, now: int | None = None) -> dict`, raises
  `AssertionInvalid` (`aud` fixed `"foundryx-connector"`, `typ="connector_assertion"`, `exp-iat<=120`, 5 s skew,
  token <= 4096 chars). jti single use is checked by the service against `assertion_jti`.

**registry.py**: `Product` dataclass (`key, display_name, tenant_slug, connection_id, consent_url, api_base_url,
ss_to_product_secret, product_to_ss_secret, issuer, consent_audience, call_audience`), `load_products(env: Mapping[str,str])
-> dict[str, ProductStatus]` and `get_product(key) -> Product | None` (None when unknown or misconfigured).
Env: `CONNECTOR_PRODUCTS=sorento,acme`; per key `CONNECTOR_<KEY>_{TENANT_SLUG,CONNECTION_ID,CONSENT_URL,API_BASE_URL,
SS_TO_PRODUCT_SECRET,PRODUCT_TO_SS_SECRET}` required, `_{DISPLAY_NAME,ISSUER,CONSENT_AUDIENCE,CALL_AUDIENCE}` optional,
defaults `key`, `<key>-connector-consent`, `<key>-connector-api`. Global `CONNECTOR_REDIRECT_ALLOWLIST` (comma list,
default `https://claude.ai/api/mcp/auth_callback`), `CONNECTOR_CALL_LOG_RETENTION_DAYS=180`,
`CONNECTOR_MANIFEST_TTL_SECONDS=900`, `CONNECTOR_CALL_TIMEOUT_SECONDS=15`. Tests inject via
`registry.set_env_for_tests(mapping)` / reset.

**Endpoints** (`{p}` = product key; base = `settings.public_base_url`):
- `GET /.well-known/oauth-protected-resource/mcp/{p}`, `GET /.well-known/oauth-authorization-server/mcp/{p}`
- `POST /mcp/{p}/oauth/register` (JSON, RFC 7591), `GET /mcp/{p}/oauth/authorize`,
  `POST /mcp/{p}/oauth/consent-return` (form: `request_id`, `assertion` | `error`), `POST /mcp/{p}/oauth/token`
  (form), `POST /mcp/{p}/oauth/revoke` (form)
- `POST /mcp/{p}` MCP JSON-RPC
- Admin (session JWT, module-gated): `GET /connector/grants`, `GET /connector/grants/{id}`,
  `GET /connector/grants/{id}/activity`, `POST /connector/grants/{id}/revoke`, `POST /connector/grants/bulk-revoke`
  `{ids}`, `GET /connector/products`, `POST /connector/products/{key}/refresh-manifest`.
- Binding cookie `fx_connector_bind`, path `/mcp/{p}/oauth`, HttpOnly, Secure, SameSite=None.

**Tables** (`app_connector`, all with `tenant_id`): `oauth_clients`, `pending_requests` (id, client, redirect,
challenge, state, bind_hash, expires_at, used_at), `auth_codes` (hash, grant, client, redirect, challenge,
expires_at, used_at), `tokens` (hash, kind access|refresh, grant, family, expires_at, used_at, revoked_at),
`grants` (product, product_user_id, name, email, client_id, consented_at, status active|revoked|expired,
revoked_reason, last_used_at), `assertion_jti`, `call_log`, `grant_events`, `manifest_cache` (product, json,
version, fetched_at, last_error).

**Seams for tests**: outbound HTTP via `modules.connector.services.product_client.TRANSPORT` (None = real httpx;
tests set an `httpx.MockTransport`); audit write `modules.connector.services.audit.write_call_log` (tests patch it
to raise for fail-closed). Prune: `modules.connector.services.maintenance.prune(db, now)` wired into the existing beat.
