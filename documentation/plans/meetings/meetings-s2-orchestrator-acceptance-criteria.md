# Meetings S2 - Orchestrator: Acceptance Criteria (UAC)

**Status:** contract, pre-build. Written FIRST per PRINCIPLES.
**Scope:** `foundryx-shared-service`. Spine: `PLAN-meetings-program.md` (M6, M7, M8, M17, M19).
**Goal:** a scheduled meeting the user has not opted out of is joined by exactly one bot container at the right time, with no human trigger; the outcome (recorded / not admitted / failed) is visible on the meeting row; audio lands in the tenant's storage as core `files`.

---

## A. Scheduling

**AC-S2-1** - Given a `meetings` row in `scheduled` whose `starts_at` is within the next 2 min and at least one participant with `is_opted_in = true` whose `calendar_events` row is not opted out, when the beat tick runs (60 s), then exactly one `background_jobs` row of type `meetings.bot_run` exists for that meeting (a second tick does not create another), and the meeting moves to `joining`.

**AC-S2-2** - Given every opted-in participant has opted the event out, or the master toggle is off, when the tick runs, then no job is created and the meeting moves to `skipped`.

**AC-S2-3** - Given two `calendar_events` rows from two users pointing at the same conference link and start, then they share one `meetings` row (S0) and one bot run.

**AC-S2-4** - Given a meeting whose `starts_at` was more than 15 min ago and no bot ever ran (worker down), when the tick runs, then it is still dispatched once with `late = true` on the job payload; a meeting whose `ends_at` has passed is marked `skipped` with reason `missed`.

## B. Bot run

**AC-S2-5** - Given a `meetings.bot_run` job is claimed by the `bots` worker, when it runs, then a container from the bot image is started with the meeting URL, the tenant's `meeting_bot` credentials (from the encrypted connection, passed as env, never written to disk), the display name and consent text from `tenant_settings`, and a per-tenant profile volume; the `meetings.status` becomes `in_lobby` / `recording` / `not_admitted` / `failed` as the container's events arrive.

**AC-S2-6** - Given the container exits `room_empty`, `removed`, `ended` or `max_duration`, then `meetings.status = processing`, `duration_s` is set, each audio segment is registered as a core `files` row in the tenant's "Meetings" folder (concatenated to one file per meeting), `recording_file_id` points at it, and a `meetings.transcribe` job is enqueued (handler is S3; in S2 it only logs).

**AC-S2-7** - Given the container exits `not_admitted` or `denied`, then `meetings.status = not_admitted` with the reason, no files are created, and the opted-in users see the status on My meetings.

**AC-S2-8** - Given the container exits non-zero, then `meetings.status = failed`, the reason and the `last.png` screenshot key are stored on the row, and the job is marked failed (no automatic retry: a meeting cannot be re-joined later).

**AC-S2-9** - Given the worker's concurrency cap (default 4 per worker), when 5 meetings start in the same minute, then the fifth waits in the queue and starts as soon as a slot frees; none is dropped.

**AC-S2-10** - Given the worker process receives SIGTERM while containers run, then it stops each container with the graceful path (bot leaves the call, uploads its tail) before exiting; segments recorded so far are kept.

## C. Ops surface

**AC-S2-11** - Given a user with `meetings.view`, when they open My meetings, then each event row shows the meeting status (`scheduled`, `joining`, `in_lobby`, `recording`, `processing`, `ready`, `not_admitted`, `failed`, `skipped`) as a badge, and a `failed` or `not_admitted` row shows its reason on hover/tap (`ClampedText`, no bare truncate).

**AC-S2-12** - Given a tenant admin, when they open Settings -> Meetings, then a "Bot" section shows the last bot run per meeting for the last 7 days (meeting, started, ended, exit reason, duration) as a resource list, and the tenant's `meeting_bot` connection status (`UNVERIFIED` until a run succeeds, then `ACTIVE` with the last success time).

## D. Isolation and infra

**AC-S2-13** - Given tenant A and tenant B each have a meeting at the same minute, then each bot runs with its own tenant's credentials, profile volume and storage connection; a test asserts the container spec for A never contains B's values.

**AC-S2-14** - Given the pilot layout (worker on the Mac Mini, app + Redis local), when `worker_bots` starts, then it consumes only the `bots` queue and `docker info` succeeds through the mounted socket; failure of either is a startup error, not a silent idle worker.
