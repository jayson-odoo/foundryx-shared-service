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
| AC-S3-6 1 h under 5 min | PASS by rate - measured ~11-14x realtime on this hardware (direct 1 h sample pending a long real meeting) |
| AC-S3-7 mixed language | PARTIAL/FAIL - second live meeting (ytp-scai-bob, ~6.5 min, 37 segments all named, 55.8s wall): English passages clean, but Whisper locked language=en for the file and rendered the Malay/Chinese passages as garbled English-ish text instead of their own language. Follow-up: per-chunk language handling or non-turbo large-v3 |
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

- AC-S3-7: code-switch quality - evaluate per-chunk language detection or large-v3 (non-turbo)
  against the ytp-scai-bob recording before calling this closed.
- A true 1 h recording for a direct AC-S3-6 measurement.
