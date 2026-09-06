# 30 - Omnichannel Dashboard + Reports v1

> **Contract:** `30-omnichannel-dashboard-reports-acceptance-criteria.md` (55 ACs). This plan fulfils it.
> **Program:** slice **A9** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gaps G15 + G16).
> **Depends on:** plan 25 (A1 lifecycle), plan 26 (A2 `contact_filters.py` + the `background_jobs`
> export pattern), plan 27 (A3 `conversation_events`, `close_reasons`,
> `contacts.last_agent_message_at`) - all merged to `origin/main` at `58759ed`.
> **Branch:** `sprint-4/30-dashboard-reports`, worktree `.claude/worktrees/s30` off `origin/main`
> `58759ed`. Lane: backend `:8009` on DB `foundryx_service_s30`, frontend `:3008`,
> `agent-browser --session s30`. Each worktree gets its OWN `npm ci` (never a shared
> `node_modules`). The main checkout carries the user's unrelated wip - never build there.
> **Runs beside:** plan 28 (A8 teams, migration `0012` / manifest `0.6.0`) and plan 29 (A4
> broadcasts, migration `0011` / manifest `0.5.0`). A9 stays on manifest `0.4.0` (amended
> 2026-09-06, D-A9-10 - reusing core `reports.*` permission keys means no new grantable module key
> and no version bump) and, by default, NO migration (see D-A9-14).

## 1. Why

Every respond.io dashboard tile and every one of its reports is an aggregate over conversation
lifecycle events. Plan 27 landed exactly that table and made nine mutation seams write it, plus a
backfill for pre-existing threads. Nothing reads it yet: the only surface is the per-thread
Activities feed. A9 turns `conversation_events` into the read model the operator lives in - one
dashboard (current state + the last 7 or 30 days) and seven reports (conversations, responses,
resolutions, messages, users, leaderboard, assignment log) - with no new fact tables, no new
events, and no second copy of the contacts filter vocabulary.

## 2. Architecture

```
READ MODEL (no new tables, D-A9-1)
  app_omnichannel.conversation_events   opened|closed|reopened|snoozed|unsnoozed|assigned|
                                        unassigned|first_agent_reply|lifecycle_changed|comment_added
  app_omnichannel.conversation_messages  direction (sender_type) + channel + sender  [join contacts for workspace]
  app_omnichannel.contacts               CURRENT state tiles + lifecycle stage counts
  core public.statuses                   lifecycle stage labels (scoped, via lifecycle_service)
  app_omnichannel.close_reasons          close-reason breakdown

ONE aggregation core
  services/report_windows.py   bucket edges from zoneinfo (PYTHON) -> [(key, starts_at, ends_at)]
  services/report_queries.py   conditional-aggregate SQL over the edges (ONE pass, dialect-free)
                               + bounded duration projections for the percentile reports
  services/report_service.py   the seven report builders + the dashboard builder, filter validation
  services/report_export_service.py   JobHandlerDef("omnichannel.report_export") -> CSV -> storage

ROUTES  routers/reports.py  (manifest prefix /omnichannel/workspaces, like contacts.py)
```

The whole design rests on **D-A9-8: bucket edges are computed in Python and applied as conditional
aggregates**, never `date_trunc` / `strftime`. That is what makes the pytest SQLite numbers and the
production Postgres numbers identical, and what makes a DST-spanning day bucket 23 hours wide
without a special case.

### 2.1 Backend pieces (every path verified at `58759ed`)

