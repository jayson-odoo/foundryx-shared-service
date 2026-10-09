---
name: resume-handoff
description: Restore a cleared session from the newest .claude/handoffs/ document - read it, re-read the files it points at, re-verify its assumptions, then restate the plan before touching anything. Use at the start of a fresh session that is continuing earlier work, or when the user says resume, pick up where we left off, or continue from the handoff.
argument-hint: "optional path or slug of the handoff to resume"
---

# /resume-handoff - restore from the resume document

The other half of `/handoff`. Turns a cold session back into a working one.

## Pick the document

- Argument is a path -> use it.
- Argument is a slug -> `ls .claude/handoffs/[0-9]*<slug>*.md`, newest match.
- No argument -> `ls .claude/handoffs/[0-9]*.md | tail -1` (timestamped names sort
  chronologically). If more than one is recent, list them with their titles and ask
  which - do NOT guess.
- The `[0-9]` prefix is load-bearing: a plain `*.md` glob matches `README.md`, which
  sorts AFTER every timestamp (`2` < `R`) and so wins `tail -1` every time.
- Nothing there -> say so and stop. Do not invent the prior session's state.

## Restore, in this order

1. **Read the handoff in full.** Do not skim.
2. **Read what it points at.** The PLAN, the UAC, the changed files, the issue or PR.
   The handoff is an index; the artifacts are the content. A resume that reads only
   the summary is working from a secondary source.
3. **Re-observe the environment.** Do not trust the handoff's Environment section -
   it describes the moment it was written.
   ```bash
   git status --short && git log --oneline -3
   lsof -i :3001 -i :8001 -i :3002 -i :8002 -sTCP:LISTEN; redis-cli ping
   ```
   Boot whatever is missing per CLAUDE.md "Commands". If the tree diverged from
   the handoff's description (new commits, unexpected modified files - the user codes
   concurrently in the main checkout), say so before doing anything else.
4. **Re-check the "Assumed, not verified" list.** Each item is a false-premise
   candidate. Verify it or explicitly carry it forward as still-unverified. This step
   is the whole reason the section exists - skipping it silently promotes guesses to
   facts.
5. **Restate the plan.** Four to eight lines: the goal, where the work stands, the
   first action, and anything that moved since the handoff was written. Then start
   at the marked resume point.

## Rules

- **Never edit the handoff file.** It is a snapshot of a session that has ended. If
  the state has moved on enough to matter, write a fresh `/handoff`.
- **Stale handoffs are suspect.** If the newest one predates commits on the branch,
  treat its state section as assumed rather than verified, and say so.
- **The handoff is not authority over the repo.** Where it contradicts `PRINCIPLES.md`,
  `CLAUDE.md`, the PLAN or the UAC, those win and the contradiction gets flagged.
- Handoffs are worktree-local and gitignored. A handoff written in another worktree
  is not visible here - ask for the path.

## Related

- `.claude/skills/handoff/SKILL.md` - the writing half
- `docs/agents/session-handoff.md` - the ritual and the open harness decision
