# Meetings S0 - Module skeleton, calendar sync, opt-in: Acceptance Criteria (UAC)

**Status:** contract, pre-build. Written FIRST per PRINCIPLES (UAC -> plan -> build).
**Scope:** `foundryx-shared-service`. Spine: `PLAN-meetings-program.md` (M1, M3, M4, M6, M19).
**Goal:** the `meetings` module installs per tenant, reads each opted-in user's Google Calendar through domain-wide delegation, and shows upcoming meetings with a per-event opt-out. Nothing joins anything yet.

---

## A. Module

**AC-S0-1** - Given a platform admin, when the module catalog is synced, then `meetings` appears in the App Store with title, icon and schema `app_meetings`, and installing it for a tenant creates the ten module tables under `app_meetings` and grants `meetings.view` / `meetings.manage` / `meetings.settings.manage` to the tenant admin role.

**AC-S0-2** - Given a tenant without the module installed, when a user of that tenant calls any `/meetings/*` route, then the response is 403 from `require_module`.

**AC-S0-3** - Given the module is uninstalled for a tenant, then only that tenant's rows are deleted and the schema stays.

## B. Connections

**AC-S0-4** - Given a tenant admin, when they open Settings -> Meetings, then they can create a `google_dwd` connection with: service-account JSON (encrypted at rest, never echoed back), admin email to impersonate. Test button lists the first 5 users of the domain or shows the Google error verbatim.

**AC-S0-5** - Given a tenant admin, when they create a `meet_bot` connection (notetaker email + password, encrypted at rest, never echoed back), then it is saved; no live test in S0 (the bot tests it in S2).

## C. Opt-in

**AC-S0-6** - Given a tenant user with `meetings.view`, when they open Meetings -> My meetings, then they see a master toggle, off by default, and copy-free UI (Foolproof-UI mandate).

**AC-S0-7** - Given the master toggle is switched on, when the next sync runs (at most 60 s), then the user's calendar events for the next 14 days that carry a Google Meet, Zoom or Teams link appear in the list with title, start, end, organiser, attendee count, platform badge, and an opt-out switch per event, on by default.

**AC-S0-8** - Given an event row, when the user switches it off, then `calendar_events.opted_out = true` for that row, it stays visible greyed, and a later sync does not flip it back.

**AC-S0-9** - Given the master toggle is switched off, then no further events are synced for that user, existing rows stay, and the list shows an empty state with the toggle as the next-step CTA.

**AC-S0-10** - Given a calendar event is cancelled or its Meet link removed, when the next sync runs, then the row disappears (or is marked cancelled if a meeting already exists for it, S2 concern).

## D. Sync mechanics

**AC-S0-11** - Given the sync job, when it runs, then it uses Google incremental sync (`syncToken`) per user and falls back to a full 14-day window when the token is invalid, logging one `integration_activity` row per run with counts.

**AC-S0-12** - Given two users of the same tenant are invited to the same Meet, when both are opted in, then two `calendar_events` rows exist (one per calendar user) and exactly one `meetings` row is created with `dedupe_key = <conference_url>|<starts_at>`.

**AC-S0-13** - Given tenant A and tenant B both installed, when a user of tenant A lists events, then no tenant B rows are returned (test asserts across tenants).

## E. Responsive

**AC-S0-14** - My meetings and Settings -> Meetings are usable and non-clipped at 375 px and 1280 px.
