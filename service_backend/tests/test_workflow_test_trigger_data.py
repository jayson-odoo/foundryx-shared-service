"""Workflow draft test-trigger data (sprint-4/18, AC-OA-25..33)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.ai.stub import StubResponse, stub_fixtures
from app.models import DEFAULT_TENANT_ID, Permission, User
from app.models.workflow import RUN_SUCCESS, WorkflowRun
from modules.omnichannel.models import (
    Channel,
    Contact,
    ContactChannelIdentity,
    ConversationMessage,
    Workspace,
)
from modules.omnichannel.security import encrypt_credentials
from modules.omnichannel.services import statuses
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.test_omnichannel_conversations import _seed_thread
from tests.test_omnichannel_webhooks import _channel_id
from tests.test_omnichannel_workflow_triggers import _make_agent, _publish_workflow


def _headers(client) -> dict:
    login = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _request(channel_id: str, contact_id: str, text: str = "Help with my booking") -> dict:
    return {
        "inputs": {},
        "isTest": True,
        "testTrigger": {
            "type": "omnichannel.message_received",
            "channelId": channel_id,
            "contactId": contact_id,
            "messageText": text,
        },
    }


def _workflow(session_factory, channel_id: str):
    db = session_factory()
    try:
        agent = _make_agent(db, key="test_data_agent")
        workflow = _publish_workflow(db, channel_id=channel_id, agent_id=agent.id)
        db.commit()
        return workflow.id
    finally:
        db.close()


def _attach(session_factory, contact_id: str, channel_id: str) -> None:
    db = session_factory()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).one()
        db.add(
            ContactChannelIdentity(
                tenant_id=contact.tenant_id,
                contact_id=contact.id,
                channel_id=channel_id,
                external_user_id=contact.phone or contact.id,
                profile_name=contact.first_name,
            )
        )
        db.commit()
    finally:
        db.close()


def _counts(session_factory, workflow_id: str, contact_id: str) -> tuple[int, int, int]:
    db = session_factory()
    try:
        return (
            db.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow_id).count(),
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.contact_id == contact_id,
                ConversationMessage.sender_type == "CONTACT",
            )
            .count(),
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.contact_id == contact_id,
                ConversationMessage.sender_type == "AGENT",
            )
            .count(),
        )
    finally:
        db.close()


def test_omnichannel_test_trigger_runs_draft_with_canonical_context(
    client, session_factory
):
    contact_id = _seed_thread(
        session_factory, name="Sandbox Contact", phone="+60129990000", messages=[]
    )
    channel_id = _channel_id(session_factory)
    _attach(session_factory, contact_id, channel_id)
    workflow_id = _workflow(session_factory, channel_id)

    with stub_fixtures(
        StubResponse(
            structured={"intent": "support", "domain": "general", "urgency": "low"}
        )
    ):
        response = client.post(
            f"/workflows/{workflow_id}/run",
            headers=_headers(client),
            json=_request(channel_id, contact_id),
        )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == RUN_SUCCESS
    assert response.json()["isTest"] is True
    assert response.json()["versionNumber"] == 0

    db = session_factory()
    try:
        run = (
            db.query(WorkflowRun)
            .filter(WorkflowRun.workflow_id == workflow_id)
            .one()
        )
        assert run.version_id is None
        assert run.version_number == 0
        assert run.is_test is True
        omni = run.trigger_payload_json["omnichannel"]
        assert omni == {
            "channelId": channel_id,
            "channelName": "Test WhatsApp",
            "workspaceId": omni["workspaceId"],
            "contactId": contact_id,
            "contactName": "Sandbox Contact",
            "contactPhone": "+60129990000",
            "conversationId": contact_id,
            "messageId": omni["messageId"],
            "messageType": "TEXT",
            "messageText": "Help with my booking",
            "mediaUrl": None,
            "mediaMime": None,
        }
        assert omni["messageId"].startswith("test-")

        trigger_trace = next(node for node in run.nodes if node.node_type == "omnichannel.message_received")
        assert trigger_trace.output_json["message"]["text"] == "Help with my booking"
        assert trigger_trace.output_json["contact"]["id"] == contact_id
        assert trigger_trace.output_json["channel"]["id"] == channel_id
        assert trigger_trace.output_json["conversationId"] == contact_id

        inbound = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.contact_id == contact_id,
                ConversationMessage.sender_type == "CONTACT",
            )
            .count()
        )
        outbound = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.contact_id == contact_id,
                ConversationMessage.sender_type == "AGENT",
            )
            .all()
        )
        assert inbound == 0
        assert len(outbound) == 1
        assert (outbound[0].body or "").startswith("Logged as ")
        assert outbound[0].channel_id == channel_id
    finally:
        db.close()


def test_dedicated_options_only_offer_active_dev_channel_contact_pairs(
    client, session_factory
):
    offered = _seed_thread(session_factory, name="Offered Contact", messages=[])
    channel_id = _channel_id(session_factory)
    _attach(session_factory, offered, channel_id)
    workflow_id = _workflow(session_factory, channel_id)

    db = session_factory()
    try:
        workspace = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID).first()
        live = Channel(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=workspace.id,
            channel_type="WHATSAPP",
            name="Live channel",
            credentials_json=encrypt_credentials({"access_token": "real"}),
            is_active=True,
            is_trashed=False,
            status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
        )
        db.add(live)
        db.commit()
        live_id = live.id
    finally:
        db.close()

    general = client.get("/workflows/metadata", headers=_headers(client))
    assert general.status_code == 200, general.text
    assert "omnichannelTestSources" not in general.json()

    response = client.get(
        f"/workflows/{workflow_id}/test-options", headers=_headers(client)
    )
    assert response.status_code == 200, response.text
    sources = response.json()["omnichannelTestSources"]
    assert {
        "channelId": channel_id,
        "channelName": "Test WhatsApp",
        "contactId": offered,
        "contactName": "Offered Contact",
        "contactPhone": "+60123456789",
    } in sources
    assert all(source["channelId"] != live_id for source in sources)


def test_test_options_requires_workflow_run_and_conversation_read(
    client, session_factory
):
    contact_id = _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    _attach(session_factory, contact_id, channel_id)
    workflow_id = _workflow(session_factory, channel_id)

    db = session_factory()
    try:
        admin = db.query(User).filter(User.email == ACTIVE_EMAIL).one().roles[0]
        all_permission_keys = [permission.key for permission in admin.permissions]
        admin.permissions = [
            permission
            for permission in admin.permissions
            if permission.key != "conversations.read"
        ]
        db.commit()
    finally:
        db.close()

    headers = _headers(client)
    general = client.get("/workflows/metadata", headers=headers)
    assert general.status_code == 200
    assert "omnichannelTestSources" not in general.json()
    assert (
        client.get(f"/workflows/{workflow_id}/test-options", headers=headers).status_code
        == 403
    )

    db = session_factory()
    try:
        admin = db.query(User).filter(User.email == ACTIVE_EMAIL).one().roles[0]
        restored = (
            db.query(Permission)
            .filter(
                Permission.key.in_(all_permission_keys),
                Permission.key != "workflows.run",
            )
            .all()
        )
        admin.permissions = restored
        db.commit()
    finally:
        db.close()

    assert (
        client.get(f"/workflows/{workflow_id}/test-options", headers=headers).status_code
        == 403
    )


def test_sandbox_test_outbound_fails_closed_if_channel_becomes_live_before_dispatch(
    client, session_factory, monkeypatch
):
    contact_id = _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    _attach(session_factory, contact_id, channel_id)
    workflow_id = _workflow(session_factory, channel_id)

    # Hold the queued message at the same boundary used by the production
    # Celery worker so credentials can change between run creation and dispatch.
    monkeypatch.setattr(
        "modules.omnichannel.services.message_service.run_send",
        lambda _db, _message_id: "QUEUED",
    )
    with stub_fixtures(
        StubResponse(
            structured={"intent": "support", "domain": "general", "urgency": "low"}
        )
    ):
        response = client.post(
            f"/workflows/{workflow_id}/run",
            headers=_headers(client),
            json=_request(channel_id, contact_id),
        )
    assert response.status_code == 200, response.text

    db = session_factory()
    try:
        outbound = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.contact_id == contact_id,
                ConversationMessage.sender_type == "AGENT",
            )
            .one()
        )
        assert outbound.delivery_status == "QUEUED"
        assert (outbound.metadata_json or {}).get("workflowTest") == {
            "sandboxOnly": True
        }
        message_id = outbound.id

        channel = db.query(Channel).filter(Channel.id == channel_id).one()
        channel.credentials_json = encrypt_credentials({"access_token": "now-live"})
        db.commit()
    finally:
        db.close()

    dispatched = []

    class RecordingAdapter:
        def send(self, *_args, **_kwargs):
            dispatched.append(True)
            return {"external_message_id": "should-not-send"}

    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.get_adapter",
        lambda *_args, **_kwargs: RecordingAdapter(),
    )
    from modules.omnichannel.services.send_runner import run_send

    db = session_factory()
    try:
        assert run_send(db, message_id) == "FAILED"
        outbound = db.query(ConversationMessage).filter_by(id=message_id).one()
        assert outbound.delivery_status == "FAILED"
        assert "sandbox" in (outbound.error_message or "").lower()
        assert dispatched == []
    finally:
        db.close()


@pytest.mark.parametrize("lifecycle_field", ["is_active", "is_trashed"])
def test_sandbox_test_outbound_fails_closed_on_channel_lifecycle_race(
    client, session_factory, monkeypatch, lifecycle_field
):
    """A queued sandbox send must not reach the adapter after channel removal."""
    contact_id = _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    _attach(session_factory, contact_id, channel_id)
    workflow_id = _workflow(session_factory, channel_id)

    monkeypatch.setattr(
        "modules.omnichannel.services.message_service.run_send",
        lambda _db, _message_id: "QUEUED",
    )
    with stub_fixtures(
        StubResponse(
            structured={"intent": "support", "domain": "general", "urgency": "low"}
        )
    ):
        response = client.post(
            f"/workflows/{workflow_id}/run",
            headers=_headers(client),
            json=_request(channel_id, contact_id),
        )
    assert response.status_code == 200, response.text

    db = session_factory()
    try:
        outbound = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.contact_id == contact_id,
                ConversationMessage.sender_type == "AGENT",
            )
            .one()
        )
        message_id = outbound.id
    finally:
        db.close()

    original_decrypt = __import__(
        "modules.omnichannel.services.send_runner", fromlist=["decrypt_credentials"]
    ).decrypt_credentials
    mutated = {"done": False}

    def decrypt_then_mutate(credentials):
        if not mutated["done"]:
            mutated["done"] = True
            race_db = session_factory()
            try:
                race_channel = (
                    race_db.query(Channel).filter(Channel.id == channel_id).one()
                )
                setattr(
                    race_channel,
                    lifecycle_field,
                    False if lifecycle_field == "is_active" else True,
                )
                race_db.commit()
            finally:
                race_db.close()
        return original_decrypt(credentials)

    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.decrypt_credentials",
        decrypt_then_mutate,
    )
    dispatched = []

    class RecordingAdapter:
        def send(self, *_args, **_kwargs):
            dispatched.append(True)
            return {"external_message_id": "must-not-send"}

    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.get_adapter",
        lambda *_args, **_kwargs: RecordingAdapter(),
    )
    from modules.omnichannel.services.send_runner import run_send

    db = session_factory()
    try:
        assert run_send(db, message_id) == "FAILED"
        outbound = db.query(ConversationMessage).filter_by(id=message_id).one()
        assert outbound.delivery_status == "FAILED"
        assert "active" in (outbound.error_message or "").lower()
        assert dispatched == []
    finally:
        db.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "blank",
        "oversized",
        "stale_type",
        "not_test",
        "inactive",
        "trashed",
        "live",
        "expired",
        "forged_channel",
        "forged_contact",
    ],
)
def test_invalid_test_trigger_is_rejected_before_any_run_or_message(
    client, session_factory, mutation
):
    contact_id = _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    _attach(session_factory, contact_id, channel_id)
    workflow_id = _workflow(session_factory, channel_id)
    body = _request(channel_id, contact_id)

    db = session_factory()
    try:
        channel = db.query(Channel).filter(Channel.id == channel_id).one()
        if mutation == "inactive":
            channel.is_active = False
        elif mutation == "trashed":
            channel.is_trashed = True
        elif mutation == "live":
            channel.credentials_json = encrypt_credentials({"access_token": "real"})
        elif mutation == "expired":
            contact = db.query(Contact).filter(Contact.id == contact_id).one()
            contact.csw_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    if mutation == "blank":
        body["testTrigger"]["messageText"] = "   "
    elif mutation == "oversized":
        body["testTrigger"]["messageText"] = "x" * 4097
    elif mutation == "stale_type":
        body["testTrigger"]["type"] = "manual"
    elif mutation == "not_test":
        body["isTest"] = False
    elif mutation == "forged_channel":
        body["testTrigger"]["channelId"] = "forged-channel"
    elif mutation == "forged_contact":
        body["testTrigger"]["contactId"] = "forged-contact"

    response = client.post(
        f"/workflows/{workflow_id}/run", headers=_headers(client), json=body
    )
    assert response.status_code == 422, response.text
    assert _counts(session_factory, workflow_id, contact_id) == (0, 0, 0)


def test_cross_tenant_and_workspace_mismatches_are_rejected(client, session_factory):
    contact_id = _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    _attach(session_factory, contact_id, channel_id)
    workflow_id = _workflow(session_factory, channel_id)

    db = session_factory()
    try:
        other_workspace = Workspace(
            tenant_id=DEFAULT_TENANT_ID,
            name="Other workspace",
            is_default=False,
            is_trashed=False,
        )
        db.add(other_workspace)
        db.flush()
        mismatch_channel = Channel(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=other_workspace.id,
            channel_type="WHATSAPP",
            name="Other sandbox",
            credentials_json=encrypt_credentials({"dev": True}),
            is_active=True,
            is_trashed=False,
            status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
        )
        db.add(mismatch_channel)

        foreign_workspace = Workspace(
            tenant_id="foreign-tenant", name="Foreign", is_default=True, is_trashed=False
        )
        db.add(foreign_workspace)
        db.flush()
        foreign_contact = Contact(
            tenant_id="foreign-tenant",
            workspace_id=foreign_workspace.id,
            first_name="Foreign",
            phone="+60999999999",
            csw_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(foreign_contact)
        foreign_channel = Channel(
            tenant_id="foreign-tenant",
            workspace_id=foreign_workspace.id,
            channel_type="WHATSAPP",
            name="Foreign sandbox",
            credentials_json=encrypt_credentials({"dev": True}),
            is_active=True,
            is_trashed=False,
        )
        db.add(foreign_channel)
        db.commit()
        mismatch_id = mismatch_channel.id
        foreign_id = foreign_contact.id
        foreign_channel_id = foreign_channel.id
    finally:
        db.close()

    for body in (
        _request(mismatch_id, contact_id),
        _request(channel_id, foreign_id),
        _request(foreign_channel_id, contact_id),
    ):
        response = client.post(
            f"/workflows/{workflow_id}/run", headers=_headers(client), json=body
        )
        assert response.status_code == 422, response.text

    assert _counts(session_factory, workflow_id, contact_id) == (0, 0, 0)


def test_same_workspace_contact_must_be_attached_to_selected_channel(
    client, session_factory
):
    contact_id = _seed_thread(session_factory, messages=[])
    attached_channel_id = _channel_id(session_factory)
    _attach(session_factory, contact_id, attached_channel_id)

    db = session_factory()
    try:
        attached = db.query(Channel).filter(Channel.id == attached_channel_id).one()
        unattached = Channel(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=attached.workspace_id,
            channel_type="WHATSAPP",
            name="Unattached sandbox",
            credentials_json=encrypt_credentials({"dev": True}),
            is_active=True,
            is_trashed=False,
            status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
        )
        db.add(unattached)
        db.flush()
        agent = _make_agent(db, key="unattached_agent")
        workflow = _publish_workflow(db, channel_id=None, agent_id=agent.id)
        db.commit()
        unattached_id = unattached.id
        workflow_id = workflow.id
    finally:
        db.close()

    response = client.post(
        f"/workflows/{workflow_id}/run",
        headers=_headers(client),
        json=_request(unattached_id, contact_id),
    )
    assert response.status_code == 422, response.text
    assert _counts(session_factory, workflow_id, contact_id) == (0, 0, 0)


def test_manual_run_contract_remains_unchanged(client):
    headers = _headers(client)
    template = client.get("/workflows/template-options", headers=headers).json()[0]["value"]
    definition = {
        "schemaVersion": 1,
        "nodes": [
            {
                "id": "trigger",
                "kind": "trigger",
                "type": "manual",
                "config": {"inputs": [{"key": "email", "label": "Email", "type": "string"}]},
            },
            {
                "id": "action",
                "kind": "action",
                "type": "email.send",
                "config": {"mode": "template", "templateId": template, "to": "{{ trigger.input.email }}"},
            },
        ],
        "edges": [{"id": "edge", "source": "trigger", "target": "action", "sourcePort": "out"}],
    }
    workflow_id = client.post(
        "/workflows",
        headers=headers,
        json={"name": "Manual regression", "description": "", "draftDefinition": definition},
    ).json()["id"]

    response = client.post(
        f"/workflows/{workflow_id}/run",
        headers=headers,
        json={"inputs": {"email": "manual@example.com"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == RUN_SUCCESS
    assert response.json()["isTest"] is False
