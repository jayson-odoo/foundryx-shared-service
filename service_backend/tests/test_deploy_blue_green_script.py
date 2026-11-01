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
  *"compose up -d db pgbackups"*)
    if [ -n "$FAKE_DB_FAIL_MSG" ] && [ ! -e "$FAKE_LOG.db_failed" ]; then
      touch "$FAKE_LOG.db_failed"; echo "$FAKE_DB_FAIL_MSG" >&2; exit 1
    fi
    exit 0 ;;
  *"compose up -d --no-recreate redis"*)
    if [ -n "$FAKE_REDIS_FAIL_MSG" ] && [ ! -e "$FAKE_LOG.redis_failed" ]; then
      touch "$FAKE_LOG.redis_failed"; echo "$FAKE_REDIS_FAIL_MSG" >&2; exit 1
    fi
    exit 0 ;;
  *"compose exec"*"redis-cli ping"*)
    # Plan 39: auth is honoured ONLY when the exec forwards it with
    # `-e REDISCLI_AUTH` (a real container sees no host env otherwise), AND the
    # env var is set. Never echo the value.
    case "$args" in
      *" -a "*|*"--pass"*) echo "docker-stub: password on a command line" >> "$FAKE_LOG" ;;
    esac
    if [ -n "$REDISCLI_AUTH" ] && [[ " $args " == *" -e REDISCLI_AUTH "* ]]; then
      n=0; [ -f "$FAKE_LOG.authn" ] && n=$(cat "$FAKE_LOG.authn"); n=$((n + 1)); echo "$n" > "$FAKE_LOG.authn"
      if [ -n "$FAKE_REDIS_REFUSED_COUNT" ] && [ "$n" -le "$FAKE_REDIS_REFUSED_COUNT" ]; then
        echo "stub: authenticated ping #$n refused" >> "$FAKE_LOG"
        echo "Could not connect to Redis at redis:6379: Connection refused"; exit 0
      fi
      if [ "$n" = "1" ] && [ -n "$FAKE_REDIS_FIRST_REPLY" ]; then
        echo "stub: authenticated ping #1" >> "$FAKE_LOG"
        printf '%b\n' "$FAKE_REDIS_FIRST_REPLY"; exit 0
      fi
      if [ "$REDISCLI_AUTH" = "$FAKE_EXPECTED_PW" ]; then
        echo "stub: authenticated ping, REDISCLI_AUTH matched" >> "$FAKE_LOG"
      fi
      echo "${FAKE_REDIS_AUTH_REPLY:-PONG}"
    else
      echo "stub: unauthenticated ping" >> "$FAKE_LOG"
      echo "${FAKE_REDIS_NOAUTH_REPLY:-NOAUTH Authentication required.}"
    fi
    exit 0 ;;
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


FAKE_REDIS_PW = "deadbeef" * 8  # obvious fake (64 hex chars, valid form), never a real secret


def _run(tmp_path, dotenv=None, **env_over):
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    root = tmp_path / "deploy"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "blue_green_deploy.sh")
    (root / ".env").write_text(
        f"REDIS_PASSWORD={FAKE_REDIS_PW}\n" if dotenv is None else dotenv
    )
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
        "FAKE_EXPECTED_PW": FAKE_REDIS_PW,
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


# ── Plan 39: Redis password step (7a-7c) ─────────────────────────────────────
def _line_index(calls: str, needle: str, *, last=False) -> int:
    lines = calls.splitlines()
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    assert hits, f"control: {needle!r} not found in recorded calls:\n{calls}"
    return hits[-1] if last else hits[0]


def test_plan39_healthy_deploy_recreates_redis_after_old_color_then_checks(tmp_path):
    result, calls, active = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert active == "green"
    rm_old = _line_index(calls, "compose rm -f backend_blue frontend_blue")
    redis_up = _line_index(calls, "docker compose up -d redis", last=True)
    authed = _line_index(calls, "stub: authenticated ping, REDISCLI_AUTH matched", last=True)
    unauthed = _line_index(calls, "stub: unauthenticated ping")
    assert rm_old < redis_up < authed < unauthed
    # AC-39-14: one authenticated ping BEFORE the new color starts, one AFTER redis is recreated
    first_authed = _line_index(calls, "stub: authenticated ping, REDISCLI_AUTH matched")
    new_color_up = _line_index(calls, "up -d --no-deps backend_green")
    assert first_authed < new_color_up < redis_up < authed
    # the infra step did not recreate redis (the only plain `up -d redis` is the late one)
    assert sum(1 for ln in calls.splitlines() if ln.endswith("compose up -d redis")) == 1
    assert "--no-recreate redis" in calls


