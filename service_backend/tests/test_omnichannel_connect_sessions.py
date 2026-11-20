"""FSS-1 - partner connect sessions (hosted WhatsApp connect, two-step finish).

Behaviour, all through the API: off until configured (503 on every new
route); the local simulation (no Meta app id) runs the whole loop with no
Meta account; the state works once; an expired session cannot be used; a
session of another tenant or another client app answers one uniform 404; a
disabled client app is refused; the return URL must match the key's
allow-list; complete only after AUTHORIZED, and the channel is created only
there; cancel; a Meta account with several numbers gets one channel per
number not connected anywhere yet; no token, code or state in any response,
stored row or log; the simulation can never run with a Meta app id set; the
dashboard onboarding path is unchanged; migration chain and model agree.
Fake values only.
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from tests.test_omnichannel_api_gateway import _default_workspace_id, _seed_channel
from tests.test_omnichannel_client_apps import _new_app
from tests.test_omnichannel_partner_keys import _auth, other_tenant

P = "/api/v1/omnichannel/partner"
CB = "/api/v1/omnichannel/connect/wa-callback"
KEYS = "/omnichannel/partner-keys"
VERSIONS = Path(__file__).resolve().parents[1] / "modules" / "omnichannel" / "alembic" / "versions"
ORIGIN = "https://app.ecohub.example"
RETURN = f"{ORIGIN}/settings/messaging/whatsapp/return?tab=wa&status=stale"
REDIRECT_URI = "http://localhost:3001/wa-callback"
SESSION_NOT_FOUND = {"error": {"code": "connect_session_not_found", "message": "Connect session not found."}}
NOT_CONFIGURED = {"error": {"code": "connect_not_configured", "message": "Hosted connect is not configured."}}

TOKEN = "EAAG-real-secret-token-0001"
CODE = "meta-auth-code-0001"


# ── helpers ──────────────────────────────────────────────────────────────────
@pytest.fixture
def sim(monkeypatch):
    """Feature on, local simulation (no Meta app id)."""
    monkeypatch.setattr(settings, "omni_partner_wa_redirect_uri", REDIRECT_URI)
    monkeypatch.setattr(settings, "meta_app_id", "")
    monkeypatch.setattr(settings, "meta_app_secret", "")
    monkeypatch.setattr(settings, "meta_es_dialog_version", "")


@pytest.fixture
def real(monkeypatch):
    """Feature on with a (fake) Meta app configured."""
    monkeypatch.setattr(settings, "omni_partner_wa_redirect_uri", "https://chat.example/wa-callback")
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")
    monkeypatch.setattr(settings, "meta_es_config_id", "test-config-id")
    monkeypatch.setattr(settings, "meta_es_dialog_version", "v25.0")


def key(client, origins=(ORIGIN,), app_id=None, headers=None, name="EcoHub"):
    body = {"name": name, "allowedReturnOrigins": list(origins)}
    if app_id is not None:
        body["clientAppId"] = app_id
    res = client.post(KEYS, json=body, headers=headers or _auth(client))
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['fullKey']}"}


def workspace(client, hdr, ext="org-1"):
    res = client.put(f"{P}/workspaces/{ext}", json={"name": f"Company {ext}"}, headers=hdr)
    assert res.status_code == 200, res.text
    return res.json()["id"]


def create(client, hdr, ws, return_url=RETURN, client_state="nonce-123"):
    body = {"channelType": "WHATSAPP", "returnUrl": return_url}
    if client_state is not None:
        body["clientState"] = client_state
    return client.post(f"{P}/workspaces/{ws}/connect-sessions", json=body, headers=hdr)


def state_of(url):
    return parse_qs(urlsplit(url).query)["state"][0]


def callback(client, state, code="dev", error=None):
    body = {"state": state}
    if code is not None:
        body["code"] = code
    if error is not None:
        body["error"] = error
    return client.post(CB, json=body)


def setup(client):
    hdr = key(client)
    ws = workspace(client, hdr)
    return hdr, ws


def session_row(session_factory, sid):
    from modules.omnichannel.models import PartnerConnectSession

    db = session_factory()
    row = db.get(PartnerConnectSession, sid)
    db.expunge(row)
    db.close()
    return row


def update_row(session_factory, sid, **values):
    from modules.omnichannel.models import PartnerConnectSession

    db = session_factory()
    db.query(PartnerConnectSession).filter(PartnerConnectSession.id == sid).update(values)
    db.commit()
    db.close()


def channels(client, hdr, ws):
    res = client.get(f"{P}/workspaces/{ws}/channels", headers=hdr)
    assert res.status_code == 200, res.text
    return res.json()["data"]


def graph(monkeypatch, wabas, *, exchange_status=200, record=None):
    """A fake Meta Graph: `wabas` maps WABA id -> list of (id, display)."""
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
    from modules.omnichannel.services import partner_connect_service

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if record is not None:
            record.append(request)
        if path.endswith("/oauth/access_token"):
            if exchange_status != 200:
                return httpx.Response(exchange_status, json={"error": {"message": "bad code"}})
            return httpx.Response(200, json={"access_token": TOKEN})
        if path.endswith("/debug_token"):
            return httpx.Response(
                200,
                json={"data": {"granular_scopes": [
                    {"scope": "whatsapp_business_management", "target_ids": list(wabas)},
                    {"scope": "whatsapp_business_messaging", "target_ids": list(wabas)},
                ]}},
            )
        for waba, nums in wabas.items():
            if path.endswith(f"/{waba}/phone_numbers"):
                return httpx.Response(
                    200,
                    json={"data": [
                        {"id": pid, "display_phone_number": disp, "verified_name": f"Name {pid}"}
                        for pid, disp in nums
                    ]},
                )
            if path.endswith(f"/{waba}/subscribed_apps"):
                return httpx.Response(200, json={"success": True})
        for nums in wabas.values():
            for pid, disp in nums:
                if path.endswith(f"/{pid}"):
                    return httpx.Response(200, json={"display_phone_number": disp, "verified_name": f"Name {pid}"})
        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        partner_connect_service,
        "get_adapter",
        lambda channel_type="WHATSAPP": WhatsAppCloudAdapter(client=fake),
    )


# ── feature off ──────────────────────────────────────────────────────────────
def test_every_new_route_answers_503_until_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "omni_partner_wa_redirect_uri", "")
    hdr, ws = setup(client)
    calls = [
        ("POST", f"{P}/workspaces/{ws}/connect-sessions", {"returnUrl": RETURN}, hdr),
        ("GET", f"{P}/connect-sessions/any", None, hdr),
        ("POST", f"{P}/connect-sessions/any/complete", None, hdr),
        ("POST", f"{P}/connect-sessions/any/cancel", None, hdr),
        ("POST", CB, {"state": "x", "code": "y"}, {}),
    ]
    for method, url, body, headers in calls:
        res = client.request(method, url, json=body, headers=headers)
        assert res.status_code == 503 and res.json() == NOT_CONFIGURED, (url, res.text)


def test_real_mode_needs_every_meta_setting(client, real, monkeypatch):
    hdr, ws = setup(client)
    for name in ("meta_app_secret", "meta_es_config_id", "meta_es_dialog_version"):
        monkeypatch.setattr(settings, name, "")
        res = create(client, hdr, ws)
        assert res.status_code == 503 and res.json() == NOT_CONFIGURED, name
        monkeypatch.setattr(settings, name, {"meta_app_secret": "s", "meta_es_config_id": "c", "meta_es_dialog_version": "v25.0"}[name])
    assert create(client, hdr, ws).status_code == 201


# ── the local simulation: the whole loop without a Meta account ──────────────
def test_simulated_loop_creates_the_channel_only_at_complete(client, session_factory, sim):
    hdr, ws = setup(client)
    res = create(client, hdr, ws)
    assert res.status_code == 201, res.text
    body = res.json()
    sid = body["id"]
    assert body["workspaceId"] == ws and body["status"] == "OPEN" and body["expiresAt"]
    url = urlsplit(body["url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == REDIRECT_URI
    query = parse_qs(url.query)
    assert query["code"] == ["dev"] and len(query["state"][0]) >= 40

    got = client.get(f"{P}/connect-sessions/{sid}", headers=hdr).json()
    assert got["status"] == "OPEN" and got["channelIds"] == [] and got["errorCode"] is None

    cb = callback(client, query["state"][0], code="dev")
    assert cb.status_code == 200, cb.text
    redirect = urlsplit(cb.json()["redirect"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == RETURN.split("?")[0]
    params = parse_qs(redirect.query)
    assert params == {"tab": ["wa"], "session": [sid], "status": ["authorized"], "state": ["nonce-123"]}

    assert client.get(f"{P}/connect-sessions/{sid}", headers=hdr).json()["status"] == "AUTHORIZED"
    assert channels(client, hdr, ws) == []  # two-step finish: nothing yet

    done = client.post(f"{P}/connect-sessions/{sid}/complete", headers=hdr)
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["status"] == "COMPLETED" and len(out["channelIds"]) == 1 and out["completedAt"]
    assert [c["id"] for c in out["channels"]] == out["channelIds"]
    listed = channels(client, hdr, ws)
    assert [c["id"] for c in listed] == out["channelIds"]
    assert listed[0]["channelType"] == "WHATSAPP" and listed[0]["status"] == "ACTIVE"

    again = client.post(f"{P}/connect-sessions/{sid}/complete", headers=hdr)
    assert again.status_code == 200 and again.json()["channelIds"] == out["channelIds"]
    assert len(channels(client, hdr, ws)) == 1
    assert session_row(session_factory, sid).credentials_json is None


def test_each_simulated_connect_gets_its_own_number(client, sim):
    hdr, ws = setup(client)
    ws2 = workspace(client, hdr, "org-2")
    for w in (ws, ws2):
        res = create(client, hdr, w).json()
        assert callback(client, state_of(res["url"])).status_code == 200
        out = client.post(f"{P}/connect-sessions/{res['id']}/complete", headers=hdr).json()
        assert out["status"] == "COMPLETED", out
    assert len(channels(client, hdr, ws)) == 1 and len(channels(client, hdr, ws2)) == 1


def test_the_simulation_never_runs_with_a_meta_app_id(client, session_factory, real, monkeypatch):
    """A Meta app id configured: the URL is Meta's, and a dev token (the
    adapter's fallback when the secret is missing) is refused at callback."""
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
    from modules.omnichannel.services import partner_connect_service

    hdr, ws = setup(client)
    res = create(client, hdr, ws).json()
    assert res["url"].startswith("https://www.facebook.com/v25.0/dialog/oauth?")
    assert "code=" not in res["url"]

    class DevToken(WhatsAppCloudAdapter):
        def exchange_code(self, code, redirect_uri=None):
            return {"access_token": "dev-token-dev", "dev": True}

    monkeypatch.setattr(partner_connect_service, "get_adapter", lambda channel_type="WHATSAPP": DevToken())
    cb = callback(client, state_of(res["url"]), code="dev")
    assert cb.status_code == 200
    assert parse_qs(urlsplit(cb.json()["redirect"]).query)["status"] == ["failed"]
    row = session_row(session_factory, res["id"])
    assert row.status == "FAILED" and row.error_code == "code_exchange_failed" and row.credentials_json is None
    # And the adapter's fake number exists only while the app id is unset.
    assert WhatsAppCloudAdapter().list_onboarded_numbers({"access_token": "x", "dev": True}) == []


