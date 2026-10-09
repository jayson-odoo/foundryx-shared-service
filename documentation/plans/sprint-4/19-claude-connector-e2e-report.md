# 19 Claude connector: joint SS x Sorento end-to-end report (AC-19-70)

Date 2026-10-10. SS: branch claude/ss-connector-module-23ogqg @ 2bd069d7, backend :8031, DB foundryx_service_ssconn
(connector module installed for tenant `default`). Sorento: origin/main 55f6e567e (#1547), detached worktree, backend :8032,
DB sorento_ssconn_e2e (clone of a local dev DB, copy only), Redis db 13, connection id `ss-e2e`, fresh random secrets.
Driver: scratch httpx script, every step asserted. No tokens, secrets, names, emails or customer data recorded here.

## Setup notes
- Sorento: the clone's alembic stamp was a multi-row stamp from another branch. To prove the real migration, the
  connector objects (users.connector_revoked_at, permission, analytics_connector views) were dropped, the stamp set to
  `oihr_0005_print_one_page`, and `alembic upgrade head` ran `oihr_0005_print_one_page -> acc_0001_connector`
  cleanly; 4 views and the `analytics.connector.use` permission were recreated. Head = acc_0001_connector.
- SS: `scripts.bootstrap_db` was needed first (ideation drift guard refused start at 0002 vs 0016). Then the SS app
  started clean and the connector products load (`CONNECTOR_PRODUCTS=sorento`).
- Test user: an ACTIVE staff user moved to a cloned non-admin role `e2e_connector` (all former Admin permissions plus
  `analytics.connector.use` and `system.chat_history.view`). Reason: sorento's `check_user_has_permission` returns
  True for the `admin` role slug, so the chat-history denial cannot be shown with an Admin role (see Findings).

## Results
| Step | Result | Evidence |
|---|---|---|
| a | PASS | POST /mcp/sorento no token: 401 with `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp/sorento"`; both .well-known docs 200 (AS metadata lists authorization/token/registration/revocation endpoints, S256) |
| b | PASS | DCR with the claude.ai redirect: 201, client_id issued |
| c | PASS | authorize (PKCE S256 + state): 302 to the consent URL with `req`; `fx_connector_bind` cookie set |
| d | PASS | sorento staff login 200; consent/inspect 200 `allowed=true`; consent/approve 200, `return_url` equals the SS callback `http://localhost:8031/mcp/sorento/oauth/consent-return`, assertion present |
| e | PASS | POST request_id+assertion with bind cookie: 302 to `https://claude.ai/api/mcp/auth_callback` with code, state echoed |
| f | PASS | /token code+verifier: 200, Bearer, expires_in 3600, access+refresh issued |
| g | PASS | tools/list: 39 tools (34 reused + 5 chat: chat_list_datasets, chat_describe_dataset, chat_query, chat_search_messages, chat_get_conversation). Sorento's own manifest also reports 39. No tool hidden by SS |
| h | PASS | tools/call crm_master_brands_list: 200, isError absent, ~5.3k chars of data. chat_list_datasets: 200, 4 datasets. SS `app_connector.call_log`: rows `crm_master_brands_list ok 200`, `chat_list_datasets ok 200`. Sorento `audit_logs` EVENT `connector.tool_call` rows written for each ok call (tool + status per row; audit_logs is append-only so totals accumulate across my reruns: 26 rows total, not cleanable) |
| i | PASS | role loses `system.chat_history.view`: chat_list_datasets returns tool error "This user may not read chat history." (HTTP 200 JSON-RPC isError=true); call_log row `chat_list_datasets error chat_history_not_permitted 403`; grant stays `active`. Perm restored, next call ok |
| j | PASS | `user_session_service.revoke_all_for_user` run for the user (sets users.connector_revoked_at). Next tools/call: isError, SS grant -> `revoked` / `reconsent_required` (grant_events has `revoked`); call_log `crm_master_brands_list error reconsent_required 403`; following call HTTP 401 |
| k | PASS | refresh_token grant: 200, new access AND refresh differ from the originals, new tokens work for tools. Replaying the OLD refresh token: 400 `invalid_grant` and the whole grant is revoked (`refresh_reuse`, grant_events `refresh_reuse`) |

Also: unsigned GET sorento /api/v1/connector/manifest = 401.

## Findings (not SS defects)
1. Sorento RBAC cache (30s `RBAC_CACHE_TTL_SECONDS`) applies to the chat-history check, so a permission removed mid-session
   takes up to 30s to deny (the connector.use check is uncached as documented). Test slept 33s. Worth one line in the contract.
2. Sorento treats role slug `admin` as holding every permission for `chat_history.view`, so Admin users always pass the chat gate.
3. The `reconsent_required` tool error text on the first post-revoke call reads as the user-facing message; the code is in
   call_log.error_code and the grant revoke reason, not in the MCP text.
4. A first run of the script accidentally replayed an old refresh token mid-flow, which correctly revoked the grant
   (`refresh_reuse`); that is now the documented k replay result above.

## Teardown
Both servers (pids recorded, started by me) stopped; sorento worktree removed. DBs kept: foundryx_service_ssconn,
sorento_ssconn_e2e (Redis db 13 left). Nothing committed.

## Run 2 (automated client)

Script `service_backend/scripts/connector_e2e.py` (runbook `19-claude-connector-e2e-runbook.md`), 2026-10-10.
SS code = af9f7458 (branch claude/ss-connector-module-23ogqg): the run used 51464768 plus the then-uncommitted
tunnel-config edits, committed unchanged as af9f7458 (`git diff af9f7458 -- service_backend/modules` empty).
Sorento origin/main 55f6e567e (#1547), detached worktree. Local copies only: SS :8031 (DB foundryx_service_ssconn),
sorento API :8032 + web :3032 (DB sorento_ssconn_e2e), no tunnels, nothing pushed. CONSENT_MODE=browser (sorento
frontend started from the worktree with `next dev`; real sign-in form and Allow click via agent-browser).

| Step | Result |
|---|---|
| 1 401 + discovery | PASS |
| 2 DCR | PASS |
| 3 PKCE authorize -> product consent | PASS |
| 4 consent bounce (browser, real sorento page) | PASS |
| 5 token exchange | PASS |
| 6 initialize + tools/list (39, read-only) | PASS |
| 7 tools/call (3 reused crm_* + 4 chat tools) | PASS |
| 8 output caps | PASS (120 000-char cap with marker); 1000-row cap not reachable on this data (the product caps at 1000), covered by unit tests |
| 9 no phones / OTP masked | PASS (11 masked codes returned, none raw) |
| 10 refresh rotation + replay -> grant revoked (refresh_reuse) | PASS |
| 11 RFC 7009 revoke | PASS |
| 12 access expiry, refresh still works | PASS |
| 13 reconsent_required | PASS |
| 14 connector_access_removed | PASS |
| 15 fail-closed audit | PASS |
| 16 audit rows both sides | PASS |

Totals: pass 16, fail 0, deferred 0 (row cap sub-clause noted in step 8).

Finding (not a failure): free message text returned by `chat_get_conversation` for a bot/staff delivery message carries
third-party phone numbers typed into the message body ("Contact Number: ..."). The views exclude phone columns and the
ruling allows raw text, so step 9 only fails on phone keys or phone values in structured fields.

### Known, accepted behaviour (owner ruling 9 Oct, relayed by crew 10 Oct)

`chat_get_conversation` / `chat_search_messages` return raw message bodies; phone numbers that customers typed inside a
message stay visible. Ruling (a): no masking of free text, raw message text allowed, authorized staff only (the user must
hold `analytics.connector.use` and `system.chat_history.view`). Structured phone fields stay excluded and OTP codes stay
masked (`******`) as built. No sorento masker change.
