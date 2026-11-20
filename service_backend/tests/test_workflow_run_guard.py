"""Plan 38 gap 7, slice S2: the core run guard seam (no omnichannel).

Contract (plan 38, "Wire contract", S2 core seam): `app.workflow_engine.executor`
gets `register_run_guard(fn)`, `unregister_run_guard(fn)` and
`class RunRefused(Exception)` with `.code` and a message. A guard is
`fn(db, run, doc) -> None`. A guard that raises `RunRefused` fails the run
(status `failed`, `run.error` holds the code and the message) before any node
executes. `debug_execute` raises it to its caller, with no node executed.
With no guard registered nothing changes.

Everything new is imported lazily so each test fails on its own.
Assumption (flagged to the coordinator): `RunRefused(code, message)`.
"""
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import (
    NODE_RUNNING,
    NODE_SUCCESS,
    RUN_FAILED,
    RUN_PENDING,
    RUN_SUCCESS,
    Workflow,
    WorkflowRun,
)
from app.workflow_engine import registry
from app.workflow_engine.executor import debug_execute, run_workflow
from app.workflow_engine.registry import ActionDef, register_action

SPY_KEY = "test.run_guard_spy"


@pytest.fixture
def spy():
    calls = []

    def _exec(db, tenant_id, config, ctx):
        calls.append(config)
        return {"ok": True}

    register_action(
        ActionDef(
            key=SPY_KEY, label="Run guard spy", description="test", icon="Zap",
            category="Actions", executor=_exec,
        )
    )
    yield calls
    registry._ACTIONS.pop(SPY_KEY, None)


@pytest.fixture
def db(session_factory):
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


DOC = {
    "schemaVersion": 1,
    "nodes": [
        {"id": "trg", "kind": "trigger", "type": "manual", "config": {}},
        {"id": "spy_1", "kind": "action", "type": SPY_KEY, "config": {"n": 1}},
        {"id": "spy_2", "kind": "action", "type": SPY_KEY, "config": {"n": 2}},
    ],
    "edges": [
        {"id": "e1", "source": "trg", "target": "spy_1"},
        {"id": "e2", "source": "spy_1", "target": "spy_2"},
    ],
}


def _run(db):
    wf = Workflow(tenant_id=DEFAULT_TENANT_ID, name="guarded", description="",
                  draft_definition_json=DOC, created_by="test")
    db.add(wf)
    db.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID, workflow_id=wf.id, status=RUN_PENDING,
        definition_snapshot_json=DOC, trigger_payload_json={"triggeredBy": "manual"},
    )
    db.add(run)
    db.flush()
    return run


def test_guard_refusal_fails_run_with_no_node_executed(db, spy):
    from app.workflow_engine.executor import RunRefused, register_run_guard, unregister_run_guard

    seen = []

    def guard(db_, run, doc):
        seen.append((run.id, [n.id for n in doc.nodes]))
        raise RunRefused("test_refused", "Node spy_1 is refused by the test guard.")

    register_run_guard(guard)
    try:
        run = _run(db)
        result = run_workflow(db, run.id)  # a refusal never raises out of run_workflow
        assert seen and seen[0][0] == run.id
        assert seen[0][1] == ["trg", "spy_1", "spy_2"]
        assert result.status == RUN_FAILED
        assert "test_refused" in (result.error or "")
        assert "Node spy_1 is refused by the test guard." in (result.error or "")
        assert spy == [], "no node may execute"
        assert [n for n in result.nodes if n.status in (NODE_SUCCESS, NODE_RUNNING)] == []

        # the debug path raises the refusal to its caller and runs nothing
        dbg = _run(db)
        with pytest.raises(RunRefused) as exc:
            debug_execute(db, dbg, target_node_id="spy_2", scratch={}, stale_node_ids=[])
        assert exc.value.code == "test_refused"
        assert "spy_1" in str(exc.value)
        assert spy == []
    finally:
        unregister_run_guard(guard)

    # after unregistering, the same definition runs normally (control)
    run2 = _run(db)
    result = run_workflow(db, run2.id)
    assert result.status == RUN_SUCCESS
    assert len(spy) == 2


def test_no_guard_no_change(db, spy):
    """Control: with no guard registered a run executes every node, and the
    seam exists (importing it is the red part)."""
    from app.workflow_engine import executor

    assert callable(executor.register_run_guard)
    assert callable(executor.unregister_run_guard)
    assert issubclass(executor.RunRefused, Exception)

    run = _run(db)
    result = run_workflow(db, run.id)
    assert result.status == RUN_SUCCESS
    assert [c["n"] for c in spy] == [1, 2]
    assert all(n.status == NODE_SUCCESS for n in result.nodes)

    # a guard that allows (returns None) changes nothing
    def allow(db_, run_, doc):
        return None

    executor.register_run_guard(allow)
    try:
        run2 = _run(db)
        assert run_workflow(db, run2.id).status == RUN_SUCCESS
        assert len(spy) == 4
    finally:
        executor.unregister_run_guard(allow)
