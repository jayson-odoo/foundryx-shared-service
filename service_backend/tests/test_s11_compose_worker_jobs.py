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
DEPLOY_SCRIPT_PATH = REPO_ROOT / "scripts" / "blue_green_deploy.sh"

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


def test_worker_services_carry_the_shared_backend_env_anchor(compose):
    """Review round 1 (S4) - proves the per-service `environment:` override
    (added for the worker-only DB timeouts above) used `<<: *backend-env`
    rather than replacing the whole mapping outright, which would silently
    strip every OTHER required env (DATABASE_URL, FERNET_KEY, ...) from the
    worker services. DATABASE_URL and FERNET_KEY are two required
    (`:?set in .env`) keys from the `x-backend-env` anchor - their presence
    proves the merge survived."""
    services = compose["services"]
    for name in ("worker_workflow", "worker_jobs"):
        env = services[name].get("environment") or {}
        missing = [k for k in ("DATABASE_URL", "FERNET_KEY") if k not in env]
        assert not missing, (
            f"{name}'s environment override must merge the shared "
            f"x-backend-env anchor (`<<: *backend-env`), not replace it - "
            f"missing: {missing}"
        )


def test_deploy_md_documents_the_new_worker_jobs_service():
    text = DEPLOY_PATH.read_text()
    assert "worker_jobs" in text, (
        "AC-11-87: DEPLOY.md must document the new service, the queue "
        "split and the deploy-time steps in the SAME PR as the compose "
        "change - a config/docs pair the plan explicitly calls for"
    )


def _worker_service_names(compose: dict) -> list[str]:
    """Every top-level compose service that is a Celery worker or beat -
    literally 'beat' or a 'worker_*' name. yaml.safe_load never sees a
    commented-out service (worker_bots is commented out in compose today),
    so this only ever returns services compose would actually create."""
    return [
        name
        for name in compose["services"]
        if name == "beat" or name.startswith("worker_")
    ]


def test_deploy_script_recreates_every_compose_worker_service(compose):
    """Drift guard for the 2026-09-21 worker_jobs incident: PR #76 added the
    worker_jobs compose service (consuming the new 'jobs' queue) but
    blue_green_deploy.sh's image-pull line and --force-recreate line still
    named only worker_workflow worker_omni beat - production never started
    a jobs consumer and every autocount_sync job stayed pending. Every
    top-level worker_*/beat compose service must be named on BOTH lines of
    the deploy script, so a future new worker service fails this test
    instead of silently deploying with no consumer.
    """
    lines = DEPLOY_SCRIPT_PATH.read_text().splitlines()

    pull_line = next(
        (line for line in lines if line.strip().startswith("docker compose pull worker_")),
        None,
    )
    assert pull_line is not None, (
        "blue_green_deploy.sh must have a 'docker compose pull worker_...' "
        "line that pulls the Celery worker images before the swap"
    )

    recreate_line = next(
        (line for line in lines if "--force-recreate" in line and "worker_" in line),
        None,
    )
    assert recreate_line is not None, (
        "blue_green_deploy.sh must have a 'docker compose up -d "
        "--force-recreate --no-deps worker_...' line that recreates the "
        "Celery workers on the new image after the swap"
    )

    verify_line = next(
        (line for line in lines if line.strip().startswith("for svc in worker_")),
        None,
    )
    assert verify_line is not None, (
        "blue_green_deploy.sh must have a 'for svc in worker_...' health "
        "loop that verifies every recreated Celery worker settled"
    )

    pull_tokens = [t.strip(";") for t in pull_line.split()]
    recreate_tokens = [t.strip(";") for t in recreate_line.split()]
    verify_tokens = [t.strip(";") for t in verify_line.split()]

    for name in _worker_service_names(compose):
        assert name in pull_tokens, (
            f"{name} is a top-level worker/beat compose service missing "
            f"from the deploy script's image-pull line - it will keep "
            f"running stale code after a deploy: {pull_line!r}"
        )
        assert name in recreate_tokens, (
            f"{name} is a top-level worker/beat compose service missing "
            f"from the deploy script's --force-recreate line - production "
            f"never (re)creates it, so its queue may have NO consumer at "
            f"all: {recreate_line!r}"
        )
        assert name in verify_tokens, (
            f"{name} is a top-level worker/beat compose service missing "
            f"from the deploy script's post-recreate health-check loop: "
            f"{verify_line!r}"
        )
