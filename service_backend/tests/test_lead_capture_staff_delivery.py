"""Lane L-D (AC-64-57): signed-in staff routes for a product's receivers,
"Send test push", and the grace-window revoke/remove actions. Reuses the
gateway's service functions; no Meta or consumer call is made."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.deferred_actions.registry import deferred_action_for
from app.deferred_actions.service import PendingActionService
from app.models import DEFAULT_TENANT_ID, User
from app.models.pending_action import PendingAction
from app.secrets import decrypt_secret
from modules.lead_capture.models import LcApiKey, LcDelivery, LcWebhookEndpoint
from modules.lead_capture.services import delivery_service
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.meetings_helpers import make_admin_user, make_tenant

TENANT_B = "tenant-lead-ld-b"
URL = "https://consumer.example/leads"


@pytest.fixture
def lc(session_factory, monkeypatch):
    import app.database as database
    from app.services.app_store_service import AppStoreService

    monkeypatch.setattr(database, "SessionLocal", session_factory)
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


def _login(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create(client, headers, url=URL, events=None):
    return client.post("/lead-capture/webhooks", json={"url": url, "events": events or ["lead.created"]}, headers=headers)


def test_staff_receiver_create_list_delete(client, lc):
    headers = _login(client)
    res = _create(client, headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["secret"].startswith("whsec_")
    assert body["url"] == URL and body["events"] == ["lead.created"]

    listed = client.get("/lead-capture/webhooks", headers=headers).json()["data"]
    assert [r["id"] for r in listed] == [body["id"]]
    assert "secret" not in listed[0]

    assert client.delete(f"/lead-capture/webhooks/{body['id']}", headers=headers).status_code == 204
    assert client.get("/lead-capture/webhooks", headers=headers).json()["data"] == []
    assert client.delete(f"/lead-capture/webhooks/{body['id']}", headers=headers).status_code == 404


def test_staff_receiver_refuses_bad_url_and_unknown_event(client, lc):
    headers = _login(client)
    res = _create(client, headers, url="http://10.0.0.1/hook")
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_url"
    res = _create(client, headers, events=["lead.deleted"])
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_events"


@pytest.mark.parametrize(
    "url,message",
    [
        ("http://hooks.example.com/lead", "The URL must use https://."),
        ("https://localhost/lead", "The URL cannot target localhost."),
        ("https://10.0.0.1/lead", "The URL cannot target a private or reserved IP."),
        ("https://[::1/lead", "Enter a valid URL."),
    ],
)
def test_refused_receiver_url_uses_the_screen_words(client, lc, url, message):
    # Crew pass 4575cc46: the Add receiver field is "URL"; never "Callback URL".
    res = _create(client, _login(client), url=url)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_url"
    assert res.json()["detail"]["message"] == message


def test_test_push_sends_one_signed_test_lead_to_that_receiver_only(client, lc, posts):
    headers = _login(client)
    a = _create(client, headers, url="https://a.example/leads").json()
    _create(client, headers, url="https://b.example/leads")
    client.put(
        "/lead-capture/fields",
        json=[{"key": "fullName", "label": "Full name", "type": "name"}, {"key": "mobile", "label": "Mobile", "type": "phone"}],
        headers=headers,
    )

    res = client.post(f"/lead-capture/webhooks/{a['id']}/test", headers=headers)
    assert res.status_code == 202, res.text
    assert res.json()["event"] == "lead.created"

    assert [p["url"] for p in posts] == ["https://a.example/leads"]
    sent = posts[0]
    assert delivery_service.verify(a["secret"], sent["headers"]["X-Lead-Capture-Signature"], sent["body"])
    payload = json.loads(sent["body"])
    assert payload["type"] == "lead.created"
    assert payload["data"]["isTest"] is True
    assert payload["data"]["fields"] == {"fullName": "Test Lead", "mobile": "+60000000000"}

    db = lc()
    try:
        row = db.query(LcDelivery).filter(LcDelivery.id == res.json()["id"]).first()
        assert row.status == "SUCCESS" and row.lead_id is None
    finally:
        db.close()


def test_test_push_uses_the_receivers_own_event_when_not_lead_created(client, lc, posts):
    headers = _login(client)
    rec = _create(client, headers, events=["source.updated"]).json()
    res = client.post(f"/lead-capture/webhooks/{rec['id']}/test", headers=headers)
    assert res.status_code == 202
    assert json.loads(posts[0]["body"])["type"] == "source.updated"


def test_test_push_unknown_receiver_is_404(client, lc, posts):
    headers = _login(client)
    res = client.post("/lead-capture/webhooks/nope/test", headers=headers)
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "endpoint_not_found"
    assert posts == []


def test_receivers_are_scoped_to_the_signed_in_company(client, lc, posts):
    from app.services.app_store_service import AppStoreService

    headers_a = _login(client)
    rec = _create(client, headers_a).json()

    db = lc()
    try:
        make_tenant(db, TENANT_B, "Lead D B")
        make_admin_user(db, TENANT_B, "admin@lead-ld-b.example")
        AppStoreService(db).install(TENANT_B, "lead_capture")
        db.commit()
    finally:
        db.close()
    res = client.post(
        "/auth/login", json={"email": "admin@lead-ld-b.example", "password": "demo1234", "tenantSlug": "lead-d-b"}
    )
    assert res.status_code == 200, res.text
    headers_b = {"Authorization": f"Bearer {res.json()['access_token']}"}
    assert client.get("/lead-capture/webhooks", headers=headers_b).json()["data"] == []
    assert client.post(f"/lead-capture/webhooks/{rec['id']}/test", headers=headers_b).status_code == 404
    assert client.delete(f"/lead-capture/webhooks/{rec['id']}", headers=headers_b).status_code == 404
    assert posts == []


def test_staff_receiver_routes_need_lead_capture_module(client, session_factory):
    headers = _login(client)
    assert client.get("/lead-capture/webhooks", headers=headers).status_code == 403


# ── grace-window actions ────────────────────────────────────────────────────


def _admin(db) -> User:
    return db.query(User).filter(User.email == ACTIVE_EMAIL).first()


def _park_and_lapse(db, action_key, entity_type, entity_id):
    admin = _admin(db)
    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key=action_key, entity_type=entity_type, entity_id=entity_id, payload=None,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    return svc.commit_one(row)


def test_deferred_keys_registered():
    assert deferred_action_for("lead_capture_keys.revoke").permission == "lead_capture.keys.manage"
    assert deferred_action_for("lead_capture_receivers.remove").permission == "lead_capture.manage"
    assert deferred_action_for("lead_capture_fields.reset").permission == "lead_capture.manage"


def test_deferred_fields_reset_commits_through_set_fields(client, lc):
    headers = _login(client)
    res = client.put("/lead-capture/fields", json=[{"key": "client", "label": "Client", "type": "name"}], headers=headers)
    assert res.status_code == 200
    db = lc()
    try:
        result = _park_and_lapse(db, "lead_capture_fields.reset", "lead_capture_fields", "fields")
        assert result.status == "committed"
    finally:
        db.close()
    body = client.get("/lead-capture/fields", headers=headers).json()
    assert body["isDefault"] is True
    assert [f["key"] for f in body["data"]] == ["name", "phone", "email", "notes"]


def test_deferred_key_revoke_commits(client, lc):
    headers = _login(client)
    kid = client.post("/lead-capture/keys", json={"name": "CRM"}, headers=headers).json()["id"]
    db = lc()
    try:
        result = _park_and_lapse(db, "lead_capture_keys.revoke", "lead_capture_key", kid)
        assert result.status == "committed"
        row = db.query(LcApiKey).filter(LcApiKey.id == kid).first()
        db.refresh(row)
        assert row.revoked_at is not None
    finally:
        db.close()


def test_deferred_receiver_remove_commits(client, lc):
    headers = _login(client)
    rid = _create(client, headers).json()["id"]
    db = lc()
    try:
        result = _park_and_lapse(db, "lead_capture_receivers.remove", "lead_capture_receiver", rid)
        assert result.status == "committed"
        row = db.query(LcWebhookEndpoint).filter(LcWebhookEndpoint.id == rid).first()
        db.refresh(row)
        assert row.active is False
        assert decrypt_secret(row.secret_encrypted)["secret"].startswith("whsec_")
    finally:
        db.close()
