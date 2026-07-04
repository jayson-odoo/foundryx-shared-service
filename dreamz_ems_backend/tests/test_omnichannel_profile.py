"""WABA config + WhatsApp Business Profile tests (plan 06 Slice A).

Covers sync-config (business + verified name from the dev stub), profile
sync/mirror, save_profile validation matrix + changed-only write-through,
tenant-scoping (404), and permission gates. Dev-stub mode throughout
(no META_APP_ID) — the adapter returns canned data.
"""
from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _auth(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> dict:
    body = {"email": email, "password": password}
    if tenant_slug:
        body["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=body)
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _default_workspace_id(client, h) -> str:
    data = client.get("/omnichannel/workspaces", headers=h).json()["data"]
    return next(w["id"] for w in data if w["isDefault"])


def _onboard(client, h, workspace_id, name="Dreamz WA") -> dict:
    return client.post(
        "/omnichannel/onboarding/oauth-callback",
        headers=h,
        json={
            "workspaceId": workspace_id,
            "code": "mock-code-1",
            "wabaId": "waba-1",
            "phoneNumberId": "pn-1",
            "displayPhoneNumber": "+65 8000 0000",
            "businessName": name,
        },
    ).json()


def _channel(client, h) -> str:
    return _onboard(client, h, _default_workspace_id(client, h))["id"]


# ── sync-config ──────────────────────────────────────────────────────────────
def test_sync_config_writes_business_and_verified_name(client):
    h = _auth(client)
    cid = _channel(client, h)
    res = client.post(f"/omnichannel/channels/{cid}/sync-config", headers=h)
    assert res.status_code == 200
    body = res.json()
    # Dev stub canned name from fetch_waba_details.
    assert body["businessAccountName"] == "Dreamz Events (dev sandbox)"
    assert body["lastVerifiedAt"] is not None


# ── profile sync + mirror ────────────────────────────────────────────────────
def test_profile_empty_before_sync(client):
    h = _auth(client)
    cid = _channel(client, h)
    res = client.get(f"/omnichannel/channels/{cid}/profile", headers=h)
    assert res.status_code == 200
    body = res.json()
    assert body["about"] is None
    assert body["profileSyncedAt"] is None


def test_sync_profile_mirrors_fields_and_stamps(client):
    h = _auth(client)
    cid = _channel(client, h)
    res = client.post(f"/omnichannel/channels/{cid}/profile/sync", headers=h)
    assert res.status_code == 200
    body = res.json()
    assert body["about"] == "Premier event spaces & concierge in KL."
    assert body["vertical"] == "EVENT_PLAN"
    assert body["website1"] == "https://dreamz.example"
    assert body["profileSyncedAt"] is not None
    # Persists — re-GET serves the mirror.
    again = client.get(f"/omnichannel/channels/{cid}/profile", headers=h).json()
    assert again["about"] == "Premier event spaces & concierge in KL."


# ── save_profile validation matrix ───────────────────────────────────────────
def test_save_profile_bad_vertical_422(client):
    h = _auth(client)
    cid = _channel(client, h)
    res = client.patch(
        f"/omnichannel/channels/{cid}/profile", headers=h, json={"vertical": "NOT_A_VERTICAL"}
    )
    assert res.status_code == 422
    assert "vertical" in res.json()["detail"]["fieldErrors"]


def test_save_profile_bad_email_422(client):
    h = _auth(client)
    cid = _channel(client, h)
    res = client.patch(
        f"/omnichannel/channels/{cid}/profile", headers=h, json={"email": "not-an-email"}
    )
    assert res.status_code == 422
    assert "email" in res.json()["detail"]["fieldErrors"]


def test_save_profile_bad_website_422(client):
    h = _auth(client)
    cid = _channel(client, h)
    res = client.patch(
        f"/omnichannel/channels/{cid}/profile", headers=h, json={"website1": "ftp://nope"}
    )
    assert res.status_code == 422
    assert "website1" in res.json()["detail"]["fieldErrors"]


def test_save_profile_happy_path_writes_local(client):
    h = _auth(client)
    cid = _channel(client, h)
    res = client.patch(
        f"/omnichannel/channels/{cid}/profile",
        headers=h,
        json={"about": "New about text", "vertical": "RETAIL", "website1": "https://shop.example"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["about"] == "New about text"
    assert body["vertical"] == "RETAIL"
    assert body["website1"] == "https://shop.example"
    # Survives reload.
    again = client.get(f"/omnichannel/channels/{cid}/profile", headers=h).json()
    assert again["about"] == "New about text"


def test_save_profile_only_changed_fields_sent_to_meta(client, monkeypatch):
    """BR-6: only changed fields are POSTed to Meta."""
    from modules.omnichannel.services import channel_profile_service

    h = _auth(client)
    cid = _channel(client, h)
    # Seed a baseline from the stub.
    client.post(f"/omnichannel/channels/{cid}/profile/sync", headers=h)

    captured = {}

    class _Spy:
        channel_type = "WHATSAPP"

        def update_business_profile(self, creds, pn_id, fields):
            captured.update(fields)

    monkeypatch.setattr(
        channel_profile_service, "get_adapter", lambda channel_type="WHATSAPP": _Spy()
    )
    # Change only `about`; address/email/etc unchanged from the synced baseline.
    res = client.patch(
        f"/omnichannel/channels/{cid}/profile",
        headers=h,
        json={
            "about": "Changed only this",
            "vertical": "EVENT_PLAN",  # same as synced → not a change
        },
    )
    assert res.status_code == 200
    assert captured == {"about": "Changed only this"}


def test_save_profile_clearing_a_field_propagates_to_meta(client, monkeypatch):
    """A cleared field must be sent to Meta as "" (clear), not omitted — else the
    local mirror nulls while Meta keeps the old value (SEC-5 divergence)."""
    from modules.omnichannel.services import channel_profile_service

    h = _auth(client)
    cid = _channel(client, h)
    client.post(f"/omnichannel/channels/{cid}/profile/sync", headers=h)  # baseline has `about`

    captured = {}

    class _Spy:
        channel_type = "WHATSAPP"

        def update_business_profile(self, creds, pn_id, fields):
            captured.update(fields)

    monkeypatch.setattr(
        channel_profile_service, "get_adapter", lambda channel_type="WHATSAPP": _Spy()
    )
    res = client.patch(f"/omnichannel/channels/{cid}/profile", headers=h, json={"about": ""})
    assert res.status_code == 200
    assert captured == {"about": ""}  # explicit clear sent to Meta
    # Local mirror cleared too.
    again = client.get(f"/omnichannel/channels/{cid}/profile", headers=h).json()
    assert again["about"] is None


# ── tenant scoping ───────────────────────────────────────────────────────────
def test_profile_cross_tenant_404(client, session_factory):
    h = _auth(client)
    cid = _channel(client, h)
    # A second tenant's admin must not see tenant-1's channel. Install
    # omnichannel for the other tenant so calls clear the module gate and the
    # tenant-scoped repo is what yields 404 (not require_module's 403).
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    other = TenantService(db).provision(
        name="Other Co", slug="otherco-prof", admin_email="other-prof@example.com",
        admin_password="Password123!", admin_name="Other",
    )
    db.flush()
    AppStoreService(db).install(other.id, "omnichannel")
    db.commit()
    db.close()

    h2 = _auth(client, email="other-prof@example.com", password="Password123!", tenant_slug="otherco-prof")
    for path, method in [
        (f"/omnichannel/channels/{cid}/profile", "get"),
        (f"/omnichannel/channels/{cid}/sync-config", "post"),
        (f"/omnichannel/channels/{cid}/profile/sync", "post"),
    ]:
        res = getattr(client, method)(path, headers=h2)
        assert res.status_code == 404, f"{method} {path} → {res.status_code}"


# ── permission gates ─────────────────────────────────────────────────────────
def test_profile_permission_gates(client, session_factory):
    """GET profile = channels.read; sync/save = channels.manage. A no-role user
    is 403 everywhere."""
    db = session_factory()
    norole = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="norole-prof@example.com",
        name="No Role",
        password=hash_password("Password123!"),
        status=UserStatus.ACTIVE.value,
    )
    db.add(norole)
    db.commit()
    db.close()

    h = _auth(client)
    cid = _channel(client, h)
    hn = _auth(client, email="norole-prof@example.com", password="Password123!")
    assert client.get(f"/omnichannel/channels/{cid}/profile", headers=hn).status_code == 403
    assert client.post(f"/omnichannel/channels/{cid}/sync-config", headers=hn).status_code == 403
    assert client.patch(
        f"/omnichannel/channels/{cid}/profile", headers=hn, json={"about": "x"}
    ).status_code == 403