@pytest.mark.parametrize(
    "case,kwargs,message",
    [
        ("auth_ping_not_pong", {"FAKE_REDIS_AUTH_REPLY": "ERR invalid password", "REDIS_WAIT_TICKS": "2"}, "did not answer an authenticated PING"),
        ("unauth_not_refused", {"FAKE_REDIS_NOAUTH_REPLY": "PONG"}, "accepted an unauthenticated PING"),
    ],
)
def test_plan39_redis_check_failures_exit_nonzero_with_new_color_already_active(
    tmp_path, case, kwargs, message
):
    result, calls, active = _run(tmp_path, **kwargs)
    out = result.stdout + result.stderr
    assert result.returncode != 0, f"{case}: {out}"
    assert message in out, f"{case}: {out}"
    # the swap already happened, so the file must already say green
    assert active == "green", case
    # control: it really got past the swap and the old-color removal
    assert "sudo caddy reload" in calls
    assert "compose rm -f backend_blue frontend_blue" in calls
    assert FAKE_REDIS_PW not in out


def test_plan39_password_never_logged_and_reaches_the_stub_only_via_env(tmp_path):
    result, calls, active = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    # control: the fake value really was set in the fixture and DID reach the stub (env path)
    assert FAKE_REDIS_PW in (tmp_path / "deploy" / ".env").read_text()
    assert "stub: authenticated ping, REDISCLI_AUTH matched" in calls
    # ... but is never printed, nor recorded in any stub call line
    assert FAKE_REDIS_PW not in result.stdout + result.stderr
    assert FAKE_REDIS_PW not in calls
    assert "password on a command line" not in calls
    assert not any("redis-cli" in ln and " -a " in ln for ln in calls.splitlines())


# ── AC-39-13: REDIS_PASSWORD is validated before the first compose call ──────
BAD_PASSWORDS = [
    pytest.param("", id="missing"),
    pytest.param("abc123", id="too_short"),
    pytest.param("ab%41cd" + "a" * 30, id="percent_padded"),
    pytest.param("a" * 20 + "/" + "b" * 20, id="slash"),
    pytest.param("a" * 20 + "#" + "b" * 20, id="hash"),
    pytest.param("a" * 20 + "?" + "b" * 20, id="question"),
    pytest.param("$(touch PWNED)" + "a" * 30, id="command_substitution"),
]


@pytest.mark.parametrize("bad", BAD_PASSWORDS)
def test_ac_39_13_bad_password_rejected_before_any_compose_call(tmp_path, bad):
    dotenv = f"REDIS_PASSWORD={bad}\n" if bad else ""
    cwd_before = set(os.listdir(os.getcwd()))
    result, calls, active = _run(tmp_path, dotenv=dotenv)
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "::error::" in out, out
    assert "docker compose" not in calls, f"something was touched:\n{calls}"
    if bad:
        assert bad not in out, "the bad value was printed"
    assert active is None
    # no command substitution ever ran
    assert not (tmp_path / "deploy" / "PWNED").exists()
    assert not (tmp_path / "PWNED").exists()
    assert "PWNED" not in set(os.listdir(os.getcwd())) - cwd_before


def test_ac_39_13_control_good_64_hex_password_runs_the_deploy(tmp_path):
    good = "0123456789abcdef" * 4
    result, calls, active = _run(tmp_path, dotenv=f"REDIS_PASSWORD={good}\n", FAKE_EXPECTED_PW=good)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "docker compose" in calls
    assert active == "green"


# ── AC-39-14: wrong password on live redis stops the deploy before anything moves
def test_ac_39_14_wrongpass_aborts_before_new_color_and_names_rotation(tmp_path):
    result, calls, active = _run(
        tmp_path, FAKE_REDIS_FIRST_REPLY="WRONGPASS invalid username-password pair", REDIS_WAIT_TICKS="2"
    )
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "::error::" in out
    assert "ACL SETUSER" in out or "rotat" in out.lower(), out
    # control: the infra step did run and the authenticated ping was attempted
    assert "compose up -d --no-recreate redis" in calls
    assert "stub: authenticated ping #1" in calls
    # nothing moved
    assert "up -d --no-deps" not in calls, "new color was started"
    assert "stop backend_blue" not in calls and "rm -f backend_blue" not in calls
    assert "sudo" not in calls
    assert active is None


