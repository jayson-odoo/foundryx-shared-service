---
name: codex-review
description: Second-opinion code review from a different model family (OpenAI Codex CLI). Runs `codex exec` read-only over the current branch diff and merges the findings with the primary code-review pass. Use in the review step after code-review on risky or large diffs, or when the user asks for a codex/cross-model review.
---

# /codex-review - cross-model second-opinion review

A different model family catches different bug classes. This skill shells out to
the OpenAI Codex CLI for a read-only review of the current diff, then the main
session verifies and merges the findings.

## Preconditions

1. `codex --version` works (installed via `brew install codex`).
2. Authenticated: `codex login status`. If not logged in, STOP and ask the user
   to run `! codex login` (interactive browser flow, uses their ChatGPT
   subscription). Never attempt to log in for them.

## How to run

Determine the diff base (usually `main`, or the merge-base the user names), then:

```bash
codex exec --sandbox read-only --cd <service_backend-or-service_frontend-or-root> \
  "Review the diff between <base> and HEAD in this repository for CORRECTNESS BUGS only:
   logic errors, missing auth/RBAC checks (Depends(get_current_user), require_permission,
   tenant scoping), off-by-one, naive-vs-aware datetime handling (this repo requires
   aware-UTC everywhere - see PRINCIPLES.md Datetimes), broken idempotency,
   post-commit side effects that can raise, data loss, a router doing DB queries
   directly, a module writing to core public tables, cross-tenant leaks (an
   unscoped lookup of a stored user/role/record id).
   Ignore style, formatting, and naming.
   Output one finding per line as: <file>:<line> | <problem> | <suggested fix>.
   If you find nothing, output exactly: NO FINDINGS."
```

- `--sandbox read-only` is mandatory: codex must never write to the tree.
- This repo has two independently-runnable apps (`service_backend/`,
  `service_frontend/`) plus module code under `service_backend/modules/`. For a
  diff spanning both, run from the repo root; for a diff confined to one app or
  one module, `--cd` into that directory so codex reads less.
- Long diffs: run once per app/module rather than one giant pass.
- Timeout generously (5-10 min); codex explores files itself.

## Merging findings

- Treat codex output as CANDIDATE findings, exactly like a low-confidence
  `code-review` pass: verify each against the actual code before reporting. A
  different model family has different false positives, not fewer.
- Dedupe against the primary `code-review` findings; report the union, marking
  which reviewer found what only when the user asks.
- Never let codex findings override this repo's contract: `PRINCIPLES.md`
  hard-fail rules, the Definition of Done gate, and the UAC stay the bar.

## What this skill is NOT

- Not an executor: codex never writes code here. Implementation stays with the
  `coder` agent (Claude), per the `/feature` skill.
- Not a replacement for the built-in `code-review` skill: it is the second
  opinion, run after.
