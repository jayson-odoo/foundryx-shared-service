"""Omnichannel's deferred (grace-window) action registrations (sprint-4/23,
T5 fix round 1, item 15) - migrating the module's own `confirm:`-gated
destructive actions onto the shared core grace-window engine (D2). Covers
registration for all 8 keys + park->lapse->commit end to end for each.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.deferred_actions.registry import deferred_action_for
from app.deferred_actions.service import PendingActionService
from app.models import DEFAULT_TENANT_ID, User
from app.models.pending_action import PendingAction
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _admin(db) -> User:
    return db.query(User).filter(User.email == ACTIVE_EMAIL).first()


def _default_workspace_id(db):
    from modules.omnichannel.models import Workspace

    return db.query(Workspace).filter(Workspace.is_default.is_(True)).first().id


def _make_channel(db, ws_id, name="Test WhatsApp"):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    channel = Channel(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws_id,
        channel_type="WHATSAPP",
        name=name,
        credentials_json=encrypt_credentials({"dev": True}),
        phone_number_id=f"pn-{name}",
        display_phone_number="+60 11-111 1111",
        is_active=True,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def _make_webhook(db, ws_id, channel_id):
    from modules.omnichannel.models import WebhookEndpoint
    from modules.omnichannel.security import encrypt_credentials

    row = WebhookEndpoint(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws_id,
        channel_id=channel_id,
        name="Consumer endpoint",
        url="https://consumer.example.com/hook",
        secret_encrypted=encrypt_credentials({"secret": "s"}),
        events_json=["message.inbound"],
        status="ACTIVE",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _make_quick_reply(db, ws_id):
    from modules.omnichannel.models import QuickReply

    row = QuickReply(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, shortcut="/hi", body="Hello!")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _make_wa_template(db, channel_id):
    from modules.omnichannel.models import WhatsappTemplate

    row = WhatsappTemplate(
        tenant_id=DEFAULT_TENANT_ID,
        channel_id=channel_id,
        name="greeting",
        language="en_US",
        category="MARKETING",
        components_json=[],
        status="LOCAL_DRAFT",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _park_and_lapse(db, admin, action_key, entity_type, entity_id, payload=None):
    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key=action_key, entity_type=entity_type, entity_id=entity_id, payload=payload,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()
    return svc.commit_one(row)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_all_eight_omnichannel_keys_registered(db):
    for key in (
        "channels.disconnect",
        "channels.delete",
        "wa_templates.delete",
        "webhooks.set_active",
        "webhooks.delete",
        "quick_replies.delete",
        "api_keys.revoke",
        "workspaces.trash",
    ):
        assert deferred_action_for(key).key == key


def test_channels_disconnect_and_delete(db):
    admin = _admin(db)
    ws_id = _default_workspace_id(db)
    channel = _make_channel(db, ws_id, "Disconnect me")

    result = _park_and_lapse(db, admin, "channels.disconnect", "channel", channel.id)
    assert result.status == "committed"
    db.refresh(channel)
    assert channel.is_trashed is True

    result2 = _park_and_lapse(db, admin, "channels.delete", "channel", channel.id)
    assert result2.status == "committed"

    from modules.omnichannel.models import Channel

    assert db.get(Channel, channel.id) is None


def test_channels_missing_target_404_at_park(client):
    h = _auth(client)
    res = client.post(
        "/api/v1/pending-actions",
        headers=h,
        json={"actionKey": "channels.delete", "entityType": "channel", "entityId": "no-such-channel"},
    )
    assert res.status_code == 404


def test_wa_templates_delete(db):
    admin = _admin(db)
    ws_id = _default_workspace_id(db)
    channel = _make_channel(db, ws_id, "Template channel")
    template = _make_wa_template(db, channel.id)

    result = _park_and_lapse(db, admin, "wa_templates.delete", "wa_template", template.id)
    assert result.status == "committed"

    from modules.omnichannel.models import WhatsappTemplate

    assert db.get(WhatsappTemplate, template.id) is None


def test_webhooks_set_active_and_delete(db):
    admin = _admin(db)
    ws_id = _default_workspace_id(db)
    channel = _make_channel(db, ws_id, "Webhook channel")
    endpoint = _make_webhook(db, ws_id, channel.id)

    result = _park_and_lapse(
        db, admin, "webhooks.set_active", "webhook_endpoint", endpoint.id, payload={"active": False}
    )
    assert result.status == "committed"
    db.refresh(endpoint)
    assert endpoint.status == "DISABLED"

    result2 = _park_and_lapse(db, admin, "webhooks.delete", "webhook_endpoint", endpoint.id)
    assert result2.status == "committed"

    from modules.omnichannel.models import WebhookEndpoint

    assert db.get(WebhookEndpoint, endpoint.id) is None


def test_quick_replies_delete(db):
    admin = _admin(db)
    ws_id = _default_workspace_id(db)
    qr = _make_quick_reply(db, ws_id)

    # `entity_id` is the bare quick-reply id (globally unique PK) - the
    # handler resolves its owning workspace from the row itself.
    result = _park_and_lapse(db, admin, "quick_replies.delete", "quick_reply", qr.id)
    assert result.status == "committed"

    from modules.omnichannel.models import QuickReply

    assert db.get(QuickReply, qr.id) is None


def test_api_keys_revoke(db):
    from modules.omnichannel.services.api_key_service import ApiKeyService

    admin = _admin(db)
    ws_id = _default_workspace_id(db)
    key_row, _plaintext = ApiKeyService(db).mint(DEFAULT_TENANT_ID, ws_id, "Test key", admin.id)

    # `entity_id` is the bare key id (globally unique PK) - the handler
    # resolves its owning workspace from the row itself.
    result = _park_and_lapse(db, admin, "api_keys.revoke", "api_key", key_row.id)
    assert result.status == "committed"

    db.refresh(key_row)
    assert key_row.revoked_at is not None


def test_workspaces_trash(db):
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    admin = _admin(db)
    ws = Workspace(
        tenant_id=DEFAULT_TENANT_ID,
        name="Extra workspace",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
        is_default=False,
        is_trashed=False,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)

    result = _park_and_lapse(db, admin, "workspaces.trash", "workspace", ws.id)
    assert result.status == "committed"
    db.refresh(ws)
    assert ws.is_trashed is True
