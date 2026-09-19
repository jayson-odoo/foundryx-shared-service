# Plan 10 S1 - live replay run log (db1 / SRT, logging sink)

Lane `s40`, branch `sprint-5/10-autocount-pull-review`, HEAD `ce15df69` at the time of this
run. Backend `.venv/bin/python -m uvicorn app.main:app --port 8009` from `s40/service_backend`,
DB `foundryx_service_s40` (native Postgres). All timestamps UTC.

Nothing in this run was ever delivered to a real Sorento endpoint: the AutoCount company's
`sinkImpl` stayed `logging` (the slice-1 no-op sink, `modules/autocount/sinks.py`) throughout -
never touched. The only outbound network calls this run ever made were READ-ONLY `GET`s against
the live, read-only `https://hapi.sorento.cc.cd/api/db1` wrapper.

## Environment

- `2026-09-19` (UTC) throughout this run (`date -u`; local shell clock reads `2026-09-20 +08`).
- `lsof -i :8009 -sTCP:LISTEN` confirmed free before start; backend started in the background,
  logged to a scratchpad file (not committed - contains SQL echo, no secrets).
- Confirmed `CELERY_TASK_ALWAYS_EAGER=true` already present in the lane `.env` (not printed).
- Logged in as `demo@example.com` / `demo1234`, tenant `default` - no throttle hit (fresh lane,
  first login this session), so `auth_throttle` was never touched.
- Credentials: NONE needed. The db1 wrapper is reached through an `autocount` connection with
  `auth: "none"` (the "No auth" open-REST mode `modules/autocount/provider.py` registers for
  AC-08-01/02) - base URL only, `https://hapi.sorento.cc.cd/api/db1`. The `AUTOCOUNT_DEMO_USERNAME`/
  `AUTOCOUNT_DEMO_PASSWORD` values present in the lane `.env` are not referenced anywhere in the
  codebase (confirmed by grep) and were not needed for this replay.

## Part A - targeted pytest

From `s40/service_backend`, absolute venv python:

```
.venv/bin/python -m pytest -q tests/test_s10_*.py tests/test_autocount_http_source.py \
  tests/test_autocount_http_lifecycle.py tests/test_autocount_http_task_config.py
```

Result: **136 passed, 0 failed** (93.06s), 11 warnings (pre-existing `StarletteDeprecationWarning`
noise from `HTTP_422_UNPROCESSABLE_ENTITY`/`httpx`-via-`TestClient`, unrelated to this slice).

Files covered: `test_s10_http_client_user_agent.py`, `test_s10_http_lookups.py`,
`test_s10_http_retry.py`, `test_s10_lookups_validate.py`, `test_s10_preview_lookups_route.py`,
`test_s10_product_preset.py`, `test_s10_product_preset_seeding.py`, plus the named plan-08 HTTP
source/lifecycle/task-config files (unchanged coverage, re-run to confirm no regression from S1's
diff).

## Part B - live replay, db1 (company `SRT`, AutoCount `AED_SORENTO`)

### Setup (via the operator API, real backend, real network to the wrapper)

