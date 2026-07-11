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
