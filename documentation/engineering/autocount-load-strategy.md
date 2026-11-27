# AutoCount load strategy (per-server gate, safety stop, pacing, office hours)

Plan + owner answers: `documentation/plans/sprint-5/autocount-load-strategy.md` (section 3). UAC: `...-acceptance-criteria.md`.
Goal: our sync is never the reason AutoCount is slow.

## One request at a time per server (`modules/autocount/http_source/server_gate.py`)
- A Redis turn per AutoCount **server** (`server_key`: scheme + lower-cased host without trailing dot / default port, IDNA), held for ONE request and handed back after it, so jobs interleave page by page. Every read and write goes through it: `HttpApiClient.get` (task walks, lookups, previews, doc feeds, document finder) and `write_back` client + reader (`send_as_person`).
- Priority: `PRIORITY_USER` (writes, document finder, previews, write-back reads) raises a per-tenant "a person is waiting" marker; scheduled pages of that tenant do not take the turn while it is set. A person waits at most for the page in flight (within the tenant) and is never refused (goes ahead after `MAX_WAIT_SECONDS_USER`).
- A scheduled page with no turn in `MAX_WAIT_SECONDS_SYNC` (300 s, under the 15-min orphan sweep) fails its run once: `HttpSourceError(code="server_busy")` / doc feed `VENDOR_STOPPED`. Never retried.
- Turn TTL = 3x the request timeout + 10 s (`hold_ttl_ms`): a crashed holder frees the server, a slow trickling page keeps it.
- **Tenant isolation (security review):** the turn is per server, but the urgent marker and the safety stop are per tenant + server (`_keys(base_url, tenant_id)`). Every client must carry its `tenant_id` (`HttpApiClient(tenant_id=)`, write-back via `call_log.context.tenant_id`); a client without one only affects the `-` scope.
- Redis unreachable = go ahead (today's behaviour) with a rate-limited warning. Tests: conftest `autocount_server_gate_off` switches the gate off; `tests/test_autocount_load_strategy.py` turns it on with fakeredis.

## Safety stop
- `stopAfterFailures` (3) failed requests in a row (timeout, transport error, 5xx/524; a 4xx is not a server failure) set `stopped_until = now + stopMinutes` (10). Scheduled calls are refused before AND after waiting for the turn (`HttpTransportError.stopped_until` -> `server_stopped` / `VENDOR_STOPPED`, no retry ladder). After it runs out exactly one caller sets `probe` (NX) and makes the test call; good = clear, bad = stop again. A person's call is never refused and its good answer clears the stop.

## Pacing (`http_source/gentle.py`)
- `AdaptivePause`: floor = `pagePauseSeconds`; a page slower than `slowPageSeconds` (30, 0 = off) doubles the next pause (min 5 s, max 90 s), a page faster than half of it halves it back to the floor. Applied between main-walk pages (`source.py _walk_path_serial`) and between document-feed day reads (`DocFeedVendor.pace`). Latency is measured after the turn is taken (`HttpApiClient.last_latency_seconds`).
- `stockPageSize` (3000, 50-3000) is used only by the stock balance MAIN walk; lookups and every other entity keep `pageSize` (max 1000).

## Office hours from Sorento CRM (`modules/autocount/office_hours.py`)
- Reads the CRM's `GET /api/v1/external/work-calendar` (`timezone`, `working_hours_start/_end` "09:00 A.M.", `working_day_ranges[{start_weekday,end_weekday}]`) and `GET .../work-calendar/is-working-day` (`is_working_day`) with the Sorento connection's `X-API-Key` (`SorentoSink.fetch_work_calendar`, SSRF-guarded). Cache 1 h per (tenant, connection, base URL, key hash); a failed read 5 min; bounded.
- `scheduler._sweep_one`, open-REST tasks only, incremental only: outside office hours the stock balance runs at most hourly (never past the next office-hours start); other open-REST lists are parked to the next start. A due reconcile is never held. No calendar / unreadable = every hour is office hours. At most `SWEEP_MAX_READS` CRM reads (3 s timeout) per scheduler tick.
- The reason / hours show under the Sorento connection's base URL (`SorentoProvider.field_hints`, FE hint kind `text`).

## Settings (AutoCount open-REST connection, `provider.py`)
`stockPageSize`, `oneRequestAtATime` (yes/no), `slowPageSeconds`, `stopAfterFailures`, `stopMinutes` - config_json keys with defaults when absent (no backfill).
