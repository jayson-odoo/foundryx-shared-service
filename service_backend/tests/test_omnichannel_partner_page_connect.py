"""wp-6 - partner hosted connect for a Facebook Page (channelType FACEBOOK).

The WhatsApp partner flow (``test_omnichannel_connect_sessions.py``) with a
Page picker between the Meta sign-in and the return: create, callback answers
the Page list and a single-use pick token, page-select authorizes (or
cancels), complete creates a Messenger channel plus an Instagram channel for
the Page's linked professional account, subscribes the Page once, and the
channels then carry messages through the existing gateway and consumer
webhooks; disconnect is the WhatsApp route. Meta Graph is mocked; fake values
only.
"""
import logging
import time
from urllib.parse import parse_qs, urlsplit

import fakeredis
import httpx
import pytest

from app.config import settings
from modules.omnichannel.services import idempotency, realtime
from tests.test_omnichannel_channels_instagram import _ig_payload
from tests.test_omnichannel_channels_messenger import _messenger_payload, _process
from tests.test_omnichannel_connect_sessions import (
    CB,
    NOT_CONFIGURED,
    ORIGIN,
    P,
    REDIRECT_URI,
    SESSION_NOT_FOUND,
    callback,
    channels,
    key,
    session_row,
    state_of,
    workspace,
)

SELECT = "/api/v1/omnichannel/connect/page-select"
RETURN = f"{ORIGIN}/settings/messaging/meta/return?tab=meta"
USER_TOKEN = "EAAG-user-short-0001"
LONG_TOKEN = "EAAG-user-long-0001"
PAGE_TOKEN = "EAAG-page-token-0001"
CODE = "meta-auth-code-0002"


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


@pytest.fixture(autouse=True)
def _fake_realtime():
    realtime.set_client(fakeredis.FakeRedis(decode_responses=True))
    yield
    realtime.set_client(None)


@pytest.fixture
def sim(monkeypatch):
    monkeypatch.setattr(settings, "omni_partner_wa_redirect_uri", REDIRECT_URI)
    monkeypatch.setattr(settings, "meta_app_id", "")
    monkeypatch.setattr(settings, "meta_app_secret", "")
    monkeypatch.setattr(settings, "meta_es_dialog_version", "")


@pytest.fixture
def real(monkeypatch):
    monkeypatch.setattr(settings, "omni_partner_wa_redirect_uri", "https://chat.example/wa-callback")
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")
    monkeypatch.setattr(settings, "meta_es_config_id", "test-wa-config")
    monkeypatch.setattr(settings, "omni_partner_meta_config_id", "test-page-config")
    monkeypatch.setattr(settings, "meta_es_dialog_version", "v25.0")


def graph(monkeypatch, pages, *, record=None, exchange_status=200, subscribe_status=200):
    """A fake Meta Graph for Facebook Login: code exchange, long-lived
    exchange, ``/me/accounts`` answering ``pages``, Page subscription."""
    from modules.omnichannel.adapters.messenger import MessengerAdapter
    from modules.omnichannel.services import partner_connect_service

    def handler(request: httpx.Request) -> httpx.Response:
        if record is not None:
            record.append(request)
        path = request.url.path
        params = dict(request.url.params)
        if path.endswith("/oauth/access_token"):
            if exchange_status != 200:
                return httpx.Response(exchange_status, json={"error": {"message": "bad code"}})
            if params.get("grant_type") == "fb_exchange_token":
                return httpx.Response(200, json={"access_token": LONG_TOKEN})
            return httpx.Response(200, json={"access_token": USER_TOKEN})
        if path.endswith("/me/accounts"):
            assert params.get("access_token") == LONG_TOKEN
            return httpx.Response(200, json={"data": pages})
        if path.endswith("/subscribed_apps"):
            if request.method == "GET":
                return httpx.Response(200, json={"data": []})
            return httpx.Response(subscribe_status, json={"success": subscribe_status == 200})
        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        partner_connect_service,
        "get_channel_adapter",
        lambda channel_type="FACEBOOK": MessengerAdapter(client=fake),
    )


