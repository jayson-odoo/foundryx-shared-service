"""SS-DEPLOY-SKIP-STALE (5 Nov 2026) - a queued deploy of an OLDER sha must
never roll prod back over a newer one.

Incident: #209 #210 #211 #170 merged within a minute. c748c240 (#170, newest)
deployed first; cf831cb0 (older) finished its tests later and its queued
deploy job ran AFTER, rolling prod back to a sha without #170.

Two guards, red-first:
1. Workflow: right before the host steps, the job fetches origin/main and
   SKIPS (exit 0) when github.sha is not main's head - unless a
   workflow_dispatch run sets the `force_sha` input on purpose.
2. Host: inside the flock (the pre-check is racy), blue_green_deploy.sh skips
   when the running backend's GIT_SHA is a commit newer than IMAGE_TAG on
   main (the CI passes that list as DEPLOY_NEWER_SHAS).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_deploy_blue_green_script import REPO, _run

GUARD = REPO / "scripts" / "deploy_head_guard.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy.yml"

OLD = "cf831cb0" + "0" * 32
HEAD = "c748c240" + "0" * 32


def _guard(tmp_path, sha, head, force=""):
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    out_file = tmp_path / "gh_output"
    out_file.write_text("")
    env = {"PATH": os.environ.get("PATH", ""), "GITHUB_OUTPUT": str(out_file)}
    result = subprocess.run(
        ["bash", str(GUARD), sha, head, force],
        env=env, capture_output=True, text=True, timeout=30,
    )
    return result, out_file.read_text()


# ---- 1. pre-check: the guard script ------------------------------------

def test_a_sha_older_than_main_head_skips_with_a_clear_line(tmp_path):
    result, outputs = _guard(tmp_path, OLD, HEAD)
    assert result.returncode == 0, result.stderr  # a skip is NOT a failed run
    assert f"skip: {OLD} is not main head {HEAD}; newer deploy owns prod" in result.stdout
    assert "skip=true" in outputs


def test_the_main_head_sha_deploys(tmp_path):
    result, outputs = _guard(tmp_path, HEAD, HEAD)
    assert result.returncode == 0, result.stderr
    assert "skip=false" in outputs
    assert "skip:" not in result.stdout


def test_a_dispatch_with_force_sha_deploys_an_older_sha_on_purpose(tmp_path):
    result, outputs = _guard(tmp_path, OLD, HEAD, "true")
    assert result.returncode == 0, result.stderr
    assert "skip=false" in outputs
    assert "force_sha" in result.stdout  # says loudly it bypassed the check


def test_an_unknown_main_head_fails_loudly_instead_of_deploying_blind(tmp_path):
    result, _ = _guard(tmp_path, HEAD, "")
    assert result.returncode != 0


# ---- 1b. the workflow wires it -----------------------------------------

@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(WORKFLOW.read_text())


def test_workflow_dispatch_has_a_force_sha_boolean_input(wf):
    on = wf.get("on") or wf.get(True)  # PyYAML reads the bare `on` key as True
    inp = on["workflow_dispatch"]["inputs"]["force_sha"]
    assert inp["type"] == "boolean"
    assert inp["default"] is False


def test_the_head_check_runs_before_any_host_step_and_gates_them(wf):
    steps = wf["jobs"]["build-and-deploy"]["steps"]
    names = [s.get("name", "") for s in steps]
    idx = next(i for i, n in enumerate(names) if n.startswith("Skip if not main head"))
    check = steps[idx]
    assert check["id"] == "head"
    assert "git fetch" in check["run"] and "origin" in check["run"]
    assert "scripts/deploy_head_guard.sh" in check["run"]
    assert "inputs.force_sha" in check["run"] or "inputs.force_sha" in str(check.get("env"))
    for prefix in ("Sync compose", "Deploy blue/green", "Verify public endpoints"):
        j = next(i for i, n in enumerate(names) if n.startswith(prefix))
        assert j > idx, f"{prefix} must run after the head check"
        assert "steps.head.outputs.skip != 'true'" in steps[j].get("if", ""), prefix
    # The host lock and the queue stay.
    assert wf["jobs"]["build-and-deploy"]["concurrency"]["cancel-in-progress"] is False


def test_the_deploy_step_passes_the_newer_list_and_force_to_the_host(wf):
    steps = wf["jobs"]["build-and-deploy"]["steps"]
    deploy = next(s for s in steps if s.get("name", "").startswith("Deploy blue/green"))
    cmd = deploy["with"]["command"]
    assert "git rev-list" in cmd and "origin/main" in cmd
    assert "DEPLOY_NEWER_SHAS=" in cmd
    assert "DEPLOY_FORCE=" in cmd
    # The retry action runs `bash -c` WITHOUT -e: a failed ssh deploy must
    # still fail the step (and retry), not be masked by the skip grep after it.
    assert "set -eo pipefail" in cmd
    assert cmd.index("set -eo pipefail") < cmd.index("blue_green_deploy.sh")
    assert deploy["with"]["shell"] == "bash"
    assert "grep -qx 'DEPLOY_SKIPPED_STALE_SHA'" in cmd
    assert "--max-count" not in cmd  # a cap could drop the running sha from the list
    verify = next(s for s in steps if s.get("name", "").startswith("Verify public endpoints"))
    assert "env.DEPLOY_SKIPPED != '1'" in verify["if"]


# ---- 2. in-lock re-check in blue_green_deploy.sh -----------------------

def test_inside_the_lock_a_newer_running_sha_skips_the_deploy(tmp_path):
    result, calls, active = _run(
        tmp_path, IMAGE_TAG=OLD, FAKE_RUNNING_SHA=HEAD, DEPLOY_NEWER_SHAS=f"{HEAD} deadbeef"
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert f"skip: {OLD} is older than the running {HEAD}; newer deploy owns prod" in out
    assert "DEPLOY_SKIPPED_STALE_SHA" in result.stdout.splitlines()
    assert "pull" not in calls and "up -d" not in calls and "sudo" not in calls
    assert active is None  # .active_color untouched


def test_inside_the_lock_the_check_runs_after_the_flock(tmp_path):
    text = (REPO / "scripts" / "blue_green_deploy.sh").read_text()
    assert text.index("flock -w") < text.index("DEPLOY_NEWER_SHAS") < text.index("docker compose --profile \"${NEW}\" pull")


def test_inside_the_lock_an_older_or_same_running_sha_deploys(tmp_path):
    # running = the sha being redeployed (a retry) -> not newer -> deploy,
    # even with a non-empty list (the list never names IMAGE_TAG itself, but
    # a same-sha redeploy must not skip regardless)
    result, calls, active = _run(
        tmp_path, IMAGE_TAG=HEAD, FAKE_RUNNING_SHA=HEAD, DEPLOY_NEWER_SHAS=f"{HEAD} {OLD}"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert active == "green"
    # running = an older sha -> deploy
    result, calls, active = _run(
        tmp_path / "b", IMAGE_TAG=HEAD, FAKE_RUNNING_SHA=OLD, DEPLOY_NEWER_SHAS=""
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert active == "green"


def test_inside_the_lock_force_deploys_over_a_newer_running_sha(tmp_path):
    result, calls, active = _run(
        tmp_path, IMAGE_TAG=OLD, FAKE_RUNNING_SHA=HEAD, DEPLOY_NEWER_SHAS=HEAD, DEPLOY_FORCE="1"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert active == "green"
    assert "skip:" not in result.stdout
    assert "DEPLOY_SKIPPED_STALE_SHA" not in result.stdout


def test_a_failed_deploy_never_prints_the_skip_marker(tmp_path):
    result, calls, active = _run(
        tmp_path, IMAGE_TAG=OLD, FAKE_RUNNING_SHA="", DEPLOY_NEWER_SHAS=HEAD,
        FAKE_BACKEND_HEALTH="starting", FAKE_BACKEND_STATUS="exited",
    )
    assert result.returncode != 0
    assert "DEPLOY_SKIPPED_STALE_SHA" not in result.stdout


def test_a_partial_sha_in_the_list_never_matches_by_prefix(tmp_path):
    # running sha must match a list entry exactly (no substring tricks)
    result, calls, active = _run(
        tmp_path, IMAGE_TAG=OLD, FAKE_RUNNING_SHA="c748", DEPLOY_NEWER_SHAS=HEAD
    )
    assert result.returncode == 0
    assert active == "green"
