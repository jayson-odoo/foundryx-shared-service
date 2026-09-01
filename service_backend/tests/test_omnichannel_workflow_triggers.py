"""Omnichannel × AI Agent workflow nodes (plan sprint-4/17). Covers AC-OA-01..13.

Every LLM call goes through the deterministic stub provider (``app.ai.stub``)
- no live API key anywhere, per the brief's explicit instruction. Reuses the
existing omnichannel test seams (`_seed_thread`/`_channel_id`/`_process`/
`_wa_payload`) rather than duplicating fixture setup.
"""
import fakeredis
import pytest

from app.ai.stub import StubResponse, stub_fixtures
from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.models.ai import AiAgent, AiSkill, AiSkillVersion, AiSpan, AiTrace, ai_agent_skills
from app.models.tenant import Tenant
from app.models.workflow import RUN_SUCCESS, Workflow, WorkflowRun
from app.services.workflow_service import WorkflowService
from app.workflow_engine.actions.ai_agent_actions import (
    ActionError as AiActionError,
    _schema_from_params,
    ai_agent_run,
)
from app.workflow_engine.schemas import WorkflowValidationError, validate_definition
from modules.omnichannel.services import realtime
from modules.omnichannel.services.workflow_actions import (
    ActionError as OmniActionError,
    omnichannel_get_contact,
    omnichannel_send_message,
)
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
        assert payload["omnichannel"]["mediaUrl"] is None
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
        assert out["status"] == "OPEN"

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


def test_get_contact_inactive_module_rejected(session_factory):
    _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        from app.services.app_store_service import AppStoreService
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).first()
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
        with pytest.raises(OmniActionError, match="not active"):
            omnichannel_get_contact(db, DEFAULT_TENANT_ID, {"contactId": contact.id}, {})
    finally:
        db.close()


def test_inbound_media_workflow_output_is_signed_and_usable(
    client, session_factory, tmp_path, monkeypatch
):
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
    from modules.omnichannel.services import storage as storage_module
    from modules.omnichannel.security import verify_media_sig
    from modules.omnichannel.services.storage import LocalDiskStorage
    from urllib.parse import parse_qs, urlparse

    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    storage_module.set_storage(LocalDiskStorage(str(tmp_path)))
    monkeypatch.setattr(
        WhatsAppCloudAdapter,
        "fetch_media",
        lambda self, creds, media_id: {"content": b"img", "mime_type": "image/png"},
    )
    captured = {}
    monkeypatch.setattr(
        "app.workflow_engine.entity_events.notify_entity_event",
        lambda *args, **kwargs: captured.update(kwargs["extra"]),
    )

    _seed_thread(session_factory, phone="+60555666777", messages=[])
    channel_id = _channel_id(session_factory)
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "messages", "value": {
            "contacts": [{"wa_id": "60555666777", "profile": {"name": "Pic Sender"}}],
            "messages": [{
                "id": "wamid.workflow-media-1",
                "from": "60555666777",
                "type": "image",
                "image": {"id": "media-workflow-1"},
            }],
        }}]}],
    }
    try:
        _process(session_factory, channel_id, payload)

        media_url = captured["mediaUrl"]
        parsed = urlparse(media_url)
        query = parse_qs(parsed.query)
        assert media_url.startswith(settings.public_base_url.rstrip("/") + "/")
        assert parsed.path.startswith("/omnichannel/media/")
        message_id = parsed.path.rsplit("/", 1)[-1]
        exp = int(query["exp"][0])
        sig = query["sig"][0]
        assert verify_media_sig(message_id, exp, sig)
        assert not verify_media_sig(
            message_id, exp, sig[:-1] + ("0" if sig[-1] != "0" else "1")
        )

        relative_url = parsed.path + "?" + parsed.query
        assert client.get(relative_url).status_code == 200
        assert client.get(relative_url).content == b"img"
        assert client.get(relative_url.replace("sig=", "sig=x")).status_code == 401
    finally:
        storage_module.set_storage(None)


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


def test_send_message_inactive_module_rejected(session_factory):
    contact_id = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    try:
        from app.services.app_store_service import AppStoreService

        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
        with pytest.raises(OmniActionError, match="not active"):
            omnichannel_send_message(
                db,
                DEFAULT_TENANT_ID,
                {"contactId": contact_id, "message": "Reply text"},
                {},
            )
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


