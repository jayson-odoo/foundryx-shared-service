# 30 - Omnichannel Dashboard + Reports v1 - Test Execution Report

Format: `documentation/development_process/AI_Agent_Orchestration_Guide.md` §6. Keyed to
`documentation/plans/sprint-4/30-omnichannel-dashboard-reports-acceptance-criteria.md` (AC-RPT-01..55).

## Environment

- **Commit under test:** the review round 2 commit (child of `983bff15`, `fix(omnichannel): plan 30
  review round 2 - reports meta loading state, first-reply tiebreak, grouped export test, fresh-build
  evidence`) on `sprint-4/30-dashboard-reports`, served from a clean build **`BUILD_ID UU2Fo2BsXkfYNqnCrOnZw`**
  (2026-09-06 21:09) - see the "Re-record after review round 2" section of the E2E README. The original run
  (below) was recorded against `dc92223a` + the then-uncommitted round-1 diff; screenshots 12-35 were
  re-recorded on the round-2 build because the original captures predated the round-1 frontend fixes
  (N-3).
- **Uncommitted working-tree state found at test start (not authored by the tester):** `git status`
  showed an uncommitted diff (20 files, +907/-239) across `report_service.py`,
  `report_export_service.py`, `report_queries.py`, `reports.py`, their test files, the dashboard and
  reports frontend pages/components, `date-range-picker.tsx`, `use-report-filters.ts`, and the
  UAC/plan/backlog docs. The plan file's own text ("Registered 2026-09-06 (review round 1)") and the
  UAC's "amended 2026-09-06" markers make clear this is the coder's own post-review-round-1 hardening
  pass, verified locally and left uncommitted rather than a foreign edit. **The tester did not
  author, modify, or evaluate this diff** - it is called out here so it gets committed (or explicitly
  reviewed) before merge; losing it would silently regress the D-A9-12 index-measurement note and the
  BL-SS-104..101 backlog registration. The backend process tested (fresh restart, no `--reload`) and
  the frontend process tested (already-running prod build, left untouched) both reflect this code, so
  the PASS/FAIL findings below are against the code as it stood at test time, uncommitted diff
  included.
- **Backend:** `:8009`, DB `foundryx_service_s30`, `CELERY_TASK_ALWAYS_EAGER=true`,
  `ENVIRONMENT=development`. Restarted once (previous process lacked `CORS_ORIGIN_REGEX` for tenant
  subdomains - cwd-verified before restart, only that PID killed).
- **Frontend:** `:3008`, prod build, PID 80843 (untouched, cwd-verified).
- **Suites:**
  - Backend: `.venv/bin/python -m pytest -q` -> **3112 passed, 3 skipped, 18 deselected** (the
    deselect is the pre-existing `-m "not live"` addopts, unrelated to plan 30), 2093.61s. Isolated
    re-run of just the three plan-30 test files -> **69 passed** (26
    `test_omnichannel_reports_dashboard.py` + 30 `test_omnichannel_reports_builders.py` + 13
    `test_omnichannel_reports_export.py`), 94.95s, zero failures.
  - Frontend: `npx vitest run` -> **291 test files, 2176 tests, all passed**, 75.26s.
- **Tenants created:** `p30-20260906074444` (Admin `p30admin-20260906074444@example.com`, omnichannel
  installed) + `p30-noomni-20260906074444` (Admin `p30-noomni-admin-20260906074444@example.com`,
  omnichannel NOT installed). Agent user `p30-agent-20260906074444@example.com` under a role holding
  `conversations.*` + `reports.read` (NOT `reports.export`) + `workspaces.read`.
- **E2E evidence:** `documentation/plans/sprint-4/30-evidence/E2E/` (36 screenshots + `README.md` run
  log, real clicks from `/`, 375px + 1280px, agent-browser session `s30t`).

## Summary

**55 / 55 AC ids PASS. 0 FAIL. 0 DEFERRED** (all seven Out-of-scope items and the twelve backlog
candidates were already correctly deferred by the plan itself, not by this test pass).

