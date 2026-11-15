"""Plan 64 lane P - Lead Capture backend spine (AC-64-01..03, 24..27, 35..37,
55, 60, 62..65, 70..72).

Real payload shapes from S-META (fake ids and values) drive the ingest. No real
Meta call and no real consumer: httpx MockTransport for Graph, a stubbed POST
for delivery.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import socket
from pathlib import Path

import fakeredis
import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.secrets import decrypt_secret
from modules.lead_capture import gateway_auth, meta_leads
from modules.lead_capture.models import LcApiAudit, LcDelivery, LcLead, LcSource
from modules.lead_capture.services import connect_service, delivery_service, leadgen_service
from modules.omnichannel.services import realtime
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.meetings_helpers import make_admin_user, make_tenant

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "documentation" / "plans" / "meta-leads" / "fixtures"
PAGE_ID = "300000000000001"
LEAD_ID = "100000000000001"
FORM_ID = "400000000000001"
FORM_NAME = "S-META test 1"
SYSTEM_TOKEN = "SYSUSERtok3n0123456789abcdefSECRET"
PAGE_TOKEN = "PAGEtok3n0123456789abcdefSECRETvalue"
APP_SECRET = "app-s3cret"
TENANT_B = "tenant-lead-b"


def _fixture(name: str) -> dict:
    path = FIXTURES / name
    if not path.exists():  # fixtures live on the META-LEADS docs branch until it merges
        path = Path(__file__).parent / "fixtures" / "lead_capture" / name
    return json.loads(path.read_text())


# ── harness ─────────────────────────────────────────────────────────────────

class FakeGraph:
    """Meta Graph stand-in: Page token, subscribed_apps, lead read, test_leads."""

    def __init__(self, *, lead=None, test_ids=(LEAD_ID,), lead_status=200, page_status=200):
        self.lead = lead if lead is not None else {**_fixture("lead-get-default-fields.json"), **_fixture("lead-get-extra-fields.json")}
        self.test_ids = list(test_ids)
        self.lead_status = lead_status
        self.page_status = page_status
        self.calls: list[httpx.Request] = []
        self.subscribed: list[str] = []
        self.form_status = 200
        self.form_name = FORM_NAME
        self.extra_leads: dict = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/subscribed_apps"):
            if request.method == "GET":
                return httpx.Response(200, json={"data": [{"id": settings.meta_app_id, "subscribed_fields": ["messages"]}]})
            self.subscribed = request.url.params.get("subscribed_fields", "").split(",")
            return httpx.Response(200, json={"success": True})
        if path.endswith(f"/{PAGE_ID}"):
            if self.page_status != 200:
                return httpx.Response(self.page_status, json={"error": {"message": f"(#10) bad {SYSTEM_TOKEN}", "code": 10}})
            return httpx.Response(200, json={"access_token": PAGE_TOKEN, "name": "Foundryx Test Page", "id": PAGE_ID})
        if path.endswith(f"/{FORM_ID}") and request.method == "GET":
            if self.form_status != 200:
                return httpx.Response(self.form_status, json={"error": {"message": "nope", "code": 2}})
            return httpx.Response(200, json={"id": FORM_ID, "name": self.form_name})
        for lead_id, body in self.extra_leads.items():
            if path.endswith(f"/{lead_id}"):
                return httpx.Response(200, json=body)
        if path.endswith(f"/{FORM_ID}/test_leads"):
            return httpx.Response(200, json={"data": [{"id": i} for i in self.test_ids]})
        if path.endswith(f"/{LEAD_ID}"):
            if self.lead_status != 200:
                return httpx.Response(self.lead_status, json={"error": {"message": "nope", "code": 190}})
            return httpx.Response(200, json=self.lead)
        return httpx.Response(404, json={"error": {"message": "unknown", "code": 100}})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture(autouse=True)
def _fake_realtime():
    client = fakeredis.FakeRedis(decode_responses=True)
    realtime.set_client(client)
    yield client
    realtime.set_client(None)


@pytest.fixture
def graph(monkeypatch):
    g = FakeGraph()
    monkeypatch.setattr(settings, "meta_app_id", "app-123")
    monkeypatch.setattr(settings, "meta_app_secret", APP_SECRET)
    monkeypatch.setattr(meta_leads.MetaLeadClient, "_http", lambda self: g.client())
    from app.integrations.meta import pages as meta_pages

    monkeypatch.setattr(meta_pages.MetaPages, "_http", lambda self: g.client())
    return g


@pytest.fixture
def lc(session_factory, monkeypatch):
    """Lead Capture installed for the default tenant; workers use the test DB."""
    import app.database as database
    from app.services.app_store_service import AppStoreService

    from modules.lead_capture.services import read_service

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(gateway_auth, "_audit_session", session_factory)
    monkeypatch.setattr(read_service, "PULL_SETTLE_SECONDS", 0)
    db = session_factory()
    try:
        AppStoreService(db).install(DEFAULT_TENANT_ID, "lead_capture")
        db.commit()
    finally:
        db.close()
    return session_factory


@pytest.fixture
def posts(monkeypatch):
    """Capture every consumer POST; answer 200 unless told otherwise."""
    class Sent(list):
        state: dict

    sent = Sent()
    state = {"status": 200}

    def fake_post(url, *, content, headers, timeout):
        sent.append({"url": url, "body": content, "headers": dict(headers)})
        if isinstance(state["status"], Exception):
            raise state["status"]
        return delivery_service.webhook_post.PostReply(state["status"])

    monkeypatch.setattr(delivery_service, "_post", fake_post)
    monkeypatch.setattr(delivery_service, "_assert_deliverable", lambda url: None)
    sent.state = state
    return sent


def _login(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, slug=None) -> dict:
    body = {"email": email, "password": password}
    if slug:
        body["tenantSlug"] = slug
    res = client.post("/auth/login", json=body)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _connect(client, headers, page_id=PAGE_ID):
    return client.post(
        "/lead-capture/sources/facebook",
        json={"pageId": page_id, "systemUserToken": SYSTEM_TOKEN, "formsMode": "all"},
        headers=headers,
    )


def _key(client, headers) -> str:
    res = client.post("/lead-capture/keys", json={"name": "EcoHub"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["key"]


def _register(client, key, url="https://consumer.example/leads"):
    res = client.post(
        "/api/v1/lead-capture/webhooks",
        json={"url": url, "events": ["lead.created"]},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _signed_webhook(client, payload: dict, *, secret=APP_SECRET, tamper=False):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if tamper:
        body = body.replace(LEAD_ID.encode(), b"100000000000009")
    return client.post(
        "/omnichannel/webhooks/lead",
        content=body,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )


def _second_tenant(session_factory, allow_sharing: bool):
    from app.services.app_store_service import AppStoreService

    db = session_factory()
    try:
        make_tenant(db, TENANT_B, "Lead B")
        make_admin_user(db, TENANT_B, "admin@lead-b.example")
        AppStoreService(db).install(TENANT_B, "lead_capture")
        if allow_sharing:
            connect_service.set_allow_shared_pages(db, TENANT_B, True, None)
        db.commit()
    finally:
        db.close()


def _leads(session_factory, tenant_id=None):
    db = session_factory()
    try:
        q = db.query(LcLead)
        if tenant_id:
            q = q.filter(LcLead.tenant_id == tenant_id)
        return q.all()
    finally:
        db.close()


# ── A. module, install, permissions ─────────────────────────────────────────

def test_manifest_and_permissions_have_no_collision():
    """AC-64-01/02: own schema, optional omnichannel, gateway router public,
    three keys none of which any other permissions.csv declares."""
    import csv

    manifest = json.loads((ROOT / "service_backend/modules/lead_capture/manifest.json").read_text())
    assert manifest["schema"] == "app_lead_capture"
    assert manifest["optional"] == [{"name": "omnichannel"}]
    routers = {r["name"]: r for r in manifest["routers"]}
    assert routers["gateway"]["prefix"] == "/api/v1/lead-capture" and routers["gateway"]["public"] is True
    assert not routers["staff"].get("public")

    def keys(path):
        with open(path, newline="") as fh:
            return {f"{r['resource']}.{r['action']}" for r in csv.DictReader(fh)}

    ours = keys(ROOT / "service_backend/modules/lead_capture/permissions/permissions.csv")
    assert ours == {"lead_capture.view", "lead_capture.manage", "lead_capture.keys.manage"}
    others = set()
    for path in (ROOT / "service_backend").glob("**/permissions*.csv"):
        if "lead_capture" in str(path) or ".venv" in str(path):
            continue
        others |= keys(path)
    assert not ours & others


def test_alembic_revision_fits_version_column():
    """VARCHAR(32) alembic_version: a longer id breaks every real deploy."""
    from modules.lead_capture.alembic.versions import __path__ as _p  # noqa: F401

    text = (ROOT / "service_backend/modules/lead_capture/alembic/versions/0001_lead_capture_init.py").read_text()
    rev = text.split('revision = "', 1)[1].split('"', 1)[0]
    assert len(rev) <= 32


def test_install_grants_admin_and_module_gate(client, lc):
    """AC-64-03/04: Admin holds the three keys after install; the staff API
    answers; an uninstalled tenant gets 403 Module not installed."""
    headers = _login(client)
    me = client.get("/auth/me", headers=headers).json()
    assert {"lead_capture.view", "lead_capture.manage", "lead_capture.keys.manage"} <= set(me["permissions"])
    assert client.get("/lead-capture/sources", headers=headers).status_code == 200

    from app.services.app_store_service import AppStoreService

    db = lc()
    try:
        AppStoreService(db).uninstall(DEFAULT_TENANT_ID, "lead_capture", confirm_name="lead_capture")
        db.commit()
    finally:
        db.close()
    res = client.get("/lead-capture/sources", headers=headers)
    assert res.status_code == 403


# ── connect (AC-64-25/36/71) ────────────────────────────────────────────────

def test_connect_stores_encrypted_page_token_and_subscribes_union(client, lc, graph):
    headers = _login(client)
    res = _connect(client, headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "LIVE" and body["pageId"] == PAGE_ID and body["pageName"] == "Foundryx Test Page"
    assert SYSTEM_TOKEN not in res.text and PAGE_TOKEN not in res.text
    # union: omnichannel's `messages` kept, `leadgen` added
    assert graph.subscribed == ["messages", "leadgen"]
    # the Page token was read with the system-user token in the header, never the URL
    page_call = next(c for c in graph.calls if c.url.path.endswith(f"/{PAGE_ID}"))
    assert page_call.headers["Authorization"] == f"Bearer {SYSTEM_TOKEN}"
    assert SYSTEM_TOKEN not in str(page_call.url)
    db = lc()
    try:
        row = db.query(LcSource).one()
        assert PAGE_TOKEN not in row.credentials_encrypted
        assert decrypt_secret(row.credentials_encrypted)["pageToken"] == PAGE_TOKEN
        assert SYSTEM_TOKEN not in json.dumps(decrypt_secret(row.credentials_encrypted))
    finally:
        db.close()


def test_reconnect_same_tenant_replaces_token_in_place(client, lc, graph):
    headers = _login(client)
    first = _connect(client, headers).json()
    second = _connect(client, headers)
    assert second.status_code == 201 and second.json()["id"] == first["id"]
    db = lc()
    try:
        assert db.query(LcSource).count() == 1
    finally:
        db.close()


def test_connect_refusal_never_echoes_or_logs_a_token(client, lc, graph, caplog):
    graph.page_status = 400
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    res = _connect(client, headers)
    assert res.status_code == 400
    assert SYSTEM_TOKEN not in res.text
    assert SYSTEM_TOKEN not in caplog.text and PAGE_TOKEN not in caplog.text


@pytest.mark.parametrize("allow_a,allow_b,ok", [(False, False, False), (True, False, False), (False, True, False), (True, True, True)])
def test_shared_page_rule(client, lc, graph, allow_a, allow_b, ok):
    """AC-64-36: another tenant joins a live Page only when BOTH allow sharing;
    otherwise PAGE_IN_USE, same wording whichever side said no."""
    _second_tenant(lc, allow_b)
    db = lc()
    try:
        connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
    finally:
        db.close()
    headers = _login(client)
    if allow_a:
        client.put("/lead-capture/settings", json={"allowSharedPages": True}, headers=headers)
    res = _connect(client, headers)
    if ok:
        assert res.status_code == 201
    else:
        assert res.status_code == 409
        assert res.json()["detail"] == {"code": "PAGE_IN_USE", "message": connect_service.PAGE_IN_USE_MESSAGE}
        assert TENANT_B not in res.text


# ── ingest (AC-64-26/27/35/37) ──────────────────────────────────────────────

def test_signed_fixture_webhook_creates_one_test_lead_and_replay_creates_none(client, lc, graph, posts, caplog):
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    assert _connect(client, headers).status_code == 201
    key = _key(client, headers)
    _register(client, key)
    payload = _fixture("leadgen-webhook-test-lead.json")

    res = _signed_webhook(client, payload)
    assert res.status_code == 200 and res.json() == {"status": "queued"}
    leads = _leads(lc)
    assert len(leads) == 1
    lead = leads[0]
    assert lead.platform_lead_id == LEAD_ID and lead.form_id == FORM_ID and lead.is_test is True
    assert lead.email == "lead.test@example.com" and lead.phone_e164 == "+60120000000"
    # personal data encrypted at rest (AC-64-55)
    assert "Test Lead" not in (lead.fields_encrypted or "") and "Test Lead" not in (lead.raw_encrypted or "")
    stored = decrypt_secret(lead.fields_encrypted)
    assert stored["fields"] == {
        "name": "Test Lead",
        "phone": "+60120000000",
        "email": "lead.test@example.com",
        "notes": "interest: test answer",
    }
    # lead read with the Page token, in the header
    lead_call = next(c for c in graph.calls if c.url.path.endswith(f"/{LEAD_ID}"))
    assert lead_call.headers["Authorization"] == f"Bearer {PAGE_TOKEN}"
    # one signed delivery
    assert len(posts) == 1
    sent = json.loads(posts[0]["body"])
    assert sent["type"] == "lead.created" and sent["data"]["id"] == lead.id and sent["data"]["isTest"] is True

    # replay: no second lead, no second delivery (AC-64-27)
    assert _signed_webhook(client, payload).status_code == 200
    assert len(_leads(lc)) == 1 and len(posts) == 1
    # map-fields notice data (AC-64-35)
    src = client.get("/lead-capture/sources", headers=headers).json()["data"][0]
    assert src["needsMapping"] == [{"formId": FORM_ID, "formName": FORM_NAME, "unmappedCount": 1}]
    # no token, no personal value in any log line (AC-64-71)
    for secret in (SYSTEM_TOKEN, PAGE_TOKEN, "lead.test@example.com", "+60120000000", key):
        assert secret not in caplog.text


def test_tampered_signature_is_403_and_stores_nothing(client, lc, graph):
    headers = _login(client)
    _connect(client, headers)
    res = _signed_webhook(client, _fixture("leadgen-webhook-test-lead.json"), tamper=True)
    assert res.status_code == 403
    assert _leads(lc) == []


def test_lead_with_ad_is_not_test(lc, graph):
    graph.lead = {**graph.lead, "ad_id": "500000000000001"}
    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    (lead,) = _leads(lc)
    assert lead.is_test is False and lead.attribution_json["adId"] == "500000000000001"
    assert not any(c.url.path.endswith("/test_leads") for c in graph.calls)


def test_page_with_no_live_source_enqueues_nothing(lc, graph, monkeypatch):
    called = []
    import app.workflow_engine.worker as w

    monkeypatch.setattr(w.lead_capture_process_leadgen, "delay", lambda *a, **k: called.append(a))
    db = lc()
    try:
        leadgen_service.handle_leadgen_change(db, "page", PAGE_ID, {"leadgen_id": LEAD_ID})
        db.commit()
    finally:
        db.close()
    assert called == []


def test_handler_takes_page_from_entry_and_passes_ids_only(lc, graph, monkeypatch):
    called = []
    import app.workflow_engine.worker as w

    monkeypatch.setattr(w.lead_capture_process_leadgen, "delay", lambda *a, **k: called.append(a))
    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        value = {"leadgen_id": LEAD_ID, "page_id": "999", "form_id": FORM_ID, "created_time": 1794719951}
        leadgen_service.handle_leadgen_change(db, "page", PAGE_ID, value)
        leadgen_service.handle_leadgen_change(db, "page", PAGE_ID, {"leadgen_id": "bad id!"})
        assert called == []  # nothing leaves before the ingress commits
        db.commit()
    finally:
        db.close()
    assert called == [(PAGE_ID, LEAD_ID, FORM_ID, 1794719951)]


def test_shared_page_one_fetch_one_lead_per_tenant(client, lc, graph, posts):
    """AC-64-37: both tenants allow sharing; one webhook = one Graph read, one
    lead per tenant, each delivered only to that tenant's endpoint."""
    _second_tenant(lc, True)
    db = lc()
    try:
        connect_service.set_allow_shared_pages(db, DEFAULT_TENANT_ID, True, None)
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        ep_a, _ = delivery_service.create_endpoint(db, DEFAULT_TENANT_ID, "https://a.example/hook", ["lead.created"])
        ep_b, _ = delivery_service.create_endpoint(db, TENANT_B, "https://b.example/hook", ["lead.created"])
        graph.calls.clear()
        created = leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert len(created) == 2
    assert sum(1 for c in graph.calls if c.url.path.endswith(f"/{LEAD_ID}")) == 1
    assert {lead.tenant_id for lead in _leads(lc)} == {DEFAULT_TENANT_ID, TENANT_B}
    by_url = {p["url"]: json.loads(p["body"])["data"] for p in posts}
    assert set(by_url) == {"https://a.example/hook", "https://b.example/hook"}
    a_lead = [lead for lead in _leads(lc, DEFAULT_TENANT_ID)][0]
    assert by_url["https://a.example/hook"]["id"] == a_lead.id


