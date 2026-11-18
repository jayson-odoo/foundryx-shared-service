"""Lead Capture R2 part 2 (plan 68): Google sign-in on the hosted wizard.

Simulated (no GOOGLE_ADS_CLIENT_ID) and a MockTransport Google for the live
shape. Fake data only; no call leaves the sandbox.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import settings
from app.secrets import decrypt_secret
from modules.lead_capture import google_ads
from modules.lead_capture.models import LcConnectSession, LcSource

from tests.test_lead_capture_prototype import (  # noqa: F401 - pytest fixtures
    TENANT_B,
    _fake_realtime,
    _leads,
    _login,
    _second_tenant,
    lc,
    posts,
)
from tests.test_lead_capture_google import _google_body, _post

BASE = "/public/lead-capture/wizard"
ACCOUNT = "1234567890"
FORM_A, FORM_B = "70000000001", "70000000002"
ACCESS, REFRESH = "ya29.ACCESS-secret-token", "1//REFRESH-secret-token"


@pytest.fixture
def signin_on(monkeypatch):
    monkeypatch.setattr(settings, "lead_capture_google_signin", True)


def _wiz(client):
    from tests.test_lead_capture_lc import _key_with_origins, _wizard

    admin = _login(client)
    key, _ = _key_with_origins(client, admin)
    return _wizard(client, key)


class FakeGoogle:
    """Google's token endpoint + the Ads API calls plan 68 makes."""

    def __init__(self):
        self.calls: list = []
        self.scope = f"{google_ads.ADS_SCOPE} openid email"
        self.refuse_form: set = set()
        self.code_ok = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        if url == google_ads.TOKEN_URL:
            form = parse_qs(request.content.decode())
            if form.get("grant_type") == ["authorization_code"]:
                if not self.code_ok:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(
                    200, json={"access_token": ACCESS, "refresh_token": REFRESH, "scope": self.scope, "expires_in": 3599}
                )
            return httpx.Response(200, json={"access_token": ACCESS, "expires_in": 3599})
        if url == google_ads.USERINFO_URL:
            return httpx.Response(200, json={"email": "person@example.com"})
        if url.endswith("customers:listAccessibleCustomers"):
            return httpx.Response(200, json={"resourceNames": [f"customers/{ACCOUNT}"]})
        if url.endswith("googleAds:search"):
            query = json.loads(request.content)["query"]
            if "FROM customer" in query:
                return httpx.Response(200, json={"results": [{"customer": {"id": ACCOUNT, "descriptiveName": "Acme Ads"}}]})
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"asset": {"id": FORM_A, "name": "Solar quote", "leadFormAsset": {"headline": "Get a quote"}}},
                        {"asset": {"id": FORM_B, "name": "Battery quote", "leadFormAsset": {"headline": "Batteries"}}},
                    ]
                },
            )
        if url.endswith("assets:mutate"):
            body = json.loads(request.content)
            asset = body["operations"][0]["update"]["resourceName"].rsplit("/", 1)[-1]
            if asset in self.refuse_form:
                return httpx.Response(403, json={"error": {"message": "The caller does not have permission"}})
            return httpx.Response(200, json={"results": [{"resourceName": body["operations"][0]["update"]["resourceName"]}]})
        return httpx.Response(404, json={})


