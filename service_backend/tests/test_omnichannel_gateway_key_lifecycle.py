"""Plan 38 gap 1 (AC-38-27) - a gateway API key works only while its tenant may
sign in and its workspace is not trashed.

Every route behind `get_api_workspace` must answer the same
`403 service_not_enabled` as a disabled service, and restoring the tenant or
workspace restores the key. Real lifecycle paths, fake data.
"""
import pytest

from app.models import DEFAULT_TENANT_ID
from app.services.app_store_service import AppStoreService
from app.services.tenant_service import TenantService
from modules.omnichannel.services import idempotency
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
)
from tests.test_ideation_intake_products import _key_auth, _mint_key, ideation_client  # noqa: F401

ROUTES = [
    ("GET", "/api/v1/omnichannel/templates", None),
    ("GET", "/api/v1/omnichannel/channels", None),
    ("GET", "/api/v1/omnichannel/contacts", None),
    (
        "POST",
        "/api/v1/omnichannel/messages",
        {"to": "+6012345678", "type": "text", "text": {"body": "hi"}},
    ),
]


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


def _call(client, hdr, method, path, body):
    return client.request(method, path, headers=hdr, json=body) if body else client.request(method, path, headers=hdr)


def _rig(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-life")
    _seed_open_contact(session_factory, ws, phone="+6012345678", open_window=True)
    key = _mint(client, ws).json()["fullKey"]
    return ws, {"Authorization": f"Bearer {key}"}


def _disabled_module_reference(client, session_factory, hdr, method, path, body):
    """The response a disabled service gives, captured from the real path."""
    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.close()
    ref = _call(client, hdr, method, path, body)
    db = session_factory()
    AppStoreService(db).reactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.close()
    return ref


def _suspend(session_factory):
    db = session_factory()
    try:
        TenantService(db).suspend(DEFAULT_TENANT_ID)
    finally:
        db.close()


def _reactivate(session_factory):
    db = session_factory()
    try:
        TenantService(db).reactivate(DEFAULT_TENANT_ID)
    finally:
        db.close()


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_ac_38_27_suspended_tenant_key_is_refused_and_restored(client, session_factory, method, path, body):
    ws, hdr = _rig(client, session_factory)
    ref = _disabled_module_reference(client, session_factory, hdr, method, path, body)
    assert ref.status_code == 403 and ref.json()["error"]["code"] == "service_not_enabled"
    before = _call(client, hdr, method, path, body)
    assert before.status_code in (200, 202), before.text  # control: live tenant works

    _suspend(session_factory)
    refused = _call(client, hdr, method, path, body)
    assert refused.status_code == 403, refused.text
    assert refused.json() == ref.json()

    _reactivate(session_factory)
    after = _call(client, hdr, method, path, body)
    assert after.status_code in (200, 202), after.text


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_ac_38_27_archived_tenant_key_is_refused(client, session_factory, method, path, body):
    ws, hdr = _rig(client, session_factory)
    ref = _disabled_module_reference(client, session_factory, hdr, method, path, body)
    db = session_factory()
    try:
        svc = TenantService(db)
        svc.suspend(DEFAULT_TENANT_ID)
        svc.archive(DEFAULT_TENANT_ID)
    finally:
        db.close()
    refused = _call(client, hdr, method, path, body)
    assert refused.status_code == 403, refused.text
    assert refused.json() == ref.json()


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_ac_38_27_trashed_workspace_key_is_refused_and_restored(client, session_factory, method, path, body):
    from modules.omnichannel.models import Workspace

    # a second workspace so the default one is never trashed
    db = session_factory()
    ws2 = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Second", is_default=False)
    db.add(ws2)
    db.commit()
    ws2_id = ws2.id
    db.close()
    _seed_channel(session_factory, ws2_id, phone_number_id="pn-life-2")
    _seed_open_contact(session_factory, ws2_id, phone="+6012345678", open_window=True)
    hdr = {"Authorization": f"Bearer {_mint(client, ws2_id).json()['fullKey']}"}
    ref = _disabled_module_reference(client, session_factory, hdr, method, path, body)
    before = _call(client, hdr, method, path, body)
    assert before.status_code in (200, 202), before.text  # control

    from modules.omnichannel.services.workspace_service import WorkspaceService

    db = session_factory()
    WorkspaceService(db).trash([ws2_id], DEFAULT_TENANT_ID)
    db.close()
    refused = _call(client, hdr, method, path, body)
    assert refused.status_code == 403, refused.text
    assert refused.json() == ref.json()

    db = session_factory()
    WorkspaceService(db).restore([ws2_id], DEFAULT_TENANT_ID)
    db.close()
    after = _call(client, hdr, method, path, body)
    assert after.status_code in (200, 202), after.text


def test_ac_38_27_unknown_key_is_401_whatever_the_tenant_state(client, session_factory):
    _rig(client, session_factory)
    bad = {"Authorization": "Bearer fxw_live_deadbeef"}
    live = client.get("/api/v1/omnichannel/channels", headers=bad)
    _suspend(session_factory)
    suspended = client.get("/api/v1/omnichannel/channels", headers=bad)
    assert live.status_code == suspended.status_code == 401
    assert live.json() == suspended.json()


def test_ac_38_27_intake_route_refuses_a_suspended_tenant(ideation_client):
    factory = ideation_client._factory
    key = _mint_key(factory)
    ok = ideation_client.get("/ideation/intake/products", headers=_key_auth(key))
    assert ok.status_code == 200, ok.text  # control
    db = factory()
    try:
        TenantService(db).suspend(DEFAULT_TENANT_ID)
    finally:
        db.close()
    res = ideation_client.get("/ideation/intake/products", headers=_key_auth(key))
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "service_not_enabled"


# ── Media route, activity attribution, workspace lookup scope ────────────────
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128


@pytest.fixture(autouse=True)
def _tmp_media(tmp_path):
    from app.config import settings
    from app.services.storage import set_storage

    prev = settings.media_root
    settings.media_root = str(tmp_path)
    set_storage(None)
    yield
    settings.media_root = prev
    set_storage(None)


def _session_headers(client):
    from tests.test_omnichannel_api_gateway import _auth

    return _auth(client)


def _media_message(client, session_factory, ws, phone):
    """A real outbound media message in workspace `ws`; returns (contact, message id)."""
    cid = _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    res = client.post(
        f"/omnichannel/contacts/{cid}/media",
        files={"file": ("a.png", PNG, "image/png")},
        data={"kind": "image"},
        headers=_session_headers(client),
    )
    assert res.status_code == 201, res.text
    return cid, res.json()["id"]


def _media_rig(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-media")
    _cid, mid = _media_message(client, session_factory, ws, "+6012345670")
    key_resp = _mint(client, ws).json()
    return ws, mid, {"Authorization": f"Bearer {key_resp['fullKey']}"}, key_resp["key"]["id"]


def test_ac_38_27_media_route_with_a_key_follows_tenant_state(client, session_factory):
    ws, mid, hdr, _kid = _media_rig(client, session_factory)
    live = client.get(f"/omnichannel/media/{mid}", headers=hdr)
    assert live.status_code == 200, live.text  # control: a live key gets the media

    _suspend(session_factory)
    refused = client.get(f"/omnichannel/media/{mid}", headers=hdr)
    assert refused.status_code == 403, refused.status_code
    # the media route has its own 403 body, not the gateway envelope
    assert "error" not in refused.json()

    _reactivate(session_factory)
    assert client.get(f"/omnichannel/media/{mid}", headers=hdr).status_code == 200


def test_ac_38_27_media_route_with_a_key_follows_workspace_state(client, session_factory):
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services.workspace_service import WorkspaceService

    db = session_factory()
    ws2 = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Second", is_default=False)
    db.add(ws2)
    db.commit()
    ws2_id = ws2.id
    db.close()
    _seed_channel(session_factory, ws2_id, phone_number_id="pn-media-2")
    _cid, mid = _media_message(client, session_factory, ws2_id, "+6012345671")
    hdr = {"Authorization": f"Bearer {_mint(client, ws2_id).json()['fullKey']}"}
    assert client.get(f"/omnichannel/media/{mid}", headers=hdr).status_code == 200  # control

    db = session_factory()
    WorkspaceService(db).trash([ws2_id], DEFAULT_TENANT_ID)
    db.close()
    assert client.get(f"/omnichannel/media/{mid}", headers=hdr).status_code == 403

    db = session_factory()
    WorkspaceService(db).restore([ws2_id], DEFAULT_TENANT_ID)
    db.close()
    assert client.get(f"/omnichannel/media/{mid}", headers=hdr).status_code == 200


def test_ac_38_27_media_route_with_a_session_user_on_a_suspended_tenant_is_refused(client, session_factory):
    ws, mid, _hdr, _kid = _media_rig(client, session_factory)
    session = _session_headers(client)
    assert client.get(f"/omnichannel/media/{mid}", headers=session).status_code == 200  # control
    other_route = client.get("/omnichannel/contacts", headers=session)
    assert other_route.status_code == 200  # control: the token works elsewhere while live

    _suspend(session_factory)
    other_refused = client.get("/omnichannel/contacts", headers=session)
    media_refused = client.get(f"/omnichannel/media/{mid}", headers=session)
    assert other_refused.status_code in (401, 403)
    assert media_refused.status_code == 403
    assert media_refused.status_code == other_refused.status_code or other_refused.status_code == 401


def test_signed_media_link_is_still_served_for_a_suspended_tenant(client, session_factory):
    from modules.omnichannel.security import signed_media_url

    ws, mid, _hdr, _kid = _media_rig(client, session_factory)
    url = signed_media_url(mid)
    path = url[url.index("/omnichannel/media/") :]
    assert client.get(path).status_code == 200  # control: live
    _suspend(session_factory)
    assert client.get(path).status_code == 200


def test_key_workspace_lookup_is_scoped_to_the_key_tenant(client, session_factory):
    """A key row whose workspace id belongs to another tenant (and is not
    trashed there) must not pass the gateway check."""
    from modules.omnichannel.models import Workspace, WorkspaceApiKey

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-scope")
    mint = _mint(client, ws).json()
    hdr = {"Authorization": f"Bearer {mint['fullKey']}"}
    assert client.get("/api/v1/omnichannel/channels", headers=hdr).status_code == 200  # control

    db = session_factory()
    foreign = Workspace(tenant_id="other-tenant-id", name="Elsewhere", is_default=False)
    db.add(foreign)
    db.flush()
    row = db.query(WorkspaceApiKey).filter(WorkspaceApiKey.id == mint["key"]["id"]).first()
    row.workspace_id = foreign.id
    db.commit()
    db.close()
    refused = client.get("/api/v1/omnichannel/channels", headers=hdr)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "service_not_enabled"


def test_refused_gateway_call_still_writes_an_attributed_activity_row(client, session_factory):
    from app.models.integration_activity import IntegrationActivity

    ws, _mid, hdr, key_id = _media_rig(client, session_factory)
    _suspend(session_factory)
    res = client.get("/api/v1/omnichannel/channels", headers=hdr)
    assert res.status_code == 403
    db = session_factory()
    try:
        rows = (
            db.query(IntegrationActivity)
            .filter(
                IntegrationActivity.tenant_id == DEFAULT_TENANT_ID,
                IntegrationActivity.operation.like("%/channels"),
            )
            .all()
        )
    finally:
        db.close()
    assert rows, "the refused call must be recorded"
    assert any(r.api_key_id == key_id and r.status_code == 403 for r in rows), [
        (r.api_key_id, r.status_code) for r in rows
    ]


# ── Token types and embed sessions ───────────────────────────────────────────
def test_ac_38_28_media_route_refuses_embed_token_type(client, session_factory):
    from app.security import create_access_token, decode_access_token

    ws, mid, _hdr, _kid = _media_rig(client, session_factory)
    session = _session_headers(client)
    user_id = decode_access_token(session["Authorization"].split(" ", 1)[1])["sub"]
    assert client.get(f"/omnichannel/media/{mid}", headers=session).status_code == 200  # control

    embed_typed = create_access_token({"sub": user_id, "tenant_id": DEFAULT_TENANT_ID, "typ": "embed"})
    bad = {"Authorization": f"Bearer {embed_typed}"}
    reference = client.get("/auth/me", headers=bad)  # a session route behind get_current_user
    assert reference.status_code in (401, 403), reference.status_code
    media = client.get(f"/omnichannel/media/{mid}", headers=bad)
    assert media.status_code == reference.status_code, media.status_code


def _embed_session(client, session_factory):
    from tests.test_omnichannel_embed import _assertion, _exchange, _make_connection, _workspace_id

    conn = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    _seed_channel(session_factory, wid, phone_number_id="pn-embed-life")
    _seed_open_contact(session_factory, wid, phone="+6012345672", open_window=True)
    token = _exchange(client, _assertion(iss=conn, workspace_id=wid)).json()["accessToken"]
    return wid, token, {"Authorization": f"Bearer {token}"}


def test_ac_38_29_embed_session_follows_the_tenant_lifecycle(client, session_factory):
    wid, _token, hdr = _embed_session(client, session_factory)
    assert client.get("/omnichannel/contacts", headers=hdr).status_code == 200  # control

    _suspend(session_factory)
    assert client.get("/omnichannel/contacts", headers=hdr).status_code in (401, 403)

    _reactivate(session_factory)
    assert client.get("/omnichannel/contacts", headers=hdr).status_code == 200


def test_ac_38_29_embed_session_is_refused_for_an_archived_tenant(client, session_factory):
    wid, _token, hdr = _embed_session(client, session_factory)
    assert client.get("/omnichannel/contacts", headers=hdr).status_code == 200  # control
    db = session_factory()
    try:
        svc = TenantService(db)
        svc.suspend(DEFAULT_TENANT_ID)
        svc.archive(DEFAULT_TENANT_ID)
    finally:
        db.close()
    assert client.get("/omnichannel/contacts", headers=hdr).status_code in (401, 403)


def test_ac_38_29_embed_websocket_is_refused_while_the_tenant_is_suspended(client, session_factory):
    import fakeredis
    import fakeredis.aioredis
    from starlette.websockets import WebSocketDisconnect

    from modules.omnichannel.routers import ws as ws_module
    from modules.omnichannel.services import realtime

    server = fakeredis.FakeServer()
    realtime.set_client(fakeredis.FakeRedis(server=server, decode_responses=True))
    ws_module.set_async_redis(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))
    ws_module.set_session_factory(session_factory)
    try:
        wid, token, _hdr = _embed_session(client, session_factory)
        url = f"/omnichannel/ws?workspaceId={wid}&token={token}"
        with client.websocket_connect(url):
            pass  # control: connects while the tenant is live

        _suspend(session_factory)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url):
                pass
    finally:
        realtime.set_client(None)
        ws_module.set_async_redis(None)
        ws_module.set_session_factory(ws_module.SessionLocal)


