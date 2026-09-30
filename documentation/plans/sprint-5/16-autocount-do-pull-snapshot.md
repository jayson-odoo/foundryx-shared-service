# Plan 16: AutoCount pull gateway `delivery_orders` snapshot (BL-SS-286)

Lane DO-PULL-SS, branch `crew/do-pull-snapshot`, 2026-09-30. Owner ask: the CRM's Delivery
Orders page gets a "Pull from AutoCount" action exactly like Products / Stock Balance (NOT a
run-now of the doc feed). Shared-service side: extend the existing snapshot gateway with a
scoped `delivery_orders` snapshot. Contract: `16-autocount-do-pull-snapshot-contract.md`.
UAC: `16-autocount-do-pull-snapshot-acceptance-criteria.md`.

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Reuse the products / stock snapshot end to end: same `AcPullSnapshot` / `AcPullSnapshotRow` tables, same `autocount_pull_snapshot` job type, `SnapshotService` write gate, `PullService.request_build` lifecycle, `PullGatewayService` gateway logic, retention / TTL / prune, audit, throttles. No new table, no migration. | Brief: "do not invent a new one" |
| D2 | Source = the DO doc feed's own vendor door `/deliveryorderbydocdate` via `DocFeedVendor` over the feed row's connection (plan 14). Not `HttpApiSource` (paged master-entity walker), not `byLastModified`. | A doc-date range is what the CRM user asks for; the feed already owns this door, its retry ladder and its book derivation |
| D3 | Scope on the wire is FLAT: `fromDay`, `toDay`, `docNo` on the build body; echoed flat on 202 + header. Stored in `metadata_json` from creation (so `building` / `failed` headers can echo it). | Simplest for the CRM client (`json={...}`); the header is a raw dict already |
| D4 | `docNo` alone defaults the range to the 31 MYT days ending today; the vendor has no by-DocNo door. Range cap 31 days (feed catch-up cap), floor 2023-01-01 (feed backfill floor), `toDay` <= MYT today. | "day-range (and/or DO number)" honoured without a new vendor door |
| D5 | Gate = a `delivery_orders` `ac_doc_feed` row with a connection; feed `mode` never gates; `ac_entity_config` not consulted; `PUSH_ACTIVE` never raised. | The pull is a read for a human review; the feed mode governs the hourly push only |
| D6 | Re-attach only on the SAME normalised scope; a different scope while one is building = 409 `BUILD_IN_FLIGHT` (additive). Cooldown 60 s applies only to the same scope. Products / stock: scope is `None` == `None`, so unchanged. | The DB's one-building-per-triple index stays the race closer; a different range must never silently re-attach to the wrong extraction |
| D7 | Rows = the raw vendor DO dict verbatim (D18 of plan 14), `source_ref` column `{book}:DO:{DocKey}`, `book` on the header. Order `DocDate` asc, `DocKey` asc; dedupe latest `LastModified`. | Byte-identical to what the feed pushes; the CRM reuses its DO ingest matching |
| D8 | No zero-row (`EMPTY_EXTRACT`) guard for DO; a scoped range is legitimately empty. Any day failure = `SOURCE_PAGE_FAILED`, nothing partial. `complete` always true on ready. Document cap 10,000 = `ROW_LIMIT`. | Scoped semantics differ from a whole-population master extract |
| D9 | `_resolve` in `doc_feed/runner.py` is split: `resolve_vendor(db, feed_row, vendor_transport)` (company active, connection + auth none, book match, `HttpApiClient` + `DocFeedVendor`) and the existing `_resolve` calls it then does sink + contract gate. Behaviour unchanged for the feed. | The snapshot needs the vendor half without the sink half |
| D10 | The DO build body lives in `modules/autocount/doc_feed/snapshot.py`; `sync._run_pull_snapshot` dispatches to it at the top when `entity_type == delivery_orders`, sharing `_fail_snapshot` / run-row / abandon helpers by passing them in (or duplicating the tiny closures locally, whichever keeps `sync.py` diff minimal). | Keeps the 400-line master build path untouched |
| D11 | Operator build route (`routers/pull.py`) refuses `delivery_orders` with 422 (no scope on the operator wire in this slice); operator list / detail render DO snapshots as-is. Frontend untouched. | Owner asked for the CRM-facing gateway only |