1. `POST /integrations/connections` - `provider: "autocount"`, `config: {auth: "none", baseUrl:
   "https://hapi.sorento.cc.cd/api/db1"}`, name `S40 db1 SRT 20260919T183336Z` (timestamped).
   `POST .../test` -> `{"ok": true, "message": "Reachable - 154 row(s) returned from /location."}`
   (154 matches the plan's documented `/location` row count exactly).
2. `POST /autocount/companies` - `connectionId`, `name: "Sorento SRT S40"`, `refPrefix:
   "AED_SORENTO"` -> company id `0e6f5c95-b099-4a1f-8de9-425b63f561b4`, `sinkImpl: "logging"`
   (default, never changed), `sourceKind: "http"`.
3. `PUT .../entities/product/etl-task` - `sourceImpl: "autocount_http"`, `path: "/itembypage"`,
   `keyFields: ["ItemCode"]` -> **first clean save**. The response's `sourceConfig.lookups`
   came back PRE-FILLED (seed-if-absent, AC-10-04): one lookup, `path: "/itemuombypage"`,
   `as: "uom"`, joins `ItemCode<->ItemCode` and `BaseUOM<->UOM` (`match: "casefold_trim"`),
   projects `Price -> BaseUOMPrice`. Full response saved:
   `ac10-04-product-task-save-response.json`.
4. `GET .../entities/product/mapping` confirmed every AC-10-04/59/73/74 preset row live:
   `BaseUOMPrice -> list_price` carrying `if(number(value) <= 0, 0, number(value))`; the
   `Description -> description` row carrying `trim(if(default(Desc2, "") != "", concat(Description,
   " ", Desc2), Description))` (a RAW join - `trim()` only strips the OUTER ends, so internal
   double spaces survive, per AC-10-60/D17's "one trim rule"); the `BaseUOM -> uom_code` row
   present but `isEnabled: false` (AC-10-74); no `cost_price` row at all. Saved:
   `ac10-04-59-73-74-mapping-rows.json`.

### AC-10-05 - preview-columns + preview with lookups

- `POST /autocount/http/preview-columns {connectionId, path: "/itemuombypage"}` ->
  `{"columns": ["ItemCode", "UOM", "Rate", "Price"]}` - matches the plan's documented wrapper
  shape exactly.
- `POST /autocount/http/preview` with the task's lookups -> `envelope: "paged"`,
  `totalCount: 11840` (matches the plan's `~11,840 items` fact exactly), `lookups: [{"alias":
  "uom", "matched": 50, "missed": 0}]` (the previewed page's 50 sampled rows, 100% matched), and
  `BaseUOMPrice` present as an ordinary alias column in `columns`/`rows`. Saved (trimmed to
  columns + lookups + one raw sample row, no full page dump):
  `ac10-05-preview-columns-lookups.json`.

### Test -> Activate -> Run now (run 1)

- `POST .../etl-task/preview` (the Source tab's real "Test" route, AC-22 gate) -> succeeded,
  `resultColumns` length 20 (19 source columns + `BaseUOMPrice`), `lastPreviewAt` stamped.
- `POST .../etl-task/activate` -> `etlStatus: "active"`, `activatedAt` stamped. `sinkImpl`
  untouched (`logging`).
- `POST .../etl-task/run` (run 1, `2026-09-19T18:37:38Z` -> `18:46:41Z`, ~9 minutes) ->
  `ac_sync_run` row `414d1a32-...`: `outcome SUCCESS, rows_scanned 11840, added_count 11840,
  updated_count 0, deleted_count 0, truncated false`. `complete` implied true (`rows_scanned ==
  totalCount`).

**Genuine live proof of AC-10-75's bounded retry + halving, unprompted** (this was not
engineered - the live wrapper genuinely timed out tonight): the main `/itembypage` walk at
`pageSize=1000` timed out on page 2 (one retry, succeeded on the 2nd attempt) and timed out
TWICE on page 3 (the halving trigger) - a `NOTE` activity row records exactly the designed
message: `"'/itembypage' timed out twice at the previous page size - halving to 500 and
restarting from page 1."` The walk then completed cleanly as 24 pages of 500 (11,840 rows,
matching `TotalCount`). Only ONE halving occurred (never reached `MAX_PAGE_HALVINGS`); the
`/itemuombypage` lookup walk (12 pages of 1000) had zero errors throughout, both runs. Full
`integration_activity` excerpt (operation, status, latency, response summary):
`ac10-75-retry-halving-activity-run1.txt`.

### Run 2 (idempotent replay, AC-10-06 / AC-10-54)

- `POST .../etl-task/run` (run 2, `2026-09-19T18:49:18Z` -> `18:58:35Z`, ~9 minutes, task
  UNCHANGED) -> `ac_sync_run` row `ef26b4e4-...`: `rows_scanned 11840, added_count 0,
  updated_count 0, deleted_count 0` - **exactly the AC's "0 added, 0 updated, 0 deleted" stable
  replay**, with the full enrichment (`BaseUOMPrice`) participating in `comparedFields`'s default
  hash. Run 2 ALSO independently hit and recovered from the same class of live timeout (page 8 at
  `pageSize=1000` twice, one more halving) - a second, independent confirmation of AC-10-75.

### Measured facts vs the plan's documented expectations (run 1, all 11,840 staged products)

Measured by reconstructing `CanonicalProduct(**row.canonical_json).sink_payload()` for every
staged row via the module's own model (never re-implemented) - this is the TRUE wire form a
`SorentoSink` would send (`sinks_sorento.py` calls the same `sink_payload()`); the logging sink's
own in-process log (`comparable()`, `modules/autocount/sinks.py`) is a fuller, unfiltered dump
used only for local diffing, not the wire contract, so `sink_payload()` is the correct thing to
check against AC-10-07/59/63/71/73/74's wire claims. Script: `measure-run1.py` (read-only,
imports only). Counts: `measure-run1-counts.txt`.

