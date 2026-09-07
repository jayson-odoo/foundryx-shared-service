"""Plan 34 (A7b) Slice S1 - web chat channel type: model + migration, the
origins pure move, connect/widget-config/rotate-secret/sign-out-visitors
routes, the WhatsApp-only-route guard mirrored for web-chat-only routes, and
the public loader `.js` route.

AC-WEB-12..22 (see documentation/plans/sprint-4/
34-omnichannel-channel-web-chat-acceptance-criteria.md). AC-WEB-12..15
(registry/policy/capability/addressing parity) live in
`test_omnichannel_channels_send.py` alongside their WhatsApp/Messenger/
Instagram siblings - this file covers the rest (AC-WEB-16..22).
"""
import importlib

import pytest

from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.test_omnichannel_channels_messenger import _fb_channel

ALEMBIC_REV = "0021_omni_webchat"


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    body = {"email": email, "password": password}
    if tenant_slug:
        body["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=body)
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _other_tenant_auth(client, session_factory, slug="other-s34-webchat"):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Other S34 Webchat", slug=slug, admin_email=f"admin-{slug}@example.com",
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


def _connect(client, h, *, name="Test Web Chat", allowed_origins=None):
    ws_id = _default_workspace_id(client, h)
    return client.post(
        "/omnichannel/onboarding/webchat/connect",
        headers=h,
        json={
            "name": name,
            "workspaceId": ws_id,
            "allowedOrigins": allowed_origins if allowed_origins is not None else ["https://shop.acme.com"],
        },
    )


# ── AC-WEB-16: migration + model columns ─────────────────────────────────────
def test_migration_0021_revision_sanity():
    mod = importlib.import_module(f"modules.omnichannel.alembic.versions.{ALEMBIC_REV}")
    assert mod.revision == ALEMBIC_REV
    assert len(mod.revision) <= 32
    assert mod.down_revision == "0020_omni_meta_connect"
    assert callable(mod.upgrade) and callable(mod.downgrade)


def test_channel_and_identity_columns_exist():
    from modules.omnichannel.models import Channel, ContactChannelIdentity

    assert hasattr(Channel, "widget_key")
    assert hasattr(Channel, "widget_config_json")
    assert hasattr(Channel, "widget_token_epoch")
    assert hasattr(ContactChannelIdentity, "last_seen_at")


def test_manifest_version_bumped_and_widget_router_public():
    import json
    from pathlib import Path

    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "modules" / "omnichannel" / "manifest.json").read_text()
    )
    assert manifest["version"] == "0.10.0"
    widget = next(r for r in manifest["routers"] if r["name"] == "webchat_widget")
    assert widget["prefix"] == "/omnichannel/widget"
    assert widget["public"] is True


# ── AC-WEB-17: the origins pure move ─────────────────────────────────────────
def test_origins_module_is_the_one_validator():
    """D-A7B-13 - `embed_config_service` re-imports the SAME names from
    `origins.py` rather than defining its own (a pure move)."""
    from modules.omnichannel import origins
    from modules.omnichannel.services import embed_config_service

    assert embed_config_service.InvalidOrigin is origins.InvalidOrigin
    assert embed_config_service._validate_origin is origins._validate_origin
    assert embed_config_service._validate_origins is origins._validate_origins
    assert origins._validate_origin("https://crm.acme.com") == "https://crm.acme.com"
    with pytest.raises(origins.InvalidOrigin):
        origins._validate_origin("https://*.acme.com")


# ── AC-WEB-18: connect mints a channel + secret, revealed exactly once ──────
def test_connect_creates_active_webchat_channel_and_reveals_secret_once(client):
    h = _auth(client)
    res = _connect(client, h, name="  Support Chat  ")
    assert res.status_code == 201
    body = res.json()
    assert body["channelType"] == "WEBCHAT"
    assert body["status"] == "ACTIVE"
    assert body["isActive"] is True
    assert body["name"] == "Support Chat"
    assert body["widgetKey"] and body["widgetKey"].startswith("wk_")
    assert body["widgetSecret"] and body["widgetSecret"].startswith("whsec_")
    channel_id = body["id"]

    # Never again on any subsequent read.
    get_channel = client.get(f"/omnichannel/channels/{channel_id}", headers=h)
    assert get_channel.status_code == 200
    assert "widgetSecret" not in get_channel.json()

    get_widget = client.get(f"/omnichannel/channels/{channel_id}/widget", headers=h)
    assert get_widget.status_code == 200
    assert "widgetSecret" not in get_widget.json()
    assert get_widget.json()["widgetKey"] == body["widgetKey"]
    assert get_widget.json()["tokenEpoch"] == 0
    assert get_widget.json()["allowedOrigins"] == ["https://shop.acme.com"]
    assert get_widget.json()["snippet"].endswith(f'{body["widgetKey"]}.js" async></script>')


