# 12 — Developer Logs / Integration Activity Console — Acceptance Criteria

> **Status:** DRAFT (grill settled 2026-07-11). Contract that plan `12-developer-logs-console.md` must fulfil.
> Tags: `[BE]` backend · `[FE]` frontend · `[E2E]` Playwright real-click · `[T]` unit/integration test.
> AC id prefix: **AC-DLC-**. A slice is done only when its ACs pass (report keyed back here).

## Problem

A consumer integrates with the shared service (mints a **workspace API key**, enables an **embed secret** for the iframe widget), then consumes from their own system via **API calls** and **iframe embedding**. When something misbehaves they currently have **no place to troubleshoot** — the only activity record anywhere is the per-channel webhook **Deliveries** dialog. Everything else is fire-and-forget: the public gateway has no request logging (only CORS middleware), and `WhatsAppCloudAdapter.send()` writes no record of the outbound Meta/Graph call.

## Goal

One top-level **Developers → Logs** console (a Resource-shell list + a detail/trace view) that shows every integration interaction, spanning:

1. **Inbound API** — consumer system → shared-service public gateway (`/api/v1/omnichannel/*`).
2. **Embed session** — iframe widget → `POST /embed/session` assertion exchange.
3. **Outbound Meta** — shared service → Meta Graph API (send, template submit, sync).
4. **Webhook deliveries** — shared service → consumer callback (unify the existing `webhook_deliveries`).

A single logical **consumption is traceable end-to-end** via a generated **trace id** (inbound API → outbound Meta), with the async webhook leg attached by **external ref** (message id / event id). Rows carry **metadata + redacted bodies** (credentials/tokens masked, message content kept). Storage is bounded by a **per-tenant configurable retention window**.

## Locked design decisions (from the grill)

- **Store:** ONE generic core-`public` table `integration_activity`, **source-tagged** — future consumable services (storage, LLM) write to the SAME console via a core seam. Not a module-schema table.
- **Placement:** new top-level sidebar section **Developers → Logs**, gated by a new core permission `integration_logs.read`.
- **Retention:** log all; per-tenant `retention_days` (NULL = global default `integration_activity_retention_days`, default 30). Pruned by the `background_jobs` beat pattern.
- **Correlation:** gateway mints a `trace_id` per inbound request, threaded (contextvar/`request.state`) into the outbound Meta call in the same flow; the async status-webhook leg joins by stored `external_ref` (wamid).
- **Payload depth:** metadata (method/path/status/latency/error) + request & response **summary bodies with secrets redacted** — API keys, bearer tokens, `embedSecret`, Meta access tokens masked; WhatsApp message content retained (needed to troubleshoot).
- **Writer is failure-isolated:** logging must NEVER break, slow, or 500 the request it observes (same discipline as workflow dispatch). Best-effort, own commit, swallow errors.

---

## Slice 1 — Log store + inbound-API capture + console (thinnest end-to-end)

Prove capture → store → view for the one highest-value source (inbound API).

### `[BE]` Store & write path
- **AC-DLC-01** — `integration_activity` core-`public` table + Alembic migration (backfill-safe; deploy via `bootstrap_db`). Columns per plan §Schema; every query tenant-scoped; indexes on `(tenant_id, created_at)`, `(tenant_id, trace_id)`, `(tenant_id, source)`, `(tenant_id, status)`. Datetimes are `UTCDateTime`.
- **AC-DLC-02** — A generic `ActivityLogService.record(...)` core seam writes one row; wrapped so any exception is swallowed + logged, never propagated (unit test proves a raising writer does not bubble).
- **AC-DLC-03** — A gateway request-logging hook (middleware or router dependency scoped to the public gateway) records one `inbound_api` row per `/api/v1/omnichannel/*` request with: workspace_id + api_key_id (from `get_api_workspace`), method, path/operation, status + HTTP status_code, latency_ms, error_code/message on failure, and a **minted `trace_id`** stashed on `request.state`.
- **AC-DLC-04** — Redaction: the `Authorization` header, API-key values, and any secret-looking field are masked in the stored request/response summary. `[T]` a request carrying `Authorization: Bearer fxw_live_…` stores no plaintext key.
- **AC-DLC-05** — Writer adds no meaningful latency to the observed request and cannot fail it. `[T]` gateway route still returns its normal response when `ActivityLogService.record` raises.

### `[BE]` Read API
- **AC-DLC-06** — `GET /integration-logs` — tenant-scoped, paginated, filter by source/status/time-range/workspace, search by path/trace_id/external_ref; gated `integration_logs.read`. Returns camelCase via `ApiModel`.
- **AC-DLC-07** — `GET /integration-logs/{id}` — single row incl. redacted request/response summary + trace_id + external_ref.
- **AC-DLC-08** — New core permission `integration_logs.read` (CSV row) with a grant sweep so **existing tenants' Admin** roles receive it (not just new provisions).

