"""S1 stateful AI workflow runtime tests (AC-SAR-14..32).

These tests start at the public workflow action/service seams and use the
existing SQLite fixture only for fast feedback. Migration smoke is covered
separately against Postgres because ``create_all`` cannot validate Alembic.
"""

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.ai.stub import StubResponse, stub_fixtures
from app.models import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID, User
from app.models.ai import AiAgent, AiSpan
from app.models.workflow import RUN_PENDING, Workflow, WorkflowAgentState, WorkflowRun
from app.repositories.agent_state_repository import AgentStateRepository
from app.services.agent_state_service import AgentStateService
from app.workflow_engine.actions.ai_agent_actions import ai_agent_run
from app.workflow_engine.actions.agent_state_actions import clear_agent_state
from app.workflow_engine.agent_state import reduce_agent_state
from app.workflow_engine.executor import resolve_correlation_key
from app.workflow_engine.schemas import definition_issues, parse_definition


def _actor(db):
    return db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID).first()


def _agent(db):
    agent = AiAgent(
        tenant_id=DEFAULT_TENANT_ID,
        name="State agent",
        model="stub-model-1",
        connection_id=None,
    )
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


def _scope(*, test_namespace=False):
    return {
        "tenant_id": DEFAULT_TENANT_ID,
        "workflow_id": "workflow_1",
        "node_id": "agent_1",
        "correlation_key": "conversation_1",
        "namespace": "test" if test_namespace else "production",
    }


def test_agent_state_model_and_repository_are_tenant_scoped(session_factory):
    db = session_factory()
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="State workflow",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    scope = {**_scope(), "workflow_id": workflow.id}
    state = AgentStateService(db).save_initial(**scope, state={}, provenance={})
    assert state.tenant_id == DEFAULT_TENANT_ID
    assert AgentStateRepository(db).get(
        PLATFORM_TENANT_ID,
        workflow.id,
        "agent_1",
        "conversation_1",
    ) is None


def test_reducer_applies_independent_evidence_backed_set_and_clear():
    result = reduce_agent_state(
        {},
        {},
        {
            "task": {"operation": "set", "value": "Launch page", "evidence": "launch page"},
            "status": {"operation": "set", "value": "blocked", "evidence": "blocked"},
        },
        "The launch page is blocked.",
        _schema(),
        run_id="run_1",
        message_id="message_1",
        now=datetime.now(timezone.utc),
    )
    assert result.state == {"task": "Launch page", "status": "blocked"}
    assert result.changed_fields == ["task", "status"]
    assert result.rejected_fields == []
    assert result.provenance["task"]["evidence"] == "launch page"

    cleared = reduce_agent_state(
        result.state,
        result.provenance,
        {"status": {"operation": "clear", "evidence": "blocked"}},
        "The launch page is no longer blocked.",
        _schema(),
        run_id="run_2",
        message_id="message_2",
        now=datetime.now(timezone.utc),
    )
    assert cleared.state == {"task": "Launch page"}
    assert cleared.provenance.get("status") is None


def test_reducer_rejects_prior_state_as_current_evidence_but_keeps_other_fields():
    result = reduce_agent_state(
        {"task": "Launch page"},
        {"task": {"runId": "old"}},
        {
            "task": {"operation": "set", "value": "Launch page", "evidence": "Launch page"},
            "status": {"operation": "set", "value": "completed", "evidence": "done"},
        },
        "Done for today.",
        _schema(),
        run_id="run_3",
        message_id="message_3",
        now=datetime.now(timezone.utc),
    )
    assert result.state == {"task": "Launch page", "status": "completed"}
    assert result.rejected_fields == ["task"]