def test_inactive_tenant_gets_no_lead(lc, graph):
    from app.services.app_store_service import AppStoreService

    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "lead_capture")
        db.commit()
        assert leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID) == []
    finally:
        db.close()


# ── delivery (AC-64-60/62/63/64) ────────────────────────────────────────────

def _lead_and_delivery(lc, posts_state_status=200):
    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        _row, secret = delivery_service.create_endpoint(db, DEFAULT_TENANT_ID, "https://consumer.example/leads", ["lead.created"])
        leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
        delivery = db.query(LcDelivery).one()
        return delivery.id, secret
    finally:
        db.close()


def test_delivery_signature_verifies_and_headers_match(lc, graph, posts):
    delivery_id, secret = _lead_and_delivery(lc)
    sent = posts[0]
    h = sent["headers"]
    assert h["X-Lead-Capture-Event"] == "lead.created"
    assert h["X-Lead-Capture-Delivery"] == delivery_id
    assert delivery_service.verify(secret, h["X-Lead-Capture-Signature"], sent["body"])
    assert not delivery_service.verify("whsec_wrong", h["X-Lead-Capture-Signature"], sent["body"])
    assert not delivery_service.verify(secret, h["X-Lead-Capture-Signature"], sent["body"] + b" ")
    t, v1 = (p.split("=", 1)[1] for p in h["X-Lead-Capture-Signature"].split(","))
    expected = hmac.new(secret.encode(), f"{t}.".encode() + sent["body"], hashlib.sha256).hexdigest()
    assert v1 == expected
    db = lc()
    try:
        row = db.get(LcDelivery, delivery_id)
        assert row.status == "SUCCESS" and row.attempt == 1
        assert "Test Lead" not in row.body_encrypted  # personal data encrypted at rest
    finally:
        db.close()


