# UAC - Meetings S3: STT

Plan: `PLAN-meetings-s3-stt.md`. Spine gate: 1 h audio -> transcript in under 15 min (amended 2026-09-01, see AC-S3-6); mixed-language
meeting transcribed.

**AC-S3-1** - Given a meeting with a registered `recording.ogg` and an `events.jsonl` containing
caption events, when `meetings.transcribe` runs, then one `transcripts` row and its
`transcript_segments` rows exist, every segment has `start_ms < end_ms` and non-empty `text`, and
the meeting status is `transcribed`.

**AC-S3-2** - Given the caption timeline names a speaker for the span a Whisper segment covers,
when alignment runs, then that segment's `speaker` is the caption's display name; a segment no
caption covers (none within 15 s) has `speaker = NULL`, never a guessed or copied name.

**AC-S3-3** - Given `events.jsonl` is missing or contains no caption events, when the job runs,
then the transcript is still produced with all speakers NULL, the job log says captions were
absent, and the meeting still reaches `transcribed`.

**AC-S3-4** - Given transcription fails (subprocess non-zero, timeout, unreadable audio), when the
job finishes, then the job is `FAILED`, `meeting.status = failed`, the error is in the job log,
and re-running the job after the cause is fixed produces a transcript (replace-on-rerun leaves no
duplicate rows).

**AC-S3-5** - Given the pilot host, when the run-7 evidence audio (49 s) is transcribed through
the real mlx venv, then the wall time is under 60 s warm and the text quality is at least the
S1-report baseline (no trailing-silence hallucination).

**AC-S3-6** - Given a ~1 h recording, when transcribed on the pilot host, then the transcript
lands in under 15 minutes. AMENDED 2026-09-01 (captain's ruling, was "under 5 minutes"): the
code-switch fix flipped the model to non-turbo large-v3, measured ~11 min per audio hour
(5.5x realtime, live). Accepted because transcription is a background job, flock-serialized,
nothing user-facing waits on it, and M12 already names GPU/Modal as the escalation when
volume demands speed.

**AC-S3-7** - Given a meeting whose speech mixes languages (the spine names Malay / English /
Chinese), when transcribed, then each spoken passage appears in its own language in the segment
TEXT (no wholesale translation into one language); `transcript_segments.language` carries the
REAL per-chunk detected language (from an `{en, ms, zh}` allowlist), and `meeting.language`
(transcript-level) is the majority chunk language, ties broken by first occurrence. **2026-09-01:
amended** - R3 originally said `transcript_segments.language` stays NULL because a single-pass
provider only ever detects language once for the whole file; the chunked runner detects language
PER CHUNK, so the value is now real measured data, not a guess, and is populated.

**AC-S3-8** - Given a user with `meetings.view` in the meeting's tenant, when they GET
`/meetings/{id}/transcript` once `transcribed`, then they receive provider, model, language and
the ordered segments; before that the endpoint 404s; a user from another tenant 404s always.

**AC-S3-9** - Given a re-run of `meetings.transcribe` on a meeting that already has a transcript,
when it completes, then exactly one `transcripts` row exists for the meeting (the new one).

**AC-S3-10** - Given the settings name a provider that is not built (`deepgram`), when the job
runs, then it fails loudly naming the unbuilt provider - it does not silently fall back to
`mlx_local`.

**AC-S3-11** - Given a meeting in `transcribed`, when the meetings list / bot-runs surfaces render
it, then the badge reads "Transcript ready" and is distinct from `ready` (which stays reserved
for minutes, S4).

**AC-S3-12** - Given two transcribe jobs due at once on one host, when they run, then the second
waits for the first's flock - at no point do two mlx subprocesses run concurrently (R1).

**AC-S3-13** - Given a fresh host (or a wiped `~/foundryx-stt`), when `scripts/setup_stt_venv.sh`
runs, then the venv exists with mlx-whisper pinned and a re-run is a no-op (R6).

**Evidence run (stands in for a live browser run - no UI in this slice):** one real gate-meeting
recording processed end-to-end on the pilot stack (bot -> recording -> transcribe -> named
transcript via the read endpoint), attached to the test report as
`meetings-s3-stt-test-report.md`.
