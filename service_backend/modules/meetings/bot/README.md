# The meeting bot container

One container = one meeting. Built in S1 (`PLAN-meetings-s1-bot-spike.md`), driven
in S2 by `modules/meetings/services/bot_runner.py`. This file is the contract
between the two: everything the orchestrator sets, and everything it reads back.

The image for the pilot is `foundryx-shared-service:bot-spike`, built locally:

```bash
./run.sh build          # docker build -t foundryx-shared-service:bot-spike .
./run.sh login          # one-time interactive Google sign-in, over VNC on :5900
```

`BOT_PROFILE_DIR` keeps that sign-in. Losing the profile volume means signing in
by hand again, so it is a named volume per tenant, never a throwaway.

## Environment

| Variable | Set by | Meaning |
|---|---|---|
| `BOT_EMAIL` | orchestrator | The notetaker Google account. Used only if the persisted profile is not already signed in. |
| `BOT_PASSWORD` | orchestrator | Its password. From the tenant's encrypted `meet_bot` connection; passed as env and never written to disk. |
| `BOT_DISPLAY_NAME` | orchestrator | Base display name. Default `Notetaker`. |
| `BOT_FOR_USER` | orchestrator | Whose notetaker this is. Non-empty makes the name `<display name> (for <user>)` and fills the default consent text. |
| `BOT_CONSENT_TEXT` | orchestrator | The message posted in the Meet chat on join. Omitted = the bot's own default, which names `BOT_FOR_USER`. |
| `BOT_OUT` | orchestrator | Where artefacts go: a container path (bind-mounted) or `s3://bucket/prefix/`. |
| `BOT_S3_ENDPOINT` | orchestrator | S3-compatible endpoint (R2/MinIO). Unset = AWS. |
| `BOT_S3_REGION` | orchestrator | Region for the S3 client. Default `auto`. |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | orchestrator | Credentials for `BOT_OUT` when it is `s3://`. |
| `BOT_HEADLESS` | orchestrator | `1` (default) runs `--headless=new`. `0` runs headed under Xvfb, the fallback if Meet ever refuses headless. |
| `BOT_PROFILE_DIR` | image | `/profile`. The persistent Chromium profile; mount a per-tenant volume here. |
| `BOT_LOBBY_TIMEOUT` | image | Seconds to wait in the lobby before giving up. Default 180. |
| `BOT_EMPTY_ROOM_SECONDS` | image | Leave after this long with no humans. Default 60. |
| `BOT_MIN_SECONDS` | image | Never call the room empty before this. Default 60. |
| `BOT_NO_SHOW_TIMEOUT_S` | image | Before any human has ever been seen, leave (`no_show`) after this long from join instead of arming the empty-room leave. Default 600 (10 min) - covers a late host. |
| `BOT_MAX_SECONDS` | image | Hard cap on one meeting. Default 4 h. |
| `BOT_BROWSER_CHANNEL` | image | `chrome` on amd64; unset uses Playwright's Chromium (arm64). |

Also required by the container itself: `--shm-size=1g` (Chromium), and a `/out`
bind mount when `BOT_OUT` is a path.

## Command

```
python -m bot --meet-url <url> [--display-name X] [--for-user Y] [--out DIR]
python -m bot --login-only
```

The orchestrator passes only `--meet-url`; everything else rides the environment.

## What it writes to `BOT_OUT`

| Name | When | Who reads it |
|---|---|---|
| `audio_NNNN.ogg` | every 60 s while recording | S2 concatenates these into one core `files` row, then deletes them |
| `events.jsonl` | on exit | S3 (speaker timeline from the caption events) |
| `last.png` | on a non-zero exit | S2 stores the key on the meeting so a failure is diagnosable |
| `in_call.png`, `dom_probe.json` | periodically | humans, when Meet's DOM changes |

## What it writes to stdout

Every event is one line, and this shape is the orchestrator's input:

```
[event] <kind> <json object>
```

Kinds S2 acts on: `in_lobby` (meeting -> `in_lobby`), `joined` and
`recording_started` (-> `recording`), `finished` (carries `reason` and
`segments`). Everything else - `participants`, `active_speaker`, `caption`,
`consent_posted`, `captions_on`, `dom_probe`, `logged_in`, `left` - is recorded
and ignored until S3.

Every event carries `ts` (epoch seconds). S2 takes the recorded duration from the
gap between `recording_started` and `finished` rather than re-reading the audio.

## Exit

The LAST stdout line is the bare exit reason, and it is also on the `finished`
event. Exit code 0 with one of:

| Reason | Meaning | S2 sets |
|---|---|---|
| `room_empty` | last human left (only armed AFTER a human has been seen) | `processing` -> `ready` |
| `no_show` | nobody was EVER seen; `BOT_NO_SHOW_TIMEOUT_S` expired from join | `skipped` (no recording registered, never transcribed) |
| `removed` | the bot was removed from the call | `processing` -> `ready` |
| `ended` | the host ended the meeting | `processing` -> `ready` |
| `max_duration` | hit `BOT_MAX_SECONDS` | `processing` -> `ready` |
| `stopped` | SIGTERM; it left the call and flushed its tail | `processing` -> `ready` |
| `not_admitted` | waited out the lobby | `not_admitted` |
| `denied` | Meet refused the join outright | `not_admitted` |

Exit code 1 with `error:<what>` means it crashed; S2 marks the meeting `failed`,
keeps `last.png`, and never retries - a meeting happens once, and re-joining it
later would record an empty room and report a successful capture of nothing.

## SIGTERM

`docker stop` sends SIGTERM; the bot handles it by leaving the call, flushing the
last segment and exiting `stopped`. Give it time: S2 stops with a 45 s timeout.