def test_500_retries_on_the_ladder_then_fails(lc, graph, posts):
    """AC-64-63: 1 min, 5 min, 30 min, 2 h, 6 h, 24 h, then FAILED."""
    posts.state["status"] = 500
    delivery_id, _ = _lead_and_delivery(lc)
    expected_gaps = [60, 300, 1800, 7200, 21600, 86400]
    db = lc()
    try:
        for n, gap in enumerate(expected_gaps, start=1):
            db.expire_all()
            row = db.get(LcDelivery, delivery_id)
            assert row.status == "PENDING" and row.attempt == n and row.last_code == 500
            actual = (row.next_at - row.last_attempt_at).total_seconds()
            assert gap - 5 <= actual <= gap + 5, (n, actual)
            row.next_at = row.last_attempt_at  # time travel to the next rung
            db.commit()
            assert delivery_service.dispatch(db, delivery_id) == ("dead" if n == len(expected_gaps) else "retry")
        db.expire_all()
        row = db.get(LcDelivery, delivery_id)
        assert row.attempt == 7 and row.status == "FAILED" and row.next_at is None
        assert len(posts) == 7
    finally:
        db.close()


def test_timeout_is_a_failed_attempt(lc, graph, posts):
    posts.state["status"] = httpx.ReadTimeout("slow")
    delivery_id, _ = _lead_and_delivery(lc)
    db = lc()
    try:
        row = db.get(LcDelivery, delivery_id)
        assert row.status == "PENDING" and row.last_error == "Consumer did not answer within 10 seconds."
    finally:
        db.close()