| Fact | Expected (plan, "may drift slightly") | Measured (run 1, live) | Match |
|---|---|---|---|
| Total items | ~11,840 | 11,840 | exact |
| `ItemCode`/enrich match rate | ~100% | 11,840 / 11,840 (100%, 0 enrich misses) | exact |
| Items with delivered `list_price == 0` (post-clamp, R5+R2) | ~5,008 raw-zero + ~121 clamped = ~5,129 | 5,129 | exact |
| Negative source price (`-1.0` sentinel) clamped to 0 | ~121 | 121 (all 121 confirmed delivered as `"0.0"`) | exact |
| `source_ref` prefix | `AED_SORENTO:<ItemCode>` on every row | 11,840 / 11,840 | exact |
| `list_price` wire type | JSON string | 11,840 / 11,840 strings, 0 non-string | exact |
| `uom_code` / `cost_price` / `remark` / `is_discontinued` keys in the delivered payload | absent on every row | 0 / 0 / 0 / 0 present | exact |
| Description rows with an internal double space preserved | ~2,786 | 2,768 | close (live data drift across the ~1-day gap the plan itself flags; not a defect) |

Targeted per-case payload examples (double-space description, negative-clamped, raw-zero) with
the raw source value alongside the delivered `sink_payload()` result:
`targeted-samples-output.txt` (script: `targeted-samples.py`).

### AC-10-08 - User-Agent

Confirmed in code (`modules/autocount/http_source/client.py:40`):
`USER_AGENT = "Foundryx-AutoCount-ESB/0.10.0"`, sent on every request alongside `Accept:
application/json` (line ~104). Live corroboration: every one of the dozens of live `GET` calls in
this run answered `200` (see the activity excerpt) - the wrapper is known to `403` a default
python-urllib UA (plan 08 finding, reused here), so a clean `200` on every call is itself live
evidence the explicit UA reached the wrapper. `tests/test_s10_http_client_user_agent.py` is also
in the Part A green count.

### AC-10-03 - enrich miss warning (not exercised, honestly reported)

Both runs matched 100% of rows against the `/itemuombypage` lookup (0 missed both times), so no
enrich-miss warning activity/`record_note` fired in this replay - correctly, since there was
nothing to warn about. The warning MECHANISM itself (one warning activity + one `record_note`
naming the alias and the miss count on a partial miss) is covered by `test_s10_http_lookups.py`
in Part A, not independently re-proven live here since db1's real data happens to enrich
perfectly (matches the plan's own documented fact: "every item has a row whose UOM equals its
BaseUOM").

## Observation (not a plan-10/S1 defect - pre-existing infra, flagged for awareness)

A single manual run only PUSHES up to `MASTER_RECORD_CAP = 5000` records per invocation
(`modules/autocount/services/company_service.py:225`, pre-existing, documented in that file's own
comment as "a deliberate over-provision"; unrelated to any S1 diff). Run 1 fetched+mapped+staged
all 11,840 rows but only pushed 5,000 through the logging sink before returning; run 2, re-walking
the full (unchanged) set, pushed a further 5,000 - for the SAME 5,000 `source_ref`s already pushed
in run 1, ac_staged_record now carries a SECOND row rather than being skipped/deduped - and
re-pointed the remaining 6,840 still-`STAGED` rows from run 1's `job_id` to run 2's. Net: 11,840
distinct products (correct, no invented/lost products), but `ac_staged_record` now holds 16,840
physical rows for this task. This governs PUSH QUEUE bookkeeping only, not the wire payload
content this pass verifies, and did not affect AC-10-06/54's own claim (which is about the RUN's
reported `added/updated/deleted` counts, correctly `0/0/0` on run 2) - flagging for the plan owner/
coder as a pre-existing staging-dedup gap worth a backlog entry, not filed as a new S1 defect.

## Servers

Backend `:8009` (pid 90663) killed after confirming its `cwd` was `s40/service_backend`;
`lsof -i :8009 -sTCP:LISTEN` confirmed free afterward. No frontend was started (this pass was
API-only, per the brief - `[T]` live replay, not `[E2E]`).
