"""Prod incident 26 Sep 2026 (issue #89) - shell-level control for `start.sh`.

This does NOT reproduce the incident (the bug lives in Python -
`bootstrap_modules` swallowing a module failure, W0/W1 - see
`test_deploy_module_bootstrap_abort.py`); `start.sh`'s own retry-then-abort
contract is already correct today. This is a regression guard: once W1 makes
`python -m scripts.bootstrap_db` exit non-zero on a module failure,
`start.sh` must still translate that into a non-zero container exit with no
"bootstrap complete" line - proven here with a stub `python` that always
exits 1, so the real Python bootstrap chain is not exercised at all.

Expected to be GREEN already (control, not a RED test) - flagged in the
tester report.
"""
import os
import stat
import subprocess
from pathlib import Path

START_SH = Path(__file__).resolve().parents[1] / "start.sh"


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def test_start_sh_exits_non_zero_and_never_prints_bootstrap_complete_when_python_fails(
    tmp_path,
):
    """A stub `python` that always exits 1 stands in for a `bootstrap_db`
    that (post-W1) fails fast on a module failure. `start.sh` must retry
    per `BOOTSTRAP_ATTEMPTS`, then abort the container start with a
    non-zero exit and no "bootstrap complete" line - the container never
    goes healthy, the blue/green swap aborts, the old colour keeps
    serving."""
    assert START_SH.is_file(), f"start.sh not found at {START_SH}"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    _make_executable(
        bin_dir / "python",
        "#!/bin/sh\necho \"stub python invoked: $@\" >&2\nexit 1\n",
    )
    _make_executable(
        bin_dir / "pg_isready",
        "#!/bin/sh\nexit 0\n",
    )

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["DATABASE_URL"] = "postgresql://x:x@localhost:5432/x"
    env["SKIP_MIGRATIONS"] = "0"
    env["BOOTSTRAP_ATTEMPTS"] = "1"
    env["BOOTSTRAP_RETRY_DELAY"] = "0"
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        ["sh", str(START_SH)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        f"start.sh exited 0 despite every bootstrap_db attempt failing\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "bootstrap complete" not in combined
    assert "ERROR: bootstrap_db failed after" in combined


def test_start_sh_starts_the_server_when_skip_migrations_is_set(tmp_path):
    """Control: `SKIP_MIGRATIONS=1` bypasses bootstrap entirely and goes
    straight to the server exec - proves the harness itself (stub python,
    stub pg_isready) is sound, independent of the failure path above."""
    assert START_SH.is_file()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    _make_executable(
        bin_dir / "python",
        "#!/bin/sh\necho \"stub python started: $@\"\nexit 0\n",
    )
    _make_executable(
        bin_dir / "pg_isready",
        "#!/bin/sh\nexit 0\n",
    )

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["DATABASE_URL"] = "postgresql://x:x@localhost:5432/x"
    env["SKIP_MIGRATIONS"] = "1"
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        ["sh", str(START_SH)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    combined = result.stdout + result.stderr
    assert "SKIP_MIGRATIONS=1; skipping bootstrap_db" in combined
    assert result.returncode == 0