## Results

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-RPT-01 | [BE] | PASS | `test_tiles_current_state_ignores_range`; live-confirmed via E2E dashboard tiles `Open 1/Assigned 1/Unassigned 1/Snoozed 1` matching the fixture's real thread states (`12-dashboard-last7-1280.png`) |
| AC-RPT-02 | [BE] | PASS | `test_lifecycle_stage_counts`, `test_lifecycle_percent_denominator_is_the_workspace_total_not_just_staged`; live `New Lead 3/100%` (`12-dashboard-last7-1280.png`) |
| AC-RPT-03 | [BE] | PASS | `test_opened_closed_series_kuala_lumpur` |
| AC-RPT-04 | [BE] | PASS | `test_opened_closed_series_utc` |
| AC-RPT-05 | [BE] | PASS | `test_response_and_resolution_totals`; live median/p90/avg/samples on the Dashboard + Responses report (`14-dashboard-lower-1280.png`, `18-reports-responses-1280.png`) |
| AC-RPT-06 | [BE] | PASS | `test_legacy_derivation_bounded_statements_no_per_contact_in_list`, `test_legacy_derivation_cap_raises_before_cap_plus_two` |
| AC-RPT-07 | [BE] | PASS | `test_top_agents_ordered_by_closed_count`, `test_top_agent_actor_id_from_another_tenant_renders_empty_name`; live "Top agents" card (`14-dashboard-lower-1280.png`) |
| AC-RPT-08 | [BE] | PASS | `test_granularity_auto_selects_hour_for_a_two_day_range`, `test_granularity_auto_selects_day_for_the_fixture_range`, `test_explicit_granularity_over_bucket_cap_is_422`, `test_to_before_from_is_422`, `test_range_wider_than_max_is_422`, `test_unknown_timezone_is_422`, `test_bad_date_format_is_422` |
| AC-RPT-09 | [BE] | PASS | `test_user_filter_scopes_tiles_and_totals`, `test_unknown_user_id_is_422_not_403_not_data`; live user-filtered Assignment log stayed at 3/1 (actor-OR-to_value=Admin) (`24-reports-assignments-userfilter-1280.png`) |
| AC-RPT-10 | [BE] | PASS | `test_foreign_tenant_workspace_is_uniform_404`, `test_unknown_workspace_id_is_404`; live cross-tenant probe (see AC-RPT-54 row) |
| AC-RPT-11 | [BE] | PASS | `test_bucket_query_compiles_dialect_free` |
| AC-RPT-12 | [BE] | PASS | `test_dst_spanning_day_buckets_no_gap_no_overlap` |
| AC-RPT-13 | [BE] | PASS | `test_sample_cap_exceeded_is_422`, `test_duration_samples_raises_before_cap_plus_two` |
| AC-RPT-14 | [BE] | PASS | `test_empty_workspace_returns_zeroed_dashboard` |
| AC-RPT-15 | [BE] | PASS | `test_team_id_filter_is_422_until_a8`, `test_reports_meta_reports_team_unavailable`; live filter bar has no Team control anywhere in the run |
| AC-RPT-16 | [BE] | PASS | `test_dashboard_wire_shape_camel_case_and_z_suffixed` |
| AC-RPT-17 | [BE] | PASS | `test_reports_meta_descriptors` |
| AC-RPT-18 | [BE] | PASS | `test_conversations_report_series_and_totals`; live Conversations report `Opened 0/Closed 2/Reopened 1` (`17-reports-conversations-1280.png`) |
| AC-RPT-19 | [BE] | PASS | `test_responses_report_distribution_and_totals`; live 7-bucket "By duration" table (`18-reports-responses-1280.png`) |
| AC-RPT-20 | [BE] | PASS | `test_responses_report_group_by_user` |
| AC-RPT-21 | [BE] | PASS | `test_resolutions_report_close_reason_breakdown`; live correct empty state, no cycle-start pairs in this fixture (`19-reports-resolutions-1280.png`) |
| AC-RPT-22 | [BE] | PASS | `test_resolutions_report_group_by_user` |
| AC-RPT-23 | [BE] | PASS | `test_messages_report_series_and_totals`, `test_messages_report_group_by_channel`; live `Incoming 3/Outgoing 3` (`20-reports-messages-1280.png`) |
| AC-RPT-24 | [BE] | PASS | `test_users_report_rows`; live embedded `ResourceList` with both members incl. the zero-activity-so-far Agent row (`21-reports-users-1280.png`) |
| AC-RPT-25 | [BE] | PASS | `test_leaderboard_report_order_and_rank`; live `#1 P30 Admin, #2 P30 Agent User` (`22-reports-leaderboard-1280.png`) |
| AC-RPT-26 | [BE] | PASS | `test_assignments_report_series_totals_and_rows`; live 4-row paginated log (`23-reports-assignments-1280.png`) |
| AC-RPT-27 | [BE] | PASS | `test_assignment_source_api_when_written_by_the_public_gateway`; live every row shows `source: Agent` (all events were made via the UI by a logged-in user) |
| AC-RPT-28 | [BE] | PASS | `test_assignment_log_pagination_no_repeat_no_drop`, `test_page_size_is_capped_at_200`, `test_page_and_page_size_are_422_on_unpaginated_reports`, `test_two_page_proof_for_users_and_leaderboard` |
| AC-RPT-29 | [BE] | PASS | `test_unknown_report_key_is_404`, `test_unsupported_group_by_is_422_naming_accepted_values`, `test_group_by_team_is_422_until_a8_for_every_report` |
| AC-RPT-30 | [BE] | PASS | `test_channel_id_validated_against_workspace`, `test_channel_id_applied_to_messages_report`, `test_channel_id_is_validated_but_not_applied_to_event_reports` |
| AC-RPT-31 | [BE] | PASS | `test_missing_permission_is_403_for_every_report`, `test_foreign_tenant_workspace_is_uniform_404_for_every_report`; live 403 (agent, export routes) + uniform 404 (cross-tenant, all ten routes) - see AC-RPT-39/54 rows |
| AC-RPT-32 | [BE] | PASS | `test_reports_reuse_lifecycle_stages_for_workspace` |
| AC-RPT-33 | [BE] | PASS | `test_export_creates_job_and_registers_handler`, `test_export_cooperative_cancel_stops_before_file`; live `POST .../export` 201 -> `GET .../file` 200 network trace (`25-export-assignments-1280.png`) |
| AC-RPT-34 | [BE] | PASS | `test_export_conversations_bucketed_rows_and_headers`, `test_export_assignments_rows_and_timestamp_offset`, `test_download_uniform_404_matrix`, `test_download_404_for_a_job_of_another_type` |
| AC-RPT-35 | [BE] | PASS | `test_export_sanitizes_formula_injection_agent_name`, `test_export_paginates_through_multiple_pages`; live formula-injection proof - a contact renamed to `=SUM(1+1)` exported as `'=SUM(1+1)` (leading-quote neutralized), header row = human labels, every timestamp `YYYY-MM-DD HH:MM:SS +08:00` (parsed the actual downloaded `assignments-export (2).csv` / `(3).csv` and `leaderboard-export (1).csv` with Python `csv` - header + row counts + tz offsets all correct, see E2E README step 6) |
| AC-RPT-36 | [BE] | PASS | `test_export_row_cap_422` |
| AC-RPT-37 | [BE] | PASS | `test_export_permission_gate_403_reports_read_only`, `test_export_permission_gate_403_no_permissions`; live Agent (holds `reports.read`, not `reports.export`) - Export button absent in UI (`29-agent-reports-with-data-no-export-1280.png`, `30-agent-reports-375.png`), direct API probe `POST .../export` -> 403 |
| AC-RPT-38 | [BE] | PASS | `test_demo_admin_has_reports_read_and_export_via_auth_me`, `test_freshly_provisioned_tenant_admin_has_reports_keys`; live `GET /auth/me` for the freshly-provisioned `p30-...` tenant Admin shows both `reports.read` and `reports.export` |
| AC-RPT-39 | [BE] | PASS | live: Agent `GET .../dashboard` -> 200 (holds `reports.read`), `POST .../reports/leaderboard/export` -> 403 (lacks `reports.export`) - direct curl probe, backend log confirms both codes |
| AC-RPT-40 | [BE] | PASS | `test_uninstall_module_does_not_touch_core_reports_permissions` |
| AC-RPT-41 | [FE] | PASS | `app/(protected)/omnichannel/reports/page.test.tsx` (menu-adjacent gating tests); live sidebar order Dashboard-before-Inbox, Reports-after-Contacts on tenant A (`01-sidebar-menu-order-1280.png`), and the SAME entries absent on every menu surface for the no-module tenant (`31-noomni-tenant-no-menu-1280.png` sidebar, `32-noomni-desktop-megamenu-1280.png` desktop mega, `33-noomni-mobile-megamenu-375.png` mobile mega) |
| AC-RPT-42 | [FE] | PASS | live: Dashboard resolves the single workspace with no `SearchSelect` shown (tenant has one workspace), tiles + lifecycle + chart + response/resolution + top agents all render, "Timezone: Asia/Kuala_Lumpur" shown as a plain label (`12-dashboard-last7-1280.png`) |
| AC-RPT-43 | [FE] | PASS | live: date-range presets incl. Custom via the `Calendar`/`Popover` (preset dropdown observed with Last 7/30 days, This/Last month, Custom), user + channel + granularity `SearchSelect`s present, NO team control anywhere, state round-trips through the URL (`34-reports-switch-keeps-filters-1280.png`, `35-reports-reload-restores-state-1280.png`) |
| AC-RPT-44 | [FE] | PASS | live: report `SearchSelect` defaults to Conversations, switching report while a `userId` filter is set keeps `userId` in the URL (`34-reports-switch-keeps-filters-1280.png`) |
| AC-RPT-45 | [FE] | PASS | `components/platform/report-chart/report-chart.test.tsx`; live every chart uses `ChartContainer`/`ChartTooltip`/legend, Resolutions report renders a clean "No data in this range." empty state, not an error (`19-reports-resolutions-1280.png`) |
| AC-RPT-46 | [FE] | PASS | live Users/Leaderboard/Assignment log all render as embedded `ResourceList` (search box, Columns control, sortable/reorderable headers, `Rows per page` footer) - `21-`, `22-`, `23-reports-*-1280.png` |
| AC-RPT-47 | [FE] | PASS | `app/(protected)/omnichannel/reports/page.test.tsx`, `use-report-export.test.ts`; live Export -> job -> poll -> authed file download network trace (`25-export-assignments-1280.png`), and Export control absent for the Agent role (`28-`, `29-`, `30-agent-reports-*.png`) |
| AC-RPT-48 | [FE] | PASS | `lib/duration.test.ts` (0s/45s/59s, 1m 0s/1m 30s/59m 59s, 1h 0m/3h 30m/23h 59m, 1d 0h/6d 0h, null/undefined/NaN -> `-`); live "6m 10s", "6m 53s" etc. rendered on the Dashboard/Responses cards |
| AC-RPT-49 | [FE] | PASS | live both widths verified on Dashboard AND Reports: 1280px tiles four-across (`12-dashboard-last7-1280.png`), 375px tiles stack one-per-row + lifecycle wraps 2-up (`15-`, `16-dashboard-375-*.png`), Reports filter bar collapses full-width at 375px + Assignment log table scrolls in its own container with `scrollWidth===clientWidth===375` confirmed via `eval` (`26-`, `27-reports-*-375.png`) |
| AC-RPT-50 | [FE] | PASS | live: a user without `reports.read` never reaches this page at all - proven via the no-module tenant, whose Admin (who DOES hold core `reports.read` but has no module routes to hit) never sees the menu entry; the dedicated no-`reports.read`-role case is covered by `page.test.tsx`'s `RequirePermission` denial test (`renders the standard denial without reports.read`) |
| AC-RPT-51 | [T] | PASS | Backend suite 3112 passed / 3 skipped / 18 deselected (0 failures); isolated 69/69 on the three plan-30 files |
| AC-RPT-52 | [T] | PASS | Frontend suite 291 files / 2176 tests, all passed |
| AC-RPT-53 | [E2E] | PASS | `documentation/plans/sprint-4/30-evidence/E2E/README.md` + 36 screenshots - dedicated tenant, real clicks throughout (dashboard tiles/lifecycle/chart -> preset change re-buckets -> Reports -> all seven report keys -> user filter -> Export Assignments -> download -> parsed the CSV header + one known row), full journey repeated at 375px |
| AC-RPT-54 | [E2E] | PASS | same run: default-tenant JWT against tenant A's `wsId` -> uniform 404 on `dashboard`, `meta`, all seven reports, export POST, and export file GET (ten routes, all 404, curl-verified); no-module tenant shows no Dashboard/Reports entry on sidebar, desktop mega menu, or mobile mega menu (`31-`, `32-`, `33-*.png`) |
| AC-RPT-55 | [T] | PASS | this report |