# ── real mode against a fake Meta Graph ──────────────────────────────────────
def test_real_flow_exchanges_with_the_configured_redirect_and_makes_one_channel_per_new_number(
    client, session_factory, real, monkeypatch, caplog
):
    caplog.set_level(logging.DEBUG)
    hdr, ws = setup(client)
    # One number is already live in another workspace: it is skipped.
    _seed_channel(session_factory, _default_workspace_id(session_factory), phone_number_id="pn-taken")
    seen = []
    graph(
        monkeypatch,
        {"waba-1": [("pn-a", "+60 11-000 0001"), ("pn-taken", "+60 11-000 0009")], "waba-2": [("pn-b", "+60 11-000 0002")]},
        record=seen,
    )
    res = create(client, hdr, ws)
    assert res.status_code == 201, res.text
    sid, url = res.json()["id"], res.json()["url"]
    q = parse_qs(urlsplit(url).query)
    assert q["client_id"] == ["test-app-id"] and q["config_id"] == ["test-config-id"]
    assert q["redirect_uri"] == ["https://chat.example/wa-callback"]
    assert q["response_type"] == ["code"] and q["override_default_response_type"] == ["true"]
    assert '"sessionInfoVersion":"3"' in q["extras"][0]
    state = q["state"][0]

    cb = client.post(CB, json={"state": state, "code": CODE, "redirect_uri": "https://evil.example/x"})
    assert cb.status_code == 200, cb.text
    exchange = [r for r in seen if r.url.path.endswith("/oauth/access_token")]
    assert len(exchange) == 1
    assert exchange[0].url.params["redirect_uri"] == "https://chat.example/wa-callback"
    row = session_row(session_factory, sid)
    assert row.status == "AUTHORIZED" and row.credentials_json and TOKEN not in row.credentials_json
    assert state not in (row.state_hash or "")

    done = client.post(f"{P}/connect-sessions/{sid}/complete", headers=hdr)
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["status"] == "COMPLETED" and len(out["channelIds"]) == 2
    listed = channels(client, hdr, ws)
    assert sorted(c["displayPhoneNumber"] for c in listed) == ["+60 11-000 0001", "+60 11-000 0002"]
    assert session_row(session_factory, sid).credentials_json is None

    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import decrypt_credentials

    db = session_factory()
    made = db.query(Channel).filter(Channel.id.in_(out["channelIds"])).all()
    assert {c.phone_number_id for c in made} == {"pn-a", "pn-b"}
    assert {c.waba_id for c in made} == {"waba-1", "waba-2"}
    assert all(decrypt_credentials(c.credentials_json) == {"access_token": TOKEN} for c in made)
    assert db.query(Channel).filter(Channel.phone_number_id == "pn-taken").count() == 1
    db.close()

    # No secret anywhere a caller or an operator can read.
    for text in (res.text, cb.text, done.text, client.get(f"{P}/connect-sessions/{sid}", headers=hdr).text, caplog.text):
        assert TOKEN not in text and CODE not in text
    for text in (cb.text, done.text, caplog.text):
        assert state not in text
    # The gateway activity log (it covers /api/v1/omnichannel/*) holds none of them.
    from app.models.integration_activity import IntegrationActivity

    db = session_factory()
    for act in db.query(IntegrationActivity).all():
        dumped = f"{act.request_summary_json} {act.response_summary_json} {act.error_message} {act.operation}"
        assert TOKEN not in dumped and CODE not in dumped and state not in dumped
    db.close()


