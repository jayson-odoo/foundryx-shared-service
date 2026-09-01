# PLAN - Meetings S3: STT (transcript + speaker names)

**Status:** Planned 2026-09-01. Spine: `PLAN-meetings-program.md` M12 (amended 2026-08-25), M19.
**Branch:** `sprint-5/meetings-s3-stt`. UAC: `meetings-s3-stt-acceptance-criteria.md`.

## 1. What S3 delivers

The `meetings.transcribe` job stops being a stub. After S2 registers `recording.ogg`, S3:

1. runs Whisper over the audio (pilot = `mlx-whisper` on the Mac Mini, M12),
2. reads the caption timeline the bot recorded (`events.jsonl` `caption` events, proven S1 run 7),
3. assigns each Whisper segment a speaker NAME from the overlapping captions,
4. writes one `transcripts` row + `transcript_segments` rows, sets the meeting `ready`.

No UI beyond a minimal read endpoint (S5 owns the surface). No minutes (S4). No pyannote - names
come from captions; diarization only if captions prove insufficient (M12 names the trigger).

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
a dedicated python (`MEETINGS_STT_PYTHON`, default `~/foundryx-stt/venv/bin/python`), model
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
  and starting at the previous caption's ts (floor: 2 s minimum). Good enough because Meet
  finalizes blocks per speaker turn (S1 run 7: 20/20 blocks carried the right name).
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
   (`speaker`, `start_ms`, `end_ms`, `text`, `language`) - the S0 tables, no schema change.
5. `meeting.status = ready`, `background_jobs` result carries counts + timing.
6. Failure -> job `FAILED` + `meeting.status = failed` with the error logged; the job stays
   re-runnable (idempotent via 4).

Migration `0004`: `pg_trgm` GIN index on `transcript_segments.text` (the spine's data model names
it; cheap now, and prod deploy path runs module migrations already).

### 3.4 Read endpoint (evidence surface until S5)

`GET /meetings/{meeting_id}/transcript` (permission `meetings.view`, tenant-scoped, 404 until
ready): `{ sttProvider, model, language, segments: [{speaker, startMs, endMs, text}] }`.

## 4. Files

```
modules/meetings/stt/__init__.py        # SttProvider protocol + get_provider()
modules/meetings/stt/mlx_local.py       # subprocess driver
modules/meetings/stt/mlx_runner.py      # the script exec'd inside the STT venv
modules/meetings/stt/align.py           # caption -> segment speaker assignment
modules/meetings/jobs.py                # run_transcribe real body
modules/meetings/routers/transcripts.py # GET transcript
modules/meetings/alembic/versions/0004_transcript_trgm.py
app/config.py                           # MEETINGS_STT_* settings
```

## 5. Tests (Phase 2, test-first)

- `align.py` pure-function table: overlap wins, nearest-within-15s, no-caption NULL, empty list.
- `mlx_local` driver with a fake subprocess (JSON contract, timeout kill, non-zero exit).
- `run_transcribe` with a fake provider + fake artifacts: rows written, replace-on-rerun, ready
  status, captions-missing path, failure path marks meeting failed.
- Router: transcript shape, 404 before ready, cross-tenant 404.
- ONE live evidence run (not pytest): run-7 audio + its real events.jsonl through the real
  mlx venv -> named transcript (the UAC gate).

## 6. Out of scope

Minutes (S4), transcript UI (S5), Deepgram driver body, pyannote, live transcript, per-segment
language detection beyond what Whisper emits, search endpoint (index ships, endpoint later).
