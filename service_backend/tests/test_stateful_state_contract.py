"""Plan sprint-4/22 - stateful AI state contract for real LLMs (AC-SC-01..09).

Covers: (1) the reducer's evidence FALLBACK matrix (AC-SC-05/06), (2) the
platform-generated state contract text (AC-SC-01/02), (3) the contract is
sent to the model ONLY for stateful runs (AC-SC-03), and (4) an end-to-end
real-provider-shaped run where the model omits `evidence` but quotes the
value verbatim - the field must persist and flatten to ``nodes.<id>.<field>``
(AC-SC-08).
"""
from datetime import datetime, timezone

from app.ai.stub import StubResponse, stub_fixtures
from app.models import DEFAULT_TENANT_ID
from app.models.ai import AiAgent, AiSpan
from app.models.workflow import Workflow
from app.services.agent_state_service import AgentStateService
from app.workflow_engine.actions.ai_agent_actions import _state_contract, ai_agent_run
from app.workflow_engine.agent_state import reduce_agent_state
from app.workflow_engine.context import set_node_output


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


def _agent(db):
    agent = AiAgent(
        tenant_id=DEFAULT_TENANT_ID,
        name="Contract agent",
        model="stub-model-1",
        connection_id=None,
    )
    db.add(agent)
    db.flush()
    return agent


# ---------------------------------------------------------------------------
# (1) Reducer evidence fallback matrix
# ---------------------------------------------------------------------------


def test_set_with_no_evidence_but_value_quoted_verbatim_is_accepted_via_fallback():
    result = reduce_agent_state(
        {},
        {},
        {"task": {"operation": "set", "value": "Launch landing page"}},
        "My task is Launch landing page today.",
        _schema(),
        run_id="run_1",
        message_id="message_1",
        now=datetime.now(timezone.utc),
    )
    assert result.state == {"task": "Launch landing page"}
    assert result.rejected_fields == []
    assert result.provenance["task"]["evidence"] == "Launch landing page"


def test_set_with_value_and_evidence_both_absent_from_message_is_rejected():
    result = reduce_agent_state(
        {},
        {},
        {"task": {"operation": "set", "value": "Launch landing page"}},
        "Everything is going fine, nothing to report.",
        _schema(),
        run_id="run_2",
        message_id="message_2",
        now=datetime.now(timezone.utc),
    )
    assert result.state == {}
    assert result.rejected_fields == ["task"]


def test_enum_set_whose_token_is_not_in_message_and_no_evidence_is_rejected():
    result = reduce_agent_state(
        {},
        {},
        {"status": {"operation": "set", "value": "completed"}},
        "The task is going well so far.",
        _schema(),
        run_id="run_3",
        message_id="message_3",
        now=datetime.now(timezone.utc),
    )
    assert result.state == {}
    assert result.rejected_fields == ["status"]


def test_set_with_valid_supplied_evidence_is_unchanged_and_uses_that_evidence():
    result = reduce_agent_state(
        {},
        {},
        {"status": {"operation": "set", "value": "blocked", "evidence": "stuck"}},
        "We are stuck on the launch page.",
        _schema(),
        run_id="run_4",
        message_id="message_4",
        now=datetime.now(timezone.utc),
    )
    assert result.state == {"status": "blocked"}
    assert result.rejected_fields == []
    assert result.provenance["status"]["evidence"] == "stuck"


def test_clear_without_evidence_is_still_rejected_the_fallback_is_set_only():
    result = reduce_agent_state(
        {"task": "Launch landing page"},
        {"task": {"runId": "old"}},
        {"task": {"operation": "clear"}},
        "Never mind about that.",
        _schema(),
        run_id="run_5",
        message_id="message_5",
        now=datetime.now(timezone.utc),
    )
    assert result.state == {"task": "Launch landing page"}
    assert result.rejected_fields == ["task"]


# ---------------------------------------------------------------------------
# (2) The state contract text
# ---------------------------------------------------------------------------


def test_state_contract_is_non_empty_and_names_the_operations_and_evidence_rule():
    text = _state_contract(_schema())
    assert text and isinstance(text, str)
    for term in ("set", "clear", "no_change", "ambiguous"):
        assert term in text
    assert "evidence" in text.lower()
    assert "currentMessage" in text
    assert "acceptedState" in text
    assert "statePatches" in text
    assert "pendingField" in text


# ---------------------------------------------------------------------------
# (3) The contract is added ONLY for stateful runs
# ---------------------------------------------------------------------------


