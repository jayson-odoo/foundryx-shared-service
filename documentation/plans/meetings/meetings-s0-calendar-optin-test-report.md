# Meetings S0 - Test Execution Report

**Slice:** `PLAN-meetings-s0-calendar-optin.md` · **UAC:** `meetings-s0-calendar-optin-acceptance-criteria.md`
**Branch:** `sprint-5/meetings-s0-calendar-optin` · **Date:** 2026-08-25 (revised after code review)
**Substrate:** backend pytest on the repo's SQLite + `schema_translate_map` fixtures; migrations verified separately on real Postgres; frontend Vitest/RTL; a real browser run against Postgres for the user-perspective pass.

---

## 1. Automated suites

| Suite | Command | Result |
|---|---|---|
| Meetings backend | `python -m pytest tests/test_meetings_{scaffold,api,calendar_sync,connections,jobs}.py -q` | `54 passed, 2 warnings in 29.15s` |
| Meetings + every core suite this slice touches | `... test_integrations test_connections_list test_storage_migration test_app_store test_module_platform` | `134 passed, 7 warnings in 89.40s` |
| Full backend | `python -m pytest -q` | `35 failed, 1780 passed, 18 deselected, 186 warnings in 1091.12s` (measured on the pre-review build; see the note below) |
| Meetings frontend | `npx vitest run "app/(protected)/meetings" "app/(protected)/settings/meetings"` | `Test Files 2 passed (2) · Tests 9 passed (9)` |
| Full frontend | `npx vitest run` | `Test Files 139 passed (139) · Tests 1147 passed (1147)` |
| Types | `npx tsc --noEmit -p tsconfig.json` | no error in any meetings/menu/integrations file (repo has pre-existing errors in unrelated `*.test.tsx` files) |
| Lint | `npx eslint` over every touched frontend path | 0 errors (1 pre-existing warning in `use-connections-list-config.tsx`) |

**The 35 full-backend failures are pre-existing, all in `tests/test_autocount_pipeline.py`.** Verified by
re-running that file with this slice's three core-file edits reverted to `HEAD~2` and
`modules/meetings/` moved aside: `35 failed, 197 passed` - byte-identical to the count with the slice
applied. Nothing in this slice touches AutoCount.

**On the review round's regression evidence, honestly stated.** The review round's only edit outside
`modules/meetings/` and its tests is `app/services/integration_service.py` (a provider may declare it
offers no test) plus one frontend file. Those are covered by the `134 passed` row above, which runs
meetings alongside `test_integrations`, `test_connections_list`, `test_storage_migration`,
`test_app_store` and `test_module_platform` - every core suite that exercises the changed code. A
second full 30-minute sweep was started and was still running when this report was written, on a
machine loaded to ~6-7 by sibling worktrees; the number quoted in the table is therefore the
pre-review measurement, and re-running the full suite is the one verification step this round leaves
open.

## 2. AC coverage

Legend: **T** = covered by an automated test · **B** = verified by hand in a real browser against
Postgres · **N** = not verified.

