# PLAN - Meetings S1: Bot spike

**Status:** In progress (day 1: 6 runs, join + record + leave proven; see `meetings-s1-bot-spike-test-report.md`). UAC: `meetings-s1-bot-spike-acceptance-criteria.md`. Spine: `PLAN-meetings-program.md`.
**Nature:** one-week spike. Code lives in `service_backend/modules/meetings/bot/` from the start (so S2 keeps it), but nothing is wired to the app, no migrations, no UI. Gate = evidence run, not a PR review.

## 1. What is built

```
modules/meetings/bot/
  Dockerfile            # ubuntu + chromium + xvfb + pulseaudio + ffmpeg + python playwright
  entrypoint.sh         # start pulseaudio null sink, Xvfb :99, then python -m bot
  bot/__main__.py       # CLI: --meet-url --display-name --consent-text --out s3://... --profile /profile
  bot/meet_selectors.py # EVERY Meet DOM selector, nothing else (M18)
  bot/meet.py           # login, join, lobby wait, consent chat, active-speaker poll, leave detection
  bot/recorder.py       # ffmpeg pulls the pulse monitor, writes 60 s chunks, uploads each as it closes
  bot/events.py         # events.jsonl writer (joined, active_speaker, participant_count, left, error)
```

One container = one meeting. Inputs by env / CLI. Outputs = chunks + `events.jsonl` + last screenshot to the storage prefix. Exit code + one-line reason on stdout.

## 2. Steps

1. **Image.** Playwright's Ubuntu base, add `xvfb`, `pulseaudio`, `ffmpeg`, `x11vnc`. Chromium runs **`--headless=new`** by default (no Xvfb, no compositor; memory is the constraint the captain named 2026-08-24) with a persistent `--user-data-dir=/profile`, `--disable-gpu`, no automation banner flag, 1280x720. `BOT_HEADLESS=0` falls back to headed-under-Xvfb if Meet refuses headless. The one-time login always runs headed with VNC on :5900 (2SV needs a screen). Fake-media flags off (we want the real pulse sink). Playwright stays: it is a thin driver, Chromium is the memory; agent-browser is Playwright underneath and built for interactive use, not a 2 h unattended call.
2. **Login once by hand** inside the container (`--login-only`), profile volume persisted. Automatic re-login path for expired sessions, using the password from env (encrypted `Connection` arrives in S2).
3. **Join flow** (`meet.py`): open URL, wait for pre-join screen, mute mic + cam, set display name if the field is offered, click Join / Ask to join, then poll for one of: in-call toolbar (joined), "Asking to join" (lobby), "You can't join" (denied). Lobby timeout 180 s -> exit `not_admitted`.
4. **Consent**: open chat panel, send the consent text, close panel.
5. **Record** (`recorder.py`): `ffmpeg -f pulse -i <sink>.monitor -f segment -segment_time 60 -c:a libopus out_%04d.ogg`; a watcher uploads each finished segment immediately (so a crash loses at most 60 s).
6. **Active speaker + count** (`meet.py`): every second read the participant list / speaking indicator from the DOM, append to `events.jsonl`. Participant count excludes the bot.
7. **Leave** when participant count has been 0 for 60 s, or the "You've been removed" dialog appears, or a hard 4 h cap. Flush ffmpeg, upload the tail, write `left`, exit 0.
8. **Failure path**: any unexpected state -> screenshot to storage, `error` event, exit 1 with reason.
9. **Measure memory**: `run.sh join` samples `docker stats` every 15 s into `stats.log`; the report states peak RSS per run. Turn off incoming video in Meet if a selector for it is found (largest saving).
10. **Run it five times** on scheduled FoundryX Meets, once on an external-hosted Meet (AC-S1-3). Write `meetings-s1-bot-spike-test-report.md`.

## 3. Runs on

Mac Mini, Docker Desktop, `docker run` by hand. Storage target = a FoundryX R2 bucket via `AWS_*`-style env (the tenant storage connection replaces this in S2).

## 4. Not in this slice

Scheduling, calendar, Celery, DB rows, UI, STT, retries, Zoom / Teams. Any of these creeping in is scope failure.

## 5. Exit

AC-S1-10 met, report written, list of selectors that broke during the week recorded in the report. Then S0.