def test_stateful_run_system_prompt_includes_the_state_contract(session_factory):
    db = session_factory()
    agent = _agent(db)
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Contract - stateful",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    config = {
        "agentId": agent.id,
        "instructions": "Collect the task update.",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": _schema(),
    }
    ctx = {
        "trigger.message.text": "My task is Launch landing page.",
        "_workflow.runId": "run_contract_stateful",
        "_workflow.workflowId": workflow.id,
        "_workflow.nodeId": "agent_1",
        "_workflow.correlationKey": "conversation_1",
        "_workflow.agentStateNamespace": "test",
    }
    with stub_fixtures(
        StubResponse(structured={"outputs": {}, "statePatches": {}, "pendingField": None})
    ):
        ai_agent_run(db, DEFAULT_TENANT_ID, config, ctx)
    span = db.query(AiSpan).order_by(AiSpan.started_at.desc()).first()
    system = span.input_json["system"]
    assert "evidence" in system.lower()
    assert "statePatches" in system
    assert "Collect the task update." in system


def test_transient_only_run_system_prompt_excludes_the_state_contract(session_factory):
    db = session_factory()
    agent = _agent(db)
    config = {
        "agentId": agent.id,
        "instructions": "Classify the message.",
        "inputText": "hello there",
        "outputParams": [{"key": "intent", "type": "enum", "enumValues": ["support", "sales"]}],
    }
    with stub_fixtures(StubResponse(structured={"intent": "support"})):
        ai_agent_run(db, DEFAULT_TENANT_ID, config, {})
    span = db.query(AiSpan).order_by(AiSpan.started_at.desc()).first()
    system = span.input_json["system"]
    assert system == "Classify the message."
    assert "statePatches" not in system
    assert "evidence" not in system.lower()


# ---------------------------------------------------------------------------
# (4) End-to-end: a real-provider-shaped double that omits evidence
# ---------------------------------------------------------------------------


def test_evidence_less_but_quoted_set_persists_end_to_end_and_flattens_to_node_output(
    session_factory,
):
    db = session_factory()
    agent = _agent(db)
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Contract - end to end",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    config = {
        "agentId": agent.id,
        "instructions": "Collect the task update.",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": _schema(),
        "clarificationOutputKey": "reply",
    }
    ctx = {
        "trigger.message.text": "My task is Launch landing page and it is blocked.",
        "trigger.message.id": "message_e2e",
        "_workflow.runId": "run_e2e",
        "_workflow.workflowId": workflow.id,
        "_workflow.nodeId": "agent_1",
        "_workflow.correlationKey": "conversation_1",
        "_workflow.agentStateNamespace": "test",
    }
    # A "real provider" double: returns a `set` patch with NO evidence, but the
    # value is an exact substring of the current message - the case that was
    # rejected before this slice.
    response = {
        "outputs": {"reply": "Recorded."},
        "statePatches": {
            "task": {"operation": "set", "value": "Launch landing page"},
            "status": {"operation": "set", "value": "blocked", "evidence": "blocked"},
        },
        "pendingField": None,
    }
    with stub_fixtures(StubResponse(structured=response)):
        output = ai_agent_run(db, DEFAULT_TENANT_ID, config, ctx)

    assert output["task"] == "Launch landing page"
    assert output["status"] == "blocked"
    assert output["stateChangedFields"] == ["task", "status"]
    assert output["stateRejectedFields"] == []

    row = AgentStateService(db).load(
        DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1", namespace="test"
    )
    assert row is not None
    assert row.state_json["task"] == "Launch landing page"
    assert row.provenance_json["task"]["evidence"] == "Launch landing page"

    flat_ctx: dict = {}
    set_node_output(flat_ctx, "agent_1", output)
    assert flat_ctx["nodes.agent_1.task"] == "Launch landing page"
    assert flat_ctx["nodes.agent_1.status"] == "blocked"


def test_evidence_less_and_unquoted_set_stays_rejected_end_to_end(session_factory):
    db = session_factory()
    agent = _agent(db)
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID,
        name="Contract - fabrication guard",
        description="",
        draft_definition_json={"schemaVersion": 2, "nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    config = {
        "agentId": agent.id,
        "instructions": "Collect the task update.",
        "inputText": "{{ trigger.message.text }}",
        "outputParams": _schema(),
    }
    ctx = {
        "trigger.message.text": "Just checking in, nothing new.",
        "trigger.message.id": "message_fab",
        "_workflow.runId": "run_fab",
        "_workflow.workflowId": workflow.id,
        "_workflow.nodeId": "agent_1",
        "_workflow.correlationKey": "conversation_1",
        "_workflow.agentStateNamespace": "test",
    }
    response = {
        "outputs": {},
        "statePatches": {
            "task": {"operation": "set", "value": "Launch landing page"},
        },
        "pendingField": None,
    }
    with stub_fixtures(StubResponse(structured=response)):
        output = ai_agent_run(db, DEFAULT_TENANT_ID, config, ctx)

    assert "task" not in output
    assert output["stateRejectedFields"] == ["task"]
    row = AgentStateService(db).load(
        DEFAULT_TENANT_ID, workflow.id, "agent_1", "conversation_1", namespace="test"
    )
    assert row is None or "task" not in row.state_json
