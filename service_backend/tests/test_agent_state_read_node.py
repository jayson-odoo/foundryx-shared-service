"""Plan sprint-4/20 - Read-only Agent State workflow node (AC-ASR-05..11).

Mirrors the setup style of ``tests/test_stateful_ai_runtime.py`` /
``tests/test_code_workflow_action.py``: build the AiAgent/Workflow/WorkflowRun
rows directly and exercise the action + executor at the public seam.
"""
import pytest

from app.ai.stub import StubResponse, stub_fixtures
from app.models import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID, User
from app.models.ai import AiAgent
from app.models.workflow import (
    NODE_FAILED,
    NODE_SKIPPED,
    RUN_PENDING,
    Workflow,
    WorkflowAgentState,
    WorkflowRun,
)
from app.services.agent_state_service import AgentStateService
from app.workflow_engine.actions.agent_state_actions import ActionError, read_agent_state
from app.workflow_engine.actions.ai_agent_actions import ai_agent_run
from app.workflow_engine.executor import debug_execute, run_workflow
from app.workflow_engine.schemas import definition_issues, parse_definition


def _actor(db):
    return db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID).first()


def _agent(db, tenant_id=DEFAULT_TENANT_ID):
    agent = AiAgent(tenant_id=tenant_id, name="Read-state agent", model="stub-model-1", connection_id=None)
    db.add(agent)
    db.flush()
    return agent


def _schema():
    return [
        {"key": "task", "type": "string", "stateful": True},
        {
            "key": "status",
            "type": "enum",
            "enumValues": ["in_progress", "completed", "blocked"],
            "stateful": True,
        },
        {"key": "reply", "type": "string"},
    ]


