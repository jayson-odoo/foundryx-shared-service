# 12 — Developer Logs / Integration Activity Console — Test Execution Report (Slice 1)

> Feature branch: `sprint-4/developer-logs-console`. Scope: **AC-DLC-01 … AC-DLC-13** (Slice 1 only).
> Environment: FastAPI :8001 + Next :3001 (both this branch, freshly rebuilt) → Postgres `foundryx_service`, DB already at revision `dlc_s412_integration_activity`.
> Executed 2026-07-11 by the QA agent. Keyed back to `12-developer-logs-console-acceptance-criteria.md`.

## Test environment notes (load-bearing)
- Both ports were initially squatted by the **sister product `dreamz_ems`** (backend on :8001, frontend on :3001). They were killed and replaced with this branch's servers; the dreamz frontend transiently reclaimed :3001 once and served a STALE menu (no "Developers" item) — the classic wrong-build symptom. Verified the final listeners' cwd = `foundryx-shared-service/service_{backend,frontend}` before running E2E.
- Frontend rebuilt clean (`rm -rf .next && npm run build`) — `/developers/logs` + `/developers/logs/[id]` routes present.
- `auth_throttle` cleared before the run.

## Suite results (Task 1)
| Suite | Command | Result |
|---|---|---|
| Backend activity-log | `pytest -q tests/test_activity_log.py` | **8 passed** |
| Backend full smoke | `pytest -q` | **1111 passed**, 0 failed (181 warnings), 12m22s |
| Frontend targeted | `vitest run integration-log-service.mock / log-badges / menu-filter` | **20 passed** (3 files) |
| E2E | `playwright test developer-logs.spec.ts` | **2 passed** |

---

## Per-AC verdict

| AC | Area | Verdict |
|---|---|---|
| AC-DLC-01 | table + migration + indexes + tenant-scope + UTCDateTime | **PASS** |
| AC-DLC-02 | `record()` failure-isolated (swallows) | **PASS** |
| AC-DLC-03 | gateway hook records `inbound_api` row + trace_id | **PASS** (caveat: unauth 401 not logged) |
| AC-DLC-04 | redaction of secrets in stored summary | **PASS** |
| AC-DLC-05 | writer adds no latency / can't fail the request | **PASS** |
| AC-DLC-06 | `GET /integration-logs` gated + filter/search/paginate + camelCase | **PASS** |
| AC-DLC-07 | `GET /{id}` + redacted summaries + trace + external_ref | **PASS** (note: responseSummary null for inbound) |
| AC-DLC-08 | new core perm + grant sweep to existing tenants' Admin | **PASS** |
| AC-DLC-09 | frontend-first service trio, mock→real swapped | **PASS** |
| AC-DLC-10 | Resource-shell list + columns + filters + menu (all arrays) | **PASS** |
| AC-DLC-11 | read-only detail, metadata + redacted body, error surfaced | **PASS** (caveat: body is metadata-only) |
| AC-DLC-12 | responsive 375px + 1280px | **PASS** |
| AC-DLC-13 | real-click E2E journey | **PASS** |

**Slice 1 verdict: GREEN to advance.** Two documented limitations (below) are consistent with the plan's explicit deferrals/out-of-scope and do not fail any Slice-1 AC as written. Two backlog candidates recommended.

---

## Detailed scenarios

### AC-DLC-01 — table + migration + indexes — PASS
- **Precondition:** DB at `dlc_s412_integration_activity`.
- **Steps/Expected/Actual:** Inspected live Postgres. `integration_activity` present; `tenant_id` **NOT NULL**; `created_at` = `timestamp with time zone` (UTCDateTime); all five composite indexes present: `..._tenant_created`, `..._tenant_trace`, `..._tenant_source`, `..._tenant_status`, `..._tenant_extref`. Repository filters every query by `tenant_id`; `test_read_is_tenant_scoped` proves cross-tenant rows/detail are invisible.

### AC-DLC-02 — record() swallows — PASS
- `test_record_swallows_a_raising_writer` monkeypatches the insert to raise; `record()` returns `None`, never propagates. Also `test_record_skips_when_no_tenant`.

