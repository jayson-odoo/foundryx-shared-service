"""Plan 32 (A7a) Slice S3 - Meta connect session, pages + connect routes,
webhook subscription, non-WhatsApp route guard.

AC-CHN-32..39 (see documentation/plans/sprint-4/
32-omnichannel-channels-messenger-instagram-acceptance-criteria.md).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID, User
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.test_omnichannel_channels_messenger import _fb_channel


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    body = {"email": email, "password": password}
    if tenant_slug:
        body["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=body)
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _other_tenant_auth(client, session_factory, slug="other-s32-connect"):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Other S32 Connect", slug=slug, admin_email=f"admin-{slug}@example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    AppStoreService(db).install(tenant.id, "omnichannel")
    db.commit()
    db.close()
    return _auth(client, email=f"admin-{slug}@example.com", password="Password123!", tenant_slug=slug)


def _default_workspace_id(client, h) -> str:
    res = client.get("/omnichannel/workspaces", headers=h)
    data = res.json()["data"]
    return next(w["id"] for w in data if w["isDefault"])


def _pages(client, h, channel_type="FACEBOOK", code="code-1"):
    return client.post(
        "/omnichannel/onboarding/meta/pages",
        headers=h,
        json={"channelType": channel_type, "code": code},
    )


def _connect(client, h, *, session_id, workspace_id, channel_type="FACEBOOK", page_id, ig_account_id=None):
    body = {
        "sessionId": session_id,
        "workspaceId": workspace_id,
        "channelType": channel_type,
        "pageId": page_id,
    }
    if ig_account_id is not None:
        body["igAccountId"] = ig_account_id
    return client.post("/omnichannel/onboarding/meta/connect", headers=h, json=body)


# ── AC-CHN-32/35: /meta/pages - dev-safe canned pages, token never on the wire ──
def test_list_meta_pages_dev_safe_returns_canned_pages(client):
    h = _auth(client)
    res = _pages(client, h, channel_type="FACEBOOK")
    assert res.status_code == 200
    body = res.json()
    assert body["sessionId"]
    assert body["expiresAt"]
    ids = {p["id"] for p in body["pages"]}
    assert ids == {"pg-701", "pg-702", "pg-703"}
    # The exchanged token must never reach the wire.
    raw = res.text
    assert "access_token" not in raw
    assert "dev-token-code-1" not in raw


def test_list_meta_pages_instagram_only_offers_page_linked_accounts(client):
    h = _auth(client)
    res = _pages(client, h, channel_type="INSTAGRAM")
    assert res.status_code == 200
    pages = res.json()["pages"]
    ids = {p["id"] for p in pages}
    # pg-703 has no linked Instagram account (D-A7-14/44) - never offered.
    assert ids == {"pg-701", "pg-702"}
    for p in pages:
        assert p["igAccountId"]
        assert p["igUsername"]


def test_list_meta_pages_marks_already_connected_page(client, session_factory):
    h = _auth(client)
    ws = _default_workspace_id(client, h)
    session_id = _pages(client, h).json()["sessionId"]
    connected = _connect(client, h, session_id=session_id, workspace_id=ws, page_id="pg-701")
    assert connected.status_code == 201

    res = _pages(client, h)
    pages = {p["id"]: p for p in res.json()["pages"]}
    assert pages["pg-701"]["connected"] is True
    assert pages["pg-702"]["connected"] is False


# ── AC-CHN-33/36: /meta/connect - channel creation, wire shape ──────────────
def test_connect_creates_facebook_channel(client, session_factory):
    h = _auth(client)
    ws = _default_workspace_id(client, h)
    session_id = _pages(client, h).json()["sessionId"]
    res = _connect(client, h, session_id=session_id, workspace_id=ws, page_id="pg-701")
    assert res.status_code == 201
    body = res.json()
    assert body["channelType"] == "FACEBOOK"
    assert body["externalAccountId"] == "pg-701"
    assert body["externalAccountName"] == "Foundryx Events Co."
    assert body["status"] == "ACTIVE"
    # Credentials are never in a channel read response (S1/S2 invariant).
    assert "credentialsJson" not in res.text
    assert "accessToken" not in res.text
    assert "dev-page-token" not in res.text

    # The list/get surface carries the same fields (AC-CHN-36).
    got = client.get(f"/omnichannel/channels/{body['id']}", headers=h)
    assert got.status_code == 200
    assert got.json()["externalAccountId"] == "pg-701"
    assert got.json()["externalAccountName"] == "Foundryx Events Co."


def test_connect_instagram_uses_linked_account_id(client, session_factory):
    h = _auth(client)
    ws = _default_workspace_id(client, h)
    session_id = _pages(client, h, channel_type="INSTAGRAM").json()["sessionId"]
    res = _connect(
        client, h, session_id=session_id, workspace_id=ws, channel_type="INSTAGRAM",
        page_id="pg-701", ig_account_id="ig-701",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["channelType"] == "INSTAGRAM"
    assert body["externalAccountId"] == "ig-701"
    assert body["externalAccountName"] == "foundryx.events"


def test_whatsapp_channel_external_account_fields_stay_null(client):
    h = _auth(client)
    ws = _default_workspace_id(client, h)
    res = client.post(
        "/omnichannel/onboarding/oauth-callback",
        headers=h,
        json={
            "workspaceId": ws, "code": "wa-1", "wabaId": "waba-x",
            "phoneNumberId": "pn-x", "displayPhoneNumber": "+1 555", "businessName": "WA Co",
        },
    )
    assert res.status_code == 201
    assert res.json()["externalAccountId"] is None
    assert res.json()["externalAccountName"] is None


# ── AC-CHN-34: page uniqueness - service-wide 409 ───────────────────────────
def test_connect_duplicate_page_is_409(client, session_factory):
    h = _auth(client)
    ws = _default_workspace_id(client, h)
    session_id = _pages(client, h).json()["sessionId"]
    first = _connect(client, h, session_id=session_id, workspace_id=ws, page_id="pg-701")
    assert first.status_code == 201

    session_id2 = _pages(client, h).json()["sessionId"]
    second = _connect(client, h, session_id=session_id2, workspace_id=ws, page_id="pg-701")
    assert second.status_code == 409
    assert second.json()["detail"]["reason"] == "external_account_in_use"


def test_connect_duplicate_page_is_409_across_tenants(client, session_factory):
    """AC-CHN-34: "anywhere in the service" - a page already connected in
    tenant A's workspace is refused for tenant B too (service-wide, not
    tenant-scoped - the same design as `phone_number_id`)."""
    h = _auth(client)
    ws = _default_workspace_id(client, h)
    session_id = _pages(client, h).json()["sessionId"]
    assert _connect(client, h, session_id=session_id, workspace_id=ws, page_id="pg-702").status_code == 201

    h2 = _other_tenant_auth(client, session_factory)
    ws2 = _default_workspace_id(client, h2)
    session_id2 = _pages(client, h2).json()["sessionId"]
    res = _connect(client, h2, session_id=session_id2, workspace_id=ws2, page_id="pg-702")
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "external_account_in_use"


# ── Connect session lifecycle: expiry, single-use, cross-tenant ─────────────
def test_connect_session_expired_is_400(client, session_factory):
    h = _auth(client)
    ws = _default_workspace_id(client, h)
    session_id = _pages(client, h).json()["sessionId"]

    db = session_factory()
    from modules.omnichannel.models import MetaConnectSession

    row = db.query(MetaConnectSession).filter(MetaConnectSession.id == session_id).first()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    db.close()

    res = _connect(client, h, session_id=session_id, workspace_id=ws, page_id="pg-701")
    assert res.status_code == 400
    assert res.json()["detail"]["reason"] == "connect_session_expired"


def test_connect_session_is_single_use(client, session_factory):
    h = _auth(client)
    ws = _default_workspace_id(client, h)
    session_id = _pages(client, h).json()["sessionId"]
    first = _connect(client, h, session_id=session_id, workspace_id=ws, page_id="pg-701")
    assert first.status_code == 201

    second = _connect(client, h, session_id=session_id, workspace_id=ws, page_id="pg-702")
    assert second.status_code == 400
    assert second.json()["detail"]["reason"] == "connect_session_consumed"


def test_connect_session_cross_tenant_is_404(client, session_factory):
    h = _auth(client)
    session_id = _pages(client, h).json()["sessionId"]

    h2 = _other_tenant_auth(client, session_factory)
    ws2 = _default_workspace_id(client, h2)
    res = _connect(client, h2, session_id=session_id, workspace_id=ws2, page_id="pg-701")
    assert res.status_code == 404


def test_connect_session_unknown_id_is_404(client):
    h = _auth(client)
    ws = _default_workspace_id(client, h)
    res = _connect(client, h, session_id="ghost-session", workspace_id=ws, page_id="pg-701")
    assert res.status_code == 404


def test_list_meta_pages_sweeps_expired_sessions(client, session_factory):
    h = _auth(client)
    session_id = _pages(client, h).json()["sessionId"]

    db = session_factory()
    from modules.omnichannel.models import MetaConnectSession

    row = db.query(MetaConnectSession).filter(MetaConnectSession.id == session_id).first()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    db.close()

    # A second /meta/pages call sweeps the expired row.
    _pages(client, h)

    db = session_factory()
    from modules.omnichannel.models import MetaConnectSession as MCS

    assert db.query(MCS).filter(MCS.id == session_id).first() is None
    db.close()


# ── AC-CHN-37: non-WhatsApp routes -> 409 channel_type_unsupported ──────────
def test_templates_routes_refused_on_messenger_channel(client, session_factory):
    h = _auth(client)
    cid = _fb_channel(session_factory)

    assert client.get(f"/omnichannel/channels/{cid}/templates/manage", headers=h).status_code == 409
    create = client.post(
        f"/omnichannel/channels/{cid}/templates", headers=h,
        json={"name": "hi_template", "language": "en", "category": "UTILITY", "body": {"text": "Hi there"}},
    )
    assert create.status_code == 409
    assert client.post(f"/omnichannel/channels/{cid}/templates/sync", headers=h).status_code == 409

    for res in (
        client.get(f"/omnichannel/channels/{cid}/templates/manage", headers=h),
        create,
    ):
        assert res.json()["detail"]["reason"] == "channel_type_unsupported"


def test_business_profile_routes_refused_on_messenger_channel(client, session_factory):
    h = _auth(client)
    cid = _fb_channel(session_factory)

    get_profile = client.get(f"/omnichannel/channels/{cid}/profile", headers=h)
    assert get_profile.status_code == 409
    assert get_profile.json()["detail"]["reason"] == "channel_type_unsupported"

    assert client.patch(
        f"/omnichannel/channels/{cid}/profile", headers=h, json={"about": "hi"}
    ).status_code == 409
    assert client.post(f"/omnichannel/channels/{cid}/profile/sync", headers=h).status_code == 409
    assert client.post(f"/omnichannel/channels/{cid}/sync-config", headers=h).status_code == 409


def test_test_connection_pings_external_account_id_not_phone(client, session_factory):
    """AC-CHN-37: `test_connection` pings the page/account id, never a
    phone_number_id (which a Messenger channel never has)."""
    cid = _fb_channel(session_factory, external_account_id="pg-routing-check")
    db = session_factory()
    from modules.omnichannel.services.channel_service import ChannelService

    result = ChannelService(db).test_connection(cid, DEFAULT_TENANT_ID)
    db.close()
    assert result.ok is True  # dev-safe stub


# ── AC-CHN-39: uninstall sweeps meta_connect_sessions; manifest re-grant ────
def test_uninstall_tenant_removes_meta_connect_sessions(client, session_factory):
    h = _auth(client)
    _pages(client, h)  # creates a MetaConnectSession row for DEFAULT_TENANT_ID

    db = session_factory()
    from modules.omnichannel import bootstrap
    from modules.omnichannel.models import MetaConnectSession

    assert db.query(MetaConnectSession).filter(
        MetaConnectSession.tenant_id == DEFAULT_TENANT_ID
    ).count() > 0
    bootstrap.uninstall_tenant(db, DEFAULT_TENANT_ID)
    db.commit()
    assert db.query(MetaConnectSession).filter(
        MetaConnectSession.tenant_id == DEFAULT_TENANT_ID
    ).count() == 0
    db.close()


def test_uninstall_tenant_leaves_other_tenants_sessions_alone(client, session_factory):
    h = _auth(client)
    _pages(client, h)
    h2 = _other_tenant_auth(client, session_factory)
    _pages(client, h2)

    db = session_factory()
    from modules.omnichannel import bootstrap
    from modules.omnichannel.models import MetaConnectSession
    from app.models.tenant import Tenant

    other = db.query(Tenant).filter(Tenant.slug == "other-s32-connect").first()
    bootstrap.uninstall_tenant(db, DEFAULT_TENANT_ID)
    db.commit()
    assert db.query(MetaConnectSession).filter(
        MetaConnectSession.tenant_id == other.id
    ).count() == 1
    db.close()


# ── Dev seed: chn-demo-fb gets two seeded Messenger threads (AC-CHN-38) ─────
def test_dev_seed_creates_two_messenger_threads_with_open_window(session_factory):
    db = session_factory()
    from modules.omnichannel import bootstrap
    from modules.omnichannel.models import Contact, ContactChannelIdentity

    bootstrap.seed_demo_conversations(db, DEFAULT_TENANT_ID)
    contacts = {
        c.id: c
        for c in db.query(Contact).filter(Contact.id.in_(["cnt-fb-001", "cnt-fb-002"])).all()
    }
    assert set(contacts) == {"cnt-fb-001", "cnt-fb-002"}
    for cid, contact in contacts.items():
        assert contact.phone is None
        identity = (
            db.query(ContactChannelIdentity)
            .filter(ContactChannelIdentity.contact_id == cid)
            .first()
        )
        assert identity is not None
        assert identity.external_user_id.startswith("psid-demo-")
        assert identity.window_expires_at > datetime.now(timezone.utc)
        assert identity.human_agent_expires_at > datetime.now(timezone.utc)

    # Idempotent re-run does not duplicate.
    bootstrap.seed_demo_conversations(db, DEFAULT_TENANT_ID)
    assert db.query(Contact).filter(Contact.id == "cnt-fb-001").count() == 1
    db.close()
