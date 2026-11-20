# Meetings S2 - Test Execution Report

**Slice:** `PLAN-meetings-s2-orchestrator.md` · **UAC:** `meetings-s2-orchestrator-acceptance-criteria.md`
**Branch:** `sprint-5/meetings-s2-orchestrator` (stacked on S0, S1 bot merged in) · **Date:** 2026-08-25
**Substrate:** backend pytest on the repo's SQLite + `schema_translate_map` fixtures; migrations verified separately against a throwaway Postgres; frontend Vitest/RTL; and one LIVE run of the whole chain (beat tick -> Redis -> `bots` worker -> a real Docker container -> the meeting row) against a throwaway Postgres database that was dropped afterwards.

---

## 1. Automated suites

| Suite | Command | Result |
|---|---|---|
| Meetings backend (10 files) | `python -m pytest tests/test_meetings_*.py -q` | `143 passed, 3 warnings in 68.31s` |
| Core suites this slice touches | `... test_integrations test_connections_list test_storage_migration test_app_store test_module_platform test_document_engine test_document_sharing test_background_jobs` | `135 passed, 11 warnings in 106.79s` |
| Meetings frontend | `npx vitest run "app/(protected)/meetings" "app/(protected)/settings/meetings"` | `Test Files 3 passed (3) · Tests 22 passed (22)` |
| Full frontend | `npx vitest run` | `Test Files 140 passed (140) · Tests 1160 passed (1160)` (measured before the review round; the meetings row above is the post-review measurement) |
| Types | `npx tsc --noEmit -p tsconfig.json` | no error in any meetings file |
| Lint | `npx eslint` over every touched frontend path | 0 errors, 0 warnings |

New backend test files: `test_meetings_shared_calendar.py` (Task 0, 19), `test_meetings_dispatch.py` (14),
`test_meetings_bot_runner.py` (22), `test_meetings_recordings.py` (10), `test_meetings_ops_api.py` (11),
plus `meetings_bot_fakes.py` (a fake Docker daemon, a fake artifact store, a recording storage).

New frontend tests: 3 cases on My meetings (status badge, reason, no reason on a clean row),
6 in `bot-runs.test.tsx`, 3 Task 0 cases on the calendar-address field, 1 on the settings page.

### 1.1 The full-sweep caveat, stated honestly

Meetings (`143 passed`) plus every core suite this diff touches (`135 passed`) is green. What is NOT
measured here is the whole `python -m pytest -q` sweep. **Run it before merge** and expect the same pre-existing
`tests/test_autocount_pipeline.py` failures S0 recorded (35) and nothing else - nothing in this slice
touches AutoCount.

## 2. AC coverage

Legend: **T** = covered by an automated test · **L** = exercised in the live run · **N** = not verified.