@pytest.fixture
def google(monkeypatch, signin_on):
    fake = FakeGoogle()
    monkeypatch.setattr(settings, "google_ads_client_id", "client-123.apps.example")
    monkeypatch.setattr(settings, "google_ads_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_ads_developer_token", "dev-token")
    monkeypatch.setattr(google_ads.GoogleAdsClient, "_http", lambda self: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    return fake


def _signin(client, wiz, code="code-1"):
    return client.post(f"{BASE}/google/login", json={"code": code, "redirectUri": "http://localhost:3001/wa-callback"}, headers=wiz)


# ── A. channel + sign-in ────────────────────────────────────────────────────

def test_google_signin_is_off_unless_switched_on(client, lc):
    wiz = _wiz(client)
    ctx = client.get(f"{BASE}/context", headers=wiz).json()
    assert ctx["googleLogin"]["available"] is False
    assert _signin(client, wiz).status_code == 409


def test_context_offers_google_signin_with_the_client_id_only(client, lc, google):
    wiz = _wiz(client)
    login = client.get(f"{BASE}/context", headers=wiz).json()["googleLogin"]
    assert login == {
        "available": True,
        "simulated": False,
        "clientId": "client-123.apps.example",
        "scopes": list(google_ads.LOGIN_SCOPES),
    }


def test_signin_stores_tokens_encrypted_and_returns_accounts_only(client, lc, google, caplog):
    caplog.set_level(logging.DEBUG)
    wiz = _wiz(client)
    res = _signin(client, wiz)
    assert res.status_code == 200, res.text
    assert res.json() == {"data": [{"id": ACCOUNT, "name": "Acme Ads"}]}
    for secret in (ACCESS, REFRESH):
        assert secret not in res.text and secret not in caplog.text
    db = lc()
    try:
        row = db.query(LcConnectSession).filter(LcConnectSession.google_encrypted.isnot(None)).one()
        assert REFRESH not in row.google_encrypted
        data = decrypt_secret(row.google_encrypted)
        assert data["refreshToken"] == REFRESH and data["email"] == "person@example.com"
    finally:
        db.close()
    # the Ads calls carry the developer token, tokens only in headers
    ads = [c for c in google.calls if "googleads" in str(c.url)]
    assert ads and all(c.headers["developer-token"] == "dev-token" for c in ads)
    assert all(ACCESS not in str(c.url) for c in google.calls)


def test_declined_ads_permission_is_e1(client, lc, google):
    google.scope = "openid email"
    wiz = _wiz(client)
    res = _signin(client, wiz)
    assert res.status_code == 400 and res.json()["error"]["code"] == "PERMISSION_DECLINED"


def test_refused_code_is_login_failed(client, lc, google):
    google.code_ok = False
    wiz = _wiz(client)
    res = _signin(client, wiz)
    assert res.status_code == 400 and res.json()["error"]["code"] == "LOGIN_FAILED"


def test_no_signin_yet_is_login_required(client, lc, google):
    wiz = _wiz(client)
    res = client.get(f"{BASE}/google/accounts", headers=wiz)
    assert res.status_code == 409 and res.json()["error"]["code"] == "LOGIN_REQUIRED"


# ── B. account + forms + connect ────────────────────────────────────────────

def test_forms_of_an_account_the_person_cannot_reach_is_404(client, lc, google):
    wiz = _wiz(client)
    _signin(client, wiz)
    assert client.get(f"{BASE}/google/accounts/9999999999/forms", headers=wiz).status_code == 404
    ok = client.get(f"{BASE}/google/accounts/{ACCOUNT}/forms", headers=wiz)
    assert ok.status_code == 200
    assert ok.json()["data"] == [{"id": FORM_A, "name": "Solar quote"}, {"id": FORM_B, "name": "Battery quote"}]


def test_connect_writes_the_webhook_into_each_ticked_form(client, lc, google, posts):
    wiz = _wiz(client)
    _signin(client, wiz)
    res = client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": [FORM_A, FORM_B]}, headers=wiz)
    assert res.status_code == 200, res.text
    body = res.json()
    assert [f["ok"] for f in body["forms"]] == [True, True]
    src = body["source"]
    assert src["platform"] == "google" and src["pageId"] == ACCOUNT and src["pageName"] == "Acme Ads"
    assert src["formsMode"] == "pick" and sorted(src["formIds"]) == sorted([FORM_A, FORM_B])
    mutates = [json.loads(c.content) for c in google.calls if str(c.url).endswith("assets:mutate")]
    hooks = [m["operations"][0]["update"]["leadFormAsset"]["deliveryMethods"][0]["webhook"] for m in mutates]
    assert len(hooks) == 2
    url, key = hooks[0]["advertiserWebhookUrl"], hooks[0]["googleSecret"]
    assert url.startswith(settings.public_base_url) and "/public/lead-capture/in/" in url
    # what we wrote is exactly what the receiver accepts
    assert _post(client, url, _google_body(key)).status_code == 200
    assert len(_leads(lc)) == 1
    # the session's source is bound: the next steps reach it
    ctx = client.get(f"{BASE}/context", headers=wiz).json()
    assert ctx["source"]["id"] == src["id"]


def test_one_refusing_form_never_fails_the_rest_and_try_again_keeps_the_key(client, lc, google):
    google.refuse_form = {FORM_B}
    wiz = _wiz(client)
    _signin(client, wiz)
    body = client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": [FORM_A, FORM_B]}, headers=wiz).json()
    by_id = {f["id"]: f for f in body["forms"]}
    assert by_id[FORM_A]["ok"] is True
    assert by_id[FORM_B]["ok"] is False and by_id[FORM_B]["message"]
    google.refuse_form = set()
    again = client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": [FORM_B]}, headers=wiz).json()
    assert again["source"]["id"] == body["source"]["id"] and again["forms"][0]["ok"] is True
    keys = {
        json.loads(c.content)["operations"][0]["update"]["leadFormAsset"]["deliveryMethods"][0]["webhook"]["googleSecret"]
        for c in google.calls
        if str(c.url).endswith("assets:mutate")
    }
    assert len(keys) == 1  # the same key both times: form A keeps working
    assert sorted(again["source"]["formIds"]) == sorted([FORM_A, FORM_B])


def test_connect_needs_a_form_of_that_account(client, lc, google):
    wiz = _wiz(client)
    _signin(client, wiz)
    none = client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": []}, headers=wiz)
    assert none.status_code == 422
    foreign = client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": ["123"]}, headers=wiz)
    assert foreign.status_code == 422
    other = client.post(f"{BASE}/google/connect", json={"accountId": "9999999999", "formIds": [FORM_A]}, headers=wiz)
    assert other.status_code == 404


def test_second_wizard_never_takes_over_a_connected_form(client, lc, google):
    first = _wiz(client)
    _signin(client, first)
    client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": [FORM_A]}, headers=first)
    second = _wiz(client)
    _signin(client, second)
    res = client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": [FORM_A]}, headers=second)
    assert res.status_code == 409 and res.json()["error"]["code"] == "source_exists"


def test_source_keeps_the_refresh_token_encrypted_and_a_new_key_keeps_it(client, lc, google):
    wiz = _wiz(client)
    _signin(client, wiz)
    sid = client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": [FORM_A]}, headers=wiz).json()["source"]["id"]
    db = lc()
    try:
        row = db.query(LcSource).filter(LcSource.id == sid).one()
        creds = decrypt_secret(row.credentials_encrypted)
        assert creds["googleRefreshToken"] == REFRESH and creds["googleKey"]
        assert REFRESH not in row.credentials_encrypted
    finally:
        db.close()
    admin = _login(client)
    client.post(f"/lead-capture/sources/{sid}/rotate-key", headers=admin)
    db = lc()
    try:
        creds = decrypt_secret(db.query(LcSource).filter(LcSource.id == sid).one().credentials_encrypted)
        assert creds["googleRefreshToken"] == REFRESH
    finally:
        db.close()


# ── simulated + isolation ───────────────────────────────────────────────────

def test_simulated_signin_makes_no_network_call(client, lc, signin_on, monkeypatch):
    def boom(self):
        raise AssertionError("no Google call in simulated mode")

    monkeypatch.setattr(google_ads.GoogleAdsClient, "_http", boom)
    wiz = _wiz(client)
    login = client.get(f"{BASE}/context", headers=wiz).json()["googleLogin"]
    assert login["available"] is True and login["simulated"] is True
    accounts = _signin(client, wiz, code="simulated").json()["data"]
    assert accounts == google_ads.DEV_ACCOUNTS
    forms = client.get(f"{BASE}/google/accounts/{accounts[0]['id']}/forms", headers=wiz).json()["data"]
    res = client.post(
        f"{BASE}/google/connect", json={"accountId": accounts[0]["id"], "formIds": [forms[0]["id"]]}, headers=wiz
    )
    assert res.status_code == 200 and res.json()["forms"][0]["ok"] is True


def test_another_session_cannot_use_this_google_signin(client, lc, google):
    first = _wiz(client)
    _signin(client, first)
    other = _wiz(client)
    res = client.get(f"{BASE}/google/accounts", headers=other)
    assert res.status_code == 409 and res.json()["error"]["code"] == "LOGIN_REQUIRED"


def test_one_source_per_account_a_second_wizard_on_another_form_is_409_not_500(client, lc, google):
    """Postgres-only bug class (uq_lc_source_live_account): found in the
    browser pass. One live Google source per account, like one per Page."""
    first = _wiz(client)
    _signin(client, first)
    client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": [FORM_A]}, headers=first)
    second = _wiz(client)
    _signin(client, second)
    res = client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": [FORM_B]}, headers=second)
    assert res.status_code == 409 and res.json()["error"]["code"] == "source_exists"


def test_reopened_source_adds_forms_to_the_same_source(client, lc, google):
    from tests.test_lead_capture_lc import _key_with_origins, _wizard

    first = _wiz(client)
    _signin(client, first)
    sid = client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": [FORM_A]}, headers=first).json()["source"]["id"]
    admin = _login(client)
    key, _ = _key_with_origins(client, admin, origins=("https://crm2.example.com",))
    reopened = _wizard(client, key, sourceId=sid, returnOrigin="https://crm2.example.com")
    _signin(client, reopened)
    res = client.post(f"{BASE}/google/connect", json={"accountId": ACCOUNT, "formIds": [FORM_B]}, headers=reopened)
    assert res.status_code == 200, res.text
    assert res.json()["source"]["id"] == sid and sorted(res.json()["source"]["formIds"]) == sorted([FORM_A, FORM_B])
