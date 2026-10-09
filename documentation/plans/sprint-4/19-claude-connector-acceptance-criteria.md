# 19 - Claude connector - User Acceptance Criteria

Contract: sorento-crm `documentation/plans/analytics/CONTRACT-claude-connector-ss-09oct.md` (sections 0-9), card
`19-claude-connector.md` r2. Tags: [BE] backend behaviour, [FE] frontend, [E2E] end-to-end, [T] test-only guard.
"Product" below = a registry entry; tests use a fake product `acme` plus the real `sorento` shape.

## S1 - Signing primitives (`modules/connector/crypto.py`)

- **AC-19-01 [BE]** Given a verifier/challenge pair, PKCE S256 passes only for the matching pair, only for method
  `S256`, and refuses verifiers outside RFC 7636 (43-128 unreserved chars).
- **AC-19-02 [BE]** Redirect URIs match the allow-list by exact string only (no prefix, trailing slash, case or
  query variants).
- **AC-19-03 [BE]** `request_hash(method, raw_path, query, body)` equals base64url-nopad(SHA-256 of
  `METHOD\nPATH\nCANONICAL_QUERY\nhex(sha256(body))`), CANONICAL_QUERY in SENT order with `quote(safe="-_.~")`;
  pinned by golden vectors identical to sorento `access.py:92-101` (empty body, duplicate keys, spaces, unicode,
  trailing-slash path).
- **AC-19-04 [BE]** `sign_call(...)` returns an HS256 JWT with exactly the contract section 3 claims (`typ=connector_call`,
  `iss=foundryx-ss`, product call audience, `connection_id`, `sub`, `grant_id`, int `consented_at`, `tool`,
  `req_hash`, int `iat`, `exp = iat + 60`, unique `jti`). A reference verifier accepts it and rejects a changed
  body/path/query/method.
- **AC-19-05 [BE]** `sign_consent_request(...)` returns the section 2.1 JWT (`typ=connector_consent_request`,
  `iss=foundryx-ss`, consent audience, `connection_id`, `request_id`, `client_name`, `redirect_host`, `return_url`,
  `iat`, `exp <= iat + 600`, `jti`).
- **AC-19-06 [BE]** `verify_assertion(...)` accepts only HS256 with the product->SS secret, `typ=connector_assertion`,
  product `iss`, `aud=foundryx-connector`, matching `connection_id` + `request_id`, `exp - iat <= 120`, `iat` not in
  the future beyond 5 s, not expired, non-empty `sub`/`jti`; any failure raises one opaque error. Also refuses
  `alg=none`, a token signed with the SS->product secret, and tokens over 4096 chars.

## S2 - Data + registry

- **AC-19-10 [BE]** Products load from env (`CONNECTOR_PRODUCTS`, `CONNECTOR_<KEY>_*`); a product with a missing
  secret/URL/tenant is listed as `misconfigured` and every endpoint for it answers 404 (MCP/OAuth) without leaking
  which part is missing.
- **AC-19-11 [BE]** Tables in schema `app_connector`: oauth_clients, pending_requests, auth_codes, tokens, grants,
  assertion_jti, call_log, grant_events; every row carries `tenant_id` (from the product, never client input).
- **AC-19-12 [T]** The module Alembic migration creates exactly those tables and is checked on a dev copy
  (`upgrade` then `downgrade`); revision ids <= 32 chars.

## S3 - OAuth authorization server (per product, prefix `/mcp/<product>`)

- **AC-19-20 [BE]** MCP call without a token -> 401 with `WWW-Authenticate: Bearer resource_metadata="<base>/.well-known/oauth-protected-resource/mcp/<product>"`;
  both metadata documents are served and name issuer, authorize, token, register, revoke endpoints, `S256` only.
- **AC-19-21 [BE]** DCR accepts only allow-listed redirect URIs (400 `invalid_redirect_uri` otherwise), returns a
  `client_id`, no secret (public client); per-IP throttled (429 after the limit).
- **AC-19-22 [BE]** `/authorize` with an unknown client, a non-registered redirect, no/`plain` PKCE -> error page,
  never a redirect to the given URI. Valid -> pending request (10 min), Set-Cookie binding cookie (HttpOnly, Secure,
  SameSite=None, path scoped to the product), 302 to `<consent_url>?req=<consent_request JWT>` whose `request_id`
  equals the pending request.
- **AC-19-23 [BE]** `POST consent-return` (form) with a valid assertion AND the matching binding cookie -> grant
  created (`product_user_id=sub`, name/email snapshot, `consented_at = assertion iat`), auth code minted, 302 to the
  client redirect with `code` + original `state`. The same pending request cannot be completed twice.
- **AC-19-24 [BE]** consent-return refuses (error page, no grant, no code): missing/other binding cookie, expired
  pending request, used pending request, bad signature, wrong aud/iss/typ/connection_id/request_id, expired
  assertion, replayed assertion `jti`.
- **AC-19-25 [BE]** consent-return with `error=access_denied` (and the binding cookie) -> 302 to the client with
  `error=access_denied&state`, grant event `denied`, no grant.
