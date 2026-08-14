"""Omnichannel × AI Agent workflow nodes (plan sprint-4/17). Covers AC-OA-01..13.

Every LLM call goes through the deterministic stub provider (``app.ai.stub``)
- no live API key anywhere, per the brief's explicit instruction. Reuses the
existing omnichannel test seams (`_seed_thread`/`_channel_id`/`_process`/
`_wa_payload`) rather than duplicating fixture setup.
"""
import fakeredis
import pytest

from app.ai.stub import StubResponse, stub_fixtures
from app.models import DEFAULT_TENANT_ID
from app.models.ai import AiAgent, AiTrace
from app.models.workflow import RUN_SUCCESS, Workflow, WorkflowRun
from app.services.workflow_service import WorkflowService
from modules.omnichannel.services import realtime
from modules.omnichannel.services.workflow_actions import (
    ActionError as OmniActionError,
    omnichannel_get_contact,
    omnichannel_send_message,
)
from app.workflow_engine.actions.ai_agent_actions import ActionError as AiActionError, ai_agent_run
from tests.test_omnichannel_conversations import _seed_thread
from tests.test_omnichannel_webhooks import _channel_id, _process, _wa_payload


@pytest.fixture(autouse=True)
def _fake_realtime():
    client = fakeredis.FakeRedis(decode_responses=True)
    realtime.set_client(client)
    yield client
    realtime.set_client(None)


def _make_agent(db, *, key="test_classifier", enabled=True) -> AiAgent:
    agent = AiAgent(
        tenant_id=DEFAULT_TENANT_ID,
        key=key,
        name="Test Classifier",
        connection_id=None,  # → stub provider
        model="stub-model-1",
        is_enabled=enabled,
    )
    db.add(agent)
    db.flush()
    return agent


def _publish_workflow(db, *, channel_id, agent_id, contact_ref="{{ trigger.contact.id }}") -> Workflow:
    # Underscore node ids - the merge-token regex (`[\w.]+`) doesn't match `-`.
    ai_id = "ai_1"
    doc = {
        "schemaVersion": 1,
        "nodes": [
            {
                "id": "trg_1",
                "kind": "trigger",
                "type": "omnichannel.message_received",
                "config": {"channelId": channel_id} if channel_id else {},
            },
            {
                "id": ai_id,
                "kind": "action",
                "type": "ai_agent.run",
                "config": {
                    "agentId": agent_id,
                    "instructions": "Classify intent, domain, urgency.",
                    "inputText": "{{ trigger.message.text }}",
                    "outputParams": [
                        {"key": "intent", "type": "string", "required": True},
                        {"key": "domain", "type": "string", "required": True},
                        {"key": "urgency", "type": "string", "required": True},
                    ],
                },
            },
            {
                "id": "send_1",
                "kind": "action",
                "type": "omnichannel.send_message",
                "config": {
                    "contactId": contact_ref,
                    "message": f"Logged as {{{{ nodes.{ai_id}.intent }}}}.",
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "trg_1", "target": ai_id, "sourcePort": "out"},
            {"id": "e2", "source": ai_id, "target": "send_1", "sourcePort": "out"},
        ],
    }
    service = WorkflowService(db)
    wf = service.create(
        DEFAULT_TENANT_ID, name="Test omni workflow", description="", draft=doc, actor_id=None
    )
    service.set_active(wf.id, DEFAULT_TENANT_ID, True)
    service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
    db.refresh(wf)
    return wf


# ── AC-OA-01/03: fires for any channel + context flattening ────────────────
def test_trigger_fires_for_any_channel(session_factory):
    _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    try:
        agent = _make_agent(db, key="k1")
        wf = _publish_workflow(db, channel_id=None, agent_id=agent.id)
        wf_id = wf.id
    finally:
        db.close()

    with stub_fixtures(StubResponse(structured={"intent": "booking", "domain": "events", "urgency": "low"})):
        _process(session_factory, channel_id, _wa_payload(wamid="wamid.trg-1", text="Hi there"))

    db = session_factory()
    try:
        runs = db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf_id).all()
        assert len(runs) == 1
        assert runs[0].status == RUN_SUCCESS
        payload = runs[0].trigger_payload_json
        assert payload["omnichannel"]["messageText"] == "Hi there"
    finally:
        db.close()


# ── AC-OA-02: channel filter ────────────────────────────────────────────────
def test_trigger_filters_by_channel(session_factory):
    _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    try:
        agent = _make_agent(db, key="k2")
        wf = _publish_workflow(db, channel_id="some-other-channel", agent_id=agent.id)
        wf_id = wf.id
    finally:
        db.close()

    _process(session_factory, channel_id, _wa_payload(wamid="wamid.trg-2", text="Hi"))

    db = session_factory()
    try:
        runs = db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf_id).all()
        assert runs == []
    finally:
        db.close()


# ── AC-OA-05: dispatch failure never breaks the inbound pipeline ───────────
def test_dispatch_failure_is_isolated(session_factory, monkeypatch):
    _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)

    def _boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.workflow_engine.entity_events.notify_entity_event", _boom
    )
    counters = _process(session_factory, channel_id, _wa_payload(wamid="wamid.trg-3", text="Hi"))
    assert counters["messages"] == 1


