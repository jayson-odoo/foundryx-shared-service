"""Plan sprint-4/19 S5 - the seeded progress-update proof, end to end on the
real inbound pipeline (AC-SAR-49..55) with the deterministic dev stub."""
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import RUN_SUCCESS, Workflow, WorkflowRun, WorkflowRunNode
from modules.omnichannel.services.seed_demo_workflow import (
    PROGRESS_AGENT_KEY,
    PROGRESS_WORKFLOW_NAME,
    seed_demo_progress_workflow,
)
from tests.test_omnichannel_conversations import _seed_thread
from tests.test_omnichannel_webhooks import _channel_id, _process, _wa_payload

PHONE = "60123456789"  # _seed_thread's default phone → the webhook stitches to it


def _seed(session_factory):
    contact_id = _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    try:
        seed_demo_progress_workflow(db, DEFAULT_TENANT_ID, channel_id=channel_id)
        db.commit()
        wf = db.query(Workflow).filter(Workflow.name == PROGRESS_WORKFLOW_NAME).one()
        assert wf.current_version_id is not None
        return contact_id, channel_id, wf.id
    finally:
        db.close()


def _say(session_factory, channel_id, text, n):
    counters = _process(session_factory, channel_id, _wa_payload(wamid=f"wamid.sar19-{n}", from_=PHONE, text=text))
    assert counters["messages"] == 1


def _replies(session_factory, contact_id):
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    try:
        rows = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.contact_id == contact_id, ConversationMessage.sender_type == "AGENT")
            .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
            .all()
        )
        return [r.body or "" for r in rows]
    finally:
        db.close()


def _state(session_factory, wf_id):
    from app.services.agent_state_service import AgentStateService

    db = session_factory()
    try:
        row = AgentStateService(db).load(DEFAULT_TENANT_ID, wf_id, "ai_progress", _conversation_id(db, wf_id), namespace="prod")
        return None if row is None else (dict(row.state_json), row.pending_field, row.revision)
    finally:
        db.close()


def _conversation_id(db, wf_id):
    run = db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf_id).order_by(WorkflowRun.created_at.desc()).first()
    return run.correlation_key


def _runs(session_factory, wf_id):
    db = session_factory()
    try:
        return db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf_id).order_by(WorkflowRun.created_at.asc(), WorkflowRun.id.asc()).all()
    finally:
        db.close()


def test_seed_is_generic_nodes_only_and_serialized(session_factory):
    _contact, _channel, wf_id = _seed(session_factory)
    db = session_factory()
    wf = db.query(Workflow).get(wf_id)
    doc = wf.draft_definition_json
    assert doc["execution"] == {"mode": "serialized", "correlationKey": "{{ trigger.conversationId }}"}
    assert sorted({n["type"] for n in doc["nodes"]}) == sorted(
        {"omnichannel.message_received", "ai_agent.run", "if", "omnichannel.send_message", "ai_agent.clear_state"}
    )
    agent = next(n for n in doc["nodes"] if n["type"] == "ai_agent.run")
    stateful = {p["key"] for p in agent["config"]["outputParams"] if p.get("stateful")}
    assert stateful == {"task", "status", "blocker"}
    from app.models.ai import AiAgent

    assert db.query(AiAgent).filter(AiAgent.key == PROGRESS_AGENT_KEY).one().connection_id is None
    # Idempotent reseed.
    seed_demo_progress_workflow(db, DEFAULT_TENANT_ID)
    assert db.query(Workflow).filter(Workflow.name == PROGRESS_WORKFLOW_NAME).count() == 1


def test_two_turn_clarification_correction_and_fresh_after_clear(session_factory):
    contact_id, channel_id, wf_id = _seed(session_factory)

    _say(session_factory, channel_id, "Launch landing page", 1)
    assert _replies(session_factory, contact_id)[-1] == "What is the status?"
    state, pending, rev1 = _state(session_factory, wf_id)
    assert state == {"task": "Launch landing page"} and pending == "status"

    _say(session_factory, channel_id, "blocked", 2)
    assert _replies(session_factory, contact_id)[-1] == "What is the blocker?"
    state, pending, rev2 = _state(session_factory, wf_id)
    assert state == {"task": "Launch landing page", "status": "blocked"} and pending == "blocker"
    assert rev2 > rev1

    # A correction changes only status; task + its provenance stay.
    _say(session_factory, channel_id, "Actually it is completed", 3)
    replies = _replies(session_factory, contact_id)
    assert replies[-1].startswith("Update recorded - task: Launch landing page, status: completed")
    # Clear Agent State ran after the confirmation → next message is fresh.
    assert _state(session_factory, wf_id) is None or _state(session_factory, wf_id)[0] == {}

    _say(session_factory, channel_id, "in progress", 4)
    assert _replies(session_factory, contact_id)[-1] == "What is the task?"

    runs = _runs(session_factory, wf_id)
    assert [r.status for r in runs] == [RUN_SUCCESS] * 4
    assert len({r.correlation_key for r in runs}) == 1 and runs[0].correlation_key


def test_same_key_runs_are_ordered_and_state_accumulates(session_factory):
    contact_id, channel_id, wf_id = _seed(session_factory)
    _say(session_factory, channel_id, "Prepare quarterly report", 1)
    _say(session_factory, channel_id, "in progress", 2)
    runs = _runs(session_factory, wf_id)
    assert [r.status for r in runs] == [RUN_SUCCESS, RUN_SUCCESS]
    assert runs[0].created_at <= runs[1].created_at
    assert runs[0].correlation_key == runs[1].correlation_key
    assert _replies(session_factory, contact_id)[-1].startswith(
        "Update recorded - task: Prepare quarterly report, status: in_progress"
    )


def test_downstream_failure_before_clear_retains_state_for_retry(session_factory, monkeypatch):
    contact_id, channel_id, wf_id = _seed(session_factory)
    _say(session_factory, channel_id, "Write release notes", 1)
    _say(session_factory, channel_id, "completed", 2)  # would confirm + clear
    # ...but make the confirmation send fail this time (the ONE send path).
    from modules.omnichannel.services.message_service import MessageService

    original = MessageService.send_message
    calls = {"n": 0}

    def _flaky(self, contact_id, tenant_id, actor_user_id, payload, **kwargs):
        text = getattr(payload, "text", None) or getattr(payload, "body", None) or ""
        if "Update recorded" in str(text):
            calls["n"] += 1
            raise RuntimeError("provider outage")
        return original(self, contact_id, tenant_id, actor_user_id, payload, **kwargs)

    monkeypatch.setattr(MessageService, "send_message", _flaky)
    _say(session_factory, channel_id, "Write release notes again", 3)  # after clear: fresh task
    _say(session_factory, channel_id, "completed", 4)
    assert calls["n"] == 1
    failed_runs = [r for r in _runs(session_factory, wf_id) if r.status == "failed"]
    assert len(failed_runs) == 1
    db = session_factory()
    nodes = {n.node_id: n.status for n in db.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == failed_runs[0].id).all()}
    db.close()
    assert nodes["send_confirm"] == "failed" and nodes["clear_state"] == "skipped"
    state, _pending, _rev = _state(session_factory, wf_id)
    assert state == {"task": "Write release notes again", "status": "completed"}  # retained for retry
    monkeypatch.undo()
    _say(session_factory, channel_id, "completed", 5)  # retry path: still knows the task
    assert _replies(session_factory, contact_id)[-1].startswith("Update recorded - task: Write release notes again")
