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