def page(pid="109001", name="Acme Homes", ig=("179001", "acme.homes")):
    out = {"id": pid, "name": name, "access_token": PAGE_TOKEN}
    if ig:
        out["instagram_business_account"] = {"id": ig[0], "username": ig[1]}
    return out


def setup(client, ext="org-1"):
    hdr = key(client)
    return hdr, workspace(client, hdr, ext)


def create(client, hdr, ws, return_url=RETURN, client_state="nonce-page"):
    body = {"channelType": "FACEBOOK", "returnUrl": return_url}
    if client_state is not None:
        body["clientState"] = client_state
    return client.post(f"{P}/workspaces/{ws}/connect-sessions", json=body, headers=hdr)


def signed_in(client, hdr, ws, code="dev"):
    """Create a session and run the callback; returns (session id, picker)."""
    res = create(client, hdr, ws)
    assert res.status_code == 201, res.text
    sid = res.json()["id"]
    cb = callback(client, state_of(res.json()["url"]), code=code)
    assert cb.status_code == 200, cb.text
    body = cb.json()
    assert "redirect" not in body
    return sid, body["pagePicker"]


def select(client, pick_token, page_id):
    body = {"pickToken": pick_token}
    if page_id is not None:
        body["pageId"] = page_id
    return client.post(SELECT, json=body)


def query(redirect):
    return parse_qs(urlsplit(redirect).query)


def complete(client, hdr, sid):
    return client.post(f"{P}/connect-sessions/{sid}/complete", headers=hdr)


def connect_page(client, hdr, ws, page_id="pg-701"):
    sid, picker = signed_in(client, hdr, ws)
    sel = select(client, picker["pickToken"], page_id)
    assert sel.status_code == 200, sel.text
    res = complete(client, hdr, sid)
    assert res.status_code == 200, res.text
    return res.json()


# ── create ───────────────────────────────────────────────────────────────────
def test_create_page_session_in_real_mode_builds_the_facebook_login_dialog(client, real):
    hdr, ws = setup(client)
    res = create(client, hdr, ws)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "OPEN" and body["workspaceId"] == ws
    url = urlsplit(body["url"])
    q = parse_qs(url.query)
    assert url.netloc == "www.facebook.com" and url.path == "/v25.0/dialog/oauth"
    assert q["client_id"] == ["test-app-id"]
    assert q["config_id"] == ["test-page-config"]
    assert q["redirect_uri"] == ["https://chat.example/wa-callback"]
    assert q["response_type"] == ["code"]
    assert "extras" not in q
    got = client.get(f"{P}/connect-sessions/{body['id']}", headers=hdr).json()
    assert got["channelType"] == "FACEBOOK" and got["status"] == "OPEN"


def test_page_connect_needs_its_own_config_id_while_whatsapp_keeps_working(client, real, monkeypatch):
    hdr, ws = setup(client)
    monkeypatch.setattr(settings, "omni_partner_meta_config_id", "")
    res = create(client, hdr, ws)
    assert res.status_code == 503 and res.json() == NOT_CONFIGURED
    wa = client.post(
        f"{P}/workspaces/{ws}/connect-sessions",
        json={"channelType": "WHATSAPP", "returnUrl": RETURN},
        headers=hdr,
    )
    assert wa.status_code == 201, wa.text
    assert parse_qs(urlsplit(wa.json()["url"]).query)["config_id"] == ["test-wa-config"]
    # And the reverse: WhatsApp unconfigured does not stop a Page connect.
    monkeypatch.setattr(settings, "omni_partner_meta_config_id", "test-page-config")
    monkeypatch.setattr(settings, "meta_es_config_id", "")
    assert create(client, hdr, ws).status_code == 201


def test_unknown_channel_type_is_refused(client, sim):
    hdr, ws = setup(client)
    res = client.post(
        f"{P}/workspaces/{ws}/connect-sessions",
        json={"channelType": "INSTAGRAM", "returnUrl": RETURN},
        headers=hdr,
    )
    assert res.status_code == 422


