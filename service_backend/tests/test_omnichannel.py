"""Omnichannel module endpoint tests (plan 04 Phase B).

Covers: workspace list/create/update + membership, channel onboarding
(Embedded Signup oauth-callback, dev mode) + list/get/by-workspace/test/
disconnect/restore/delete, and require_permission gating (403).
"""
from sqlalchemy.sql import func

from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _default_workspace_id(client) -> str:
    res = client.get("/omnichannel/workspaces", headers=_auth(client))
    assert res.status_code == 200
    data = res.json()["data"]
    return next(w["id"] for w in data if w["isDefault"])


# ── Workspaces ───────────────────────────────────────────────────────────────
def test_default_workspace_seeded(client):
    res = client.get("/omnichannel/workspaces", headers=_auth(client))
    assert res.status_code == 200
    names = [w["name"] for w in res.json()["data"]]
    assert "General" in names
    default = next(w for w in res.json()["data"] if w["isDefault"])
    assert default["status"] == "ACTIVE"


def test_create_update_workspace(client):
    h = _auth(client)
    created = client.post(
        "/omnichannel/workspaces", headers=h, json={"name": "Sales", "status": "ACTIVE"}
    )
    assert created.status_code == 201
    wid = created.json()["id"]
    assert created.json()["name"] == "Sales"

    updated = client.patch(
        f"/omnichannel/workspaces/{wid}", headers=h, json={"name": "Sales & Support", "status": "INACTIVE"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Sales & Support"
    assert updated.json()["status"] == "INACTIVE"


def test_workspace_members_assign_list_remove(client):
    h = _auth(client)
    wid = _default_workspace_id(client)

    # Assignable users include the seeded demo admin.
    assignable = client.get(f"/omnichannel/workspaces/{wid}/assignable", headers=h)
    assert assignable.status_code == 200
    candidates = assignable.json()
    assert len(candidates) >= 1
    uid = candidates[0]["userId"]

    # Assign → appears in members.
    assigned = client.post(
        f"/omnichannel/workspaces/{wid}/members", headers=h, json={"userIds": [uid]}
    )
    assert assigned.status_code == 204
    members = client.get(f"/omnichannel/workspaces/{wid}/members", headers=h).json()
    assert any(m["userId"] == uid for m in members)

    # Remove → gone.
    removed = client.delete(f"/omnichannel/workspaces/{wid}/members/{uid}", headers=h)
    assert removed.status_code == 204
    members2 = client.get(f"/omnichannel/workspaces/{wid}/members", headers=h).json()
    assert not any(m["userId"] == uid for m in members2)


def test_default_workspace_cannot_be_trashed(client):
    h = _auth(client)
    wid = _default_workspace_id(client)
    res = client.post("/omnichannel/workspaces/trash", headers=h, json={"ids": [wid]})
    assert res.status_code == 400


# ── Channels via onboarding ──────────────────────────────────────────────────
def _onboard(client, h, workspace_id, name="FoundryX WA"):
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
    )


def test_onboarding_surfaces_meta_exchange_error(client, monkeypatch):
    """A Meta code-exchange failure must surface as 400 + Meta's message — never
    an unhandled 500 (which loses CORS headers → browser shows 'Failed to fetch')."""
    import httpx

    from app.config import settings
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
    from modules.omnichannel.services import onboarding_service

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": (
                        "Error validating verification code. Please make sure your "
                        "redirect_uri is identical to the one you used in the OAuth "
                        "dialog request"
                    ),
                    "type": "OAuthException",
                    "code": 100,
                    "error_subcode": 36008,
                }
            },
        )

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        onboarding_service,
        "get_adapter",
        lambda channel_type="WHATSAPP": WhatsAppCloudAdapter(client=fake),
    )

    res = _onboard(client, _auth(client), _default_workspace_id(client))
    assert res.status_code == 400
    assert "Error validating verification code" in res.json()["detail"]


def test_onboarding_resolves_waba_phone_from_token(client, monkeypatch):
    """Self-hosted redirect flow: the client sends only code + redirectUri; the
    backend exchanges, then discovers the WABA + phone from the token
    (debug_token → phone_numbers) and provisions the channel."""
    import httpx

    from app.config import settings
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
    from modules.omnichannel.services import onboarding_service

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth/access_token"):
            # redirect_uri must be echoed verbatim (strict mode).
            assert request.url.params.get("redirect_uri") == "https://x.example/wa-callback"
            return httpx.Response(200, json={"access_token": "perm-token"})
        if path.endswith("/debug_token"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "granular_scopes": [
                            {"scope": "whatsapp_business_management", "target_ids": ["waba-xyz"]}
                        ]
                    }
                },
            )
        if path.endswith("/waba-xyz/phone_numbers"):
            return httpx.Response(
                200,
                json={"data": [{"id": "pn-xyz", "display_phone_number": "+65 9111 2222"}]},
            )
        if path.endswith("/pn-xyz"):
            return httpx.Response(
                200,
                json={"display_phone_number": "+65 9111 2222", "verified_name": "Acme"},
            )
        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        onboarding_service,
        "get_adapter",
        lambda channel_type="WHATSAPP": WhatsAppCloudAdapter(client=fake),
    )

    res = client.post(
        "/omnichannel/onboarding/oauth-callback",
        headers=_auth(client),
        json={
            "workspaceId": _default_workspace_id(client),
            "code": "auth-code",
            "redirectUri": "https://x.example/wa-callback",
        },
    )
    assert res.status_code == 201, res.text
    ch = res.json()
    assert ch["phoneNumberId"] == "pn-xyz"
    assert ch["wabaId"] == "waba-xyz"
    assert ch["displayPhoneNumber"] == "+65 9111 2222"
    assert ch["name"] == "Acme"


