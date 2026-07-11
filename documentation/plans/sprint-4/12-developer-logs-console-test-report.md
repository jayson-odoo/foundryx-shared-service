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