# ── the whole loop, local simulation ─────────────────────────────────────────
def test_simulated_page_connect_creates_messenger_and_instagram_channels(client, sim):
    hdr, ws = setup(client)
    sid, picker = signed_in(client, hdr, ws)
    assert [p["id"] for p in picker["pages"]] == ["pg-701", "pg-702", "pg-703"]
    assert picker["pages"][0] == {
        "id": "pg-701", "name": "Foundryx Events Co.", "igUsername": "foundryx.events", "connected": False,
    }
    # Waiting on the Page list: still OPEN, nothing created.
    assert client.get(f"{P}/connect-sessions/{sid}", headers=hdr).json()["status"] == "OPEN"
    assert complete(client, hdr, sid).status_code == 409

    sel = select(client, picker["pickToken"], "pg-701")
    assert sel.status_code == 200, sel.text
    q = query(sel.json()["redirect"])
    assert q["session"] == [sid] and q["status"] == ["authorized"] and q["state"] == ["nonce-page"]
    assert q["tab"] == ["meta"]
    assert client.get(f"{P}/connect-sessions/{sid}", headers=hdr).json()["status"] == "AUTHORIZED"

    done = complete(client, hdr, sid)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "COMPLETED" and body["channelType"] == "FACEBOOK"
    assert len(body["channelIds"]) == 2
    kinds = {c["channelType"]: c for c in body["channels"]}
    assert set(kinds) == {"FACEBOOK", "INSTAGRAM"}
    assert kinds["FACEBOOK"]["name"] == "Foundryx Events Co."
    assert kinds["INSTAGRAM"]["name"] == "foundryx.events"
    assert kinds["FACEBOOK"]["displayPhoneNumber"] is None
    listed = channels(client, hdr, ws)
    assert {c["id"] for c in listed} == set(body["channelIds"])

    # Idempotent: the same result, nothing new.
    again = complete(client, hdr, sid).json()
    assert again["channelIds"] == body["channelIds"]
    assert len(channels(client, hdr, ws)) == 2


def test_callback_state_and_pick_token_each_work_once(client, sim):
    hdr, ws = setup(client)
    res = create(client, hdr, ws)
    state = state_of(res.json()["url"])
    picker = callback(client, state).json()["pagePicker"]
    assert callback(client, state).json() == SESSION_NOT_FOUND
    assert select(client, picker["pickToken"], "pg-701").status_code == 200
    again = select(client, picker["pickToken"], "pg-702")
    assert again.status_code == 404 and again.json() == SESSION_NOT_FOUND
    assert select(client, "never-issued", "pg-701").json() == SESSION_NOT_FOUND


def test_a_page_that_was_not_offered_is_refused_and_the_token_stays_usable(client, sim):
    hdr, ws = setup(client)
    sid, picker = signed_in(client, hdr, ws)
    bad = select(client, picker["pickToken"], "pg-someone-else")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_page"
    assert select(client, picker["pickToken"], "pg-702").status_code == 200


def test_cancel_on_the_page_list_ends_the_session(client, sim, session_factory):
    hdr, ws = setup(client)
    sid, picker = signed_in(client, hdr, ws)
    sel = select(client, picker["pickToken"], None)
    assert sel.status_code == 200
    assert query(sel.json()["redirect"])["status"] == ["cancelled"]
    row = session_row(session_factory, sid)
    assert row.status == "CANCELLED" and row.credentials_json is None
    assert complete(client, hdr, sid).status_code == 409


def test_partner_cancel_while_on_the_page_list_spends_the_pick_token(client, sim):
    hdr, ws = setup(client)
    sid, picker = signed_in(client, hdr, ws)
    assert client.post(f"{P}/connect-sessions/{sid}/cancel", headers=hdr).json()["status"] == "CANCELLED"
    assert select(client, picker["pickToken"], "pg-701").json() == SESSION_NOT_FOUND


