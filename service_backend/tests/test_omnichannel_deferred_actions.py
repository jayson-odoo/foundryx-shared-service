"""Omnichannel's deferred (grace-window) action registrations (sprint-4/23,
T5 fix round 1, item 15; `contact_segments.delete` added plan 26 review round
1, Blocker 2) - migrating the module's own `confirm:`-gated destructive
actions onto the shared core grace-window engine (D2). Covers registration
for every key + park->lapse->commit end to end for each.
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


def _make_contact_segment(db, ws_id, name="VIPs"):
    from modules.omnichannel.models import ContactSegment

    row = ContactSegment(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, name=name,
        filter_json={"kind": "group", "combinator": "and", "rules": []},
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


def test_all_registered_omnichannel_keys_registered(db):
    for key in (
        "channels.disconnect",
        "channels.delete",
        "wa_templates.delete",
        "webhooks.set_active",
        "webhooks.delete",
        "quick_replies.delete",
        "api_keys.revoke",
        "contact_segments.delete",
        "workspaces.trash",
        "close_reasons.delete",
        "inbox_views.delete",
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


def test_contact_segments_delete(db):
    ws_id = _default_workspace_id(db)
    admin = _admin(db)
    segment = _make_contact_segment(db, ws_id)

    # `entity_id` is the bare segment id (globally unique PK) - the handler
    # resolves its owning workspace from the row itself.
    result = _park_and_lapse(db, admin, "contact_segments.delete", "contact_segment", segment.id)
    assert result.status == "committed"

    from modules.omnichannel.models import ContactSegment

    assert db.get(ContactSegment, segment.id) is None


def test_contact_segments_cancel_within_the_window_leaves_the_row_intact(db):
    """Review round 2, nit 11: the server side of blocker 2/should-fix 4's
    fix - Cancel arriving WHILE the window is still open must not commit,
    and the segment must still exist afterward (the frontend
    `use-segment-delete-controller.ts` calls this exact endpoint from the
    countdown toast's Cancel button)."""
    ws_id = _default_workspace_id(db)
    admin = _admin(db)
    segment = _make_contact_segment(db, ws_id, name="Cancel me")
    svc = PendingActionService(db)

    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="contact_segments.delete", entity_type="contact_segment", entity_id=segment.id,
    )
    cancelled = svc.cancel(DEFAULT_TENANT_ID, row.id, admin)
    assert cancelled.status == "cancelled"

    from modules.omnichannel.models import ContactSegment

    assert db.get(ContactSegment, segment.id) is not None  # never deleted


def test_contact_segments_missing_target_404_at_park(client):
    h = _auth(client)
    res = client.post(
        "/api/v1/pending-actions",
        headers=h,
        json={
            "actionKey": "contact_segments.delete",
            "entityType": "contact_segment",
            "entityId": "no-such-segment",
        },
    )
    assert res.status_code == 404


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


# ── Plan 27 review round 1 frontend follow-up: close_reasons.delete +
# inbox_views.delete migrated onto the deferred-actions engine ─────────────


def test_close_reasons_delete(db):
    from modules.omnichannel.models import CloseReason

    admin = _admin(db)
    ws_id = _default_workspace_id(db)
    reasons = db.query(CloseReason).filter(CloseReason.workspace_id == ws_id).all()
    reason = next(r for r in reasons if r.name == "Others")

    result = _park_and_lapse(db, admin, "close_reasons.delete", "close_reason", reason.id)
    assert result.status == "committed"
    assert db.get(CloseReason, reason.id) is None