- **AC-19-26 [BE]** `/token` authorization_code: valid code + verifier + same client + same redirect -> access (1 h) +
  refresh (30 d); code is single use (second use -> `invalid_grant` and the tokens from the first use are revoked).
  Wrong verifier/client/redirect or expired code (60 s) -> `invalid_grant`.
- **AC-19-27 [BE]** `/token` refresh_token rotates (old refresh dead, new pair). Replaying a used refresh token ->
  `invalid_grant` AND the whole grant revoked (event `refresh_reuse`).
- **AC-19-28 [BE]** `/revoke` (RFC 7009) on an access or refresh token -> the grant's tokens are dead; always 200.
- **AC-19-29 [BE]** Tokens are stored only as SHA-256 hashes; no token, assertion or secret appears in logs or in
  the call_log.
- **AC-19-30 [BE]** A grant re-consented by the same user+client reuses the active grant row (new tokens); a revoked
  grant is never reactivated (new row).

## S4 - MCP endpoint (`POST /mcp/<product>`, Streamable HTTP, stateless JSON)

- **AC-19-40 [BE]** `initialize` returns serverInfo + `tools` capability; `ping` ok; `notifications/initialized` 202;
  any other method -> JSON-RPC `-32601`.
- **AC-19-41 [BE]** `tools/list` returns the manifest tools (name, title, description, inputSchema, annotations)
  minus any tool not `readOnlyHint=true`/`destructiveHint=false`. The manifest is fetched with a signed call
  (`tool=""`, empty `sub`), cached 15 min, and the last good copy is served when the product is down.
- **AC-19-42 [BE]** `tools/call` with args failing `input_schema` (incl. any extra property) -> `-32602`, nothing sent.
- **AC-19-43 [BE]** A valid call goes to `api_base + path_template` verbatim (trailing slash kept), path params
  percent-encoded `safe=""`, only manifest `query_params` sent in manifest order, POST body = remaining args as
  JSON, `Authorization: Connector <call JWT>` whose `req_hash` matches what the product recomputes from the
  received request, `tool` = the tool name, `sub` = grant product user id, `consented_at` = grant consented_at.
- **AC-19-44 [BE]** Product 200 JSON -> MCP result content (text JSON); text over 120 000 chars or a list over 1000
  rows is cut and marked `truncated: true` with the original counts.
- **AC-19-45 [BE]** Error mapping per card section 5: 401 family -> one retry with a fresh token then tool error;
  403 `connector_access_removed`/`user_inactive`/`reconsent_required` -> grant revoked (reason = code) + tool error,
  next call 401; other 403/404/413/422/429/5xx/timeout/refused -> tool error, grant stays.
- **AC-19-46 [BE]** Every `tools/call` writes one call_log row (grant, user, tool, args capped 4 KB, status,
  ms, rows, chars, error code) committed BEFORE the response; if the write fails the client gets a tool error with
  no product data (fail-closed).
- **AC-19-47 [BE]** Bearer for product A used on `/mcp/B` -> 401; a token of a revoked/expired grant -> 401; a grant's
  `last_used_at` updates on use; a grant idle 90 d is Expired by the prune and its tokens die.
- **AC-19-48 [BE]** Throttle per grant on `tools/call` (429 + `Retry-After` over the limit).

## S5 - Admin API + perms

- **AC-19-50 [BE]** `GET /connector/grants` (perm `connector.read`) lists only the caller tenant's grants, paginated,
  filter by status/product/search; `GET /connector/grants/{id}/activity` lists its call_log + events.
- **AC-19-51 [BE]** `POST /connector/grants/{id}/revoke` and bulk revoke (perm `connector.manage`) revoke + kill tokens,
  event `revoked_by_admin` with the actor; another tenant's grant id -> 404.
- **AC-19-52 [BE]** `GET /connector/products` (read) shows key, MCP URL, consent URL, API base, manifest version,
  fetched-at, tool count, secrets as `set`/`missing` only; `POST /connector/products/{key}/refresh-manifest` (manage).
- **AC-19-53 [BE]** Module install grants `connector.read/manage` to the tenant Admin; a grant sweep covers tenants
  that installed before.
- **AC-19-54 [BE]** call_log rows older than `CONNECTOR_CALL_LOG_RETENTION_DAYS` (default 180) are pruned by the beat.
- **AC-19-55 [BE]** When a manifest refresh fails, the last good manifest keeps serving and `GET /connector/products` reports `stale: true` with the error and last good fetched-at.

## S6 - UI (after mock approval)

- **AC-19-60 [FE]** Settings > Claude connector > Grants on the Resource shell: columns, Active|Revoked|Expired
  segments, row + bulk Revoke (typed confirm on bulk), detail with Activity tab; hidden without `connector.read`.
- **AC-19-61 [FE]** Products tab read-only with copy MCP URL and Refresh manifest (manage only).
- **AC-19-62 [FE]** Works at 1280 and 375 px, no horizontal scroll, no instructional copy.

## S7 - End to end

- **AC-19-70 [E2E]** Local joint run: SS lane + sorento `claude/analytics-connector-e2jret` on local copies, an MCP
  client drives DCR -> authorize -> sorento consent (real login) -> token -> `tools/list` -> a reused tool and a
  chat tool -> sorento audit row + SS call_log row; then sorento "log out other devices" -> `reconsent_required`
  -> SS grant Revoked.
