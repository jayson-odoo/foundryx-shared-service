"""SS-DEPLOY-SKIP-TESTS (17 Nov 2026) - a release may skip the CI gate jobs,
but only for a sha that already passed every one of them.

Owner rule (14 Nov): zero GitHub-hosted minutes where possible. Every SS
release re-ran the full suite (~18 minutes) even though main's push CI had
already tested that exact sha. The `skip_tests` dispatch input skips the six
gates; a small `ci-green-check` job proves (GitHub API, check runs on the
sha) that each gate's newest attempt is green, and refuses the release
otherwise. Blue/green, health check and the owner email stay as they were.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest
import yaml

from tests.test_deploy_blue_green_script import REPO
from tests.test_deploy_skip_stale_sha import CI_JOBS, _job_runs_on

GUARD = REPO / "scripts" / "deploy_ci_green_guard.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy.yml"
SHA = "c748c240" + "0" * 32

ALL_GREEN = {name: "success" for name in CI_JOBS}
ALL_SKIPPED = {name: "skipped" for name in CI_JOBS}


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(WORKFLOW.read_text())


# ---- 1. the workflow ----------------------------------------------------

def test_workflow_dispatch_has_a_skip_tests_boolean_input_default_off(wf):
    on = wf.get("on") or wf.get(True)  # PyYAML reads the bare `on` key as True
    inp = on["workflow_dispatch"]["inputs"]["skip_tests"]
    assert inp["type"] == "boolean"
    assert inp["default"] is False
    assert on["workflow_dispatch"]["inputs"]["force_sha"]["default"] is False


def test_the_gates_run_on_every_event_except_a_skip_tests_release(wf):
    for name in CI_JOBS:
        job = wf["jobs"][name]
        for event in ("push", "pull_request", "merge_group", "workflow_dispatch"):
            assert _job_runs_on(job, event), (name, event)
        assert not _job_runs_on(job, "workflow_dispatch", skip_tests=True), name


def test_the_green_check_runs_only_on_a_skip_tests_release(wf):
    job = wf["jobs"]["ci-green-check"]
    assert _job_runs_on(job, "workflow_dispatch", skip_tests=True)
    for event in ("push", "pull_request", "merge_group", "workflow_dispatch"):
        assert not _job_runs_on(job, event), event
    assert job["permissions"]["checks"] == "read"
    run = job["steps"][-1]["run"]
    assert "scripts/deploy_ci_green_guard.sh" in run
    assert "github.sha" in run  # the EXACT sha this release builds
    assert "github.token" in str(job["steps"][-1]["env"])


def test_a_normal_release_still_needs_every_gate_green(wf):
    deploy = wf["jobs"]["build-and-deploy"]
    needs = {**ALL_GREEN, "ci-green-check": "skipped"}
    assert _job_runs_on(deploy, "workflow_dispatch", needs=needs)
    for name in CI_JOBS:
        for bad in ("failure", "cancelled", "skipped"):
            assert not _job_runs_on(
                deploy, "workflow_dispatch", needs={**needs, name: bad}
            ), (name, bad)


def test_a_skip_tests_release_deploys_only_when_the_green_check_passed(wf):
    deploy = wf["jobs"]["build-and-deploy"]
    assert {"ci-green-check", *CI_JOBS} <= set(deploy["needs"])
    ok = {**ALL_SKIPPED, "ci-green-check": "success"}
    assert _job_runs_on(deploy, "workflow_dispatch", skip_tests=True, needs=ok)
    for bad in ("failure", "cancelled", "skipped"):
        assert not _job_runs_on(
            deploy, "workflow_dispatch", skip_tests=True,
            needs={**ALL_SKIPPED, "ci-green-check": bad},
        ), bad


def test_a_push_or_pr_never_deploys_whatever_the_results(wf):
    deploy = wf["jobs"]["build-and-deploy"]
    for event in ("push", "pull_request", "merge_group"):
        assert not _job_runs_on(deploy, event, needs=ALL_GREEN), event


def test_the_deploy_job_still_survives_skipped_needs_only_via_not_cancelled(wf):
    cond = wf["jobs"]["build-and-deploy"]["if"]
    assert "!cancelled()" in cond
    assert "always()" not in cond  # a cancelled release must not deploy


def test_the_owner_email_names_a_refused_skip_tests_release(wf):
    notify = wf["jobs"]["notify-owner"]
    assert "ci-green-check" in notify["needs"]
    compute = next(s for s in notify["steps"] if s.get("id") == "notify")["run"]
    assert 'needs.ci-green-check.result }}" = "failure"' in compute
    assert "no green CI run" in compute
    # The existing subjects are unchanged.
    for subject in ("deploy succeeded", "deploy failed", "not main head", "CI only, not deployed"):
        assert subject in compute


# ---- 2. the guard script -------------------------------------------------

def test_the_script_requires_exactly_the_workflow_gate_names(wf):
    text = GUARD.read_text()
    block = text[text.index("REQUIRED=(") : text.index(")\n", text.index("REQUIRED=("))]
    names = re.findall(r'"([^"]+)"', block)
    assert sorted(names) == sorted(wf["jobs"][j]["name"] for j in CI_JOBS)


def _run(tmp_path, runs, *, sha=SHA, gh_rc=0, repo="org/repo"):
    """Run the guard with a fake `gh` that prints `runs` as the jq output
    (name, conclusion, started_at - one TSV line each)."""
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    data = tmp_path / "runs.tsv"
    data.write_text("".join("\t".join(r) + "\n" for r in runs))
    args = tmp_path / "gh_args"
    gh = bindir / "gh"
    gh.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{args}"\n'
        f'cat "{data}"\nexit {gh_rc}\n'
    )
    gh.chmod(0o755)
    env = {"PATH": f"{bindir}:{os.environ.get('PATH', '')}", "GH_REPO": repo}
    result = subprocess.run(
        ["bash", str(GUARD), sha], env=env, capture_output=True, text=True, timeout=30
    )
    called = args.read_text() if args.exists() else ""
    return result, called


def _names(wf):
    return [wf["jobs"][j]["name"] for j in CI_JOBS]


def test_every_gate_green_on_the_sha_passes(tmp_path, wf):
    runs = [(n, "success", "2026-11-17T08:00:00Z") for n in _names(wf)]
    result, called = _run(tmp_path, runs)
    assert result.returncode == 0, result.stderr
    assert f"every CI gate is green on {SHA}" in result.stdout
    assert f"repos/org/repo/commits/{SHA}/check-runs" in called
    assert "--paginate" in called


def test_a_missing_gate_refuses_and_names_it(tmp_path, wf):
    names = _names(wf)
    runs = [(n, "success", "2026-11-17T08:00:00Z") for n in names[1:]]
    result, _ = _run(tmp_path, runs)
    assert result.returncode == 1
    assert f"'{names[0]}' has no green run on {SHA} (latest: none)" in result.stderr
    assert "Nothing was built or deployed" in result.stderr


def test_no_check_runs_at_all_refuses(tmp_path):
    result, _ = _run(tmp_path, [])
    assert result.returncode == 1


def test_the_newest_attempt_counts_a_later_failure_is_red(tmp_path, wf):
    names = _names(wf)
    runs = [(n, "success", "2026-11-17T08:00:00Z") for n in names]
    runs.append((names[4], "failure", "2026-11-17T09:00:00Z"))  # re-run went red
    result, _ = _run(tmp_path, runs)
    assert result.returncode == 1
    assert f"'{names[4]}' has no green run on {SHA} (latest: failure)" in result.stderr


def test_a_later_success_after_a_failure_is_green(tmp_path, wf):
    names = _names(wf)
    runs = [(n, "success", "2026-11-17T09:00:00Z") for n in names]
    runs.append((names[4], "failure", "2026-11-17T08:00:00Z"))  # flake, then re-run green
    result, _ = _run(tmp_path, runs)
    assert result.returncode == 0, result.stderr


def test_skipped_runs_from_an_earlier_skip_tests_release_are_ignored(tmp_path, wf):
    names = _names(wf)
    runs = [(n, "success", "2026-11-17T08:00:00Z") for n in names]
    runs += [(n, "skipped", "2026-11-17T10:00:00Z") for n in names]
    result, _ = _run(tmp_path, runs)
    assert result.returncode == 0, result.stderr
    # ...but skipped alone proves nothing
    result, _ = _run(tmp_path / "b", [(n, "skipped", "2026-11-17T10:00:00Z") for n in names])
    assert result.returncode == 1


def test_a_gate_still_running_is_not_green(tmp_path, wf):
    names = _names(wf)
    runs = [(n, "success", "2026-11-17T08:00:00Z") for n in names]
    runs.append((names[5], "", "2026-11-17T09:00:00Z"))
    result, _ = _run(tmp_path, runs)
    assert result.returncode == 1


def test_a_github_api_error_refuses_instead_of_deploying_blind(tmp_path, wf):
    runs = [(n, "success", "2026-11-17T08:00:00Z") for n in _names(wf)]
    result, _ = _run(tmp_path, runs, gh_rc=1)
    assert result.returncode == 1
    assert "could not read the check runs" in result.stderr


def test_a_missing_sha_or_repo_refuses(tmp_path):
    result, _ = _run(tmp_path, [], sha="")
    assert result.returncode == 1
    result, _ = _run(tmp_path / "b", [], repo="")
    assert result.returncode == 1
