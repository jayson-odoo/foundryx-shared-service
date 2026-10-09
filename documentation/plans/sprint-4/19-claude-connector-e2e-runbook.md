# 19 Claude connector: automated end-to-end client runbook

`service_backend/scripts/connector_e2e.py` does what claude.ai does (401 discovery, DCR, PKCE authorize, consent bounce
through the product, token exchange, MCP initialize / tools/list / tools/call, refresh rotation, RFC 7009 revoke) and then
the lifecycle fault-injection steps, against LOCAL copies of shared-service (SS) and sorento. One PASS/FAIL/DEFERRED
line per step, exit code non-zero on any FAIL. stdlib + httpx only (use the SS venv); `psql` and `agent-browser` on PATH.
No public tunnels. Never point it at prod. It prints no tokens, codes, emails or passwords.

## 1. Local copies (ports reserved: SS 8031, sorento API 8032, sorento web 3032)

Databases are COPIES: an SS database with the connector module installed for tenant `default`, and a clone of a sorento
dev DB at sorento main (migration `acc_0001_connector`, the `analytics.connector.use` permission and the
`analytics_connector` views present). Test user: an ACTIVE sorento user whose role is NOT `admin` (slug `admin` bypasses
the chat-history permission check) and holds `analytics.connector.use` and `system.chat_history.view`.

Generate two random secrets (different) and export them to both sides:

| Variable | SS (`CONNECTOR_SORENTO_*`) | Sorento backend (`CONNECTOR_*`) |
|---|---|---|
| ss-to-product secret | `..._SS_TO_PRODUCT_SECRET` | `CONNECTOR_SS_TO_PRODUCT_SECRET` |
| product-to-ss secret | `..._PRODUCT_TO_SS_SECRET` | `CONNECTOR_PRODUCT_TO_SS_SECRET` |
| connection id | `..._CONNECTION_ID=ss-e2e` | `CONNECTOR_CONNECTION_ID=ss-e2e` |
| callback | n/a | `CONNECTOR_SS_CALLBACK_URL=http://localhost:8031/mcp/sorento/oauth/consent-return` |

SS (from `service_backend/`, own venv; `PUBLIC_BASE_URL` must be the SS origin the client uses):
```
export DATABASE_URL=postgresql://<app role>@localhost:5432/<ss copy db>
export PUBLIC_BASE_URL=http://localhost:8031 CONNECTOR_PRODUCTS=sorento
export CONNECTOR_SORENTO_TENANT_SLUG=default CONNECTOR_SORENTO_CONNECTION_ID=ss-e2e
export CONNECTOR_SORENTO_CONSENT_URL=http://localhost:3032/connect/claude
export CONNECTOR_SORENTO_API_BASE_URL=http://localhost:8032
export CONNECTOR_SORENTO_SS_TO_PRODUCT_SECRET=... CONNECTOR_SORENTO_PRODUCT_TO_SS_SECRET=...
python -m scripts.bootstrap_db          # once, then install the connector module for the default tenant
.venv/bin/python -m uvicorn app.main:app --port 8031
```
Sorento backend (worktree of origin/main, `.env` pointing at the copy DB, `CORS_ORIGINS` incl. `http://localhost:3032`,
`REDIS_URL` on a spare redis db, the four `CONNECTOR_*` values above):
```
cd sorento_crm_backend && ../../sorento_crm/sorento_crm_backend/venv/bin/python -m uvicorn app.main:app --port 8032
```
Sorento frontend (`.env.local`: `DATABASE_URL` and `DIRECT_URL` BOTH at the local copy DB, never a remote host,
`FASTAPI_INTERNAL_URL=http://localhost:8032`, `NEXTAUTH_URL=http://localhost:3032`, own `NEXTAUTH_COOKIE_SUFFIX`):
```
cd sorento_crm_frontend && npm ci --force && npx next dev -p 3032
```
Check each port's owner before and after: `lsof -p $(lsof -ti :PORT -sTCP:LISTEN) | grep cwd`. Stop only your own pids.

## 2. Run
```
export SORENTO_LOGIN_EMAIL=<test user> SORENTO_LOGIN_PASSWORD=<its password>
export SS_DB_URL=postgresql:///<ss copy db>        # SUPERUSER: steps 12, 15, 16
export SORENTO_DB_URL=postgresql:///<sorento copy> # steps 9 (evidence), 14, 16
export CONSENT_MODE=browser                        # or api
service_backend/.venv/bin/python service_backend/scripts/connector_e2e.py
```
Optional: `SS_BASE`, `SS_PRODUCT`, `SORENTO_API`, `SORENTO_WEB`, `SS_APP_ROLE` (default `foundryx`), `EXPECT_TOOLS` (39),
`RBAC_WAIT` (35 s).

`CONSENT_MODE=browser` drives the real sorento sign-in form and Allow button with `agent-browser` (own session, closed
at the end) starting from the SS authorize URL, so the SS binding cookie is set in that browser like claude.ai does.
The claude.ai callback request is aborted in the browser and its URL (code + state) is read from the request log.
Reconnects after the revoke steps use the api path (product API login + inspect/approve + form POST).
Without `SS_DB_URL` steps 12, 15, 16 are DEFERRED; without `SORENTO_DB_URL` step 14 is DEFERRED.

## 3. What each step asserts
1 401 + `WWW-Authenticate resource_metadata`; discovery documents; only discovered endpoints used afterwards.
2 DCR (claude.ai redirect, auth method none). 3 PKCE S256 authorize -> 302 to the product consent page.
4 consent bounce. 5 token exchange. 6 initialize + tools/list: 39 tools, all `readOnlyHint`.
7 reused `crm_*` reads + the four chat tools. 8 120 000-char cap with the `truncated` marker (the 1000-row cap is
DEFERRED unless some route returns more than 1000 rows). 9 no phone keys or phone values in structured fields, OTP
codes masked as `******` after `sign-in|verification code is`. 10 refresh rotation, old-refresh replay -> `invalid_grant`
and the grant revoked. 11 RFC 7009 revoke -> next call 401. 12 aged access token -> 401, refresh works. 13 product
"sign out other devices" -> tool error, grant `reconsent_required`, then 401. 14 `analytics.connector.use` removed from
the user's roles -> tool error, grant `connector_access_removed` (permission restored in a `finally`). 15 `REVOKE INSERT`
on `app_connector.call_log` from the SS app role -> "could not be recorded", no data (`GRANT` restored in a `finally`).
16 SS `call_log` and sorento `audit_logs` `connector.tool_call` rows exist for the run.

## 4. Teardown
Stop the three servers you started, remove the sorento worktree if it is disposable, leave the copy DBs. `audit_logs` is
append-only, so sorento rows accumulate across runs.