| AC | Verdict | Evidence |
|---|---|---|
| **AC-S2-1** one job, one `joining`, a second tick does not duplicate | PASS (T + L) | `test_meetings_dispatch.py::test_a_meeting_about_to_start_gets_exactly_one_bot`, `::test_a_second_tick_does_not_dispatch_it_again`, `::test_a_meeting_further_out_than_the_lead_is_left_alone`. **Live:** the tick dispatched 1 and the meeting went to `joining`; the second tick after the run dispatched 0. |
| **AC-S2-2** everyone opted out, or the master toggle off -> `skipped` | PASS (T) | `::test_a_meeting_everyone_opted_out_of_is_skipped`, `::test_the_master_toggle_is_read_live_not_off_the_snapshot`, `::test_a_meeting_with_only_external_attendees_is_skipped`. |
| **AC-S2-3** two invitees, one meeting, one bot run | PASS (T) | `::test_two_invitees_of_one_meeting_produce_one_run` (two `calendar_events`, one job), `::test_one_invitee_opting_out_does_not_cancel_the_others_capture`, and from the user's side `test_meetings_ops_api.py::test_two_invitees_of_one_meeting_see_the_same_status`. |
| **AC-S2-4** late dispatch with `late = true`; a finished meeting is `skipped`/`missed` | PASS (T) | `::test_a_meeting_that_started_20_minutes_ago_is_still_dispatched_as_late`, `::test_a_meeting_that_has_already_ended_is_skipped_as_missed`, `::test_a_meeting_five_minutes_in_is_dispatched_but_not_flagged_late`. |
| **AC-S2-5** container carries the tenant's credentials, name, consent and profile volume; status follows the events | PASS (T + L) | `test_meetings_bot_runner.py::test_the_container_carries_this_tenants_credentials_and_volume`, `::test_the_display_name_and_consent_come_from_the_tenants_settings`, `::test_the_status_follows_the_bots_events`, `::test_an_event_line_is_parsed_into_its_kind_and_payload`, `::test_a_tenant_with_no_notetaker_account_fails_loudly_without_a_container`. **Live:** a real `meetings-bot-<id>` container ran from `foundryx-shared-service:bot-spike` with the seeded per-tenant profile volume. |
| **AC-S2-6** finished -> `processing`, one core `files` row, duration, transcribe enqueued | PASS (T), **NOT live** | `::test_a_finished_call_registers_one_recording_and_queues_transcription` (folder, filename, one `file_versions` row, mime, segments deleted, `events.jsonl` kept, `meetings.transcribe` queued), `::test_every_normal_exit_word_counts_as_a_finished_call`, `::test_a_call_that_recorded_nothing_still_finishes_without_a_file`, and `test_meetings_recordings.py` in full - including TWO REAL opus segments concatenated by the same ffmpeg the worker uses and the joined file measured back at 1.0 s. **The live run never recorded**, because the only Meet available to it refused the join; the recording path has no live evidence. |
| **AC-S2-7** `not_admitted`/`denied` -> `not_admitted` with the reason, no files | PASS (T + L) | `::test_a_denied_join_is_not_admitted_with_the_reason_and_no_files`, `::test_a_lobby_timeout_is_not_admitted_too`, `test_meetings_ops_api.py::test_a_not_admitted_row_carries_the_reason`. **Live:** the container printed `[event] denied {"stage": "landing"}` then `[event] finished {"reason": "denied", "segments": 0}`, exited 0, and the row ended `status='not_admitted' reason='denied'` with `FILES 0`. |
| **AC-S2-8** non-zero exit -> `failed` with reason + screenshot key, no retry | PASS (T) | `::test_a_non_zero_exit_fails_the_meeting_and_keeps_the_screenshot` (asserts `screenshot_key` and the job result), `::test_a_failed_run_is_never_retried`, `::test_a_container_that_cannot_start_is_a_failed_meeting_not_a_crash`. |
| **AC-S2-9** five meetings in one minute, none dropped | PARTIAL (T) | `::test_five_meetings_in_one_minute_all_get_a_job` proves the tick never drops one and all five sit `pending`, and `::test_the_bots_worker_consumes_only_its_own_queue` pins `worker_prefetch_multiplier = 1` so a slot never hoards a job it cannot start. **The cap itself is Celery's `--concurrency` and is NOT tested** - proving the fifth waits and then starts needs five concurrent containers, which the pilot host cannot run. |
| **AC-S2-10** SIGTERM stops each container gracefully, segments kept | PASS (T), **NOT live** | `::test_sigterm_stops_the_container_the_polite_way_and_lets_celery_shut_down` asserts `container.stop(timeout=45)` and that the previous (Celery) handler still runs. That `docker stop` makes the bot leave the call and flush its tail is S1's behaviour, asserted there, not re-proven here. |
| **AC-S2-11** status badge + reason on My meetings | PARTIAL (T + B) | Backend: `test_meetings_ops_api.py::test_an_event_carries_the_status_of_the_meeting_behind_it`, `::test_a_not_admitted_row_carries_the_reason`, `::test_a_failed_row_carries_the_reason_too`, `::test_an_event_whose_meeting_row_is_not_there_yet_reads_scheduled`, `::test_the_opt_out_write_answers_with_the_status_too`. UI: `my-meetings-view.test.tsx` three AC-S2-11 cases; the reason renders through `ClampedText`, never a bare truncate. **Browser (§3b):** every status renders as a badge at 1280 and 375, and the reason is on screen clamped to two lines. **The hover half does NOT work** - `ClampedText`'s tooltip never fires in this app (pre-existing, platform-wide, evidenced in §3b), so a reason longer than two lines cannot currently be read in full. That is why this row is PARTIAL. |
| **AC-S2-12** bot-runs list + notetaker connection status | PASS (T + L + B) | Backend: `::test_a_run_is_listed_with_everything_the_page_renders`, `::test_a_failed_run_reports_the_jobs_error_when_the_bot_gave_no_reason`, `::test_the_window_is_a_week_by_default`, `::test_bot_runs_need_the_settings_permission` (403 for `meetings.view` alone), `::test_bot_runs_are_scoped_to_the_calling_tenant`. Connection half: `test_meetings_bot_runner.py::test_a_run_that_reached_meet_marks_the_notetaker_connection_active`. UI: `bot-runs.test.tsx` (6). **Live:** after the run the `meet_bot` connection was `ACTIVE` with `last_tested_at` set, having been `UNVERIFIED` before. **Browser (§3b):** `settings-meetings-1280.png` / `-375.png`. |
| **AC-S2-13** two tenants at once share nothing | PASS (T) | `::test_two_tenants_meeting_at_once_share_nothing_but_the_image` builds both specs and asserts neither contains the other's password, tenant id or volume, while the image is the same. |
| **AC-S2-14** the worker consumes only `bots` and `docker info` succeeds, or it is a startup ERROR | PASS (T + L) | `::test_the_worker_refuses_to_boot_on_the_wrong_queue`, `::test_the_worker_refuses_to_boot_without_docker`, `::test_the_worker_boots_when_the_queue_and_the_socket_are_both_right`, `::test_the_boot_check_runs_as_a_bootstep_not_a_signal`. **Live, all three:** `-Q bots` logged `queue=bots, docker reachable` and became ready; `-Q workflow` exited 1 with `WorkerBootError: The bots worker must consume only the 'bots' queue (got ['bots', 'workflow'])`; `DOCKER_HOST=unix:///nonexistent/docker.sock` exited 1 with `cannot reach Docker: ... Check DOCKER_HOST and that the socket is mounted`. |