def test_every_number_already_connected_fails_without_naming_a_tenant(client, session_factory, real, monkeypatch):
    hdr, ws = setup(client)
    _seed_channel(session_factory, _default_workspace_id(session_factory), phone_number_id="pn-only")
    graph(monkeypatch, {"waba-1": [("pn-only", "+60 11-000 0001")]})
    res = create(client, hdr, ws).json()
    callback(client, state_of(res["url"]), code=CODE)
    done = client.post(f"{P}/connect-sessions/{res['id']}/complete", headers=hdr)
    out = done.json()
    assert out["status"] == "FAILED" and out["errorCode"] == "phone_number_in_use"
    assert out["channelIds"] == [] and out["channels"] == []
    assert DEFAULT_TENANT_ID not in done.text and "tenant" not in done.text.lower()


def test_no_number_on_the_account_fails(client, real, monkeypatch):
    hdr, ws = setup(client)
    graph(monkeypatch, {})
    res = create(client, hdr, ws).json()
    callback(client, state_of(res["url"]), code=CODE)
    out = client.post(f"{P}/connect-sessions/{res['id']}/complete", headers=hdr).json()
    assert out["status"] == "FAILED" and out["errorCode"] == "no_number_found"


def test_a_failed_code_exchange_redirects_with_failed(client, session_factory, real, monkeypatch):
    hdr, ws = setup(client)
    graph(monkeypatch, {}, exchange_status=400)
    res = create(client, hdr, ws).json()
    cb = callback(client, state_of(res["url"]), code=CODE)
    assert cb.status_code == 200
    assert parse_qs(urlsplit(cb.json()["redirect"]).query)["status"] == ["failed"]
    got = client.get(f"{P}/connect-sessions/{res['id']}", headers=hdr).json()
    assert got["status"] == "FAILED" and got["errorCode"] == "code_exchange_failed"