def test_ac_39_14_open_server_auth_failed_then_pong_continues(tmp_path):
    first = "AUTH failed: ERR AUTH <password> called without any password configured for the default user.\\nPONG"
    result, calls, active = _run(tmp_path, FAKE_REDIS_FIRST_REPLY=first)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "stub: authenticated ping #1" in calls  # control: the open-server reply was served
    assert "up -d --no-deps" in calls and active == "green"


# ── Fallback branch (X6/X7/X8), run for real through the stub ────────────────
SIGNATURE_MSG = "network foundryx_ss_network has active endpoints"


def test_x6_x8_infra_failure_with_signature_takes_the_network_recreate_fallback(tmp_path):
    result, calls, active = _run(tmp_path, FAKE_REDIS_FAIL_MSG=SIGNATURE_MSG)
    assert result.returncode == 0, result.stdout + result.stderr
    down = _line_index(calls, "compose --profile blue --profile green down --remove-orphans")
    redis_after = _line_index(calls, "compose up -d --no-recreate redis", last=True)
    assert down < redis_after, "redis must be started after the stack down"
    assert active == "green"


def test_x7_db_pgbackups_failure_with_signature_also_enters_the_fallback(tmp_path):
    # `a && b` -> `a ; b` would swallow the first failure: redis would start,
    # the group would succeed and `down` would never run.
    result, calls, active = _run(tmp_path, FAKE_DB_FAIL_MSG=SIGNATURE_MSG)
    assert result.returncode == 0, result.stdout + result.stderr
    down = _line_index(calls, "compose --profile blue --profile green down --remove-orphans")
    redis_after = _line_index(calls, "compose up -d --no-recreate redis", last=True)
    assert down < redis_after
    assert active == "green"


@pytest.mark.parametrize("which", ["FAKE_DB_FAIL_MSG", "FAKE_REDIS_FAIL_MSG"])
def test_x8_non_signature_infra_failure_aborts_before_any_color_starts(tmp_path, which):
    result, calls, active = _run(tmp_path, **{which: "no space left on device"})
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "::error::infra up failed" in out
    assert "down --remove-orphans" not in calls
    assert "up -d --no-deps" not in calls, "a color was started"
    assert "sudo" not in calls
    assert active is None


# ── Plan 39 re-review round ──────────────────────────────────────────────────
def test_ac_39_14_refused_first_then_wrongpass_still_aborts_before_new_color(tmp_path):
    # Closes the mutation "a single ping with no wait": the first reply is a
    # connection refusal (redis still starting), WRONGPASS only comes later.
    result, calls, active = _run(
        tmp_path,
        FAKE_REDIS_REFUSED_COUNT="1",
        FAKE_REDIS_AUTH_REPLY="WRONGPASS invalid username-password pair",
        REDIS_WAIT_TICKS="5",
    )
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "::error::" in out
    assert "stub: authenticated ping #1 refused" in calls  # control: the refusal was served
    assert "up -d --no-deps" not in calls, "new color started despite WRONGPASS"
    assert "sudo" not in calls
    assert active is None


def test_ac_39_14_redis_never_answers_early_check_warns_and_continues(tmp_path):
    result, calls, active = _run(
        tmp_path, FAKE_REDIS_REFUSED_COUNT="3", REDIS_WAIT_TICKS="3"
    )
    out = result.stdout + result.stderr
    assert "stub: authenticated ping #3 refused" in calls  # control: pings were refused
    warn = [ln for ln in out.splitlines() if "::warning::" in ln and "password" in ln.lower()]
    assert warn, f"no ::warning:: about the password check could not run:\n{out}"
    assert "up -d --no-deps backend_green" in calls, "must not become a silent abort"
    assert result.returncode == 0, out
    assert active == "green"


def test_every_redis_cli_exec_in_the_script_reads_stdin_from_dev_null():
    lines = [
        (n, ln)
        for n, ln in enumerate(SCRIPT.read_text().splitlines(), start=1)
        if "docker compose exec" in ln and "redis-cli" in ln and not ln.strip().startswith("#")
    ]
    assert len(lines) >= 3, f"control: expected at least 3 redis-cli exec lines, got {lines}"
    for n, ln in lines:
        assert "</dev/null" in ln, f"line {n} lets redis-cli swallow the script's stdin: {ln.strip()}"
