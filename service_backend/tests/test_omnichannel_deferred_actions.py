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


def test_workspaces_trash_fails_when_the_workspace_is_gone_by_commit_time(db):
    """T5 fix round 2, S3: `WorkspaceService.trash` is bulk-shaped (`get_many`
    loop) and silently no-ops on a missing id - a workspace removed between
    park and commit must fail the commit loudly (row `failed`, `error_text`
    set), never report `committed` for a row it never touched."""
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    admin = _admin(db)
    ws = Workspace(
        tenant_id=DEFAULT_TENANT_ID,
        name="Vanishing workspace",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
        is_default=False,
        is_trashed=False,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    ws_id = ws.id

    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="workspaces.trash", entity_type="workspace", entity_id=ws_id,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    # The workspace vanishes (hard-deleted) before the sweep gets to it.
    db.delete(db.get(Workspace, ws_id))
    db.commit()

    committed = svc.commit_one(row)
    assert committed.status == "failed"
    assert committed.error_text
    assert db.get(Workspace, ws_id) is None


# ── T5 fix round 2, S4: module gating - a tenant with omnichannel INACTIVE
# cannot park (or keep observing) one of its actions. ──────────────────────


def test_park_rejected_when_the_module_is_inactive_for_the_tenant(client, session_factory):
    from app.models import Tenant
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService
    from modules.omnichannel.models import Workspace

    db = session_factory()
    TenantService(db).provision(
        name="Beta", slug="beta-mod-gate", admin_name="Bea",
        admin_email="admin@beta-mod-gate.example.com", admin_password="pw12345678",
    )
    tenant = db.query(Tenant).filter(Tenant.slug == "beta-mod-gate").first()
    AppStoreService(db).install(tenant.id, "omnichannel")
    ws = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == tenant.id, Workspace.is_default.is_(True))
        .first()
    )
    ws_id = ws.id
    db.close()

    login_res = client.post(
        "/auth/login",
        json={
            "email": "admin@beta-mod-gate.example.com",
            "password": "pw12345678",
            "tenantSlug": "beta-mod-gate",
        },
    )
    assert login_res.status_code == 200, login_res.text
    h = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    # Module ACTIVE - park succeeds (the admin's install-time grant covers
    # `workspaces.manage`).
    res = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "workspaces.trash", "entityType": "workspace", "entityId": ws_id},
        headers=h,
    )
    assert res.status_code == 202, res.text

    # Cancel it so the second park below isn't short-circuited by the
    # idempotent-existing-pending-row path.
    action_id = res.json()["id"]
    cancel_res = client.post(f"/api/v1/pending-actions/{action_id}/cancel", headers=h)
    assert cancel_res.status_code == 200, cancel_res.text

    db2 = session_factory()
    AppStoreService(db2).deactivate(tenant.id, "omnichannel")
    db2.close()

    # Module now INACTIVE - park is rejected even though the admin's role
    # still carries the (now-inert) `workspaces.manage` grant from before
    # deactivation (deactivate keeps grants, unlike uninstall).
    res2 = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "workspaces.trash", "entityType": "workspace", "entityId": ws_id},
        headers=h,
    )
    assert res2.status_code == 403, res2.text


# ── T5 fix round 3, item 1: `commit_one`/`commit_due` must ALSO gate on
# module activation - only the lazy `current()` path was gated before this
# fix, so the beat sweep (or a racing `current` poll) could still run a
# handler for an action whose module had since been deactivated. ──────────


def test_commit_settles_failed_when_the_module_is_deactivated_during_the_window(session_factory):
    """A park while ACTIVE, followed by a deactivation DURING the grace
    window, must settle the row `failed` at commit time - never run the
    (now module-less) handler."""
    from app.services.app_store_service import AppStoreService
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    db = session_factory()
    admin = _admin(db)
    ws = Workspace(
        tenant_id=DEFAULT_TENANT_ID,
        name="Deactivated-mid-window workspace",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
        is_default=False,
        is_trashed=False,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    ws_id = ws.id

    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="workspaces.trash", entity_type="workspace", entity_id=ws_id,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")

    committed = svc.commit_one(row)
    assert committed.status == "failed"
    assert committed.error_text == "Module 'omnichannel' is not active"
    db.refresh(ws)
    assert ws.is_trashed is False
    db.close()


def test_commit_due_settles_failed_when_the_module_is_deactivated_during_the_window(session_factory):
    """Same as above, via the beat sweep (`commit_due`) rather than a direct
    `commit_one` call - the sweep must not bypass the module gate either."""
    from app.services.app_store_service import AppStoreService
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    db = session_factory()
    admin = _admin(db)
    ws = Workspace(
        tenant_id=DEFAULT_TENANT_ID,
        name="Swept-while-inactive workspace",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
        is_default=False,
        is_trashed=False,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    ws_id = ws.id

    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="workspaces.trash", entity_type="workspace", entity_id=ws_id,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")

    swept = svc.commit_due()
    assert swept == 1
    db.refresh(pa)
    assert pa.status == "failed"
    assert pa.error_text == "Module 'omnichannel' is not active"
    db.refresh(ws)
    assert ws.is_trashed is False
    db.close()
