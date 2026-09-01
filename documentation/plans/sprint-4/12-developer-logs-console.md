# 12 - Developer Logs / Integration Activity Console

> **UAC:** `12-developer-logs-console-acceptance-criteria.md` (the contract). This plan is the design that fulfils it.
> **Status:** DRAFT (grill settled 2026-07-11). Branch: `sprint-4/developer-logs-console`.
> Built in **3 vertical slices** (thinnest end-to-end first), frontend-first per slice.

## 1. What & why

Consumers integrate with the shared service (workspace API key + embed secret for the iframe), consume from their own systems via **API calls** and **iframe embedding**, and today have **nowhere to troubleshoot** - every path is fire-and-forget except the per-channel webhook Deliveries dialog. This feature is a **Developers → Logs** console: one source-tagged activity log across inbound API, embed sessions, outbound Meta calls, and webhook deliveries, with **trace-id correlation** so one consumption is visible end-to-end, **redacted bodies**, and **per-tenant retention**.

Design is deliberately **generic + core** (not omnichannel-scoped): the shared-service vision is many consumable services; the log table + write seam + console are horizontal so a future storage/LLM consumer writes to the SAME console.

## 2. Grounding (current reality - verified)

| Piece | State | Ref |
|---|---|---|
| Public gateway auth | Every `/api/v1/omnichannel/*` route deps `get_api_workspace` → `ApiWorkspace{tenant_id, workspace_id, key_id}` | `modules/omnichannel/api_auth.py:42` |
| Request logging | **None** - only `CORSMiddleware`; no per-request hook | `app/main.py:75` |
| API key model | `workspace_api_keys` (`key_prefix`, `key_hash`, `last_used_at`) | `modules/omnichannel/models.py:283` |
| Embed session | Built - `POST /embed/session` verifies HS256 assertion vs `embedSecret`, typed `EmbedError` codes | `modules/omnichannel/services/embed_session_service.py` |
| Outbound Meta | Fire-and-forget - `send()` writes no row, one `logger.warning` | `modules/omnichannel/adapters/whatsapp_cloud.py:244` |
| Webhook deliveries | Real - `webhook_deliveries` (status/attempts/`response_status`/`response_ms`/error) + read endpoint + drawer | `modules/omnichannel/models.py:339`, `services/webhook_delivery.py` |
| Reuse: async job + pruner | `background_jobs` + `register_job_handler` + beat `prune_jobs` | `app/models/background_job.py`, `app/jobs/*` |
| Reuse: UI | `ResourceListConfig` (jobs list), activity-Sheet drawers, email-log list | `app/(protected)/jobs/use-jobs-list-config.tsx` |

**None of the activity data is captured today** - 3 of 4 sources need new instrumentation; the 4th (webhooks) is unified read-only.

## 3. Data model (core `public`)

### `integration_activity`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid, indexed | every query tenant-scoped |
| `trace_id` | uuid, nullable, indexed | correlation; minted at inbound gateway |
| `source` | enum | `inbound_api` \| `embed_session` \| `outbound_meta` \| `webhook_delivery`* |
| `workspace_id` | uuid, nullable, indexed | attribution (from `get_api_workspace`) |
| `api_key_id` | uuid, nullable | which key made the call |
| `operation` | str | `POST /messages`, `graph:send`, `embed:session`, … |
| `method` | str, nullable | HTTP verb (inbound) |
| `status` | enum | `success` \| `error` \| `pending` |
| `status_code` | int, nullable | HTTP / Meta status |
| `error_code` | str, nullable | e.g. `invalid_api_key`, `expired`, `SendError` |
| `error_message` | str, nullable | redacted |
| `latency_ms` | int, nullable | |
| `external_ref` | str, nullable, indexed | wamid / event_id - async webhook join |
| `request_summary_json` | JSON(none_as_null), nullable | redacted metadata + body |
| `response_summary_json` | JSON(none_as_null), nullable | redacted |
| `created_at` | UTCDateTime | |

