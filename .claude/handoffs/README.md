# .claude/handoffs/

Session resume documents written by `/handoff` and read by `/resume-handoff`.

- Filename: `<UTC timestamp>-<slug>.md`, e.g. `20260814T221500Z-form-sla-lock-banner.md`.
  Lexical sort equals chronological sort, so `ls [0-9]*.md | tail -1` is the newest.
  The `[0-9]` matters: a plain `*.md` glob also matches this README, which sorts after
  every timestamp and would win `tail -1`.
- Everything here except this README is **gitignored**. A handoff is transit, not an
  artifact: it must never appear in a feature PR diff.
- The directory is **worktree-local**. A handoff written in another worktree is not
  visible from this one.
- Handoffs are disposable. Anything in one that is still true next month belongs in
  `CLAUDE.md`, the PLAN, or the UAC instead.

See `docs/agents/session-handoff.md` for the ritual, and
`.claude/skills/handoff/SKILL.md` for the document template.