### `[FE]` Console
- **AC-DLC-09** — Frontend-first: `integration-log-service.{ts,mock,real}` behind the service layer; UI built + tunable against the mock (loading/error/empty/success) before the real swap.
- **AC-DLC-10** — `Developers → Logs` on the **Resource shell** (`ResourceListConfig`, not a hand-rolled table): columns source badge · operation · status badge · latency · workspace · time; server-side sort/filter/search/paginate; source + status filter fields; per-user column prefs. Sidebar entry in ALL menu arrays, gated `integration_logs.read` + tagged.
- **AC-DLC-11** — Row → read-only detail view (no Edit toggle): metadata + redacted request/response bodies in a sandboxed/pre-rendered block; error prominently surfaced.
- **AC-DLC-12** — Responsive at 375px AND 1280px (list reflows, detail readable, no horizontal scroll).

### `[E2E]`
- **AC-DLC-13** — Real-click journey: sign in → click into Developers → Logs → make (or seed) an inbound API call → the row appears with correct source/status → open detail → redacted body shown, no plaintext key. Report keyed to these AC ids.

---

## Slice 2 — Correlated trace (outbound Meta + webhook unify + trace view)

### `[BE]` Outbound Meta capture
- **AC-DLC-14** — `WhatsAppCloudAdapter.send()` (and other Graph calls) record an `outbound_meta` row: operation (`graph:send` / `graph:template_submit` / `graph:sync`), status + Meta HTTP status, latency_ms, error, `external_ref = wamid` on success, and the **inbound `trace_id`** when present (threaded from Slice 1). Meta access token redacted.
- **AC-DLC-15** — Trace threading: an inbound API `send_message` → the resulting outbound Meta call share the SAME `trace_id` (contextvar propagation). `[T]` proves both rows carry it.

### `[BE]` Webhook unify
- **AC-DLC-16** — Existing `webhook_deliveries` rows surface in the console timeline as `webhook_delivery` source — via a **read-time join/adapter, NOT duplicated writes** (single source of truth stays `webhook_deliveries`). Attach to a trace by `external_ref` (message/event id) when resolvable.

### `[BE/FE]` Trace view
- **AC-DLC-17** — `GET /integration-logs/trace/{traceId}` returns the ordered set of rows for one consumption (inbound → outbound Meta → webhook), oldest→newest.
- **AC-DLC-18** — Detail view shows a **timeline of the whole trace** (a click on any row's trace id opens the correlated sequence), each leg with its status/latency — the end-to-end troubleshooting picture.

### `[E2E]`
- **AC-DLC-19** — Real-click: consumer sends a message via the gateway → console shows the inbound row → its trace links the outbound Meta row → (seeded status webhook) the webhook-delivery leg attaches → one trace timeline renders all legs.

---

## Slice 3 — Embed logging + per-tenant retention + hardening

### `[BE]` Embed
- **AC-DLC-20** — `EmbedSessionService.exchange()` records an `embed_session` row on success AND on each typed `EmbedError` (`invalid_assertion`/`replayed`/`expired`/`origin_not_allowed`/`workspace_not_found`) — the error code is the row's status/error_code; parent origin captured (redacted of any secret); `embedSecret`/assertion never stored raw.

### `[BE]` Retention
- **AC-DLC-21** — Per-tenant `retention_days` setting (NULL = global default): `GET/PUT /integration-logs/settings` gated `integration_logs.manage`; global default config key `integration_activity_retention_days` (default 30).
- **AC-DLC-22** — A `background_jobs`-driven beat pruner deletes `integration_activity` rows older than the tenant's window (per-tenant override else global default), failure-isolated. `[T]` prunes only past-window rows, respects per-tenant override.

### `[FE]`
- **AC-DLC-23** — `Developers → Logs → Settings` (or `/settings`) page to set retention days, gated `integration_logs.manage`. Reuse Resource/settings patterns — no hand-rolled form.
- **AC-DLC-24** — Embed rows render with a distinct source badge; a failed embed session shows its typed error clearly (the primary embed troubleshooting need).

### `[T]` Cross-cutting
- **AC-DLC-25** — Redaction unit-test matrix: API key, bearer token, `embedSecret`, Meta access token all masked across all four sources; message content preserved.
- **AC-DLC-26** — Volume guard documented + a cap/best-effort behavior verified (writer degrades gracefully under burst — drops/samples rather than blocking). Exact strategy set in the plan.

---

## Out of scope (v1) / backlog candidates
- Non-omnichannel service sources (storage/LLM) — table is source-tagged + seam is generic so they slot in later; no such writer built here.
- Metrics/aggregates dashboards (call counts, error rates over time) — this is a raw activity log, not analytics.
- Full request/response body capture (only redacted summaries stored).
- Alerting/notifications on error spikes.
- Export of logs (CSV) — add if the Resource shell gives it cheaply; not a gating AC.