Indexes: `(tenant_id, created_at)`, `(tenant_id, trace_id)`, `(tenant_id, source)`, `(tenant_id, status)`, `(tenant_id, external_ref)`.

\* `webhook_delivery` rows are **NOT written here** - they stay in `webhook_deliveries` (single source of truth) and are merged at read time (§6). The enum value exists so the seam/console treats them uniformly.

### `integration_log_settings`
`tenant_id` PK · `retention_days` int NULL (NULL = global default). Mirrors `workflow_settings` shape.
Global default: config `integration_activity_retention_days` (default **30**).

Migration deploys via **`bootstrap_db`** (adds a table → `create_all` is fine, but ship the Alembic revision; keep revision id ≤32 chars). New core permission → grant sweep (§7).

## 4. Write seam (generic, failure-isolated)

`app/activity_log/` (mirrors `app/jobs/` shape):
- `ActivityLogService.record(db, *, tenant_id, source, operation, status, trace_id=None, workspace_id=None, api_key_id=None, status_code=None, latency_ms=None, error_code=None, error_message=None, external_ref=None, request=None, response=None)` - redacts, inserts one row, **own commit**, `try/except` swallow-and-log. NEVER raises to caller.
- `redaction.py` - `redact(obj)` masks keys matching `authorization|api[_-]?key|token|secret|password|assertion|embedsecret` (case-insensitive) → `"***"`; recurses dicts/lists; caps body size. WhatsApp message text is NOT a secret key → preserved.
- **Volume guard (AC-DLC-26):** v1 = best-effort synchronous insert with isolated failure (matches `webhook_deliveries` per-attempt writes). Add a lightweight in-process guard: if insert latency/error budget trips, drop the row (log a counter) rather than block. Document the trade-off; a Celery/`background_jobs`-backed async buffer is the scale path (backlog if load demands).

### Trace-id threading
- A `contextvars.ContextVar[str] trace_id_var` in `app/activity_log/context.py`.
- Gateway hook mints `trace_id`, sets `request.state.trace_id` + the contextvar.
- `WhatsAppCloudAdapter.send()` reads the contextvar → same `trace_id` on the outbound row (AC-DLC-15). Also persists `trace_id ↔ wamid` so the async status-webhook (which has only the wamid) can resolve the trace by `external_ref` at read time (AC-DLC-16).

## 5. Instrumentation points

1. **Inbound API (Slice 1)** - a `BaseHTTPMiddleware` scoped to path-prefix `/api/v1/omnichannel` (cheap prefix check, skip everything else) OR a router-level dependency on the gateway router. Middleware chosen: captures latency + status_code including exceptions uniformly, and is the single natural place to mint the trace id. Reads `get_api_workspace` result via `request.state` (set the resolved `ApiWorkspace` there in the dep) for attribution. Records after the response.
2. **Embed session (Slice 3)** - wrap `EmbedSessionService.exchange()`: on return → `success` row; on `EmbedError` → `error` row with `error_code = e.code`. Parent origin captured. No raw assertion/secret.
3. **Outbound Meta (Slice 2)** - wrap the Graph HTTP calls in `WhatsAppCloudAdapter` (`send`, template submit, sync). Record operation/status/latency/`external_ref=wamid`, token redacted. Reuse a small `_graph_call(...)` timing wrapper so every call is instrumented once.
4. **Webhook deliveries (Slice 2)** - read-time merge from `webhook_deliveries`; no new writes.

## 6. Read API (`app/api/v1/integration_logs.py`, Service-Repository)

- `GET /integration-logs` - paginated, whitelisted filter translator (source/status/time/workspace), search path/trace_id/external_ref. Gated `integration_logs.read`. Merges `integration_activity` + a projection of `webhook_deliveries` (same tenant) into one ordered feed (UNION-style at the repository, or two queries merged + paginated - pick per volume; document). camelCase via `ApiModel`.
- `GET /integration-logs/{id}` - single row + redacted summaries.
- `GET /integration-logs/trace/{traceId}` - ordered legs of one consumption (activity rows with that trace_id + webhook rows whose `external_ref` maps to the trace).
- `GET/PUT /integration-logs/settings` - retention; gated `integration_logs.manage`.