def test_meta_error_redirects_with_cancelled(client, sim):
    hdr, ws = setup(client)
    res = create(client, hdr, ws).json()
    cb = callback(client, state_of(res["url"]), code=None, error="access_denied")
    assert cb.status_code == 200
    assert parse_qs(urlsplit(cb.json()["redirect"]).query)["status"] == ["cancelled"]
    assert client.get(f"{P}/connect-sessions/{res['id']}", headers=hdr).json()["status"] == "CANCELLED"


# ── single use, expiry ───────────────────────────────────────────────────────
def test_the_state_works_once(client, sim):
    hdr, ws = setup(client)
    res = create(client, hdr, ws).json()
    state = state_of(res["url"])
    assert callback(client, state).status_code == 200
    second = callback(client, state)
    assert second.status_code == 404 and second.json() == SESSION_NOT_FOUND
    unknown = callback(client, "not-a-real-state")
    assert unknown.status_code == 404 and unknown.json() == SESSION_NOT_FOUND


def test_a_concurrent_second_claim_loses(client, sim, monkeypatch):
    """Both callbacks read the session as OPEN; only one conditional UPDATE wins."""
    from modules.omnichannel.repositories.partner_connect_session_repository import (
        PartnerConnectSessionRepository,
    )

    hdr, ws = setup(client)
    res = create(client, hdr, ws).json()
    state = state_of(res["url"])
    assert callback(client, state).status_code == 200
    real_get = PartnerConnectSessionRepository.get_by_state_hash

    def stale_read(self, h):
        row = real_get(self, h)
        if row is not None:
            self.db.expunge(row)
            row.status, row.claimed_at = "OPEN", None  # what a racing request saw
        return row

    monkeypatch.setattr(PartnerConnectSessionRepository, "get_by_state_hash", stale_read)
    assert callback(client, state).json() == SESSION_NOT_FOUND