def test_definition_v1_defaults_parallel_and_stateful_requires_serialized_key():
    legacy = parse_definition({"schemaVersion": 1, "nodes": [], "edges": []})
    assert legacy.execution is None
    assert resolve_correlation_key(legacy, {}) is None

    node = {
        "id": "agent_1",
        "kind": "action",
        "type": "ai_agent.run",
        "config": {
            "agentId": "agent",
            "instructions": "Collect",
            "inputText": "{{ trigger.message.text }}",
            "outputParams": [{"key": "task", "type": "string", "stateful": True}],
        },
        "position": {},
    }
    doc = parse_definition(
        {
            "schemaVersion": 2,
            "execution": {"mode": "parallel", "correlationKey": ""},
            "nodes": [{"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}}, node],
            "edges": [{"id": "e", "source": "trigger", "target": "agent_1"}],
        }
    )
    assert any("serialized execution" in issue for issue in definition_issues(doc))

    serialized = parse_definition(
        {
            "schemaVersion": 2,
            "execution": {"mode": "serialized", "correlationKey": "{{ trigger.conversationId }}"},
            "nodes": [],
            "edges": [],
        }
    )
    assert resolve_correlation_key(serialized, {"trigger.conversationId": "conversation_1"}) == "conversation_1"


def test_schema_evolution_drops_removed_transient_and_invalid_enum_values():
    result = reduce_agent_state(
        {"task": "old", "status": "obsolete", "removed": "discard", "reply": "transient"},
        {"task": {"runId": "old"}, "status": {"runId": "old"}},
        {"task": {"operation": "no_change"}},
        "No change.",
        [
            {"key": "task", "type": "string", "stateful": True},
            {"key": "status", "type": "enum", "enumValues": ["ready", "blocked"], "stateful": True},
            {"key": "reply", "type": "string"},
        ],
        run_id="run_1",
        message_id=None,
        now=datetime.now(timezone.utc),
    )
    assert result.state == {"task": "old"}
    assert result.rejected_fields == ["status", "removed", "reply"]


def test_stateful_prompt_projects_schema_before_call_and_contains_no_transcript(
    session_factory,
):
    db = session_factory()
    agent = _agent(db)
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Prompt projection",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    AgentStateService(db).save_initial(
        DEFAULT_TENANT_ID,
        workflow.id,
        "agent_1",
        "conversation_1",
        {"task": "Launch page", "removed": "old value", "status": "obsolete"},
        {
            "task": {
                "runId": "old_run",
                "messageId": "old_message",
                "evidence": "old transcript secret",
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    config = {
        "agentId": agent.id,
        "instructions": "Collect only the current update.",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": [
            {
                "key": "task",
                "type": "string",
                "description": "The task being updated",
                "stateful": True,
            },
            {
                "key": "status",
                "type": "enum",
                "description": "Current task status",
                "enumValues": ["in_progress", "completed"],
                "stateful": True,
            },
        ],
    }
    ctx = {
        "trigger.message.text": "Still working today.",
        "trigger.message.id": "current_message",
        "_workflow.runId": "current_run",
        "_workflow.workflowId": workflow.id,
        "_workflow.nodeId": "agent_1",
        "_workflow.correlationKey": "conversation_1",
        "_workflow.agentStateNamespace": "prod",
    }
    with stub_fixtures(
        StubResponse(
            structured={
                "outputs": {},
                "statePatches": {
                    "task": {"operation": "no_change"},
                    "status": {"operation": "no_change"},
                },
            }
        )
    ):
        ai_agent_run(db, DEFAULT_TENANT_ID, config, ctx)

    span = db.query(AiSpan).order_by(AiSpan.started_at.desc()).first()
    prompt = json.loads(span.input_json["messages"][0]["content"])
    assert prompt["currentMessage"] == "Still working today."
    assert prompt["acceptedState"] == {"task": "Launch page"}
    assert prompt["pendingClarification"] is None
    assert prompt["outputParameters"][0]["description"] == "The task being updated"
    assert prompt["outputParameters"][1]["enumValues"] == [
        "in_progress",
        "completed",
    ]
    assert "old transcript secret" not in span.input_json["messages"][0]["content"]


def test_reducer_preserves_no_change_and_ambiguous_fields_independently():
    result = reduce_agent_state(
        {"task": "Launch", "status": "blocked"},
        {"task": {"runId": "old"}, "status": {"runId": "old"}},
        {
            "task": {"operation": "no_change"},
            "status": {"operation": "ambiguous", "evidence": "blocked"},
        },
        "The launch is still blocked.",
        _schema(),
        run_id="run_4",
        message_id="message_4",
        now=datetime.now(timezone.utc),
    )
    assert result.state == {"task": "Launch", "status": "blocked"}
    assert result.rejected_fields == ["status"]
    assert result.provenance["task"] == {"runId": "old"}


def test_reducer_rejects_each_invalid_type_enum_and_evidence_without_cross_field_loss():
    result = reduce_agent_state(
        {},
        {},
        {
            "task": {"operation": "set", "value": 42, "evidence": "task"},
            "status": {"operation": "set", "value": "unknown", "evidence": "status"},
            "reply": {"operation": "set", "value": "ok", "evidence": "not present"},
            "count": {"operation": "set", "value": "two", "evidence": "two"},
            "active": {"operation": "set", "value": "yes", "evidence": "yes"},
        },
        "The status is blocked and the count is two.",
        [
            {"key": "task", "type": "string", "stateful": True},
            {"key": "status", "type": "enum", "enumValues": ["ready", "blocked"], "stateful": True},
            {"key": "reply", "type": "string", "stateful": True},
            {"key": "count", "type": "number", "stateful": True},
            {"key": "active", "type": "boolean", "stateful": True},
        ],
        run_id="run_invalid",
        message_id="message_invalid",
        now=datetime.now(timezone.utc),
    )
    assert result.state == {}
    assert result.rejected_fields == ["task", "status", "reply", "count", "active"]


def test_agent_state_has_no_inactivity_expiry(session_factory):
    db = session_factory()
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Long-lived state",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    service = AgentStateService(db)
    row = service.save_initial(
        DEFAULT_TENANT_ID,
        workflow.id,
        "agent_1",
        "conversation_1",
        {"task": "retained"},
        {"task": {"runId": "old"}},
    )
    assert service.load(DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1").state_json == {"task": "retained"}
    assert row.created_at is not None


def test_repository_compare_and_swap_rejects_stale_revision(session_factory):
    db = session_factory()
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="CAS workflow",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    row = AgentStateService(db).save_initial(
        DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1", {}, {}
    )
    repository = AgentStateRepository(db)
    assert repository.compare_and_swap(
        row,
        expected_revision=0,
        state={"task": "one"},
        provenance={},
        pending_question=None,
        pending_field=None,
    )
    assert not repository.compare_and_swap(
        row,
        expected_revision=0,
        state={"task": "stale"},
        provenance={},
        pending_question=None,
        pending_field=None,
    )


def test_pending_short_answer_resolves_only_target_field(session_factory):
    db = session_factory()
    agent = _agent(db)
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Clarification workflow",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    config = {
        "agentId": agent.id,
        "instructions": "Collect the task.",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": _schema(),
        "clarificationOutputKey": "reply",
    }
    base = {
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
                "outputs": {"reply": "What is the task?"},
                "statePatches": {},
                "pendingField": "task",
            }
        ),
        StubResponse(
            structured={
                "outputs": {"reply": "Thanks."},
                "statePatches": {
                    "task": {"operation": "set", "value": "Yes", "evidence": "yes"}
                },
                "pendingField": None,
            }
        ),
    ):
        ai_agent_run(db, DEFAULT_TENANT_ID, config, {**base, "trigger.message.text": "Please confirm."})
        output = ai_agent_run(db, DEFAULT_TENANT_ID, config, {**base, "_workflow.runId": "run_2", "trigger.message.text": "yes"})
    row = AgentStateService(db).load(DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1")
    assert output["task"] == "Yes"
    assert row is not None and row.pending_question is None and row.pending_field is None


def test_missing_or_disabled_agent_fails_cleanly(session_factory):
    db = session_factory()
    with pytest.raises(Exception, match="not found"):
        ai_agent_run(
            db,
            DEFAULT_TENANT_ID,
            {"agentId": "missing", "instructions": "x", "inputText": "x", "outputParams": [{"key": "x", "type": "string"}]},
            {},
        )
    agent = _agent(db)
    agent.is_enabled = False
    with pytest.raises(Exception, match="disabled"):
        ai_agent_run(
            db,
            DEFAULT_TENANT_ID,
            {"agentId": agent.id, "instructions": "x", "inputText": "x", "outputParams": [{"key": "x", "type": "string"}]},
            {},
        )


def test_executor_clear_uses_private_test_namespace_and_reachable_stateful_node(session_factory):
    db = session_factory()
    agent = _agent(db)
    workflow_doc = {
        "schemaVersion": 2,
        "execution": {"mode": "serialized", "correlationKey": "{{ trigger.conversationId }}"},
        "nodes": [
            {"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}},
            {"id": "agent_1", "kind": "action", "type": "ai_agent.run", "config": {
                "agentId": agent.id, "instructions": "Collect", "inputText": "{{ trigger.message.text }}",
                "outputParams": [{"key": "task", "type": "string", "stateful": True}],
            }, "position": {}},
            {"id": "clear", "kind": "action", "type": "ai_agent.clear_state", "config": {"agentNodeId": "agent_1"}, "position": {}},
        ],
        "edges": [
            {"id": "e1", "source": "trigger", "target": "agent_1"},
            {"id": "e2", "source": "agent_1", "target": "clear"},
        ],
    }
    workflow = Workflow(tenant_id=DEFAULT_TENANT_ID, name="Executor", description="", draft_definition_json=workflow_doc)
    db.add(workflow)
    db.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        # Manual runs omit the frontend ``isTest`` flag but still use the test
        # Agent-state namespace. Production event runs are the only prod path.
        is_test=False,
        definition_snapshot_json=workflow_doc,
        trigger_payload_json={"triggeredBy": "manual", "omnichannel": {"conversationId": "conversation_1", "messageText": "launch"}},
    )
    db.add(run)
    db.flush()
    from app.workflow_engine.executor import run_workflow

    with stub_fixtures(StubResponse(structured={"outputs": {}, "statePatches": {"task": {"operation": "set", "value": "launch", "evidence": "launch"}}, "pendingField": None})):
        result = run_workflow(db, run.id)
    assert result.status == "success"
    state = AgentStateService(db).load(DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1", namespace="test")
    assert state is not None and state.state_json == {}


def test_debug_execute_forces_test_agent_state_namespace_for_production_run(session_factory):
    db = session_factory()
    agent = _agent(db)
    workflow_doc = {
        "schemaVersion": 2,
        "execution": {"mode": "serialized", "correlationKey": "{{ trigger.conversationId }}"},
        "nodes": [
            {"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}},
            {"id": "agent_1", "kind": "action", "type": "ai_agent.run", "config": {
                "agentId": agent.id, "instructions": "Collect", "inputText": "{{ trigger.message.text }}",
                "outputParams": [{"key": "task", "type": "string", "stateful": True}],
            }, "position": {}},
        ],
        "edges": [{"id": "e1", "source": "trigger", "target": "agent_1"}],
    }
    workflow = Workflow(tenant_id=DEFAULT_TENANT_ID, name="Debug namespace", description="", draft_definition_json=workflow_doc)
    db.add(workflow)
    db.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        triggered_by="event",
        is_test=False,
        definition_snapshot_json=workflow_doc,
        trigger_payload_json={"triggeredBy": "event", "omnichannel": {"conversationId": "conversation_1", "messageText": "launch"}},
    )
    db.add(run)
    db.flush()
    from app.workflow_engine.executor import debug_execute

    with stub_fixtures(StubResponse(structured={"outputs": {}, "statePatches": {"task": {"operation": "set", "value": "launch", "evidence": "launch"}}, "pendingField": None})):
        debug_execute(db, run, target_node_id="agent_1", scratch={}, stale_node_ids=[])
    assert AgentStateService(db).load(DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1", namespace="test") is not None
    assert AgentStateService(db).load(DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1", namespace="prod") is None


def test_both_agent_state_namespaces_are_prefixed_without_collision(session_factory):
    db = session_factory()
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Namespace collision",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    service = AgentStateService(db)
    service.save_initial(DEFAULT_TENANT_ID, workflow.id, "agent_1", "test:x", {"v": "prod"}, {})
    service.save_initial(
        DEFAULT_TENANT_ID,
        workflow.id,
        "agent_1",
        "x",
        {"v": "test"},
        {},
        namespace="test",
    )
    rows = AgentStateRepository(db).list_for_tenant(DEFAULT_TENANT_ID)
    assert {row.correlation_key for row in rows} == {"prod:test:x", "test:x"}
    assert service.load(DEFAULT_TENANT_ID, workflow.id, "agent_1", "test:x").state_json == {"v": "prod"}
    assert service.load(DEFAULT_TENANT_ID, workflow.id, "agent_1", "x", namespace="test").state_json == {"v": "test"}


def test_first_state_insert_race_requeries_existing_row_without_poisoning(session_factory, monkeypatch):
    db = session_factory()
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Race workflow",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    existing = WorkflowAgentState(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        node_id="agent_1",
        correlation_key="prod:conversation_1",
        state_json={},
        provenance_json={},
    )
    db.add(existing)
    db.flush()
    service = AgentStateService(db)
    original_get = service.repo.get
    first = True

    def raced_get(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            return None
        return original_get(*args, **kwargs)

    monkeypatch.setattr(service.repo, "get", raced_get)

    def duplicate_insert(*args, **kwargs):
        raise IntegrityError("duplicate", {}, Exception("duplicate"))

    monkeypatch.setattr(service.repo, "save_initial", duplicate_insert)
    row, _ = service.apply(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        node_id="agent_1",
        correlation_key="conversation_1",
        schema=[{"key": "task", "type": "string", "stateful": True}],
        patches={},
        message="No update.",
        run_id="race",
        message_id=None,
    )
    assert row.id == existing.id
    assert db.query(WorkflowAgentState).count() == 1


def test_stateful_action_rejects_undeclared_output_and_text_fallback(session_factory):
    db = session_factory()
    agent = _agent(db)
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Output contract",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    config = {
        "agentId": agent.id,
        "instructions": "Collect",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": [{"key": "task", "type": "string", "stateful": True}, {"key": "reply", "type": "string"}],
        "clarificationOutputKey": "reply",
    }
    ctx = {
        "trigger.message.text": "launch",
        "_workflow.runId": "run_output",
        "_workflow.workflowId": workflow.id,
        "_workflow.nodeId": "agent_1",
        "_workflow.correlationKey": "conversation_1",
        "_workflow.agentStateNamespace": "test",
    }
    with stub_fixtures(StubResponse(structured={"outputs": {"reply": "ok", "secret": "leak"}, "statePatches": {}})):
        output = ai_agent_run(db, DEFAULT_TENANT_ID, config, ctx)
    assert "secret" not in output
    with stub_fixtures(StubResponse(text="plain text")):
        with pytest.raises(Exception, match="structured"):
            ai_agent_run(db, DEFAULT_TENANT_ID, config, ctx)


def test_pending_requires_atomic_question_and_field(session_factory):
    db = session_factory()
    agent = _agent(db)
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Pending contract",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    config = {
        "agentId": agent.id,
        "instructions": "Collect",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": [{"key": "task", "type": "string", "stateful": True}],
    }
    ctx = {
        "trigger.message.text": "launch",
        "_workflow.runId": "run_pending",
        "_workflow.workflowId": workflow.id,
        "_workflow.nodeId": "agent_1",
        "_workflow.correlationKey": "conversation_1",
        "_workflow.agentStateNamespace": "test",
    }
    with stub_fixtures(StubResponse(structured={"outputs": {}, "statePatches": {}, "pendingField": "task"})):
        with pytest.raises(Exception, match="pending"):
            ai_agent_run(db, DEFAULT_TENANT_ID, config, ctx)


def test_omitted_pending_field_retains_the_existing_exact_pair(session_factory):
    db = session_factory()
    agent = _agent(db)
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Pending carry",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    service = AgentStateService(db)
    service.save_initial(
        DEFAULT_TENANT_ID,
        workflow.id,
        "agent_1",
        "conversation_1",
        {},
        {},
        pending_question="What is the task?",
        pending_field="task",
        namespace="test",
    )
    config = {
        "agentId": agent.id,
        "instructions": "Collect",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": [
            {"key": "task", "type": "string", "stateful": True},
            {"key": "reply", "type": "string"},
        ],
        "clarificationOutputKey": "reply",
    }
    ctx = {
        "trigger.message.text": "Still thinking.",
        "_workflow.runId": "run_carry",
        "_workflow.workflowId": workflow.id,
        "_workflow.nodeId": "agent_1",
        "_workflow.correlationKey": "conversation_1",
        "_workflow.agentStateNamespace": "test",
    }
    with stub_fixtures(StubResponse(structured={"outputs": {}, "statePatches": {}})):
        ai_agent_run(db, DEFAULT_TENANT_ID, config, ctx)
    row = service.load(DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1", namespace="test")
    assert row is not None
    assert row.pending_question == "What is the task?" and row.pending_field == "task"


def test_run_lookup_requires_workflow_tenant_match(session_factory):
    db = session_factory()
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Tenant lookup",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    run = WorkflowRun(
        tenant_id=PLATFORM_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=workflow.draft_definition_json,
        trigger_payload_json={},
    )
    db.add(run)
    db.flush()
    from app.workflow_engine.executor import run_workflow

    with pytest.raises(RuntimeError, match="not found"):
        run_workflow(db, run.id)


def test_enum_output_schema_and_stateful_action_are_supported(session_factory):
    db = session_factory()
    agent = _agent(db)
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="State workflow",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    config = {
        "agentId": agent.id,
        "instructions": "Classify the current message.",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": _schema(),
        "clarificationOutputKey": "reply",
    }
    ctx = {
        "trigger.message.text": "The launch page is blocked.",
        "trigger.message.id": "message_1",
        "_workflow.runId": "run_1",
        "_workflow.workflowId": workflow.id,
        "_workflow.nodeId": "agent_1",
        "_workflow.correlationKey": "conversation_1",
        "_workflow.isTest": False,
    }
    response = {
        "outputs": {"reply": "I recorded that."},
        "statePatches": {
            "task": {"operation": "set", "value": "Launch page", "evidence": "launch page"},
            "status": {"operation": "set", "value": "blocked", "evidence": "blocked"},
        },
        "pendingField": None,
    }
    with stub_fixtures(StubResponse(structured=response)):
        output = ai_agent_run(db, DEFAULT_TENANT_ID, config, ctx)
    assert output["task"] == "Launch page"
    assert output["status"] == "blocked"
    assert output["reply"] == "I recorded that."
    assert output["stateChangedFields"] == ["task", "status"]


def test_stateless_agent_still_returns_flat_output_without_state_row(session_factory):
    db = session_factory()
    agent = _agent(db)
    config = {
        "agentId": agent.id,
        "instructions": "Classify.",
        "inputText": "hello",
        "outputParams": [{"key": "intent", "type": "enum", "enumValues": ["support", "sales"]}],
    }
    with stub_fixtures(StubResponse(structured={"intent": "support"})):
        output = ai_agent_run(db, DEFAULT_TENANT_ID, config, {})
    assert output == {"intent": "support"}
    assert AgentStateRepository(db).list_for_tenant(DEFAULT_TENANT_ID) == []


def test_test_namespace_does_not_read_production_state(session_factory):
    db = session_factory()
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="State workflow",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    svc = AgentStateService(db)
    production = svc.save_initial(
        **{**_scope(), "workflow_id": workflow.id}, state={"task": "production"}, provenance={}
    )
    sandbox = svc.load(
        **{**_scope(test_namespace=True), "workflow_id": workflow.id}
    )
    assert production.state_json == {"task": "production"}
    assert sandbox is None


def test_pending_clarification_is_carried_and_clear_is_idempotent(session_factory):
    db = session_factory()
    agent = _agent(db)
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="State workflow",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    config = {
        "agentId": agent.id,
        "instructions": "Collect the task.",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": _schema(),
        "clarificationOutputKey": "reply",
    }
    ctx = {
        "trigger.message.text": "The launch page is blocked.",
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
                "outputs": {"reply": "What is the task?"},
                "statePatches": {
                    "status": {"operation": "set", "value": "blocked", "evidence": "blocked"}
                },
                "pendingField": "task",
            }
        )
    ):
        ai_agent_run(db, DEFAULT_TENANT_ID, config, ctx)
    row = AgentStateService(db).load(DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1")
    assert row is not None and row.pending_question == "What is the task?"
    assert row.pending_field == "task"

    first_clear = clear_agent_state(
        db,
        DEFAULT_TENANT_ID,
        {"agentNodeId": "agent_1"},
        {
            **ctx,
            "_workflow.correlationKey": "conversation_1",
            "_workflow.reachableStatefulAgentIds": ["agent_1"],
        },
    )
    assert first_clear == {"cleared": True, "previousRevision": row.revision}
    again = clear_agent_state(
        db,
        DEFAULT_TENANT_ID,
        {"agentNodeId": "agent_1"},
        {
            **ctx,
            "_workflow.correlationKey": "conversation_1",
            "_workflow.reachableStatefulAgentIds": ["agent_1"],
        },
    )
    assert again == {"cleared": False, "previousRevision": None}