def test_internal_callback_is_refused_per_attempt(lc, graph, monkeypatch):
    """AC-64-64: registered while public, re-pointed to an internal address:
    the attempt is refused by the REAL guard and nothing is sent."""
    sent = []
    monkeypatch.setattr(delivery_service, "_post", lambda *a, **k: sent.append(a) or delivery_service.webhook_post.PostReply(200))
    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        delivery_service.create_endpoint(db, DEFAULT_TENANT_ID, "https://consumer.example/leads", ["lead.created"])
        monkeypatch.setattr(
            socket, "getaddrinfo", lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]
        )
        leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
        row = db.query(LcDelivery).one()
        assert row.status == "PENDING" and row.attempt == 1 and row.last_error.startswith("Delivery refused")
    finally:
        db.close()
    assert sent == []


def test_redeliver_resends_same_body_with_new_signature(client, lc, graph, posts):
    delivery_id, _ = _lead_and_delivery(lc)
    headers = _login(client)
    key = _key(client, headers)
    res = client.post(f"/api/v1/lead-capture/deliveries/{delivery_id}/redeliver", headers={"Authorization": f"Bearer {key}"})
    assert res.status_code == 200, res.text
    assert len(posts) == 2 and posts[0]["body"] == posts[1]["body"]


# ── gateway (AC-64-60/65/70/72) ─────────────────────────────────────────────

