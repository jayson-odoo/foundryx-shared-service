# Plan 30 / S4 - Wire dashboard + reports to the real backend - smoke evidence

**Run date:** 2026-09-06. **Session:** `agent-browser --session s30b`. **Stack:** frontend `:3008`
(this worktree, `npm run build` + `npx next start -p 3008`), backend `:8009` (this worktree, already
running, not restarted). **Tenant/user:** the `default` tenant demo Admin (`demo@example.com` /
`demo1234`) - not a dedicated timestamped tenant, since this is the coder's smoke pass ahead of the
tester's formal `[E2E]` run (AC-RPT-53/54), which will provision its own dedicated tenant/workspace
per the house convention.

## What this proves

The `omnichannel-report-service` barrel is bound to `.real.ts` (S1-S3 backend, live on `:8009`) and
every screen renders REAL data end-to-end - no `S0 MOCK` tags remain in `services/omnichannel-
report-service.{ts,mock.ts,real.ts}` (verified by `grep -rn "S0 MOCK"` returning nothing repo-wide).

## Journey (real clicks from `/`, never a typed URL)

1. Signed in as `demo@example.com`, sidebar -> Omnichannel -> Inbox (`01-inbox-1280.png`).
2. Opened the "Sarah Chen" thread (`02-thread-open-1280.png`), clicked the assignee control ->
   "Assign to me" -> now shows "Demo User" (`03-assigned-1280.png`) - generates an `assigned`
   conversation event.
3. Typed a reply ("Confirmed for 7pm Saturday, see you then!") and pressed Enter
   (`04-reply-sent-1280.png`) - generates an outbound `AGENT` message + (since this thread already
   had a first-agent-reply historically) no new `first_agent_reply` event, but a real message row
   for the Messages report.
4. Clicked Close -> chose reason "General Inquiry" -> Close conversation -> toast "Conversation
   closed." (`05-closed-1280.png`) - generates a `closed` event with `close_reason_id` set.
5. Clicked Reopen -> back to Open (`06-reopened-1280.png`) - generates a `reopened` event (this is
   the one that shows up as `Reopened: 1` on the Conversations report below).
6. Sidebar -> Dashboard, range "Last 7 days" (default preset, `07-dashboard-last7-1280.png`): tiles
   `Open 3 / Assigned 1 / Unassigned 3 / Snoozed 1`, Lifecycle `New Lead 5 / 100%`, opened-vs-closed
   chart bucketed to `31 Aug .. 6 Sept`, scrolled down for first-response/resolution medians + Top
   agents ("Demo User", 1 closed, 4h 13m median) - all real numbers off the demo tenant's inbox
   history plus the activity just generated.
7. Changed the date-range preset to "Last 30 days" -> URL updated to
   `?preset=last30&from=2026-08-08&to=2026-09-06` and the chart re-bucketed to the wider x-axis
   (`08-dashboard-last30-1280.png`) - same tiles/lifecycle (current-state, range-independent per
   AC-RPT-01/02), different series.
8. Sidebar -> Reports, cycled the report `SearchSelect` through all seven keys, screenshotting each:
   - Conversations (`09-...png`) - Opened 5 / Closed 2 / Reopened 1, bucketed chart.
   - Responses (`10-...png`) - median/P90/average/sample-count tile + the 7-bucket "By duration"
     breakdown table.
   - Resolutions (`11-...png`) - median/P90/average/sample-count tile + "By close reason" breakdown,
     including a row with a blank name (a `closed` event with `close_reason_id IS NULL` renders an
     empty label per AC-RPT-21 - proves the null-id-groups-to-blank-label path is live on real data,
     not just the mock).
   - Messages (`12-...png`) - Incoming 10 / Outgoing 7, bucketed two-series chart.
   - Users (`13-...png`) - initially "No data available" because the demo workspace had ZERO
     `WorkspaceMember` rows (Members tab showed "No members yet" - a real, correct empty state, not
     a bug); added "Demo User" as a workspace member via Workspaces -> General -> Members -> Add
     member (toast "Added 1 member(s)."), then the Users report showed one real row (Assigned 1,
     Closed 1, Unique contacts 1, Messages sent 1, medians populated) - an embedded `ResourceList`,
     server-paginated.
   - Leaderboard (`14-...png`) - same row with `Rank #1` (dense rank, per AC-RPT-25).
   - Assignment log (`15-...png`) - the paginated log's first row is the REAL assignment made in
     step 2: `06 Sept 2026, 15:24 | Sarah Chen | Assigned | - | Demo User | Agent | Demo User` -
     `source: "agent"` renders correctly (capitalized "Agent" in the UI cell).
