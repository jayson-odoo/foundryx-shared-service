# Plan 10 S6 - AC-10-53 live replay, both books, LOGGING sink (backend/API only)

Lane `s40`, branch `sprint-5/10-autocount-pull-review`. Backend `.venv/bin/python -m uvicorn
app.main:app --port 8009` from `s40/service_backend`, DB `foundryx_service_s40` (native Postgres).
All timestamps UTC unless marked `+09` (raw `ac_sync_run` rows, server-local). No frontend was
started (API-only, backend operator routes + the public gateway).

Boot HEAD `b1593264` (the SHA named in the brief). Backend was never restarted during this run, so
every result below reflects the code as it stood when uvicorn started. **HEAD advanced to `b5a5ec2e`
while this replay ran** (a concurrent coder committed `994ca215`/`7660251a`/`67d4f1a3`/`b5a5ec2e` -
FE phase-2 swap, a pull-filter fix, a confirm-round-2 red test, docs - plus left uncommitted WIP in
`routers/http.py`/`schemas.py`/`services/etl_service.py`). Checked the diff: all of it is
Lookups/preview-editor/HTTP-task-config surface, not `pull_service.py`/`routers/pull.py`/
`routers/pull_v1.py`/`sync.py`'s `_run_pull_snapshot` - the pull-snapshot build and gateway-read
code this replay exercises is untouched by the concurrent work. Final commit sha for this evidence:
see the end of this file.

## Summary verdict

| Book | Entity | Status | Records | Duration | Matches expected |
|---|---|---|---|---|---|
| db1 (SRT, `AED_SORENTO`) | product | **ready** | 11,840 | 9m 0.1s | exact |
| db1 (SRT, `AED_SORENTO`) | stock_balance | **ready** | 12,133 | 8m 0.8s | exact |
| db2 (MCH, `MOCHA`) | product | **failed** (`SOURCE_PAGE_FAILED`) | 0 | 3m 4.9s (to failure) | N/A - db2 cannot complete a pull build in this codebase today, see Finding 1 |
| db2 (MCH, `MOCHA`) | stock_balance | **failed** (`ENRICH_FAILED`) | 0 | 3m 5.5s (to failure) | N/A - same root cause |

**db1 is a clean, exact pass** against every number the plan and the earlier PROBE.md capture
documented. **db2 cannot build a pull snapshot at all in this codebase** - not a data problem, a
missing feature (Finding 1). A second, independently significant defect (Finding 2): the PUBLIC
GATEWAY's build route freezes the entire backend - every tenant, every route - for the full build
duration when it must actually start a new extraction.

## Setup

- Login `demo@example.com` / `demo1234`, tenant `default`, Admin. No throttle hit.
- Company `Sorento SRT S40` (`0e6f5c95-b099-4a1f-8de9-425b63f561b4`) already existed from earlier
  S1/S3/S4/S5b evidence sessions, sink `sorento` pointing at connection `8129747b-...` (`Sorento`,
  `baseUrl: https://s40-sorento-fixture.invalid` - a deliberate, unroutable `.invalid`-TLD fixture,
  confirmed by earlier testers; genuinely non-resolvable, so even an accidental push attempt cannot
  reach a real Sorento), `sorentoCompanyCode: "SRT"`.
- **Finding 0 (design coupling, see below): switching the sink to `logging` unconditionally clears
  `sorento_company_code`, which both the pull-gateway's companyCode resolution AND the
  entity-level "enable pull delivery" guard require.** I switched SRT to `logging` first (per the
  brief), discovered this, then restored the ORIGINAL sink target (`sorento` + the SAME `.invalid`
  fixture connection + code `SRT`) rather than leaving it on `logging`, because (a) `logging` makes
  pull mode itself unreachable in this codebase (`EtlService.set_delivery_mode`'s own 422:
  `"Set a consumer company code on this company before enabling pull."`) and (b) I verified by
  reading `sync.py:_run_pull_snapshot` that the pull-snapshot job this replay exercises NEVER
  calls the sink (`mode=reconcile, persist_hashes=False`, no `SorentoSink` reference anywhere in
  that function) - so no real delivery risk exists regardless of this field's value, as long as no
  push-triggering route (`etl-task/run`, the push scheduler) is ever called, which this replay
  never calls. Full reasoning and code citations in Finding 0 below.