## 3. The live run

No human trigger anywhere in the chain past the single tick invocation, which is the same call
`celery beat` makes every 60 s.

**Setup.** Throwaway Postgres `meetings_s2_live` (dropped afterwards; the shared dev DB was never
touched). Its own `.env` in a scratch directory - `pydantic-settings` reads `.env` relative to the
CWD and `.env` beats real env vars, so a second file is the only way to point at a different
database. `CELERY_TASK_ALWAYS_EAGER=false` so the job really crosses Redis. The S1 spike's
signed-in Chromium profile was copied INTO a Docker volume
`meetings-profile-<tenant_id>` (a read of the s1 worktree; nothing there was modified), because
without a signed-in profile the bot would have tried a real Google login with the bogus seeded
credentials and never reached the join.

```bash
psql -U tehjayson -d postgres -c "CREATE DATABASE meetings_s2_live;"
sed -e 's|^DATABASE_URL=.*|DATABASE_URL=postgresql://tehjayson@localhost:5432/meetings_s2_live|' \
    -e 's|^CELERY_TASK_ALWAYS_EAGER=.*|CELERY_TASK_ALWAYS_EAGER=false|' \
    service_backend/.env > <scratch>/live/.env

docker volume create meetings-profile-00000000-0000-0000-0000-000000000001
docker run --rm -v "meetings-profile-...:/profile" -v "<s1>/bot/.profile:/seed:ro" alpine:3 \
  sh -c 'cp -a /seed/. /profile/ && rm -f /profile/Singleton*'

# core tables + module install + one meeting starting in 1 minute, fake Meet code
cd <scratch>/live && PYTHONPATH=<worktree>/service_backend python seed_live.py

# the bots worker (the three env vars are mandatory on macOS - see §4.6)
no_proxy='*' PGGSSENCMODE=disable OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
  PYTHONPATH=<worktree>/service_backend \
  celery -A modules.meetings.worker worker -Q bots -c 1 --loglevel info

# ONE beat tick
PYTHONPATH=<worktree>/service_backend python tick.py
```

**Outcome, verbatim.**