def test_an_expired_session_cannot_be_used(client, session_factory, sim):
    hdr, ws = setup(client)
    res = create(client, hdr, ws).json()
    update_row(session_factory, res["id"], expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert callback(client, state_of(res["url"])).json() == SESSION_NOT_FOUND
    got = client.get(f"{P}/connect-sessions/{res['id']}", headers=hdr).json()
    assert got["status"] == "EXPIRED"
    done = client.post(f"{P}/connect-sessions/{res['id']}/complete", headers=hdr)
    assert done.status_code == 409 and done.json()["error"]["code"] == "connect_session_not_authorized"


def test_an_authorized_session_expires_and_drops_its_token(client, session_factory, sim):
    hdr, ws = setup(client)
    res = create(client, hdr, ws).json()
    callback(client, state_of(res["url"]))
    update_row(session_factory, res["id"], expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert client.post(f"{P}/connect-sessions/{res['id']}/complete", headers=hdr).status_code == 409
    row = session_row(session_factory, res["id"])
    assert row.status == "EXPIRED" and row.credentials_json is None


def test_ttl_setting_sets_the_expiry(client, sim, monkeypatch):
    monkeypatch.setattr(settings, "partner_connect_session_ttl_minutes", 5)
    hdr, ws = setup(client)
    body = create(client, hdr, ws).json()
    expires = datetime.fromisoformat(body["expiresAt"].replace("Z", "+00:00"))
    left = expires - datetime.now(timezone.utc)
    assert timedelta(minutes=4) < left <= timedelta(minutes=5)


# ── complete / cancel order ──────────────────────────────────────────────────
def test_complete_before_authorized_is_refused(client, sim):
    hdr, ws = setup(client)
    res = create(client, hdr, ws).json()
    done = client.post(f"{P}/connect-sessions/{res['id']}/complete", headers=hdr)
    assert done.status_code == 409
    assert done.json()["error"]["code"] == "connect_session_not_authorized"
    assert client.get(f"{P}/connect-sessions/{res['id']}", headers=hdr).json()["status"] == "OPEN"


def test_cancel_ends_the_session_and_is_idempotent(client, session_factory, sim):
    hdr, ws = setup(client)
    res = create(client, hdr, ws).json()
    first = client.post(f"{P}/connect-sessions/{res['id']}/cancel", headers=hdr)
    assert first.status_code == 200 and first.json()["status"] == "CANCELLED"
    again = client.post(f"{P}/connect-sessions/{res['id']}/cancel", headers=hdr)
    assert again.status_code == 200 and again.json()["status"] == "CANCELLED"
    assert callback(client, state_of(res["url"])).json() == SESSION_NOT_FOUND
    assert client.post(f"{P}/connect-sessions/{res['id']}/complete", headers=hdr).status_code == 409

    # Cancelling an AUTHORIZED one drops its token; a COMPLETED one stays completed.
    res2 = create(client, hdr, ws).json()
    callback(client, state_of(res2["url"]))
    client.post(f"{P}/connect-sessions/{res2['id']}/cancel", headers=hdr)
    assert session_row(session_factory, res2["id"]).credentials_json is None
    res3 = create(client, hdr, ws).json()
    callback(client, state_of(res3["url"]))
    client.post(f"{P}/connect-sessions/{res3['id']}/complete", headers=hdr)
    after = client.post(f"{P}/connect-sessions/{res3['id']}/cancel", headers=hdr).json()
    assert after["status"] == "COMPLETED" and len(after["channelIds"]) == 1


# ── scope: tenant, client app, status ────────────────────────────────────────
def _session_routes(sid):
    return [
        ("GET", f"{P}/connect-sessions/{sid}"),
        ("POST", f"{P}/connect-sessions/{sid}/complete"),
        ("POST", f"{P}/connect-sessions/{sid}/cancel"),
    ]


def test_another_tenants_key_gets_the_uniform_404(client, session_factory, sim):
    hdr, ws = setup(client)
    sid = create(client, hdr, ws).json()["id"]
    _, admin_b = other_tenant(client, session_factory, slug="connect-b")
    hdr_b = key(client, headers=admin_b, name="B")
    for method, url in _session_routes(sid) + _session_routes("no-such-id"):
        res = client.request(method, url, headers=hdr_b)
        assert res.status_code == 404 and res.json() == SESSION_NOT_FOUND, url
    cross = create(client, hdr_b, ws)
    assert cross.status_code == 404 and cross.json()["error"]["code"] == "workspace_not_found"
    assert client.get(f"{P}/connect-sessions/{sid}", headers=hdr).json()["status"] == "OPEN"


def test_another_client_app_of_the_same_tenant_gets_the_uniform_404(client, session_factory, sim):
    hdr_eco = key(client, app_id=_new_app(session_factory, "Ecohub"), name="Eco")
    hdr_fuji = key(client, app_id=_new_app(session_factory, "MyFuji Platform"), name="Fuji")
    ws_eco = workspace(client, hdr_eco, "org-eco")
    sid = create(client, hdr_eco, ws_eco).json()["id"]
    for method, url in _session_routes(sid):
        res = client.request(method, url, headers=hdr_fuji)
        assert res.status_code == 404 and res.json() == SESSION_NOT_FOUND, url
    assert create(client, hdr_fuji, ws_eco).json()["error"]["code"] == "workspace_not_found"
    # A second key of the SAME client app may finish it (key rotation).
    hdr_eco2 = key(client, app_id=session_row(session_factory, sid).client_app_id, name="Eco 2")
    assert client.get(f"{P}/connect-sessions/{sid}", headers=hdr_eco2).status_code == 200


def test_a_disabled_client_app_is_refused_on_partner_routes_and_at_the_callback(client, session_factory, sim):
    from modules.omnichannel.models import ClientApp

    hdr, ws = setup(client)
    res = create(client, hdr, ws).json()
    app_id = session_row(session_factory, res["id"]).client_app_id
    db = session_factory()
    db.query(ClientApp).filter(ClientApp.id == app_id).update({"status": "DISABLED"})
    db.commit()
    db.close()
    for method, url in _session_routes(res["id"]) + [("POST", f"{P}/workspaces/{ws}/connect-sessions")]:
        out = client.request(method, url, headers=hdr, json={"returnUrl": RETURN})
        assert out.status_code == 403 and out.json()["error"]["code"] == "client_app_disabled", url
    assert callback(client, state_of(res["url"])).json() == SESSION_NOT_FOUND
    # Nothing was claimed: re-enabled, the same link still works.
    db = session_factory()
    db.query(ClientApp).filter(ClientApp.id == app_id).update({"status": "ACTIVE"})
    db.commit()
    db.close()
    assert callback(client, state_of(res["url"])).status_code == 200


def test_a_trashed_workspace_ends_the_flow(client, session_factory, sim):
    from modules.omnichannel.models import Workspace

    hdr, ws = setup(client)
    res = create(client, hdr, ws).json()
    callback(client, state_of(res["url"]))
    db = session_factory()
    db.query(Workspace).filter(Workspace.id == ws).update({"is_trashed": True})
    db.commit()
    db.close()
    done = client.post(f"{P}/connect-sessions/{res['id']}/complete", headers=hdr)
    assert done.status_code == 404 and done.json() == SESSION_NOT_FOUND


def test_the_callback_throttles_repeated_misses(client, sim, monkeypatch):
    monkeypatch.setattr(settings, "throttle_embed_max_fails", 3)
    for _ in range(3):
        assert callback(client, "guess").status_code == 404
    res = callback(client, "guess")
    assert res.status_code == 429 and res.headers.get("Retry-After")


# ── return URL allow-list (decision 8: on the partner key) ───────────────────
@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/return",
        "https://app.ecohub.example:8443/return",
        "http://app.ecohub.example/return",
        "https://app.ecohub.example.evil.example/return",
        "https://app.ecohub.example@evil.example/return",
        "https://user:pw@app.ecohub.example/return",
        "https://app.ecohub.example/return#frag",
        "/settings/messaging",
        "javascript:alert(1)",
        "https://app.ecohub.example/ret urn",
    ],
)
def test_a_return_url_outside_the_keys_allow_list_is_refused(client, sim, url):
    hdr, ws = setup(client)
    res = create(client, hdr, ws, return_url=url)
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_return_url"