def test_an_expired_session_refuses_the_pick(client, sim, session_factory):
    from datetime import datetime, timedelta, timezone

    from tests.test_omnichannel_connect_sessions import update_row

    hdr, ws = setup(client)
    sid, picker = signed_in(client, hdr, ws)
    update_row(session_factory, sid, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert select(client, picker["pickToken"], "pg-701").json() == SESSION_NOT_FOUND
    assert session_row(session_factory, sid).status == "EXPIRED"


def test_whatsapp_callback_answer_is_unchanged(client, sim):
    hdr, ws = setup(client)
    res = client.post(
        f"{P}/workspaces/{ws}/connect-sessions",
        json={"channelType": "WHATSAPP", "returnUrl": RETURN},
        headers=hdr,
    )
    cb = callback(client, state_of(res.json()["url"]))
    assert list(cb.json()) == ["redirect"]


# ── real mode, mocked Graph ──────────────────────────────────────────────────
def test_real_page_connect_uses_the_page_token_and_subscribes_the_page_once(
    client, real, monkeypatch, session_factory, caplog
):
    record = []
    graph(monkeypatch, [page(), page("109002", "Other Page", ig=None)], record=record)
    hdr, ws = setup(client)
    caplog.set_level(logging.DEBUG)
    sid, picker = signed_in(client, hdr, ws, code=CODE)
    assert picker["pages"] == [
        {"id": "109001", "name": "Acme Homes", "igUsername": "acme.homes", "connected": False},
        {"id": "109002", "name": "Other Page", "connected": False},
    ]
    exchange = record[0]
    assert dict(exchange.url.params)["redirect_uri"] == "https://chat.example/wa-callback"
    assert dict(exchange.url.params)["code"] == CODE
    assert select(client, picker["pickToken"], "109001").status_code == 200

    record.clear()
    body = complete(client, hdr, sid).json()
    assert body["status"] == "COMPLETED"
    assert {c["channelType"]: c["name"] for c in body["channels"]} == {
        "FACEBOOK": "Acme Homes",
        "INSTAGRAM": "acme.homes",
    }
    posts = [r for r in record if r.method == "POST" and r.url.path.endswith("/subscribed_apps")]
    assert len(posts) == 1
    assert posts[0].url.path.endswith("/109001/subscribed_apps")
    fields = set(dict(posts[0].url.params)["subscribed_fields"].split(","))
    assert {"messages", "messaging_postbacks", "message_reads", "message_deliveries", "message_reactions"} <= fields
    assert posts[0].headers["Authorization"] == f"Bearer {PAGE_TOKEN}"

    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import decrypt_credentials

    db = session_factory()
    rows = db.query(Channel).filter(Channel.id.in_(body["channelIds"])).all()
    by_type = {c.channel_type: c for c in rows}
    assert by_type["FACEBOOK"].external_account_id == "109001"
    assert by_type["INSTAGRAM"].external_account_id == "179001"
    for c in rows:
        assert decrypt_credentials(c.credentials_json) == {"access_token": PAGE_TOKEN}
        assert c.workspace_id == ws
    db.close()

    row = session_row(session_factory, sid)
    assert row.credentials_json is None
    texts = [str(v) for v in (row.state_hash, row.return_url, row.error_code)] + [caplog.text]
    for secret in (USER_TOKEN, LONG_TOKEN, PAGE_TOKEN, CODE):
        assert all(secret not in t for t in texts)


def test_page_without_instagram_gives_messenger_only(client, real, monkeypatch):
    graph(monkeypatch, [page(ig=None)])
    hdr, ws = setup(client)
    sid, picker = signed_in(client, hdr, ws, code=CODE)
    select(client, picker["pickToken"], "109001")
    body = complete(client, hdr, sid).json()
    assert body["status"] == "COMPLETED"
    assert [c["channelType"] for c in body["channels"]] == ["FACEBOOK"]


def test_subscription_failure_does_not_block_the_connect(client, real, monkeypatch):
    graph(monkeypatch, [page()], subscribe_status=500)
    hdr, ws = setup(client)
    sid, picker = signed_in(client, hdr, ws, code=CODE)
    select(client, picker["pickToken"], "109001")
    assert complete(client, hdr, sid).json()["status"] == "COMPLETED"


def test_failed_code_exchange_redirects_failed(client, real, monkeypatch, session_factory):
    graph(monkeypatch, [page()], exchange_status=400)
    hdr, ws = setup(client)
    res = create(client, hdr, ws)
    sid = res.json()["id"]
    cb = callback(client, state_of(res.json()["url"]), code=CODE)
    assert query(cb.json()["redirect"])["status"] == ["failed"]
    row = session_row(session_factory, sid)
    assert row.status == "FAILED" and row.error_code == "code_exchange_failed"


def test_no_page_redirects_failed_no_page_found(client, real, monkeypatch, session_factory):
    graph(monkeypatch, [])
    hdr, ws = setup(client)
    res = create(client, hdr, ws)
    cb = callback(client, state_of(res.json()["url"]), code=CODE)
    assert query(cb.json()["redirect"])["status"] == ["failed"]
    got = client.get(f"{P}/connect-sessions/{res.json()['id']}", headers=hdr).json()
    assert got["status"] == "FAILED" and got["errorCode"] == "no_page_found"


def test_page_gone_before_complete_fails_page_not_found(client, real, monkeypatch):
    pages = [page()]
    graph(monkeypatch, pages)
    hdr, ws = setup(client)
    sid, picker = signed_in(client, hdr, ws, code=CODE)
    select(client, picker["pickToken"], "109001")
    pages.clear()
    body = complete(client, hdr, sid).json()
    assert body["status"] == "FAILED" and body["errorCode"] == "page_not_found"


def test_dev_credentials_never_used_with_a_meta_app_configured(client, real, monkeypatch, session_factory):
    from modules.omnichannel.services import partner_connect_service

    class DevAdapter:
        def exchange_code(self, code, redirect_uri=None):
            return {"access_token": "dev-token", "dev": True}

        def exchange_long_lived_token(self, credentials):
            return credentials

        def list_pages(self, credentials):
            return [page()]

    monkeypatch.setattr(partner_connect_service, "get_channel_adapter", lambda t="FACEBOOK": DevAdapter())
    hdr, ws = setup(client)
    res = create(client, hdr, ws)
    cb = callback(client, state_of(res.json()["url"]), code=CODE)
    assert query(cb.json()["redirect"])["status"] == ["failed"]
    assert session_row(session_factory, res.json()["id"]).error_code == "code_exchange_failed"


# ── one Page, one owner ──────────────────────────────────────────────────────
def test_page_already_connected_elsewhere_is_skipped_and_its_instagram_still_connects(client, sim):
    hdr, ws1 = setup(client, "org-1")
    first = connect_page(client, hdr, ws1)
    fb_first = next(c["id"] for c in first["channels"] if c["channelType"] == "FACEBOOK")
    ig_first = next(c["id"] for c in first["channels"] if c["channelType"] == "INSTAGRAM")
    # The Instagram account is freed; the Page stays connected in org-1.
    client.post(f"{P}/workspaces/{ws1}/channels/{ig_first}/disconnect", headers=hdr)

    ws2 = workspace(client, hdr, "org-2")
    sid, picker = signed_in(client, hdr, ws2)
    assert picker["pages"][0]["connected"] is False  # the Instagram account is free
    select(client, picker["pickToken"], "pg-701")
    body = complete(client, hdr, sid).json()
    assert body["status"] == "COMPLETED"
    assert [c["channelType"] for c in body["channels"]] == ["INSTAGRAM"]
    assert [c["id"] for c in channels(client, hdr, ws1)] == [fb_first]


def test_page_and_instagram_both_connected_fails_page_in_use(client, sim):
    hdr, ws1 = setup(client, "org-1")
    connect_page(client, hdr, ws1)
    ws2 = workspace(client, hdr, "org-2")
    sid, picker = signed_in(client, hdr, ws2)
    assert picker["pages"][0]["connected"] is True
    assert picker["pages"][1]["connected"] is False
    select(client, picker["pickToken"], "pg-701")
    body = complete(client, hdr, sid).json()
    assert body["status"] == "FAILED" and body["errorCode"] == "page_in_use"
    assert body["channels"] == [] and channels(client, hdr, ws2) == []


# ── disconnect ───────────────────────────────────────────────────────────────
def test_disconnect_and_reconnect_a_page(client, sim):
    hdr, ws = setup(client)
    first = connect_page(client, hdr, ws)
    for ch in first["channels"]:
        res = client.post(f"{P}/workspaces/{ws}/channels/{ch['id']}/disconnect", headers=hdr)
        assert res.status_code == 200, res.text
    assert channels(client, hdr, ws) == []
    again = connect_page(client, hdr, ws)
    assert again["status"] == "COMPLETED" and len(again["channels"]) == 2


# ── messages reach the partner through the existing gateway ──────────────────
def test_messages_on_the_connected_page_flow_through_the_workspace_key(client, sim, session_factory):
    from modules.omnichannel.models import WebhookDelivery

    hdr, ws = setup(client)
    body = connect_page(client, hdr, ws)
    fb = next(c["id"] for c in body["channels"] if c["channelType"] == "FACEBOOK")
    ig = next(c["id"] for c in body["channels"] if c["channelType"] == "INSTAGRAM")
    minted = client.post(f"{P}/workspaces/{ws}/api-keys", json={"name": "EcoHub org-1"}, headers=hdr)
    wk = {"Authorization": f"Bearer {minted.json()['fullKey']}"}
    ep = client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": "ecohub", "url": "https://93.184.216.34/hook", "events": ["message.inbound"]},
        headers=wk,
    )
    assert ep.status_code == 201, ep.text
    endpoint_id = ep.json()["endpoint"]["id"]

    now_ms = int(time.time() * 1000)
    _process(session_factory, fb, _messenger_payload(page_id="pg-701", psid="psid-77", mid="m.77", timestamp=now_ms))
    _process(session_factory, ig, _ig_payload(ig_id="ig-701", igsid="igsid-77", mid="m.ig77", timestamp=now_ms))

    db = session_factory()
    rows = db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == endpoint_id).all()
    events = {r.payload_json["channelId"]: r.payload_json for r in rows}
    db.close()
    assert set(events) == {fb, ig}
    fb_event = events[fb]
    assert fb_event["type"] == "message.inbound" and fb_event["id"] == "m.77"
    assert fb_event["data"]["message"]["channelType"] == "FACEBOOK"
    assert fb_event["data"]["contact"]["phone"] is None
    assert events[ig]["data"]["message"]["channelType"] == "INSTAGRAM"
    contact_id = fb_event["data"]["contact"]["id"]

    sent = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": f"id:{contact_id}", "channelId": fb, "type": "text", "text": {"body": "Hello"}},
        headers=wk,
    )
    assert sent.status_code == 202, sent.text
    ig_contact = events[ig]["data"]["contact"]["id"]
    assert ig_contact != contact_id
    sent_ig = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": f"id:{ig_contact}", "channelId": ig, "type": "text", "text": {"body": "Hello"}},
        headers=wk,
    )
    assert sent_ig.status_code == 202, sent_ig.text