| Piece | Where | Notes |
|---|---|---|
| Bucket windows | `service_backend/modules/omnichannel/services/report_windows.py` (new) | `resolve_range(from_date, to_date, tz) -> (start_utc, end_utc)`, `auto_granularity(span)`, `bucket_edges(start_utc, end_utc, tz, granularity) -> [Bucket(key, starts_at, ends_at)]`, `MAX_BUCKETS = 120`. Pure Python + `zoneinfo`; no DB, fully unit-testable |
| Query core | `services/report_queries.py` (new) | `bucketed_counts(db, base_query, ts_column, edges, series_filters) -> Dict[str, List[int]]` (one SELECT, one `func.sum(case(...))` per bucket per series), `duration_samples(...)` (bounded single-column projection), `REPORT_MAX_SAMPLE_ROWS = 100_000` |
| Percentiles | `services/report_stats.py` (new) | `percentile(sorted_values, p)` (linear interpolation, `i = p*(n-1)`), `median`, `average`, `bucket_distribution(values, RESPONSE_BUCKETS)`. Pure functions, no SQL - D-A9-9 |
| Report service | `services/report_service.py` (new) | `dashboard(...)` + `report(key, ...)` + `REPORTS` descriptor registry (key, label, `supports_group_by`, `paginated`, `exportable`) - the ONE list `reports/meta` publishes and `reportKey` / `groupBy` validate against |
| Filter validation | `services/report_filters.py` (new) | `ReportQuery` dataclass; validates `tz` via `zoneinfo`, `from`/`to`, `granularity`, `userId` (tenant-scoped), `channelId` (workspace-scoped), `groupBy` (per-report whitelist), `teamId` (422 while `team_column()` is None). REUSES `contact_filters.CONTACT_FILTER_COLUMNS` for any contact-side predicate - never a second map |
| Team seam | `services/report_filters.py team_column()` | `getattr(Contact, "assigned_team_id", None)`; returns `None` until plan 28 lands. Every report reads the dimension through this one accessor (D-A9-13) |
| Export | `services/report_export_service.py` (new) | `JobHandlerDef(type="omnichannel.report_export", ...)` via `app/jobs/registry.register_job_handler`; row stream -> `sanitize_cell` -> CSV -> `storage_for_tenant(db, tenant).save(...)`; `result_json = {fileKey, rowCount, columns}`; job status re-read per batch (cooperative abort). Copies `services/contact_export_service.py` structure, does not re-invent it |
| Router | `routers/reports.py` (new) | HTTP + Pydantic only. Reads gated `require_permission("reports.read")`, exports `require_permission("reports.export")` (**amended 2026-09-06** - see D-A9-10); `WorkspaceService(db).get_or_404(ws_id, tenant_id)` first line of every handler |
| Schemas | `modules/omnichannel/schemas.py` | `DashboardResponse`, `ReportMetaResponse`, `ReportResponse`, `ReportBucket`, `ReportSeries`, `ReportRow` variants, `ReportExportRequest`. Datetime-bearing schemas inherit `ApiModel`; wire is camelCase via `validation_alias` |
| Permissions | `modules/omnichannel/permissions/permissions.csv` | **No new rows (amended 2026-09-06, D-A9-10).** The module CSV declares nothing for reports; both routes reuse the core `reports.read`/`reports.export` keys, already granted to every tenant Admin |
| Manifest | `modules/omnichannel/manifest.json` | **Stays `0.4.0` (amended 2026-09-06).** The `reports` router entry was already added at that version by S1; reusing core permission keys means there is no new grantable module key to version-gate, so S3 adds no bump either |
| Tenant hook | `modules/omnichannel/bootstrap.py update_tenant` | **No new guard branch needed (amended 2026-09-06).** No manifest bump, no new permission rows to sync/grant - `sweep_tenant_admin_grants`/`tenant_admin_grant` already cover the core `reports.*` keys for every existing tenant |
| Test fixture | `service_backend/tests/omnichannel_report_fixture.py` (new) | `seed_report_fixture(db, tenant_id, workspace_id) -> FixtureIds` producing EXACTLY the UAC fixture table; imported by every report test |

Reused unchanged: `services/event_service.py` (`_label_map` batching pattern for tenant-scoped id
resolution), `services/lifecycle_service.py stages_for_workspace`, `services/contact_filters.py`,
`services/workspace_service.py get_or_404`, `app/jobs/*`, `app/services/storage.py`,
`app/import_engine/sanitize.py`, `app/dependencies.require_permission`.

### 2.2 Frontend pieces

| Piece | Where |
|---|---|
| Routes | `service_frontend/app/(protected)/omnichannel/dashboard/page.tsx`, `omnichannel/reports/page.tsx` |
| Shared filter bar | `app/(protected)/omnichannel/components/report-filter-bar.tsx` (+ `use-report-filters.ts` for the URL sync) - ONE component used by both pages |
| Date range | `components/platform/date-range-picker/` (new shared primitive: `Popover` + existing `Calendar` in `mode="range"` + a preset `SearchSelect`; no new dependency - D-A9-15) |
| Chart adapter | `components/platform/report-chart/report-chart.tsx` (new thin wrapper over the EXISTING `components/ui/chart.tsx`; maps `{buckets, series}` -> `ChartConfig` + recharts `<BarChart>` / `<LineChart>`) |
| Dashboard | `omnichannel/dashboard/components/`: `state-tiles.tsx`, `lifecycle-tiles.tsx`, `opened-closed-card.tsx`, `duration-stat-card.tsx`, `top-agents-card.tsx` |
| Reports | `omnichannel/reports/components/`: `report-picker.tsx` (`SearchSelect`), `conversations-report.tsx`, `responses-report.tsx`, `resolutions-report.tsx`, `messages-report.tsx`, `users-report.tsx`, `leaderboard-report.tsx`, `assignments-report.tsx` (+ `use-assignment-log-config.tsx`, `use-users-report-config.tsx` - embedded `ResourceList` configs) |
| Export | `omnichannel/reports/components/use-report-export.ts` - lifts the A2 contacts-export controller (create job -> poll `/jobs/{id}` -> `apiFetchBlob` the authed file route -> Jobs-drawer fallback) |
| Duration format | `lib/duration.ts` (new) `formatDuration(seconds)` -> `45s` / `1m 30s` / `3h 30m` / `6d 0h` |
| Service trio | `services/omnichannel-report-service.{ts,mock,real}.ts` |
| Hooks | `hooks/use-report-meta.ts`, `hooks/use-omnichannel-dashboard.ts`, `hooks/use-omnichannel-report.ts` |
| Types | `types/omnichannel.ts` += `ReportMeta`, `ReportDescriptor`, `ReportBucket`, `ReportSeries`, `ReportResponse`, `DashboardResponse`, `ReportFilters` |
| Menu | `config/menu.config.tsx` - Dashboard (before Inbox) + Reports (after Contacts) in ALL THREE arrays, tagged `module: 'omnichannel'` + `permission: 'reports.read'` (**amended 2026-09-06** - see D-A9-10) |

