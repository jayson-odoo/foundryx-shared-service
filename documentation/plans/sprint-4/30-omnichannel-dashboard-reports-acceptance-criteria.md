# 30 - Omnichannel Dashboard + Reports v1 - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/30-omnichannel-dashboard-reports.md`.
> **Program:** slice **A9** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gaps G15 + G16).
> **Depends on:** plan 27 / A3 merged (`app_omnichannel.conversation_events`, `close_reasons`,
> `contacts.last_agent_message_at`) and plan 25 / A1 (lifecycle stages) and plan 26 / A2
> (`contact_filters.py` whitelisted column map, the `background_jobs` export pattern). Base =
> `origin/main` `58759ed`.
> **Decisions (main session 2026-09-06):** D-A9-1 no new fact tables, aggregate over
> `conversation_events` + `conversation_messages` + `contacts`; D-A9-2 dashboard content;
> D-A9-3 seven reports on one page; D-A9-4 CSV export via `background_jobs`; D-A9-5 permissions +
> menu; D-A9-6 legacy threads derive first response from messages; D-A9-7 out of scope.
> Planner additions D-A9-8..D-A9-15 live in the plan's Decisions table.
> **Lane:** branch `sprint-4/30-dashboard-reports`, worktree `.claude/worktrees/s30`, backend `:8009`
> on DB `foundryx_service_s30`, frontend `:3008`, `agent-browser --session s30`. Each worktree gets
> its OWN `npm ci`.
> **Out of scope (D-A9-7):** custom report builder, scheduled report emails, team presence /
> online status, broadcast reports (A4 owns its own status page), lifecycle funnel + time-in-stage
> + contacts-added report (Phase D reports v2), calls, materialized rollup tables.

