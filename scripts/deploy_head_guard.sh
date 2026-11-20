#!/usr/bin/env bash
# SS-DEPLOY-SKIP-STALE: decide whether this CI run may deploy its sha.
#
#   deploy_head_guard.sh <sha> <main_head> [force]
#
# Deploys are queued (concurrency: deploy-prod, never cancelled), so a run for
# an OLDER main commit can reach the deploy step after a newer one already
# shipped and roll prod back (5 Nov 2026: cf831cb0 deployed over c748c240).
# Rule: deploy only when <sha> IS origin/main's head; otherwise skip (exit 0,
# a skip is not a failure). force=true (workflow_dispatch input `force_sha`)
# deploys <sha> on purpose, e.g. a rollback.
#
# Writes skip=true|false to $GITHUB_OUTPUT. An empty head (fetch failed) is a
# loud failure: never deploy blind.
set -euo pipefail

SHA="${1:-}"
HEAD="${2:-}"
FORCE="${3:-}"
OUT="${GITHUB_OUTPUT:-/dev/null}"

if [ -z "$SHA" ] || [ -z "$HEAD" ]; then
  echo "::error::deploy head guard: sha='${SHA}' main head='${HEAD}' - could not read origin/main; not deploying blind (re-run, or dispatch with force_sha)" >&2
  exit 1
fi

if [ "$FORCE" = "true" ]; then
  echo "::warning::force_sha=true - deploying ${SHA} on purpose (main head is ${HEAD}); head check bypassed"
  echo "skip=false" >> "$OUT"
  exit 0
fi

if [ "$SHA" != "$HEAD" ]; then
  echo "skip: ${SHA} is not main head ${HEAD}; newer deploy owns prod"
  echo "::notice::skip: ${SHA} is not main head ${HEAD}; newer deploy owns prod"
  echo "skip=true" >> "$OUT"
  exit 0
fi

echo "deploy: ${SHA} is main head"
echo "skip=false" >> "$OUT"