def test_a_key_with_no_allowed_origins_refuses_every_return_url(client, sim):
    hdr = key(client, origins=())
    ws = workspace(client, hdr)
    res = create(client, hdr, ws)
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_return_url"


def test_the_allow_list_is_the_calling_keys_own(client, session_factory, sim):
    hdr, ws = setup(client)
    other = key(client, origins=("https://other.example",), name="Other key")
    res = create(client, other, ws)
    assert res.status_code == 422
    ok = create(client, other, ws, return_url="https://other.example/back")
    assert ok.status_code == 201
    redirect = callback(client, state_of(ok.json()["url"])).json()["redirect"]
    assert redirect.startswith("https://other.example/back?session=")


def test_the_redirect_has_no_state_when_none_was_given(client, sim):
    hdr, ws = setup(client)
    res = create(client, hdr, ws, return_url=f"{ORIGIN}/r", client_state=None).json()
    redirect = callback(client, state_of(res["url"])).json()["redirect"]
    assert parse_qs(urlsplit(redirect).query) == {"session": [res["id"]], "status": ["authorized"]}


# ── the existing dashboard onboarding path is unchanged ──────────────────────
def test_dashboard_onboarding_still_connects_the_first_number_only(client, session_factory, real, monkeypatch):
    """With the new feature switched on, the dashboard path still runs
    OnboardingService.complete as before: the exchange uses the redirect URI the
    dashboard sends, and only the first number of the first WABA is connected."""
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
    from modules.omnichannel.services import onboarding_service

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "perm-token"})
        if path.endswith("/debug_token"):
            return httpx.Response(200, json={"data": {"granular_scopes": [
                {"scope": "whatsapp_business_management", "target_ids": ["waba-d"]}]}})
        if path.endswith("/waba-d/phone_numbers"):
            return httpx.Response(200, json={"data": [
                {"id": "pn-d1", "display_phone_number": "+60 1"}, {"id": "pn-d2", "display_phone_number": "+60 2"}]})
        return httpx.Response(200, json={})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(onboarding_service, "get_adapter", lambda channel_type="WHATSAPP": WhatsAppCloudAdapter(client=fake))
    res = client.post(
        "/omnichannel/onboarding/oauth-callback",
        headers=_auth(client),
        json={"workspaceId": _default_workspace_id(session_factory), "code": "c", "redirectUri": "https://dash.example/wa-callback"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["phoneNumberId"] == "pn-d1"
    exchange = [r for r in seen if r.url.path.endswith("/oauth/access_token")][0]
    assert exchange.url.params["redirect_uri"] == "https://dash.example/wa-callback"
    from modules.omnichannel.models import Channel

    db = session_factory()
    assert db.query(Channel).filter(Channel.phone_number_id == "pn-d2").count() == 0
    db.close()


# ── schema: migration chain, model and Alembic agree ─────────────────────────
def test_connect_session_migration_is_the_single_head():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(VERSIONS.parent))
    assert script.get_heads() == ["0033_omni_connect_sessions"]
    rev = script.get_revision("0033_omni_connect_sessions")
    assert rev.down_revision == "0032_omni_client_apps"
    assert len(rev.revision) <= 32


def test_migration_creates_the_models_columns_indexes_and_foreign_keys(monkeypatch):
    import importlib.util

    import sqlalchemy as sa

    from modules.omnichannel.models import PartnerConnectSession

    spec = importlib.util.spec_from_file_location("omni_0033", VERSIONS / "0033_omni_connect_sessions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    created = {}
    indexes = {}

    class FakeInspector:
        def get_table_names(self, schema=None):
            return []

    monkeypatch.setattr(mod.op, "get_bind", lambda: object(), raising=False)
    monkeypatch.setattr(mod.sa, "inspect", lambda bind: FakeInspector())
    monkeypatch.setattr(mod.op, "create_table", lambda name, *items, **kw: created.update(name=name, items=items), raising=False)
    monkeypatch.setattr(
        mod.op, "create_index",
        lambda name, table, cols, unique=False, **kw: indexes.update({name: (tuple(cols), unique)}),
        raising=False,
    )
    mod.upgrade()

    table = PartnerConnectSession.__table__
    assert created["name"] == table.name
    cols = {c.name: c for c in created["items"] if isinstance(c, sa.Column)}
    assert set(cols) == set(table.columns.keys())
    for name, col in cols.items():
        assert col.nullable == table.columns[name].nullable, name
        assert {fk.target_fullname.split(".")[-2] for fk in col.foreign_keys} == {
            fk.target_fullname.split(".")[-2] for fk in table.columns[name].foreign_keys
        }, name
    model_indexes = {
        ix.name: (tuple(c.name for c in ix.columns), bool(ix.unique)) for ix in table.indexes
    }
    assert indexes == model_indexes
    checks = [c for c in created["items"] if isinstance(c, sa.CheckConstraint)]
    model_checks = [c for c in table.constraints if isinstance(c, sa.CheckConstraint)]
    assert [str(c.sqltext) for c in checks] == [str(c.sqltext) for c in model_checks]


def test_uninstall_removes_a_tenants_sessions_only(client, session_factory, sim):
    from app.services.app_store_service import AppStoreService
    from modules.omnichannel.models import OmniBase, PartnerConnectSession

    tables = [t.name for t in OmniBase.metadata.sorted_tables]
    assert tables.index("partner_connect_sessions") > tables.index("workspaces")
    assert tables.index("partner_connect_sessions") > tables.index("client_apps")
    hdr, ws = setup(client)
    create(client, hdr, ws)
    tid, admin_b = other_tenant(client, session_factory, slug="connect-uninstall")
    hdr_b = key(client, headers=admin_b, name="B")
    create(client, hdr_b, workspace(client, hdr_b, "org-b"))
    db = session_factory()
    AppStoreService(db).uninstall(tid, "omnichannel", "omnichannel")
    db.commit()
    assert db.query(PartnerConnectSession).filter_by(tenant_id=tid).count() == 0
    assert db.query(PartnerConnectSession).filter_by(tenant_id=DEFAULT_TENANT_ID).count() == 1
    db.close()