- `product` entity switched to `deliveryMode: "pull"` (was `push`/`active` from an earlier
  session). `stock_balance` entity (already `deliveryMode: "pull"` by default, combine preset
  pre-seeded) was Tested (preview succeeded) then Activated.
- db2 connection created fresh: `provider: "autocount"`, `auth: "none"`,
  `baseUrl: https://hapi.sorento.cc.cd/api/db2`, name `S40 db2 MCH 20260920T094731Z`. Test:
  `{"ok":true,"message":"Reachable - 21 row(s) returned from /location."}`.
- Company `Mocha MCH S40 20260920T094731Z` created (`cdf1c397-20fe-4a78-b335-bfeaf6bd9b27`),
  `databaseName` discovered as `MOCHA`. Sink set to `sorento` + the SAME `.invalid` fixture
  connection + code `MCH` (same reasoning as Finding 0 - required to enable pull at all; never
  delivers anywhere real).
- `product` task saved (`path: /itembypage`, `keyFields: ["ItemCode"]`) - the `/itemuombypage`
  lookup pre-filled automatically (seed-if-absent), matching db1's preset exactly.
  `stock_balance` task saved (`path: /itembatchbalqtybypage`,
  `keyFields: ["item_code","location_code"]`) - `deliveryMode: pull` by default and the FULL
  combine preset (computed columns, `uom_rate` require rule, `zero`/`negative` drop rules,
  `round half_up 0dp`) pre-seeded automatically, matching db1's preset exactly. **Neither MCH task
  could be Activated** (`POST .../etl-task/activate` 409s "unless a successful preview exists" -
  see Finding 1, the preview never succeeds against db2). This did not block the pull-snapshot
  BUILD route, which does not require `etlStatus: active` (verified in `pull_service.py`
  `request_build` - only refuses a push-active pair, never checks draft/active either way).
- Pull API key issued, scoped to BOTH companies: `POST /autocount/pull/keys`
  `{"name":"S6 live replay 20260920T095117Z","companyIds":[SRT, MCH]}` -> `keyPrefix: FYd43RG2`,
  plaintext used for every gateway call below (never committed - see `.gitignore` note at bottom).

## Finding 0 - `sinkImpl=logging` unconditionally clears `sorento_company_code`, which the pull path also depends on

