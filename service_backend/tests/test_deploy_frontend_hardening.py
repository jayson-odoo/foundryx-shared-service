"""Plan 40 (sprint-5) - RED tests: frontend container + deploy transport hardening.

Parses the REAL repo files (no Docker): `docker-compose.yml` via yaml.safe_load,
`.github/workflows/deploy.yml`, `.github/workflows/diag-ssh.yml` and `DEPLOY.md`
as text. No host keys, IPs or secrets appear here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
DIAG_PATH = REPO_ROOT / ".github" / "workflows" / "diag-ssh.yml"
DEPLOY_MD_PATH = REPO_ROOT / "DEPLOY.md"

FRONTENDS = ["frontend_blue", "frontend_green"]


@pytest.fixture(scope="module")
def compose():
    with open(COMPOSE_PATH) as f:
        return yaml.safe_load(f)


def _wf_lines():
    return WORKFLOW_PATH.read_text().splitlines()


# ── AC-40-01 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", FRONTENDS)
def test_ac_40_01_frontend_drops_all_caps_and_no_new_privileges(compose, name):
    svc = compose["services"][name]
    assert svc.get("cap_drop") == ["ALL"]
    assert "no-new-privileges:true" in (svc.get("security_opt") or [])


# ── AC-40-02 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", FRONTENDS)
def test_ac_40_02_frontend_is_read_only_with_two_sized_tmpfs(compose, name):
    svc = compose["services"][name]
    assert svc.get("read_only") is True
    entries = svc.get("tmpfs") or []
    assert len(entries) == 2, entries
    paths = {}
    for e in entries:
        path, _, opts = str(e).partition(":")
        paths[path] = opts
    assert set(paths) == {"/tmp", "/app/.next/cache"}, paths
    for path, opts in paths.items():
        assert "size=" in opts, f"{path} tmpfs needs a size= limit"


@pytest.mark.parametrize(
    "name",
    ["backend_blue", "backend_green", "worker_workflow", "worker_jobs", "worker_omni", "beat", "db", "redis", "pgbackups"],
)
def test_ac_40_02_scope_control_other_services_not_hardened_here(compose, name):
    svc = compose["services"][name]
    assert "read_only" not in svc, name
    assert "cap_drop" not in svc, name


# ── AC-40-03 ─────────────────────────────────────────────────────────────────
def test_ac_40_03_no_host_key_checking_disabled_anywhere_in_the_workflow():
    text = WORKFLOW_PATH.read_text()
    assert "StrictHostKeyChecking=no" not in text
    assert "UserKnownHostsFile=/dev/null" not in text
    assert "skip host-key" not in text.lower(), "the comment justifying skipped host checks must go"


def test_ac_40_03_every_ssh_option_string_pins_host_keys():
    opt_lines = [ln for ln in _wf_lines() if re.search(r'\bO="', ln)]
    assert len(opt_lines) >= 3, f"control: expected at least 3 O= option strings, got {len(opt_lines)}"
    for ln in opt_lines:
        assert "StrictHostKeyChecking=yes" in ln, ln.strip()
        assert "UserKnownHostsFile=" in ln and "UserKnownHostsFile=/dev/null" not in ln, ln.strip()


def test_ac_40_03_every_ssh_and_scp_call_goes_through_the_option_string():
    calls = [ln for ln in _wf_lines() if re.search(r"\b(ssh|scp)\s+\$O\b", ln)]
    assert len(calls) >= 3, "control: expected the deploy's ssh/scp calls"
    raw = [
        ln for ln in _wf_lines()
        if re.search(r"(^|[\s|;(])(ssh|scp)\s+(?!\$O\b)-", ln) and not ln.strip().startswith("#")
    ]
    assert not raw, f"ssh/scp calls bypassing $O: {raw}"


def test_ac_40_03_diag_ssh_workflow_does_not_use_ssh_at_all():
    text = DIAG_PATH.read_text()
    assert not re.search(r"(^|[\s|;(])(ssh|scp)\s", "\n".join(
        ln for ln in text.splitlines() if not ln.strip().startswith("#")
    ))
    assert "StrictHostKeyChecking" not in text


# ── AC-40-04 ─────────────────────────────────────────────────────────────────
def _known_hosts_step():
    lines = _wf_lines()
    idx = next((i for i, ln in enumerate(lines) if "secrets.SSH_KNOWN_HOSTS" in ln), None)
    assert idx is not None, "AC-40-04: no step reads secrets.SSH_KNOWN_HOSTS"
    start = idx
    while start > 0 and not lines[start].lstrip().startswith("- name:"):
        start -= 1
    end = idx + 1
    while end < len(lines) and not lines[end].lstrip().startswith("- name:"):
        end += 1
    return start, end, lines[start:end]


def test_ac_40_04_known_hosts_written_from_secret_without_echoing_it():
    _, _, block = _known_hosts_step()
    text = "\n".join(block)
    env_name = re.search(r"(\w+):\s*\$\{\{\s*secrets\.SSH_KNOWN_HOSTS\s*\}\}", text)
    assert env_name, "the secret must come in through an env var"
    var = env_name.group(1)
    assert "known_hosts" in text, "must write a known-hosts file"
    uses = [ln for ln in block if re.search(r"\$\{?%s\}?" % var, ln)]
    assert uses, "control: the env var must be used"
    for ln in uses:
        s = ln.strip()
        assert not s.startswith("echo"), f"secret echoed: {s}"
        assert s.startswith(("printf", "if", "[", "test")) or "-z" in s or "-n" in s, s
    assert re.search(r"-z\s+\"?\$\{?%s" % var, text) or re.search(r"\[\s*-n", text), "must test for empty"
    assert "::error::" in text and "exit 1" in text


def test_ac_40_04_known_hosts_step_comes_before_any_ssh_use():
    start, _, _ = _known_hosts_step()
    first_ssh = next(
        (i for i, ln in enumerate(_wf_lines())
         if re.search(r"\b(ssh|scp)\s+\$O\b", ln) or re.search(r'\bO="', ln)),
        None,
    )
    assert first_ssh is not None, "control: the first ssh use must be found"
    assert start < first_ssh


# ── AC-40-05 ─────────────────────────────────────────────────────────────────
def test_ac_40_05_env_write_sets_mode_600_in_the_same_remote_command_and_still_only_warns():
    line = next((ln for ln in _wf_lines() if "cat > $D/.env" in ln), None)
    assert line is not None, "control: the .env write line must exist"
    assert re.search(
        r'"umask 077;[^"]*cat > \$D/\.env[^"]*chmod 600 \$D/\.env[^"]*"', line
    ), f"chmod 600 must be part of the same remote command as the write: {line.strip()}"
    assert '|| echo "::warning::' in line, "a refused write must still only warn"


# ── AC-40-06 ─────────────────────────────────────────────────────────────────
def test_ac_40_06_deploy_md_documents_known_hosts_and_readonly_frontend():
    text = DEPLOY_MD_PATH.read_text()
    assert "SSH_KNOWN_HOSTS" in text
    assert "/app/.next/cache" in text
    assert "StrictHostKeyChecking=no" not in text


# ═════════════════════════════════════════════════════════════════════════════
# Review round (AC-40-07, AC-40-08 and mutation guards)
# ═════════════════════════════════════════════════════════════════════════════
import os
import stat
import subprocess


def _first_connection_script() -> str:
    """The sync step's shell up to and including its first `ssh $O ...` line,
    with Actions templating replaced by plain placeholders."""
    lines = _wf_lines()
    start = next(i for i, ln in enumerate(lines) if "Sync compose + deploy script" in ln)
    cmd = next(i for i in range(start, len(lines)) if lines[i].strip() == "command: |")
    indent = len(lines[cmd + 1]) - len(lines[cmd + 1].lstrip())
    out = []
    for ln in lines[cmd + 1 :]:
        out.append(ln[indent:])
        if re.match(r"\s*ssh \$O\b", ln):
            break
    text = "\n".join(out)
    return re.sub(r"\$\{\{[^}]*\}\}", "x", text)


def _run_first_connection(tmp_path, ssh_exit: int):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("ssh", f"#!/bin/sh\nexit {ssh_exit}\n"),
        ("timeout", "#!/bin/sh\nexit 0\n"),  # the TCP probe succeeds
        ("sleep", "#!/bin/sh\nexit 0\n"),
    ):
        f = bin_dir / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    script = tmp_path / "step.sh"
    script.write_text(_first_connection_script() + "\n")
    env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}", "HOME": str(tmp_path)}
    return subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)


def test_ac_40_07_exit_255_at_first_connection_points_at_the_known_hosts_secret(tmp_path):
    res = _run_first_connection(tmp_path, 255)
    out = res.stdout + res.stderr
    assert res.returncode != 0
    errs = [ln for ln in out.splitlines() if "::error::" in ln]
    assert errs, out
    assert any("SSH_KNOWN_HOSTS" in ln for ln in errs), errs
    assert any("re-run" in ln.lower() for ln in errs), errs


def test_ac_40_07_remote_command_failure_keeps_the_permissions_message(tmp_path):
    res = _run_first_connection(tmp_path, 1)
    out = res.stdout + res.stderr
    assert res.returncode != 0
    assert "::error::cannot mkdir" in out and "sudo chown" in out, out
    assert "SSH_KNOWN_HOSTS" not in out, out


# ── AC-40-08 ─────────────────────────────────────────────────────────────────
def test_ac_40_08_deploy_md_documents_the_scan_command_with_matching_host_and_port():
    text = DEPLOY_MD_PATH.read_text()
    assert "ssh-keyscan -t ed25519 -p" in text
    i = text.index("ssh-keyscan -t ed25519 -p")
    window = text[max(0, i - 600) : i + 900]
    assert "SSH_HOST" in window and "SSH_PORT" in window
    assert "unedited" in window.lower()


# ── mutation guards ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", FRONTENDS)
def test_cache_tmpfs_is_owned_by_the_image_user(compose, name):
    entries = {str(e).partition(":")[0]: str(e).partition(":")[2] for e in compose["services"][name]["tmpfs"]}
    opts = entries["/app/.next/cache"]
    assert "uid=1001" in opts and "gid=1001" in opts, opts


def test_env_write_only_sets_the_mode_when_the_write_succeeded():
    line = next(ln for ln in _wf_lines() if "cat > $D/.env" in ln)
    assert re.search(r"cat > \$D/\.env\s*&&\s*chmod 600 \$D/\.env", line), line.strip()
    assert not re.search(r"cat > \$D/\.env\s*;\s*chmod", line), line.strip()


def _normalize(path: str) -> str:
    return path.strip("\"'").replace("${HOME}", "~").replace("$HOME", "~")


def test_known_hosts_file_written_is_the_file_every_ssh_option_string_reads():
    _, _, block = _known_hosts_step()
    text = "\n".join(block)
    written = {_normalize(m) for m in re.findall(r">\s*(\S*known_hosts\S*)", text)}
    assert len(written) == 1, written
    read = set()
    opt_lines = [ln for ln in _wf_lines() if re.search(r'\bO="', ln)]
    assert len(opt_lines) >= 3
    for ln in opt_lines:
        m = re.search(r"UserKnownHostsFile=(\S+)", ln)
        assert m, ln.strip()
        read.add(_normalize(m.group(1)))
    assert read == written, (read, written)


def test_known_hosts_file_gets_mode_600():
    _, _, block = _known_hosts_step()
    text = "\n".join(block)
    written = re.findall(r">\s*(\S*known_hosts\S*)", text)
    assert written
    for path in written:
        assert re.search(r"chmod 600 %s\b" % re.escape(path), text), path