| AC | Verdict | Evidence |
|---|---|---|
| **AC-S0-1** module in catalog, ten tables, three permissions granted to Admin | PASS (T + B) | `test_meetings_scaffold.py::test_manifest_discovered_and_fields`, `::test_ten_tables_in_the_module_schema`, `::test_permission_catalog_and_admin_grant`, `::test_install_seeds_the_tenant_settings_row`. Browser: the Meetings block renders in the sidebar for a tenant with the module installed, and the App-Store install granted `meetings.view` / `meetings.manage` / `meetings.settings.manage` to the seeded Admin role on Postgres. |
| **AC-S0-2** 403 without the module | PASS (T) | `::test_routes_403_without_the_module` - the core fixture's tenant has no meetings install; all three routes answer 403 from `require_module`. |
| **AC-S0-3** uninstall wipes only that tenant | PASS (T) | `::test_uninstall_wipes_only_this_tenants_rows` - two installed tenants; after uninstalling tenant A its rows are gone, tenant B's survive, and every table is still selectable. |
| **AC-S0-4** `google_dwd` connection: encrypted key, never echoed, Test lists 5 users or shows Google's error | PASS (T + B) | `test_meetings_connections.py::test_google_dwd_is_offered_with_its_two_fields`, `::test_google_dwd_credentials_are_never_echoed_back` (asserts the plaintext key is absent from create AND read responses, and that the stored column is Fernet ciphertext that decrypts back), `::test_google_dwd_test_lists_the_first_five_directory_users`, `::test_google_dwd_test_reports_the_google_error_verbatim`, `::test_google_dwd_test_rejects_a_malformed_key_before_calling_google`. Browser: Settings -> Meetings -> Connect opened the shared integrations form with the provider preselected, saved a connection, and Test returned Google's own wording (`Service account info was not in the expected format, missing fields token_uri.`) with `google-api-python-client` really installed. |
| **AC-S0-5** `meet_bot` connection saved, no live test | PASS (T) | `::test_meet_bot_is_offered_with_a_secret_password`, `::test_meet_bot_saves_without_a_live_test`, `::test_a_tenant_can_hold_both_kinds_at_once`, and `::test_meet_bot_offers_no_test_at_all` - the provider declares an empty `test_label`, the API answers 422 rather than inventing a verdict, and the connection stays `UNVERIFIED` with `lastTestedAt` null. (Review fix 4: the first cut returned ok on a regex check, which showed the operator "Connected" for an account nobody had signed into.) |
| **AC-S0-6** master toggle, off by default, copy-free | PASS (T + B) | API: `test_meetings_api.py::test_optin_is_off_by_default` (which now also asserts that READING the toggle writes no row - review fix 8), `::test_optin_can_be_flipped_both_ways`. UI: `my-meetings-view.test.tsx` "AC-S0-6/9". Browser: the page carries a page title, one switch and the list - no instructional copy anywhere. |
| **AC-S0-7** opted-in user's next 14 days with title/start/end/organiser/attendee count/platform/opt-out switch, within 60 s | PASS (T + B) | Fields: `test_meetings_api.py::test_events_carry_everything_the_row_renders` (seeded RELATIVE to now, review fix 5 - a fixed 2026-09-01 would have turned the suite red the day it passed). Link recognition: `test_meetings_calendar_sync.py::test_meet_zoom_and_teams_links_are_all_mirrored`, `::test_an_event_with_no_conference_link_is_not_mirrored`. The 60 s path: `test_meetings_jobs.py::test_the_beat_tick_enqueues_one_job_per_due_tenant` plus the `meetings.calendar_sync_due` beat entry at `schedule: 60.0`, now with `::test_the_tick_skips_a_tenant_whose_last_sync_is_still_in_flight` (review fix 3: a pass slower than the tick used to pile up jobs that race on one `sync_token` and collide on `uq_meetings_event_calendar`) and `::test_tenants_due_skips_a_tenant_with_no_calendar_connection` (review fix 9: a tenant that never onboarded Google was getting a job every 60 s that could only finish `skipped`). Browser: three real rows (Meet / Zoom / Teams) rendered from Postgres with every field visible. **Not verified:** the 60 s figure end to end against a live Celery beat - only the tick's enqueue behaviour and the schedule value are tested. |
| **AC-S0-8** per-event opt-out sticks, row stays greyed, a later sync does not flip it back | PASS (T + B) | `test_meetings_api.py::test_event_opt_out_sticks_and_the_row_stays`, `::test_event_opt_out_rejects_someone_elses_event`; `test_meetings_calendar_sync.py::test_a_later_sync_never_flips_the_opt_out_back`; UI `my-meetings-view.test.tsx` two AC-S0-8 cases. Browser: clicking the Capture switch on "Vendor call" wrote `opted_out = true` in `app_meetings.calendar_events` (confirmed by SQL), and the row stayed listed with muted text. |
| **AC-S0-9** toggle off: nothing synced, rows kept, empty state with the toggle as the CTA | PASS (T + B) | `test_meetings_api.py::test_optin_off_hides_events_but_keeps_the_rows` (asserts the row count is unchanged in the DB); `test_meetings_calendar_sync.py::test_only_opted_in_users_are_read` (the source is never called); UI `my-meetings-view.test.tsx` AC-S0-9 case asserts the empty state's CTA. |
| **AC-S0-10** cancelled event or removed link disappears | PASS (T) | Google reports a cancellation two ways and both are now covered: `::test_a_cancelled_event_disappears_on_an_incremental_read` (a tokened page names it `status="cancelled"`) and `::test_a_cancelled_event_disappears_on_a_full_read` (a full read defaults to `showDeleted=false`, so the event simply stops being returned). The absence case is handled by a prune, guarded by `::test_a_full_read_prunes_a_row_the_calendar_no_longer_returns`, `::test_a_full_read_does_not_prune_rows_outside_its_window` (a meeting that has since started is behind `time_min` and must survive) and `::test_an_incremental_read_never_prunes` (an incremental page carries only changes, so treating an absence as a deletion there would wipe the calendar on the first quiet tick). Plus `::test_removing_the_link_removes_the_row`. **Review fix 2:** the first cut deleted only on `raw.cancelled`, which a full read never returns, so a cancellation outside an incremental page was invisible. The `meetings` row is still deliberately left in place (S2 owns it once a bot has been scheduled) - noted in §4. |
| **AC-S0-11** incremental `syncToken`, 410 fallback to the 14-day window, one `integration_activity` row per run with counts | PASS (T) | `::test_the_sync_token_is_stored_and_reused` (first read has no token and does carry the window; the second carries the stored token), `::test_an_expired_token_falls_back_to_the_full_window` (call sequence is `["stale", None]`, the retry carries the window, the fresh token is stored), `::test_the_run_writes_one_integration_activity_row` (one row, `source="meetings"`, `operation="calendar.sync"`, counts in the response summary), `::test_a_calendar_error_is_recorded_and_does_not_stop_the_run`. Also `test_meetings_jobs.py::test_a_run_finishes_the_job_and_leaves_one_activity_row`. **Review fix 1**, covered by `::test_a_held_token_is_refreshed_with_a_full_read_once_it_goes_stale`: Google answers an incremental read against the `timeMin`/`timeMax` of the request that MINTED the token, so a token held forever means the 14-day window never rolls and a meeting first seen beyond it never arrives. The token is now dropped every `FULL_RESYNC_AFTER_HOURS` (6); the test asserts the call sequence `[None, "tok-1", None]`, that the third read carries the rolled window, and that an event 20 days out finally lands. |
| **AC-S0-12** two invitees -> two `calendar_events`, exactly one `meetings` row keyed `<url>|<start>` | PASS (T) | `::test_two_invitees_produce_two_events_but_one_meeting` (also asserts participant resolution: tenant users get a `user_id` and their opt-in snapshot, an external attendee gets neither), `::test_the_same_link_at_a_different_start_is_a_different_meeting`, `::test_a_second_sync_does_not_duplicate_the_meeting`. |
| **AC-S0-13** no cross-tenant rows | PASS (T) | `test_meetings_api.py::test_no_cross_tenant_events` (two tenants, two logins, each sees only its own; a cross-tenant id on the opt-out write is a 404), `::test_settings_are_tenant_scoped`, `::test_events_are_scoped_to_the_calling_user`, `::test_settings_needs_the_settings_permission`, and `test_meetings_calendar_sync.py::test_sync_writes_only_into_its_own_tenant` (syncing tenant B reads only B's calendars and writes only B's rows). |
| **AC-S0-14** usable + non-clipped at 375 px and 1280 px | PASS (B) | Browser, real data, both surfaces. **1280:** all seven event fields visible with the capture switch on screen (this needed two fixes, see §4); Settings renders both cards and the four fields. **375:** `document.documentElement.scrollWidth === clientWidth === 375` on both pages - the page body never scrolls sideways. My meetings additionally gained the shared list's card view so the capture switch is reachable on a phone without scrolling the grid sideways. Screenshots were reviewed for each. **Not covered by an automated test** - there is no responsive assertion in the suite. |