```
worker  [2026-08-25 11:00:28] meetings bots worker: queue=bots, docker reachable
worker   -------------- [queues]  .> bots  exchange=bots(direct) key=bots
worker  [2026-08-25 11:00:29] celery@Tehs-Mac-mini.local ready.
tick    dispatched: 1
tick    meeting 58060895-47fd-432d-8706-a18fd78c50d1 joining None
worker  [job 5c4d4027-...] started meetings-bot-58060895-... from foundryx-shared-service:bot-spike
docker  meetings-bot-58060895-47fd-432d-8706-a18fd78c50d1   Exited (0)
docker  [event] denied {"stage": "landing"}
docker  [event] finished {"reason": "denied", "segments": 0}
db      MEETING  status='not_admitted' reason='denied' screenshot=None duration=None file=None
db      JOB      type=meetings.bot_run status=done result={'reason': 'denied'} error=None
db        log    started meetings-bot-58060895-... from foundryx-shared-service:bot-spike
db      FILES     0
db      CONN     meet_bot status=ACTIVE last_tested_at=2026-08-25 03:00:46+00:00
tick2   dispatched: 0
```

**Teardown.** Container removed, volume removed, both throwaway databases dropped, the worker
killed by PID filtered on its own cwd. Verified afterwards: no `meetings_s2%` database, no
`meetings-bot-*` container, no `meetings*` volume, no worker process.

## 3a. Review round (2026-08-25)

Seven correctness findings, each written test-first. **Every new test was then confirmed RED with
its fix reverted** - which is how three of them were caught proving nothing:

| Test | First verdict | Why it was not testing anything |
|---|---|---|
| the skip survives a later failure | GREEN | `JobService.create` commits, so a LATER meeting's insert had already committed the earlier skip. The failure has to happen before anything in that pass commits, so it now explodes inside `wants_capture`. |
| a NULL-ended meeting is not dispatched weeks later | GREEN | The test helper turned an explicit `ends_at=None` into its DEFAULT (start + 1 h), so the NULL case was never built. A sentinel now tells "not given" from "the calendar gave no end". |
| the twelfth calendar still fails the test | GREEN | `opted_in_calendars` ordered by `user_id`, which is a uuid - so "the twelfth calendar" landed anywhere in the list. It now sorts by ADDRESS, which is stable and also stops the Test message reordering itself between runs. |

The other four were red first time: any-setup-failure, container re-attach, SIG_DFL, and the
double registration.

## 3b. Browser pass (DoD gate)

Driven with `agent-browser` (own session `meetings-s2`, closed afterwards; never `close --all`),
navigating by SIDEBAR clicks from `/`, against a throwaway Postgres `meetings_s2_browser` seeded
with every state the surfaces have to render - scheduled / recording / not-admitted / failed (with a
deliberately long, space-free reason) / ready / skipped, two bot runs, and a calendar connection in
shared mode. Backend on 8051 and `npm run dev` on 3051 (8001 and 3001 belong to other lanes and were
left alone). Screenshots: `evidence/s2/`.

**Two real defects the tests could not have caught, both fixed and re-verified:**

1. **The status column pushed the Capture switch off the right edge at 1280 px** - the exact trap S0
   hit and fixed once already (its decision 4). A seventh column does not fit beside the sidebar at
   the widths S0 chose. Every column was re-sized to what it actually needs; the switch is back on
   screen and `When` still shows both ends of the meeting.
2. **The failed row's reason ran out of its cell instead of wrapping.** Two causes stacked: the
   DataGrid's own `td` carries `truncate`, whose `white-space: nowrap` cascades in and neuters
   `line-clamp` entirely; and a reason like `error:TimeoutError:waiting...` has no spaces to wrap at.
   Fixed with `whitespace-normal break-all` on that one cell. It now clamps to two lines inside the
   column.

**One defect found and deliberately NOT fixed here.** `ClampedText` renders its recover-the-text
tooltip only when it measures itself as truncated, and in this app it never does: instrumented in
the live page, all 16 `ClampedText` instances reported `truncated=false`, including several that
were genuinely overflowing (the reason at `scrollHeight` 192 vs `clientHeight` 32, and the
service-account address at 40 vs 20). A `ResizeObserver` attached by hand to the same element from
the console fired normally, so the observer is not the problem - the component's state is being
reset, most likely by a remount on every grid render. **This is pre-existing and platform-wide**
(it affects every list in the app, not just meetings), so it is reported rather than patched: a
speculative change to a shared component that I could not verify fixes the cause is worse than
leaving it visible. One such change was written during this pass and REVERTED for exactly that
reason. Consequence for this slice: the reason is on screen, clamped, and present in full in the
DOM, but the hover half of AC-S2-11 does not work. Logged as the top follow-up.