## Defects found

**None.** Zero FAILs.

## Non-defect observations (logged for completeness, not scored as findings)

1. **Backend `opened` events do not fire when an inbound message matches an already-existing contact
   by phone digits within the workspace** (`InboundService._resolve_contact`) - this is correct,
   documented behaviour (the event fires only when the pipeline CREATES a new contact), but it means
   an E2E setup that creates contacts via the UI first and injects inbound messages second (as this
   run did, to keep contact creation on real clicks per the brief) will show `Opened: 0` on the
   Conversations report even though three threads plainly exist. Not a plan-30 defect - the numbers
   the tester DID generate (2 closed, 1 reopened, 3 incoming/3 outgoing messages, 3 response
   samples) were sufficient to prove every non-flat-chart requirement in AC-RPT-53.
2. **Role-editor `MultiSelect` treats Escape as "cancel the pending selection," not "just close the
   popover"** - cost the tester one redo when granting the Agent's `workspaces.read` permission (see
   `README.md` step 1 for the full account). Pre-existing RBAC role-editor UX, outside plan 30's
   surface area; not filed as a plan-30 defect. Worth a backlog candidate for whoever owns the role
   editor (`BL-SS-` id not minted here - out of scope for this report).

## Deferred items

None deferred by this test pass. The plan's own out-of-scope list (D-A9-7: custom report builder,
scheduled report emails, team presence, broadcast reports, lifecycle funnel/time-in-stage/contacts-
added, calls, materialized rollups) and its twelve backlog candidates (`BL-SS-104..101`, already
registered in `documentation/backlogs/backlog.md` by the coder's uncommitted-but-verified pass noted
in Environment above) cover every acknowledged follow-up; nothing surfaced during this test run that
isn't already tracked there.

