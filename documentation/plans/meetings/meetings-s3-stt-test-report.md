# Test report - Meetings S3: STT

Date: 2026-09-01. Branch `sprint-5/meetings-s3-stt`. Evidence meeting: kuo-ydrw-gmg (the first
fully unattended pilot capture, 134 s, single speaker), on the live pilot stack
(`foundryx_meetings_pilot` DB, Mac Mini, mlx venv `~/foundryx-stt/venv`).

## Automated

- Backend full suite: 2659 passed, 1 skipped, 0 failed (24m49s).
- Meetings-scoped: 193 passed (S3 + review round + align monologue fix).
- Frontend meetings-scoped vitest: 26 passed.
- Phase 3 review (Opus): 2 blockers, 8 should-fixes, 11 nits - ALL applied except B2, which is
  this evidence run. Red-first verified on the behavioral fixes.

## Live evidence run (AC references)

| Check | Result |
|---|---|
| AC-S3-1 rows + `transcribed` | PASS - 16 segments, all `start_ms < end_ms`, non-empty text; meeting `transcribed` |
| AC-S3-2 names from captions | PASS after the monologue fix - 16/16 segments `Teh Jayson` (single caption block flushed at leave; first-caption span now starts at recording start). First run under the pre-fix rule produced 0 names - the caption landed 15.13 s after the last segment, 130 ms outside the nearest window - which motivated the amendment to plan 3.2 |
| AC-S3-5 warm wall clock | PASS - 134 s audio in 11.6 s (first run) / 9.5 s (re-run); no trailing-silence hallucination |
| AC-S3-6 1 h under 15 min (gate amended 2026-09-01, was 5 min - captain's ruling with the non-turbo model flip) | PASS by rate - non-turbo chunked runner measured 5.5x realtime live (396.7s audio in 72.7s, ~11 min per audio hour; direct 1 h sample still pending a long real meeting). The earlier ~11-14x figure was the turbo model this branch replaces |
| AC-S3-7 mixed language | PASS (2026-09-01, code-switch fold-in branch, see section below) - chunked runner re-run on the same ytp-scai-bob recording: 29 segments all named, per-segment language en/ms/zh, Chinese and Malay passages verbatim in their own script, transcribeMs 72.7s. The original single-pass run (this row's earlier PARTIAL/FAIL) locked language=en and garbled them |
| AC-S3-8 read endpoint | PASS - participant GET 200 with camelCase shape; the pre-restart 404 proved the route is really version-gated by deploy, not a stub |
| AC-S3-9 replace-on-rerun | PASS live - second run replaced the first, exactly 16 rows |
| AC-S3-12 flock | unit-tested (real fcntl, two threads); not exercised live with two concurrent jobs |
| AC-S3-13 venv script | script idempotency unit-shaped; not run against a wiped host yet |

Transcript quality: Whisper output clearly beats the Meet caption text on the same speech
(punctuation, structure, fewer fillers), confirming the M12 choice.

## Also proven live today (S2 scope, same session)

Unattended calendar -> dispatch -> join -> record -> register chain; `missed` skip; failure
screenshots; the three S2 defects (calendar_email matching, Singleton locks, dead-container
re-attach) each reproduced live before being fixed.

## Open

- AC-S3-7: CLOSED 2026-09-01 by the code-switch fold-in (section below).
- A true 1 h recording for a direct AC-S3-6 measurement.

## Code-switch fold-in re-run (2026-09-01, branch `sprint-5/meetings-s3-codeswitch`)

The chunked runner (plan section 8) was folded in and re-run live against the same
ytp-scai-bob recording (396.7s), meeting 734759ad, job bbedf3ac:

- 29 `transcript_segments`, all speaker-named, `language` populated per segment (en/ms/zh -
  R3 as amended); Chinese passages verbatim (e.g. segment at 62s), Malay verbatim
  (e.g. 120-142s); meeting `language` = `en` (majority chunk language).
- `transcribeMs` 72726 (72.7s); direct CLI timing 75.4s cold. About 11 min per audio hour
  on this host with the pilot stack running.
- Replace-on-rerun held across three runs (16 -> 28 -> 29 rows, one transcript row each time).
- Two defects found live during fold-in, both fixed on the branch:
  1. ffprobe flag typo `noprint_wrapper` (correct: `noprint_wrappers`) failed the first
     chunked job instantly; replaced with the eval-proven `csv=p=0`. The mlx/ffmpeg-touching
     helpers have no unit coverage (they need the STT venv), which is exactly where the typo
     hid - the live run is their test.
  2. The detection model was loaded via `load_models.load_model` (float32) while
     `mlx_whisper.transcribe` cached its own fp16 copy: two large-v3 copies swap-thrashed the
     16 GB host and the first successful job took transcribeMs 1503977 (25 min). Sharing
     `ModelHolder.get_model(model, mx.float16)` dropped it to 72.7s (20x).
- Meetings-scoped pytest after fold-in: 215 passed (16 new runner-helper tests included).
