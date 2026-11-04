"""SS-DEPLOY-LOCK-SHA (4 Nov 2026) - two prod-safety guards, red-first.

1. Two `main` pushes a minute apart ran two blue/green deploys at once (both
   read the same `.active_color` and brought up the same standby colour). The
   workflow now queues deploys (`concurrency: deploy-prod`, never cancelled
   mid-switch) and `scripts/blue_green_deploy.sh` takes a host-side `flock` on
   a fixed lock file, so a manual run cannot overlap a CI run either. A deploy
   that cannot get the lock in time fails LOUDLY and touches nothing.
2. `/be/health` returned `git_sha: null` in prod: the deploy never set
   `GIT_SHA`. Every backend-image container (API colours + Celery workers +
   beat) now gets `GIT_SHA=${IMAGE_TAG}` (the full commit the script exports).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_deploy_blue_green_script import SCRIPT, _run

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "deploy.yml"
COMPOSE = REPO / "docker-compose.yml"


# ---- 1a. workflow-level concurrency -------------------------------------

def test_deploy_workflow_queues_prod_deploys_and_never_cancels_one_mid_switch():
    wf = yaml.safe_load(WORKFLOW.read_text())
    deploy = wf["jobs"]["build-and-deploy"]
    conc = deploy.get("concurrency") or wf.get("concurrency")
    assert conc, "build-and-deploy must carry a concurrency group"
    assert conc["group"] == "deploy-prod"
    assert conc["cancel-in-progress"] is False


# ---- 1b. host-side flock in blue_green_deploy.sh ------------------------

def test_a_second_deploy_waits_for_the_lock_then_fails_loudly_without_touching_anything(tmp_path):
    if not shutil_which("flock"):
        pytest.skip("flock not available")
    lock = tmp_path / "held.lock"
    lock.write_text("pid=4242 image_tag=olderdeploy\n")
    # Hold the lock in a separate process for the whole run (a concurrent deploy).
    holder = subprocess.Popen(["flock", str(lock), "sh", "-c", "sleep 30"])
    try:
        _wait_until_locked(lock)
        result, calls, active = _run(
            tmp_path, DEPLOY_LOCK_FILE=str(lock), DEPLOY_LOCK_TIMEOUT_SECONDS="1"
        )
    finally:
        holder.kill()
        holder.wait()
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "DEPLOY ABORTED (another blue/green deploy holds" in out
    assert str(lock) in out
    assert "olderdeploy" in out  # names the holder it waited on
    assert calls == ""  # no docker / sudo call at all: nothing pulled, started or swapped
    assert active is None


def test_a_deploy_takes_and_releases_the_lock(tmp_path):
    lock = tmp_path / "deploy.lock"
    result, calls, active = _run(tmp_path, DEPLOY_LOCK_FILE=str(lock))
    assert result.returncode == 0, result.stdout + result.stderr
    assert active == "green"
    assert "image_tag=abc123" in lock.read_text()  # holder recorded for the next waiter
    # Released on exit: a non-blocking take now succeeds.
    assert subprocess.run(["flock", "-n", str(lock), "true"]).returncode == 0


def test_the_default_lock_is_a_fixed_file_in_the_deploy_dir_with_a_bounded_wait():
    text = SCRIPT.read_text()
    assert 'DEPLOY_LOCK_FILE="${DEPLOY_LOCK_FILE:-.blue_green_deploy.lock}"' in text
    assert 'DEPLOY_LOCK_TIMEOUT_SECONDS="${DEPLOY_LOCK_TIMEOUT_SECONDS:-900}"' in text
    # The lock is taken before the active colour is read (the race this closes).
    assert text.index("flock -w") < text.index("ACTIVE=$(cat .active_color")


# ---- 2. GIT_SHA reaches every backend-image container -------------------

@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text())


@pytest.mark.parametrize(
    "svc",
    ["backend_blue", "backend_green", "worker_workflow", "worker_jobs", "worker_omni", "beat"],
)
def test_backend_image_containers_get_git_sha_from_the_deployed_image_tag(compose, svc):
    env = compose["services"][svc]["environment"]
    assert env.get("GIT_SHA") == "${IMAGE_TAG:-}"


def test_the_deploy_script_exports_the_image_tag_compose_interpolates():
    assert "export IMAGE_TAG" in SCRIPT.read_text()


# ---- helpers ------------------------------------------------------------

def shutil_which(name: str):
    import shutil

    return shutil.which(name)


def _wait_until_locked(lock: Path) -> None:
    import time

    for _ in range(100):
        if subprocess.run(["flock", "-n", str(lock), "true"]).returncode != 0:
            return
        time.sleep(0.05)
    raise AssertionError("holder never took the lock")