## Could not independently verify

- **AC-RPT-27 `source: "workflow"` has no writer yet.** The assignment-log `source` column accepts
  `agent | api | workflow`, and the reader prefers the writer's own `payload.source`; but no code path
  writes `"workflow"` today - the `omnichannel.*` workflow actions do not assign, so every row this run
  produced is `agent` (UI) or would be `api` (gateway). The `workflow` value is pinned only at the
  reader/parity level until an assigning workflow action exists (BL-SS-114's neighbourhood; not a
  plan-30 defect).

- The exact DST bucket-width arithmetic (AC-RPT-12), the 120-bucket/100000-sample caps (AC-RPT-08/13)
  and the two-dialect SQL compile (AC-RPT-11) are internal/numeric properties that pytest already
  pins byte-for-byte; a browser click cannot assert them any more precisely, so these are cited to
  the backend suite only, per house convention for this class of AC.

## Round 1 fixes (coder, 2026-09-06, post-review)

The Opus review of `58759ed..dc92223` raised one blocker, nine significant findings and a set of
nits. All are fixed on this branch; nothing was deferred. Lane `s30` throughout (`:8009` backend,
`:3008` frontend, `foundryx_service_s30`). The tester's 55/55 PASS run (`04cd2aff`) was recorded
against the same working tree, so the evidence above already covers these changes.