def test_close_reasons_delete_fails_when_referenced(db, client, session_factory):
    """D-A3-13: a reason referenced by a closed conversation stays 409'd at
    the router AND fails loudly (never silently no-ops) via the deferred
    commit - the UI only offers Delete while `usesCount == 0`, so this only
    fires if the reason picks up a reference DURING the countdown."""
    from modules.omnichannel.models import CloseReason
    from tests.test_omnichannel_conversations import _seed_thread

    admin = _admin(db)
    ws_id = _default_workspace_id(db)
    reasons = db.query(CloseReason).filter(CloseReason.workspace_id == ws_id).all()
    reason = reasons[0]

    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="close_reasons.delete", entity_type="close_reason", entity_id=reason.id,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    # A conversation closes with this reason WHILE the countdown is open
    # (own session/commit, mirrors every other cross-session seed in this
    # suite - `_seed_thread` closes its own session).
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    h = _auth(client)
    client.post(f"/omnichannel/contacts/{cid}/close", headers=h, json={"closeReasonId": reason.id})

    committed = svc.commit_one(row)
    assert committed.status == "failed"
    assert committed.error_text
    assert db.get(CloseReason, reason.id) is not None


def test_inbox_views_delete_own_view_needs_only_conversations_read(db):
    from modules.omnichannel.models import InboxView
    from modules.omnichannel.schemas import InboxViewCreate
    from modules.omnichannel.services.inbox_view_service import InboxViewService

    admin = _admin(db)
    ws_id = _default_workspace_id(db)
    view = InboxViewService(db).create(
        ws_id, DEFAULT_TENANT_ID, admin.id, InboxViewCreate(name="Mine", isShared=False)
    )

    result = _park_and_lapse(db, admin, "inbox_views.delete", "inbox_view", view.id)
    assert result.status == "committed"
    assert db.get(InboxView, view.id) is None


def test_inbox_views_delete_shared_view_requires_manage(db, client, session_factory):
    """AC-IVE-19: a caller without `inbox_views.manage` may commit-delete
    their OWN view but never a SHARED one or someone else's - the countdown
    can start (park only checks the wider `conversations.read`), but the
    commit fails loudly rather than silently deleting it."""
    from modules.omnichannel.models import InboxView
    from modules.omnichannel.schemas import InboxViewCreate
    from modules.omnichannel.services.inbox_view_service import InboxViewService
    from tests.test_omnichannel_inbox_views import _limited_role_auth

    admin = _admin(db)
    ws_id = _default_workspace_id(db)
    shared_view = InboxViewService(db).create(
        ws_id, DEFAULT_TENANT_ID, admin.id, InboxViewCreate(name="Shared", isShared=True)
    )

    _h_limited, limited_user_id = _limited_role_auth(
        client, session_factory, keys=["conversations.read"], email="ive-deferred-noperm@example.com"
    )
    noperm = db.query(User).filter(User.id == limited_user_id).first()

    result = _park_and_lapse(db, noperm, "inbox_views.delete", "inbox_view", shared_view.id)
    assert result.status == "failed"
    assert result.error_text
    assert db.get(InboxView, shared_view.id) is not None


# ── Round-3 codex triage B9: commit-time authorization uses the EFFECTIVE
# user (park's `actor`), never the REAL actor (`requested_by_id`) - matches
# the house impersonation rule and closes the round-2 documented gap. ──────
def test_inbox_views_delete_own_view_authorizes_as_effective_user_under_impersonation(db):
    """A platform admin impersonating a tenant user parks with `actor` =
    the impersonated (effective) owner but `requested_by_id` = the real
    admin's OWN id (a different, non-tenant-scoped user). The commit must
    authorize (and delete) as the EFFECTIVE owner - never 404/403 just
    because the real actor id doesn't resolve in this tenant."""
    from app.models import PLATFORM_TENANT_ID
    from modules.omnichannel.models import InboxView
    from modules.omnichannel.schemas import InboxViewCreate
    from modules.omnichannel.services.inbox_view_service import InboxViewService

    owner = _admin(db)
    ws_id = _default_workspace_id(db)
    view = InboxViewService(db).create(
        ws_id, DEFAULT_TENANT_ID, owner.id, InboxViewCreate(name="Mine (impersonated)", isShared=False)
    )

    real_admin = (
        db.query(User)
        .filter(User.tenant_id == PLATFORM_TENANT_ID, User.email == "platform@example.com")
        .first()
    )
    assert real_admin is not None and real_admin.id != owner.id

    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=owner, requested_by_id=real_admin.id,
        action_key="inbox_views.delete", entity_type="inbox_view", entity_id=view.id,
    )
    assert row.payload_json["_effectiveUserId"] == owner.id
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    result = svc.commit_one(row)
    assert result.status == "committed"
    assert db.get(InboxView, view.id) is None


