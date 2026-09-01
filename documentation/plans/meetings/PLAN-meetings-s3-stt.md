# PLAN - Meetings S3: STT (transcript + speaker names)

**Status:** In progress 2026-09-01 - coder pass done (pytest + vitest green); live mlx evidence run still pending (captain's step, see Deviations). Spine: `PLAN-meetings-program.md` M12 (amended 2026-08-25), M19.
**Branch:** `sprint-5/meetings-s3-stt`. UAC: `meetings-s3-stt-acceptance-criteria.md`.

## 1. What S3 delivers

The `meetings.transcribe` job stops being a stub. After S2 registers `recording.ogg`, S3:

1. runs Whisper over the audio (pilot = `mlx-whisper` on the Mac Mini, M12),
2. reads the caption timeline the bot recorded (`events.jsonl` `caption` events, proven S1 run 7),
3. assigns each Whisper segment a speaker NAME from the overlapping captions,
4. writes one `transcripts` row + `transcript_segments` rows, sets the meeting `transcribed`.

No UI beyond a minimal read endpoint + the new status badge (S5 owns the surface). No minutes
(S4). No pyannote - names come from captions; diarization only if captions prove insufficient
(M12 names the trigger).

## Grill rulings (2026-09-01)

- **R1** Transcription runs on the existing workflow queue; the `mlx_local` driver holds a
  host-level flock so at most ONE transcription runs at a time (16 GB host shares Metal with
  live bot containers). No fourth worker.
- **R2/R7/R8** Status chain grows one value: `recording -> processing -> transcribed -> ready`.
  S3 ends at **`transcribed`** (badge "Transcript ready"); `ready` means minutes exist and is
  S4's to set - no stub job that fakes it. Spine data model + S2 FE badges updated in this PR.
- **R3** `transcript_segments.language` stays NULL (Whisper turbo reports one language per file;
  never store a guessed per-segment value). Transcript-level `language` carries the detection.
- **R4** Re-run = the existing core `/jobs/{id}/retry`; no bespoke retranscribe endpoint.
- **R5** Provider selection is a platform setting, not per-tenant (M21 trigger stands).
- **R6** `scripts/setup_stt_venv.sh` creates/pins `~/foundryx-stt/venv` (mlx-whisper==0.4.3)
  idempotently - a reboot or new host rebuilds it deterministically.

## S2 live-run fixes (2026-09-01)

Three defects found in a live pilot run, fixed test-first on this branch (do-not-touch hold on
`dispatch.py`/`bot_runner.py` lifted for exactly these changes; `bot/` untouched):

- **Shared-calendar participants never matched their opted-in user.** Participant-to-user
  matching only compared the login email; a shared personal calendar's attendee list carries
  `calendar_email` instead, so every `meeting_participants.user_id` stayed NULL and eligibility
  found nobody opted in (`opted_out` on every meeting). Fix: `calendar_email` is now an
  ADDITIONAL match, case-insensitive, ENABLED opt-ins only - at sync-time row creation
  (`calendar_sync._ensure_participants`) and again in eligibility (`dispatch.wants_capture`, so a
  legacy NULL-`user_id` row also resolves once its owner's opt-in exists). Login-email matching
  is unchanged. New shared helper `optin.enabled_calendar_email_index`.
- **A stale Chromium `Singleton*` lock killed the join.** An interactive re-login on the same
  tenant profile volume leaves `SingletonLock`/`-Cookie`/`-Socket` behind; the next bot's
  Chromium then refuses to start ("profile appears to be in use ... on another computer"). Fix:
  `bot_runner._container_for` now runs a short-lived helper container (`spec.image`, entrypoint
  override, `remove=True`) that clears `/profile/Singleton*` on the SAME profile volume right
  before every fresh container start (never before a re-attach, while Chromium may still be using
  the volume). A cleanup failure fails the run with the docker error, not a silent skip.
- **Re-attach adopted a dead container and re-failed forever.** A failed run leaves its exited
  container behind (`auto_remove=False`, kept for logs); the next `bot_run` for that meeting
  re-attached to it, saw it exited, and marked the meeting failed again in ~0.1s - the fixed
  container name then blocked every retry's fresh container with a name conflict. Fix:
  `_container_for` re-attaches only to a container whose `.status == "running"`; anything else
  found under that name is removed (`force=True`) and a fresh container is started in the same
  run. A removal failure fails the run with the docker error.

## 2. Inputs available at transcribe time (measured, not assumed)

- `meetings.recording_file_id` -> core `files` row = `recording.ogg` (opus, concatenated by S2).
- The meeting's artifacts location (same resolution as S2 `recordings.py`: tenant storage
  connection -> S3 prefix, else local dir under `media_root`) still holds `events.jsonl` -
  S2 deletes only `audio_*.ogg` segments after concatenation.
- `events.jsonl` rows: `{"ts": <epoch float>, "kind": "caption", "speaker": "<display name>",
  "text": "<final block>"}` plus lifecycle events. Recording start epoch = the ts of the first
  recorder segment event; caption offset into the audio = `caption.ts - start_epoch`.

## 3. Design (simplest thing that works)

### 3.1 `SttProvider` adapter (`modules/meetings/stt/`)

Adapter earns its place: a second implementation is already planned (M12 - GPU VM / Modal when
volume demands, Deepgram as fallback). Interface:

```python
class SttProvider(Protocol):
    def transcribe(self, audio_path: Path) -> SttResult:
        ...  # SttResult = language + [SttSegment(start_ms, end_ms, text)]
```

**v1 driver `mlx_local`** (`stt/mlx_local.py`): subprocess exec of a small runner script through
a dedicated python (`MEETINGS_STT_PYTHON`, default `~/foundryx-stt/venv/bin/python`; built by
`scripts/setup_stt_venv.sh`, R6), serialized by a host flock (R1), model
`MEETINGS_STT_MODEL` (default `mlx-community/whisper-large-v3-turbo`), with
`condition_on_previous_text=False` and a `no_speech_threshold` - both proven necessary on run-7
audio (trailing-silence hallucination). Subprocess, not import: mlx runs on Metal in its own venv
(py version + deps differ from the backend venv) and a crash must not take the worker down. JSON
on stdout, hard timeout `MEETINGS_STT_TIMEOUT_S` (default 1800).

**Deepgram fallback = config only** (`MEETINGS_STT_PROVIDER=deepgram` exists in settings and
selects a driver that does not ship in S3; the plan-named trigger for building it is the first
real mlx outage or the prod move). Provider selection: `MEETINGS_STT_PROVIDER` (default
`mlx_local`) - platform setting, not per-tenant (one pilot host; per-tenant when a second
tenant's volume demands it, M21).

### 3.2 Speaker names from captions (`stt/align.py`)

Pure function, no I/O: `assign_speakers(segments, captions, start_epoch)`.

- Caption event -> interval: block FINALIZED at `ts`; its span is approximated as ending at `ts`
  and starting at the previous caption's ts (floor: 2 s minimum) - except the FIRST caption, whose
  span starts at the recording start, not `ts - 2s`. Good enough because Meet finalizes blocks per
  speaker turn (S1 run 7: 20/20 blocks carried the right name). The first-caption rule was fixed
  post-implementation: a 2026-09-01 live evidence run (134 s single-speaker meeting) showed Meet
  finalizing a continuous monologue as ONE caption block only on leave, at ts 130.65 s, while the
  last speech segment ended at 113.52 s - 15.13 s outside the 15 s nearest-caption window under the
  original `ts - 2s` rule, so every segment named nobody; the fix widens the first caption's span
  back to the recording start so it covers everything spoken since captures began.
- Whisper segment -> the speaker whose caption interval overlaps it most; no overlap -> nearest
  caption within 15 s; still nothing -> `NULL` (renders as "Speaker" later, never a guess).
- Text similarity is deliberately NOT used - names ride TIME, captions and Whisper disagree on
  wording by design (that is why we transcribe at all).

### 3.3 Handler + rows

`run_transcribe` (replaces the stub in `jobs.py`):

1. Load meeting + recording file; download bytes to a temp file (storage router).
2. `provider.transcribe(path)`.
3. Read `events.jsonl` from artifacts (missing/empty file -> transcript with NULL speakers,
   `service.log` says captions were absent - a host disabling captions must not kill the job).
4. Replace-on-rerun: delete existing `transcripts` row for the meeting (cascade segments), insert
   one `transcripts` row (`stt_provider`, `model`, `created_at`) + `transcript_segments`
   (`speaker`, `start_ms`, `end_ms`, `text`, `language` NULL per R3) - the S0 tables, no schema
   change beyond the status enum value (R2).
5. `meeting.status = transcribed` (R2), `background_jobs` result carries counts + timing.
6. Failure -> job `FAILED` + `meeting.status = failed` with the error logged; the job stays
   re-runnable (idempotent via 4).

Migration `0004`: `pg_trgm` GIN index on `transcript_segments.text` (the spine's data model names
it; cheap now, and prod deploy path runs module migrations already).

### 3.4 Read endpoint (evidence surface until S5)

`GET /meetings/{meeting_id}/transcript` (permission `meetings.view`, tenant-scoped, 404 until
`transcribed`): `{ sttProvider, model, language, segments: [{speaker, startMs, endMs, text}] }`.

## 4. Files

```
modules/meetings/stt/__init__.py        # SttProvider protocol + get_provider()
modules/meetings/stt/mlx_local.py       # subprocess driver
modules/meetings/stt/mlx_runner.py      # the script exec'd inside the STT venv
modules/meetings/stt/align.py           # caption -> segment speaker assignment
modules/meetings/jobs.py                # run_transcribe real body
modules/meetings/routers/transcripts.py # GET transcript
modules/meetings/alembic/versions/0004_transcript_trgm.py  # + CREATE EXTENSION IF NOT EXISTS pg_trgm
modules/meetings/models.py              # STATUS_TRANSCRIBED
service_frontend (status badges)        # "Transcript ready" badge for the new value
scripts/setup_stt_venv.sh               # R6
app/config.py                           # MEETINGS_STT_* settings
```

## 5. Tests (Phase 2, test-first)

- `align.py` pure-function table: overlap wins, nearest-within-15s, no-caption NULL, empty list.
- `mlx_local` driver with a fake subprocess (JSON contract, timeout kill, non-zero exit).
- `run_transcribe` with a fake provider + fake artifacts: rows written, replace-on-rerun,
  `transcribed` status, captions-missing path, failure path marks meeting failed.
- Router: transcript shape, 404 before ready, cross-tenant 404.
- ONE live evidence run (not pytest): run-7 audio + its real events.jsonl through the real
  mlx venv -> named transcript (the UAC gate).

## 6. Out of scope

Minutes (S4 - it adds the minutes job + the `ready` hop), transcript UI (S5), Deepgram driver
body, pyannote, live transcript, per-segment language values (R3), search endpoint (index
ships, endpoint later).

## 7. Deviations from this plan (coder pass, 2026-09-01)

Flagged rather than applied silently, per the house rule:

- **No migration `0004_transcript_trgm.py`.** Measured against the real schema before writing
  it: `pg_trgm` + `ix_meetings_segments_text_trgm` were ALREADY created in migration `0001`
  (S0's "whole shape in one migration" - see its lines creating the extension/index right after
  `transcript_segments`). Adding a second `CREATE EXTENSION IF NOT EXISTS` / `CREATE INDEX IF NOT
  EXISTS` would be a no-op DDL migration for no reason - "simplest thing that works" says don't
  ship it.
- **Transcript-level `language` rides `Meeting.language`, not a new `transcripts.language`
  column.** The `Transcript` model (fixed in rev 0001) never had a `language` column - only
  `TranscriptSegment.language` exists, and R3 says that one stays NULL. `PLAN-meetings-program.md`
  §3's table already lists `language` as a `meetings` column (present since S0, unused until now)
  - S3 is simply the first slice to WRITE it, from `SttResult.language`. Zero new DDL. The
    `GET /transcript` response's `language` field reads `meeting.language`.
  - `TranscriptSegment`'s docstring updated to explain why its `language` column stays unused
    (R3) rather than leaving the stale S0 comment that said the opposite.
- **`meetings.transcribe` treats "no recording" as a clean SKIP, not a failure.** `bot_run` (S2,
  out of scope to change) enqueues `transcribe` unconditionally on every normal exit, including a
  call that recorded nothing (empty room, `recording_file_id` stays NULL). Failing that loudly
  would mark a meeting "failed" when nothing actually went wrong - there is simply nothing to
  transcribe. Treated the same as the existing "meeting is gone" skip. Confirmed against the S2
  test `test_a_call_that_recorded_nothing_still_finishes_without_a_file`, which already existed
  for exactly this case.
- **Reused `bot_runner.build_output`, not a "helper extracted from `recordings.py`."** Measured:
  the artifacts-resolution logic (`storage_connection` + `S3Artifacts`/`LocalArtifacts` branch) is
  in `services/bot_runner.py`, not `services/recordings.py` (which only has the `Artifacts`
  protocol + the two concrete classes). `bot_runner.py` is on this slice's do-not-touch list (live
  pilot code), so `jobs.py` imports `build_output` as-is rather than moving/duplicating it -
  reuse, not a rebuild, just from where the code actually lives.
- **Five pre-existing S2 tests in `test_meetings_bot_runner.py` updated, `bot_runner.py` itself
  untouched.** R2/R7/R8 retire the S2 stub's "mark it `ready`" behavior; those five tests asserted
  exactly that stub behavior (one even said so in a comment: "S2 hands off to the S3 stub, which
  marks it ready"). Updated their assertions to the new terminal statuses (`transcribed` on a real
  recording, `processing` - untouched - when nothing was recorded) and extended the file's
  `local_storage` fixture to also cover `jobs.py`'s own `storage_for_tenant` import plus a trivial
  always-succeeds `get_provider` stub, so the S3 job `bot_run` now synchronously triggers in tests
  finishes cleanly without every S2 test needing its own STT setup.
- **Live mlx evidence run (AC-S3-5/6/7, UAC "Evidence run") NOT done.** Explicitly the captain's
  step per the brief - the STT venv (`scripts/setup_stt_venv.sh`) was written but not executed,
  and no real mlx-whisper process ran. Every subprocess-touching test uses a fake `subprocess.run`
  or a fake `SttProvider`.
