"""Lane L-D round 2 (owner 17 Nov 19:32, AC-64-57): every action on the Lead
Capture screens is ALSO available to the consuming product through the
key-holder gateway, so it can build the same screens in its own app. One
service function, two doors (staff session + gateway key)."""
from __future__ import annotations

import json

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.lead_capture.routers import gateway as gateway_router
from modules.lead_capture.routers import staff as staff_router
from modules.lead_capture.services import delivery_service, key_service
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.meetings_helpers import make_admin_user, make_tenant

TENANT_B = "tenant-lead-ld2-b"
GW = "/api/v1/lead-capture"


@pytest.fixture
def lc(session_factory, monkeypatch):
    import app.database as database
    from app.services.app_store_service import AppStoreService
    from modules.lead_capture import gateway_auth

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(gateway_auth, "_audit_session", session_factory)
    db = session_factory()
    try:
        AppStoreService(db).install(DEFAULT_TENANT_ID, "lead_capture")
        db.commit()
    finally:
        db.close()
    return session_factory


@pytest.fixture
def posts(monkeypatch):
    sent = []

    def fake_post(url, *, content, headers, timeout):
        sent.append({"url": url, "body": content, "headers": dict(headers)})
        return delivery_service.webhook_post.PostReply(200)

    monkeypatch.setattr(delivery_service, "_post", fake_post)
    monkeypatch.setattr(delivery_service, "_assert_deliverable", lambda url: None)
    return sent


def _staff(client) -> dict:
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _key(client, name="EcoHub") -> dict:
    res = client.post("/lead-capture/keys", json={"name": name}, headers=_staff(client))
    assert res.status_code == 201, res.text
    return res.json()


def _bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


# ── route parity: every staff screen action has a gateway door ─────────────

# Staff-only on purpose: connecting a Page needs Foundryx's system-user token
# (product-side connect = lane L-C).
STAFF_ONLY = {("POST", "/sources/facebook")}


def _routes(router) -> set:
    out = set()
    for route in router.routes:
        for method in getattr(route, "methods", set()) or set():
            if method in ("HEAD", "OPTIONS"):
                continue
            out.add((method, route.path))
    return out


def test_every_staff_route_has_a_gateway_counterpart():
    missing = _routes(staff_router.router) - _routes(gateway_router.router) - STAFF_ONLY
    assert missing == set()


# ── keys through the gateway ───────────────────────────────────────────────


def test_gateway_lists_and_creates_keys_shown_once(client, lc):
    first = _key(client)
    headers = _bearer(first["key"])

    res = client.post(f"{GW}/keys", json={"name": "Rotation"}, headers=headers)
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["key"].startswith("fxl_live_")
    assert created["keyMasked"].endswith(created["key"][-4:])

    listed = client.get(f"{GW}/keys", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()["data"]
    assert {r["name"] for r in rows} == {"EcoHub", "Rotation"}
    assert all("key" not in r for r in rows)
    # The new key works on the gateway.
    assert client.get(f"{GW}/keys", headers=_bearer(created["key"])).status_code == 200


def test_gateway_revokes_another_key_but_not_the_calling_one(client, lc):
    first = _key(client)
    second = _key(client, "Old server")
    headers = _bearer(first["key"])

    res = client.delete(f"{GW}/keys/{second['id']}", headers=headers)
    assert res.status_code == 204
    assert client.get(f"{GW}/keys", headers=_bearer(second["key"])).status_code == 401
    row = next(r for r in client.get(f"{GW}/keys", headers=headers).json()["data"] if r["id"] == second["id"])
    assert row["revokedAt"] is not None

    self_res = client.delete(f"{GW}/keys/{first['id']}", headers=headers)
    assert self_res.status_code == 409
    assert self_res.json()["error"]["code"] == "key_in_use"
    assert client.get(f"{GW}/keys", headers=headers).status_code == 200

    missing = client.delete(f"{GW}/keys/nope", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "key_not_found"


def test_gateway_keys_are_scoped_to_the_key_company(client, lc):
    from app.services.app_store_service import AppStoreService

    a = _key(client)
    db = lc()
    try:
        make_tenant(db, TENANT_B, "Lead LD2 B")
        make_admin_user(db, TENANT_B, "admin@lead-ld2-b.example")
        AppStoreService(db).install(TENANT_B, "lead_capture")
        row, b_key = key_service.issue(db, TENANT_B, name="B", created_by=None)
        db.commit()
    finally:
        db.close()

    b_rows = client.get(f"{GW}/keys", headers=_bearer(b_key)).json()["data"]
    assert [r["name"] for r in b_rows] == ["B"]
    res = client.delete(f"{GW}/keys/{a['id']}", headers=_bearer(b_key))
    assert res.status_code == 404
    assert client.get(f"{GW}/keys", headers=_bearer(a["key"])).status_code == 200


# ── test push through the gateway ──────────────────────────────────────────


def test_gateway_test_push_sends_one_signed_test_lead(client, lc, posts):
    headers = _bearer(_key(client)["key"])
    rec = client.post(f"{GW}/webhooks", json={"url": "https://a.example/leads", "events": ["lead.created"]}, headers=headers)
    assert rec.status_code == 201, rec.text
    rec = rec.json()

    res = client.post(f"{GW}/webhooks/{rec['id']}/test", headers=headers)
    assert res.status_code == 202, res.text
    assert res.json()["event"] == "lead.created"
    assert len(posts) == 1
    assert delivery_service.verify(rec["secret"], posts[0]["headers"]["X-Lead-Capture-Signature"], posts[0]["body"])
    assert json.loads(posts[0]["body"])["data"]["isTest"] is True

    missing = client.post(f"{GW}/webhooks/nope/test", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "endpoint_not_found"


# ── one function, two doors ────────────────────────────────────────────────


def test_staff_and_gateway_call_the_same_service_functions(client, lc, posts, monkeypatch):
    calls = []

    def spy(module, name):
        real = getattr(module, name)

        def wrapper(*a, **k):
            calls.append(name)
            return real(*a, **k)

        monkeypatch.setattr(module, name, wrapper)

    for name in ("issue", "list_keys", "revoke"):
        spy(key_service, name)
    spy(delivery_service, "send_test_push")

    staff = _staff(client)
    gw_key = client.post("/lead-capture/keys", json={"name": "A"}, headers=staff).json()
    gw = _bearer(gw_key["key"])
    rec = client.post(f"{GW}/webhooks", json={"url": "https://a.example/leads", "events": ["lead.created"]}, headers=gw).json()
    other = client.post(f"{GW}/keys", json={"name": "B"}, headers=gw).json()
    client.get("/lead-capture/keys", headers=staff)
    client.get(f"{GW}/keys", headers=gw)
    client.delete(f"/lead-capture/keys/{other['id']}", headers=staff)
    client.post(f"/lead-capture/webhooks/{rec['id']}/test", headers=staff)
    client.post(f"{GW}/webhooks/{rec['id']}/test", headers=gw)

    assert calls.count("issue") == 2
    assert calls.count("list_keys") == 2
    assert calls.count("revoke") == 1
    assert calls.count("send_test_push") == 2
