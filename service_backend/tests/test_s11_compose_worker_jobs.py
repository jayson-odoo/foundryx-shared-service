"""Sprint-5/11 S1 - RED tests for the deploy-side half of the queue split
(AC-11-80's `worker_jobs` compose service, AC-11-85's worker-only DB-timeout
env, AC-11-87's compose + DEPLOY.md pairing).

Parses the REAL repo-root ``docker-compose.yml`` (not a fixture copy) - a
docs/config drift here is exactly the class of bug this plan's own root
cause narrative describes (a deploy-time file nobody re-reads once it works).
YAML anchors/aliases (``x-backend-env``/``x-backend-base``) resolve natively
via ``yaml.safe_load`` since compose files are plain YAML with no custom
tags, so the merged ``environment`` mapping each service actually gets is
what these tests inspect.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
DEPLOY_PATH = REPO_ROOT / "DEPLOY.md"

WORKER_DB_TIMEOUT_ENVS = (
    "WORKER_DB_STATEMENT_TIMEOUT_SECONDS",
    "WORKER_DB_LOCK_TIMEOUT_SECONDS",
    "WORKER_DB_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_SECONDS",
)


@pytest.fixture(scope="module")
def compose():
    with open(COMPOSE_PATH) as f:
        return yaml.safe_load(f)


def test_worker_jobs_service_exists_with_the_jobs_queue_and_concurrency_2(compose):
    services = compose["services"]
    assert "worker_jobs" in services, (
        "AC-11-80: docker-compose.yml needs a dedicated worker_jobs service "
        "consuming the new 'jobs' queue - isolating jobs.run onto its own "
        "container is the actual fix, not just a Celery-side route"
    )
    command = services["worker_jobs"]["command"]
    assert "-Q" in command and "jobs" in command, (
        f"worker_jobs must consume -Q jobs, got: {command}"
    )
    assert "-c" in command, "R9: worker_jobs needs an explicit -c (recommended 2)"
    c_index = command.index("-c")
    assert command[c_index + 1] == "2", (
        f"R9 recommends -c 2 (I/O-bound work, one extra forked image is the "
        f"accepted cost) - got {command[c_index + 1]!r}"
    )


def test_worker_workflow_still_consumes_only_the_workflow_queue(compose):
    """Control: the existing service must be UNTOUCHED by the split - a
    message already queued on 'workflow' at deploy time must still run
    there (lossless rollout, AC-11-80)."""
    command = compose["services"]["worker_workflow"]["command"]
    assert "-Q" in command
    q_index = command.index("-Q")
    assert command[q_index + 1] == "workflow"


def test_worker_db_timeout_envs_reach_the_worker_services_only(compose):
    """AC-11-85: settings-driven, worker-only. backend_blue/backend_green
    share the SAME x-backend-env anchor as the workers, so simply adding
    these three envs to that anchor would leak them onto the API too - the
    coder must add them via a per-service environment override on
    worker_workflow + worker_jobs specifically, never on the shared anchor."""
    services = compose["services"]
    for name in ("worker_workflow", "worker_jobs"):
        env = services[name].get("environment") or {}
        missing = [k for k in WORKER_DB_TIMEOUT_ENVS if k not in env]
        assert not missing, f"{name} is missing worker DB-timeout env(s): {missing}"

    for name in ("backend_blue", "backend_green"):
        env = services[name].get("environment") or {}
        leaked = [k for k in WORKER_DB_TIMEOUT_ENVS if k in env]
        assert not leaked, (
            f"{name} must NEVER receive the worker DB-timeout envs (AC-11-85: "
            f"'unset (the API default) leaves today's behaviour exactly as "
            f"is') - leaked: {leaked}"
        )


def test_deploy_md_documents_the_new_worker_jobs_service():
    text = DEPLOY_PATH.read_text()
    assert "worker_jobs" in text, (
        "AC-11-87: DEPLOY.md must document the new service, the queue "
        "split and the deploy-time steps in the SAME PR as the compose "
        "change - a config/docs pair the plan explicitly calls for"
    )