Reused unchanged: `components/platform/resource-list`, `search-select`, `page-header`,
`components/common/container`, `components/common/require-permission`, `components/ui/{card,
tabs,popover,calendar,skeleton,chart}`, `hooks/use-can.ts`, `hooks/use-datetime.ts`,
`hooks/use-contacts.ts useActiveWorkspace`, `hooks/use-workspace-members.ts`,
`services/jobs-service.*`, `components/platform/jobs-drawer`.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D-A9-1 | Data source = `conversation_events` + `conversation_messages` + `contacts`. No new fact tables, no new events, no materialized rollups in v1 | Main session 2026-09-06. A3 already writes every event A9 needs and backfilled the history; a rollup is premature before a real tenant's volume is known (backlog BL-SS-090) |
| D-A9-2 | Dashboard content = state tiles, lifecycle stage counts, opened vs closed series, response + resolution medians, top agents. Team presence deferred | Main session. Presence needs an online-status source we do not have (A8 follow-up) |
| D-A9-3 | Reports = ONE page, a report `SearchSelect` + the shared filter bar, seven reports; each report = one endpoint returning `{buckets, series, rows, totals}` | Main session. A left rail (respond.io's shape) is a backlog polish item; a picker is one component and works identically at 375px |
| D-A9-4 | Export = CSV through the A2 `background_jobs` pattern (`omnichannel.report_export`), authed download route | Main session. One job type covers all seven reports (the report key rides in the payload) |
| D-A9-5 | Menu = Dashboard + Reports as top-level omnichannel entries in all three arrays (roadmap D10) | Main session |
| D-A9-6 | A9 adds NO events. For a contact with no `first_agent_reply` event the response time is DERIVED from `conversation_messages` (first `AGENT` row minus the latest `CONTACT` row strictly before it), attributed to that message's sender; `SYSTEM` notes never count | Main session. Keeps pre-A3 threads reportable without backfilling a synthetic event, and without any on-screen caveat copy. `totals.derivedFromMessages` exposes how many datapoints came that way, for support - it is not rendered as prose |
| D-A9-7 | Out of scope: custom report builder, scheduled report emails, team presence, broadcast reports, lifecycle funnel / time-in-stage / contacts-added (reports v2) | Main session |
| **D-A9-8** | **Bucket edges are computed in Python from `zoneinfo`; aggregation is conditional `SUM(CASE ...)` over those edges in ONE SQL pass.** No `date_trunc`, no `strftime`, no dialect branch | Planner. `date_trunc(... AT TIME ZONE ...)` is Postgres-only, so the pytest suite (SQLite) could only ever test a fallback - and the ACs demand exact numbers from the real code path. Python edges are also DST-correct by construction (a London day bucket is 23h wide because `zoneinfo` says so) and cost one bounded `CASE` list, capped at 120 buckets |
| **D-A9-9** | **Percentiles, medians and durations are computed in Python** over a bounded single-column projection (`REPORT_MAX_SAMPLE_ROWS = 100_000`, 422 beyond); counts and sums stay in SQL | Planner. `percentile_cont` is Postgres-only; timestamp subtraction is dialect-specific. One reduction path means one set of numbers to test. The cap is the same fail-fast shape A2's export cap uses |
| **D-A9-10** | **Permission keys are the CORE `reports.read` / `reports.export` - the module declares NO `conversation_reports.*` rows.** (**Amended 2026-09-06 by the main session, final** - superseding the planner's original "declare `conversation_reports.*`" draft below.) | Planner's original reasoning stands (core already declares `reports.read`/`reports.export`, `app/permissions/permissions.csv` L39-40; `Permission.key` is globally UNIQUE and `PermissionRepository.sync` is delete-by-module, so a module row of the same name would `IntegrityError` at install and, worse, delete core's rows + every grant at uninstall - same shape as the `templates` vs `wa_templates` collision) but the CONCLUSION flips: rather than mint a parallel `conversation_reports.*` pair, S1/S2/S3 REUSE the core keys directly (`require_permission("reports.read"/"reports.export")`). Reasons: (1) "Conversation Reports" is not a materially different resource from core "Reports & Analytics" - both core rows were seeded unused specifically for a future reports feature, and this IS that feature; (2) reuse needs zero new CSV rows, zero manifest version bump, zero `update_tenant` guard branch, and zero grant-sweep migration, because `tenant_admin_grant`/`sweep_tenant_admin_grants` already grant every core key (including these two, previously dormant) to every tenant Admin; (3) a module-scoped pair would still need its own grant-sweep the day it ships, for zero practical isolation benefit (both keys gate the SAME ten routes either way). Trade-off accepted: uninstalling the omnichannel module can never revoke reports access (the keys are core, not module-owned) - acceptable since nothing else currently uses them and a future SECOND module wanting its own reports surface reuses the same two keys rather than forking a per-module resource name (documented here so nobody re-forks `conversation_reports.*` later) |
| **D-A9-11** | A bucket's `key` is already LOCAL (`2026-03-01`, `2026-03-01T09`, `2026-W10`, `2026-03`); the client formats the axis label from the key and never re-applies a timezone. Only `startsAt` / `endsAt` are UTC instants | Planner. The classic bug in this feature class is double conversion: the server buckets in Asia/Kuala_Lumpur, then `useDatetime` shifts the label again. A local key cannot be shifted twice |
| **D-A9-12** | The `conversations`, `responses`, `resolutions` and `assignments` reports read only `conversation_events` (well indexed by A3). The `messages` report joins `conversation_messages -> contacts`, whose only usable index is `contact_id`; ship an INDEX-ONLY migration adding `ix_conv_messages_tenant_created (tenant_id, created_at)` if S2 measures a seq scan on a seeded 100k-row table, otherwise defer | Planner. `conversation_messages` is the largest table in the module and the one report that touches it is the one most likely to time out first |
| **D-A9-13** | Team is an OPTIONAL dimension read through ONE `team_column()` accessor that returns `None` until plan 28 lands; `reports/meta` advertises `dimensions.team.available` and the frontend hides the control accordingly; `teamId` / `groupBy=team` are 422 until then | Planner + brief. A8 turns the dimension on by adding the column - no report SQL changes |
| **D-A9-14** | Manifest stays `0.4.0` (**amended 2026-09-06, D-A9-10** - superseding the planner's original `0.4.0 -> 0.4.1`, since reusing core permission keys leaves no new grantable module key to version-gate), new `reports` router, NO Alembic migration by default. If D-A9-12's index ships, the revision takes the next free number at MERGE time (reserve `0013`) and rebases its `down_revision` onto whatever is head then | Planner (manifest-bump clause superseded by the main session). A4 claims `0011` / `0.5.0` and A8 `0012` / `0.6.0` off the same `main`; a duplicated parent is a merge break git cannot see (the D-A3-16 lesson) |
| **D-A9-15** | Charts render through the EXISTING `components/ui/chart.tsx` (shadcn + recharts), not `apexcharts`. A new `components/platform/date-range-picker` is built from existing `Popover` + `Calendar` primitives | Planner. Both libraries are already in `package.json`; apex is used by exactly one demo page behind `dynamic ssr:false`, while `chart.tsx` already wires `ChartConfig` colours to CSS variables (so brand tokens win) and needs no client-only shim. A4 broadcasts will reuse the same date-range control |
| **D-A9-16** | Every report is workspace-scoped (`/omnichannel/workspaces/{wsId}/...`), workspace resolved on the client exactly like Contacts (default first, header `SearchSelect` only when the tenant has more than one) | Planner. Matches A2's D-A2-10 and A2/A3's route shape; a tenant-wide "all workspaces" roll-up is a backlog item |

### 3.1 Data-viz rules (the `dataviz` skill is not installed in this environment - these are the rules that apply)

- Colour comes from Foundryx brand CSS variables through `ChartConfig` (`var(--primary)`,
  `var(--chart-2..5)`); never a hard-coded hex, never a rainbow ramp, never `<style>` or raw CSS.
- A series is identifiable WITHOUT colour: legend + tooltip label always, direct labels where a
  single value dominates. Two-series charts (opened vs closed, incoming vs outgoing) use one filled
  and one outlined treatment so they read in greyscale.
- Bars for counts per bucket, lines for a rate or a duration trend, a plain table for a
  distribution (the response-time breakdown is a table, exactly as respond.io renders it).
- No 3D, no donut for more than four slices, no dual y-axis. Zero-baseline always.
- At 375px the axis thins its ticks (first / last / every Nth) rather than rotating text into
  overlap; the chart never forces horizontal page scroll.
- Empty state = a short status line inside the card ("No data in this range"), never instructional
  copy about how to change the filters (foolproof-UI mandate).

## 4. Slices (build order - one Sonnet coder lane each, sequential on the branch)

| Slice | Content | Size | AC ids |
|---|---|---|---|
| **S0 FE mock** | types, `omnichannel-report-service` trio (mock returns EXACTLY the UAC fixture numbers), `lib/duration.ts`, `date-range-picker`, `report-filter-bar` + URL sync, `report-chart` adapter, dashboard page + its five cards, reports page + picker + all seven report renderers (assignment log and users as embedded `ResourceList`), menu entries in all three arrays, vitest for every new component; agent-browser smoke at 375 + 1280 against the mock | **L** | 41-46, 48-50, 52 |
| **S1 BE aggregation + dashboard** | `report_windows.py`, `report_queries.py`, `report_stats.py`, `report_filters.py` (+ `team_column`), `report_service.dashboard`, `GET .../dashboard`, the shared test fixture, pytest incl. the two-dialect golden compile and the DST test | **M** | 01-16, 51 (partial) |
| **S2 BE reports + assignment log** | the seven report builders + `GET .../reports/meta` + `GET .../reports/{key}`, `groupBy` whitelists, pagination + stable tiebreaks, the D-A9-12 index measurement (and the index-only migration only if it is needed), pytest | **L** | 17-32, 51 (partial) |
| **S3 BE export + permissions** | `report_export_service.py` (job handler, CSV, cap, cooperative abort), the two export routes, pytest. **No permissions-CSV/manifest/`update_tenant` change (amended 2026-09-06, D-A9-10)** - both export routes reuse the core `reports.export` key | **M** | 33-40, 47 (backend half), 51 (partial) |
| **S4 Wire + E2E** | swap mocks for real at the service boundary (one line per method in `*.real.ts`), export poll-then-Jobs fallback against the real job, responsive pass at 375 + 1280 on both pages, recorded agent-browser evidence run, Test Execution Report | **M** | 47, 49, 53-55 |
| **Review** | `reviewer` agent on **Opus** (ten new routes, a PII-egress CSV path, and an aggregation layer that must not leak a cross-tenant name through a polymorphic actor id), then `/codex-review` | - | - |

S1 must land before S2 (every report builder consumes `report_windows` + `report_queries`) and
before S3 (the export streams the same builders). S0 is independent and can start immediately.

## 5. Contracts

### 5.1 Internal API (camelCase, datetimes Z-suffixed via `ApiModel`)

```
GET  /omnichannel/workspaces/{wsId}/dashboard
       ?from=YYYY-MM-DD&to=YYYY-MM-DD&tz=<IANA>&granularity=&userId=&channelId=&teamId=
       -> DashboardResponse                                   (reports.read - amended 2026-09-06, D-A9-10)

GET  /omnichannel/workspaces/{wsId}/reports/meta
       -> { reports: ReportDescriptor[], granularities: [...], dimensions: { team: {available} } }

GET  /omnichannel/workspaces/{wsId}/reports/{reportKey}
       ?from&to&tz&granularity&userId&channelId&teamId&groupBy&page&pageSize
       -> ReportResponse                                      (reports.read - amended 2026-09-06, D-A9-10)

POST /omnichannel/workspaces/{wsId}/reports/{reportKey}/export
       { from, to, tz, granularity?, userId?, channelId?, groupBy? }  -> { jobId }   (…export)
GET  /omnichannel/workspaces/{wsId}/reports/{reportKey}/export/{jobId}/file
       -> text/csv attachment                                                        (…export)
```

`reportKey` is one of `conversations | responses | resolutions | messages | users | leaderboard |
assignments`.

### 5.2 Wire shapes

```
Bucket             {key, startsAt, endsAt}
Series             {key, label, points: number[]}          // points aligned to buckets by index
DurationStats      {medianSeconds|null, p90Seconds|null, averageSeconds|null,
                    sampleCount, derivedFromMessages?}

DashboardResponse  {timezone, range:{from,to}, granularity, buckets: Bucket[],
                    tiles:{open, assigned, unassigned, snoozed},
                    lifecycle:[{statusId,key,label,color,sortOrder,count,percent}],
                    series:{opened:number[], closed:number[]},
                    responseTotals: DurationStats,
                    resolutionTotals: DurationStats,
                    topAgents:[{userId,name,closedCount,medianResponseSeconds|null}]}

ReportDescriptor   {key, label, supportsGroupBy: string[], paginated: bool, exportable: bool}

ReportResponse     {reportKey, timezone, range, granularity, buckets: Bucket[],
                    series: Series[], rows: object[], totals: object,
                    page?, pageSize?, total?}
```

Per-report `rows` / `totals`:

| reportKey | series | rows | totals |
|---|---|---|---|
| `conversations` | opened, closed, reopened | (none) | `{opened, closed, reopened}` |
| `responses` | (none) | the 7-bucket distribution `{bucket,label,count,percent}`, or per-user when `groupBy=user` | `DurationStats` |
| `resolutions` | (none) | close-reason breakdown `{closeReasonId,name,count,percent}`, or per-user when `groupBy=user` | `DurationStats` |
| `messages` | incoming, outgoing | per channel when `groupBy=channel` `{channelId,name,channelType,incoming,outgoing}` | `{incoming, outgoing}` |
| `users` | (none) | `{userId,name,teamName,assignedCount,closedCount,uniqueContacts,messagesSent,commentsCount,medianFirstResponseSeconds,medianResolutionSeconds}` | `{userCount}` |
| `leaderboard` | (none) | the `users` rows + `rank`, ordered closed desc / median asc / name asc | `{userCount}` |
| `assignments` | assigned | the paginated log `{id,createdAt,contactId,contactName,eventType,previousAssigneeId,previousAssigneeName,assignedToId,assignedToName,source,actorUserId,actorName}` | `{assigned, unassigned}` |

`supportsGroupBy`: `responses` and `resolutions` -> `["user"]` (`"team"` once A8 lands), `messages`
-> `["channel"]` (`"team"` later), everything else -> `[]`.

### 5.3 The bucketing approach (D-A9-8) - what the coder writes

```python
# report_windows.py  (pure Python, no DB)
def resolve_range(from_date, to_date, tz):        # tz = ZoneInfo(name)
    start_local = datetime.combine(from_date, time.min, tzinfo=tz)
    end_local   = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

def bucket_edges(start_utc, end_utc, tz, granularity) -> list[Bucket]:
    # walk in LOCAL calendar units (day/week/month) or in local hours, converting
    # each local boundary to UTC with .astimezone(timezone.utc).
    # A DST-short day is naturally 23h wide because the two local midnights are
    # 23h apart in UTC. Raise BucketLimitExceeded above MAX_BUCKETS (120).
```

```python
# report_queries.py  - ONE pass, dialect-free
cols = [
    func.sum(case((and_(ts >= b.starts_at, ts < b.ends_at), 1), else_=0)).label(f"b{i}")
    for i, b in enumerate(edges)
]
row = db.query(*cols).filter(*base_filters).one()
```

For a multi-series chart, add one `case` column per (series, bucket) with the series predicate
ANDed in, still ONE query. For a grouped report, `GROUP BY` the dimension and select the same
`case` columns. `ts` is `ConversationEvent.created_at` or `ConversationMessage.created_at`; both
are `UTCDateTime`, so the comparison is a plain bound-parameter comparison on both dialects.

Durations never touch SQL arithmetic: `duration_samples()` projects the raw columns
(`payload_json["responseSeconds"].as_integer()` for responses - the same typed-JSON comparator
`contact_filters.py` already uses; `(closed_at, cycle_start_at)` pairs for resolutions) with
`LIMIT REPORT_MAX_SAMPLE_ROWS + 1`, and `report_stats.py` reduces them.

The resolution cycle-start pairing is a correlated scalar subquery (portable on both dialects):

```
cycle_start = (select(func.max(E2.created_at))
               .where(E2.contact_id == E.contact_id,
                      E2.event_type.in_(("opened", "reopened")),
                      E2.created_at <= E.created_at)
               .correlate(E).scalar_subquery())
```

The legacy response derivation (D-A9-6) is a second, disjoint query: contacts in the workspace with
NO `first_agent_reply` event at all (`NOT EXISTS`), joined to their first `AGENT` message and the
latest `CONTACT` message strictly before it. Its results are unioned into the same sample list and
counted in `totals.derivedFromMessages`.

### 5.4 CSV export

One job type, the report key in the payload. Columns per report = the `rows` keys in declaration
order, with human labels in the header. Timestamps render as `YYYY-MM-DD HH:MM:SS +08:00` in the
requested `tz`. Every cell goes through `sanitize_cell`. Cap 50000 rows, checked synchronously
before the job row is created (the `ExportRowCapExceeded` precedent). The download route is a
byte-for-byte copy of `routers/contacts.py download_contacts_export`'s guard set (tenant +
workspace + type + DONE + `fileKey`, uniform 404, sandbox CSP, nosniff, no-store, presigned
redirect for object storage).

### 5.5 Frontend build order (mock first, one-line swap)

S0 writes `services/omnichannel-report-service.mock.ts` returning the UAC fixture verbatim, so the
whole UI (charts, tables, filter bar, export controller stub, responsive behaviour) is buildable
and unit-testable before any endpoint exists. S4's swap is one line per method in
`omnichannel-report-service.real.ts` plus flipping the barrel in
`omnichannel-report-service.ts` - the components never change.

## 6. Risks + mitigations

- **Query cost on a large tenant.** `conversation_events` carries A3's three indexes -
  `(tenant_id, workspace_id, created_at)`, `(tenant_id, contact_id, created_at)`,
  `(tenant_id, event_type, created_at)` (verified in `models.py` L395-399) - and the workspace +
  range predicate hits the first one; the conditional `CASE` list is evaluated over the already
  filtered rows. `conversation_messages` has NO `(tenant_id, created_at)` index (verified: only
  per-column indexes plus `uq_message_external_id`), so the messages report is the one that will
  degrade first - D-A9-12 measures it on a seeded 100k-row table in S2 and ships an index-only
  migration if needed. Materialized rollups stay a backlog item until a real tenant's volume is
  known.
- **Cross-tenant name leak through a polymorphic actor id.** `actor_user_id`, `to_value` and
  `from_value` are stored ids of several kinds (thread status, core lifecycle status, user,
  external agent). Every resolution must be batched AND tenant-scoped in the same shape
  `event_service._label_map` already uses (it additionally constrains lifecycle ids by
  `entity_type` + `scope_id`). An unresolvable id renders an empty name. This class has leaked
  twice in this codebase; the reviewer rejects any bare `get_by_id` in the report path.
- **Double timezone conversion.** Mitigated structurally by D-A9-11 (the bucket key is local, so
  there is nothing left to convert). A vitest asserts the axis label for `2026-03-01` renders as
  `1 Mar` under a browser tz of `America/Los_Angeles`.
- **Numbers that only hold on one dialect.** D-A9-8 + D-A9-9 remove every dialect branch from the
  number path; a golden test compiles the bucketing statement on both a SQLite and a Postgres
  dialect and asserts the same parameterized SQL shape.
- **Permission collision with core `reports.*`.** Real and hard (D-A9-10). The reviewer must grep
  `app/permissions/permissions.csv` against the module CSV; a duplicate key is a merge reject.
- **Three Phase-A lanes on one module.** A4 (`0011` / `0.5.0`), A8 (`0012` / `0.6.0`) and A9
  (`0.4.1`, no migration) all branch off `58759ed` and all touch `manifest.json`,
  `permissions.csv`, `bootstrap.update_tenant` and `config/menu.config.tsx`. Keep A9's code in NEW
  files; the only shared lines are the manifest router array, the CSV tail, one `update_tenant`
  branch and the three menu arrays. Re-check the version at merge time.
- **Shared Postgres across worktrees.** Lane s30 owns `foundryx_service_s30`; reseed only from the
  branch you are serving (`sync_permissions` is delete-by-module).
- **Wrong build on a port.** Frontend `:3008` is the lane's; before evidence, kill only the server
  pid whose cwd is this worktree, `rm -rf .next && npm run build`, start once.
- **Empty demo data.** The dev seed's demo inbox (`chn-demo`, threads `cnt-001..005`) only carries
  A3's backfilled `opened` events, so the demo dashboard will show a flat series. The E2E run must
  generate a few real events by clicking (assign, close with a reason, reply) before screenshotting
  the charts, or the evidence proves nothing.

## 7. Backlog candidates (proposed ids - the lane coder registers them in `documentation/backlogs/backlog.md` on close, each linking back to this plan)

`BL-SS-082..089` are reserved by plan 29 after renumbering, so this slice starts at 090.

**Registered 2026-09-06 (review round 1)**: all twelve rows below are now in
`documentation/backlogs/backlog.md` under these ids, each linking back to this plan. The
plan's `P0/P1/P2` map onto the register's `High/Medium/Low` column. BL-SS-091 carries the
D-A9-12 measurement in full (1,000,000 seeded `conversation_messages` rows, ~37-49 ms via
the existing single-column `tenant_id` index with OR without the composite index once
`ANALYZE` has run - so the index was deferred, not shipped).

| Proposed id | Title | Priority |
|---|---|---|
| BL-SS-090 | Omnichannel reports: materialized daily rollup table + incremental refresh job (replaces the live aggregate once a tenant outgrows it) | P1 |
| BL-SS-091 | Omnichannel reports: `(tenant_id, created_at)` index on `conversation_messages` if D-A9-12's measurement defers it | P1 |
| BL-SS-092 | Omnichannel reports: team dimension turned on (filter + `groupBy=team` + `teamName`) once plan 28 / A8 lands | P0 (blocked on A8) |
| BL-SS-093 | Omnichannel dashboard: team presence panel (online status + assigned-count per member) | P2 |
| BL-SS-094 | Omnichannel reports: scheduled report emails (a cron workflow rendering a report through `render_email`) | P2 |
| BL-SS-095 | Omnichannel reports: lifecycle funnel, time-in-stage and contacts added / merged (reports v2, roadmap Phase D) | P2 |
| BL-SS-096 | Omnichannel reports: tenant-wide roll-up across all workspaces (today every report is single-workspace) | P2 |
| BL-SS-097 | Omnichannel reports: comment log on the Users report (respond.io parity - the second table on that page) | P2 |
| BL-SS-098 | Omnichannel reports: left rail of report names at >= `lg` instead of the `SearchSelect` (respond.io shape) | P2 |
| BL-SS-099 | Omnichannel reports: previous-period comparison line + delta percentage on every metric card (respond.io shows both) | P2 |
| BL-SS-100 | Omnichannel reports: `first assignment -> first response` and `last assignment -> first response` metrics (respond.io Responses report has all three) | P2 |
| BL-SS-101 | Platform: export blob garbage collection for `background_jobs.result_json.fileKey` artefacts (shared with A2's contacts export) | P2 |

## 8. Flagged for the user (planner deviations from the 2026-09-06 decision set)

1. **RESOLVED 2026-09-06 (main session, final): reuse the CORE `reports.read` / `reports.export`
   keys - the module declares NO `conversation_reports.*` rows.** The planner's original flag stood
   at "declare `conversation_reports.read`/`.export`" for the reason still true today (core already
   declares both keys, `service_backend/app/permissions/permissions.csv` lines 39-40, previously
   unused by any route; `Permission.key` is globally unique and `PermissionRepository.sync(module,
   rows)` selects existing rows BY MODULE and deletes the ones a module stops declaring, so a
   module-CSV `reports.read` row would `IntegrityError` at install and, on uninstall, delete core's
   rows and every grant hanging off them). The main session picked the REUSE alternative instead:
   `require_permission("reports.read"/"reports.export")` directly, no module CSV rows, no manifest
   bump, no grant sweep - every tenant Admin already holds both core keys via
   `tenant_admin_grant`/`sweep_tenant_admin_grants`. Accepted trade-off: uninstalling omnichannel
   can never revoke reports access (the keys are core-owned, not module-owned) - fine today since
   nothing else consumes them, and the next module wanting a reports surface reuses the SAME two
   keys rather than minting its own resource name. S1/S2/S3 all ship this way; see D-A9-10.
2. **The `dataviz` skill is not installed in this environment.** No `~/.claude/skills/dataviz*`
   and nothing chart-related in `docs/reference/frontend-design-language.md`. §3.1 encodes the
   palette / form rules explicitly instead, derived from the house design mandates (brand tokens,
   no raw CSS, no instructional copy, readable at 375). If the skill exists elsewhere, point the
   S0 coder at it and §3.1 is superseded.
3. **Charts use `components/ui/chart.tsx` (recharts), not `apexcharts` (D-A9-15).** Both are in
   `package.json`. Apex appears in exactly one Metronic demo page behind `dynamic ssr:false`;
   `chart.tsx` is the shadcn/ReUI primitive that already maps `ChartConfig` colours onto CSS
   variables, so brand tokens win without a shim. Nothing in the decision set named a library.
4. **A new shared `date-range-picker` primitive.** Nothing in `components/` does a date range
   today; it is assembled from the existing `Popover` + `Calendar` (already `react-day-picker`, so
   `mode="range"` is free) + a preset `SearchSelect`. It lives in `components/platform/` because
   A4 broadcasts will want the same control.
5. **Percentiles and durations are reduced in Python, not SQL (D-A9-9).** `percentile_cont` is
   Postgres-only and timestamp arithmetic is dialect-specific, so a SQL implementation could not
   be pinned by the pytest suite - and the ACs are built on exact numbers. The cost is a bounded
   single-column fetch with a hard 100000-row cap and a fail-fast 422 beyond it; rollups
   (BL-SS-090) are the answer when a tenant outgrows that.
6. **The response-time attribution rule for derived (legacy) datapoints.** D-A9-6 stated the
   derivation but not who owns the datapoint in a per-agent breakdown. This plan attributes it to
   the sender of the derived `AGENT` message. The alternative (exclude derived datapoints from
   per-agent reports and keep them only in the totals) is defensible; not chosen unilaterally.
7. **`groupBy` is limited to `user` and `channel` in v1** (plus `team` after A8). The decision set
   said "group by" generally; a full group-by-anything surface is the custom report builder that
   D-A9-7 puts out of scope.
8. **Reports are per workspace, not per tenant (D-A9-16)**, matching A2 and A3. A tenant with
   several workspaces has no combined view in v1 (BL-SS-096).
9. **The `users` report includes zero-activity workspace members as rows.** respond.io shows an
   empty table when there is no data; a row per member reads better and makes "who did nothing this
   week" answerable. Cheap to reverse.
10. **`totals.derivedFromMessages` is returned but not rendered.** D-A9-6 explicitly ruled out any
    on-screen caveat; the number stays in the API for support and for the Test Execution Report.
11. **No Alembic migration by default (D-A9-14).** If S2's measurement forces the
    `conversation_messages` index, the revision takes the next free number at MERGE time rather
    than a pre-claimed `0013`, because A4 (`0011`) and A8 (`0012`) branch off the same commit and
    two revisions claiming one parent is a silent merge break.
12. **The E2E run must create data before screenshotting.** The dev seed's demo threads only carry
    backfilled `opened` events, so an untouched demo tenant renders flat charts. The run script in
    AC-RPT-53 assumes the tester assigns, replies and closes a couple of threads first; that is a
    change to the usual "click through the finished surface" evidence shape.