## 2. Slices

- S0: contract + UAC + plan (this commit set). Contract path relayed via crew report.
- S1 (tester, red): `tests/test_s16_do_pull_snapshot_gateway.py` (build route: scope validation,
  gating, re-attach, BUILD_IN_FLIGHT, cooldown, audit, header / rows shapes, products
  unchanged), `tests/test_s16_do_pull_snapshot_build.py` (job: vendor door usage, dedupe / order,
  docNo filter, excluded rows, metadata, failure ladder, row limit, progress, no feed side
  effects), `tests/test_s16_do_pull_snapshot_runner_split.py` (AC-16-50 resolve split).
  Fixtures: reuse `tests/fixtures/s14_doc_feed/do-vendor-day.json` + `s14_doc_feed_helpers.py`
  builders (`wired_company`, `route_transport`); feed rows via `DocFeedRepository.get_or_create`
  + `connection_id` / `book` set directly.
- S2 (coder, green): backend changes below. Existing `test_s10_*` and `test_s14_*` stay green.
- S3: reviewer + security-reviewer in parallel (gateway = public, API-key surface: scope echo
  sanitisation, body cap, no vendor URL leak in failed messages, tenant scoping of the feed row
  lookup). Docs (AC-16-60). PR, CI.

## 3. Backend changes (file map)

- `services/pull_gateway_service.py`: `ENTITY_WIRE_TO_INTERNAL["delivery_orders"] =
  DOC_FEED_DELIVERY_ORDERS`; `parse_do_scope(raw, today_myt) -> DoScope | raises
  PullGatewayError(422, INVALID_REQUEST, ...)`; `build()` takes `scope`; DO gating via
  `DocFeedRepository.get(tenant, company, delivery_orders)` (+ `connection_id`) instead of the
  entity-config ladder; `gateway_snapshot_header` emits the DO keys from `metadata_json`
  (`fromDay`, `toDay`, `docNo`, `book` on every status; `daysRead`, `fetchedCount`, `lineCount`
  on ready) and never for other entities.
- `services/pull_service.py`: `request_build(..., scope: Optional[dict] = None)`: same-scope
  re-attach, `PullBuildInFlightError` for a different scope, cooldown keyed on scope equality,
  `metadata_json = {"fromDay","toDay","docNo"}` at creation, scope in the job payload.
  `snapshot_header` (operator) unchanged except it already passes metadata through.
- `routers/pull_v1.py`: parse `fromDay` / `toDay` / `docNo` (strings only, `_safe_echo`-style
  sanitisation), reject scope keys on non-DO entities, echo the normalised scope on the 202;
  map `PullBuildInFlightError` -> 409 `BUILD_IN_FLIGHT`.
- `doc_feed/runner.py`: D9 split, `resolve_vendor` public (used by `snapshot.py`).
- `doc_feed/snapshot.py` (new): `build_delivery_orders_snapshot(db, job, snapshot, company,
  feed_row, scope, helpers)`: per-day `day_by_doc_date`, heartbeat + abandon check per day,
  dedupe, docNo filter, order, excluded rows, cap, insert rows (beat every 200), metadata,
  `stamp_ready`; failures via the shared `_fail_snapshot` with pinned codes.
- `sync.py::_run_pull_snapshot`: early dispatch for `delivery_orders` (feed row lookup, no
  `EntityConfig` requirement for this entity).
- `routers/pull.py`: 422 for `entityType == delivery_orders` on the operator build.
- Docs: engineering doc section, backlog row, CLAUDE.md index row.

## 4. Test list for the tester (beyond the UAC ids)

- Kill test: remove the scope-equality check in `request_build` -> AC-16-10 must fail.
- Control: products build with no scope keys still 202 and still hits `HttpApiSource` (stub as
  `test_s10_s4_gateway_build.py` does).
- The DO build must NOT call `/api/v1/external/contract` or any `/api/v1/external/ingest/*`
  path: use `route_transport` with only the DO door routed (an unrouted path asserts).