def test_gateway_key_auth_audit_and_cross_tenant_pull(client, lc, graph, posts):
    headers = _login(client)
    _connect(client, headers)
    key_a = _key(client, headers)
    assert key_a.startswith("fxl_live_")
    _register(client, key_a)
    _signed_webhook(client, _fixture("leadgen-webhook-test-lead.json"))

    # tenant B with its own key sees none of A's leads
    _second_tenant(lc, False)
    from modules.lead_capture.services import key_service

    db = lc()
    try:
        _row, key_b = key_service.issue(db, TENANT_B, name="B", created_by=None)
        stored = db.query(key_service.LcApiKey).filter(key_service.LcApiKey.tenant_id == DEFAULT_TENANT_ID).one()
        assert stored.key_hash != key_a and key_a not in stored.key_hash and stored.key_prefix in key_a
    finally:
        db.close()

    res_a = client.get("/api/v1/lead-capture/leads", headers={"Authorization": f"Bearer {key_a}"})
    assert res_a.status_code == 200, res_a.text
    data = res_a.json()["data"]
    assert len(data) == 1 and data[0]["platformLeadId"] == LEAD_ID and data[0]["fields"]["name"] == "Test Lead"
    assert data[0]["receivedAt"].endswith("Z")
    res_b = client.get("/api/v1/lead-capture/leads", headers={"Authorization": f"Bearer {key_b}"})
    assert res_b.json()["data"] == []
    # B cannot redeliver A's delivery
    db = lc()
    try:
        a_delivery = db.query(LcDelivery).first().id
    finally:
        db.close()
    res = client.post(f"/api/v1/lead-capture/deliveries/{a_delivery}/redeliver", headers={"Authorization": f"Bearer {key_b}"})
    assert res.status_code == 404

    # bad / revoked key: uniform 401, error envelope
    bad = client.get("/api/v1/lead-capture/leads", headers={"Authorization": "Bearer fxl_live_nope12345678"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_api_key"
    kid = client.get("/lead-capture/keys", headers=headers).json()["data"][0]["id"]
    assert client.delete(f"/lead-capture/keys/{kid}", headers=headers).status_code == 204
    assert client.get("/api/v1/lead-capture/leads", headers={"Authorization": f"Bearer {key_a}"}).status_code == 401
    # listing shows the masked key only
    listed = client.get("/lead-capture/keys", headers=headers).json()["data"][0]
    assert listed["keyMasked"] == "fxl_live_****" + key_a[-4:] and key_a not in json.dumps(listed)

    db = lc()
    try:
        audits = db.query(LcApiAudit).filter(LcApiAudit.tenant_id == DEFAULT_TENANT_ID).all()
        assert {(a.route, a.status_code) for a in audits} >= {("/leads", 200)}
        b_audits = db.query(LcApiAudit).filter(LcApiAudit.tenant_id == TENANT_B).all()
        assert {(a.route, a.status_code) for a in b_audits} >= {("/leads", 200), ("/deliveries/{delivery_id}/redeliver", 404)}
    finally:
        db.close()


def test_bad_keys_are_throttled_per_ip(client, lc, monkeypatch):
    """AC-64-72: repeated 401s from one IP answer 429 with Retry-After."""
    monkeypatch.setattr(settings, "throttle_lead_gateway_max_fails", 3)
    codes = [
        client.get("/api/v1/lead-capture/leads", headers={"Authorization": "Bearer fxl_live_wrong0000000000"}).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401] and codes[-1] == 429
    res = client.get("/api/v1/lead-capture/leads", headers={"Authorization": "Bearer fxl_live_wrong0000000000"})
    assert res.json()["error"]["code"] == "rate_limited" and "Retry-After" in res.headers


def test_pull_cursor_pages_in_order(client, lc, graph, posts):
    from datetime import datetime, timedelta, timezone

    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        src = db.query(LcSource).one()
        base = datetime(2026, 11, 15, tzinfo=timezone.utc)
        for i in range(3):
            db.add(LcLead(tenant_id=DEFAULT_TENANT_ID, source_id=src.id, platform="facebook",
                          platform_lead_id=f"l{i}", received_at=base + timedelta(minutes=i)))
        db.commit()
    finally:
        db.close()
    headers = _login(client)
    key = {"Authorization": f"Bearer {_key(client, headers)}"}
    p1 = client.get("/api/v1/lead-capture/leads?limit=2&since=2026-11-15T00:00:00Z", headers=key).json()
    assert [d["platformLeadId"] for d in p1["data"]] == ["l0", "l1"] and p1["hasMore"] is True
    p2 = client.get(f"/api/v1/lead-capture/leads?limit=2&cursor={p1['nextCursor']}", headers=key).json()
    assert [d["platformLeadId"] for d in p2["data"]] == ["l2"] and p2["hasMore"] is False
    p3 = client.get(f"/api/v1/lead-capture/leads?cursor={p2['nextCursor']}", headers=key).json()
    assert p3["data"] == [] and p3["nextCursor"] == p2["nextCursor"]
    bad = client.get("/api/v1/lead-capture/leads?cursor=garbage", headers=key)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_cursor"


def test_webhook_registration_rejects_internal_url_and_caps(client, lc):
    headers = _login(client)
    key = {"Authorization": f"Bearer {_key(client, headers)}"}
    res = client.post("/api/v1/lead-capture/webhooks", json={"url": "http://10.0.0.5/x", "events": ["lead.created"]}, headers=key)
    assert res.status_code == 422
    created = [client.post("/api/v1/lead-capture/webhooks", json={"url": f"https://c{i}.example/x"}, headers=key) for i in range(6)]
    assert [r.status_code for r in created] == [201] * 5 + [409]
    first = created[0].json()
    assert first["secret"].startswith("whsec_")
    listed = client.get("/api/v1/lead-capture/webhooks", headers=key).json()["data"]
    assert len(listed) == 5 and "secret" not in json.dumps(listed)


def test_settings_toggle_via_gateway(client, lc):
    headers = _login(client)
    key = {"Authorization": f"Bearer {_key(client, headers)}"}
    assert client.get("/api/v1/lead-capture/settings", headers=key).json()["allowSharedPages"] is False
    res = client.put("/api/v1/lead-capture/settings", json={"allowSharedPages": True}, headers=key)
    assert res.json()["allowSharedPages"] is True


# ── security review round 1 ─────────────────────────────────────────────────

@pytest.mark.parametrize("since", ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00", "not-a-time"])
def test_edge_since_and_cursor_are_422_not_500(client, lc, since):
    import base64

    headers = _login(client)
    key = {"Authorization": f"Bearer {_key(client, headers)}"}
    res = client.get("/api/v1/lead-capture/leads", params={"since": since}, headers=key)
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_since"
    raw = json.dumps(["0001-01-01T00:00:00+14:00", "x"]).encode()
    cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    res = client.get("/api/v1/lead-capture/leads", params={"cursor": cursor}, headers=key)
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_cursor"


def test_purged_lead_is_not_redelivered(lc, graph, posts):
    from datetime import datetime, timezone

    delivery_id, _ = _lead_and_delivery(lc)
    db = lc()
    try:
        lead = db.query(LcLead).one()
        lead.purged_at = datetime.now(timezone.utc)
        db.commit()
        with pytest.raises(delivery_service.DeliveryError) as exc:
            delivery_service.redeliver(db, DEFAULT_TENANT_ID, delivery_id)
        assert exc.value.code == "lead_purged"
    finally:
        db.close()
    assert len(posts) == 1


def test_dev_credential_is_ignored_once_meta_is_configured(lc, graph):
    """A source connected with no Meta app (dev stub) never serves canned
    leads after the real app is configured; a real source still works."""
    from app.secrets import encrypt_secret

    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        src = db.query(LcSource).one()
        src.credentials_encrypted = encrypt_secret({"pageToken": "dev-page-token", "dev": True})
        db.commit()
        with pytest.raises(meta_leads.MetaLeadError):
            leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert _leads(lc) == []


# ── code review round 1 ─────────────────────────────────────────────────────

def test_a_claimed_delivery_is_sent_once(lc, graph, posts):
    """The task's reschedule and the due tick reaching one row together send
    it ONCE (atomic claim)."""
    posts.state["status"] = 500
    delivery_id, _ = _lead_and_delivery(lc)
    db = lc()
    try:
        row = db.get(LcDelivery, delivery_id)
        row.next_at = row.last_attempt_at
        db.commit()
        stale = lc()  # a second worker that read the row before the claim
        stale_row = stale.get(LcDelivery, delivery_id)
        assert delivery_service.dispatch(db, delivery_id) == "retry"
        assert stale_row.status == "PENDING"
        assert delivery_service.dispatch(stale, delivery_id) == "skip"
        stale.close()
        db.expire_all()
        assert db.get(LcDelivery, delivery_id).attempt == 2
    finally:
        db.close()
    assert len(posts) == 2


def test_pull_holds_back_a_lead_still_settling(client, lc, graph, posts, monkeypatch):
    from modules.lead_capture.services import read_service

    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    headers = _login(client)
    key = {"Authorization": f"Bearer {_key(client, headers)}"}
    monkeypatch.setattr(read_service, "PULL_SETTLE_SECONDS", 60)
    assert client.get("/api/v1/lead-capture/leads?since=2026-01-01T00:00:00Z", headers=key).json()["data"] == []
    monkeypatch.setattr(read_service, "PULL_SETTLE_SECONDS", 0)
    assert len(client.get("/api/v1/lead-capture/leads?since=2026-01-01T00:00:00Z", headers=key).json()["data"]) == 1


def test_per_key_budget_is_429(client, lc, monkeypatch):
    monkeypatch.setattr(settings, "throttle_lead_gateway_key_max_requests", 2)
    headers = _login(client)
    key = {"Authorization": f"Bearer {_key(client, headers)}"}
    codes = [client.get("/api/v1/lead-capture/sources", headers=key).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and codes[-1] == 429


def test_cross_tenant_webhook_delete_is_404(client, lc):
    from modules.lead_capture.services import key_service

    headers = _login(client)
    key_a = {"Authorization": f"Bearer {_key(client, headers)}"}
    ep = _register(client, key_a["Authorization"].split(" ", 1)[1])
    _second_tenant(lc, False)
    db = lc()
    try:
        _row, key_b = key_service.issue(db, TENANT_B, name="B", created_by=None)
    finally:
        db.close()
    res = client.delete(f"/api/v1/lead-capture/webhooks/{ep['id']}", headers={"Authorization": f"Bearer {key_b}"})
    assert res.status_code == 404 and res.json()["error"]["code"] == "endpoint_not_found"
    assert len(client.get("/api/v1/lead-capture/webhooks", headers=key_a).json()["data"]) == 1


def test_rolled_back_ingress_enqueues_nothing(lc, graph, monkeypatch):
    called = []
    import app.workflow_engine.worker as w

    monkeypatch.setattr(w.lead_capture_process_leadgen, "delay", lambda *a, **k: called.append(a))
    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        leadgen_service.handle_leadgen_change(db, "page", PAGE_ID, {"leadgen_id": LEAD_ID})
        db.rollback()
        db.commit()
    finally:
        db.close()
    assert called == []


# ── per-product mapping (owner 15 Nov: Sorento and EcoHub fields differ) ──────

def test_each_product_maps_to_its_own_fields(client, lc, graph, posts):
    """Two products on one shared Page: each publishes its own field list and
    map; each delivery carries only that product's field keys."""
    from modules.lead_capture.services import field_service

    _second_tenant(lc, True)
    db = lc()
    try:
        connect_service.set_allow_shared_pages(db, DEFAULT_TENANT_ID, True, None)
        src_a = connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        src_b = connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        field_service.set_fields(db, DEFAULT_TENANT_ID, [
            {"key": "contact_name", "label": "Contact", "type": "name"},
            {"key": "mobile_no", "label": "Mobile", "type": "phone"},
            {"key": "email_address", "label": "Email", "type": "email"},
            {"key": "product_interest", "label": "Interest", "type": "text"},
            {"key": "remarks", "label": "Remarks", "type": "notes"},
        ])
        field_service.set_field_map(db, DEFAULT_TENANT_ID, src_a.id, "*", {"interest": "product_interest"})
        # product B keeps the defaults
        delivery_service.create_endpoint(db, DEFAULT_TENANT_ID, "https://a.example/hook", ["lead.created"])
        delivery_service.create_endpoint(db, TENANT_B, "https://b.example/hook", ["lead.created"])
        leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
        b_row = db.get(LcSource, src_b.id)
        a_row = db.get(LcSource, src_a.id)
        assert a_row.needs_mapping_json is None  # mapped: no notice
        assert b_row.needs_mapping_json == {FORM_ID: {"formId": FORM_ID, "formName": FORM_NAME, "unmappedCount": 1}}
    finally:
        db.close()
    by_url = {p["url"]: json.loads(p["body"])["data"]["fields"] for p in posts}
    assert by_url["https://a.example/hook"] == {
        "contact_name": "Test Lead",
        "mobile_no": "+60120000000",
        "email_address": "lead.test@example.com",
        "product_interest": "test answer",
        "remarks": None,
    }
    assert by_url["https://b.example/hook"] == {
        "name": "Test Lead", "phone": "+60120000000", "email": "lead.test@example.com", "notes": "interest: test answer",
    }
    a_lead = _leads(lc, DEFAULT_TENANT_ID)[0]
    assert a_lead.email == "lead.test@example.com" and a_lead.phone_e164 == "+60120000000"


def test_fields_and_field_map_over_the_gateway(client, lc, graph):
    headers = _login(client)
    src = _connect(client, headers).json()
    key = {"Authorization": f"Bearer {_key(client, headers)}"}
    default = client.get("/api/v1/lead-capture/fields", headers=key).json()
    assert default["isDefault"] is True and [f["key"] for f in default["data"]] == ["name", "phone", "email", "notes"]
    res = client.put("/api/v1/lead-capture/fields", json=[{"key": "full_name", "label": "Name", "type": "name"}, {"key": "memo", "label": "Memo", "type": "notes"}], headers=key)
    assert res.status_code == 200 and res.json()["isDefault"] is False
    bad = client.put("/api/v1/lead-capture/fields", json=[{"key": "x", "type": "colour"}], headers=key)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_fields"
    ok = client.put(f"/api/v1/lead-capture/sources/{src['id']}/field-map", json={"formId": FORM_ID, "map": {"interest": "memo"}}, headers=key)
    assert ok.status_code == 200 and ok.json()["fieldMap"] == {FORM_ID: {"interest": "memo"}}
    unknown = client.put(f"/api/v1/lead-capture/sources/{src['id']}/field-map", json={"formId": FORM_ID, "map": {"interest": "nope"}}, headers=key)
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "invalid_field_map"
    missing = client.put("/api/v1/lead-capture/sources/not-mine/field-map", json={"formId": "*", "map": {}}, headers=key)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "source_not_found"



# ── live-run finding 1: formName on the Lead (additive, nullable) ───────────

def _form_reads(graph):
    return [c for c in graph.calls if c.url.path.endswith(f"/{FORM_ID}") and c.method == "GET"]


def test_lead_carries_form_name_in_push_pull_and_notice(client, lc, graph, posts):
    headers = _login(client)
    assert _connect(client, headers).status_code == 201
    key = _key(client, headers)
    _register(client, key)
    _signed_webhook(client, _fixture("leadgen-webhook-test-lead.json"))
    (lead,) = _leads(lc)
    assert lead.form_name == FORM_NAME
    pushed = json.loads(posts[0]["body"])["data"]
    assert pushed["formId"] == FORM_ID and pushed["formName"] == FORM_NAME
    pulled = client.get("/api/v1/lead-capture/leads?since=2026-01-01T00:00:00Z", headers={"Authorization": f"Bearer {key}"}).json()["data"]
    assert pulled[0]["formName"] == FORM_NAME
    src = client.get("/lead-capture/sources", headers=headers).json()["data"][0]
    assert src["needsMapping"] == [{"formId": FORM_ID, "formName": FORM_NAME, "unmappedCount": 1}]
    # read with the Page token, in the header, asking for the name only
    (read,) = _form_reads(graph)
    assert read.headers["Authorization"] == f"Bearer {PAGE_TOKEN}" and read.url.params.get("fields") == "name"


def test_form_name_is_read_once_per_form(lc, graph):
    second = "100000000000002"
    graph.extra_leads[second] = {**graph.lead, "id": second}
    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
        leadgen_service.process_leadgen(db, PAGE_ID, second, FORM_ID)
    finally:
        db.close()
    assert [lead.form_name for lead in _leads(lc)] == [FORM_NAME, FORM_NAME]
    assert len(_form_reads(graph)) == 1


def test_form_name_read_failure_never_blocks_the_lead(lc, graph, posts):
    graph.form_status = 500
    second = "100000000000002"
    graph.extra_leads[second] = {**graph.lead, "id": second}
    db = lc()
    try:
        connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        delivery_service.create_endpoint(db, DEFAULT_TENANT_ID, "https://consumer.example/leads", ["lead.created"])
        leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
        graph.form_status = 200  # a failed read is not cached: the next lead retries it
        leadgen_service.process_leadgen(db, PAGE_ID, second, FORM_ID)
    finally:
        db.close()
    names = {lead.platform_lead_id: lead.form_name for lead in _leads(lc)}
    assert names == {LEAD_ID: None, second: FORM_NAME}
    first_push = json.loads(posts[0]["body"])["data"]
    assert first_push["formName"] is None and first_push["formId"] == FORM_ID
    assert len(_form_reads(graph)) == 2


def test_form_name_migration_is_additive():
    text = (ROOT / "service_backend/modules/lead_capture/alembic/versions/0002_lc_lead_form_name.py").read_text()
    rev = text.split('revision = "', 1)[1].split('"', 1)[0]
    assert len(rev) <= 32 and 'down_revision = "0001_lead_capture_init"' in text
    assert "IF NOT EXISTS" in text and "form_name" in text
