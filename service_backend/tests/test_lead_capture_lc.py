"""Lead Capture lane L-C (plan 64): connect sessions (AC-64-06), the scoped
wizard token (AC-64-07), Facebook login on core plumbing (AC-64-20/21), the
hosted-wizard steps through the same services as the gateway, the gateway
login door for a product's own wizard, and the staff Sources + Leads lists
(AC-64-05/53). Cross-tenant and token-leak checks (AC-64-70/71).

Never calls real Graph: the simulated flow (no META_APP_ID) or an httpx
MockTransport on top of the prototype harness.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.scoped_tokens import decode_scoped_token, mint_scoped_token
from app.secrets import decrypt_secret
from modules.lead_capture.models import (
    SOURCE_LIVE,
    SOURCE_WAITING_FOR_TEST,
    LcConnectSession,
    LcLead,
    LcSource,
)
from modules.lead_capture.services import connect_session_service as sessions

from tests.test_lead_capture_prototype import (  # noqa: F401 - pytest fixtures
    PAGE_ID,
    PAGE_TOKEN,
    TENANT_B,
    FakeGraph,
    _fake_realtime,
    _key,
    _login,
    _second_tenant,
    graph,
    lc,
    posts,
)

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://crm.example.com"
USER_TOKEN = "USERtok3n0123456789abcdefSECRETvalue"
FB_CODE = "AQCcode0123456789SECRET"
DEV_PAGE = sessions.DEV_PAGES[0]["id"]


def _gw(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _key_with_origins(client, headers, origins=(ORIGIN,)) -> tuple:
    res = client.post(
        "/lead-capture/keys", json={"name": "CRM", "allowedOrigins": list(origins)}, headers=headers
    )
    assert res.status_code == 201, res.text
    body = res.json()
    return body["key"], body["id"]


def _secret(url: str) -> str:
    assert "#s=" in url
    return url.split("#s=", 1)[1]


def _session(client, key, **body) -> dict:
    res = client.post("/api/v1/lead-capture/connect-sessions", json={"returnOrigin": ORIGIN, **body}, headers=_gw(key))
    assert res.status_code == 201, res.text
    return res.json()


def _redeem(client, secret: str):
    return client.post("/public/lead-capture/connect/redeem", json={"token": secret})


def _wizard(client, key, **body) -> dict:
    """Open a fresh hosted session; the wizard headers."""
    url = _session(client, key, **body)["url"]
    res = _redeem(client, _secret(url))
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['accessToken']}"}


class LoginGraph(FakeGraph):
    """FakeGraph + the login edges: code exchange, long-lived swap,
    /me/permissions and /me/accounts."""

    def __init__(self):
        super().__init__()
        self.declined = False
        self.code_ok = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth/access_token"):
            self.calls.append(request)
            if request.url.params.get("grant_type") == "fb_exchange_token":
                return httpx.Response(200, json={"access_token": USER_TOKEN})
            if not self.code_ok:
                return httpx.Response(400, json={"error": {"message": "bad code", "code": 100}})
            return httpx.Response(200, json={"access_token": "short-" + USER_TOKEN})
        if path.endswith("/me/permissions"):
            self.calls.append(request)
            perms = [{"permission": "pages_show_list", "status": "granted"}]
            perms.append({"permission": "leads_retrieval", "status": "declined" if self.declined else "granted"})
            return httpx.Response(200, json={"data": perms})
        if path.endswith("/me/accounts"):
            self.calls.append(request)
            return httpx.Response(
                200, json={"data": [{"id": PAGE_ID, "name": "Solar Page", "access_token": PAGE_TOKEN}]}
            )
        return super().handler(request)


@pytest.fixture
def login_graph(monkeypatch):
    g = LoginGraph()
    monkeypatch.setattr(settings, "meta_app_id", "app-123")
    monkeypatch.setattr(settings, "meta_app_secret", "app-s3cret")
    monkeypatch.setattr(settings, "lead_capture_login_config_id", "cfg-1")
    from app.integrations.meta import pages as meta_pages
    from modules.lead_capture import meta_leads

    monkeypatch.setattr(meta_leads.MetaLeadClient, "_http", lambda self: g.client())
    monkeypatch.setattr(meta_pages.MetaPages, "_http", lambda self: g.client())
    return g


# ── migration ───────────────────────────────────────────────────────────────

def test_connect_session_migration_revision_fits_and_chains():
    text = (ROOT / "service_backend/modules/lead_capture/alembic/versions/0005_lc_connect_session.py").read_text()
    rev = text.split('revision = "', 1)[1].split('"', 1)[0]
    assert len(rev) <= 32
    assert 'down_revision = "0004_lc_source_backfill_history"' in text


# ── AC-64-06 connect sessions ───────────────────────────────────────────────

def test_session_needs_an_allowed_origin(client, lc):
    admin = _login(client)
    bare = _key(client, admin)  # no origins
    res = client.post("/api/v1/lead-capture/connect-sessions", json={"returnOrigin": ORIGIN}, headers=_gw(bare))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"

    key, key_id = _key_with_origins(client, admin)
    for bad in ("https://evil.example", "https://crm.example.com/path", "javascript:alert(1)", None):
        res = client.post("/api/v1/lead-capture/connect-sessions", json={"returnOrigin": bad}, headers=_gw(key))
        assert res.status_code == 422, bad
        assert res.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    # Case and trailing slash normalise to the same origin.
    res = client.post(
        "/api/v1/lead-capture/connect-sessions", json={"returnOrigin": "HTTPS://CRM.example.com/"}, headers=_gw(key)
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["url"].startswith(settings.frontend_url.rstrip("/") + "/public/lead-capture/connect#s=")
    expires = datetime.fromisoformat(body["expiresAt"].replace("Z", "+00:00"))
    assert timedelta(minutes=9) < expires - datetime.now(timezone.utc) <= timedelta(minutes=10)
    # Only the secret's hash is stored.
    db = lc()
    try:
        row = db.query(LcConnectSession).one()
        assert row.token_hash and _secret(body["url"]) not in row.token_hash
        assert row.return_origin == ORIGIN and row.key_id == key_id
    finally:
        db.close()


def test_staff_can_edit_key_origins_and_bad_origins_are_422(client, lc):
    admin = _login(client)
    _key_value, key_id = _key_with_origins(client, admin, origins=())
    res = client.put(
        f"/lead-capture/keys/{key_id}/origins", json={"allowedOrigins": ["ftp://x.example"]}, headers=admin
    )
    assert res.status_code == 422
    res = client.put(f"/lead-capture/keys/{key_id}/origins", json={"allowedOrigins": [ORIGIN]}, headers=admin)
    assert res.status_code == 200 and res.json()["allowedOrigins"] == [ORIGIN]


def test_url_is_single_use_and_expires(client, lc):
    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    secret = _secret(_session(client, key)["url"])
    first = _redeem(client, secret)
    assert first.status_code == 200, first.text
    assert first.json()["returnOrigin"] == ORIGIN
    second = _redeem(client, secret)
    assert second.status_code == 410
    assert second.json() == {"error": {"code": "SESSION_EXPIRED", "message": second.json()["error"]["message"]}}
    assert "Default" not in second.text  # no tenant data

    stale = _secret(_session(client, key)["url"])
    db = lc()
    try:
        for row in db.query(LcConnectSession).filter(LcConnectSession.consumed_at.is_(None)).all():
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    assert _redeem(client, stale).status_code == 410
    assert _redeem(client, "x" * 43).status_code == 410  # unknown


# ── AC-64-07 scoped wizard token ────────────────────────────────────────────

def test_wizard_token_is_scoped_to_wizard_routes(client, lc):
    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    wiz = _wizard(client, key)
    ctx = client.get("/public/lead-capture/wizard/context", headers=wiz)
    assert ctx.status_code == 200, ctx.text
    assert ctx.json()["returnOrigin"] == ORIGIN
    assert [c["key"] for c in ctx.json()["channels"]] == ["facebook"]
    # Staff and gateway routes refuse it.
    assert client.get("/lead-capture/sources", headers=wiz).status_code == 401
    assert client.get("/api/v1/lead-capture/sources", headers=wiz).status_code == 401
    assert client.get("/auth/me", headers=wiz).status_code == 401
    # A staff session and the gateway key are not wizard tokens.
    assert client.get("/public/lead-capture/wizard/context", headers=admin).status_code == 401
    assert client.get("/public/lead-capture/wizard/context", headers=_gw(key)).status_code == 401


def test_a_typed_token_never_opens_a_staff_route_even_with_a_user_sub(client, lc):
    """assert_staff_token refuses ANY typ (one shared rule for every scoped
    token), so a forged-looking wizard token whose sub is a real user id
    is still refused on staff routes."""
    admin = _login(client)
    me = client.get("/auth/me", headers=admin).json()
    forged = mint_scoped_token(
        sessions.EMBED_TYP, {"sub": me["id"], "tenant_id": DEFAULT_TENANT_ID, "sid": "x"}, ttl_minutes=5
    )
    assert client.get("/lead-capture/sources", headers=_gw(forged)).status_code == 401
    assert decode_scoped_token(forged, "embed") is None
    other = mint_scoped_token("embed", {"sub": "a", "tenant_id": DEFAULT_TENANT_ID}, ttl_minutes=5)
    assert client.get("/public/lead-capture/wizard/context", headers=_gw(other)).status_code == 401


def test_wizard_reaches_only_its_own_source(client, lc):
    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    wiz = _wizard(client, key)
    client.post("/public/lead-capture/wizard/facebook/login", json={"code": "dev"}, headers=wiz)
    source = client.post("/public/lead-capture/wizard/facebook/connect", json={"pageId": DEV_PAGE}, headers=wiz)
    assert source.status_code == 200, source.text
    sid = source.json()["id"]
    # A second wizard of the same tenant cannot read the first one's source.
    other = _wizard(client, key)
    for path in (f"/wizard/sources/{sid}", f"/wizard/sources/{sid}/forms"):
        assert client.get("/public/lead-capture" + path, headers=other).status_code == 404
    res = client.put(
        f"/public/lead-capture/wizard/sources/{sid}/field-map", json={"formId": "1", "map": {}}, headers=other
    )
    assert res.status_code == 404


def test_cross_tenant_session_and_source(client, lc):
    _second_tenant(lc, allow_sharing=False)
    admin_a = _login(client)
    key_a, _ = _key_with_origins(client, admin_a)
    wiz_a = _wizard(client, key_a)
    client.post("/public/lead-capture/wizard/facebook/login", json={"code": "dev"}, headers=wiz_a)
    sid = client.post(
        "/public/lead-capture/wizard/facebook/connect", json={"pageId": DEV_PAGE}, headers=wiz_a
    ).json()["id"]

    # Tenant B's key can never bind a session to tenant A's source.
    db = lc()
    try:
        from modules.lead_capture.services import key_service

        row_b, key_b = key_service.issue(db, TENANT_B, name="B", created_by=None)
        sessions.set_key_origins(db, TENANT_B, row_b.id, [ORIGIN])
    finally:
        db.close()
    res = client.post(
        "/api/v1/lead-capture/connect-sessions", json={"returnOrigin": ORIGIN, "sourceId": sid}, headers=_gw(key_b)
    )
    assert res.status_code == 404
    wiz_b = _wizard(client, key_b)
    assert client.get(f"/public/lead-capture/wizard/sources/{sid}", headers=wiz_b).status_code == 404
    assert client.get("/public/lead-capture/wizard/context", headers=wiz_b).json()["source"] is None


def test_disabled_module_turns_the_wizard_token_off(client, lc):
    from app.services.app_store_service import AppStoreService

    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    wiz = _wizard(client, key)
    db = lc()
    try:
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "lead_capture")
        db.commit()
    finally:
        db.close()
    assert client.get("/public/lead-capture/wizard/context", headers=wiz).status_code == 403


# ── the whole hosted flow (simulated Meta) ──────────────────────────────────

def test_simulated_wizard_flow_ends_live_with_done_data(client, lc):
    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    wiz = _wizard(client, key)
    base = "/public/lead-capture/wizard"
    pages = client.post(f"{base}/facebook/login", json={"code": "dev"}, headers=wiz)
    assert pages.status_code == 200, pages.text
    assert [p["id"] for p in pages.json()["data"]] == [p["id"] for p in sessions.DEV_PAGES]
    assert "Foundryx" not in pages.text  # white-label (AC-64-11)
    assert client.get(f"{base}/facebook/pages", headers=wiz).json() == pages.json()

    src = client.post(f"{base}/facebook/connect", json={"pageId": DEV_PAGE}, headers=wiz)
    assert src.status_code == 200, src.text
    assert src.json()["status"] == SOURCE_WAITING_FOR_TEST
    sid = src.json()["id"]

    forms = client.get(f"{base}/sources/{sid}/forms", headers=wiz)
    assert forms.status_code == 200, forms.text
    form_id = forms.json()["data"][0]["id"]
    assert client.put(f"{base}/sources/{sid}/forms", json={"formsMode": "pick", "formIds": []}, headers=wiz).status_code == 422
    assert client.put(f"{base}/sources/{sid}/forms", json={"formsMode": "all"}, headers=wiz).status_code == 200

    questions = client.get(f"{base}/sources/{sid}/forms/{form_id}/questions", headers=wiz)
    assert questions.status_code == 200, questions.text
    fields = client.get(f"{base}/fields", headers=wiz).json()["data"]
    assert {f["key"] for f in fields} >= {"name", "email", "phone", "notes"}
    mapped = client.put(
        f"{base}/sources/{sid}/field-map",
        json={"formId": form_id, "map": {"full_name": "name", "email": "email", "phone_number": "phone"}},
        headers=wiz,
    )
    assert mapped.status_code == 200, mapped.text

    sent = client.post(f"{base}/sources/{sid}/test-lead", json={"formId": form_id}, headers=wiz)
    assert sent.status_code == 202, sent.text
    assert client.get(f"{base}/sources/{sid}", headers=wiz).json()["status"] == SOURCE_LIVE

    done = client.post(f"{base}/finish", json={}, headers=wiz)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["source"]["id"] == sid
    assert body["connectedBy"] == "CRM"  # the key's name
    assert body["testLeadAt"] and body["waitingForRealLead"] is True

    # The same source shows on the gateway list the product reads (AC-64-09).
    listed = client.get("/api/v1/lead-capture/sources", headers=_gw(key)).json()["data"]
    assert [s["id"] for s in listed] == [sid]


def test_steps_before_login_and_connect_are_refused_cleanly(client, lc):
    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    wiz = _wizard(client, key)
    res = client.get("/public/lead-capture/wizard/facebook/pages", headers=wiz)
    assert res.status_code == 409 and res.json()["error"]["code"] == "LOGIN_REQUIRED"
    res = client.post("/public/lead-capture/wizard/facebook/connect", json={"pageId": DEV_PAGE}, headers=wiz)
    assert res.status_code == 409 and res.json()["error"]["code"] == "LOGIN_REQUIRED"
    res = client.post("/public/lead-capture/wizard/finish", json={}, headers=wiz)
    assert res.status_code == 409


def test_page_in_use_is_the_e4_answer(client, lc):
    _second_tenant(lc, allow_sharing=False)
    db = lc()
    try:
        from modules.lead_capture.services import connect_service, key_service

        connect_service.connect_facebook(db, TENANT_B, page_id=DEV_PAGE, system_user_token="dev")
        row_b, _ = key_service.issue(db, TENANT_B, name="B", created_by=None)
    finally:
        db.close()
    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    wiz = _wizard(client, key)
    client.post("/public/lead-capture/wizard/facebook/login", json={"code": "dev"}, headers=wiz)
    res = client.post("/public/lead-capture/wizard/facebook/connect", json={"pageId": DEV_PAGE}, headers=wiz)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "PAGE_IN_USE"


# ── AC-64-20/21 Facebook login on core plumbing (real-mode, MockTransport) ──

def test_login_exchanges_code_and_keeps_the_token_server_side(client, lc, login_graph, caplog):
    caplog.set_level(logging.DEBUG)
    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    wiz = _wizard(client, key)
    ctx = client.get("/public/lead-capture/wizard/context", headers=wiz).json()
    assert ctx["login"] == {
        "available": True,
        "simulated": False,
        "appId": "app-123",
        "configId": "cfg-1",
        "graphVersion": settings.meta_graph_version,
        "scopes": ["pages_show_list", "pages_manage_metadata", "pages_read_engagement", "leads_retrieval", "pages_manage_ads"],
    }
    res = client.post("/public/lead-capture/wizard/facebook/login", json={"code": FB_CODE}, headers=wiz)
    assert res.status_code == 200, res.text
    assert res.json()["data"] == [{"id": PAGE_ID, "name": "Solar Page"}]
    for secret in (USER_TOKEN, PAGE_TOKEN, FB_CODE):
        assert secret not in res.text
        assert secret not in caplog.text
    db = lc()
    try:
        row = db.query(LcConnectSession).filter(LcConnectSession.meta_encrypted.isnot(None)).one()
        assert USER_TOKEN not in row.meta_encrypted
        assert decrypt_secret(row.meta_encrypted)["userToken"] == USER_TOKEN
    finally:
        db.close()
    # Connect derives the Page token from the stored login token (one function).
    src = client.post("/public/lead-capture/wizard/facebook/connect", json={"pageId": PAGE_ID}, headers=wiz)
    assert src.status_code == 200, src.text
    page_reads = [c for c in login_graph.calls if c.url.path.endswith(f"/{PAGE_ID}")]
    assert page_reads and page_reads[-1].headers["Authorization"] == f"Bearer {USER_TOKEN}"


def test_declined_lead_permission_is_e1(client, lc, login_graph):
    login_graph.declined = True
    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    wiz = _wizard(client, key)
    res = client.post("/public/lead-capture/wizard/facebook/login", json={"code": FB_CODE}, headers=wiz)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "PERMISSION_DECLINED"
    login_graph.declined, login_graph.code_ok = False, False
    res = client.post("/public/lead-capture/wizard/facebook/login", json={"code": FB_CODE}, headers=wiz)
    assert res.status_code == 400 and res.json()["error"]["code"] == "LOGIN_FAILED"


def test_facebook_hidden_when_app_set_but_no_login_config(client, lc, monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "app-123")
    monkeypatch.setattr(settings, "lead_capture_login_config_id", "")
    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    assert client.get("/api/v1/lead-capture/channels", headers=_gw(key)).json()["data"] == []
    wiz = _wizard(client, key)
    res = client.post("/public/lead-capture/wizard/facebook/login", json={"code": FB_CODE}, headers=wiz)
    assert res.status_code == 409


# ── gateway door: a product's own wizard (owner 17 Nov) ─────────────────────

def test_gateway_login_then_connect_with_login_id(client, lc, login_graph):
    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    other_key = _key(client, admin)
    cfg = client.get("/api/v1/lead-capture/facebook/login-config", headers=_gw(key))
    assert cfg.status_code == 200 and cfg.json()["configId"] == "cfg-1"
    res = client.post("/api/v1/lead-capture/facebook/login", json={"code": FB_CODE}, headers=_gw(key))
    assert res.status_code == 201, res.text
    login = res.json()
    assert login["pages"] == [{"id": PAGE_ID, "name": "Solar Page"}]
    assert USER_TOKEN not in res.text
    listed = client.get(f"/api/v1/lead-capture/facebook/logins/{login['loginId']}/pages", headers=_gw(key))
    assert listed.json()["data"] == login["pages"]
    # Another key of the same tenant cannot use it.
    res = client.post(
        "/api/v1/lead-capture/sources/facebook", json={"pageId": PAGE_ID, "loginId": login["loginId"]}, headers=_gw(other_key)
    )
    assert res.status_code == 409
    both = client.post(
        "/api/v1/lead-capture/sources/facebook",
        json={"pageId": PAGE_ID, "loginId": login["loginId"], "systemUserToken": "x"},
        headers=_gw(key),
    )
    assert both.status_code == 422
    ok = client.post(
        "/api/v1/lead-capture/sources/facebook", json={"pageId": PAGE_ID, "loginId": login["loginId"]}, headers=_gw(key)
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["status"] == SOURCE_WAITING_FOR_TEST


# ── staff door + lists (AC-64-05/53) ────────────────────────────────────────

def test_staff_session_posts_back_only_to_this_app(client, lc):
    admin = _login(client)
    res = client.post("/lead-capture/connect-sessions", json={"returnOrigin": "https://evil.example"}, headers=admin)
    assert res.status_code == 422
    res = client.post("/lead-capture/connect-sessions", json={"returnOrigin": "http://localhost:3001"}, headers=admin)
    assert res.status_code == 201, res.text
    res = client.post("/lead-capture/connect-sessions", json={}, headers=admin)
    assert res.status_code == 201
    wiz = {"Authorization": f"Bearer {_redeem(client, _secret(res.json()['url'])).json()['accessToken']}"}
    client.post("/public/lead-capture/wizard/facebook/login", json={"code": "dev"}, headers=wiz)
    client.post("/public/lead-capture/wizard/facebook/connect", json={"pageId": DEV_PAGE}, headers=wiz)
    sources = client.get("/lead-capture/sources/list", headers=admin).json()
    assert sources["total"] == 1 and sources["data"][0]["leads7d"] == 0


def _seed_leads(lc, source_id: str):
    from app.secrets import encrypt_secret

    db = lc()
    try:
        now = datetime.now(timezone.utc)
        for i, (email, test) in enumerate((("a@x.example", False), ("b@x.example", True), ("c@x.example", False))):
            db.add(
                LcLead(
                    tenant_id=DEFAULT_TENANT_ID,
                    source_id=source_id,
                    platform="facebook",
                    platform_lead_id=f"9000{i}",
                    form_id="1",
                    form_name=f"Form {i}",
                    received_at=now - timedelta(hours=i),
                    fields_encrypted=encrypt_secret({"fields": {"name": f"Person {i}", "email": email}}),
                    email=email,
                    is_test=test,
                )
            )
        db.commit()
    finally:
        db.close()


def test_staff_leads_list_filters_sorts_and_detail(client, lc):
    admin = _login(client)
    res = client.post("/lead-capture/connect-sessions", json={}, headers=admin)
    wiz = {"Authorization": f"Bearer {_redeem(client, _secret(res.json()['url'])).json()['accessToken']}"}
    client.post("/public/lead-capture/wizard/facebook/login", json={"code": "dev"}, headers=wiz)
    sid = client.post("/public/lead-capture/wizard/facebook/connect", json={"pageId": DEV_PAGE}, headers=wiz).json()["id"]
    _seed_leads(lc, sid)

    page = client.get("/lead-capture/leads", params={"sort": "email", "order": "asc"}, headers=admin).json()
    assert page["total"] == 3
    assert [r["email"] for r in page["data"]] == ["a@x.example", "b@x.example", "c@x.example"]
    assert page["data"][0]["name"] == "Person 0"
    real = client.get("/lead-capture/leads", params={"isTest": "false"}, headers=admin).json()
    assert real["total"] == 2
    found = client.get("/lead-capture/leads", params={"search": "b@x"}, headers=admin).json()
    assert [r["email"] for r in found["data"]] == ["b@x.example"]
    paged = client.get("/lead-capture/leads", params={"pageSize": 1, "page": 1, "sort": "email", "order": "asc"}, headers=admin)
    assert [r["email"] for r in paged.json()["data"]] == ["b@x.example"]
    assert client.get("/lead-capture/leads", params={"receivedFrom": "nope"}, headers=admin).status_code == 422

    sources = client.get("/lead-capture/sources/list", headers=admin).json()
    assert sources["data"][0]["leads7d"] == 2  # test leads do not count

    lead_id = page["data"][0]["id"]
    detail = client.get(f"/lead-capture/leads/{lead_id}", headers=admin)
    assert detail.status_code == 200, detail.text
    assert detail.json()["lead"]["fields"]["name"] == "Person 0"
    assert detail.json()["deliveries"] == []

    # Another tenant sees none of it.
    _second_tenant(lc, allow_sharing=False)
    admin_b = _login(client, email="admin@lead-b.example", password="demo1234", slug="lead-b")
    assert client.get("/lead-capture/leads", headers=admin_b).json()["total"] == 0
    assert client.get(f"/lead-capture/leads/{lead_id}", headers=admin_b).status_code == 404


def test_lists_need_the_view_permission(client, lc):
    assert client.get("/lead-capture/leads").status_code == 401
    assert client.get("/lead-capture/sources/list").status_code == 401