| Evidence | Shows |
|---|---|
| `my-meetings-1280.png` | AC-S2-11 at 1280: status badge per row (Scheduled / Recording / Not admitted / Failed / Ready / Skipped), the reason clamped under the badge, the Capture switch on screen, plus Task 0's Calendar field and the "Shared with" service-account address. |
| `my-meetings-375.png` | AC-S2-14-equivalent at 375: `scrollWidth === clientWidth === 375`, the toggle, Calendar field and address stacked. |
| `my-meetings-375-cards.png` | AC-S2-11 at 375 in the shared list's card mode: every card carries status, reason and the capture switch without sideways scrolling. |
| `settings-meetings-1280.png` | AC-S2-12 at 1280: Bot runs with meeting, started, ended, exit reason (badge + word) and duration (`58m 00s`, and `-` for the run that never recorded); the notetaker connection Connected with its last success time; the calendar connection Unverified with the service-account address. |
| `settings-meetings-375.png` | AC-S2-12 at 375: `scrollWidth === clientWidth === 375`, cards stack. |
| `connection-shared-mode-1280.png` | Task 0: Access reads "Calendars shared with the service account", Admin email empty, key masked. |
| `connection-shared-mode-test-1280.png` | Task 0, the Test button run for real against the Google client: `notetaker@foundryx-meet.iam.gserviceaccount.com cannot read demo.personal@gmail.com: The private_key field was not found in the service account info.` It names the address to share WITH, the calendar it could not read (which is the opt-in override, so `test_needs_context` really reached the tenant's rows), and Google's own wording. |

Also verified by hand, not screenshotted: typing a new address into the Calendar field and blurring
wrote it through the real API (`demo.personal@gmail.com` to `demo.work@gmail.comx`, confirmed by
SQL against `app_meetings.user_opt_ins`).

Torn down afterwards: browser session closed, both servers stopped by PID filtered on their own cwd,
database dropped. Verified zero leftovers, and the other lanes' servers on 3030/3060/8001 untouched.

## 4. Decisions the plan did not cover

1. **The boot check is a BOOTSTEP, not a `worker_init` signal handler** (plan §5 did not say how).
   Celery CATCHES whatever a signal receiver raises, logs it and carries on - its own docstring says
   "in Celery send and send_robust do the same thing". The first cut used the signal and was caught
   live: `-Q workflow` booted happily, banner and all. As a bootstep the exception propagates out of
   the worker's constructor and the process exits 1. Pinned by
   `::test_the_boot_check_runs_as_a_bootstep_not_a_signal`, which also asserts no meetings receiver
   is attached to `worker_init`.
2. **A local bind-mount output target beside the plan's `s3://`** (plan §3). The plan assumes a
   tenant storage connection; the pilot tenant has none, so `BOT_OUT=s3://<bucket>/...` would have
   nothing to fill in and the bot would record nowhere. `build_output` returns the S3 form when the
   tenant HAS a storage connection (with that connection's own credentials on the container, as the
   plan says) and otherwise bind-mounts `<media_root>/meetings/<tenant>/<meeting>` at `/out`. Both
   paths carry the tenant id, and `Artifacts` is the two-method seam so nothing above branches.
3. **`not_admitted_reason` renamed to `status_reason`, plus `screenshot_key`** (migration 0003).
   S2 has three unhappy statuses and the S0 column could only ever have told the truth about one of
   them. Nothing had written it - S0 creates every meeting `scheduled` and never sets a reason - so
   the rename carries no data and needs no backfill. It is a rename rather than a drop-and-add so a
   database that somehow does hold a value keeps it.
4. **The master toggle is read LIVE at dispatch**, not off `meeting_participants.is_opted_in`. That
   column is a snapshot taken when the participant row was written (S0 kept it for later minutes
   visibility), so a user who switched off this morning would still have been recorded.
   `::test_the_master_toggle_is_read_live_not_off_the_snapshot`.
5. **Duration comes from the bot's own event timestamps**, not from re-reading the audio. Every
   event carries `ts`, so `finished - recording_started` is exact and costs nothing; ffprobing the
   joined file would be a second ffmpeg pass for a number we already have.
6. **The macOS worker needs three env vars.** The very first live run died with
   `WorkerLostError: Worker exited prematurely: signal 11 (SIGSEGV)` before the handler ran, leaving
   the meeting in `joining`. `PGGSSENCMODE=disable` (libpq's Kerberos/XPC path segfaults in a forked
   prefork child), `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` and `no_proxy='*'` fix it. Documented at
   the top of `modules/meetings/worker.py`; Linux needs none of them, so the compose service does
   not carry them.
7. **`worker_bots` is in `docker-compose.yml` but COMMENTED OUT.** A worker that cannot reach Docker
   now refuses to boot by design, so enabling the service before the bot image is published and a
   host is chosen would break a deploy. The block is complete and ready to uncomment.
8. **Registration failure is a `failed` meeting, not a raised job.** An exception inside
   `register_recording` used to escape `run_bot`; `run_job` would mark the job failed but leave the
   meeting in `joining` forever. It is now caught, and the reason says the recording could not be
   stored - the audio is still where the bot left it.
9. **A `select` field, not a checkbox, for the calendar access mode** (Task 0). The shared connection
   form stores every non-secret field as a string and has no boolean control; two named options are
   both foolproof and a zero-line change to core.
10. **A provider may ask core for the session** (Task 0), by declaring `test_needs_context`.
    `IntegrationService.test` then passes `db` and `tenant_id`. The shared-calendar test has to read
    the tenant's own opt-in rows, and a provider opening its own session would leave nothing a test
    could steer. Two lines in core, one attribute on one provider - the same shape as S0's
    "a provider may declare it offers no test".

## 5. What is NOT verified

- **The recording path has no live evidence** (AC-S2-6). The only Meet reachable from here refuses
  the join, so no container has ever recorded audio under the orchestrator. Segments -> one file ->
  a `files` row is covered by tests using REAL opus bytes and the real ffmpeg concat, and the S1
  spike recorded real meetings by hand - but the two halves have never run joined up.
- **Concurrency (AC-S2-9)** beyond "the tick drops nothing". Five simultaneous bot containers were
  not run.
- **SIGTERM mid-call (AC-S2-10)** against a real container. The handler is asserted with a fake; the
  bot's own leave-and-flush behaviour is S1's evidence, not this slice's.
- **The recover-the-text tooltip on a clamped reason** (the hover half of AC-S2-11), because
  `ClampedText` never measures itself as truncated in this app. Pre-existing and platform-wide;
  evidence and the reasoning for not patching it are in §3b. **Top follow-up.**
- **`next build`.** Dev-server rule; not run.
- **The full `pytest -q` sweep** (see §1.1).
- **A real Google Workspace** for the Task 0 shared-calendar sync. The three live-probe facts are
  encoded and tested against a fake source; a real end-to-end sync in shared mode has not run.
- **Playwright.** No new spec; the live evidence above is a scripted run, not a browser one.

## 6. DoD gate

| Gate item | State |
|---|---|
| Mock swapped to real + verified showing real data | **Done.** `meetings-service.ts` binds `realMeetingsService`, and both surfaces were driven in a browser against a live backend and Postgres (§3b): the bot-runs list, the status badges and the service-account address are all real rows, and a Calendar address typed in the browser was confirmed written by SQL. |
| Backfill existing rows/tenants | **Covered.** `user_opt_ins.calendar_email` is nullable and NULL is the correct value for every existing row (it means "my login email", which is what the sync already did). `meetings.status_reason` is a rename of a column nothing had written; `screenshot_key` is new and NULL is correct. Verified on Postgres: fresh upgrade, downgrade to base, re-upgrade, zero model-vs-schema drift. |
| No hardcoded lookup of a tenant-editable key | **Holds.** The "Meetings" folder is looked up by NAME and created if absent - a stored id would be a hardcoded reference to something a tenant can rename. Connection providers resolve by registry key, which is a code constant. |
| New permission -> grant sweep | **N/A.** No new permission. `/meetings/bot-runs` reuses `meetings.settings.manage`, which S0 already grants at install. |
| Verify from the USER's perspective, 375 + 1280 | **Done** (§3b), on `npm run dev` per the standing rule, not a production build - so `next build`-only errors are unverified. Two real layout defects were found and fixed by it. One pre-existing platform defect (the ClampedText tooltip) is reported, not fixed. |