| Finding | Fix | Verified by |
|---|---|---|
| **B-1** legacy first-response derivation fetched every no-reply contact id into an unbounded `IN (...)` list, then pulled EVERY message of those contacts into Python | `_derived_response_samples` now identifies each contact's first-ever `AGENT` message (correlated `MIN`) and its preceding `CONTACT` message (correlated `MAX`) under a correlated `NOT EXISTS` on `first_agent_reply`, in ONE statement routed through `duration_samples(cap=REPORT_MAX_SAMPLE_ROWS)` | pytest: fixture numbers unchanged in both timezones; a 25-extra-contact seed proves the round-trip count stays at exactly 1 statement; the cap still raises at `cap + 1`. Live: dashboard `responseTotals.derivedFromMessages = 3` |
| **S-1** correlated / `EXISTS` subqueries over `conversation_events` were not tenant-scoped | `tenant_id` (+ `workspace_id` where available) added to `resolution_samples`' cycle-marker subquery and to the legacy-derivation `NOT EXISTS` | pytest suite green; both remaining correlated sites audited by grep |
| **S-2** `outerjoin(ThreadStatus, ...)` on `Contact.status_id` was unscoped | join condition now carries `ThreadStatus.tenant_id == rq.tenant_id`; audit confirms it is the only such join in the report path | pytest |
| **S-3** lifecycle `percent` divided by the STAGED contact count, not the workspace total (AC-RPT-02) | denominator is now a `COUNT(*)` over the workspace's contacts | pytest (a 9th, unstaged contact makes the fixture read 44.4 / 22.2 / 11.1 / 11.1 / 0.0). Live probe: one unstaged contact took `new_lead` from `5 / 100.0` to `5 / 83.3`, restored on cleanup |
| **S-4** `_series` lacked the explicit window bound its sibling bucketed queries carry | bound added (redundant with the per-bucket `CASE`, but it lets Postgres range-scan `ix_conv_events_ws_created`) | pytest - all series numbers unchanged |
| **S-5** Export ignored the renderer-local `groupBy`, so an export taken while viewing "By agent" silently produced the ungrouped CSV | `groupBy` lifted into `useReportFilters` (URL-synced); the three grouping reports are now controlled; the page derives ONE `scopedFilters` used by both the report request and the export, and clears a group-by the newly selected report does not declare | vitest (`page.test.tsx`: "By agent" -> export sends `groupBy=user`; report switch keeps range/granularity and drops the unsupported group-by). Live: the same export POST with and without `groupBy=user` returns two different CSVs (`User ID,Name,Samples,...` vs `Bucket,Label,Count,Percent`) |
| **S-6** `parseKey` built UTC-midnight Dates while `react-day-picker` matches local midnight - west of UTC the calendar highlighted the previous day and opened on the wrong month | `parseKey` builds from local components, matching `localDateKey`; `displayLabel` drops its `timeZone: 'UTC'` override | vitest `date-range-picker.tz.test.tsx` runs under `TZ=America/Los_Angeles` (with a guard assertion so it cannot pass vacuously) and pins `localDateKey(parseKey(k)) === k` |
| **S-7** the shared fixture hashed three passwords with bcrypt on EVERY test | one module-level precomputed hash | measured A/B on `test_omnichannel_reports_builders.py` (25 tests): **37.74s -> 23.40s**, a 38% cut |
| **S-8** the two-dialect compile test built its own stand-in column | `report_queries.bucketed_select_columns` extracted as the pure column-building half of `bucketed_counts`; the test compiles the REAL multi-series statement on both dialects | pytest |
| **S-9** plan 30's backlog candidates were never registered | `BL-SS-104..101` added to `documentation/backlogs/backlog.md`, each linking back to the plan; BL-SS-105 carries the D-A9-12 measurement in full (1,000,000 rows, ~37-49 ms with or without the composite index after `ANALYZE`, index deferred) | file |
| Nits | assignment-log `source` prefers the writer's own `payload.source` and infers only for legacy rows; `page`/`pageSize` are a typed 422 on the four unpaginated reports; the reports page dropped its hardcoded descriptor fallback for an error state; `useWorkspaceChannels` extracted and used by both pages; `dashboard/loading.tsx` added; the export builds the `users`/`leaderboard` row set ONCE then paginates in memory | pytest (foreign-tenant actor id renders an empty name; a job of another TYPE 404s; two-page proof for `users` + `leaderboard`; explicit `page` 422) + vitest |