IDs: `AC-RPT-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

---

## Definitions

- **Workspace** - `app_omnichannel.workspaces`. Every dashboard and report route is workspace
  scoped, exactly like the A2 contacts routes (`/omnichannel/workspaces/{wsId}/...`).
- **Event** - one `app_omnichannel.conversation_events` row (plan 27). Types used here: `opened`,
  `closed`, `reopened`, `snoozed`, `unsnoozed`, `assigned`, `unassigned`, `first_agent_reply`,
  `lifecycle_changed`, `comment_added`.
- **Report timezone** - the IANA zone sent as `tz` (the frontend always sends
  `useDatetime().timeZone`). All bucketing, all range boundaries and every rendered date are in
  this zone. The workspace has no timezone of its own in v1.
- **Range** - `from` and `to` are LOCAL calendar dates (`YYYY-MM-DD`), both inclusive. The server
  resolves them to the half-open UTC window `[local_midnight(from), local_midnight(to + 1 day))`
  using `zoneinfo`, so DST transitions inside the range are handled by the zone, not by an offset.
- **Bucket** - one time slot inside the range. `granularity` is `hour` | `day` | `week` | `month`.
  A bucket carries `key` (a LOCAL label token: `2026-03-01T09`, `2026-03-01`, `2026-W10`,
  `2026-03`), `startsAt` and `endsAt` (UTC, Z-suffixed).
- **Response time** - whole seconds from the contact's inbound message to the agent's first
  outbound reply in that open cycle. Primary source = the `first_agent_reply` event's
  `payload_json.responseSeconds` (written live by plan 27). Legacy source (D-A9-6) = for a contact
  with NO `first_agent_reply` event at all, the first `AGENT` `conversation_messages` row minus the
  latest `CONTACT` row strictly before it; contacts with no `AGENT` message contribute nothing.
- **Resolution time** - whole seconds from the cycle-start event (`opened` or `reopened`, whichever
  is the latest at or before the close) to the `closed` event, per `closed` event.
- **Response buckets** - the respond.io parity set, half-open `[lo, hi)` in seconds:
  `< 30s` `[0,30)`, `30s - 2m` `[30,120)`, `2m - 5m` `[120,300)`, `5m - 10m` `[300,600)`,
  `10m - 30m` `[600,1800)`, `30m - 1h` `[1800,3600)`, `> 1h` `[3600, inf)`.
- **Percentile** - linear interpolation on the sorted sample: `i = p * (n - 1)`,
  `value = s[floor(i)] + (s[ceil(i)] - s[floor(i)]) * (i - floor(i))`, rounded half-up to whole
  seconds; `n = 0` yields `null`.
- **Team dimension** - `teamId` filter and `groupBy=team`. NOT available until plan 28 / A8 lands
  (`Contact.assigned_team_id` and the team id in the `assigned` event payload). Every report must
  be None-safe: the dimension is absent from `reports/meta` and rejected as a 422 until A8 exists.

---

## Seeded report fixture (the ONE fixture every numeric AC below asserts against)

The backend fixture (`service_backend/tests/conftest`-local factory
`seed_report_fixture(db, tenant, workspace)`) and the frontend mock service both produce EXACTLY
this data. Report timezone for every numeric AC = `Asia/Kuala_Lumpur` (UTC+08, no DST).
Range for every numeric AC = `from=2026-03-01`, `to=2026-03-07`, i.e. UTC
`[2026-02-28T16:00:00Z, 2026-03-07T16:00:00Z)`.

**Users:** `u_ann` (Ann Lee), `u_ben` (Ben Ooi), `u_cara` (Cara Tan - workspace member, no activity).

**Threads and events (all timestamps UTC; the local day is shown for the boundary cases):**

| Thread | Event | UTC instant | Local day | Detail |
|---|---|---|---|---|
| C1 | opened | 2026-03-01T02:00:00Z | Mar 1 | |
| C1 | first_agent_reply | 2026-03-01T02:00:30Z | Mar 1 | actor `u_ann`, `responseSeconds` 30 |
| C1 | closed | 2026-03-01T03:00:00Z | Mar 1 | actor `u_ann`, reason General Inquiry |
| C2 | opened | 2026-03-01T15:30:00Z | Mar 1 (23:30 local) | |
| C2 | assigned | 2026-03-01T15:40:00Z | Mar 1 | actor `u_ann`, `to_value` `u_ann` |
| C2 | first_agent_reply | 2026-03-01T15:45:00Z | Mar 1 | actor `u_ben`, `responseSeconds` 900 |
| C2 | closed | 2026-03-02T02:00:00Z | Mar 2 | actor `u_ben`, reason Sales Inquiry |
| C3 | opened | 2026-03-01T16:30:00Z | **Mar 2** (00:30 local) | the UTC-day / local-day boundary case |
| C3 | first_agent_reply | 2026-03-01T16:32:00Z | Mar 2 | actor `u_ann`, `responseSeconds` 120 |
| C4 | opened | 2026-03-02T01:00:00Z | Mar 2 | |
| C4 | assigned | 2026-03-02T01:05:00Z | Mar 2 | actor `u_ann`, `to_value` `u_ben` |
| C4 | first_agent_reply | 2026-03-02T01:07:00Z | Mar 2 | actor `u_ben`, `responseSeconds` 420 |
| C4 | closed | 2026-03-02T05:00:00Z | Mar 2 | actor `u_ben`, reason Payment Issue |
| C5 | opened | 2026-03-03T03:00:00Z | Mar 3 | |
| C5 | closed | 2026-03-03T04:00:00Z | Mar 3 | actor `u_ann`, reason Others |
| C5 | reopened | 2026-03-04T03:00:00Z | Mar 4 | |
| C5 | first_agent_reply | 2026-03-04T03:00:20Z | Mar 4 | actor `u_ann`, `responseSeconds` 20 |
| C5 | closed | 2026-03-04T06:00:00Z | Mar 4 | actor `u_ann`, reason General Inquiry |
| C2 | unassigned | 2026-03-04T08:00:00Z | Mar 4 | actor `u_ben`, `from_value` `u_ann` |
| C6 | opened (backfilled) | 2026-03-05T02:00:00Z | Mar 5 | `payload_json.backfilled = true`, NO `first_agent_reply` event ever |
| C6 | comment_added | 2026-03-05T02:05:00Z | Mar 5 | actor `u_ann`, `payload_json.messageId` = the SYSTEM note below |
| C7 | opened | 2026-03-05T16:10:00Z | **Mar 6** (00:10 local) | second boundary case |
| C7 | snoozed | 2026-03-05T17:00:00Z | Mar 6 | |
| C8 | opened | 2026-02-28T02:00:00Z | Feb 28 (OUTSIDE the range) | |
| C8 | closed | 2026-03-06T02:00:00Z | Mar 6 | actor `u_ann`, reason Others |

**Messages** (channel `chn-wa`, `WHATSAPP`):

| Thread | Sender | UTC instant | Local day |
|---|---|---|---|
| C1 | CONTACT | 2026-03-01T02:00:00Z | Mar 1 |
| C1 | AGENT (`u_ann`) | 2026-03-01T02:00:30Z | Mar 1 |
| C2 | CONTACT | 2026-03-01T15:30:00Z | Mar 1 |
| C2 | AGENT (`u_ben`) | 2026-03-01T15:45:00Z | Mar 1 |
| C3 | CONTACT | 2026-03-01T16:30:00Z | Mar 2 |
| C3 | AGENT (`u_ann`) | 2026-03-01T16:32:00Z | Mar 2 |
| C4 | CONTACT | 2026-03-02T01:00:00Z | Mar 2 |
| C4 | AGENT (`u_ben`) | 2026-03-02T01:07:00Z | Mar 2 |
| C5 | CONTACT | 2026-03-04T03:00:00Z | Mar 4 |
| C5 | AGENT (`u_ann`) | 2026-03-04T03:00:20Z | Mar 4 |
| C6 | CONTACT | 2026-03-05T02:00:00Z | Mar 5 |
| C6 | AGENT (`u_ben`) | 2026-03-05T02:03:00Z | Mar 5 |
| C6 | SYSTEM (internal note, `u_ann`) | 2026-03-05T02:05:00Z | Mar 5 |

**Current state (as the fixture leaves it):** C1 CLOSED, C2 CLOSED, C3 OPEN assigned `u_ann`,
C4 CLOSED, C5 CLOSED, C6 OPEN unassigned, C7 SNOOZED unassigned, C8 CLOSED.
**Lifecycle:** C1-C4 New Lead, C5-C6 Hot Lead, C7 Payment, C8 Customer, nothing in Cold Lead.

**Derived expectations (asserted below):** opened per local day
`[Mar1 2, Mar2 2, Mar3 1, Mar4 0, Mar5 1, Mar6 1, Mar7 0]` = 7;
closed per local day `[Mar1 1, Mar2 2, Mar3 1, Mar4 1, Mar5 0, Mar6 1, Mar7 0]` = 6;
reopened total 1. Response sample `[20, 30, 120, 180, 420, 900]` (n = 6, one derived from
messages: C6 at 180s). Resolution sample `[3600, 3600, 10800, 14400, 37800, 518400]` (n = 6).

---

## Slice S1 - Backend: aggregation core + dashboard

- **AC-RPT-01 [BE]** Given `GET /omnichannel/workspaces/{wsId}/dashboard?from=2026-03-01&to=2026-03-07&tz=Asia/Kuala_Lumpur`
  on the fixture, then `tiles` = `{open: 2, assigned: 1, unassigned: 2, snoozed: 1}` where `open`
  counts threads whose CURRENT thread status is OPEN, `snoozed` counts SNOOZED, `assigned` counts
  non-CLOSED threads with an assignee (user or external agent) and `unassigned` counts non-CLOSED
  threads without one. Tiles are CURRENT STATE and ignore `from` / `to` entirely.
- **AC-RPT-02 [BE]** Given the same call, then `lifecycle` lists the workspace's stages in
  `sortOrder` with `{statusId, key, label, color, count, percent}` = New Lead 4 / 50.0, Hot Lead
  2 / 25.0, Payment 1 / 12.5, Customer 1 / 12.5, Cold Lead 0 / 0.0; `percent` is over the
  workspace's total contact count, rounded to one decimal; a stage with no contacts is still
  listed (never dropped).
- **AC-RPT-03 [BE]** Given the same call, then `series.buckets` has 7 day buckets keyed
  `2026-03-01 .. 2026-03-07`, `series.opened` = `[2,2,1,0,1,1,0]` and `series.closed` =
  `[1,2,1,1,0,1,0]`. The C3 `opened` at `2026-03-01T16:30:00Z` lands in the `2026-03-02` bucket
  and the C7 `opened` at `2026-03-05T16:10:00Z` lands in `2026-03-06` (local-day bucketing, not
  UTC-day).
- **AC-RPT-04 [BE]** Given the same call with `tz=UTC` instead, then `series.opened` =
  `[3,1,1,0,2,0,0]` and `series.closed` = `[1,2,1,1,0,1,0]` - the SAME rows bucket differently,
  proving the zone is a real parameter and not a cosmetic label.
- **AC-RPT-05 [BE]** Given the same call, then `responseTotals` =
  `{medianSeconds: 150, p90Seconds: 660, sampleCount: 6, derivedFromMessages: 1}` and
  `resolutionTotals` = `{medianSeconds: 12600, p90Seconds: 278100, sampleCount: 6}`, computed with
  the linear-interpolation percentile defined above.
- **AC-RPT-06 [BE]** Given a contact with NO `first_agent_reply` event (C6), then its response
  datapoint is derived from `conversation_messages` (first `AGENT` row minus the latest `CONTACT`
  row strictly before it) = 180 seconds, a `SYSTEM` internal note is NEVER treated as a reply, and
  a contact that already HAS a `first_agent_reply` event contributes only its event value (no
  double counting).
- **AC-RPT-07 [BE]** Given the same call, then `topAgents` is ordered by `closedCount` desc then
  name asc and equals `[{u_ann, "Ann Lee", closedCount 4, medianResponseSeconds 30},
  {u_ben, "Ben Ooi", closedCount 2, medianResponseSeconds 420}]`; `u_cara` (no activity) is absent;
  every user name resolves TENANT-SCOPED from the actor id (never an unscoped `get_by_id`) and an
  unresolvable id renders an empty name, never another tenant's user.
- **AC-RPT-08 [BE]** Given `granularity` is omitted, then it is auto-selected from the range
  (`<= 2 days` -> `hour`, `<= 62 days` -> `day`, `<= 366 days` -> `week`, else `month`); given an
  explicit `granularity` that would produce more than 120 buckets, then 422 naming the limit;
  given `to` earlier than `from`, or a range wider than 366 days, or a `tz` `zoneinfo` cannot
  resolve, or a `from` / `to` that is not `YYYY-MM-DD`, then 422 `{fieldErrors}` naming the param.
- **AC-RPT-09 [BE]** Given a `userId` filter, then every count, sample and series in the response
  is restricted to events whose `actor_user_id` (or, for `assigned`, whose `to_value`) is that
  user, and the tiles restrict to threads currently assigned to that user; given a `userId` that
  does not belong to the caller's tenant, then 422 (never 403, never data).
- **AC-RPT-10 [BE]** Given every dashboard and report query, then it is tenant-scoped from the JWT
  AND workspace-scoped from the path, in the SQL (never post-filtered in Python); a `wsId` of
  another tenant returns a uniform 404.
- **AC-RPT-11 [BE]** Given time bucketing, then the bucket edges are computed in PYTHON from
  `zoneinfo` and applied as conditional aggregates in ONE SQL pass (no `date_trunc`, no
  `strftime`), so the numbers are byte-identical on the pytest SQLite engine and on production
  Postgres; a golden test compiles the statement on both dialects.
- **AC-RPT-12 [BE]** Given a range that spans a DST transition in a zone that has one (e.g.
  `tz=Europe/London`, `from=2026-03-28`, `to=2026-03-30`, `granularity=day`), then the three day
  buckets are 24h, 23h and 24h wide respectively and every event falls in exactly one bucket
  (no gap, no overlap) - asserted by summing per-bucket counts against the unbucketed total.
- **AC-RPT-13 [BE]** Given a report or dashboard query whose duration sample would exceed
  `REPORT_MAX_SAMPLE_ROWS` (100000), then the request returns 422 with a message naming the row
  count and the cap (the `ExportRowCapExceeded` precedent), never a silent truncation and never an
  unbounded fetch.
- **AC-RPT-14 [BE]** Given a workspace with no events at all, then the dashboard returns the full
  bucket list with zeroes, every lifecycle stage at count 0 / percent 0.0, `medianSeconds` and
  `p90Seconds` `null`, `sampleCount` 0 and `topAgents` `[]` - a 200, never a 404 and never a
  divide-by-zero.
- **AC-RPT-15 [BE]** Given the `teamId` param or `groupBy=team` while plan 28 / A8 has NOT landed,
  then the route returns 422 `{fieldErrors: {teamId | groupBy: ...}}` and
  `GET .../reports/meta` reports `dimensions.team.available = false`; the aggregation service reads
  the team column through ONE `team_column()` seam that returns `None` when the attribute is absent,
  so A8 turns the dimension on without touching any report SQL.
- **AC-RPT-16 [BE]** Given the dashboard response, then every datetime field is Z-suffixed via
  `ApiModel`, every wire key is camelCase, and the response echoes `timezone`, `range.from`,
  `range.to` and `granularity` so the client never has to re-derive them.

## Slice S2 - Backend: the seven reports + assignment log

- **AC-RPT-17 [BE]** Given `GET /omnichannel/workspaces/{wsId}/reports/meta`, then it returns the
  seven report descriptors (`conversations`, `responses`, `resolutions`, `messages`, `users`,
  `leaderboard`, `assignments`) each with `key`, `label`, `supportsGroupBy`, `exportable`, plus
  `granularities` and `dimensions` (`team.available`), gated by the core `reports.read` key
  (amended 2026-09-06 - see AC-RPT-37).
- **AC-RPT-18 [BE]** Given `reports/conversations` on the fixture range, then `series` =
  `[{key: "opened", points: [2,2,1,0,1,1,0]}, {key: "closed", points: [1,2,1,1,0,1,0]},
  {key: "reopened", points: [0,0,0,1,0,0,0]}]` and `totals` = `{opened: 7, closed: 6, reopened: 1}`.
- **AC-RPT-19 [BE]** Given `reports/responses`, then `totals` =
  `{medianSeconds: 150, p90Seconds: 660, averageSeconds: 278, sampleCount: 6, derivedFromMessages: 1}`
  (average rounded half-up) and `rows` is the seven-bucket distribution
  `[{bucket: "lt30s", label: "< 30s", count: 1, percent: 16.7}, {"30s-2m", 1, 16.7},
  {"2m-5m", 2, 33.3}, {"5m-10m", 1, 16.7}, {"10m-30m", 1, 16.7}, {"30m-1h", 0, 0.0},
  {"gt1h", 0, 0.0}]`; `percent` is over `sampleCount`, one decimal.
- **AC-RPT-20 [BE]** Given `reports/responses?groupBy=user`, then `rows` is per agent with
  `{userId, name, sampleCount, medianSeconds, p90Seconds, averageSeconds}`: `u_ann`
  `{sampleCount 3, medianSeconds 30}` (samples 20, 30, 120) and `u_ben`
  `{sampleCount 3, medianSeconds 420}` (samples 180 derived, 420, 900); the derived C6 datapoint is
  attributed to the sender of the derived AGENT message (`u_ben`).
- **AC-RPT-21 [BE]** Given `reports/resolutions`, then `totals` =
  `{medianSeconds: 12600, p90Seconds: 278100, averageSeconds: 98100, sampleCount: 6}` and `rows`
  carries the close-reason breakdown `[{closeReasonId, name, count, percent}]` =
  General Inquiry 2 / 33.3, Sales Inquiry 1 / 16.7, Payment Issue 1 / 16.7, Others 2 / 33.3; a
  `closed` event whose `close_reason_id` is NULL groups under a `null` id with the label rendered
  empty by the client (no invented label server-side).
- **AC-RPT-22 [BE]** Given `reports/resolutions`, then each resolution datapoint pairs a `closed`
  event with the LATEST `opened` or `reopened` event of the same contact at or before it (C5
  contributes two datapoints, 3600 and 10800; C8 contributes 518400 from an `opened` OUTSIDE the
  range), and a `closed` event with no preceding cycle-start event contributes nothing.
- **AC-RPT-23 [BE]** Given `reports/messages`, then `series` = `[{key: "incoming", points:
  [2,2,0,1,1,0,0]}, {key: "outgoing", points: [2,2,0,1,1,0,0]}]`, `totals` =
  `{incoming: 6, outgoing: 6}`, `SYSTEM` internal notes are counted in NEITHER direction, and
  `groupBy=channel` splits the same numbers per `{channelId, name, channelType}` (one row,
  `chn-wa` / WHATSAPP).
- **AC-RPT-24 [BE]** Given `reports/users`, then `rows` is one row per workspace member with
  `{userId, name, teamName, assignedCount, closedCount, uniqueContacts, messagesSent,
  commentsCount, medianFirstResponseSeconds, medianResolutionSeconds}`: `u_ann`
  `{assignedCount 1, closedCount 4, messagesSent 3, commentsCount 1}`, `u_ben`
  `{assignedCount 1, closedCount 2, messagesSent 3, commentsCount 0}`, `u_cara` all zeroes and
  `null` medians; `teamName` is `null` until A8. A member with zero activity is still a row.
- **AC-RPT-25 [BE]** Given `reports/leaderboard`, then `rows` is `reports/users` ordered by
  `closedCount` desc, then `medianFirstResponseSeconds` asc (nulls last), then name asc, each row
  carrying `rank` starting at 1; ties share the SQL ordering but `rank` is dense and stable.
- **AC-RPT-26 [BE]** Given `reports/assignments`, then `series` = the per-bucket count of
  `assigned` events `[1,1,0,0,0,0,0]` with `totals.assigned = 2` and `totals.unassigned = 1`, and
  `rows` is the PAGINATED assignment log (`page`, `pageSize`, `total`) newest-first with
  `{id, createdAt, contactId, contactName, eventType, previousAssigneeId, previousAssigneeName,
  assignedToId, assignedToName, source, actorUserId, actorName}`; on the fixture `total = 3`.
- **AC-RPT-27 [BE]** Given an assignment-log row, then `source` is derived from the event, not
  invented: the WRITER'S OWN `payload_json.source` when it is present and one of
  `workflow` / `agent` / `api` (`ConversationService.patch_thread` stamps it on every
  `assigned`/`unassigned` event it writes; the public gateway passes `api`), falling back to
  INFERENCE only for a legacy row that carries no `source` key at all - `api` when the row has no
  actor of any kind, otherwise `agent` (**amended 2026-09-06 (review round 1)** - the original
  wording only honoured `source == "workflow"` and re-inferred everything else, so a row the
  writer had explicitly stamped `api` was re-derived as `agent` whenever an actor happened to be
  attached); every id is resolved TENANT-SCOPED in ONE batched pass (reuse the
  `event_service._label_map` pattern) and an unresolvable id renders an empty name.
- **AC-RPT-28 [BE]** Given any report route with `page` / `pageSize`, then only `assignments` and
  `users` / `leaderboard` accept them - the four unpaginated reports return a 422 `{fieldErrors}`
  naming the offending param rather than silently ignoring it (**amended 2026-09-06 (review round
  1)** - "only X accept them" is now enforced literally; a caller that sends neither param is
  unaffected) - `pageSize` is capped at 200, and every ordering ends with a deterministic tiebreak
  (`created_at DESC, id DESC` for the log; `userId ASC` for the tables) so page 0 and page 1 never
  repeat or drop a row - pinned by a two-page test for the log AND for `users` / `leaderboard`
  (which build their whole row set in Python, so their slicing needs its own proof).
- **AC-RPT-29 [BE]** Given an unknown `reportKey`, then 404 uniform; given an unknown `groupBy` for
  a report that does not declare it, then 422 naming the accepted values (the whitelist is the same
  list `reports/meta` publishes - one source, never forked).
- **AC-RPT-30 [BE]** Given a `channelId` filter, then it is validated against the workspace's own
  channels for EVERY report (a channel of another workspace or tenant is a 422 regardless of
  report key), but only APPLIED in SQL for the `messages` report - the one report shape that
  carries a channel dimension (`conversation_messages.channel_id`); `conversation_events` has no
  channel column, so `channelId` is accepted-and-a-no-op for every other report rather than
  misrepresenting history through the contact's CURRENT channel identity (amended 2026-09-06 - the
  S2 coder flagged the original wording, "applied... to the message and event queries alike", as
  inaccurate against the shipped `CHANNEL_FILTERED_REPORTS = {"messages"}` rule in
  `report_service.py`; this is the corrected, shipped behaviour, not a new decision).
- **AC-RPT-31 [BE]** Given every report route, then it requires the core `reports.read` key
  (amended 2026-09-06 - see AC-RPT-37), is tenant-scoped from the JWT and workspace-scoped from
  the path, and a caller from tenant B asking for tenant A's `wsId` gets a uniform 404 for every
  one of the seven reports plus `meta` plus the dashboard.
- **AC-RPT-32 [BE]** Given the report services, then they REUSE `contact_filters.py`'s whitelisted
  column map and `lifecycle_service.stages_for_workspace` rather than forking a second map, and no
  report builds SQL from a client string (all identifiers come from server-side constants).

## Slice S3 - Backend: export + permissions

- **AC-RPT-33 [BE]** Given `POST /omnichannel/workspaces/{wsId}/reports/{reportKey}/export` with
  the same filter body the read route accepts, then a `background_jobs` row of type
  `omnichannel.report_export` is created and `{jobId}` returned; the handler is registered through
  `app/jobs/registry.register_job_handler` (one code path, eager-inline in dev and tests, Celery in
  prod) and re-reads its own job status at every batch checkpoint so an abort is honoured.
- **AC-RPT-34 [BE]** Given a finished export job, then `result_json` = `{fileKey, rowCount,
  columns}` and `GET .../reports/{reportKey}/export/{jobId}/file` streams `text/csv` with
  `Content-Disposition: attachment`, `Content-Security-Policy: default-src 'none'; sandbox`,
  `X-Content-Type-Options: nosniff` and `Cache-Control: private, max-age=0, no-store`, requiring
  the caller's bearer + the core `reports.export` key (amended 2026-09-06 - see AC-RPT-37); a job
  of another tenant, another workspace, another report key, another job type, or one not yet DONE
  returns a uniform 404 (the A2 `download_contacts_export` precedent, copied not re-invented).
- **AC-RPT-35 [BE]** Given the CSV, then every cell goes through `app.import_engine.sanitize
  sanitize_cell` (spreadsheet-formula injection: contact names originate from inbound WhatsApp
  profile names) INCLUDING every header cell, the header row carries human labels sourced from the
  same series labels / column maps the read route already returns (never a second hardcoded list),
  and every timestamp column (bucket `startsAt`/`endsAt`, the assignment log's `createdAt`) is
  rendered in the requested `tz` with the offset appended (`YYYY-MM-DD HH:MM:SS +08:00`) so a
  spreadsheet reader is not silently in UTC; the two report shapes with no per-record `rows`
  (`conversations`, and `messages` when not grouped by channel) export one row per bucket instead,
  reusing the SAME `buckets`/`series` the chart renders - never a second query path.
- **AC-RPT-36 [BE]** Given an export whose row count would exceed 50000, then the POST fails FAST
  with 422 naming the count and the cap, before any job row is created; the count comes from the
  SAME report builder the read route calls (a paginated report's `total`, an unpaginated report's
  row count), never a second query.
- **AC-RPT-37 [BE]** **Amended 2026-09-06 (main session, final - supersedes the original text
  below).** Given permissions, then BOTH export routes are gated by the CORE `reports.export` key
  and the read routes (dashboard, `meta`, all seven reports) stay gated by the core `reports.read`
  key from S1/S2 - the module declares NO `conversation_reports.*` permission rows, no manifest
  version bump, and no `update_tenant` grant-sweep guard. *Original text (superseded, kept for
  history): "the module CSV adds `conversation_reports.read` and `conversation_reports.export`...
  the module MUST NOT declare `reports.read`/`reports.export` because core already owns those
  globally-unique keys and `PermissionRepository.sync` is delete-by-module on a unique key -
  declaring them would raise on insert and, worse, delete core's rows and their grants on
  uninstall." The collision risk described is real and is exactly why the FINAL decision reuses
  the core keys directly rather than minting a colliding or parallel pair - see plan D-A9-10.*
- **AC-RPT-38 [BE]** **Amended 2026-09-06 (supersedes the original manifest-bump text).** Given the
  reused-core-key decision, then the manifest stays at `0.4.0` (the `reports` router was already
  added at that version in S1), there is no new `update_tenant` guard branch, and no grant-sweep
  migration is needed - `sweep_tenant_admin_grants`/`tenant_admin_grant` already grant every core
  key (including the two previously-dormant `reports.*` rows) to every tenant's Admin role. Proven
  by a live `GET /auth/me` check for the demo tenant Admin showing both `reports.read` and
  `reports.export` in `permissions[]`, plus a pytest asserting the same for a freshly-provisioned
  tenant.
- **AC-RPT-39 [BE]** Given a user holding `conversations.read` but NOT the core `reports.read` key,
  then every dashboard, report, meta and export route returns 403 (not 404, not data); given
  `reports.read` but not `reports.export`, then the read routes work and both export routes return
  403 (amended 2026-09-06 - key names updated per AC-RPT-37; the crafted-role mechanism is
  unchanged).
- **AC-RPT-40 [BE]** **Amended 2026-09-06 (supersedes the original text below).** Given a tenant is
  uninstalled from the omnichannel module, then NO permission row is touched at all - the module
  declares no `reports.*`/`conversation_reports.*` rows of its own, so `PermissionRepository.sync`
  has nothing module-owned to delete-by-module here; the core `reports.read`/`reports.export` rows
  and every tenant's grants on them persist untouched (proven by a pytest that installs, uninstalls,
  and re-checks the core permission catalog is unchanged). *Original text (superseded): "then its
  `conversation_reports.*` permission rows and their role grants are removed with the module and no
  core permission row is touched" - moot once no module-owned rows exist to remove.*

## Slice S0 / S4 - Frontend

- **AC-RPT-41 [FE]** Given the omnichannel module is active and the user holds the core
  `reports.read` key (amended 2026-09-06 - see AC-RPT-37), then a **Dashboard** entry (before
  Inbox) and a **Reports** entry (after Contacts) exist in the omnichannel block of ALL THREE menu
  arrays (`MENU_SIDEBAR`, `MENU_MEGA`, `MENU_MEGA_MOBILE`), each tagged `module: 'omnichannel'` +
  `permission: 'reports.read'`; a tenant without the module or a user without the key sees
  neither, in every menu surface.
- **AC-RPT-42 [FE]** Given `/omnichannel/dashboard`, then it resolves the workspace exactly like
  Contacts (`useActiveWorkspace`, default first, a header `SearchSelect` only when the tenant has
  more than one workspace), shows the four state tiles, the lifecycle stage tiles, the opened vs
  closed chart, the response and resolution medians, and the top-agents list; the effective
  timezone is shown as a plain value in the header (a label, not instructional copy).
- **AC-RPT-43 [FE]** Given the shared filter bar (dashboard and reports), then it offers a date
  range control (presets Last 7 days / Last 30 days / This month / Last month / Custom, custom via
  the existing `Calendar` in range mode inside a `Popover`), a user `SearchSelect` over workspace
  members, a channel `SearchSelect`, and a granularity `SearchSelect`; the team control is ABSENT
  while `reports/meta` reports `dimensions.team.available = false`; every dropdown is a
  `SearchSelect` (no bare shadcn `Select`); state is synced to the URL so a reload restores it -
  including the current report's group-by (**amended 2026-09-06 (review round 1)**: the group-by
  was renderer-local state, so it survived neither a reload nor the Export request).
- **AC-RPT-44 [FE]** Given `/omnichannel/reports`, then the report is chosen with a `SearchSelect`
  over the seven `reports/meta` descriptors (default `conversations`), the filter bar is the same
  component as the dashboard's, and switching report keeps the range, user, channel and
  granularity - while a group-by the newly selected report does not declare in `supportsGroupBy`
  is dropped, so a carried-over dimension can never 422 (**amended 2026-09-06 (review round 1)**,
  a consequence of AC-RPT-43's group-by now being shared filter state). `reports/meta` is the ONLY
  source of the descriptor list; if it fails to load the page shows an error state rather than
  falling back to a hardcoded list that could drift from the server's.
- **AC-RPT-45 [FE]** Given any chart, then it is rendered through the EXISTING
  `components/ui/chart.tsx` recharts wrapper (`ChartContainer` + `ChartTooltip` +
  `ChartTooltipContent` + `ChartLegend`) with a `ChartConfig` whose colours are Foundryx brand CSS
  variables; no `apexcharts`, no new chart dependency, no `<style>` tag and no raw CSS; a series
  is identified by its legend AND its tooltip (never colour alone), and the empty state is a short
  status line, never instructional copy.
- **AC-RPT-46 [FE]** Given the assignment log and the users / leaderboard tables, then they are
  embedded `ResourceList` configs (the `workspace-contact-fields-tab.tsx` precedent), never
  hand-rolled tables, with server-side pagination and the shell's Columns control.
- **AC-RPT-47 [FE]** Given Export on a report, then it calls the `background_jobs` export, polls
  `GET /jobs/{id}` briefly and downloads through the authed file route via `apiFetchBlob`, falling
  back to the Jobs drawer when the wait window elapses - the exact A2 contacts-export controller,
  reused not re-implemented, and the request carries the SAME filters the on-screen report was
  built from, group-by included (**amended 2026-09-06 (review round 1)**); the control is hidden
  without the core `reports.export` key (`useCan`, UX only - the API is the gate; corrected here
  from the pre-D-A9-10 `conversation_reports.export` the rest of this file already dropped).
- **AC-RPT-48 [FE]** Given every duration rendered on screen, then it is formatted from whole
  seconds by ONE shared helper (`formatDuration`) as `1m 30s` / `3h 30m` / `6d 0h`, and every
  timestamp goes through `useDatetime()`; nothing renders a raw UTC string and nothing re-converts
  a bucket `key` (which is already local).
- **AC-RPT-49 [FE]** Given `~375px`, then the dashboard tiles stack one per row, the lifecycle
  tiles wrap, every chart keeps a readable axis (fewer tick labels, no overlapping text, no
  horizontal page scroll), the filter bar collapses its controls onto full-width rows, and the
  report tables scroll inside their own container; given `~1280px`, then tiles sit four across and
  charts fill the card. Both widths are verified on every surface, not sampled.
- **AC-RPT-50 [FE]** Given a user without the core `reports.read` key (amended 2026-09-06 - see
  AC-RPT-37) who navigates directly to `/omnichannel/dashboard` or `/omnichannel/reports`, then the
  page renders the standard `RequirePermission` denial, not a broken shell and not a partial render
  of another tenant's data.

## Slice S4 - Tests + evidence

- **AC-RPT-51 [T]** pytest covers: the seeded fixture and every numeric expectation above
  (tiles, lifecycle, opened / closed series in two zones, DST-spanning buckets, percentiles,
  response buckets, derived legacy response, resolution pairing incl. the out-of-range `opened`,
  messages by direction and channel, users / leaderboard rows incl. the zero-activity member,
  assignment log pagination across two pages), granularity auto-selection and the 120-bucket and
  100000-sample caps, filter validation (`tz`, `from` / `to`, `userId`, `channelId`, `groupBy`,
  `teamId` unavailable), permission gates (403 for each key), tenant isolation (uniform 404) on
  every one of the ten routes, the export job happy path + cap + abort + authed file route + CSV
  sanitization, and the golden two-dialect compile of the bucketing statement.
- **AC-RPT-52 [T]** vitest covers: the filter-bar URL sync and preset resolution, the report
  `SearchSelect` switching without losing filters, `formatDuration` (seconds, minutes, hours,
  days, zero, null), the chart adapter mapping `{buckets, series}` onto `ChartConfig` + recharts
  data, the empty-state render, the export controller (poll then Jobs fallback), and permission
  gating of the export control.
- **AC-RPT-53 [E2E]** Recorded agent-browser run (dedicated timestamped tenant + workspace, real
  clicks from `/`, never URL navigation, screenshots at 375 AND 1280 into
  `documentation/plans/sprint-4/30-evidence/<slice>/` with a README run log): sidebar ->
  Omnichannel -> Dashboard (tiles + lifecycle + chart render with the demo tenant's data) -> change
  the range preset to Last 30 days and see the chart re-bucket -> sidebar -> Reports -> switch the
  report `SearchSelect` through Conversations, Responses, Resolutions, Messages, Users,
  Leaderboard, Assignments -> filter by a user -> Export the Assignments report -> download the CSV
  -> open it and confirm the header row and one known row. Repeat the whole journey at 375px.
- **AC-RPT-54 [E2E]** Same run: a second tenant's token against tenant A's `wsId` returns 404 for
  the dashboard, `meta`, all seven reports and the export file route (API probe recorded in the run
  log); a user whose role lacks the core `reports.read` key (amended 2026-09-06 - see AC-RPT-37)
  sees no Dashboard / Reports menu entry in the sidebar, the desktop mega menu or the mobile mega
  menu.
- **AC-RPT-55 [T]** The Test Execution Report
  (`documentation/plans/sprint-4/30-omnichannel-dashboard-reports-test-report.md`, the
  `AI_Agent_Orchestration_Guide.md` §6 format) is keyed to these ids with PASS / FAIL / DEFERRED
  and cites the evidence run per `[E2E]` id; deferrals are registered in
  `documentation/backlogs/backlog.md` from `BL-SS-090` with a link back to the plan.