def test_onboarding_resolve_failure_is_400(client, monkeypatch):
    """Token exchanged but no number on the account → clean 400, not a 500."""
    import httpx

    from app.config import settings
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
    from modules.omnichannel.services import onboarding_service

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "perm-token"})
        if request.url.path.endswith("/debug_token"):
            return httpx.Response(200, json={"data": {"granular_scopes": []}})
        return httpx.Response(404, json={"error": {"message": "none"}})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        onboarding_service,
        "get_adapter",
        lambda channel_type="WHATSAPP": WhatsAppCloudAdapter(client=fake),
    )

    res = client.post(
        "/omnichannel/onboarding/oauth-callback",
        headers=_auth(client),
        json={
            "workspaceId": _default_workspace_id(client),
            "code": "auth-code",
            "redirectUri": "https://x.example/wa-callback",
        },
    )
    assert res.status_code == 400
    assert "no WhatsApp number" in res.json()["detail"]


def test_onboarding_provisions_channel(client):
    h = _auth(client)
    wid = _default_workspace_id(client)

    res = _onboard(client, h, wid)
    assert res.status_code == 201
    ch = res.json()
    assert ch["status"] == "ACTIVE"
    assert ch["workspaceId"] == wid
    assert ch["workspaceName"] == "General"
    assert ch["displayPhoneNumber"] == "+65 8000 0000"

    # Shows up in the channels list + by-workspace.
    listed = client.get("/omnichannel/channels", headers=h).json()
    assert any(c["id"] == ch["id"] for c in listed["data"])
    by_ws = client.get(f"/omnichannel/channels/by-workspace/{wid}", headers=h).json()
    assert any(c["id"] == ch["id"] for c in by_ws)


def test_channel_test_connection_and_lifecycle(client):
    h = _auth(client)
    wid = _default_workspace_id(client)
    ch = _onboard(client, h, wid).json()
    cid = ch["id"]

    # Test connection (dev mode → ok).
    test = client.post(f"/omnichannel/channels/{cid}/test", headers=h)
    assert test.status_code == 200
    assert test.json()["ok"] is True

    # Disconnect → moves to trashed; gone from active list.
    assert client.post("/omnichannel/channels/disconnect", headers=h, json={"ids": [cid]}).status_code == 204
    active = client.get("/omnichannel/channels", headers=h).json()
    assert not any(c["id"] == cid for c in active["data"])
    trashed = client.get("/omnichannel/channels?status_view=trashed", headers=h).json()
    assert any(c["id"] == cid for c in trashed["data"])

    # Restore → back in active.
    assert client.post("/omnichannel/channels/restore", headers=h, json={"ids": [cid]}).status_code == 204
    active2 = client.get("/omnichannel/channels", headers=h).json()
    assert any(c["id"] == cid for c in active2["data"])

    # Disconnect then permanently delete.
    client.post("/omnichannel/channels/disconnect", headers=h, json={"ids": [cid]})
    assert client.post("/omnichannel/channels/delete", headers=h, json={"ids": [cid]}).status_code == 204
    trashed2 = client.get("/omnichannel/channels?status_view=trashed", headers=h).json()
    assert not any(c["id"] == cid for c in trashed2["data"])


def test_manual_connect_provisions_channel(client):
    h = _auth(client)
    wid = _default_workspace_id(client)
    res = client.post(
        "/omnichannel/onboarding/manual-connect",
        headers=h,
        json={
            "workspaceId": wid,
            "accessToken": "EAAG-fake-system-user-token",
            "phoneNumberId": "pn-manual-1",
            "phoneNumber": "+60 16 675 3328",
        },
    )
    assert res.status_code == 201
    ch = res.json()
    assert ch["status"] == "ACTIVE"
    assert ch["phoneNumberId"] == "pn-manual-1"
    # dev mode (no Meta app in tests) falls back to the provided phone number.
    assert ch["displayPhoneNumber"] == "+60 16 675 3328"


def test_manual_connect_requires_phone_number_id(client):
    h = _auth(client)
    wid = _default_workspace_id(client)
    res = client.post(
        "/omnichannel/onboarding/manual-connect",
        headers=h,
        json={"workspaceId": wid, "accessToken": "tok"},
    )
    assert res.status_code == 400


def test_channel_update_toggles_status(client):
    h = _auth(client)
    wid = _default_workspace_id(client)
    cid = _onboard(client, h, wid).json()["id"]

    res = client.patch(f"/omnichannel/channels/{cid}", headers=h, json={"isActive": False})
    assert res.status_code == 200
    assert res.json()["isActive"] is False
    assert res.json()["status"] == "INACTIVE"


# ── Permission gating ────────────────────────────────────────────────────────
def test_omnichannel_requires_permission(client, session_factory):
    # An active user with no roles → no omnichannel.* keys → 403.
    db = session_factory()
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email="noperm@example.com",
            password=hash_password("noperm1234"),
            name="No Perm",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
    )
    db.commit()
    db.close()

    h = _auth(client, email="noperm@example.com", password="noperm1234")
    assert client.get("/omnichannel/workspaces", headers=h).status_code == 403
    assert client.get("/omnichannel/channels", headers=h).status_code == 403
