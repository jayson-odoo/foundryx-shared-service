"""S2 correlated serialized workflow runtime tests (AC-SAR-33..42)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import RUN_FAILED, RUN_PENDING, RUN_SUCCESS, Workflow, WorkflowRun
from app.services.workflow_service import WorkflowError, WorkflowService
from app.workflow_engine.serialization import (
    SerializedCoordinationUnavailable,
    assign_run_correlation,
    correlation_digest,
    dispatch_persisted_run,
    drain_serialized_runs,
    redrive_pending_serialized_runs,
)


def _definition(*, mode="serialized"):
    return {
        "schemaVersion": 2,
        "execution": {
            "mode": mode,
            "correlationKey": "{{ trigger.conversationId }}" if mode == "serialized" else "",
        },
        "nodes": [],
        "edges": [],
    }


def _workflow(db):
    row = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Serialized runtime",
        description="",
        draft_definition_json=_definition(),
    )
    db.add(row)
    db.flush()
    return row


def _run(db, workflow, key, *, run_id, created_at=None):
    row = WorkflowRun(
        id=run_id,
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=_definition(),
        trigger_payload_json={
            "triggeredBy": "event",
            "omnichannel": {"conversationId": key},
        },
        created_at=created_at or datetime.now(timezone.utc),
    )
    assign_run_correlation(row)
    db.add(row)
    db.flush()
    return row


class FakeLeaseClient:
    def __init__(self, *, admitted=True, fail=False):
        self.admitted = admitted
        self.fail = fail
        self.acquired = []
        self.renewed = []
        self.released = []

    def acquire(self, key, token, ttl_seconds):
        if self.fail:
            raise OSError("redis unavailable")
        self.acquired.append((key, token, ttl_seconds))
        return self.admitted

    def renew(self, key, token, ttl_seconds):
        self.renewed.append((key, token, ttl_seconds))
        return True

    def release(self, key, token):
        self.released.append((key, token))
        return True


def test_run_snapshots_resolved_correlation_key_once(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=_definition(),
        trigger_payload_json={
            "triggeredBy": "event",
            "omnichannel": {"conversationId": "conversation-a"},
        },
    )
    assign_run_correlation(run)
    assert run.correlation_key == "conversation-a"
    assert run.correlation_key_digest == correlation_digest("conversation-a")
    run.definition_snapshot_json["execution"]["correlationKey"] = "changed"
    run.trigger_payload_json["omnichannel"]["conversationId"] = "conversation-b"
    assert run.correlation_key == "conversation-a"
    assert run.correlation_key_digest == correlation_digest("conversation-a")


def test_manual_serialized_run_reports_unresolved_key_as_workflow_error(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    from app.models import User

    actor = db.query(User).filter(User.email == "demo@example.com").one()

    with pytest.raises(WorkflowError, match="Correlation key"):
        WorkflowService(db).run(
            workflow.id,
            DEFAULT_TENANT_ID,
            inputs={},
            is_test=False,
            actor=actor,
        )

def test_parallel_run_keeps_direct_dispatch_and_no_correlation_snapshot(
    session_factory,
):
    db = session_factory()
    workflow = _workflow(db)
    run = WorkflowRun(
        id="parallel-run",
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=_definition(mode="parallel"),
        trigger_payload_json={"triggeredBy": "manual"},
    )
    assign_run_correlation(run)
    db.add(run)
    db.commit()
    direct = []
    serialized = []
    dispatch_persisted_run(
        db,
        run,
        eager=False,
        direct_wake=direct.append,
        serialized_wake=lambda *scope: serialized.append(scope),
    )
    assert run.correlation_key is None
    assert direct == [run.id]
    assert serialized == []


def test_serialized_run_dispatches_digest_wakeup_instead_of_direct_task(
    session_factory,
):
    db = session_factory()
    workflow = _workflow(db)
    run = _run(db, workflow, "conversation-a", run_id="serialized-run")
    db.commit()
    direct = []
    serialized = []
    dispatch_persisted_run(
        db,
        run,
        eager=False,
        direct_wake=direct.append,
        serialized_wake=lambda *scope: serialized.append(scope),
    )
    assert direct == []
    assert serialized == [
        (
            DEFAULT_TENANT_ID,
            workflow.id,
            correlation_digest("conversation-a"),
        )
    ]


def test_serialized_drain_is_fifo_and_scoped_to_one_key(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    base = datetime.now(timezone.utc)
    _run(db, workflow, "conversation-a", run_id="run-b", created_at=base)
    _run(db, workflow, "conversation-a", run_id="run-a", created_at=base)
    other = _run(
        db,
        workflow,
        "conversation-b",
        run_id="run-other",
        created_at=base - timedelta(seconds=1),
    )
    db.commit()
    executed = []

    def execute(run_db, run_id):
        row = run_db.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        executed.append(run_id)
        row.status = RUN_SUCCESS
        run_db.commit()
        return row

    lease = FakeLeaseClient()
    result = drain_serialized_runs(
        db,
        DEFAULT_TENANT_ID,
        workflow.id,
        correlation_digest("conversation-a"),
        lease_client=lease,
        execute=execute,
    )
    assert result == {"admitted": True, "drained": 2}
    assert executed == ["run-a", "run-b"]
    assert other.status == RUN_PENDING
    assert len(lease.acquired) == 1 and len(lease.released) == 1


def test_duplicate_wakeup_that_loses_lease_executes_nothing(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    run = _run(db, workflow, "conversation-a", run_id="pending-run")
    db.commit()
    executed = []
    result = drain_serialized_runs(
        db,
        DEFAULT_TENANT_ID,
        workflow.id,
        run.correlation_key_digest,
        lease_client=FakeLeaseClient(admitted=False),
        execute=lambda _db, run_id: executed.append(run_id),
    )
    assert result == {"admitted": False, "drained": 0}
    assert executed == []
    assert run.status == RUN_PENDING


def test_redis_outage_leaves_serialized_run_pending(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    run = _run(db, workflow, "conversation-a", run_id="redis-down")
    db.commit()
    with pytest.raises(SerializedCoordinationUnavailable, match="Redis"):
        drain_serialized_runs(
            db,
            DEFAULT_TENANT_ID,
            workflow.id,
            run.correlation_key_digest,
            lease_client=FakeLeaseClient(fail=True),
            execute=lambda *_args: pytest.fail("must not execute"),
        )
    db.expire_all()
    assert db.query(WorkflowRun).filter(WorkflowRun.id == run.id).one().status == RUN_PENDING


def test_in_process_crash_fails_only_that_run_and_keeps_draining(session_factory):
    """Mirror of the parallel task: an exception marks THIS run failed so a
    poison run cannot block its key forever; the next run still drains."""
    db = session_factory()
    workflow = _workflow(db)
    base = datetime.now(timezone.utc)
    crashed = _run(db, workflow, "conversation-a", run_id="crashed-run", created_at=base)
    _run(
        db,
        workflow,
        "conversation-a",
        run_id="next-run",
        created_at=base + timedelta(seconds=1),
    )
    db.commit()
    lease = FakeLeaseClient()
    executed = []

    def execute(run_db, run_id):
        row = run_db.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        executed.append(run_id)
        if run_id == "crashed-run":
            row.status = "running"
            run_db.flush()
            raise RuntimeError("worker crashed")
        row.status = RUN_SUCCESS
        run_db.commit()
        return row

    result = drain_serialized_runs(
        db,
        DEFAULT_TENANT_ID,
        workflow.id,
        crashed.correlation_key_digest,
        lease_client=lease,
        execute=execute,
    )
    assert result == {"admitted": True, "drained": 2}
    assert executed == ["crashed-run", "next-run"]
    db.expire_all()
    rows = {r.id: r for r in db.query(WorkflowRun).all()}
    assert rows["crashed-run"].status == RUN_FAILED
    assert rows["crashed-run"].error == "Run crashed unexpectedly."
    assert rows["next-run"].status == RUN_SUCCESS
    assert len(lease.released) == 1


def test_process_death_leaves_run_pending_for_redrive(session_factory):
    """A hard worker death never commits RUNNING (run_workflow only flushes it),
    so the abandoned transaction rolls back to Pending and the beat backstop
    re-drives the scope in order."""
    db = session_factory()
    workflow = _workflow(db)
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    run = _run(db, workflow, "conversation-a", run_id="abandoned", created_at=old)
    db.commit()
    # Simulate the worker dying after the claim: the RUNNING flush is never
    # committed, so the connection drop rolls it back.
    claimed = db.query(WorkflowRun).filter(WorkflowRun.id == run.id).one()
    claimed.status = "running"
    db.flush()
    db.rollback()

    db.expire_all()
    assert db.query(WorkflowRun).filter(WorkflowRun.id == run.id).one().status == RUN_PENDING
    wakes = []
    assert (
        redrive_pending_serialized_runs(
            db,
            now=datetime.now(timezone.utc),
            minimum_age=timedelta(minutes=1),
            wake=lambda *scope: wakes.append(scope),
        )
        == 1
    )
    assert wakes == [(DEFAULT_TENANT_ID, workflow.id, run.correlation_key_digest)]
    executed = []

    def execute(run_db, run_id):
        row = run_db.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        executed.append(run_id)
        row.status = RUN_SUCCESS
        run_db.commit()
        return row

    drain_serialized_runs(
        db,
        *wakes[0],
        lease_client=FakeLeaseClient(),
        execute=execute,
    )
    assert executed == [run.id]


def test_drain_stops_instead_of_spinning_when_a_run_never_leaves_pending(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    run = _run(db, workflow, "conversation-a", run_id="stuck-run")
    db.commit()
    calls = []
    result = drain_serialized_runs(
        db,
        DEFAULT_TENANT_ID,
        workflow.id,
        run.correlation_key_digest,
        lease_client=FakeLeaseClient(),
        execute=lambda _db, run_id: calls.append(run_id),
    )
    assert calls == ["stuck-run"]
    assert result == {"admitted": True, "drained": 1, "stalled": "stuck-run"}
    db.expire_all()
    assert db.query(WorkflowRun).filter(WorkflowRun.id == run.id).one().status == RUN_PENDING


def test_lost_lease_stops_drain_and_leaves_rest_pending(session_factory):
    """Lease expiry mid-queue: the current run finishes, the loop stops before
    the next run, and the remaining runs stay Pending for a fresh owner."""
    db = session_factory()
    workflow = _workflow(db)
    base = datetime.now(timezone.utc)
    _run(db, workflow, "conversation-a", run_id="first", created_at=base)
    _run(
        db,
        workflow,
        "conversation-a",
        run_id="second",
        created_at=base + timedelta(seconds=1),
    )
    db.commit()

    class ExpiringLease(FakeLeaseClient):
        def renew(self, key, token, ttl_seconds):
            return False

    executed = []

    def slow_execute(run_db, run_id):
        import time

        row = run_db.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        executed.append(run_id)
        time.sleep(1.5)  # outlive one heartbeat interval (ttl 3s -> 1s)
        row.status = RUN_SUCCESS
        run_db.commit()
        return row

    with pytest.raises(SerializedCoordinationUnavailable, match="lease was lost"):
        drain_serialized_runs(
            db,
            DEFAULT_TENANT_ID,
            workflow.id,
            correlation_digest("conversation-a"),
            lease_client=ExpiringLease(),
            execute=slow_execute,
            ttl_seconds=3,
        )
    assert executed == ["first"]
    db.expire_all()
    assert db.query(WorkflowRun).filter(WorkflowRun.id == "second").one().status == RUN_PENDING


def test_local_lease_admits_different_keys_and_rejects_same_key():
    from app.workflow_engine.serialization import LocalLeaseClient

    lease = LocalLeaseClient()
    assert lease.acquire("k1", "t1", 10) is True
    assert lease.acquire("k2", "t2", 10) is True  # different key drains concurrently
    assert lease.acquire("k1", "t3", 10) is False  # same key: one owner
    assert lease.renew("k1", "t3", 10) is False  # a non-owner cannot renew
    assert lease.release("k1", "t3") is False  # or release
    assert lease.release("k1", "t1") is True
    assert lease.acquire("k1", "t3", 10) is True


def test_redis_lease_is_token_owned():
    import fakeredis

    from app.workflow_engine.serialization import RedisLeaseClient

    lease = RedisLeaseClient(fakeredis.FakeRedis(decode_responses=True))
    assert lease.acquire("k", "owner", 30) is True
    assert lease.acquire("k", "intruder", 30) is False
    assert lease.renew("k", "intruder", 30) is False
    assert lease.release("k", "intruder") is False
    assert lease.renew("k", "owner", 30) is True
    assert lease.client.ttl("k") > 0
    assert lease.release("k", "owner") is True
    assert lease.acquire("k", "intruder", 30) is True


def test_recovery_redrives_each_oldest_pending_serialized_scope(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    _run(db, workflow, "conversation-a", run_id="a-1", created_at=old)
    _run(db, workflow, "conversation-a", run_id="a-2", created_at=old)
    _run(db, workflow, "conversation-b", run_id="b-1", created_at=old)
    db.commit()
    wakes = []
    count = redrive_pending_serialized_runs(
        db,
        now=datetime.now(timezone.utc),
        minimum_age=timedelta(minutes=1),
        wake=lambda *scope: wakes.append(scope),
    )
    assert count == 2
    assert set(wakes) == {
        (DEFAULT_TENANT_ID, workflow.id, correlation_digest("conversation-a")),
        (DEFAULT_TENANT_ID, workflow.id, correlation_digest("conversation-b")),
    }


def test_duplicate_direct_execution_does_not_execute_run_nodes_twice(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    definition = {
        "schemaVersion": 2,
        "execution": {"mode": "parallel", "correlationKey": ""},
        "nodes": [
            {
                "id": "trigger",
                "kind": "trigger",
                "type": "manual",
                "config": {},
                "position": {},
            }
        ],
        "edges": [],
    }
    run = WorkflowRun(
        id="duplicate-direct-run",
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=definition,
        trigger_payload_json={"triggeredBy": "manual"},
    )
    assign_run_correlation(run)
    db.add(run)
    db.commit()
    from app.models.workflow import WorkflowRunNode
    from app.workflow_engine.executor import run_workflow

    first = run_workflow(db, run.id)
    second = run_workflow(db, run.id)
    assert first.status == RUN_SUCCESS and second.status == RUN_SUCCESS
    assert (
        db.query(WorkflowRunNode)
        .filter(WorkflowRunNode.run_id == run.id)
        .count()
        == 1
    )