9. Filtered by user (`SearchSelect` -> "Demo User") on the Conversations report
   (`16-...png`) - totals correctly restrict to that actor's events (`Opened 0 / Closed 1 /
   Reopened 1`, since Demo User only closed+reopened Sarah Chen's thread, never opened a new one).
10. Exported the Assignment log report: clicked Export -> network log shows
    `POST .../reports/assignments/export` (201, `{jobId}`) immediately followed by
    `GET .../reports/assignments/export/{jobId}/file` (200) - the eager-inline dev job finished
    inside the hook's poll window, no Jobs-drawer fallback needed. No console errors.
11. Exported the Leaderboard report the same way (network log: `POST .../reports/leaderboard/export`
    201 -> `GET .../reports/leaderboard/export/{jobId}/file` 200).
12. Repeated the sidebar -> Omnichannel -> Dashboard / Reports journey at 375px: opened the mobile
    nav drawer (hamburger icon) and confirmed Dashboard + Reports both appear under the Omnichannel
    section (`17-mobile-menu-omnichannel-375.png`); Dashboard tiles stack one per row
    (`18-dashboard-375.png`); Lifecycle tiles wrap to 2 columns and the opened/closed chart keeps a
    readable axis (`19-dashboard-lifecycle-chart-375.png`); the Reports filter bar collapses to
    full-width stacked rows and the Assignment log table scrolls inside its own container while the
    page itself has NO horizontal scroll (`document.documentElement.scrollWidth === clientWidth ===
    375`, verified both on Reports and Dashboard) (`20-reports-assignments-table-375.png`).

## Mock vs backend differences reconciled

- **Assignment-log `source`.** The mock hardcoded every row's `source` to `'agent'`; the real
  backend derives it from the event (`workflow` when `payload_json.source == "workflow"`, `api` when
  written by the public gateway, else `agent`, per AC-RPT-27). The frontend column
  (`use-assignment-log-config.tsx`) already rendered `row.original.source` generically (`capitalize`
  CSS, no hardcoded mapping) - no FE change needed; the real "Agent" value seen in evidence
  screenshot 15 confirms the live path.
- **Export contract.** The mock's `exportReport` returned CSV text directly (with a size-based
  heuristic to simulate the pending-job case); the real `.real.ts` (already written in S3 handoff)
  POSTs the job, polls `GET /jobs/{id}` up to ~2s, then downloads via `apiFetchBlob` on the authed
  file route - matched byte-for-byte against `service_backend/modules/omnichannel/routers/
  reports.py`'s two export routes. Verified live via the network log in steps 10-11 (job created,
  file streamed, both 200/201).
- **Bucketed vs per-record reports.** `conversations` and ungrouped `messages` return `rows: []`
  with the series carried in `series`/`buckets` (per the backend `ReportResponse` schema and
  AC-RPT-18/23); every renderer already read `report.series`/`report.buckets` for those two report
  keys and `report.rows` for the other five - confirmed rendering correctly against the real
  payload shapes with no frontend change required.
- **Empty-workspace-members edge case.** Not explicitly called out as an AC scenario, but surfaced
  during this smoke pass: `reports/users`/`reports/leaderboard` legitimately return zero rows when
  the workspace has zero `WorkspaceMember` rows (the demo tenant's `General` workspace started with
  none). This is correct backend behaviour (AC-RPT-24's "one row per workspace member" - zero
  members, zero rows), not a bug; resolved for the demo tenant by adding "Demo User" as a member so
  the smoke run could show populated Users/Leaderboard tables. No code change.

## Console / network

`agent-browser console` and `agent-browser errors` showed only a single pre-existing warning
(`Missing Description or aria-describedby for {DialogContent}` on the Inbox close-conversation
dialog, unrelated to plan 30 - a pre-existing Radix a11y nit on a component this slice does not
touch) - no errors, no failed requests, throughout the whole run.

## Not covered by this smoke pass (left to the tester's formal `[E2E]` run)

- AC-RPT-53's dedicated timestamped tenant/workspace and the full "open the downloaded CSV and
  confirm the header row + one known row" step (this pass confirmed the export network round-trip
  succeeds with a 200 file response but did not parse the downloaded blob's bytes).
- AC-RPT-54's cross-tenant 404 probe (a second tenant's token against tenant A's `wsId`) and the
  "role without `reports.read` sees no menu entry" probe - both need a purpose-built second
  tenant/role, which the tester will provision per the dedicated-tenant convention.
