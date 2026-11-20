"""Sprint-5/11 review rounds 1+2 (B2/B3) - cooperative ``SoftTimeLimitExceeded``
handling for ``workflows.run_workflow`` / ``workflows.wake_serialized``.

Both tasks used to have NO declared time limit of their own, so they silently
inherited the workflow app's tick-family default (`task_soft_time_limit=300`,
`task_time_limit=330`) - wrong for a run that legitimately executes many
nodes, or a serialized drain that legitimately processes several queued runs
in one wakeup. Each now declares its own generous, settings-driven bound
(`settings.workflow_run_soft_time_limit_seconds`, mirroring `jobs.run`).

Round 2 (B3) moved the drain's OWN cooperative handling from the task level
into ``drain_serialized_runs`` itself: the round-1 shape caught
``SoftTimeLimitExceeded`` only at ``wake_serialized_task`` (task-level),
where it (a) never actually stopped the drain loop early - a bare
``except Exception`` inside ``drain_serialized_runs`` already swallowed the
exception as a plain crash and kept draining the NEXT pending run past the
worker's own soft limit - and (b) when the task-level net DID fire (the
limit landing between runs, outside that inner try), it failed "whatever
RUNNING row happens to match this scope" with no ownership check, which
could fail a SIBLING worker's still-live run. Now ``drain_serialized_runs``
catches the exception itself, BEFORE its own generic except, fails ONLY the
exact ``run_id`` in flight, and RE-RAISES so the loop stops immediately;
``wake_serialized_task`` only logs and returns.
"""
from __future__ import annotations

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import RUN_FAILED, RUN_PENDING, RUN_RUNNING, Workflow, WorkflowRun
from app.workflow_engine.serialization import assign_run_correlation, drain_serialized_runs
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


class FakeLeaseClient:
    """Mirrors ``tests/test_serialized_workflow_runtime.py``'s own fixture -
    duplicated locally rather than imported (that module's helpers are
    private, and duplicating three small methods here is cheaper than
    coupling the two test files' internals)."""

    def __init__(self, *, admitted: bool = True):
        self.admitted = admitted
        self.acquired: list = []
        self.released: list = []

    def acquire(self, key, token, ttl_seconds):
        self.acquired.append((key, token, ttl_seconds))
        return self.admitted

    def renew(self, key, token, ttl_seconds):
        return True

    def release(self, key, token):
        self.released.append((key, token))
        return True


def _serialized_definition() -> dict:
    return {
        "schemaVersion": 2,
        "execution": {
            "mode": "serialized",
            "correlationKey": "{{ trigger.conversationId }}",
        },
        "nodes": [],
        "edges": [],
    }


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


def _serialized_workflow(db) -> Workflow:
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID, name="S11 serialized drain", description="",
        draft_definition_json=_serialized_definition(),
    )
    db.add(workflow)
    db.flush()
    return workflow


def _pending_serialized_run(db, workflow: Workflow, key: str, *, run_id: str) -> WorkflowRun:
    row = WorkflowRun(
        id=run_id,
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=_serialized_definition(),
        trigger_payload_json={"triggeredBy": "event", "omnichannel": {"conversationId": key}},
    )
    assign_run_correlation(row)
    db.add(row)
    db.flush()
    return row


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


# ── B3 (review round 2): drain_serialized_runs owns the stop, not the task ──


def test_drain_serialized_runs_fails_only_the_run_in_flight_and_stops_the_loop(
    db, session_factory
):
    """The drain-level regression B3 asks for: two runs queued in the SAME
    serialized scope, ``execute`` raises SoftTimeLimitExceeded on the FIRST.
    Must fail ONLY that run (never guess at "whatever is RUNNING for this
    scope"), must NOT process the second run, and must re-raise so the
    caller (the task) knows to stop rather than treat it as a normal
    'drained N' result."""
    workflow = _serialized_workflow(db)
    first = _pending_serialized_run(db, workflow, "conversation-a", run_id="s11-b3-first")
    _pending_serialized_run(db, workflow, "conversation-a", run_id="s11-b3-second")
    db.commit()

    executed: list[str] = []

    def execute(run_db, run_id):
        executed.append(run_id)
        raise SoftTimeLimitExceeded()

    lease = FakeLeaseClient()
    with pytest.raises(SoftTimeLimitExceeded):
        drain_serialized_runs(
            db,
            DEFAULT_TENANT_ID,
            workflow.id,
            first.correlation_key_digest,
            lease_client=lease,
            execute=execute,
        )

    # Only the FIRST run was ever handed to execute() - the loop stopped
    # immediately rather than moving on to the next pending run.
    assert executed == ["s11-b3-first"]
    # The lease was still released (the outer `finally` runs regardless).
    assert len(lease.released) == 1

    db.expire_all()
    rows = {r.id: r for r in db.query(WorkflowRun).filter(WorkflowRun.id.in_(
        ["s11-b3-first", "s11-b3-second"]
    )).all()}
    assert rows["s11-b3-first"].status == RUN_FAILED
    assert rows["s11-b3-first"].error == WORKFLOW_RUN_TIME_LIMIT_ERROR
    assert rows["s11-b3-first"].finished_at is not None
    assert rows["s11-b3-second"].status == RUN_PENDING, (
        "the second run in the SAME scope must NOT be processed - the drain "
        "stopped at the exact limit, it did not keep draining past it"
    )


def test_wake_serialized_task_never_queries_or_fails_a_run_itself_on_soft_time_limit(
    db, session_factory, monkeypatch
):
    """Task-level regression for the round-1 ownership bug (B3): the OLD
    shape queried "whatever RUNNING row matches this tenant/workflow/digest"
    with no ownership check - a RUNNING row that this exact invocation never
    called ``execute_run`` on (the timeout landing between runs, or a stale
    leftover row in the same scope) would still get wrongly failed. The task
    no longer queries the DB in this branch at all -
    ``drain_serialized_runs`` already closed the exact run it was executing
    (proven by the test above) before re-raising, so a RUNNING row for this
    EXACT scope that this invocation never touched must survive."""
    workflow = _workflow(db)
    digest = "a" * 64
    # A RUNNING row for the SAME scope this call targets - exactly what the
    # round-1 task-level query would have matched and wrongly failed.
    untouched_run = _running_run(db, workflow, digest=digest)
    untouched_id = untouched_run.id

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
    untouched = db.get(WorkflowRun, untouched_id)
    assert untouched.status == RUN_RUNNING, (
        "the task-level handler must never guess at a RUNNING row for the "
        "scope - only drain_serialized_runs, which knows the EXACT run_id "
        "it was executing, may fail a run"
    )
    assert untouched.error is None
