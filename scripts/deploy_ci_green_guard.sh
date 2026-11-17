#!/usr/bin/env bash
# SS-DEPLOY-SKIP-TESTS: may a release skip the test jobs for this sha?
#
#   deploy_ci_green_guard.sh <sha>
#
# A workflow_dispatch release with the `skip_tests` input ticked does NOT
# re-run the six CI gate jobs (about 18 hosted minutes). That is only safe
# when the EXACT sha being deployed already passed every one of them in an
# earlier run (normally the push-to-main run after the merge). This script
# asks the GitHub API for that sha's check runs and passes only when, for
# every required gate, the newest non-skipped check run concluded "success".
#
#   - skipped runs are ignored (a previous skip_tests release leaves skipped
#     check runs behind; they prove nothing either way)
#   - the NEWEST attempt counts: a gate that passed once and then failed on
#     a re-run is red
#   - a gate still running (no conclusion yet) is not green
#   - an API error is a failure: never deploy untested code blind
#
# Needs: GH_TOKEN (checks: read) and GH_REPO or GITHUB_REPOSITORY (owner/repo).
# Exit 0 = green, deploy may go on; exit 1 = refuse, with a ::error:: line
# naming each gate that is not green.
set -euo pipefail

SHA="${1:-}"
REPO="${GH_REPO:-${GITHUB_REPOSITORY:-}}"

# The six CI gate jobs of .github/workflows/deploy.yml, by their `name:`
# (a job's check run carries that name). Pinned against the workflow by
# service_backend/tests/test_deploy_skip_tests.py.
REQUIRED=(
  "Single alembic head per module (fast gate)"
  "Lint conventions (no emdash, brand spelling)"
  "Validate backend (import + pytest collect)"
  "Validate frontend (next build)"
  "Test backend (pytest)"
  "Test frontend (lint + vitest)"
)

if [ -z "$SHA" ] || [ -z "$REPO" ]; then
  echo "::error::skip_tests: sha='${SHA}' repo='${REPO}' - cannot look up CI results; not deploying (dispatch again without skip_tests)" >&2
  exit 1
fi

# One TSV line per check run: name, conclusion ("" while running), started_at.
if ! RUNS=$(gh api --paginate "repos/${REPO}/commits/${SHA}/check-runs?per_page=100" \
    --jq '.check_runs[] | select(.app.slug == "github-actions") | [.name, (.conclusion // ""), (.started_at // "")] | @tsv'); then
  echo "::error::skip_tests: could not read the check runs of ${SHA} from the GitHub API; not deploying (dispatch again without skip_tests)" >&2
  exit 1
fi

missing=0
for name in "${REQUIRED[@]}"; do
  # Newest non-skipped attempt of this gate (ISO timestamps sort as text).
  latest=$(printf '%s\n' "$RUNS" \
    | awk -F'\t' -v n="$name" '$1 == n && $2 != "skipped"' \
    | sort -t$'\t' -k3,3 | tail -n 1 | cut -f2)
  if [ "$latest" = "success" ]; then
    echo "green: ${name}"
  else
    echo "::error::skip_tests: '${name}' has no green run on ${SHA} (latest: ${latest:-none})" >&2
    missing=1
  fi
done

if [ "$missing" -ne 0 ]; then
  echo "::error::skip_tests refused: ${SHA} has no complete green CI run. Wait for main's CI on this sha to pass, or dispatch again without skip_tests to run the tests now. Nothing was built or deployed." >&2
  exit 1
fi

echo "skip_tests: every CI gate is green on ${SHA}; deploying without re-running them"
