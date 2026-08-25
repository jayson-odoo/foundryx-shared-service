# PLAN - Meetings S2: Orchestrator

**Status:** Planning. UAC: `meetings-s2-orchestrator-acceptance-criteria.md`. Spine: `PLAN-meetings-program.md`.
**Branch:** `sprint-5/meetings-s2-orchestrator`, stacked on S0 with the S1 bot merged in.
**Order:** frontend status badge + bot-runs list against a mock, then backend test-first, then swap.

## 1. Pieces

```
modules/meetings/
  jobs.py                 # + dispatch_due_bot_runs (beat 60 s), bot_run handler, transcribe stub
  services/dispatch.py    # which meetings are due, skipped, late, missed (AC-S2-1..4)
  services/bot_runner.py  # container lifecycle via docker SDK (AC-S2-5..10)
  services/recordings.py  # segments -> one opus file -> core files row (AC-S2-6)
  bot/                    # S1 image; add bot/README with the env contract
  worker.py               # Celery app for queue "bots" (like omnichannel/worker.py), concurrency from env
```

## 2. Dispatch (`services/dispatch.py`)

- Beat entry `meetings.dispatch_bots` every 60 s, next to the calendar sync entry.
- Query: `meetings.status = scheduled` and `starts_at <= now + 2 min`. For each: opted-in participants whose event row is not opted out. None -> `skipped` (`reason = opted_out`). `ends_at < now` -> `skipped` (`reason = missed`). Else create one `background_jobs` row type `meetings.bot_run`, payload `{meeting_id, tenant_id, late}`, and set `status = joining`. Idempotent by status: a meeting is only picked while `scheduled`.
- The job is enqueued on the Celery queue `bots` (the `app/jobs` framework's `jobs.run` task with `queue="bots"`); the app-server workers never see it.

## 3. Bot runner (`services/bot_runner.py`)

- `docker` SDK (`docker>=7`) against the local socket (`DOCKER_HOST` default). Image name from settings (`MEETINGS_BOT_IMAGE`, default `foundryx-shared-service:bot-spike` for the pilot).
- Container spec: env `BOT_EMAIL`, `BOT_PASSWORD` (from the decrypted `meeting_bot` connection), `BOT_DISPLAY_NAME`, `BOT_FOR_USER`, `BOT_CONSENT_TEXT`, `BOT_HEADLESS=1`, `BOT_OUT=s3://<bucket>/<tenant>/<meeting>/` plus the tenant storage connection's S3 credentials as env; volume `meetings-profile-<tenant_id>:/profile`; `shm_size=1g`; `auto_remove=False` so logs survive; name `meetings-bot-<meeting_id>`.
- Run loop: start container, tail `events.jsonl` from the container's stdout `[event]` lines, map to status updates (`in_lobby`, `joined -> recording`, `not_admitted`, `denied`, `finished`). Wait for exit. Exit reason from the last stdout line.
- Concurrency: Celery worker `--concurrency` (default 4). The handler blocks for the meeting duration; that is the cap.
- SIGTERM on the worker: Celery warm shutdown lets running tasks finish; the handler installs a signal hook that runs `container.stop(timeout=45)` (the bot handles SIGTERM by leaving) so shutdown takes under a minute.

## 4. Recording registration (`services/recordings.py`)

- On `finished` with a recording: list `audio_*.ogg` under the meeting prefix, concatenate with `ffmpeg -f concat` inside the worker (ffmpeg is in the backend image), upload `recording.ogg`, delete the segments, register one core `files` row (+ `file_versions`) in the tenant's "Meetings" folder (created on first use), set `meetings.recording_file_id`, `duration_s`, `status = processing`, enqueue `meetings.transcribe` (S3; S2 handler logs and sets `ready` so the UI path can be seen).
- `events.jsonl` and captions stay under the meeting prefix for S3.

## 5. Worker (`modules/meetings/worker.py`)

Clone `modules/omnichannel/worker.py`: Celery app on the shared Redis, `task_default_queue = "bots"`, imports the meetings job handlers. Docker-compose service `worker_bots` for prod (separate VM later; in compose it mounts `/var/run/docker.sock`). Pilot: `celery -A modules.meetings.worker worker -Q bots -c 2` on the Mac Mini with `DOCKER_HOST` unset (colima socket).

## 6. UI

- My meetings: status badge column (colour per status), reason via `ClampedText` on failed / not_admitted rows. Hook + service extended; mock first.
- Settings -> Meetings: "Bot runs" resource list (last 7 days) from `GET /meetings/bot-runs`, and the connection status line.

## 7. API

| Route | Perm | Returns |
|---|---|---|
| `GET /meetings/events` (existing) | view | + `meetingStatus`, `statusReason` |
| `GET /meetings/bot-runs?days=7` | settings.manage | runs from `background_jobs` joined to meetings |

## 8. Tests (before implementation)

- pytest: dispatch (due / opted-out / missed / late / idempotent second tick / shared meeting for two users); runner with a fake Docker client (container spec per tenant, AC-S2-13; event -> status mapping; non-zero exit -> failed with screenshot key; graceful stop on SIGTERM); recordings registration with a fake storage (segments -> one file row, meeting fields); worker boot checks (AC-S2-14) with a fake docker client.
- Vitest: status badge states, reason clamp, bot-runs list.
- Live: one real meeting dispatched from the calendar with no human trigger (the spike's manual `run.sh join` retired).

## 9. Not in this slice

STT, minutes, notifications, retention, canary, Zoom / Teams, the Linux bot VM (pilot stays on the Mac Mini until the S2 gate passes).
