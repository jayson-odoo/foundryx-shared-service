# PLAN - Meetings S0: Module skeleton, calendar sync, opt-in

**Status:** BUILT + REVIEWED (2026-08-25) on `sprint-5/meetings-s0-calendar-optin`, unmerged. All
fourteen ACs pass; report: `meetings-s0-calendar-optin-test-report.md`. Backend 54/54 meetings
(134/134 including every core suite this slice touches), frontend 1147/1147, migration verified on
real Postgres across fresh upgrade, downgrade-to-base, re-upgrade and the production stamp path,
with a model-vs-migration drift check that now comes back clean.

Code review closed three blockers that automated tests alone had not caught: a held `syncToken`
meant the 14-day window never rolled, so a meeting first seen beyond it would never arrive; a full
read never returns cancelled events (`showDeleted=false`), so cancellations outside an incremental
page were invisible until the sync learned to prune; and the minute tick had no in-flight guard, so
a tenant whose pass outran the tick accumulated jobs that raced on one `sync_token`. The migration
was also rewritten from `metadata.create_all` to explicit DDL, without which drift is undetectable
by construction.

One follow-up stands: the `google_dwd` adapter has never run against a real Google Workspace. The
onboarding gap it exposed - the Test button needs `admin.directory.user.readonly` on top of
`calendar.readonly`, and the tenant holds TWO connection types - is folded back into spine §5.3.
UAC: `meetings-s0-calendar-optin-acceptance-criteria.md`. Spine: `PLAN-meetings-program.md`.
**Order:** after S1 gate. Frontend mock first (PRINCIPLES step 3), backend test-first second.

## 1. Module skeleton (clone ideation's layout)

```
modules/meetings/
  manifest.json          # module_name meetings, schema app_meetings, alembic_version_table alembic_version_meetings,
                         # routers: settings, optin, events, embed (public later, S6); permissions_csv
  bootstrap.py           # install (schema + create_all + permissions), install_tenant (tenant_settings row), uninstall_tenant (delete where tenant_id)
  db.py                  # MeetingsBase, MEETINGS_SCHEMA = "app_meetings"
  models.py              # the ten tables from spine section 3
  schemas.py             # camelCase ApiModel
  permissions/permissions.csv   # meetings.view, meetings.manage, meetings.settings.manage
  alembic/versions/0001_meetings_init.py
  routers/{settings,optin,events}.py
  services/{calendar_sync,optin,settings}.py
  calendar/{base,google_dwd}.py  # CalendarSource
  jobs.py                # register_job_handler("meetings.calendar_sync")
```

All ten tables land in migration 0001 even though S0 only writes four of them; one migration, one shape, no drip.

## 2. Connections

Two new connection kinds registered with the core connections registry, both encrypted with the existing secret handling:

- `google_dwd`: `service_account_json`, `impersonate_email`. `test()` = list 5 directory users via the Admin SDK with the impersonated admin.
- `meet_bot`: `email`, `password`, `display_name_override` (optional). No `test()` in S0.

## 3. Calendar sync

- Celery beat entry `meetings.calendar_sync` every 60 s -> one `background_jobs` row per tenant with the module active and at least one opted-in user.
- Handler: for each opted-in user, build delegated credentials for that user's email, call `events.list` with `syncToken` when stored (in `user_opt_ins.sync_token`), else `timeMin = now`, `timeMax = now + 14 d`, `singleEvents = true`. On 410 drop the token and refetch.
- Keep events with `conferenceData.entryPoints[video].uri` (Meet) or a Zoom / Teams URL found in `location` / `description` by regex. Upsert `calendar_events` by `(tenant_id, calendar_user_id, external_id)`. Cancelled -> delete the row (or mark, S2).
- After upsert, ensure a `meetings` row per `dedupe_key` (`conference_url|starts_at` in UTC) in status `scheduled`, and a `meeting_participants` row per attendee email with `user_id` resolved against tenant users by email.
- One `integration_activity` row per run: users synced, events upserted, deleted, errors.

## 4. UI (shared-service, `app/(protected)/meetings/`)

- `my-meetings/page.tsx`: master toggle (top), resource-list of upcoming events (title, start, end, organiser, attendees count as `OverflowPills`, platform badge, opt-out switch). Empty state = toggle CTA. Resource shell per the design mandate, no hand-rolled table.
- `settings/page.tsx` (permission `meetings.settings.manage`): connections section (google_dwd, meet_bot), tenant settings form (minutes language `SearchSelect`, audio retention days, bot display name, consent message). Settings fields beyond connections are stored now, used from S4 onward.
- Menu: `config/menu.config.tsx` block gated with `module: 'meetings'`, children `my-meetings` (`meetings.view`) and `settings` (`meetings.settings.manage`). No clickable parent.
- Layering: component -> `useMeetingsOptIn` / `useUpcomingEvents` / `useMeetingsSettings` hooks -> `meetings-service.ts` (mock first, swapped last) -> `lib/api-client`.

## 5. API

| Route | Perm | Body / returns |
|---|---|---|
| `GET /meetings/optin` | view | `{ enabled }` |
| `PUT /meetings/optin` | view | `{ enabled }` |
| `GET /meetings/events?from=&to=` | view | upcoming events for the caller |
| `PUT /meetings/events/{id}/opt-out` | view | `{ optedOut }` |
| `GET /meetings/settings` | settings.manage | tenant settings |
| `PUT /meetings/settings` | settings.manage | tenant settings |
| connections | existing core connection routes, new kinds only |

Routers stay HTTP-only; services own the logic; every query tenant-scoped from the JWT.

## 6. Tests (written before implementation)

- pytest: install / uninstall per tenant (AC-S0-1, 3); module gate 403 (AC-S0-2); sync handler with a fake Google client covering incremental token, 410 fallback, Meet / Zoom / Teams link parsing, cancelled event, dedupe across two users (AC-S0-11, 12); cross-tenant isolation (AC-S0-13); opt-out sticks across syncs (AC-S0-8).
- Vitest / RTL: toggle states, event row opt-out, empty state, settings form validation.
- Playwright: real clicks from the sidebar for AC-S0-6 to AC-S0-9 against the mock, then live, 375 px and 1280 px. Test report keyed to AC ids.

## 7. Backfill / grant sweep (DoD gate)

New permissions -> grant sweep for already-provisioned tenants. No existing rows to backfill (new module).

## 8. Not in this slice

Joining, recording, STT, minutes, notifications, embed pages, Zoom / Teams join. `meetings` rows are created in `scheduled` and stay there until S2.