## 7. Permissions

Core CSV rows: `integration_logs.read`, `integration_logs.manage`. Add to `tenant_admin_grant` computed set AND ship a **grant sweep** (migration or `tenant_admin_grant` re-run) so existing tenants' Admin roles get them - else the console silently 403s (recurring-gap rule #4).

## 8. Frontend

- `Developers` sidebar section (new) → `Logs` (+ `Settings` for retention). Tagged `permission: integration_logs.read` in `MENU_SIDEBAR`, `MENU_MEGA`, `MENU_MEGA_MOBILE` (all three), pruned by `filterMenu`.
- Service trio `services/integration-log-service.{ts,mock,real}` - build UI on the mock first (all states), swap to real at the service boundary (one-line).
- `app/(protected)/developers/logs/` - `useIntegrationLogsListConfig(): ResourceListConfig` (clone the jobs list). Columns: source badge (registry) · operation · status badge · `latency_ms` · workspace · relative time (`useDatetime`). Source + status filter fields; N-way source **segments** via `ResourceListConfig.segments` (SearchSelect) is a nice-to-have.
- Detail: read-only ResourceForm (no Edit toggle) - metadata block + redacted request/response in a sandboxed/pre block (reuse email-log body-iframe pattern if HTML) + a **trace timeline** (the correlated legs, each with status/latency, clickable). Clamp long values via `ClampedText`.
- Retention settings page - reuse the `/settings/workflows` shape.
- Responsive verified at 375px + 1280px.

## 9. Slicing

- **Slice 1** - table + write seam + inbound-API middleware + redaction + read list/detail + console (mock→real) + permission + grant sweep. Thinnest end-to-end (one source, capture→store→view). ACs 01-13.
- **Slice 2** - outbound Meta instrumentation + trace threading + webhook read-merge + trace endpoint + timeline view. ACs 14-19.
- **Slice 3** - embed session logging + per-tenant retention + beat pruner + redaction matrix + volume guard + settings UI. ACs 20-26.

## 10. Testing

- `[T]` backend: `tests/test_activity_log.py` - record swallows raising writer (AC-02/05), redaction matrix (AC-04/25), tenant scoping, trace threading (AC-15), retention prune per-tenant (AC-22), read merge with webhooks (AC-16). Conftest is `create_all` - the omnichannel schema-translate rig applies.
- `[T]` frontend: `integration-log-service` + list-config + redaction render + source-badge registry (Vitest).
- `[E2E]` `e2e/developer-logs.spec.ts` - Slice 1 journey (AC-13), Slice 2 trace journey (AC-19); real clicks, dedicated E2E tenant, timestamped names. Mailbox-style seeding for inbound calls; report keyed to AC ids → `12-developer-logs-console-test-report.md`.

## 11. Definition-of-Done gate (must pass before merge)

1. Mock swapped to real + verified showing real captured rows (no `PHASE 1 MOCK` residue).
2. New table/columns on existing flow - N/A backfill (new table), but the grant sweep IS the "reaches existing tenants" requirement - verify an existing tenant's Admin sees the console.
3. No hardcoded tenant-editable keys (source/status are code enums, fine).
4. `integration_logs.*` reaches existing tenants' Admin (grant sweep).
5. End-to-end from a consumer's perspective - make a real gateway call, see its row + trace - at 375px + 1280px, fresh `rm -rf .next && npm run build`, ports 3001/8001.

## 12. Backlog candidates (log to `backlog.md` on defer)
- Async/buffered high-volume writer (`background_jobs`-backed) if synchronous best-effort proves insufficient under load.
- Non-omnichannel service sources (storage/LLM) writing to the same console.
- Analytics/aggregates (call counts, error-rate trends) + alerting on error spikes.
- CSV export of logs.
- Full (un-summarized) body capture opt-in.