def test_ai_agent_run_scopes_skill_versions_to_visible_tiers(session_factory):
    db = session_factory()
    try:
        default_tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).one()
        other_tenant = Tenant(
            name="Other AI",
            slug="other-ai-workflow",
            status_id=default_tenant.status_id,
        )
        db.add(other_tenant)
        db.flush()

        def add_skill(*, tenant_id, version_tenant_id, key, body):
            skill = AiSkill(tenant_id=tenant_id, key=key, name=key)
            db.add(skill)
            db.flush()
            version = AiSkillVersion(
                skill_id=skill.id,
                tenant_id=version_tenant_id,
                version=1,
                body=body,
            )
            db.add(version)
            db.flush()
            skill.active_version_id = version.id
            return skill, version

        own_skill, _ = add_skill(
            tenant_id=DEFAULT_TENANT_ID,
            version_tenant_id=DEFAULT_TENANT_ID,
            key="own",
            body="own-body",
        )
        platform_skill, _ = add_skill(
            tenant_id=None,
            version_tenant_id=None,
            key="platform",
            body="platform-body",
        )
        foreign_skill, foreign_version = add_skill(
            tenant_id=other_tenant.id,
            version_tenant_id=other_tenant.id,
            key="foreign",
            body="foreign-body",
        )
        wrong_tier_skill, _ = add_skill(
            tenant_id=DEFAULT_TENANT_ID,
            version_tenant_id=other_tenant.id,
            key="wrong-tier",
            body="wrong-tier-body",
        )
        corrupt_skill, _ = add_skill(
            tenant_id=DEFAULT_TENANT_ID,
            version_tenant_id=DEFAULT_TENANT_ID,
            key="corrupt",
            body="corrupt-body",
        )
        corrupt_skill.active_version_id = foreign_version.id

        agent = _make_agent(db, key="skill_scope")
        agent.skills = [own_skill, platform_skill, wrong_tier_skill, corrupt_skill]
        db.flush()
        db.execute(
            ai_agent_skills.insert().values(
                agent_id=agent.id,
                skill_id=foreign_skill.id,
                tenant_id=DEFAULT_TENANT_ID,
            )
        )
        db.commit()

        ai_agent_run(
            db,
            DEFAULT_TENANT_ID,
            {
                "agentId": agent.id,
                "inputText": "hello",
                "outputParams": [{"key": "answer", "type": "string"}],
            },
            {},
        )

        trace = (
            db.query(AiTrace)
            .filter(AiTrace.agent_id == agent.id)
            .order_by(AiTrace.created_at.desc())
            .first()
        )
        span = db.query(AiSpan).filter(AiSpan.trace_id == trace.id).one()
        system = span.input_json["system"]
        assert "own-body" in system
        assert "platform-body" in system
        assert "foreign-body" not in system
        assert "wrong-tier-body" not in system
        assert "corrupt-body" not in system
    finally:
        db.close()


def test_publish_gate_rejects_blank_output_parameter_key():
    doc = {
        "schemaVersion": 1,
        "nodes": [
            {"id": "trg_1", "kind": "trigger", "type": "manual", "config": {"inputs": []}},
            {
                "id": "ai_1",
                "kind": "action",
                "type": "ai_agent.run",
                "config": {
                    "agentId": "agent-1",
                    "instructions": "Classify.",
                    "inputText": "Message",
                    "outputParams": [{"key": "   ", "type": "string", "required": True}],
                },
            },
        ],
        "edges": [{"id": "e1", "source": "trg_1", "target": "ai_1", "sourcePort": "out"}],
    }

    with pytest.raises(WorkflowValidationError) as exc_info:
        validate_definition(doc)

    assert 'AI Agent: "Output parameters" contains a parameter without a key.' in exc_info.value.issues


def _ai_output_doc(output_params):
    return {
        "schemaVersion": 1,
        "nodes": [
            {"id": "trg_1", "kind": "trigger", "type": "manual", "config": {"inputs": []}},
            {
                "id": "ai_1",
                "kind": "action",
                "type": "ai_agent.run",
                "config": {
                    "agentId": "agent-1",
                    "instructions": "Classify.",
                    "inputText": "Message",
                    "outputParams": output_params,
                },
            },
        ],
        "edges": [{"id": "e1", "source": "trg_1", "target": "ai_1", "sourcePort": "out"}],
    }


@pytest.mark.parametrize(
    ("output_params", "expected"),
    [
        ([{"key": "intent", "type": "string"}, {"key": "intent", "type": "number"}], 'duplicate key "intent"'),
        ([{"key": "intent-value", "type": "string"}], 'invalid key "intent-value"'),
        ([{"key": " intent", "type": "string"}], "surrounding whitespace"),
        ([{"key": "intent", "type": "object"}], "invalid type"),
        ({"key": "intent", "type": "string"}, "non-empty list of parameter objects"),
    ],
)
def test_publish_gate_rejects_invalid_output_param_contract(output_params, expected):
    with pytest.raises(WorkflowValidationError) as exc_info:
        validate_definition(_ai_output_doc(output_params))

    assert any(expected in issue for issue in exc_info.value.issues)


def test_publish_gate_accepts_valid_output_param_contract():
    doc = _ai_output_doc(
        [
            {"key": "intent", "type": "string", "required": True},
            {"key": "_confidence2", "type": "number", "required": False},
            {"key": "ready", "type": "boolean"},
        ]
    )

    assert validate_definition(doc).nodes[-1].config["outputParams"]


@pytest.mark.parametrize(
    "output_params",
    [
        [],
        [{"key": "intent", "type": "string"}, {"key": "intent", "type": "string"}],
        [{"key": "intent-value", "type": "string"}],
        [{"key": "intent", "type": "object"}],
    ],
)
def test_ai_agent_run_rejects_invalid_output_params(session_factory, output_params):
    db = session_factory()
    try:
        agent = _make_agent(db, key="invalid_output")
        db.commit()
        with pytest.raises(AiActionError, match="Output parameters"):
            ai_agent_run(
                db,
                DEFAULT_TENANT_ID,
                {"agentId": agent.id, "inputText": "hello", "outputParams": output_params},
                {},
            )
    finally:
        db.close()


def test_ai_output_schema_dedupes_required_keys():
    schema = _schema_from_params(
        [
            {"key": "intent", "type": "string", "required": True},
            {"key": "intent", "type": "string", "required": True},
        ]
    )

    assert schema["required"] == ["intent"]


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
