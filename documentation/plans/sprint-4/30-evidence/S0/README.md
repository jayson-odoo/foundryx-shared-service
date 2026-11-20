# Plan 30 - S0 (frontend-mock) evidence run

Session: `agent-browser --session s30`. Backend `:8009` (real auth only, no S1-S3
report routes yet - the FE runs entirely against `omnichannel-report-service.mock.ts`).
Frontend `:3008`, prod build (`rm -rf .next && npm run build && npx next start -p 3008`).
Login: `demo@example.com` / `demo1234` at `http://localhost:3008` (default tenant,
already holds `reports.read` + `reports.export` - verified via `/auth/login`).

## Run log (real clicks from `/`, unless noted)

1. Sign in -> sidebar -> expand **Omnichannel** -> click **Dashboard**
   (`01-dashboard-1280.png`). Confirms the menu order (Dashboard before Inbox,
   Reports after Contacts) and the default `Last 7 days` range resolved
   against the ACTUAL current date (Aug 31 - Sep 6, 2026) - tiles/lifecycle
   are date-independent and show real numbers (`open:2 assigned:1
   unassigned:2 snoozed:1`, lifecycle `New Lead 4/50%, Hot Lead 2/25%, Payment
   1/12.5%, Customer 1/12.5%, Cold Lead 0/0%` - exact AC-RPT-01/02 match); the
   date-scoped cards (chart, response/resolution stats, top agents) correctly
   show the "No data in this range." empty state because the S0 mock's fixed
   fixture events all live in March 2026 - expected, not a bug (see
   `omnichannel-report-service.mock.ts`'s header comment).
2. Clicked the date-range trigger, paged the calendar back to March 2026 and
   picked 1 Mar - 7 Mar (the UAC fixture's canonical range).
   `02-dashboard-fixture-range-1280.png` now shows every card populated -
   opened/closed chart, `First response time` (median 2m30s / p90 11m0s /
   avg 4m38s / 6 samples), `Resolution time` (median 3h30m / p90 3d5h / avg
   1d3h / 6 samples), `Top agents` (Ann Lee 4 closed / 30s median, Ben Ooi 2
   closed / 7m0s median) - byte-for-byte the AC-RPT-05/06/07 numbers.
   - **Bug found + fixed live**: the FIRST click on a day before an already-
     complete range closed the popover immediately (react-day-picker's
     range-merge handed back a "complete-looking" range on click one). Fixed
     `date-range-picker.tsx` with an explicit two-click anchor (own state,
     not react-day-picker's range-merge) + a `defaultMonth` so the calendar
     opens on the CURRENT value's month instead of always today's. Pinned by
     two new vitest cases in `date-range-picker.test.tsx` before re-verifying
     (`03-dashboard-custom-range-1280.png` shows the corrected two-click flow
     landing on `31 Aug - 5 Sept` without a premature close).
3. Switched the preset `SearchSelect` to **Last 30 days** -
   `04-dashboard-last30-1280.png` - range updates to `8 Aug - 6 Sept`,
   confirming a preset change re-fetches (AC-RPT-53's "chart re-buckets"
   step).
4. Sidebar -> **Reports**. Report `SearchSelect` defaults to **Conversations**
   (`05-reports-conversations-1280.png`, current date range - empty chart,
   correct). Switched to the fixture range (1 Mar - 7 Mar) -
   `06-reports-conversations-fixture-1280.png` matches AC-RPT-18 exactly
   (opened 7 / closed 6 / reopened 1, day buckets `1 Mar`..`7 Mar`).
5. Cycled the report picker through all seven reports, same fixture range:
   - `07-reports-responses-1280.png` - AC-RPT-19 exact (median 2m30s, p90
     11m0s, avg 4m38s, 6 samples; 7-bucket distribution table via `DataGrid`).
   - `08-reports-resolutions-1280.png` - AC-RPT-21 exact (median 3h30m, p90
     3d5h, avg 1d3h; close-reason breakdown General 2/33.3%, Sales 1/16.7%,
     Payment 1/16.7%, Others 2/33.3%).
   - `09-reports-messages-1280.png` - AC-RPT-23 exact (incoming 6 / outgoing
     6, day chart).
   - `10-reports-users-1280.png` - AC-RPT-24 exact, rendered as an embedded
     `ResourceList` (search box, Columns control, sortable/reorderable
     column headers, pagination footer) - Ann Lee/Ben Ooi/Cara Tan
     (zero-activity member still a row) all match.
   - `11-reports-leaderboard-1280.png` - AC-RPT-25 exact (#1 Ann Lee, #2 Ben
     Ooi, #3 Cara Tan).
   - `12-reports-assignments-1280.png` - AC-RPT-26/27 exact (assigned 2 /
     unassigned 1, 3-row newest-first log as an embedded `ResourceList`).
6. On the Assignment log report, clicked **Export** - the mock resolves a
   small CSV instantly (assignment log has 3 rows, under the mock's
   pending-simulation threshold) - a silent successful browser download, no
   error. Switched to **Responses** (fixed 7-row distribution, always over
   the threshold with no filters) and clicked **Export** again -
   `13-reports-export-pending-toast-1280.png` shows the "The export is still
   running - it will finish in Jobs." toast with a **View Jobs** action,
   confirming AC-RPT-47's fallback path fires through the real toast system
   (not just unit-mocked).
7. Repeated the responsive pass at **375px** (dashboard default state
   `14-dashboard-375.png`, dashboard on the fixture range with a populated
   chart `15-dashboard-fixture-375.png`, reports/conversations
   `16-reports-conversations-375.png`, reports/assignments with its
   `DataGrid` `17-reports-assignments-375.png`) - every tile stacks one per
   row, the lifecycle tiles wrap into a 2-up grid, filter bar controls go
   full-width, chart axes stay readable with all 7 day labels, and the
   assignment log's `DataGrid` scrolls its own columns without pushing the
   page wider than the viewport. No horizontal page scroll on any screen.
8. Verified menu parity across all three surfaces: sidebar (`01-...png`),
   the **mobile mega menu** (`Open apps menu` at 375px, expanded Omnichannel
   section shown in `18-mobile-mega-menu-375.png`, clicked **Reports** and
   landed on `/omnichannel/reports`), and the **desktop mega menu** (`Apps`
   dropdown at 1280px, `19-desktop-mega-menu-1280.png`, clicked **Reports**
   and landed on the same route). Dashboard sits before Inbox, Reports sits
   after Contacts in all three.
9. `agent-browser console` showed zero errors for the whole run (one
   pre-existing unrelated a11y warning about a `DialogContent` description,
   not from any plan-30 surface).

## Deferred to S4 (real backend, out of S0 scope)

- AC-RPT-54 (cross-tenant 404 + menu-hiding for a user lacking
  `reports.read`) needs the real backend routes; S0 covers the
  `RequirePermission` denial and Export-button gating via vitest
  (`app/(protected)/omnichannel/reports/page.test.tsx`) instead of a live
  second-tenant/second-role probe.
- Filtering by a specific user/channel wasn't exercised live: the User/
  Channel `SearchSelect` options come from the REAL workspace-members/
  channel-list services (already-merged A1/A2 features), which only know
  about the demo tenant's actual members (`demo@example.com`) - the S0 mock's
  fixture users ("Ann Lee"/"Ben Ooi"/"Cara Tan") are fictional report data,
  not real workspace members, so a live user-filter click can't be
  demonstrated meaningfully until S4 wires a matching seeded fixture on the
  real backend.