def _workflow(db, doc=None, tenant_id=DEFAULT_TENANT_ID):
    workflow = Workflow(
        tenant_id=tenant_id,
        name="Read-state workflow",
        description="",
        draft_definition_json=doc or {"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    return workflow


def _node(nid, kind, ntype, config=None):
    return {"id": nid, "kind": kind, "type": ntype, "config": config or {}, "position": {"x": 0, "y": 0}}


def _edge(src, tgt, port="out"):
    return {"id": f"e_{src}_{tgt}_{port}", "source": src, "target": tgt, "sourcePort": port}


# ---- direct action tests ---------------------------------------------------


def test_read_agent_state_flattens_accepted_fields_and_diagnostics(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    row = AgentStateService(db).save_initial(
        DEFAULT_TENANT_ID,
        workflow.id,
        "agent_1",
        "conversation_1",
        {"task": "Launch page", "status": "blocked"},
        {"task": {"evidence": "launch"}},
        pending_question="What is the deadline?",
        pending_field="deadline",
    )
    ctx = {
        "_workflow.workflowId": workflow.id,
        "_workflow.correlationKey": "conversation_1",
        "_workflow.statefulAgentIds": ["agent_1"],
    }
    result = read_agent_state(db, DEFAULT_TENANT_ID, {"agentNodeId": "agent_1"}, ctx)
    assert result == {
        "task": "Launch page",
        "status": "blocked",
        "stateRevision": row.revision,
        "pendingField": "deadline",
        "exists": True,
    }


def test_read_agent_state_no_row_yields_defaults_and_run_continues(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    ctx = {
        "_workflow.workflowId": workflow.id,
        "_workflow.correlationKey": "never_seen",
        "_workflow.statefulAgentIds": ["agent_1"],
    }
    result = read_agent_state(db, DEFAULT_TENANT_ID, {"agentNodeId": "agent_1"}, ctx)
    assert result == {"stateRevision": 0, "pendingField": None, "exists": False}
    # No field outputs and no row was ever created for this key.
    assert "task" not in result
    assert db.query(WorkflowAgentState).count() == 0


def test_read_agent_state_never_writes_or_bumps_revision(session_factory):
    """Read-only contract (AC-ASR-06): reading must not create a row or move
    the revision. Paired with a WRITE-path control (``ai_agent_run``) that
    DOES move the revision, so this isn't passing "by accident" (the
    rollback-test lesson - a no-op assertion needs a mutation control)."""
    db = session_factory()
    agent = _agent(db)
    workflow = _workflow(db)
    row = AgentStateService(db).save_initial(
        DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1",
        {"task": "Launch page"}, {},
    )
    before_revision = row.revision
    assert db.query(WorkflowAgentState).count() == 1

    ctx = {
        "_workflow.workflowId": workflow.id,
        "_workflow.correlationKey": "conversation_1",
        "_workflow.statefulAgentIds": ["agent_1"],
    }
    for _ in range(3):
        result = read_agent_state(db, DEFAULT_TENANT_ID, {"agentNodeId": "agent_1"}, ctx)
        assert result["stateRevision"] == before_revision
    assert db.query(WorkflowAgentState).count() == 1
    db.refresh(row)
    assert row.revision == before_revision

    # Control: the WRITE path (the AI Agent reducer) DOES move the revision -
    # proves the assertion above is a real read/write distinction, not a
    # tautology (a broken CAS bumping nothing would pass silently otherwise).
    ai_config = {
        "agentId": agent.id,
        "instructions": "Collect the task.",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": _schema(),
    }
    ai_ctx = {
        "trigger.message.text": "Still blocked.",
        "trigger.message.id": "message_1",
        "_workflow.runId": "run_1",
        "_workflow.workflowId": workflow.id,
        "_workflow.nodeId": "agent_1",
        "_workflow.correlationKey": "conversation_1",
        "_workflow.isTest": False,
    }
    with stub_fixtures(
        StubResponse(
            structured={
                "outputs": {},
                "statePatches": {"status": {"operation": "set", "value": "blocked", "evidence": "blocked"}},
                "pendingField": None,
            }
        )
    ):
        ai_agent_run(db, DEFAULT_TENANT_ID, ai_config, ai_ctx)
    db.refresh(row)
    assert row.revision == before_revision + 1
    assert db.query(WorkflowAgentState).count() == 1


def test_read_agent_state_namespace_isolation_test_vs_prod(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    service = AgentStateService(db)
    service.save_initial(
        DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1",
        {"task": "prod value"}, {}, namespace="prod",
    )
    service.save_initial(
        DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1",
        {"task": "test value"}, {}, namespace="test",
    )
    base_ctx = {
        "_workflow.workflowId": workflow.id,
        "_workflow.correlationKey": "conversation_1",
        "_workflow.statefulAgentIds": ["agent_1"],
    }
    prod_result = read_agent_state(
        db, DEFAULT_TENANT_ID, {"agentNodeId": "agent_1"},
        {**base_ctx, "_workflow.agentStateNamespace": "prod"},
    )
    test_result = read_agent_state(
        db, DEFAULT_TENANT_ID, {"agentNodeId": "agent_1"},
        {**base_ctx, "_workflow.isTest": True},
    )
    assert prod_result["task"] == "prod value"
    assert test_result["task"] == "test value"


def test_read_agent_state_missing_or_removed_agent_raises_action_error(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    ctx = {
        "_workflow.workflowId": workflow.id,
        "_workflow.correlationKey": "conversation_1",
        # The referenced node is no longer a stateful agent in this graph
        # (e.g. removed/edited after the read node was configured).
        "_workflow.statefulAgentIds": ["agent_other"],
    }
    with pytest.raises(ActionError):
        read_agent_state(db, DEFAULT_TENANT_ID, {"agentNodeId": "agent_1"}, ctx)


def test_read_agent_state_requires_correlation_key(session_factory):
    db = session_factory()
    workflow = _workflow(db)
    ctx = {
        "_workflow.workflowId": workflow.id,
        "_workflow.statefulAgentIds": ["agent_1"],
    }
    with pytest.raises(ActionError):
        read_agent_state(db, DEFAULT_TENANT_ID, {"agentNodeId": "agent_1"}, ctx)


def test_read_agent_state_is_tenant_scoped(session_factory):
    db = session_factory()
    workflow = _workflow(db, tenant_id=DEFAULT_TENANT_ID)
    AgentStateService(db).save_initial(
        DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1",
        {"task": "tenant secret"}, {},
    )
    ctx = {
        "_workflow.workflowId": workflow.id,
        "_workflow.correlationKey": "conversation_1",
        "_workflow.statefulAgentIds": ["agent_1"],
    }
    # A different tenant does not own this workflow at all - reading through
    # it must never surface the other tenant's accepted state.
    with pytest.raises(Exception):
        read_agent_state(db, PLATFORM_TENANT_ID, {"agentNodeId": "agent_1"}, ctx)


# ---- executor: structural reachability (AC-ASR-09) --------------------------


def test_executor_reads_durable_state_on_a_branch_that_never_ran_the_agent(session_factory):
    """The read node sits on the FALSE branch of an IF; the agent node sits on
    the (untaken) TRUE branch and never executes this run. The read must
    still succeed and report the pre-seeded durable state (D4 - structural
    reachability, not executed-this-pass)."""
    db = session_factory()
    agent = _agent(db)
    workflow = _workflow(db)
    # Pre-seed durable state as if a prior run's AI Agent already accepted it.
    AgentStateService(db).save_initial(
        DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1",
        {"task": "Launch page"}, {}, namespace="prod",
    )
    doc = {
        "schemaVersion": 2,
        "execution": {"mode": "serialized", "correlationKey": "{{ trigger.conversationId }}"},
        "nodes": [
            _node("trigger", "trigger", "manual", {"inputs": [{"key": "route", "label": "Route", "type": "text"}]}),
            _node("cond", "if", "if", {
                "conditions": {
                    "kind": "group",
                    "combinator": "and",
                    "rules": [
                        {"kind": "condition", "fact": "trigger.input.route", "operator": "equals", "valueKind": "literal", "value": "agent"},
                    ],
                }
            }),
            _node("agent_1", "action", "ai_agent.run", {
                "agentId": agent.id, "instructions": "Collect", "inputText": "{{ trigger.message.text }}",
                "outputParams": [{"key": "task", "type": "string", "stateful": True}],
            }),
            _node("read_1", "action", "ai_agent.read_state", {"agentNodeId": "agent_1"}),
        ],
        "edges": [
            _edge("trigger", "cond"),
            _edge("cond", "agent_1", "true"),
            _edge("cond", "read_1", "false"),
        ],
    }
    workflow.draft_definition_json = doc
    db.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        triggered_by="event",
        is_test=False,
        definition_snapshot_json=doc,
        trigger_payload_json={
            "triggeredBy": "event",
            "input": {"route": "skip"},
            "omnichannel": {"conversationId": "conversation_1"},
        },
    )
    db.add(run)
    db.flush()

    result = run_workflow(db, run.id)
    assert result.status == "success"
    nodes_by_id = {n.node_id: n for n in result.nodes}
    assert nodes_by_id["agent_1"].status == "skipped"
    assert nodes_by_id["read_1"].status == "success"
    assert nodes_by_id["read_1"].output_json["task"] == "Launch page"
    assert nodes_by_id["read_1"].output_json["exists"] is True


# ---- node-failure isolation, never a 500 (AC-ASR-11) -----------------------


def _missing_agent_doc():
    return {
        "schemaVersion": 2,
        "execution": {"mode": "serialized", "correlationKey": "{{ trigger.conversationId }}"},
        "nodes": [
            _node("trigger", "trigger", "manual"),
            # References an agent node id that is NOT present in this graph -
            # the "draft run after an edit" scenario (AC-ASR-11).
            _node("read_1", "action", "ai_agent.read_state", {"agentNodeId": "agent_removed"}),
            _node("downstream", "action", "email.send", {"mode": "custom", "to": "a@b.com", "subject": "S", "body": "B"}),
        ],
        "edges": [_edge("trigger", "read_1"), _edge("read_1", "downstream")],
    }


def test_run_workflow_marks_read_state_failed_and_skips_downstream_on_missing_agent(session_factory):
    db = session_factory()
    doc = _missing_agent_doc()
    workflow = _workflow(db, doc)
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=doc,
        trigger_payload_json={"triggeredBy": "manual", "omnichannel": {"conversationId": "conversation_1"}},
    )
    db.add(run)
    db.flush()

    result = run_workflow(db, run.id)  # must not raise - a node failure never 500s
    assert result.status == "failed"
    nodes_by_id = {n.node_id: n for n in result.nodes}
    assert nodes_by_id["read_1"].status == NODE_FAILED
    assert "not part of this workflow" in (nodes_by_id["read_1"].error or "")
    assert nodes_by_id["downstream"].status == NODE_SKIPPED


def test_debug_execute_marks_read_state_failed_without_raising_and_never_runs_the_target(session_factory):
    """The editor's Execute-node / Logs replay path (``debug_execute``) must
    fail the same way ``run_workflow`` does: record the failing node and stop,
    never propagate the ActionError as an uncaught 500."""
    db = session_factory()
    doc = _missing_agent_doc()
    workflow = _workflow(db, doc)
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=doc,
        trigger_payload_json={"triggeredBy": "manual", "omnichannel": {"conversationId": "conversation_1"}},
    )
    db.add(run)
    db.flush()

    # Explicit target is the downstream node ("Execute this node" in the
    # editor) - its upstream read node never produced output before, so it
    # must run first, fails, and the pass halts without raising.
    touched = debug_execute(db, run, target_node_id="downstream", scratch={}, stale_node_ids=[])
    by_id = {t["nodeId"]: t for t in touched}
    assert by_id["read_1"]["status"] == NODE_FAILED
    assert "not part of this workflow" in (by_id["read_1"]["error"] or "")
    assert "downstream" not in by_id


# ---- publish gate parity (AC-ASR-10) ----------------------------------------


def _stateful_agent_node(nid="agent_1"):
    return _node(nid, "action", "ai_agent.run", {
        "agentId": "any-agent-id", "instructions": "x", "inputText": "x",
        "outputParams": [{"key": "task", "type": "string", "stateful": True}],
    })


def test_definition_issues_blocks_read_state_without_a_stateful_target():
    doc = parse_definition({
        "schemaVersion": 2,
        "nodes": [
            _node("trigger", "trigger", "manual"),
            _node("read_1", "action", "ai_agent.read_state", {"agentNodeId": "missing"}),
        ],
        "edges": [_edge("trigger", "read_1")],
    })
    issues = definition_issues(doc)
    assert any("Read Agent State must reference a stateful AI Agent" in issue for issue in issues)


def test_definition_issues_allows_read_state_referencing_a_stateful_agent():
    doc = parse_definition({
        "schemaVersion": 2,
        "execution": {"mode": "serialized", "correlationKey": "{{ trigger.conversationId }}"},
        "nodes": [
            _node("trigger", "trigger", "manual"),
            _stateful_agent_node("agent_1"),
            _node("read_1", "action", "ai_agent.read_state", {"agentNodeId": "agent_1"}),
        ],
        "edges": [_edge("trigger", "agent_1"), _edge("agent_1", "read_1")],
    })
    issues = definition_issues(doc)
    assert not any("Read Agent State must reference a stateful AI Agent" in issue for issue in issues)


def test_definition_issues_blocks_read_state_referencing_a_non_stateful_agent():
    doc = parse_definition({
        "schemaVersion": 2,
        "nodes": [
            _node("trigger", "trigger", "manual"),
            _node("agent_1", "action", "ai_agent.run", {
                "agentId": "any-agent-id", "instructions": "x", "inputText": "x",
                "outputParams": [{"key": "reply", "type": "string"}],
            }),
            _node("read_1", "action", "ai_agent.read_state", {"agentNodeId": "agent_1"}),
        ],
        "edges": [_edge("trigger", "agent_1"), _edge("agent_1", "read_1")],
    })
    issues = definition_issues(doc)
    assert any("Read Agent State must reference a stateful AI Agent" in issue for issue in issues)
