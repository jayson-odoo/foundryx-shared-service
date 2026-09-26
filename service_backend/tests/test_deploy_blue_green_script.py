"""Issue #89 (prod 26 Sep 2026), W3 - `scripts/blue_green_deploy.sh` regression
guards, run against stub `docker` / `sudo` / `sleep` binaries (no Docker, no
Caddy). Pins the sorento-crm safeguards adopted here:

- the new colour gets a 4-minute health budget and a NAMED abort; an exited
  or restarting new colour aborts at once; the aborted colour is STOPPED;
  Caddy (sudo) is never touched and `.active_color` never flips;
- Celery workers are recreated only after the API colour is healthy and are
  gated on Celery's positive `celery@<host> ready.` line;
- `SKIP_MIGRATIONS=1` is announced.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "blue_green_deploy.sh"

FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
args="$*"
case "$args" in
  *"compose ps -q "*)
    echo "cid_${args##* }"; exit 0 ;;
  *"inspect --format={{.State.Health.Status}} "*)
    cid="${args##* }"
    if [ "$cid" = "cid_backend_green" ]; then echo "$FAKE_BACKEND_HEALTH"; else echo healthy; fi
    exit 0 ;;
  *"inspect --format={{.State.Status}} "*)
    cid="${args##* }"
    if [ "$cid" = "cid_backend_green" ]; then echo "$FAKE_BACKEND_STATUS"; else echo running; fi
    exit 0 ;;
  *"inspect --format={{.RestartCount}} "*)
    echo 0; exit 0 ;;
  "logs "*)
    cid="${args##* }"
    if [ "$cid" != "cid_beat" ] && [ "$FAKE_WORKERS_READY" = "1" ]; then
      echo "[INFO/MainProcess] celery@abc123 ready."
      # A long log after the ready line: a reader that stops at the first
      # match closes the pipe and this writer dies of SIGPIPE (141).
      if [ "$FAKE_LONG_LOGS" = "1" ]; then
        yes "[INFO/MainProcess] Task done in 0.01s" | head -n 200000
        exit $?
      fi
    fi
    exit 0 ;;
esac
exit 0
"""


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path, **env_over):
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    root = tmp_path / "deploy"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "blue_green_deploy.sh")
    (root / ".env").write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    _exe(bin_dir / "docker", FAKE_DOCKER)
    _exe(bin_dir / "sudo", '#!/bin/sh\necho "sudo $*" >> "$FAKE_LOG"\nexit 0\n')
    _exe(bin_dir / "sleep", "#!/bin/sh\nexit 0\n")
    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "IMAGE_TAG": "abc123",
        "APP_DOMAIN": "example.test",
        "TLS_EMAIL": "ops@example.test",
        "CADDY_SITE_FILE": str(tmp_path / "site.caddy"),
        "CADDY_CONFIG": str(tmp_path / "Caddyfile"),
        "DRAIN_SECONDS": "0",
        "FAKE_LOG": str(log),
        "FAKE_BACKEND_HEALTH": "healthy",
        "FAKE_BACKEND_STATUS": "running",
        "FAKE_WORKERS_READY": "1",
        "FAKE_LONG_LOGS": "0",
    }
    env.update(env_over)
    result = subprocess.run(
        ["bash", str(root / "scripts" / "blue_green_deploy.sh")],
        env=env, capture_output=True, text=True, timeout=60,
    )
    active = root / ".active_color"
    return result, log.read_text(), (active.read_text().strip() if active.exists() else None)


def test_the_health_budget_defaults_to_sorento_crms_four_minutes():
    text = SCRIPT.read_text()
    assert 'HEALTH_WAIT_TICKS="${HEALTH_WAIT_TICKS:-120}"' in text
    assert "TICK_SECONDS=2" in text


def test_a_new_colour_that_exits_during_start_aborts_at_once_and_is_stopped(tmp_path):
    result, calls, active = _run(
        tmp_path, FAKE_BACKEND_HEALTH="starting", FAKE_BACKEND_STATUS="exited"
    )
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "DEPLOY ABORTED (backend_green exited during start (status=exited" in out
    assert "Swap NOT performed - blue keeps serving" in out
    assert "stop backend_green frontend_green" in calls
    assert "sudo" not in calls  # Caddy never touched
    assert "--force-recreate" not in calls  # workers never recreated
    assert active is None


def test_a_new_colour_never_healthy_within_budget_aborts_with_a_named_error(tmp_path):
    result, calls, active = _run(
        tmp_path, FAKE_BACKEND_HEALTH="starting", HEALTH_WAIT_TICKS="3"
    )
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "DEPLOY ABORTED (backend_green not healthy after 6s)" in out
    assert "stop backend_green frontend_green" in calls
    assert "sudo" not in calls
    assert "--force-recreate" not in calls
    assert active is None


def test_a_healthy_deploy_swaps_then_recreates_and_gates_workers(tmp_path):
    result, calls, active = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert active == "green"
    # workers recreated only after the swap (Caddy reload) happened
    assert calls.index("sudo caddy reload") < calls.index("--force-recreate")
    for svc in ("worker_workflow", "worker_jobs", "worker_omni"):
        assert f"{svc} ready after" in result.stdout
    assert "beat running (no restarts" in result.stdout


def test_a_worker_that_never_logs_ready_fails_the_deploy_after_the_swap(tmp_path):
    result, calls, active = _run(tmp_path, FAKE_WORKERS_READY="0", WORKER_WAIT_TICKS="2")
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "DEPLOY FAILED AFTER SWAP (worker_workflow did not prove startup" in out
    # old colour left running for rollback: step 7 never reached
    assert "stop backend_blue" not in calls


def test_skip_migrations_is_announced(tmp_path):
    result, _calls, _active = _run(tmp_path, SKIP_MIGRATIONS="1")
    assert "SKIP_MIGRATIONS=1" in result.stdout + result.stderr


def test_compose_passes_the_bootstrap_controls_into_the_backend_env():
    """The compose env block is an allow-list: without these the documented
    SKIP_MIGRATIONS=1 bypass never reached the container."""
    import yaml

    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    env = compose["services"]["backend_green"]["environment"]
    for key in ("SKIP_MIGRATIONS", "BOOTSTRAP_LOCK_TIMEOUT", "BOOTSTRAP_ATTEMPTS", "BOOTSTRAP_RETRY_DELAY"):
        assert key in env, key


def test_a_ready_worker_with_a_long_log_is_not_misread_as_never_ready(tmp_path):
    """Review S3: `docker logs | grep` under `set -o pipefail` can report a
    started worker as not ready when grep stops at the first match and the
    writer dies of SIGPIPE. The gate captures the log first."""
    result, _calls, active = _run(tmp_path, FAKE_LONG_LOGS="1", WORKER_WAIT_TICKS="5")
    assert result.returncode == 0, result.stdout + result.stderr
    assert active == "green"
    assert "worker_workflow ready after" in result.stdout


def test_bootstrap_attempts_fit_the_health_budget():
    """Review S4: start.sh's default retries must fit the 240s budget."""
    start_sh = (REPO / "service_backend" / "start.sh").read_text()
    assert 'BOOTSTRAP_ATTEMPTS="${BOOTSTRAP_ATTEMPTS:-4}"' in start_sh
    assert "BOOTSTRAP_ATTEMPTS: ${BOOTSTRAP_ATTEMPTS:-4}" in (REPO / "docker-compose.yml").read_text()