UAC/plan amendments (all tagged **amended 2026-09-06 (review round 1)**): AC-RPT-27 (source
precedence), AC-RPT-28 (422 rather than silent ignore, plus the users/leaderboard two-page proof),
AC-RPT-43 (group-by is URL-synced shared state), AC-RPT-44 (unsupported group-by dropped on report
switch; `reports/meta` is the only descriptor source), AC-RPT-47 (export carries the on-screen
group-by; the stale pre-D-A9-10 `conversation_reports.export` corrected to the core `reports.export`).
Plan section 7 records the backlog registration.

Suites after the round: **backend 3121 passed, 1 skipped** (baseline 3114/1, +7 new tests);
**frontend 2181 passed across 292 files** (baseline 2176, +5 new tests); `npx eslint .` 0 errors
(216 pre-existing warnings); `npx tsc --noEmit` 0 errors outside the repo's pre-existing test-file
noise.


## Round 2 fixes (coder, 2026-09-06, post re-read)

The Opus re-read of `983bff15` confirmed every round-1 finding closed and raised four new items plus
nits. All fixed; nothing deferred. Lane `s30` throughout.

| Finding | Fix | Verified by |
|---|---|---|
| **N-1** `reports/page.tsx` treated `!meta` as the error state, so the commit between the workspace id landing and the catalog fetch re-running (the real `useReportMeta(null)` post-state: loading=false / meta=null / error=false) replaced the page with "Couldn't load the reports." on every normal load, and permanently for a role with no workspace (BL-SS-081) | spinner while `!ready || metaLoading || (workspaceId && !meta && !metaError)`; error ONLY on `metaError`; a null workspace renders the header + empty body | new `page.meta-loading.test.tsx` keeps the REAL hook and drives the service with a deferred promise; a `MutationObserver` over the mutation RECORDS (not the live body) catches the transient paint. Both the transient and the dead-end case **fail on the old page** (mutation-checked) and pass on the new. Live: 17 and 28 render the catalog straight off the sidebar click, `Couldn't load` absent on every capture |
| **N-2** `created_at == MIN(created_at)` matched every agent message tied on the first-reply second, double-counting a contact | deterministic `ORDER BY contact_id, created_at, id` + first-row-wins dedupe on `contact_id` in `_derived_response_samples` | `test_legacy_derivation_tied_first_agent_messages_yield_one_sample`: two AGENT messages with the exact same `created_at` -> ONE sample (300s). **Fails without the fix (2 samples), passes with it.** Live: the dashboard's real (untied) numbers are byte-identical to the original run |
| **N-3** screenshots 12-35 predated the round-1 frontend fixes | clean rebuild (`BUILD_ID UU2Fo2BsXkfYNqnCrOnZw`), both servers restarted from the round-2 tree (cwd-verified before killing), all of 12-35 re-recorded with real clicks at 1280 + 375, plus a new **18b** for the group-by URL sync | E2E README "Re-record after review round 2" |
| **N-4** no export test sent `groupBy` | `test_export_responses_group_by_user_renders_the_per_agent_shape` (per-agent header vs the bucket header for the same report ungrouped) + `test_export_messages_group_by_channel_renders_the_per_channel_shape` | pytest |
| Nits | `BL-SS-077..079` moved above `080` (numeric order); `date-range-picker.tz.test.tsx` restores `process.env.TZ` in `afterAll`; this report's "Commit under test" restated to the round-2 commit + build; the AC-RPT-27 `source: "workflow"` gap recorded above | files |

Suites after the round: targeted backend (`test_omnichannel_reports_{dashboard,export,builders}.py`)
**72 passed** (69 + 3 new); **frontend 2184 passed across 293 files** (+3 new); `npx eslint .` 0
errors (216 pre-existing warnings); `npx tsc --noEmit` 0 errors outside the repo's pre-existing
test-file noise. The full backend suite was last run green at `983bff15` (3121 passed, 1 skipped);
round 2 touches only `report_service.py` on the backend, covered by the targeted files.