# ── Embed exchange and native websocket follow the tenant lifecycle ─────────
def _embed_exchange_rig(session_factory):
    from tests.test_omnichannel_embed import _make_connection, _workspace_id

    return _make_connection(session_factory), _workspace_id(session_factory)


def test_embed_exchange_follows_the_tenant_lifecycle_and_keeps_the_assertion_unconsumed(client, session_factory):
    from tests.test_omnichannel_embed import _assertion, _exchange

    conn, wid = _embed_exchange_rig(session_factory)
    live = _exchange(client, _assertion(iss=conn, workspace_id=wid))
    assert live.status_code == 200 and live.json()["accessToken"]  # control: a live tenant gets a session

    held_back = _assertion(iss=conn, workspace_id=wid)
    _suspend(session_factory)
    refused = _exchange(client, held_back)
    assert refused.status_code == 403, refused.text
    assert "tenant_suspended" in refused.text
    assert "accessToken" not in refused.text  # no session issued

    _reactivate(session_factory)
    # the refused assertion was not consumed: it still exchanges once the tenant is back
    again = _exchange(client, held_back)
    assert again.status_code == 200, again.text
    fresh = _exchange(client, _assertion(iss=conn, workspace_id=wid))
    assert fresh.status_code == 200, fresh.text


def test_embed_exchange_is_refused_for_an_archived_tenant(client, session_factory):
    from tests.test_omnichannel_embed import _assertion, _exchange

    conn, wid = _embed_exchange_rig(session_factory)
    assert _exchange(client, _assertion(iss=conn, workspace_id=wid)).status_code == 200  # control
    db = session_factory()
    try:
        svc = TenantService(db)
        svc.suspend(DEFAULT_TENANT_ID)
        svc.archive(DEFAULT_TENANT_ID)
    finally:
        db.close()
    refused = _exchange(client, _assertion(iss=conn, workspace_id=wid))
    assert refused.status_code == 403, refused.text
    assert "accessToken" not in refused.text


