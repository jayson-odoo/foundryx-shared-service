---
name: handoff
description: Write a self-contained resume document for the current session to .claude/handoffs/, so a fresh session can pick the work up after /clear. Use before clearing a long session, before swapping harness or machine, or to fork a side task.
argument-hint: "What will the next session be used for?"
disable-model-invocation: true
---

# /handoff - write the resume document

Compress the live session into ONE markdown file under `.claude/handoffs/` that a
fresh session can read cold and continue from. Then the user runs `/clear` and
`/resume-handoff`.

**An agent cannot clear its own conversation.** This skill writes the document and
stops. It never clears, never continues the work "one more step" afterwards, and
never assumes the next session is itself.

## Relationship to `mattpocock-skills:handoff`

Upstream `/mattpocock-skills:handoff` writes to the OS temp directory and has no
resume half - deliberately, because it is scoped to *portability* (moving work to
another harness or colleague). This repo's `/handoff` is scoped to *session
continuity*: replacing autocompact on long sessions in this worktree. Same content
discipline (reference artifacts, never copy them; redact secrets), different
destination and a matching `/resume-handoff`.

Use upstream when the work leaves this checkout. Use this one otherwise.

## Where it goes

```
.claude/handoffs/<UTC timestamp>-<slug>.md
```

Get the timestamp from `date -u +%Y%m%dT%H%M%SZ`. The slug is 2-4 kebab-case words
naming the work (`form-sla-lock-banner`, not `session-2`). Lexical sort equals
chronological sort, so `ls .claude/handoffs/[0-9]*.md | tail -1` is always the newest.
Keep the timestamp first and never name a handoff with a leading letter - the `[0-9]`
glob is what keeps `README.md` (which sorts after every timestamp) out of the result.

`.claude/handoffs/*.md` is gitignored (`README.md` excepted). A handoff is transit,
not an artifact - it must never land in a feature PR diff. If a fact in it deserves
to outlive the work, it belongs in `CLAUDE.md`, the PLAN, or the UAC, not here.

## Content rules

1. **Reference, never copy.** Specs, PLANs, UACs, issues, commits, diffs and code go
   in as paths, line numbers, SHAs and URLs. If the next session can `Read` it, do
   not restate it. The document is a pointer index plus the reasoning that is only
   in the conversation.
2. **Separate verified from assumed.** Anything the session did not actually run,
   read or see goes under "Assumed, not verified" - never in the state section. The
   next session treats this file as a contract and will not re-check it, so a belief
   written as a fact becomes a false premise for everything after it.
3. **Redact secrets.** No API keys, tokens, passwords, connection strings or PII.
4. **Next steps are executable.** "Continue the SLA work" is useless. "Run
   `npx vitest run app/components/.../X.test.tsx`, expect 3 failures on the lock
   banner, fix `resolveHandlingLockState`" is a resume.
5. **Small.** A fraction of the conversation. If it is growing past ~150 lines, the
   detail belongs in the PLAN file instead and the handoff should point at it.

## Template

```markdown
# HANDOFF - <title>

**Written:** <UTC timestamp> | **Session focus next:** <the argument, or "continue">

## Goal
One paragraph. What we are trying to land and why.

## Where the work lives
- Worktree: <absolute path>
- Branch: <name> (base <sha> <subject>)
- Working tree: <clean | N modified, list the files>
- Last commit made this session: <sha or "none">
- PLAN / UAC: <documentation/plans/... paths>
- Issue / PR: <url or "none">

## State - verified
Only what this session actually ran, read or saw in a browser. Bullet each with the
evidence (command output, test name, screenshot, endpoint hit).

## Assumed, not verified
Beliefs the session acted on without checking. The next session re-checks these
before relying on them.

## Decisions made (and why)
The reasoning that exists nowhere but this conversation. Rejected options too - a
decision without its discarded alternatives gets re-litigated. Link to the PLAN's
decision log if one exists rather than duplicating it.

## Next steps
Ordered, executable, with the exact commands. Mark the first one as the resume point.

## Open questions / blocked on
Anything needing a human decision. Name who or what unblocks it.

## Environment
Dev servers this session started, and their mode:
- Backend :8001 <running/not>, Redis <running/not>, FE :3001 <dev | prod build | not>, isolated lane ports :8002/:3002 <running/not>
Note anything non-default (env vars set, seeded rows, a scratch DB).

## Suggested skills
Which skills the next session should reach for (`/feature` step N, `/code-review`,
`/tdd`, ...) and why.

## Traps
Repo gotchas that bit this session. If one is durable and general, also add it to
CLAUDE.md (the relevant engine section) in the same pass - the handoff dies, CLAUDE.md does not.
```

## Procedure

1. Run `git status --short`, `git log --oneline -1`, `git rev-parse --abbrev-ref HEAD`
   and `lsof -i :3001 -i :8001 -i :3002 -i :8002 -sTCP:LISTEN` so the state section is observed,
   not remembered.
2. Fill the template. Sort every claim into "verified" or "assumed" as you write it.
3. Write the file. `mkdir -p .claude/handoffs` first - the directory is committed via
   its README, but a fresh worktree may not have it yet.
4. Print the absolute path back to the user, and tell them the next two moves are
   `/clear` then `/resume-handoff`. If there is no human at the keyboard (a firstmate
   lane, `--bg`, cron), report `blocked:` with that absolute path instead - the
   supervisor resumes a fresh session from it.

Then stop. **Never run `/compact`** - not before writing the document, not instead of
it, and not to buy room to keep going afterwards.