def test_send_outside_the_24h_window_is_refused(client, sim, session_factory):
    hdr, ws = setup(client)
    body = connect_page(client, hdr, ws)
    fb = next(c["id"] for c in body["channels"] if c["channelType"] == "FACEBOOK")
    minted = client.post(f"{P}/workspaces/{ws}/api-keys", json={"name": "k"}, headers=hdr)
    wk = {"Authorization": f"Bearer {minted.json()['fullKey']}"}
    _process(session_factory, fb, _messenger_payload(page_id="pg-701", psid="psid-78", mid="m.78"))
    from datetime import datetime, timedelta, timezone

    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.channel_id == fb).first()
    identity.window_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    db.close()
    contact = client.get("/api/v1/omnichannel/contacts", headers=wk).json()["data"][0]
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": f"id:{contact['id']}", "channelId": fb, "type": "text", "text": {"body": "late"}},
        headers=wk,
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "messaging_window_closed"


def test_consumer_guide_documents_the_page_connect():
    import pathlib

    guide = (
        pathlib.Path(__file__).resolve().parents[2] / "documentation" / "omnichannel" / "consumer-integration-guide.md"
    ).read_text()
    for needle in ('"channelType": "FACEBOOK"', "page-select", "page_in_use", "no_page_found", "page_not_found"):
        assert needle in guide, needle