def test_connect_workspace_not_found_is_404(client):
    h = _auth(client)
    res = client.post(
        "/omnichannel/onboarding/webchat/connect",
        headers=h,
        json={"name": "Nope", "workspaceId": "ws-does-not-exist", "allowedOrigins": []},
    )
    assert res.status_code == 404


def test_connect_invalid_origin_is_422(client):
    h = _auth(client)
    res = _connect(client, h, allowed_origins=["https://*.acme.com"])
    assert res.status_code == 422
    assert "allowedOrigins" in res.json()["detail"]["fieldErrors"]


def test_connect_requires_authentication(client):
    """`channels.manage` is gated the same way every onboarding route already
    is (AC-WEB-22 - no new permission key, the existing dependency covers
    it) - no Authorization header at all is a clean 401."""
    res = client.post(
        "/omnichannel/onboarding/webchat/connect",
        json={"name": "x", "workspaceId": "irrelevant", "allowedOrigins": []},
    )
    assert res.status_code == 401


# ── Widget config read/write (D-A7B-6 style partial PATCH shape) ────────────
def test_widget_config_put_partial_does_not_clobber_other_fields(client):
    h = _auth(client)
    channel_id = _connect(client, h).json()["id"]

    updated = client.put(
        f"/omnichannel/channels/{channel_id}/widget",
        headers=h,
        json={"greeting": "Yo!"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["greeting"] == "Yo!"
    # Untouched fields keep their defaults.
    assert body["offlineGreeting"]
    assert body["appearance"]["accentColor"] == "#FF5A00"
    assert body["allowedOrigins"] == ["https://shop.acme.com"]

    updated2 = client.put(
        f"/omnichannel/channels/{channel_id}/widget",
        headers=h,
        json={"appearance": {"position": "left"}},
    )
    assert updated2.status_code == 200
    body2 = updated2.json()
    assert body2["appearance"]["position"] == "left"
    assert body2["appearance"]["accentColor"] == "#FF5A00"  # untouched
    assert body2["greeting"] == "Yo!"  # earlier partial write survives


def test_widget_config_put_invalid_origin_is_422(client):
    h = _auth(client)
    channel_id = _connect(client, h).json()["id"]
    res = client.put(
        f"/omnichannel/channels/{channel_id}/widget",
        headers=h,
        json={"allowedOrigins": ["not-a-url"]},
    )
    assert res.status_code == 422
    assert "allowedOrigins" in res.json()["detail"]["fieldErrors"]


def test_widget_config_put_invalid_position_is_422(client):
    h = _auth(client)
    channel_id = _connect(client, h).json()["id"]
    res = client.put(
        f"/omnichannel/channels/{channel_id}/widget",
        headers=h,
        json={"appearance": {"position": "middle"}},
    )
    assert res.status_code == 422


# ── AC-WEB-19: rotate-secret / sign-out-visitors ─────────────────────────────
def test_rotate_secret_returns_new_secret_previous_stops_verifying_epoch_unchanged(
    client, session_factory
):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.services.webchat_service import widget_secret_for

    h = _auth(client)
    connect_body = _connect(client, h).json()
    channel_id = connect_body["id"]
    original_secret = connect_body["widgetSecret"]

    rotated = client.post(f"/omnichannel/channels/{channel_id}/widget/rotate-secret", headers=h)
    assert rotated.status_code == 200
    new_secret = rotated.json()["widgetSecret"]
    assert new_secret != original_secret
    assert new_secret.startswith("whsec_")

    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    assert widget_secret_for(channel) == new_secret  # the OLD one is gone - stops verifying
    assert channel.widget_token_epoch == 0  # D-A7B-6: rotate never bumps the epoch
    db.close()

    widget = client.get(f"/omnichannel/channels/{channel_id}/widget", headers=h)
    assert widget.json()["tokenEpoch"] == 0


def test_sign_out_visitors_bumps_epoch_secret_unchanged(client, session_factory):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.services.webchat_service import widget_secret_for

    h = _auth(client)
    connect_body = _connect(client, h).json()
    channel_id = connect_body["id"]
    secret_before = connect_body["widgetSecret"]

    signed_out = client.post(
        f"/omnichannel/channels/{channel_id}/widget/sign-out-visitors", headers=h
    )
    assert signed_out.status_code == 200
    assert signed_out.json()["tokenEpoch"] == 1

    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    assert channel.widget_token_epoch == 1
    assert widget_secret_for(channel) == secret_before  # D-A7B-6: secret untouched
    db.close()

    # Bumping again is cumulative.
    signed_out2 = client.post(
        f"/omnichannel/channels/{channel_id}/widget/sign-out-visitors", headers=h
    )
    assert signed_out2.json()["tokenEpoch"] == 2


# ── Guard: web-chat-only routes refuse a non-WEBCHAT channel (and vice versa) ─
def test_widget_routes_refused_on_messenger_channel_409(client, session_factory):
    h = _auth(client)
    cid = _fb_channel(session_factory)

    for res in (
        client.get(f"/omnichannel/channels/{cid}/widget", headers=h),
        client.put(f"/omnichannel/channels/{cid}/widget", headers=h, json={}),
        client.post(f"/omnichannel/channels/{cid}/widget/rotate-secret", headers=h),
        client.post(f"/omnichannel/channels/{cid}/widget/sign-out-visitors", headers=h),
    ):
        assert res.status_code == 409
        assert res.json()["detail"]["reason"] == "channel_type_unsupported"


def test_templates_and_profile_routes_refused_on_webchat_channel_409(client):
    """Plan §5.1 - the SAME typed 409 the A7a guard already produces for any
    non-WhatsApp channel (WEBCHAT included, no new code needed)."""
    h = _auth(client)
    cid = _connect(client, h).json()["id"]

    for res in (
        client.get(f"/omnichannel/channels/{cid}/templates/manage", headers=h),
        client.get(f"/omnichannel/channels/{cid}/profile", headers=h),
        client.post(f"/omnichannel/channels/{cid}/sync-config", headers=h),
    ):
        assert res.status_code == 409
        assert res.json()["detail"]["reason"] == "channel_type_unsupported"


def test_widget_routes_404_on_unknown_channel(client):
    h = _auth(client)
    assert client.get("/omnichannel/channels/does-not-exist/widget", headers=h).status_code == 404
    assert client.post(
        "/omnichannel/channels/does-not-exist/widget/rotate-secret", headers=h
    ).status_code == 404
    assert client.post(
        "/omnichannel/channels/does-not-exist/widget/sign-out-visitors", headers=h
    ).status_code == 404


def test_cross_tenant_404_on_every_admin_widget_route(client, session_factory):
    h = _auth(client)
    channel_id = _connect(client, h).json()["id"]
    other_h = _other_tenant_auth(client, session_factory)

    assert client.get(f"/omnichannel/channels/{channel_id}/widget", headers=other_h).status_code == 404
    assert client.put(
        f"/omnichannel/channels/{channel_id}/widget", headers=other_h, json={}
    ).status_code == 404
    assert client.post(
        f"/omnichannel/channels/{channel_id}/widget/rotate-secret", headers=other_h
    ).status_code == 404
    assert client.post(
        f"/omnichannel/channels/{channel_id}/widget/sign-out-visitors", headers=other_h
    ).status_code == 404
    other_ws = _default_workspace_id(client, other_h)
    connect_cross = client.post(
        "/omnichannel/onboarding/webchat/connect",
        headers=other_h,
        json={"name": "Cross", "workspaceId": other_ws, "allowedOrigins": []},
    )
    assert connect_cross.status_code == 201  # the OTHER tenant may connect its OWN channel
    # ... but it must never see the FIRST tenant's channel via any route above.


# ── AC-WEB-22: no new permission rows ────────────────────────────────────────
def test_no_new_permission_rows_required():
    from pathlib import Path

    csv_text = (
        Path(__file__).resolve().parents[1]
        / "modules" / "omnichannel" / "permissions" / "permissions.csv"
    ).read_text()
    assert "widget" not in csv_text.lower()
    assert "webchat" not in csv_text.lower()


# ── AC-WEB-20/21: the public loader route ────────────────────────────────────
def _js(client, widget_key: str):
    return client.get(f"/omnichannel/widget/{widget_key}.js")


def test_loader_route_serves_js_with_headers_and_substitutions(client):
    h = _auth(client)
    connect_body = _connect(client, h).json()
    widget_key = connect_body["widgetKey"]

    res = _js(client, widget_key)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/javascript; charset=utf-8"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["cache-control"] == "public, max-age=300"
    assert res.headers.get("etag")
    # The two substitutions land as separate JS string literals (WIDGET_KEY /
    # PANEL_ORIGIN) - the panel URL is concatenated in the BROWSER, not baked
    # into the served source as one literal string.
    assert widget_key in res.text
    assert "/public/webchat/" in res.text
    assert "http://localhost:3001" in res.text  # settings.frontend_url default


def test_loader_route_carries_no_tenant_identifying_strings(client):
    """AC-WEB-20 - the body contains the widget key and the panel origin and
    NOTHING else that is tenant-identifying: no tenant slug, no tenant name,
    no secret, no origin list, no branding."""
    h = _auth(client)
    connect_body = _connect(client, h, name="Very Secret Tenant Name Inc").json()
    widget_key = connect_body["widgetKey"]
    widget_secret = connect_body["widgetSecret"]

    body = _js(client, widget_key).text
    assert "Very Secret Tenant Name" not in body
    assert widget_secret not in body
    assert "shop.acme.com" not in body  # the connected allowed origin
    assert "default" not in body.lower()  # the seeded tenant slug never leaks in


def test_loader_route_unknown_key_is_404(client):
    res = _js(client, "wk_does_not_exist_at_all_0000000")
    assert res.status_code == 404


def test_loader_route_trashed_channel_is_404(client):
    h = _auth(client)
    connect_body = _connect(client, h).json()
    channel_id, widget_key = connect_body["id"], connect_body["widgetKey"]
    client.post("/omnichannel/channels/disconnect", headers=h, json={"ids": [channel_id]})
    assert _js(client, widget_key).status_code == 404


def test_loader_route_inactive_channel_is_404(client):
    h = _auth(client)
    connect_body = _connect(client, h).json()
    channel_id, widget_key = connect_body["id"], connect_body["widgetKey"]
    patched = client.patch(
        f"/omnichannel/channels/{channel_id}", headers=h, json={"isActive": False}
    )
    assert patched.status_code == 200
    assert patched.json()["isTrashed"] is False  # inactive, NOT trashed - a distinct path
    assert _js(client, widget_key).status_code == 404


def test_loader_route_module_inactive_tenant_is_404(client, session_factory):
    from app.services.app_store_service import AppStoreService

    h = _auth(client)
    connect_body = _connect(client, h).json()
    widget_key = connect_body["widgetKey"]

    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.commit()
    db.close()
    try:
        assert _js(client, widget_key).status_code == 404
    finally:
        db2 = session_factory()
        AppStoreService(db2).reactivate(DEFAULT_TENANT_ID, "omnichannel")
        db2.commit()
        db2.close()


def test_loader_route_tenant_cannot_sign_in_is_404(client, session_factory):
    from app.services.tenant_service import TenantService

    h = _auth(client)
    connect_body = _connect(client, h).json()
    widget_key = connect_body["widgetKey"]

    db = session_factory()
    TenantService(db).suspend(DEFAULT_TENANT_ID)
    db.close()
    try:
        assert _js(client, widget_key).status_code == 404
    finally:
        db2 = session_factory()
        TenantService(db2).reactivate(DEFAULT_TENANT_ID)
        db2.close()


def test_loader_route_all_five_failure_modes_are_byte_identical(client, session_factory):
    """AC-WEB-21 - no enumeration: every failure mode answers the SAME body
    (status + text), whatever the reason."""
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    h = _auth(client)

    unknown = _js(client, "wk_totally_unknown_0000000000000")

    trashed_body = _connect(client, h, name="Trashed One").json()
    client.post(
        "/omnichannel/channels/disconnect", headers=h, json={"ids": [trashed_body["id"]]}
    )
    trashed = _js(client, trashed_body["widgetKey"])

    inactive_body = _connect(client, h, name="Inactive One").json()
    client.patch(
        f"/omnichannel/channels/{inactive_body['id']}", headers=h, json={"isActive": False}
    )
    inactive = _js(client, inactive_body["widgetKey"])

    module_body = _connect(client, h, name="Module Off One").json()
    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.commit()
    db.close()
    module_off = _js(client, module_body["widgetKey"])
    db2 = session_factory()
    AppStoreService(db2).reactivate(DEFAULT_TENANT_ID, "omnichannel")
    db2.commit()
    db2.close()

    blocked_body = _connect(client, h, name="Blocked Tenant One").json()
    db3 = session_factory()
    TenantService(db3).suspend(DEFAULT_TENANT_ID)
    db3.close()
    blocked = _js(client, blocked_body["widgetKey"])
    db4 = session_factory()
    TenantService(db4).reactivate(DEFAULT_TENANT_ID)
    db4.close()

    responses = [unknown, trashed, inactive, module_off, blocked]
    for res in responses:
        assert res.status_code == 404
    bodies = {res.text for res in responses}
    assert len(bodies) == 1, f"404 bodies diverged: {bodies}"