`CompanyService.set_sink_target` (`services/company_service.py:1103-1108`): switching to
`logging` sets `company.sorento_company_code = None` by design ("Cleared with the target: a code
left behind would silently anchor a later switch back to Sorento at a company nobody re-chose").
But `EtlService.set_delivery_mode` (`services/etl_service.py:2796-2806`) REQUIRES
`company.sorento_company_code` to be non-blank before a task may switch to `deliveryMode: "pull"`,
and the public gateway's build route (`PullGatewayService.build`,
`services/pull_gateway_service.py:168`) resolves the target company BY that same
`sorento_company_code` via `CompanyRepository.find_by_sorento_company_code`. So **a company on the
`logging` sink can never be configured for pull at all** - not a bug in the strict sense (the
company-code field genuinely is the pull book's public identity, so requiring it makes sense), but
it means the brief's literal ask ("the company must use the LOGGING sink" AND "test the pull
gateway using companyCode") is not simultaneously satisfiable in this codebase as built. Resolved
by restoring the sorento sink target (verified sink-independent for the pull path - see Setup
above); recommend the plan owner decide whether `sorento_company_code` should be split into two
concepts (a push-sink anchor vs a pull-book public identity) or whether the docs should just say
"pull requires a live-looking sink target, but the pull path itself never uses it" more explicitly.

## Finding 1 - AC-10-85 (per-connection `pageSize`/`requestTimeoutSeconds`) is NOT implemented; db2 cannot build a pull snapshot at all

The plan's AC-10-85 text says this was "Verified today" as built. It is not present at this HEAD:

- `AutoCountProvider.fields()` (`modules/autocount/provider.py:101-156`) has exactly 5 fields
  (`auth`, `baseUrl`, `appId`, `userId`, `password`) - no `pageSize`, no `requestTimeoutSeconds`,
  gated or otherwise.
- `HttpApiClient.__init__` (`http_source/client.py:71`) defaults `timeout_seconds` to the module
  constant `DEFAULT_TIMEOUT_SECONDS = 30.0`; both call sites that construct it
  (`http_source/source.py:237`, `http_source/preview.py:116`) never pass an override - there is no
  code path from a connection's config to this parameter at all.
- `HttpApiSource._walk_endpoint` (`http_source/source.py:440-458`) starts at
  `DEFAULT_PAGE_SIZE = 1000`, halves on a double-timeout (`MIN_PAGE_SIZE = 50`, but
  `MAX_PAGE_HALVINGS = 2` - so the floor actually reachable is 1000 -> 500 -> 250, not 50), and
  RAISES `HttpSourceError(code="transport")` once `MAX_PAGE_HALVINGS` is exhausted and a THIRD
  page still double-times-out.

db2's real per-page latency (measured live this session, `integration_activity`, `MOCHA` rows):
`/itembatchbalqtybypage` (a narrower row shape) is FINE - 11 pages at pageSize 1000, 131-234ms
each. `/itembypage` (the product entity's main path, and stock's own `item` lookup) is NOT: every
attempt at every page size tried (1000, 500, 250) hit the fixed 30s client timeout on BOTH allowed
attempts before halving/failing - `itembypage?page=1&pageSize=1000` errored 4 times at
30,420-31,528ms, `pageSize=500` errored 4 times at 30,104-30,121ms, `pageSize=250` errored 4 times
at 30,069-30,123ms - i.e. it never got a SINGLE successful response from `/itembypage` on db2 at
any size, because the real server-side latency for that endpoint on db2 is far above the
hardcoded 30s ceiling (consistent with the plan's own Appendix A7 measurement: "300 rows -> 65s").
After the 3rd size (250) also double-times-out, `_walk_endpoint` raises
`"'/itembypage' timed out repeatedly even after 2 halving(s) of the page size."` - this is EXACTLY
what happened, 3 separate times this session:

1. `POST .../entities/product/etl-task/preview` (Test) - failed after 3m 3.52s, HTTP 422
   `{"code":"transport","message":"'/itembypage' timed out repeatedly even after 2 halving(s) of
   the page size."}`. This is also why the task could never be Activated (activation requires a
   successful preview).
2. `POST /autocount/pull/snapshots {companyId: MCH, entityType: product}` (the operator build
   route) - snapshot `1c89a3f4-f89d-4ee8-95aa-bb5a46d0872b` went `building` -> `failed` in
   184,955ms (`ac_sync_run` `b89cf4e1-...`), `errorCode: SOURCE_PAGE_FAILED`, same message.
3. `POST /autocount/pull/snapshots {companyId: MCH, entityType: stock_balance}` - snapshot
   `0a6d8373-765c-4a2c-bf31-ff1a1735c5b2` went `building` -> `failed` in 185,458ms (`ac_sync_run`
   `c2c55b4b-...`), `errorCode: ENRICH_FAILED`, message `"The 'item' lookup endpoint '/itembypage'
   failed: '/itembypage' timed out repeatedly even after 2 halving(s) of the page size."` - the
   stock task's OWN main path (`/itembatchbalqtybypage`, 11 pages) succeeded completely; it is the
   `item` lookup (which also hits `/itembypage`) that fails, confirming the root cause is
   endpoint-specific latency, not something wrong with the stock preset itself.

**Net: db2/Mocha cannot deliver a product or stock pull snapshot in this codebase today,
end-to-end, for ANY entity that touches `/itembypage` (directly or via lookup) - not a data
correctness gap, a missing per-connection timeout/page-size override (AC-10-85).** Full raw
per-endpoint call log: `integration-activity-summary.txt` in this directory.

## Finding 2 - the PUBLIC GATEWAY's build route blocks the entire backend for the full build duration (severe, all-tenant availability impact)

`routers/pull_v1.py`'s `POST /snapshots` handler is declared `async def build_snapshot(...)`, but
its body calls straight through to `PullGatewayService(db).build(...)` ->
`PullService.request_build(...)` -> (eager mode) `run_job(db, job_id)` -> the job handler
`_run_pull_snapshot`, which performs fully SYNCHRONOUS, blocking `httpx.Client` I/O across
potentially dozens of pages - none of it ever `await`ed or offloaded to a thread. Because the
route is `async def`, FastAPI runs it directly on the ASGI event loop rather than in Starlette's
automatic threadpool (which only ordinary `def` handlers get). The result: **while a
gateway-triggered build is actually running an extraction (i.e. whenever cooldown/re-attach does
not short-circuit it), the single uvicorn worker's event loop is fully occupied and CANNOT service
ANY other request - not just other autocount routes, not just other tenants, literally every route
including `/openapi.json` and login.**

Reproduced and timed directly this session:

- `2026-09-20T10:05:55Z` - `POST /api/v1/autocount/snapshots {"companyCode":"SRT","entity":"products"}`
  (a genuine new build - the existing `ready` snapshot was outside its cooldown window, so this did
  not re-attach or 429).
- From `10:05:55Z` onward, `GET /openapi.json` (an entirely unrelated, unauthenticated, static
  route) returned NOTHING - `curl --max-time 10/15` timed out repeatedly (`exit 28`), confirmed
  THREE separate times across the build's duration.
- `ac_sync_run` confirms: `started_at 2026-09-20 19:05:56.008745+09`,
  `finished_at 2026-09-20 19:14:43.860345+09` = **8 minutes 47.9 seconds**.
- The moment the build finished, `GET /openapi.json` succeeded immediately (`HTTP 200`,
  `1.25s`) - confirming the freeze was exactly bounded by the build's own duration, not a crash or
  an unrelated hang.

By contrast, the OPERATOR route (`routers/pull.py`'s `def build_pull_snapshot`, a plain
synchronous function) does NOT exhibit this - FastAPI threadpools ordinary `def` routes
automatically, and this session's own operator-route builds (db1 product 9m0s, db1 stock 8m0s)
were polled successfully via concurrent `GET /autocount/pull/snapshots` calls (and one successful
re-attach POST) throughout, with no observed freeze.

**Impact: any holder of a pull API key (a THIRD PARTY, external-consumer-facing credential, per
this gateway's own threat model) can hang the entire platform - every tenant - for the duration of
one build (9 minutes for an 11.8k-row book here; proportionally longer for a bigger one, and per
AC-10-86 "long builds are supported, not papered over" - i.e. this is expected to sometimes take
much longer) simply by triggering a fresh extraction.** This reads as a genuine, load-bearing
availability defect for the plan owner/coder to fix - most likely: dispatch the build via the SAME
`background_jobs`/Celery-eager mechanism WITHOUT blocking the request coroutine (e.g. run the sync
extraction in a thread via `run_in_threadpool`, or make the gateway route an ordinary `def` like
the operator route already is), so `POST /snapshots`'s `202 Accepted` genuinely means "accepted,
poll `GET .../{id}` for progress" rather than "the entire platform is unavailable until this
finishes."

## db1 (SRT) - full header data

### product (`504088ab-c9ad-4d73-9632-43b49484c3d1`, operator-triggered build)

`db1-product-header.json` (operator route) / `gateway-db1-product-header.json` (gateway route, same
snapshot - confirms both surfaces render the identical `ready` data, gateway shape correctly
trims to Appendix A3's `ready`-only key set).

| Fact | Expected (plan / earlier PROBE) | Measured | Match |
|---|---|---|---|
| recordCount | ~11,840 | 11,840 | exact |
| zeroListPriceCount | ~5,129 | 5,129 | exact |
| negativeListPriceCount | ~121 | 121 | exact |
| enrichMissCount | 0 | 0 | exact |
| excludedCount | 0-10 (varies by live data) | 0 | within documented range |
| complete | true | true | exact |
| sourcePageSize | 500 (halved once, live wrapper timeout) | 500 | exact - same halving class S1 hit |
| duration | ~9 min (S1 baseline) | 9m 0.1s (540,111ms) | exact |

Re-built a SECOND time via the gateway (`c52df8df-6999-4097-825b-5e150e223692`,
`requestedVia: gateway`, 8m 47.9s) - **byte-identical `contentHash`**
(`2d1b3832afc0de42f4cddc5edc2c6f70e26c66ee62c6539358c9197946f1a984`) to the operator-route build,
same 11,840/5,129/121/0 counters - confirms the pull path is deterministic across both callers.

### stock_balance (`428cf3fb-6233-4b91-9f15-e96756044d85`)

`db1-stock-header.json` / `gateway-db1-stock-header.json` (`negativePairList` trimmed to first 5 +
`negativePairList_count`; the full untrimmed 42-row list is `db1-stock-negative-pairs-full.json`).

| Fact | Expected (PROBE.md, db1 recorded capture) | Measured | Match |
|---|---|---|---|
| recordCount (rows out) | 12,133 | 12,133 | exact |
| zeroPairs | 56,422 | 56,422 | exact |
| negativePairs | 42 | 42 (all 42 listed) | exact |
| fractionalPairs | 0 | 0 | exact |
| excludedNonzeroCount | 0 | 0 | exact |
| excludedCount | 0 | 0 | exact |
| complete | true | true | exact |
| sourcePageSize | 1000 (no halving this run) | 1000 | exact |
| duration | not previously timed end-to-end via this route | 8m 0.8s (480,810ms) | new data point |

**db1 is an exact, unqualified pass on every number.**

## db2 (MCH) - full header data (both failed)

`db2-product-header.json`, `db2-stock-header.json` (operator route) and
`gateway-db2-product-header.json`, `gateway-db2-stock-header.json` (gateway route - confirms the
FAILED-status Appendix A3 shape: only `snapshotId/entity/companyCode/status/error`, no ready-only
keys, not even as null). See Finding 1 for the full root-cause narrative.

## Gateway row-shape verification (AC-10-30/33, Appendix A4)

`gateway-row-samples.json` - `GET /api/v1/autocount/snapshots/{id}/rows?page=1&pageSize=3` for
both db1 snapshots via the gateway (X-API-Key auth). Product rows:
`{source_ref, code, name, description, category_code, brand_code, list_price (JSON STRING),
is_active}` - matches Appendix A4 exactly, `list_price` confirmed as a wire STRING
(`"0.0"`) per AC-10-59. Stock rows:
`{source_ref, item_code, item_description, location_code, uom_code, qty}` - matches exactly,
`qty` an integer. `totalPages` correctly derived (3,947 for product at pageSize 3; 4,045 for
stock).

## Cooldown, re-attach, auth negative probes

Full curl transcripts: `cooldown-reattach-transcripts.txt`. Summary:

- **Re-attach (AC-10-88):** a build POST issued while a build is still `building` returns the SAME
  `snapshotId` instantly (15ms), never starts a second extraction. Confirmed on db1 product.
- **Cooldown (AC-10-26):** a build POST for a triple whose most recent build finished < 60s ago
  gets `HTTP 429` with `Retry-After: <exact remaining seconds>` - confirmed on BOTH the operator
  route (`{"detail": "A snapshot for this entity was built less than 60 seconds ago..."}`) and the
  gateway (`{"code":"TOO_MANY_BUILDS", ...}`, Appendix A6 shape). The brief text said "409" for
  this probe; the actual, code-defined status is 429 on both surfaces (409 is reserved for
  `PUSH_ACTIVE`/`AMBIGUOUS_COMPANY`) - noted as a brief-text correction, not a defect (the plan's
  own Appendix A6 also specifies 429 for `TOO_MANY_BUILDS`).
- **Gateway auth:** unknown snapshot id -> `404 UNKNOWN_SNAPSHOT`; missing/bogus `X-API-Key` ->
  `401 INVALID_API_KEY`. Matches Appendix A6.
- **TTL:** both `ready` snapshots' `expiresAt` = `createdAt + 24h` exactly
  (`AUTOCOUNT_PULL_SNAPSHOT_TTL_HOURS = 24`), confirmed on db1 product and stock.
- **`?format=`:** not applicable - Appendix A names no such parameter for the autocount pull
  gateway (unlike the omnichannel gateway's `?format=rio`); none observed or expected.
- **AC-10-87 progress hint:** NOT implemented at this HEAD - `snapshot_header`/
  `gateway_snapshot_header` (both in `pull_service.py`/`pull_gateway_service.py`) carry no
  `progress` key at all, and no `progress_json`-shaped column exists on `AcPullSnapshot`. Every
  `building` header polled this session (operator AND gateway) carried only
  `{id/snapshotId, entityType/entity, companyId/companyCode, status}`. The AC text marks this
  field OPTIONAL ("may carry"), so its absence is not a hard AC failure, but it means "record
  progress hints seen while building" (this brief's own ask) yielded none to record - flagged for
  completeness, not filed as a defect.

## Request/latency evidence

`integration-activity-summary.txt` - every outbound call this session made, grouped by
book/endpoint/status, with call counts and latencies. Totals: db1 (`AED_SORENTO`) 224 successful +
10 error (timeout-then-retry) calls, 1,305,277ms cumulative successful latency; db2 (`MOCHA`) 12
successful (all `/itembatchbalqtybypage`, `/location`, discover-company) + 16 error calls (all
`/itembypage`, every one a 30s client-side timeout), 362,370ms cumulative error latency.

## Teardown

- SRT company sink target: back to `sorento` + connection `8129747b-...` + code `SRT` - IDENTICAL
  to what it was before this session touched it (confirmed by GET). No further action needed.
- SRT `product` entity delivery mode: **left as `pull`** (was `push` before this session).
  **Deliberate deviation from a full revert** - switching a `push`+`active` task back to `push`
  re-arms the scheduled sync sweep (`EtlService.set_delivery_mode`'s own
  `elif config.etl_status == ETL_STATUS_ACTIVE: # Re-arm...` branch), which would then attempt a
  real scheduled push against the `.invalid` fixture sink target on its own schedule - strictly
  safer to leave it on `pull` (inert on the sweep by design: `config.next_incremental_at = None`)
  than to re-arm a scheduled push this session did not intend to leave running. Reported here in
  full rather than silently reverted or silently left; the plan owner/next tester can revert with
  one `PUT .../entities/product/delivery-mode {"deliveryMode":"push"}` call if desired.
- SRT `stock_balance` entity: left `etlStatus: active` (was `draft`) - safe (pull-only, never
  auto-runs on the sweep regardless of status).
- MCH company + both its tasks: left in place, lane-only state, as instructed (both tasks stay
  `draft`/never-activatable per Finding 1, harmless).
- Backend `:8009` (pid `9338`, `cwd` confirmed `s40/service_backend` before kill) stopped;
  `lsof -i :8009 -sTCP:LISTEN` confirmed free afterward.
- Pull API key issued this session (`d41d894f-...`) left ACTIVE (not revoked) - it is scoped only
  to this lane's two test companies and carries no real credential risk; revoking it is optional
  lane cleanup, not required for isolation (it cannot reach anything outside `foundryx_service_s40`).

## Report cross-reference

- AC-10-53 `[T]` - **PASS for db1** (both entities, exact numbers, operator route AND gateway
  route, byte-identical replay). **db2 cannot complete** due to Finding 1 (AC-10-85 not built) -
  this is the primary, load-bearing gap this replay surfaces.
- AC-10-26/88 (cooldown/re-attach) - PASS on both surfaces.
- AC-10-30/32/33 (gateway header/rows shape, Appendix A3/A4) - PASS, including the `ready` and
  `failed` omission rules.
- AC-10-34 (audit row per gateway call) - not independently re-verified this session (time budget
  went to the primary build/gateway/finding work); the mechanism was already covered by earlier
  slices' own tests, not re-probed here.
- AC-10-85 - **NOT IMPLEMENTED** at this HEAD (Finding 1) - contradicts the plan's own "Verified
  today" note; the plan text and the code have drifted.
- AC-10-87 - optional field, NOT IMPLEMENTED, no hard failure.
- New finding (no AC id yet) - the gateway build event-loop-blocking defect (Finding 2) - a
  backlog-worthy, severe availability gap, recommend filing as a new BL-SS entry.