def test_ac_38_29_invalid_assertion_gets_the_same_answer_whatever_the_tenant_state(client, session_factory):
    from tests.test_omnichannel_embed import SECRET_B, _assertion, _exchange

    conn, wid = _embed_exchange_rig(session_factory)
    wrong_key = _assertion(iss=conn, workspace_id=wid, secret=SECRET_B)
    live = _exchange(client, wrong_key)
    live_body = live.json()
    assert live.status_code in (400, 401, 403), live.text

    _suspend(session_factory)
    try:
        suspended = _exchange(client, _assertion(iss=conn, workspace_id=wid, secret=SECRET_B))
        # control: a validly signed assertion is refused while suspended
        control = _exchange(client, _assertion(iss=conn, workspace_id=wid))
        assert control.status_code == 403 and "tenant_suspended" in control.text
        assert (suspended.status_code, suspended.json()) == (live.status_code, live_body)
    finally:
        _reactivate(session_factory)
    # control: the same valid assertion succeeds while live
    ok = _exchange(client, _assertion(iss=conn, workspace_id=wid))
    assert ok.status_code == 200, ok.text


def test_ac_38_29_guide_lists_tenant_suspended_and_the_reconnect_note():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "documentation/omnichannel/consumer-integration-guide.md").read_text()
    start = text.index("## 12. Embedding the conversation UI")
    nxt = text.find("\n## ", start + 5)
    section = text[start : nxt if nxt != -1 else len(text)]
    assert "tenant_suspended" in section
    assert "reconnect" in section.lower()


def test_native_staff_websocket_is_refused_while_the_tenant_is_suspended(client, session_factory):
    import fakeredis
    import fakeredis.aioredis
    from starlette.websockets import WebSocketDisconnect

    from modules.omnichannel.routers import ws as ws_module
    from modules.omnichannel.services import realtime

    server = fakeredis.FakeServer()
    realtime.set_client(fakeredis.FakeRedis(server=server, decode_responses=True))
    ws_module.set_async_redis(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))
    ws_module.set_session_factory(session_factory)
    try:
        wid = _default_workspace_id(session_factory)
        staff_token = _session_headers(client)["Authorization"].split(" ", 1)[1]
        url = f"/omnichannel/ws?workspaceId={wid}&token={staff_token}"
        with client.websocket_connect(url):
            pass  # control: connects while the tenant is live

        _suspend(session_factory)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url):
                pass
    finally:
        realtime.set_client(None)
        ws_module.set_async_redis(None)
        ws_module.set_session_factory(ws_module.SessionLocal)
