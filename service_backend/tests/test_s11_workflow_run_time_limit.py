"""Sprint-5/11 review round 1 (B2) - cooperative ``SoftTimeLimitExceeded``
handling for ``workflows.run_workflow`` / ``workflows.wake_serialized``.

Both tasks used to have NO declared time limit of their own, so they silently
inherited the workflow app's tick-family default (`task_soft_time_limit=300`,
`task_time_limit=330`) - wrong for a run that legitimately executes many
nodes, or a serialized drain that legitimately processes several queued runs
in one wakeup. Each now declares its own generous, settings-driven bound
(`settings.workflow_run_soft_time_limit_seconds`, mirroring `jobs.run`), and
catches `SoftTimeLimitExceeded` BEFORE the generic `except Exception` so a
wedged run/drain is failed cleanly (`workflow_runs.status` never left
`'running'`) instead of crashing the worker process.
"""
from __future__ import annotations

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import RUN_FAILED, RUN_RUNNING, Workflow, WorkflowRun
from app.workflow_engine.worker import (
    WORKFLOW_RUN_TIME_LIMIT_ERROR,
    run_workflow_task,
    wake_serialized_task,
)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _workflow(db) -> Workflow:
    doc = {
        "schemaVersion": 1,
        "nodes": [{"id": "trigger", "type": "trigger", "data": {"kind": "manual"}}],
        "edges": [],
    }
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID, name="S11 time limit", description="",
        draft_definition_json=doc,
    )
    db.add(workflow)
    db.flush()
    return workflow


def _running_run(db, workflow: Workflow, *, digest: str | None = None) -> WorkflowRun:
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_RUNNING,
        definition_snapshot_json=workflow.draft_definition_json,
        trigger_payload_json={"triggeredBy": "manual"},
        correlation_key_digest=digest,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_run_workflow_task_declares_soft_time_limit_from_settings():
    from app.config import settings

    assert run_workflow_task.soft_time_limit == settings.workflow_run_soft_time_limit_seconds
    assert run_workflow_task.time_limit == settings.workflow_run_soft_time_limit_seconds + 300


def test_wake_serialized_task_declares_soft_time_limit_from_settings():
    from app.config import settings

    assert wake_serialized_task.soft_time_limit == settings.workflow_run_soft_time_limit_seconds
    assert wake_serialized_task.time_limit == settings.workflow_run_soft_time_limit_seconds + 300


def test_run_workflow_task_fails_the_run_cooperatively_on_soft_time_limit(
    db, session_factory, monkeypatch
):
    workflow = _workflow(db)
    run = _running_run(db, workflow)
    run_id = run.id

    # The task body opens its OWN session via `app.database.SessionLocal()`
    # (a worker process has its own pool) - point it at THIS test's fixture
    # session factory, same pattern test_s11_orphan_sweep_decoupled.py uses.
    import app.database as app_database

    monkeypatch.setattr(app_database, "SessionLocal", session_factory)

    import app.workflow_engine.executor as executor_module

    def _blocked(db, rid):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(executor_module, "run_workflow", _blocked)

    # Must not raise - a worker that let this propagate would crash the
    # ForkPoolWorker instead of failing the run cleanly.
    result = run_workflow_task(run_id)
    assert result == {"runId": run_id, "status": RUN_FAILED}

    db.expire_all()
    fresh = db.get(WorkflowRun, run_id)
    assert fresh.status == RUN_FAILED
    assert fresh.error == WORKFLOW_RUN_TIME_LIMIT_ERROR, (
        f"got {fresh.error!r} - the generic 'Run crashed unexpectedly.' branch "
        "must not be the one that catches this exception type"
    )
    assert fresh.finished_at is not None


def test_wake_serialized_task_fails_the_owned_run_cooperatively_on_soft_time_limit(
    db, session_factory, monkeypatch
):
    """When the drain owns a RUNNING row for this exact scope at the moment
    the limit fires (the safety net for the timeout landing OUTSIDE
    ``drain_serialized_runs``'s own per-run try/except), the task itself
    fails that row rather than leaving it ``running`` forever."""
    workflow = _workflow(db)
    digest = "a" * 64
    run = _running_run(db, workflow, digest=digest)
    run_id = run.id

    import app.database as app_database

    monkeypatch.setattr(app_database, "SessionLocal", session_factory)

    import app.workflow_engine.serialization as serialization_module

    def _blocked(db, tenant_id, workflow_id, digest_, **kwargs):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(serialization_module, "drain_serialized_runs", _blocked)

    result = wake_serialized_task(DEFAULT_TENANT_ID, workflow.id, digest)
    assert result == {
        "admitted": True, "drained": 0, "error": WORKFLOW_RUN_TIME_LIMIT_ERROR,
    }

    db.expire_all()
    fresh = db.get(WorkflowRun, run_id)
    assert fresh.status == RUN_FAILED
    assert fresh.error == WORKFLOW_RUN_TIME_LIMIT_ERROR
    assert fresh.finished_at is not None