def test_inbox_views_delete_shared_view_still_requires_manage_under_impersonation(db, client, session_factory):
    """The impersonation fix must not become a bypass: an EFFECTIVE user
    without `inbox_views.manage` still cannot commit-delete a SHARED view,
    even though `requested_by_id` (the real actor) is a full admin."""
    from modules.omnichannel.models import InboxView
    from modules.omnichannel.schemas import InboxViewCreate
    from modules.omnichannel.services.inbox_view_service import InboxViewService
    from tests.test_omnichannel_inbox_views import _limited_role_auth

    admin = _admin(db)
    ws_id = _default_workspace_id(db)
    shared_view = InboxViewService(db).create(
        ws_id, DEFAULT_TENANT_ID, admin.id, InboxViewCreate(name="Shared 2", isShared=True)
    )

    _h_limited, limited_user_id = _limited_role_auth(
        client, session_factory, keys=["conversations.read"], email="ive-deferred-noperm2@example.com"
    )
    noperm = db.query(User).filter(User.id == limited_user_id).first()

    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=noperm, requested_by_id=admin.id,
        action_key="inbox_views.delete", entity_type="inbox_view", entity_id=shared_view.id,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    result = svc.commit_one(row)
    assert result.status == "failed"
    assert db.get(InboxView, shared_view.id) is not None


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


def test_current_and_cancel_rejected_when_the_module_is_inactive_for_the_tenant(client, session_factory):
    """T5 fix round 3, item 3: `park` already 403s (S4) once the module is
    inactive - `current`/`cancel` on a row parked while the module was still
    ACTIVE must ALSO refuse once it goes INACTIVE (`_may_act_on` gates both
    via the same `_module_active` check `park` uses)."""
    from app.models import Tenant
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService
    from modules.omnichannel.models import Workspace

    db = session_factory()
    TenantService(db).provision(
        name="Gamma", slug="gamma-mod-gate", admin_name="Gia",
        admin_email="admin@gamma-mod-gate.example.com", admin_password="pw12345678",
    )
    tenant = db.query(Tenant).filter(Tenant.slug == "gamma-mod-gate").first()
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
            "email": "admin@gamma-mod-gate.example.com",
            "password": "pw12345678",
            "tenantSlug": "gamma-mod-gate",
        },
    )
    assert login_res.status_code == 200, login_res.text
    h = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    park_res = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "workspaces.trash", "entityType": "workspace", "entityId": ws_id},
        headers=h,
    )
    assert park_res.status_code == 202, park_res.text
    action_id = park_res.json()["id"]

    # Module still ACTIVE - both observe and cancel work.
    current_res = client.get(
        "/api/v1/pending-actions/current",
        params={"entityType": "workspace", "entityId": ws_id},
        headers=h,
    )
    assert current_res.status_code == 200, current_res.text
    assert current_res.json()["pending"] is not None

    db2 = session_factory()
    AppStoreService(db2).deactivate(tenant.id, "omnichannel")
    db2.close()

    # Module now INACTIVE - `current` 404s uniformly (matches the S4/S5
    # permission-denied contract) and `cancel` 403s (matches `park`'s own
    # `PermissionDenied` -> 403 contract, not a 404 - the id itself already
    # resolved above, so there's nothing left to enumerate).
    current_res2 = client.get(
        "/api/v1/pending-actions/current",
        params={"entityType": "workspace", "entityId": ws_id},
        headers=h,
    )
    assert current_res2.status_code == 404, current_res2.text

    cancel_res = client.post(f"/api/v1/pending-actions/{action_id}/cancel", headers=h)
    assert cancel_res.status_code == 403, cancel_res.text


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
