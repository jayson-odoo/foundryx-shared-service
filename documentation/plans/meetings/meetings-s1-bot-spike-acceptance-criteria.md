# Meetings S1 - Bot spike: Acceptance Criteria (UAC)

**Status:** contract, pre-build. Written FIRST per PRINCIPLES (UAC -> plan -> build).
**Scope:** `foundryx-shared-service` only. Throwaway code allowed; the gate is a recorded evidence run, not a PR.
**Goal:** prove the one unknown in the program: a container we own can join a real Google Meet as a tenant-domain notetaker account, record the audio, and leave when the room empties. Spine: `PLAN-meetings-program.md` (M2, M5, M9, M10).

Preconditions (human, before the spike starts): a `notetaker@foundryx.my` Workspace account exists in a 2SV-exempt OU; five test Meets are scheduled in the FoundryX calendar over the week.

---

## A. Join

**AC-S1-1** - Given a Meet URL hosted by a FoundryX user and the notetaker credentials, when the container starts, then within 90 s the bot is a participant in the Meet with display name `Notetaker (for <user>)`, with mic and camera off, and no human clicked Admit.

**AC-S1-2** - Given the same, when the bot has joined, then a chat message with the consent text is posted within 10 s of joining.

**AC-S1-3** - Given a Meet hosted by an external (non-FoundryX) Google account, when the container starts, then the bot waits in the lobby and exits with reason `not_admitted` after 3 min if nobody admits it, and exits with reason `joined` if admitted.

**AC-S1-4** - Given the Chromium profile volume persisted from a previous run, when the container starts, then no login screen is shown (session reused). Given the session has expired, then the bot logs in with the stored password and the run proceeds.

## B. Record

**AC-S1-5** - Given the bot is in the meeting and one human speaks, when the run ends, then the storage bucket holds 60 s audio chunks (`opus` or `wav`) for the whole time the bot was in the room, and playing them back the speech is intelligible.

**AC-S1-6** - Given two humans in the meeting, when the run ends, then an `events.jsonl` file exists alongside the chunks with `active_speaker` entries (display name + timestamp) that align with who spoke, sampled at least once per second.

## C. Leave

**AC-S1-7** - Given the bot is recording, when every human participant leaves, then the bot leaves within 60 s and the container exits 0 with reason `room_empty`.

**AC-S1-8** - Given the bot is recording, when the host removes the bot, then the container exits 0 with reason `removed` and the chunks recorded so far are kept.

**AC-S1-9** - Given any failure (login rejected, join button not found, Chromium crash), when it happens, then the container exits non-zero with a one-line reason and the last screenshot saved to storage.

## D. Gate

**AC-S1-10** - Five scheduled FoundryX Meets across the week: 5 of 5 satisfy AC-S1-1, AC-S1-5 and AC-S1-7. Evidence = the five chunk sets + a one-page spike report (`meetings-s1-bot-spike-test-report.md`) with what broke and what selectors the join path depends on.

**AC-S1-11** - Every run records peak container memory and CPU (`stats.log`); the report states the peak per run and whether headless (`--headless=new`) worked or the Xvfb fallback was needed. No threshold in S1; the number sizes the bot VM in S2.

Defer-items discovered during the spike go to `documentation/backlogs/backlog.md`.