## 3. Migration verification (real Postgres, not the SQLite fixture)

The conftest `create_all` path hides a broken migration, so `0001_meetings_init` was run against a
throwaway Postgres database (created and dropped for this check; the shared dev DB was never touched
by it):

- **Fresh path** (`upgrade head`): ten tables + `alembic_version_meetings`, revision id
  `0001_meetings_init` (18 chars, inside the 32-char limit), 42 indexes including the `pg_trgm`
  `ix_meetings_segments_text_trgm` GIN index, `starts_at` is `timestamp with time zone`.
- **Downgrade** (`downgrade base`): every table dropped, zero left behind; `upgrade head` then
  rebuilds all ten.
- **Production path** (`install()`'s `create_all` first, then the orchestrator): stamps to
  `0001_meetings_init` with no DDL, ten tables intact.
- **Drift check** (review fix 6): `compare_metadata` between the live models and the migrated schema
  reports **no differences** other than the `pg_trgm` index, which autogenerate always wants to drop
  because it has no SQLAlchemy equivalent. That check is only meaningful now that the migration is
  explicit DDL.

**Two real bugs the SQLite suite could not see, both found here:**

1. The migration built from `MeetingsBase.metadata` without importing `models`, so the metadata was
   empty, `create_all` was a silent no-op, and the migration only failed later on the trigram index.
2. Worse, `create_all` meant the revision was **not a snapshot at all** - it tracked whatever the
   models happened to say at run time, so a later model change would leave no revision behind and
   drift would be undetectable. The revision is now explicit `op.create_table` for all ten tables
   (autogenerated against Postgres, with a matching `downgrade`), which is what makes the drift check
   above possible.

## 4. Decisions taken that the plan did not cover

1. **Two connection TYPES, not one.** `google_dwd` is `type="calendar"` and `meet_bot` is
   `type="meeting_bot"`. `uq_connection_tenant_type` allows one active connection per type, and a
   tenant needs both at once - a single shared "meetings" type would have made the second one
   unsavable. This avoids touching core's `EXEMPT_FROM_ONE_PER_TYPE`. Test:
   `::test_a_tenant_can_hold_both_kinds_at_once`.
2. **The Test button needs a second Google scope.** AC-S0-4 asks the test to list the first five
   users of the domain, which is the Admin SDK Directory API, not Calendar, so a tenant that grants
   only `calendar.readonly` gets Google's "not authorized" message from every Test. Spine §5.3
   step 2 now names `admin.directory.user.readonly` alongside it, and step 3 names the two connection
   types (decision 1 below) - both folded back in commit `76a6d4c`.
3. **Connections are not re-implemented on Settings -> Meetings.** Each kind is a card that
   deep-links into the shared `/settings/integrations` form. That needed a small extension to the
   shared form (`?provider=` preselect, threaded through `ConnectionFormView` /
   `useConnectionForm`) so the operator is never offered a provider that is wrong for the page they
   came from. Two other one-line additions were needed for a genuinely new connection type: the
   `IntegrationType` union and the form's `TYPE_LABELS` map.
4. **Start and end are ONE "When" column.** Seven separate columns do not fit beside the sidebar at
   1280 px, and the capture switch - the page's only control - was the part falling off the right
   edge. `25 Aug 2026, 02:57-03:57` shows both ends of AC-S0-7 and is how a person reads a meeting
   time.
5. **Card view on the events list.** At 375 px the grid has to scroll sideways to reach the capture
   switch. `cardRender` is the shared list's own prop, so this is a mode on the existing component
   rather than a parallel one.
6. **Retention is a picker, not a number field.** `0 = keep forever` cannot be expressed in a number
   input without instructional copy, which the Foolproof-UI mandate forbids. The field offers
   `30/60/90/180/365 days` and `Keep`.
7. **`SOURCE_MEETINGS` added to core's `ACTIVITY_SOURCES`.** That tuple is closed; without the value
   the module's runs would never render in the Developer Logs console. Precedent: `SOURCE_AUTOCOUNT`.
   The frontend's log badge + filter maps were left alone - an unknown source falls back to its raw
   key, and wiring the console's presentation is not this slice.
8. **A cancelled event deletes its `calendar_events` row but leaves the `meetings` row.** AC-S0-10
   itself defers the "mark cancelled if a meeting already exists" half to S2; S0 creates the meeting
   row in `scheduled` and never removes it.
9. **A full read prunes; an incremental read never does** (review fix 2). `events.list` defaults to
   `showDeleted=false`, so a cancellation is an ABSENCE on a full read and a named event on an
   incremental one. The prune is scoped to the window that was actually read, so a meeting that has
   since started - behind `time_min`, and outside anything the calendar was asked about - survives.
   `FakeCalendarSource` now drops cancelled events from a tokenless read so the tests cannot pass
   against behaviour Google does not have.
10. **`FULL_RESYNC_AFTER_HOURS = 6`** (review fix 1). One constant, chosen so the 14-day window rolls
   several times a day while nearly every tick stays incremental. Anything longer risks a
   long-scheduled meeting arriving late; anything shorter throws away the point of the token.
11. **A provider may declare that it offers no test** (review fix 4), by leaving `test_label` empty.
   Core's `IntegrationService.test` then answers 422 instead of running something weaker and stamping
   the connection ACTIVE on the strength of it, and the frontend hides the Test action for such a
   provider. This is a small generic addition to core rather than a meetings special case - the
   frontend reads it off the provider catalog and hardcodes no provider key.
12. **The in-flight guard reuses the storage migration's shape** (review fix 3): the same
   `(pending, running, needs_review)` triple, checked with the existing
   `BackgroundJobRepository.active_of_type`. No new machinery.

## 5. DoD gate

| Gate item | State |
|---|---|
| Mock swapped to real + verified showing real data | **Done.** `meetings-service.ts` binds `realMeetingsService`; both pages were driven in a browser against Postgres, and a switch clicked in the browser was confirmed written by SQL. The mock stays in `*.mock.ts` for tunable states. |
| Backfill existing rows/tenants | **N/A + covered.** Net-new module, no existing rows. `install_tenant` seeds the settings row, `update_tenant` re-ensures it, and `MeetingsSettingsService.ensure` is seed-if-absent on every read, so a tenant provisioned before a settings row existed still gets one. |
| No hardcoded lookup of a tenant-editable key | **Holds.** The module reads no tenant-editable key; the connection providers resolve by their registry keys, which are code constants. |
| New permission -> grant sweep | **Covered by the install path.** The three keys are new and belong to a new module, so no already-provisioned tenant can be missing them: `AppStoreService.install` grants them to the tenant's Admin role at install time, asserted by `::test_permission_catalog_and_admin_grant` and confirmed on Postgres. |
| Verify from the USER's perspective, 375 + 1280 | **Done** (see AC-S0-14). Verified on `npm run dev` (the standing rule), not a production build - **`next build` was not run**, so `next build`-only errors (RSC / server-component typing) are unverified for this slice. |

## 6. What is NOT verified

- **The 60 s freshness figure end to end.** No live Celery beat + worker was run; the tick's tenant
  selection, its enqueue, and the `schedule: 60.0` entry are tested, the wall-clock claim is not.
- **A real Google Workspace - still the single largest untested surface.** Every calendar test drives
  a scripted `CalendarSource`. `modules/meetings/calendar/google_dwd.py` - the `events().list`
  parameter shaping (including the rule that `syncToken` and `timeMin`/`orderBy` are mutually
  exclusive), pagination, the HTTP-410 -> `SyncTokenInvalid` mapping, `parse_event`, and
  `list_directory_users` - has **no automated test and has never run against Google.** Only its
  failure paths have been exercised for real: the Test button was driven end to end in the browser
  with `google-api-python-client` installed and returned Google's own wording
  (`Service account info was not in the expected format, missing fields token_uri.`). The unused
  injection seam that used to sit in this file was removed in review (it had zero callers and gave a
  false impression of testability), so exercising this properly means a real Workspace, which is the
  first thing to do when a tenant is onboarded.
- **`next build`.** Dev server only, per the standing frontend rule.
- **A second full backend sweep after the review round.** Meetings plus every core suite the round's
  diff touches is green (`134 passed`); the full 1815-test sweep was still running when this was
  written. Run `python -m pytest -q` before merge and expect the same 35 pre-existing
  `test_autocount_pipeline.py` failures and nothing else.
- **The browser pass was not repeated after the review round.** Nothing in it changes a rendered
  surface except hiding the Test action for a provider that offers none; that is asserted on the
  backend (422 + `UNVERIFIED`) but the hidden menu row itself is unverified in a browser.
- **Playwright.** No new spec was added; the browser evidence above is an agent-browser run.
- **Multi-tenant browser check.** Cross-tenant isolation is proven by tests, not by two browser
  sessions.