# ── AC-OA-06/07: Get Contact ────────────────────────────────────────────────
def test_get_contact_found_and_not_found(session_factory):
    _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).first()
        out = omnichannel_get_contact(db, DEFAULT_TENANT_ID, {"contactId": contact.id}, {})
        assert out["id"] == contact.id
        assert out["phone"] == contact.phone

        with pytest.raises(OmniActionError):
            omnichannel_get_contact(db, DEFAULT_TENANT_ID, {"contactId": "does-not-exist"}, {})
    finally:
        db.close()


def test_get_contact_cross_tenant_rejected(session_factory):
    _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).first()
        with pytest.raises(OmniActionError):
            omnichannel_get_contact(db, "some-other-tenant", {"contactId": contact.id}, {})
    finally:
        db.close()


# ── AC-OA-08/09: Send Message ───────────────────────────────────────────────
def test_send_message_success(session_factory):
    # _seed_thread's default csw_expires_at is +20h (open window).
    contact_id = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    try:
        out = omnichannel_send_message(
            db, DEFAULT_TENANT_ID, {"contactId": contact_id, "message": "Reply text"}, {}
        )
        assert out["messageId"]
    finally:
        db.close()


def test_send_message_csw_closed_fails(session_factory):
    _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        from datetime import datetime, timedelta, timezone

        from modules.omnichannel.models import Contact

        contact = db.query(Contact).first()
        contact.csw_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        with pytest.raises(OmniActionError):
            omnichannel_send_message(
                db, DEFAULT_TENANT_ID, {"contactId": contact.id, "message": "Reply text"}, {}
            )
    finally:
        db.close()


# ── AC-OA-10/12: AI Agent structured output + trace ─────────────────────────
def test_ai_agent_run_structured_output_via_stub(session_factory):
    db = session_factory()
    try:
        agent = _make_agent(db, key="k3")
        db.commit()
        config = {
            "agentId": agent.id,
            "instructions": "Classify.",
            "inputText": "I need my booking moved to Saturday.",
            "outputParams": [
                {"key": "intent", "type": "string", "required": True},
                {"key": "domain", "type": "string", "required": True},
            ],
        }
        with stub_fixtures(StubResponse(structured={"intent": "reschedule", "domain": "booking"})):
            out = ai_agent_run(db, DEFAULT_TENANT_ID, config, {})
        assert out == {"intent": "reschedule", "domain": "booking"}

        traces = db.query(AiTrace).filter(AiTrace.agent_id == agent.id).all()
        assert len(traces) == 1
        assert traces[0].status == "ok"
    finally:
        db.close()


# ── AC-OA-11: missing / disabled agent ──────────────────────────────────────
def test_ai_agent_run_missing_agent(session_factory):
    db = session_factory()
    try:
        with pytest.raises(AiActionError):
            ai_agent_run(db, DEFAULT_TENANT_ID, {"agentId": "nope", "inputText": "hi", "outputParams": []}, {})
    finally:
        db.close()


def test_ai_agent_run_disabled_agent(session_factory):
    db = session_factory()
    try:
        agent = _make_agent(db, key="k4", enabled=False)
        db.commit()
        with pytest.raises(AiActionError):
            ai_agent_run(
                db, DEFAULT_TENANT_ID, {"agentId": agent.id, "inputText": "hi", "outputParams": []}, {}
            )
    finally:
        db.close()


# ── publish() denormalization ───────────────────────────────────────────────
def test_publish_denormalizes_trigger_entity_type(session_factory):
    db = session_factory()
    try:
        agent = _make_agent(db, key="k5")
        wf = _publish_workflow(db, channel_id=None, agent_id=agent.id)
        assert wf.trigger_type == "omnichannel.message_received"
        assert wf.trigger_entity_type == "omnichannel_message"
    finally:
        db.close()


# ── AC-OA-13: end-to-end demo flow ──────────────────────────────────────────
def test_end_to_end_inbound_to_reply(session_factory):
    # _seed_thread's default csw_expires_at is +20h - open window, no override needed.
    contact_id = _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    try:
        agent = _make_agent(db, key="k6")
        wf = _publish_workflow(db, channel_id=channel_id, agent_id=agent.id)
        db.commit()
        wf_id = wf.id
    finally:
        db.close()

    # _seed_thread's default phone is +60123456789 - match it so the webhook's
    # phone-stitch resolves to the SAME contact (proves trigger.contact.id ties
    # back to the real seeded contact, not a freshly-stitched one).
    with stub_fixtures(StubResponse(structured={"intent": "support", "domain": "general", "urgency": "low"})):
        counters = _process(
            session_factory,
            channel_id,
            _wa_payload(wamid="wamid.e2e-1", from_="60123456789", text="Help please"),
        )
    assert counters["messages"] == 1

    db = session_factory()
    try:
        runs = db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf_id).all()
        assert len(runs) == 1
        assert runs[0].status == RUN_SUCCESS

        from modules.omnichannel.models import ConversationMessage

        reply = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.contact_id == contact_id,
                ConversationMessage.sender_type == "AGENT",
            )
            .order_by(ConversationMessage.created_at.desc())
            .first()
        )
        assert reply is not None
        assert "support" in (reply.body or "")
    finally:
        db.close()