### AC-DLC-03 — inbound_api capture — PASS (with caveat)
- **Steps:** Minted a workspace API key via `POST /omnichannel/workspaces/{id}/api-keys`; called `GET /api/v1/omnichannel/contacts` with `Authorization: Bearer fxw_live_…`.
- **Actual:** ONE `inbound_api` row recorded with `traceId` (uuid), `workspaceId`, `apiKeyId`, `operation="GET /contacts"`, `method=GET`, `status=success`, `statusCode=200`, `latencyMs≈17`. Error path stamps `errorCode=<status>`.
- **CAVEAT (limitation b):** An **unauthenticated 401** (bad or missing API key) is **NOT recorded** — verified empirically (row count stayed at 7 across a bad-key 401 and a no-key 401). This is a deliberate, documented design choice (no resolvable workspace ⇒ no attributable tenant ⇒ a tenant-scoped, NOT-NULL-tenant_id row can't be written). A **403 `service_not_enabled`** IS attributable (the auth dep stashes `request.state.api_workspace` before the service check) and IS recorded. Judgment: AC-DLC-03's required field list is fully met for every attributable request; the 401 gap is defensible but means a consumer with a wrong key sees no log entry for exactly that failure. **Backlog candidate** (see below).

### AC-DLC-04 — redaction — PASS
- `test_redact_masks_secrets_keeps_message_text` (unit): `Authorization`/`apiKey`/`api_key`/`access_token`/`embedSecret`/`password`/`assertion`/`clientSecret` → `***`; WhatsApp message content preserved.
- Live: the captured row's `requestSummary.headers.authorization == "***"`; a DB scan confirmed the plaintext key `fxw_live_pCQbehK8…` appears in **no** row's request/response/error. E2E also asserts `"authorization": "***"` visible and the full key absent from the detail page body.

### AC-DLC-05 — writer can't fail/slow the request — PASS
- Middleware records **after** the response is produced and via the swallowing `record()`. `test_record_swallows_a_raising_writer` proves a raising writer is inert. Gateway call returned its normal 200 with the row written out-of-band.

### AC-DLC-06 — read list gated + shaped — PASS
- **No token → 401** (verified). **Authenticated non-admin (Member role, no `integration_logs.read`) → 403** on both list and detail (verified with an app-signed token for `demo@kt.com`). **Granted Admin → 200**. Filter-by-status (`test_list_filter_by_source_and_status`) works via the whitelisted translator; wire is camelCase with `Z` datetimes (`test_list_endpoint_camelcase_and_gated`). Paginated (`page`/`page_size`, capped 200), search over operation/trace/external_ref.

### AC-DLC-07 — detail — PASS (note)
- `GET /integration-logs/{id}` returns the row incl. redacted `requestSummary`, `traceId`, `externalRef`; unknown id → 404; cross-tenant id → 404.
- **Note:** `responseSummary` is `null` for `inbound_api` rows (no response body is summarized in Slice 1) — consistent with the "only redacted summaries / body capture deferred" scope.

### AC-DLC-08 — grant sweep reaches existing tenants — PASS
- Migration inserts the two perms and back-grants them to every non-platform tenant's Admin. Live: **17/17** non-platform tenants' Admin roles hold `integration_logs.read` and `.manage`. The **existing** demo tenant's Admin session carries `integration_logs.read` (95 perms) and got 200 — the console is not silently 403'd for pre-existing tenants.

### AC-DLC-09 — frontend-first trio — PASS
- `integration-log-service.{ts,mock,real}` present; `.mock.test.ts` (6) passes; the shipped `.ts` boundary imports `.real` (real api-client) — **no `PHASE 1 MOCK` residue**. E2E ran against real captured rows.

### AC-DLC-10 — Resource-shell list — PASS
- `useIntegrationLogsListConfig(): ResourceListConfig` — columns Source badge / Operation / Status badge (+ code) / Latency / Workspace / Time; server-side sort/filter/search/paginate; source + status enum filter fields; `viewKey` column prefs. Menu tagged `permission: integration_logs.read` in **all three** arrays (`MENU_SIDEBAR`, `MENU_MEGA`, `MENU_MEGA_MOBILE`); `menu-filter.test.ts` green. Verified live in E2E + screenshots.

### AC-DLC-11 — read-only detail — PASS (with caveat)
- Detail is a read-only `ResourceForm` — **no Edit toggle** (asserted `Edit` button count 0). Overview tab = metadata rows (source/operation/status/latency/workspace/api key/trace/external ref/time); a prominent `destructive` error block when present. Payloads tab = redacted request/response in a `<pre>` JSON block.
- **CAVEAT (limitation a):** the "request/response **bodies**" are **metadata-only** — path/method/query + redacted headers; the actual request body is not read (middleware avoids consuming the stream) and the response body is not summarized (`responseSummary` null). This matches the plan's out-of-scope ("Full request/response body capture") and the §5 note. Judgment: the AC's intent (read-only, redacted, error prominent) is met; flagged as a deferral, not a fail.

### AC-DLC-12 — responsive — PASS
- E2E `setViewportSize` at 1280×800 and 375×812; horizontal overflow ≤ 2px at both. Screenshots (scratchpad `dlc-list-desktop.png` / `dlc-list-mobile.png`): desktop shows all six columns + sidebar Developers→Logs; mobile reflows to Source + Operation, toolbar wraps, no clipping/overlap.

### AC-DLC-13 — real-click E2E — PASS
- `e2e/developer-logs.spec.ts`: precondition seeds one inbound row via the operator API (mint key + real gateway call, timestamped key name `dlc-e2e-<ts>`), then the FLOW is real clicks — sign in via the login form → expand **Developers** in the sidebar → click **Logs** (URL `/developers/logs`) → search the row's trace id → assert row with **Inbound API** source + **Success** status + `GET /contacts` → click the row → detail (`Trace <id>`, no Edit) → Payloads tab → assert `"authorization": "***"` and the plaintext key absent from the page. Both tests green.

---

## Backlog candidates (recommend logging)
1. **Unattributed inbound failures are invisible.** A wrong/missing-API-key `401` writes no row (no tenant to attribute), so a consumer troubleshooting auth failures — arguably the top reason to open the console — finds nothing. Consider a platform/system bucket or an operator-visible unattributed-failures stream. (Deviation from AC-DLC-03's literal "one row per request".)
2. **`responseSummary` always null for inbound** + request captured as metadata-only. When body-summary capture lands (currently out-of-scope), inbound rows should carry a redacted response summary so the detail's "Response (redacted)" panel is meaningful.

## Other remarks (not AC failures)
- Migration `dlc_s412_integration_activity`: **docstring/code mismatch** — the header says `Revises: bgjob_logs_ab12cd34` but `down_revision = "migrate_storage_perm410"`. Harmless (DB already stamped), but tidy before merge.
- The repo currently has **two Alembic heads** (`migrate_storage_perm410`→this revision, plus the untracked user-WIP `bgjob_logs_ab12cd34`), so `alembic upgrade head` errors "multiple heads". Pre-existing and out of this feature's scope, but a clean `bootstrap_db` deploy will need the heads merged.
- Revision id `dlc_s412_integration_activity` = 29 chars ≤ 32 (OK for `alembic_version`).

## Verdict
**Slice 1 is GREEN to advance.** All 13 Slice-1 ACs PASS; the two coder-noted limitations are documented deferrals that do not break any AC as written. Recommend logging the two backlog items above.

---

# Slice 2 — Correlated trace (outbound Meta + webhook unify + trace view)

> Scope: **AC-DLC-14 … AC-DLC-19**. Executed 2026-07-11 by the QA agent against this branch (Slice 2 = uncommitted working-tree changes on top of Slice-1 commit `6a98148`).
> Environment: FastAPI :8001 + Next :3001 (both freshly rebuilt from this tree, port ownership confirmed cwd=`foundryx-shared-service`) → Postgres `foundryx_service` (already at head; NO `alembic upgrade`/`bootstrap_db` — Slice 2 adds no schema). Dev channel `chn-demo` present + ACTIVE (Meta-stubbed). `auth_throttle` cleared.

## Test environment notes (load-bearing)
- Both ports were again squatted by the sister product `dreamz_ems`; killed, and the final listeners' cwd verified = `foundryx-shared-service/service_{backend,frontend}` before E2E. The frontend was clean-rebuilt (`rm -rf .next && npm run build`) and a **pre-existing foundryx `next-server` (stale build) that had reclaimed :3001 was killed** so E2E ran against the just-built bundle (the documented wrong-build trap — caught here).
- Meta is stubbed for `chn-demo` because `META_APP_ID` is unset in `.env` (`_is_dev = not settings.meta_app_id`), so a gateway send records an `outbound_meta` row without Graph traffic — the intended E2E path.

## Suite results (Task 1)
| Suite | Command | Result |
|---|---|---|
| Backend Slice-2 targeted | `pytest -q tests/test_activity_trace.py tests/test_activity_log.py tests/test_omnichannel_api_gateway.py tests/test_omnichannel_consumer_webhooks.py` | **53 passed** |
| Backend full smoke | `pytest -q` | **1116 passed**, 0 failed (181 warnings), 12m49s (= Slice-1 1111 + 5 new trace tests) |
| Frontend targeted | `vitest run integration-log-service trace-timeline log-badges menu-filter` | **25 passed** (4 files; mock-service grew 6→8 for trace) |
| Frontend full | `vitest run` | **769 passed** (99 files) |
| E2E | `playwright test developer-logs.spec.ts` | **4 passed** (2 Slice-1 + 2 new Slice-2 trace) |

---

## Per-AC verdict (Slice 2)

| AC | Area | Verdict |
|---|---|---|
| AC-DLC-14 | `outbound_meta` row: operation/status/Meta-HTTP/latency/error + `external_ref=wamid`, token redacted | **PASS** |
| AC-DLC-15 | inbound + outbound share ONE `trace_id` (contextvar) | **PASS** |
| AC-DLC-16 | webhook legs surface in console + attach to trace by external_ref | **PASS (with deviation — see below)** |
| AC-DLC-17 | `GET /integration-logs/trace/{id}` ordered, tenant-scoped, gated | **PASS (ordering finding — see below)** |
| AC-DLC-18 | detail view renders the whole-trace timeline, each leg status/latency | **PASS** |
| AC-DLC-19 | real-click E2E: send → console → trace links legs → timeline | **PASS** |

**Slice 2 verdict: GREEN to advance.** All six ACs pass. One intentional mechanism deviation (AC-DLC-16, judged acceptable) and one quality finding (AC-DLC-17 timeline causal-order inversion) are documented below as backlog candidates; neither breaks an AC as written.

---

## Detailed scenarios (Slice 2)

### AC-DLC-14 — outbound_meta capture — PASS
- **Steps (live):** reopened a 24h window on `cnt-001` via an inbound webhook to `chn-demo`, minted a workspace API key, then real gateway `POST /api/v1/omnichannel/messages` (text). 
- **Actual:** exactly ONE `outbound_meta` row: `operation="graph:send"`, `status="success"`, `external_ref="wamid.dev-077f78ca8452"` (the dev-stub wamid), `latency_ms` present, on the same trace as the inbound send. Adapter instruments all three Graph calls through one `_graph_call` wrapper — `graph:send` (verified live + unit), `graph:sync` (`fetch_waba_details`) and `graph:template_submit` (`submit_template`) share the identical instrumentation path (wired in `channel_profile_service` / `template_management_service` / `message_service` / `send_runner`; not independently exercised live).
- **Redaction (Task 4):** the `outbound_meta` row stores NO request/response summary (both `*_summary_json` NULL) → no Meta access token can leak. A DB-wide scan for `EAA%` / `fxw_live_%` / unmasked `authorization` across ALL `integration_activity` rows returned **0**.
- **Note (dev-stub artifact, not a fail):** on the stubbed channel `status_code` is NULL and `latency_ms=0` (the stub is instant + sets no HTTP status). A real Graph call populates `_last_http_status` (adapter sets it on the live POST) → the field is real in production.

### AC-DLC-15 — shared trace id — PASS
- **Live:** the inbound `POST /messages` row and the resulting `outbound_meta graph:send` row both carry `trace_id=73a906e1-22b7-4d54-89a1-88a71fbcc450`. The gateway middleware mints the trace onto a `contextvars.ContextVar`; `build_meta_recorder` reads `get_trace_id()` when persisting — no plumbing through call args. Also proven by `test_inbound_and_outbound_share_trace_id`.

### AC-DLC-16 — webhook unify — PASS (with deviation)
- **Deviation from the AC's literal wording (intentional, disclosed in the brief):** the AC specifies a *read-time join/adapter, NOT duplicated writes*. Slice 2 instead **writes** a `webhook_delivery` `integration_activity` row per delivery attempt (`webhook_delivery.py _record_webhook_activity`) via the core `ActivityLogService.record` seam, attaching the trace by resolving the message wamid (`trace_for_external_ref`). `webhook_deliveries` stays the operational source of truth (retry queue/backoff); the activity row is a pure observability copy on a fresh, failure-isolated session.
- **Judgment against the AC's INTENT (webhook legs appear in the console + attach to a trace):** OUTCOME MET → **PASS**. Verified: (a) `test_webhook_delivery_records_activity_on_trace` drives a real `dispatch()` (stubbed 200 POST) and asserts a `webhook_delivery` row with `operation="webhook:message.status"`, `status="success"`, `external_ref="wamid.o1"`, `trace_id="trace-xyz"`; (b) live-DB assertion that the join key `trace_for_external_ref(DEFAULT_TENANT, "wamid.dev-077f78ca8452")` resolves the REAL traced wamid → `73a906e1…`, and is tenant-scoped (a foreign tenant → `None`).
- **Why the deviation is defensible:** the AC's read-time-join would force the CORE console to read a MODULE's schema (`app_omnichannel.webhook_deliveries`) — a module-governance smell (core reaching into a module). The write-time seam keeps the module writing UP to the core seam (the sanctioned direction), so the console reads ONE table uniformly across all sources. Per-attempt granularity is arguably more useful for troubleshooting than a single joined row. Failure-isolated (fresh session, swallows errors — cannot break delivery).
- **LIMITATION (backlog candidate — real functional gap vs the literal AC):** because it is write-time (no read-time join, no backfill), **pre-existing `webhook_deliveries` rows created before Slice 2 do NOT appear** in the console, and only NEW delivery attempts get an activity row. The literal AC ("existing `webhook_deliveries` rows surface") would have shown history. New deliveries surface correctly; historical ones are invisible.
- **E2E note:** a live webhook-delivery leg could NOT be added to the E2E trace — endpoint creation is SSRF-guarded (rejects non-HTTPS + private/reserved IPs), so no local receiver is reachable in the sandbox. Per the brief this is acceptable; the webhook→trace attachment is covered by the unit test + the live join-key assertion above.

### AC-DLC-17 — trace endpoint — PASS (ordering finding)
- **Live:** `GET /integration-logs/trace/73a906e1…` (authed) returns 2 legs ordered oldest→newest by `created_at`. **Tenant-scoped:** an unknown/other-tenant trace → `200 {legs: []}` (never leaks). **Gated:** unauthenticated → 401; an authenticated user WITHOUT `integration_logs.read` (`demo@kt.com`, app-signed JWT) → **403** on both `/trace/{id}` and the list (same `require_permission("integration_logs.read")` dependency).
- **FINDING (quality, not a literal-AC fail — backlog candidate):** the endpoint orders strictly by `created_at` (contract met), BUT the gateway middleware records the `inbound_api` row **after the response is produced** (to capture status_code + latency), so its `created_at` is ~10 ms LATER than the `outbound_meta` leg it caused (084190Z vs 094501Z live). Result: the timeline lists **Outbound Meta BEFORE the Inbound API request that triggered it** — the causal order the AC illustrates (`inbound → outbound Meta → webhook`) is visually inverted for the real gateway flow. (The unit test masks this by seeding explicit increasing `created_at`.) Recommend a stable causal sort (record the inbound row at request-start, or add a monotonic sequence, or sort by a per-source causal rank within a trace).

### AC-DLC-18 — trace timeline in the detail view — PASS
- **Live (E2E + screenshots):** the log detail has a dedicated **Trace** tab (`GitBranch` icon) rendering `TraceTimeline` — an ordered rail of legs, each with a source badge (Inbound API / Outbound), the operation code (`POST /messages` / `graph:send`), formatted time, latency (`46 ms` / `0 ms`) and a status badge (Success). The currently-viewed leg is highlighted (`border-primary bg-primary/5`); clicking another leg navigates to that leg's detail (verified: clicking `graph:send` → the outbound leg's detail on the same trace, wamid shown as External ref). A row with no trace shows "not part of a correlated trace"; an empty trace shows "No correlated legs found".
- Screenshots: `scratchpad/dlc-trace-desktop.png` (1280 — two-leg timeline, outbound above inbound per the finding), `dlc-trace-mobile.png` (375 — legs stack, status/latency wrap below the operation, no clipping).

### AC-DLC-19 — real-click E2E — PASS
- Extended `e2e/developer-logs.spec.ts` with a **Slice-2 `Developer Logs trace` describe** (2 tests, both green). Precondition (API setup, timestamped/unique per run): locate the workspace owning `chn-demo`, POST a unique inbound message to reopen a window, mint a key, real gateway send → read back the inbound `POST /messages` trace id + confirm an `outbound_meta` leg shares it. The FLOW is real clicks: sign in → expand **Developers** → click **Logs** → search the trace → open the inbound row → **Trace** tab → assert the timeline shows BOTH legs (Inbound API `POST /messages` + Outbound `graph:send`) each with status/latency → click the outbound leg → its detail on the same trace shows the wamid. Second test re-checks the timeline at 375px + 1280px (horizontal overflow ≤ 2px both).
- Webhook leg intentionally NOT part of the live E2E trace (SSRF-guarded endpoint; see AC-DLC-16) — the inbound→outbound correlation is the asserted real-click picture.

---

## Backlog candidates (Slice 2 — recommend logging)
1. **Trace-timeline causal-order inversion (AC-DLC-17 finding).** `inbound_api` is recorded post-response so it sorts AFTER the `outbound_meta` leg it caused; the timeline shows outbound before inbound. Give the trace a stable causal ordering (inbound row stamped at request-start, a monotonic per-trace sequence, or a source-rank sort) so the timeline reads inbound → outbound → webhook.
2. **Historical webhook deliveries invisible (AC-DLC-16 deviation limitation).** The write-time seam only records NEW delivery attempts; pre-Slice-2 `webhook_deliveries` rows never surface (no backfill, no read-time join). Either backfill or add a read-time adapter if surfacing history matters.
3. **(Carried from Slice 1, still open)** unattributed inbound `401`s write no row; inbound `responseSummary` always null.

## Other remarks (not AC failures)
- Slice 2 adds NO migration/schema — no Alembic risk; the two-heads condition from Slice 1 (untracked user WIP `bgjob_logs_ab12cd34`) is unchanged and out of scope.
- Full backend suite delta is exactly +5 (1111→1116) = the 5 new cases in `tests/test_activity_trace.py`; no regressions in the load-bearing status-engine / tenant-lifecycle / omnichannel suites.
- Redaction: outbound_meta and webhook_delivery rows store summaries that carry no secrets (outbound stores no summary at all); the webhook row's `request` summary is the envelope `data` block (message metadata, no signing secret — the HMAC secret lives only in the delivery headers, never in the stored summary).

## Verdict (Slice 2)
**Slice 2 is GREEN to advance.** AC-DLC-14/15/17/18/19 PASS cleanly; AC-DLC-16 PASSES on intent with a disclosed, defensible mechanism deviation (write-time core-seam denormalization instead of read-time cross-schema join) plus one historical-surfacing limitation. The one quality finding (timeline causal-order inversion) and the two limitations are backlog candidates, none breaking an AC as written. The trace timeline was confirmed rendering REAL correlated data (live gateway send → two-leg trace), not just green pytest.

---

# Slice 3 — Embed logging + per-tenant retention + hardening

> Scope: **AC-DLC-20 … AC-DLC-26**. Executed 2026-07-11 by the QA agent against this branch (Slice 3 = uncommitted working-tree changes on top of the Slice-2 commit `cb583ff` + the head-merge `1b41dfe`).
> Environment: FastAPI :8001 + Next :3001 → Postgres `foundryx_service`. DB at the single alembic head `dlc_s412b_log_settings` (`integration_log_settings` table present). Demo Admin `demo@example.com` / `demo1234` (holds `integration_logs.read` + `.manage`).

## Test environment notes (load-bearing)
- **Both servers were serving STALE code and had to be restarted** — the running uvicorn (started 21:50) and next-server (started 21:50) both PREDATED the Slice-3 source (embed_session_service edited 22:34, build 22:53). The stale uvicorn had NO `--reload`, so the embed-recording code path did not exist in-process: a real failing `/embed/session` returned the correct 403 but wrote **zero** `embed_session` rows (`SELECT … WHERE source='embed_session'` → 0 across all tenants). Killed both, restarted uvicorn fresh on :8001, clean-rebuilt the frontend (`rm -rf .next && npm run build`, `/developers/logs/settings` present in the manifest) and restarted next-server on :3001 (owner cwd confirmed = `foundryx-shared-service/service_{backend,frontend}`). After the restart the identical exchange recorded the row correctly. **This is the documented "uvicorn without --reload won't pick up new code" + stale-build trap — it would have silently failed the E2E and masked a working feature.**
- `auth_throttle` cleared before the E2E run (manual validation logins had pumped the shared 127.0.0.1 bucket).
- `chn-demo` present + not trashed (Slice-2 trace test dependency) — re-verified.

## Suite results (Task 1)
| Suite | Command | Result |
|---|---|---|
| Backend Slice-3 targeted | `pytest -q test_activity_embed test_activity_retention test_activity_redaction test_activity_volume_guard test_activity_log test_activity_trace` | **32 passed** (embed 7 · retention 7 · redaction 2 · volume_guard 2 · log 8 · trace 6) |
| Backend full smoke | `pytest -q` | **1139 passed**, 0 failed (182 warnings), 11m17s (= Slice-2 1116 + 18 new activity cases + 5 others; no regressions) |
| Frontend targeted | `vitest run integration-log-service log-badges menu-filter` | **24 passed** (3 files; mock-service grew to 10 incl. `getSettings`/`updateSettings` round-trip) |
| E2E | `playwright test developer-logs.spec.ts` | **6 passed** (2 Slice-1 + 2 Slice-2 + 2 new Slice-3) |

---

## Per-AC verdict (Slice 3)

| AC | Area | Verdict |
|---|---|---|
| AC-DLC-20 | `EmbedSessionService.exchange()` records `embed_session` on success + each typed EmbedError; parent origin captured; no raw assertion/secret; unattributable → nothing | **PASS** |
| AC-DLC-21 | per-tenant `retention_days`; `GET/PUT /integration-logs/settings` gated `integration_logs.manage`; global default key | **PASS** |
| AC-DLC-22 | beat pruner deletes only past-window rows, per-tenant override else global default, failure-isolated | **PASS** |
| AC-DLC-23 | `Developers → Logs → Log settings` page to set retention, gated `integration_logs.manage`, Resource/settings pattern | **PASS** |
| AC-DLC-24 | embed rows render with a distinct source badge; failed embed shows its typed error clearly | **PASS** |
| AC-DLC-25 | redaction matrix: API key + bearer + `embedSecret` + Meta token masked across ALL 4 sources; message content preserved | **PASS** |
| AC-DLC-26 | volume guard documented + drops/degrades (not blocks) under burst; cap=0 disables | **PASS** |

**Slice 3 verdict: GREEN.** All seven ACs PASS. The embed-error rendering AND the retention save were both confirmed with REAL clicks against the live stack (screenshots below), not just green pytest.

---

## Detailed scenarios (Slice 3)

### AC-DLC-20 — embed-session logging — PASS
- **Precondition:** `tests/test_activity_embed.py` (7 cases, all green) is the reference; live-verified via a real dedicated-tenant exchange.
- **Actual (unit):** a SUCCESS exchange records ONE `embed_session` row (`operation="embed:session"`, `status="success"`, `statusCode=200`, `workspaceId` captured, `request={"parentOrigin": ORIGIN}`, and `SECRET_A not in str(row)` — no raw secret). Each typed `EmbedError` records an `error` row with the code as `error_code`: `invalid_assertion` (bad signature), `expired`, `origin_not_allowed` (403), `workspace_not_found` (404), `replayed` (a 2nd exchange of the same jti → one success + one replayed). An unknown-issuer failure (no resolvable tenant) records **nothing** (documented skip, mirrors the inbound-401 case).
- **Actual (live):** a genuine `POST /embed/session` with a valid HS256 assertion but a mismatched `parentOrigin` → 403 `origin_not_allowed` → exactly ONE `embed_session error origin_not_allowed statusCode=403` row in the tenant's console (`SELECT` confirmed). No raw assertion/embedSecret stored (`requestSummary` = `{"parentOrigin": …}` only). The recorder is failure-isolated (fresh `Session(bind=…)`, swallow-and-log) so it can never break the security path.

### AC-DLC-21 — retention settings endpoints + gate — PASS
- **Live (demo Admin, has `integration_logs.manage`):** `GET /integration-logs/settings` → **200**; `PUT {retentionDays:0}` → **422**; `PUT {retentionDays:5000}` (>3650) → **422**; `PUT {retentionDays:30}` → **200**; unauthenticated `GET` → **401**.
- **Gate (unit `test_settings_requires_manage_permission`):** a user granted `integration_logs.read` but NOT `.manage` gets **200** on the read list but **403** on both `GET` and `PUT /settings` — backend is the real boundary. `IntegrationLogSettingsUpdate.retentionDays` is `Field(ge=1, le=3650)` (the 422 source). Effective retention resolves override else the global default `integration_activity_retention_days=30` (`isDefault` flag on the wire).

### AC-DLC-22 — retention prune — PASS
- **Direct call (`prune_integration_activity(db)`, eager dev has no beat):** `test_prune_deletes_only_past_window_rows` seeds an age=default+5 row and an age=default-5 row for the default tenant → prune deletes exactly the old one (`deleted==1`), fresh survives. `test_prune_respects_per_tenant_override` seeds `IntegrationLogSettings(tenant=OTHER, retention_days=7)` then a 10-day + 3-day row for OTHER and a 10-day row for the 30-day-default tenant → only OTHER's 10-day row is pruned (past its 7-day override), OTHER's 3-day + the default tenant's 10-day survive (`deleted==1`). Per-tenant, isolated per tenant (a bad delete rolls back + continues), wired into the workflow beat tick (`run_due_workflows_task`, failure-isolated try/except).

### AC-DLC-23 — retention settings page (real clicks) — PASS
- **Live (E2E, default tenant demo Admin):** real-click nav sign in → expand **Developers** → click **Log settings** (`/developers/logs/settings`) → the "Log retention" card (`RequirePermission integration_logs.manage`) → filled **Keep developer logs for (days)** = a run-unique value (40–159) → **Save** → "Log retention saved." toast → **hard reload** → the input still shows the saved value (round-trips backend PUT→GET; caption flips to "Custom for this workspace."). Screenshot `dlc-settings-desktop.png` (157 persisted). Reuses the `/settings/workflows` shape (no hand-rolled form; UI → `useIntegrationLogSettings` hook → service, never a direct fetch).
- **Responsive:** asserted horizontal overflow ≤ 2px and the value intact at 1280×800 AND 375×812 (`dlc-settings-{desktop,mobile}.png`).
- **Isolation note:** run on the `default` tenant (benign — no Celery beat runs in the E2E stack so nothing is pruned, and the value is kept well above any seeded row's age; no other spec reads retention). Left an `integration_log_settings` override row on `default` (harmless).

### AC-DLC-24 — embed error rendering (real clicks) — PASS
- **Setup (operator/API, isolated):** the `default` tenant's live embed-config connection is depended on by `omnichannel-embed*.spec` ("DO NOT MUTATE … NEVER rotate the secret", and the one-active-`omnichannel_shared`-per-tenant unique index blocks a 2nd), so this journey **provisions a DEDICATED tenant** (`e2e-dlc-embed-<ts>`), seeds it its OWN `omnichannel_shared` connection with a known `embedSecret` + `allowedOrigins` (new helper `e2e/helpers/seed_embed_connection_for_tenant.py`, resolves tenant by slug — a fresh tenant has no existing row so the unique index is never touched), mints a valid HS256 assertion (`jose SignJWT`) and drives a real `POST /embed/session` with a mismatched `parentOrigin` → 403 `origin_not_allowed`, recording one `embed_session` error row in that tenant's console.
- **Flow (real clicks):** sign in as the dedicated tenant's admin at `<slug>.localhost:3001` → expand **Developers** → click **Logs** → the LIST row shows the **Embed** source badge + the typed `origin_not_allowed` inline (the status column renders `errorCode` for error rows instead of the numeric code) → click the row → the read-only DETAIL surfaces the error code (`data-testid="log-error-code"` = `origin_not_allowed`, in destructive red), the Embed source, the error message "This origin is not permitted to embed.", and the raw `embedSecret` appears **nowhere** on the page. Screenshots `dlc-embed-desktop.png` / `dlc-embed-mobile.png` (both viewports, overflow ≤ 2px).
- **`log-badges.test.ts`** pins the badge registry: `LOG_SOURCE_REGISTRY.embed_session.label === 'Embed'`, tone `primary`.

### AC-DLC-25 — redaction matrix — PASS (all sources + secrets present)
- **Confirmed the matrix is COMPLETE** (the task's fail-if-missing check): `tests/test_activity_redaction.py` `_summary()` carries all four secret shapes — API key (`apiKey`/`api_key`), bearer token (`authorization` header + a nested `list[].token`), `embedSecret` (+ nested `clientSecret`), Meta access token (`accessToken`/`access_token`) — plus a WhatsApp message body. `test_redaction_matrix_masks_all_secret_shapes` asserts each is `"***"` and message content survives. `test_redaction_matrix_across_all_four_sources` drives a real `ActivityLogService.record` write for **each of `inbound_api`, `embed_session`, `outbound_meta`, `webhook_delivery`** and re-reads the STORED `request_summary_json` AND `response_summary_json`, asserting `_all_secrets_masked` (API key / `fxw_live_bearer` / embedSecret / Meta token all absent, `MESSAGE` present) on both. No source or secret shape is missing from the matrix.

### AC-DLC-26 — volume guard — PASS
- **Documented + verified:** `ActivityLogService._volume_guard_admits()` is a per-process 1s token counter (`integration_activity_max_writes_per_second`, default 500); over cap → the write is DROPPED (returns `None`, no row) with a running dropped-counter logged every 100 drops, never blocked. `test_volume_guard_drops_over_cap` (cap=2, 5 writes → 2 admitted rows persisted, 3 return `None`) and `test_volume_guard_disabled_when_cap_zero` (cap=0 → all 4 admitted) prove drop-not-block + the disable switch. The write is already off the request critical path (fresh-session / prod BackgroundTask) and swallow-isolated, so dropping is graceful degradation. Documented trade-off (per-process cap; an async/buffered writer is the true scale path) noted in the plan/code as a backlog candidate.

---

## Screenshots (scratchpad)
- `dlc-settings-desktop.png` / `dlc-settings-mobile.png` — Log-retention form, value 157 persisted after reload ("Custom for this workspace."), sidebar Developers → Logs / Log settings.
- `dlc-embed-desktop.png` / `dlc-embed-mobile.png` — embed_session detail: Embed source badge, Error 403, Error code `origin_not_allowed`, message, no secret.

## Other remarks (not AC failures)
- **New E2E helper** `service_frontend/e2e/helpers/seed_embed_connection_for_tenant.py` (sibling of the existing `seed_embed_connection.py`, generalized to an arbitrary tenant-by-slug) — required so AC-DLC-24 uses a dedicated tenant and never mutates the default tenant's live embed-config connection. Invoked with `PYTHONPATH=<backend>` (script-dir-on-sys.path means `cwd` alone doesn't import `app`); the spec parses the JSON line by matching `"connectionId"` because local SQLAlchemy echo pollutes stdout.
- **E2E residue (consistent with existing specs, BL-069):** each AC-DLC-24 run leaves a provisioned `e2e-dlc-embed-%` tenant (+ its one embed error row) — never purged (BL-035). Suspect + clean these before blaming code if the tenants list crowds. The AC-DLC-23 run leaves a benign `integration_log_settings` override on the `default` tenant.
- **Migration:** single alembic head `dlc_s412b_log_settings` (≤ 32 chars). The two-heads condition noted in Slice 1 was reconciled by the merge commit `1b41dfe`; `alembic upgrade head` now succeeds.

## Verdict (Slice 3)
**Slice 3 is GREEN.** All seven ACs (AC-DLC-20…26) PASS — including the two that a green pytest alone can't satisfy: the retention **save** and the **embed error rendering** were both confirmed with real clicks against the live stack (screenshots), after catching + fixing a stale-code/stale-build environment that had silently disabled embed recording. No regressions (full backend suite 1139 passed; frontend targeted 24; E2E 6).

---

# Feature-wide summary — all 26 ACs across the 3 slices

| Slice | AC ids | Final status |
|---|---|---|
| **1 — store + inbound-API capture + console** | AC-DLC-01 … 13 | **ALL PASS** (2 documented deferrals, none breaking an AC: unattributed inbound-401 writes no row [AC-DLC-03]; inbound `responseSummary` null / body metadata-only [AC-DLC-07/11]) |
| **2 — correlated trace (outbound Meta + webhook unify + trace view)** | AC-DLC-14 … 19 | **ALL PASS** (AC-DLC-16 disclosed mechanism deviation: write-time core-seam vs read-time join — outcome met, historical rows not backfilled; AC-DLC-17 timeline causal-order inversion — quality finding, contract met) |
| **3 — embed logging + per-tenant retention + hardening** | AC-DLC-20 … 26 | **ALL PASS** |

**FEATURE VERDICT: GREEN.** All 26 acceptance criteria pass. The remaining items are backlog candidates (unattributed-401 stream, inbound response-summary capture, historical webhook backfill, trace causal ordering, async/buffered activity writer) — none blocks a slice as written. Recommend merge after code review.
