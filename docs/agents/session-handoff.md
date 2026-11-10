# Session Handoff

How a long agent session survives its context window in this repo.

## The problem with autocompact

Autocompact fires when context fills. It is a lossy summary chosen by the harness at a
moment nobody picked, with no notion of what this repo cares about: which UAC lines are
still unverified, whether :3001 is a dev server or a prod build, which decisions were
made and which alternatives were rejected, what was actually observed versus assumed.
The session keeps going and quietly gets worse - the usual tell is the agent re-deriving
a decision from three hours ago, or asserting a verification it no longer has evidence for.

The replacement is a deliberate cut: write the state down, clear, restore.

## The ritual

```
/handoff [what the next session is for]   -> writes .claude/handoffs/<ts>-<slug>.md
/clear                                    -> user does this; an agent cannot clear itself
/resume-handoff                           -> reads the newest handoff, re-verifies, restates
```

Three commands, two of them typed by the agent's user. **An agent cannot clear its own
conversation**, so the middle step is unavoidably human today. That is the whole reason
this is a ritual rather than a feature - see the open decision below.

- Writing half: `.claude/skills/handoff/SKILL.md` (document template, content rules)
- Reading half: `.claude/skills/resume-handoff/SKILL.md` (restore order, re-verify step)
- Storage: `.claude/handoffs/README.md` (naming, gitignore, worktree-locality)

## When to hand off rather than continue

| Situation | Move |
| --- | --- |
| Context filling on work that is not done | `/handoff` + `/clear` + `/resume-handoff` |
| Phase boundary in `/feature` (Phase 1 signed off, Phase 2 starting) | `/handoff` - the PLAN carries the spec, the handoff carries the state |
| Work moves to another harness, machine or colleague | upstream `/mattpocock-skills:handoff` (temp dir, portable) |
| Forking a side task while keeping this session alive | either; write the doc, hand the path to the second agent |
| Short session, work is finished | nothing - just stop |

**Never run `/compact`.** It is not an alternative to any row above. Compaction is the
lossy summary this whole document exists to replace, and "the session is nearly done"
is a judgement that is wrong often enough to be worth removing as an option. When
context gets tight, write the handoff.

### Unattended agents (firstmate lanes, `--bg`, cron)

An agent with no human at the keyboard cannot do the `/clear` step, so its ritual is
two moves rather than three:

1. `/handoff` - write the document.
2. Report `blocked:` with the document's absolute path.

The supervisor resumes a fresh session from that path, which does the `/resume-handoff`
half. Do not keep working past the handoff hoping to finish: the document was written
against the state at that moment, and every further edit makes it a little more wrong.

## Relationship to `mattpocock-skills:handoff`

The plugin ships `/handoff` already (1.2.3, `skills/productivity/handoff`). It is scoped
to **portability**: it writes to the OS temp directory, and it has no resume counterpart,
because its job is moving work somewhere the current session cannot reach.

That does not fit session continuity. Temp directories are cleared between sessions in
some environments and on reboot in all of them; the path is long, per-OS and easy to
lose; and with no `/resume-handoff` the restore is improvised each time. So this repo
keeps its own pair, and inherits upstream's content discipline verbatim: reference
artifacts instead of copying them, redact secrets, name the skills the next session
should reach for.

Both remain available, and the names cannot collide. Plugin skills are namespaced
`plugin-name:skill-name`, so upstream is `/mattpocock-skills:handoff`. A plugin skill also
answers to its bare name *unless another command already uses it* - this repo's project
skill does, so `/handoff` and `/resume-handoff` are always ours.

One gotcha when editing these: for a **project** skill the command name comes from the
**directory** name, and frontmatter `name` is only the display label. Renaming the
directory renames the command; renaming the frontmatter does not.

## Open decision - WHEN the cut happens (captain picks)

The ritual above is manual: the user notices context is filling and types `/handoff`.
Three arrangements can automate the trigger. **None is implemented.** They are laid out
here so the choice is a decision rather than a default.

### Option A - user ritual at a threshold (what this PR ships)

The user types the three commands when the context indicator crosses a threshold they
pick (say 70%).

- Zero configuration, zero machine-level state, works in every worktree today.
- Nothing fires unexpectedly; the user chooses the cut point, which is the moment they
  understand best.
- Costs discipline. A user absorbed in the work misses the threshold and autocompact
  wins anyway - which is exactly the failure this is meant to prevent.

### Option B - `PreCompact` hook blocks autocompact

A `PreCompact` hook with matcher `auto` exits 2, which **blocks compaction**, and prints
to stderr: "context is full, run /handoff then /clear then /resume-handoff".

- Autocompact genuinely cannot fire. The literal reading of "replace autocompact".
- The block is a hard stop mid-turn. If the user is away, the session is wedged rather
  than degraded, which is worse for unattended lanes (firstmate crewmates, `--bg` agents).
- Would want a matcher-scoped escape hatch (block `auto`, always allow `manual`), and
  probably an env guard so unattended sessions keep compacting.

### Option C - `SessionStart` hook auto-restores after `/clear`

A `SessionStart` hook with matcher `clear` prints the newest `.claude/handoffs/*.md` path
(or its content) to stdout. `SessionStart` is one of the three events whose **stdout is
added as context Claude can see and act on**, so the fresh session opens already knowing
to resume. The user's ritual shrinks from three commands to two.

- Removes the step most likely to be forgotten - the restore, after the context is
  already gone.
- Does not solve the trigger; the user still has to remember `/handoff` before `/clear`.
  Pairs naturally with A or B rather than replacing them.
- Fires on **every** `/clear`, including deliberate ones that want a genuinely empty
  window. Needs a staleness guard (ignore handoffs older than N hours) or it starts
  resurrecting finished work.

### Recommendation

**A now, C next, B only if A demonstrably fails.** A is what this PR ships. C is a small,
reversible addition once the document format has proven itself in real sessions and the
staleness rule is known. B trades a degraded session for a wedged one, which is the wrong
trade for unattended lanes.

Hooks live in `.claude/settings.json` (repo, committed, applies to every contributor) or
`~/.claude/settings.json` (per-machine). B and C are repo-level and belong in the former.
This PR adds neither, and adds no `.claude/settings.json`.

## Related

- `.claude/skills/handoff/SKILL.md`, `.claude/skills/resume-handoff/SKILL.md`
- `.claude/skills/feature/SKILL.md` - the pipeline; "context" row of the skill map
- `CLAUDE.md` - what belongs there instead of in a handoff (facts true next month)
- Hook events reference: https://code.claude.com/docs/en/hooks
