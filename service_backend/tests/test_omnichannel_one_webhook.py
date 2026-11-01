"""Plan 38 gap 2 - one webhook for all channels, and naming the channel on send
(AC-38-80..97, backend only).

RED tests written before the implementation. Everything is asserted from the
outside: HTTP routes, `webhook_deliveries` rows (via the real producers), and
the migration files on disk. Every test seeds its own channels, contacts, keys
and endpoints. Numbers and hosts are obvious fakes.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import (
    Channel,
    Contact,
    ConversationMessage,
    WebhookDelivery,
    WebhookEndpoint,
)
from modules.omnichannel.services import idempotency
from modules.omnichannel.services import webhook_delivery as wd
from modules.omnichannel.services.webhook_service import (
    AUTO_DISABLE_THRESHOLD,
    WebhookService,
)
from tests.test_omnichannel_api_gateway import (
    _auth,
    _default_workspace_id,
    _seed_open_contact,
    _seed_second_workspace,
)
from tests.test_omnichannel_broadcasts import _ensure_template
from tests.test_omnichannel_consumer_webhooks import _reaction_payload
from tests.test_omnichannel_gateway_channels import (
    _channel,
    _hdr,
    _post_without_channel_id,
    _sent_channel_id,
)
from tests.test_omnichannel_webhooks import _process, _wa_payload

BASE = "/api/v1/omnichannel"
HOOK = "https://hooks.example.com/all"
FOREIGN_TENANT = "other-tenant-id"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
VERSIONS = Path(__file__).resolve().parents[1] / "modules/omnichannel/alembic/versions"


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


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


class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
    """No delivery attempt may reach the network."""
    monkeypatch.setattr(wd.httpx, "post", lambda *a, **k: _Resp(200))


# ── helpers ──────────────────────────────────────────────────────────────────
def _two_wa(session_factory, ws):
    a = _channel(session_factory, ws, name="wa-first", age_rank=1)
    b = _channel(session_factory, ws, name="wa-second", age_rank=2)
    return a, b


def _register_all(client, hdr, events, *, url=HOOK, name="all", expect_null=False):
    """Public POST /webhooks. Returns (endpoint_id, signing_secret)."""
    res = client.post(
        f"{BASE}/webhooks",
        json={"name": name, "url": url, "events": list(events)},
        headers=hdr,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    if expect_null:
        assert body["endpoint"]["channelId"] is None, body["endpoint"]
    return body["endpoint"]["id"], body["signingSecret"]


def _insert_endpoint(
    session_factory, *, tenant_id, workspace_id, channel_id, events, status="ACTIVE", url=HOOK
):
    db = session_factory()
    try:
        row = WebhookEndpoint(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            channel_id=channel_id,
            name="direct",
            url=url,
            secret_encrypted="x",
            events_json=list(events),
            status=status,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _rows(session_factory, endpoint_id=None, event_type=None):
    db = session_factory()
    try:
        q = db.query(WebhookDelivery)
        if endpoint_id:
            q = q.filter(WebhookDelivery.endpoint_id == endpoint_id)
        if event_type:
            q = q.filter(WebhookDelivery.event_type == event_type)
        return [
            {"id": r.id, "endpoint_id": r.endpoint_id, "event_id": r.event_id, "payload": r.payload_json}
            for r in q.all()
        ]
    finally:
        db.close()


def _inbound(session_factory, channel_id, phone_digits, wamid):
    out = _process(session_factory, channel_id, _wa_payload(wamid=wamid, from_=phone_digits, text="hello"))
    assert out["messages"] == 1, out  # control: the real producer ran


def _send(client, hdr, to, channel_id=None, extra_headers=None):
    body = {"to": to, "type": "text", "text": {"body": "hi"}}
    if channel_id:
        body["channelId"] = channel_id
    return client.post(f"{BASE}/messages", json=body, headers={**hdr, **(extra_headers or {})})


def _external_id(session_factory, message_id):
    db = session_factory()
    try:
        return db.query(ConversationMessage).filter(ConversationMessage.id == message_id).first().external_message_id
    finally:
        db.close()


def _counts(session_factory, phone_fragment=None):
    db = session_factory()
    try:
        msgs = db.query(ConversationMessage).count()
        contacts = (
            db.query(Contact).filter(Contact.phone.contains(phone_fragment)).count()
            if phone_fragment
            else db.query(Contact).count()
        )
        return msgs, contacts
    finally:
        db.close()


def _rig_sent(client, session_factory, events):
    """Two WhatsApp channels, an all-channels endpoint, and one API send on each."""
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    ep, _ = _register_all(client, hdr, events)
    _seed_open_contact(session_factory, ws, phone="+60111000011", open_window=True)
    _seed_open_contact(session_factory, ws, phone="+60111000022", open_window=True)
    ra = _send(client, hdr, "+60111000011", a)
    rb = _send(client, hdr, "+60111000022", b)
    assert ra.status_code == 202 and rb.status_code == 202, (ra.text, rb.text)
    return {"ws": ws, "a": a, "b": b, "hdr": hdr, "ep": ep, "mid_a": ra.json()["id"], "mid_b": rb.json()["id"]}


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-80 - public registration has no channel
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_80_register_with_two_active_channels_has_null_channel(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    res = client.post(
        f"{BASE}/webhooks",
        json={"name": "all", "url": HOOK, "events": ["message.inbound"]},
        headers=hdr,
    )
    assert res.status_code == 201, res.text
    ep = res.json()["endpoint"]
    assert ep["channelId"] is None
    assert ep["workspaceId"] == ws and ep["tenantId"] == DEFAULT_TENANT_ID
    db = session_factory()
    try:
        row = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == ep["id"]).one()
        assert row.channel_id is None
        assert row.tenant_id == DEFAULT_TENANT_ID and row.workspace_id == ws
    finally:
        db.close()


def test_ac_38_80_register_with_no_active_channel_is_201(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _channel(session_factory, ws, name="paused", age_rank=1, active=False, status_key="INACTIVE")
    hdr = _hdr(client, ws)
    res = client.post(
        f"{BASE}/webhooks",
        json={"name": "all", "url": HOOK, "events": ["message.inbound"]},
        headers=hdr,
    )
    assert res.status_code == 201, res.text
    assert res.json()["endpoint"]["channelId"] is None


def test_ac_38_80_channel_id_in_body_is_not_honoured(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    res = client.post(
        f"{BASE}/webhooks",
        json={"name": "all", "url": HOOK, "events": ["message.inbound"], "channelId": b},
        headers=hdr,
    )
    assert res.status_code == 201, res.text
    assert res.json()["endpoint"]["channelId"] is None


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-81 - read and manage a null-channel endpoint; scoped like any other
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_81_list_patch_rotate_disable_enable_delete_on_null_endpoint(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    ep, secret = _register_all(client, hdr, ["message.inbound"], expect_null=True)

    listed = client.get(f"{BASE}/webhooks", headers=hdr)
    assert listed.status_code == 200, listed.text
    item = next(i for i in listed.json()["data"] if i["id"] == ep)
    assert item["channelId"] is None

    patched = client.patch(f"{BASE}/webhooks/{ep}", json={"name": "renamed"}, headers=hdr)
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "renamed" and patched.json()["channelId"] is None

    rotated = client.post(f"{BASE}/webhooks/{ep}/rotate", headers=hdr)
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["signingSecret"] != secret

    off = client.post(f"{BASE}/webhooks/{ep}/disable", headers=hdr)
    assert off.status_code == 200 and off.json()["status"] == "DISABLED"
    assert off.json()["channelId"] is None
    on = client.post(f"{BASE}/webhooks/{ep}/enable", headers=hdr)
    assert on.status_code == 200 and on.json()["status"] == "ACTIVE"

    gone = client.delete(f"{BASE}/webhooks/{ep}", headers=hdr)
    assert gone.status_code == 204
    after = client.get(f"{BASE}/webhooks", headers=hdr).json()["data"]
    assert ep not in [i["id"] for i in after]


_VERBS = [
    ("patch", "", {"name": "x"}),
    ("post", "/rotate", None),
    ("post", "/enable", None),
    ("post", "/disable", None),
    ("delete", "", None),
]


@pytest.mark.parametrize("verb,suffix,body", _VERBS)
def test_ac_38_81_other_workspace_key_gets_404(client, session_factory, verb, suffix, body):
    ws = _default_workspace_id(session_factory)
    other_ws = _seed_second_workspace(session_factory)
    mine = _hdr(client, ws)
    theirs = _hdr(client, other_ws)
    ep, _ = _register_all(client, theirs, ["message.inbound"], expect_null=True)
    kwargs = {"headers": mine}
    if body is not None:
        kwargs["json"] = body
    res = getattr(client, verb)(f"{BASE}/webhooks/{ep}{suffix}", **kwargs)
    assert res.status_code == 404, res.text
    # control: the owner still reaches it
    assert ep in [i["id"] for i in client.get(f"{BASE}/webhooks", headers=theirs).json()["data"]]


@pytest.mark.parametrize("verb,suffix,body", _VERBS)
def test_ac_38_81_other_tenant_endpoint_gets_404(client, session_factory, verb, suffix, body):
    ws = _default_workspace_id(session_factory)
    mine = _hdr(client, ws)
    # same workspace id string, another tenant: only the tenant filter can exclude it
    ep = _insert_endpoint(
        session_factory, tenant_id=FOREIGN_TENANT, workspace_id=ws, channel_id=None, events=["message.inbound"]
    )
    kwargs = {"headers": mine}
    if body is not None:
        kwargs["json"] = body
    res = getattr(client, verb)(f"{BASE}/webhooks/{ep}{suffix}", **kwargs)
    assert res.status_code == 404, res.text
    db = session_factory()
    try:
        assert db.query(WebhookEndpoint).filter(WebhookEndpoint.id == ep).count() == 1
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-82 - 10 all-channels endpoints per workspace, counted separately
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_82_constant_is_ten():
    from modules.omnichannel.services.webhook_service import MAX_ENDPOINTS_PER_WORKSPACE

    assert MAX_ENDPOINTS_PER_WORKSPACE == 10


def test_ac_38_82_eleventh_all_channels_endpoint_is_422_and_not_saved(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    for i in range(10):
        _register_all(client, hdr, ["message.inbound"], name=f"n{i}", expect_null=True)
    res = client.post(
        f"{BASE}/webhooks",
        json={"name": "n10", "url": HOOK, "events": ["message.inbound"]},
        headers=hdr,
    )
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "invalid_request"
    db = session_factory()
    try:
        assert db.query(WebhookEndpoint).filter(WebhookEndpoint.workspace_id == ws).count() == 10
    finally:
        db.close()


def test_ac_38_82_per_channel_rows_do_not_block_an_all_channels_one(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, _b = _two_wa(session_factory, ws)
    db = session_factory()
    try:
        for i in range(10):
            WebhookService(db).create(DEFAULT_TENANT_ID, a, f"pc{i}", HOOK, ["message.inbound"], created_by=None)
    finally:
        db.close()
    hdr = _hdr(client, ws)
    _register_all(client, hdr, ["message.inbound"], expect_null=True)


def test_ac_38_82_all_channels_rows_do_not_block_a_per_channel_one(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, _b = _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    for i in range(10):
        _register_all(client, hdr, ["message.inbound"], name=f"n{i}", expect_null=True)
    res = client.post(
        f"/omnichannel/channels/{a}/webhooks",
        headers=_auth(client),
        json={"name": "per", "url": HOOK, "events": ["message.inbound"]},
    )
    assert res.status_code == 201, res.text
    assert res.json()["endpoint"]["channelId"] == a


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-83 - operator create still binds the channel (control, passes today)
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_83_operator_create_binds_the_channel(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    res = client.post(
        f"/omnichannel/channels/{b}/webhooks",
        headers=_auth(client),
        json={"name": "per", "url": HOOK, "events": ["message.inbound"]},
    )
    assert res.status_code == 201, res.text
    ep = res.json()["endpoint"]
    assert ep["channelId"] == b and ep["workspaceId"] == ws
    listed = client.get(f"/omnichannel/channels/{b}/webhooks", headers=_auth(client)).json()["data"]
    assert [i["id"] for i in listed] == [ep["id"]]
    assert client.get(f"/omnichannel/channels/{a}/webhooks", headers=_auth(client)).json()["data"] == []


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-84 - an event on either channel reaches the endpoint once (real producers)
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_84_inbound_on_each_channel_reaches_endpoint_once(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    ep, _ = _register_all(client, hdr, ["message.inbound"], expect_null=True)
    _inbound(session_factory, a, "60111000031", "wamid.84-in-a")
    _inbound(session_factory, b, "60111000032", "wamid.84-in-b")
    rows = _rows(session_factory, ep, "message.inbound")
    assert {r["event_id"]: r["payload"]["channelId"] for r in rows} == {
        "wamid.84-in-a": a,
        "wamid.84-in-b": b,
    }
    assert len(rows) == 2


def test_ac_38_84_outbound_on_each_channel_reaches_endpoint_once(client, session_factory):
    r = _rig_sent(client, session_factory, ["message.outbound"])
    rows = _rows(session_factory, r["ep"], "message.outbound")
    assert len(rows) == 2
    assert {x["event_id"]: x["payload"]["channelId"] for x in rows} == {
        f"{r['mid_a']}:outbound": r["a"],
        f"{r['mid_b']}:outbound": r["b"],
    }


def test_ac_38_84_status_events_on_each_channel_reach_endpoint_once(client, session_factory):
    r = _rig_sent(client, session_factory, ["message.status"])
    # sender-side SENT (send_runner producer)
    sent = {x["payload"]["data"]["messageId"]: x["payload"]["channelId"]
            for x in _rows(session_factory, r["ep"], "message.status")
            if x["payload"]["data"]["deliveryStatus"] == "SENT"}
    assert sent == {r["mid_a"]: r["a"], r["mid_b"]: r["b"]}
    # receipt DELIVERED (inbound_service producer)
    for ch, mid in ((r["a"], r["mid_a"]), (r["b"], r["mid_b"])):
        ext = _external_id(session_factory, mid)
        assert ext
        _process(
            session_factory, ch,
            _wa_payload(statuses=[{"id": ext, "status": "delivered", "timestamp": "1717550002"}]),
        )
    rows = [x for x in _rows(session_factory, r["ep"], "message.status")
            if x["payload"]["data"]["deliveryStatus"] == "DELIVERED"]
    assert len(rows) == 2
    assert {x["payload"]["data"]["messageId"]: x["payload"]["channelId"] for x in rows} == {
        r["mid_a"]: r["a"],
        r["mid_b"]: r["b"],
    }


def test_ac_38_84_reaction_on_each_channel_reaches_endpoint_once(client, session_factory):
    r = _rig_sent(client, session_factory, ["message.reaction"])
    for n, (ch, mid, phone) in enumerate(
        ((r["a"], r["mid_a"], "60111000011"), (r["b"], r["mid_b"], "60111000022"))
    ):
        ext = _external_id(session_factory, mid)
        assert ext
        _process(
            session_factory, ch,
            _reaction_payload(target_wamid=ext, emoji="👍", from_=phone, wamid=f"wamid.84-rx-{n}"),
        )
    rows = _rows(session_factory, r["ep"], "message.reaction")
    assert len(rows) == 2
    assert {x["payload"]["data"]["targetMessageId"]: x["payload"]["channelId"] for x in rows} == {
        r["mid_a"]: r["a"],
        r["mid_b"]: r["b"],
    }


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-85 - per-channel endpoints keep their scope; same URL on both kinds
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_85_per_channel_endpoint_gets_only_its_own_channel(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    db = session_factory()
    try:
        ea = WebhookService(db).create(DEFAULT_TENANT_ID, a, "pa", HOOK, ["message.inbound"], created_by=None)[0].id
        eb = WebhookService(db).create(DEFAULT_TENANT_ID, b, "pb", HOOK, ["message.inbound"], created_by=None)[0].id
    finally:
        db.close()
    _inbound(session_factory, a, "60111000041", "wamid.85-a")
    _inbound(session_factory, b, "60111000042", "wamid.85-b")
    assert [x["event_id"] for x in _rows(session_factory, ea)] == ["wamid.85-a"]
    assert [x["event_id"] for x in _rows(session_factory, eb)] == ["wamid.85-b"]


def test_ac_38_85_same_url_on_both_kinds_gets_one_row_each(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    db = session_factory()
    try:
        per_a = WebhookService(db).create(DEFAULT_TENANT_ID, a, "pa", HOOK, ["message.inbound"], created_by=None)[0].id
    finally:
        db.close()
    allc, _ = _register_all(client, hdr, ["message.inbound"], url=HOOK, expect_null=True)

    _inbound(session_factory, a, "60111000051", "wamid.85-same-a")
    on_a = _rows(session_factory, event_type="message.inbound")
    assert sorted(x["endpoint_id"] for x in on_a) == sorted([per_a, allc])  # one row each

    _inbound(session_factory, b, "60111000052", "wamid.85-same-b")
    on_b = [x for x in _rows(session_factory, event_type="message.inbound") if x["event_id"] == "wamid.85-same-b"]
    assert [x["endpoint_id"] for x in on_b] == [allc]  # per-channel A never sees B


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-86 - tenant and workspace are the only boundary on a null row
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_86_other_tenant_same_workspace_id_and_other_workspace_get_nothing(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    other_ws = _seed_second_workspace(session_factory)
    hdr = _hdr(client, ws)
    mine, _ = _register_all(client, hdr, ["message.inbound"], expect_null=True)
    # second workspace, same tenant: registered through its own key
    sibling, _ = _register_all(client, _hdr(client, other_ws), ["message.inbound"], expect_null=True)
    # another tenant carrying the SAME workspace id string
    foreign = _insert_endpoint(
        session_factory, tenant_id=FOREIGN_TENANT, workspace_id=ws, channel_id=None, events=["message.inbound"]
    )
    _inbound(session_factory, b, "60111000061", "wamid.86-iso")
    assert [x["event_id"] for x in _rows(session_factory, mine)] == ["wamid.86-iso"]  # positive control
    assert _rows(session_factory, sibling) == []
    assert _rows(session_factory, foreign) == []


def test_ac_38_86_disabled_auto_disabled_and_unsubscribed_get_nothing(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    live, _ = _register_all(client, hdr, ["message.inbound"], expect_null=True)
    paused, _ = _register_all(client, hdr, ["message.inbound"], name="paused", expect_null=True)
    assert client.post(f"{BASE}/webhooks/{paused}/disable", headers=hdr).status_code == 200
    auto, _ = _register_all(client, hdr, ["message.inbound"], name="auto", expect_null=True)
    db = session_factory()
    try:
        db.query(WebhookEndpoint).filter(WebhookEndpoint.id == auto).update({"status": "AUTO_DISABLED"})
        db.commit()
    finally:
        db.close()
    other_event, _ = _register_all(client, hdr, ["message.outbound"], name="other", expect_null=True)

    _inbound(session_factory, b, "60111000071", "wamid.86-state")
    assert [x["event_id"] for x in _rows(session_factory, live)] == ["wamid.86-state"]
    for ep in (paused, auto, other_event):
        assert _rows(session_factory, ep) == []


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-87 - real delivery path for a null-channel endpoint
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_87_delivery_is_signed_succeeds_and_is_listed(client, session_factory, monkeypatch):
    import hmac

    from modules.omnichannel.services.webhook_delivery import dispatch, sign_body

    calls = []

    def fake_post(url, content=None, headers=None, timeout=None):
        calls.append({"url": url, "body": content, "headers": headers})
        return _Resp(200)

    monkeypatch.setattr(wd.httpx, "post", fake_post)
    monkeypatch.setattr(wd, "assert_deliverable", lambda url: None)

    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    ep, secret = _register_all(client, hdr, ["message.inbound"], expect_null=True)
    _inbound(session_factory, b, "60111000081", "wamid.87-ok")
    row = _rows(session_factory, ep)[0]

    db = session_factory()
    try:
        assert dispatch(db, row["id"]) == "success"
        delivery = db.query(WebhookDelivery).filter(WebhookDelivery.id == row["id"]).one()
        assert delivery.status == "SUCCESS" and delivery.response_status == 200
    finally:
        db.close()

    assert len(calls) == 1
    hdrs = calls[0]["headers"]
    expected = sign_body(secret, hdrs["X-Fx-Timestamp"], calls[0]["body"])
    assert hmac.compare_digest(hdrs["X-Fx-Signature"], expected)
    assert json.loads(calls[0]["body"])["channelId"] == b

    log = client.get(f"/omnichannel/webhooks/{ep}/deliveries", headers=_auth(client))
    assert log.status_code == 200, log.text
    assert [(d["id"], d["status"]) for d in log.json()["data"]] == [(row["id"], "SUCCESS")]


def test_ac_38_87_failures_retry_count_and_auto_disable(client, session_factory, monkeypatch):
    from modules.omnichannel.services.webhook_delivery import dispatch

    monkeypatch.setattr(wd.httpx, "post", lambda *a, **k: _Resp(500))
    monkeypatch.setattr(wd, "assert_deliverable", lambda url: None)

    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    ep, _ = _register_all(client, hdr, ["message.inbound"], expect_null=True)

    for i in range(AUTO_DISABLE_THRESHOLD):
        channel = a if i % 2 == 0 else b
        _inbound(session_factory, channel, f"6011100100{i}", f"wamid.87-fail-{i}")
        delivery_id = next(x["id"] for x in _rows(session_factory, ep) if x["event_id"] == f"wamid.87-fail-{i}")
        db = session_factory()
        try:
            assert dispatch(db, delivery_id) == "retry"  # first failure is retried, not dead
            delivery = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).one()
            assert delivery.attempt_count == 1 and delivery.status == "PENDING"
            for _ in range(wd.MAX_ATTEMPTS):
                db.refresh(delivery)
                if delivery.status != "PENDING":
                    break
                delivery.next_attempt_at = None
                dispatch(db, delivery_id)
            db.refresh(delivery)
            assert delivery.status == "FAILED"
            endpoint = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == ep).one()
            if i < AUTO_DISABLE_THRESHOLD - 1:
                assert endpoint.consecutive_failures == i + 1 and endpoint.status == "ACTIVE"
        finally:
            db.close()

    db = session_factory()
    try:
        endpoint = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == ep).one()
        assert endpoint.status == "AUTO_DISABLED"
        assert endpoint.consecutive_failures >= AUTO_DISABLE_THRESHOLD
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-88 - contact.updated
# ═════════════════════════════════════════════════════════════════════════════
def _add_message(session_factory, contact_id, channel_id, minutes_ago):
    db = session_factory()
    try:
        db.add(
            ConversationMessage(
                tenant_id=DEFAULT_TENANT_ID,
                contact_id=contact_id,
                channel_id=channel_id,
                sender_type="CONTACT",
                message_type="TEXT",
                body="earlier",
                delivery_status="DELIVERED",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
            )
        )
        db.commit()
    finally:
        db.close()


def _patch_priority(client, cid):
    return client.patch(f"/omnichannel/contacts/{cid}", headers=_auth(client), json={"priority": "HIGH"})


def test_ac_38_88_all_channels_endpoint_gets_one_event_with_latest_channel(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    cid = _seed_open_contact(session_factory, ws, phone="+60111000091")
    _add_message(session_factory, cid, a, minutes_ago=30)
    _add_message(session_factory, cid, b, minutes_ago=5)  # latest
    hdr = _hdr(client, ws)
    allc, _ = _register_all(client, hdr, ["contact.updated"], expect_null=True)
    db = session_factory()
    try:
        per_a = WebhookService(db).create(DEFAULT_TENANT_ID, a, "pa", HOOK, ["contact.updated"], created_by=None)[0].id
        per_b = WebhookService(db).create(DEFAULT_TENANT_ID, b, "pb", HOOK, ["contact.updated"], created_by=None)[0].id
    finally:
        db.close()

    assert _patch_priority(client, cid).status_code == 200
    rows = _rows(session_factory, allc, "contact.updated")
    assert len(rows) == 1
    assert rows[0]["payload"]["channelId"] == b
    assert len(_rows(session_factory, per_b, "contact.updated")) == 1  # latest channel only
    assert _rows(session_factory, per_a, "contact.updated") == []


def test_ac_38_88_never_messaged_contact_gives_null_channel_event_to_all_channels_only(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    cid = _seed_open_contact(session_factory, ws, phone="+60111000092")
    hdr = _hdr(client, ws)
    allc, _ = _register_all(client, hdr, ["contact.updated"], expect_null=True)
    db = session_factory()
    try:
        per_a = WebhookService(db).create(DEFAULT_TENANT_ID, a, "pa", HOOK, ["contact.updated"], created_by=None)[0].id
        per_b = WebhookService(db).create(DEFAULT_TENANT_ID, b, "pb", HOOK, ["contact.updated"], created_by=None)[0].id
    finally:
        db.close()

    assert _patch_priority(client, cid).status_code == 200
    rows = _rows(session_factory, allc, "contact.updated")
    assert len(rows) == 1
    assert rows[0]["payload"]["channelId"] is None
    assert rows[0]["payload"]["workspaceId"] == ws
    assert rows[0]["payload"]["data"]["contact"]["id"] == cid
    assert _rows(session_factory, per_a) == [] and _rows(session_factory, per_b) == []


@pytest.mark.parametrize("has_channel", [True, False])
def test_ac_38_88_fan_out_failure_never_reaches_the_caller(client, session_factory, monkeypatch, has_channel):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    cid = _seed_open_contact(session_factory, ws, phone="+60111000093")
    if has_channel:
        _add_message(session_factory, cid, a, minutes_ago=5)
    hdr = _hdr(client, ws)
    _register_all(client, hdr, ["contact.updated"])

    def boom(*args, **kwargs):
        raise RuntimeError("fan-out exploded")

    monkeypatch.setattr(wd, "enqueue_event", boom)
    monkeypatch.setattr(wd, "enqueue_workspace_event", boom, raising=False)
    res = _patch_priority(client, cid)
    assert res.status_code == 200, res.text
    assert res.json()["priority"] == "HIGH"  # the change itself stood


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-89 / 90 / 91 / 92 - the channel is named when the default is a guess
# ═════════════════════════════════════════════════════════════════════════════
def _assert_channel_required(res):
    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert err["code"] == "channel_required"
    assert "channelId" in err["message"]


def test_ac_38_89_json_send_with_two_whatsapp_channels_is_refused_and_creates_nothing(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _two_wa(session_factory, ws)
    hdr = _hdr(client, ws)
    before = _counts(session_factory)
    res = _post_without_channel_id(client, hdr, "+60111555901")
    _assert_channel_required(res)
    assert _counts(session_factory) == before
    assert _counts(session_factory, "555901")[1] == 0  # no contact for the unseen phone


def test_ac_38_89_json_send_with_two_messenger_channels_and_no_whatsapp_is_refused(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _channel(session_factory, ws, name="fb-one", age_rank=1, channel_type="FACEBOOK")
    _channel(session_factory, ws, name="fb-two", age_rank=2, channel_type="FACEBOOK")
    hdr = _hdr(client, ws)
    res = _post_without_channel_id(client, hdr, "+60111555902")
    _assert_channel_required(res)
    assert _counts(session_factory, "555902") == (0, 0)


def test_ac_38_90_multipart_send_is_refused_and_nothing_is_uploaded(client, session_factory, tmp_path):
    ws = _default_workspace_id(session_factory)
    _two_wa(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60111555903", open_window=True)
    hdr = _hdr(client, ws)
    before = _counts(session_factory)
    res = client.post(
        f"{BASE}/messages",
        files={"file": ("a.png", PNG, "image/png")},
        data={"payload": json.dumps({"to": "+60111555903", "type": "image"})},
        headers=hdr,
    )
    _assert_channel_required(res)
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []
    assert _counts(session_factory) == before


def test_ac_38_90_control_multipart_with_channel_id_does_store_the_file(client, session_factory, tmp_path):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60111555904", open_window=True)
    hdr = _hdr(client, ws)
    res = client.post(
        f"{BASE}/messages",
        files={"file": ("a.png", PNG, "image/png")},
        data={"payload": json.dumps({"to": "+60111555904", "type": "image", "channelId": b})},
        headers=hdr,
    )
    assert res.status_code == 202, res.text
    assert [p for p in tmp_path.rglob("*") if p.is_file()]  # the assertion above is meaningful


def test_ac_38_91_refusal_does_not_use_up_the_idempotency_key(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60111555905", open_window=True)
    hdr = _hdr(client, ws)
    key = {"Idempotency-Key": "retry-after-refusal"}
    first = _send(client, hdr, "+60111555905", extra_headers=key)
    _assert_channel_required(first)
    assert idempotency.get_store().lookup(ws, "retry-after-refusal") is None  # slot released
    retry = _send(client, hdr, "+60111555905", channel_id=b, extra_headers=key)
    assert retry.status_code == 202, retry.text
    assert retry.json()["idempotencyReplay"] is False
    assert _sent_channel_id(session_factory, retry.json()["id"]) == b


def test_ac_38_92_id_recipient_without_channel_id_is_refused(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _two_wa(session_factory, ws)
    cid = _seed_open_contact(session_factory, ws, phone="+60111555906", open_window=True)
    hdr = _hdr(client, ws)
    before = _counts(session_factory)
    _assert_channel_required(_send(client, hdr, f"id:{cid}"))
    assert _counts(session_factory) == before


def test_ac_38_92_phone_and_id_recipients_go_out_on_the_named_channel(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    cid = _seed_open_contact(session_factory, ws, phone="+60111555907", open_window=True)
    hdr = _hdr(client, ws)
    by_phone = _send(client, hdr, "+60111555907", channel_id=b)
    by_id = _send(client, hdr, f"id:{cid}", channel_id=b)
    assert by_phone.status_code == 202, by_phone.text
    assert by_id.status_code == 202, by_id.text
    assert _sent_channel_id(session_factory, by_phone.json()["id"]) == b
    assert _sent_channel_id(session_factory, by_id.json()["id"]) == b


def test_ac_38_92_unknown_inactive_and_foreign_channel_ids_stay_invalid_channel(client, session_factory):
    ws = _default_workspace_id(session_factory)
    live = _channel(session_factory, ws, name="live", age_rank=1)
    _channel(session_factory, ws, name="live2", age_rank=2)
    dead = _channel(session_factory, ws, name="dead", age_rank=3, active=False, status_key="INACTIVE")
    other_ws = _seed_second_workspace(session_factory)
    db = session_factory()
    try:
        sibling = db.query(Channel).filter(Channel.workspace_id == other_ws).first().id
    finally:
        db.close()
    alien = _channel(session_factory, ws, name="alien", age_rank=1, tenant_id=FOREIGN_TENANT)
    _seed_open_contact(session_factory, ws, phone="+60111555908", open_window=True)
    hdr = _hdr(client, ws)
    for bad in ("no-such-channel", dead, sibling, alien):
        res = _send(client, hdr, "+60111555908", channel_id=bad)
        assert res.status_code == 422, (bad, res.text)
        assert res.json()["error"]["code"] == "invalid_channel", (bad, res.text)
    # control: a real channel of the workspace is accepted
    assert _send(client, hdr, "+60111555908", channel_id=live).status_code == 202


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-93 - no refusal when the default is not a guess (controls, pass today)
# ═════════════════════════════════════════════════════════════════════════════
def _assert_sends_on(client, session_factory, ws, expected_channel, phone):
    _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    res = _post_without_channel_id(client, _hdr(client, ws), phone)
    assert res.status_code == 202, res.text
    assert _sent_channel_id(session_factory, res.json()["id"]) == expected_channel


def test_ac_38_93_one_active_channel(client, session_factory):
    ws = _default_workspace_id(session_factory)
    only = _channel(session_factory, ws, name="only", age_rank=1)
    _channel(session_factory, ws, name="off", age_rank=2, active=False, status_key="INACTIVE")
    _assert_sends_on(client, session_factory, ws, only, "+60111555911")


@pytest.mark.parametrize("other_type", ["FACEBOOK", "WEBCHAT"])
def test_ac_38_93_one_whatsapp_plus_another_kind_uses_whatsapp(client, session_factory, other_type):
    ws = _default_workspace_id(session_factory)
    _channel(session_factory, ws, name="other-older", age_rank=1, channel_type=other_type)
    wa = _channel(session_factory, ws, name="wa-newer", age_rank=2)
    _assert_sends_on(client, session_factory, ws, wa, "+60111555912")


def test_ac_38_93_two_whatsapp_one_paused(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _channel(session_factory, ws, name="paused", age_rank=1, active=False, status_key="INACTIVE")
    live = _channel(session_factory, ws, name="live", age_rank=2)
    _assert_sends_on(client, session_factory, ws, live, "+60111555913")


def test_ac_38_93_two_whatsapp_one_disconnected(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _channel(session_factory, ws, name="gone", age_rank=1, trashed=True)
    live = _channel(session_factory, ws, name="live", age_rank=2)
    _assert_sends_on(client, session_factory, ws, live, "+60111555914")


def test_ac_38_93_no_active_channel_stays_409(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _channel(session_factory, ws, name="paused", age_rank=1, active=False, status_key="INACTIVE")
    _channel(session_factory, ws, name="gone", age_rank=2, trashed=True)
    res = _post_without_channel_id(client, _hdr(client, ws), "+60111555915")
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "no_active_channel"


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-94 - GET /templates
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_94_templates_without_channel_id_on_a_real_guess_is_refused(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _two_wa(session_factory, ws)
    res = client.get(f"{BASE}/templates", headers=_hdr(client, ws))
    _assert_channel_required(res)


def test_ac_38_94_templates_with_channel_id_return_that_channels_templates(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    _ensure_template(session_factory, a, name="only_on_first")
    _ensure_template(session_factory, b, name="only_on_second")
    res = client.get(f"{BASE}/templates", params={"channelId": b}, headers=_hdr(client, ws))
    assert res.status_code == 200, res.text
    assert [t["name"] for t in res.json()["data"]] == ["only_on_second"]


def test_ac_38_94_templates_on_a_non_guess_workspace_answer_as_today(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _channel(session_factory, ws, name="fb", age_rank=1, channel_type="FACEBOOK")
    wa = _channel(session_factory, ws, name="wa", age_rank=2)
    _ensure_template(session_factory, wa, name="the_only_one")
    res = client.get(f"{BASE}/templates", headers=_hdr(client, ws))
    assert res.status_code == 200, res.text
    assert [t["name"] for t in res.json()["data"]] == ["the_only_one"]


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-95 - GET /channels isDefault follows the same resolver
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("kind", ["WHATSAPP", "FACEBOOK"])
def test_ac_38_95_is_default_false_on_every_channel_when_the_default_is_a_guess(client, session_factory, kind):
    ws = _default_workspace_id(session_factory)
    one = _channel(session_factory, ws, name="first", age_rank=1, channel_type=kind)
    two = _channel(session_factory, ws, name="second", age_rank=2, channel_type=kind)
    res = client.get(f"{BASE}/channels", headers=_hdr(client, ws))
    assert res.status_code == 200, res.text
    flags = {i["id"]: i["isDefault"] for i in res.json()["data"]}
    assert flags == {one: False, two: False}


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-96 - schema: what the sqlite suite can see
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_96_model_column_is_nullable():
    assert WebhookEndpoint.__table__.c.channel_id.nullable is True


def _revision_graph():
    """revision -> list of down revisions (a merge file carries a tuple)."""
    rev_pat = re.compile(r"""^revision\s*(?::[^=\n]+)?=\s*["']([^"']+)["']""", re.M)
    down_pat = re.compile(r"""^down_revision\s*(?::[^=\n]+)?=\s*(\([^)]*\)|["'][^"']+["']|None)""", re.M)
    revs, by_file = {}, {}
    for f in sorted(VERSIONS.glob("*.py")):
        text = f.read_text()
        rev = rev_pat.search(text)
        assert rev, f"no revision id in {f.name}"
        down = down_pat.search(text)
        revs[rev.group(1)] = re.findall(r"""["']([^"']+)["']""", down.group(1)) if down else []
        by_file[rev.group(1)] = f
    return revs, by_file


def test_ac_38_96_migration_chain_has_one_head_with_a_short_new_revision():
    revs, by_file = _revision_graph()
    downs = {d for ds in revs.values() for d in ds}
    heads = [r for r in revs if r not in downs]
    assert len(heads) == 1, heads
    head = heads[0]
    assert by_file[head].name.startswith("0023_"), by_file[head].name
    assert revs[head] == ["0022_omni_webchat_profile"]
    assert len(head) <= 32, head
    text = by_file[head].read_text().lower()
    assert "webhook_endpoints" in text and "channel_id" in text
    assert "drop not null" in text or "nullable=true" in text.replace(" ", "")
    assert len(list(VERSIONS.glob("0023_*.py"))) == 1


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-97 - operator list for a channel includes the workspace's null rows
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_97_channel_list_has_own_rows_plus_null_rows_of_its_tenant_and_workspace(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    other_ws = _seed_second_workspace(session_factory)
    db = session_factory()
    try:
        own = WebhookService(db).create(DEFAULT_TENANT_ID, a, "own", HOOK, ["message.inbound"], created_by=None)[0].id
        other_channel = WebhookService(db).create(DEFAULT_TENANT_ID, b, "elsewhere", HOOK, ["message.inbound"], created_by=None)[0].id
    finally:
        db.close()
    allc, _ = _register_all(client, _hdr(client, ws), ["message.inbound"], expect_null=True)
    sibling, _ = _register_all(client, _hdr(client, other_ws), ["message.inbound"], expect_null=True)
    foreign = _insert_endpoint(
        session_factory, tenant_id=FOREIGN_TENANT, workspace_id=ws, channel_id=None, events=["message.inbound"]
    )

    ids_a = {i["id"] for i in client.get(f"/omnichannel/channels/{a}/webhooks", headers=_auth(client)).json()["data"]}
    assert ids_a == {own, allc}
    assert other_channel not in ids_a and sibling not in ids_a and foreign not in ids_a

    ids_b = {i["id"] for i in client.get(f"/omnichannel/channels/{b}/webhooks", headers=_auth(client)).json()["data"]}
    assert ids_b == {other_channel, allc}


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-101 - a reaction names no default channel, so it is not refused
# ═════════════════════════════════════════════════════════════════════════════
def _reaction_rig(session_factory, ws, channel_id):
    """A contact whose identity (and last message) sits on `channel_id`, with a
    delivered message to react to."""
    from modules.omnichannel.models import ContactChannelIdentity

    phone = "+60111777101"
    cid = _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    db = session_factory()
    try:
        db.add(
            ConversationMessage(
                tenant_id=DEFAULT_TENANT_ID,
                contact_id=cid,
                channel_id=channel_id,
                sender_type="CONTACT",
                message_type="TEXT",
                body="target",
                external_message_id="wamid.101-target",
                delivery_status="DELIVERED",
            )
        )
        db.add(
            ContactChannelIdentity(
                tenant_id=DEFAULT_TENANT_ID,
                contact_id=cid,
                channel_id=channel_id,
                external_user_id=phone,
            )
        )
        db.commit()
        mid = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "wamid.101-target").one().id
    finally:
        db.close()
    return cid, mid


def _react(client, hdr, message_id, channel_id=None):
    body = {"to": "+60111777101", "type": "reaction", "reaction": {"messageId": message_id, "emoji": "👍"}}
    if channel_id:
        body["channelId"] = channel_id
    return client.post(f"{BASE}/messages", json=body, headers=hdr)


def _reaction_count(session_factory):
    from modules.omnichannel.models import MessageReaction

    db = session_factory()
    try:
        return db.query(MessageReaction).count()
    finally:
        db.close()


def test_ac_38_101_reaction_without_channel_id_sends_on_the_contacts_own_channel(client, session_factory):
    # Control, passes today. It guards the exemption: `_do_send` resolves the
    # channel before the type branch, so a resolver that refuses a real guess
    # there would answer this request 422 channel_required (two active WhatsApp
    # channels, no channelId) instead of 202.
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    _cid, mid = _reaction_rig(session_factory, ws, b)  # own channel is the SECOND one
    db = session_factory()
    try:
        per_a = WebhookService(db).create(DEFAULT_TENANT_ID, a, "pa", HOOK, ["message.reaction"], created_by=None)[0].id
        per_b = WebhookService(db).create(DEFAULT_TENANT_ID, b, "pb", HOOK, ["message.reaction"], created_by=None)[0].id
    finally:
        db.close()
    res = _react(client, _hdr(client, ws), mid)
    assert res.status_code == 202, res.text
    assert _reaction_count(session_factory) == 1
    assert len(_rows(session_factory, per_b, "message.reaction")) == 1  # went out on its own channel
    assert _rows(session_factory, per_a) == []


def test_ac_38_101_reaction_with_foreign_or_unknown_channel_id_is_invalid_channel(client, session_factory):
    ws = _default_workspace_id(session_factory)
    a, b = _two_wa(session_factory, ws)
    _cid, mid = _reaction_rig(session_factory, ws, b)
    other_ws = _seed_second_workspace(session_factory)
    db = session_factory()
    try:
        sibling = db.query(Channel).filter(Channel.workspace_id == other_ws).first().id
    finally:
        db.close()
    alien = _channel(session_factory, ws, name="alien", age_rank=1, tenant_id=FOREIGN_TENANT)
    hdr = _hdr(client, ws)
    for bad in ("no-such-channel", sibling, alien):
        res = _react(client, hdr, mid, channel_id=bad)
        assert res.status_code == 422, (bad, res.text)
        assert res.json()["error"]["code"] == "invalid_channel", (bad, res.text)
    assert _reaction_count(session_factory) == 0


def test_ac_38_101_reaction_with_no_active_channel_stays_409(client, session_factory):
    ws = _default_workspace_id(session_factory)
    off = _channel(session_factory, ws, name="paused", age_rank=1, active=False, status_key="INACTIVE")
    _cid, mid = _reaction_rig(session_factory, ws, off)
    res = _react(client, _hdr(client, ws), mid)
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "no_active_channel"


_NON_TEXT = {
    "template": {"template": {"name": "tpl_101", "variables": []}},
    "interactive": {"interactive": {"type": "button", "body": {"text": "Pick"}, "buttons": [{"id": "1", "title": "One"}]}},
    "location": {"location": {"lat": 3.1, "lng": 101.6, "name": "HQ"}},
    "contacts": {"contacts": [{"name": {"formatted_name": "Sam"}, "phones": [{"phone": "+60111000000"}]}]},
}


@pytest.mark.parametrize("kind", sorted(_NON_TEXT))
def test_ac_38_101_other_types_are_still_refused_on_a_real_guess(client, session_factory, kind):
    ws = _default_workspace_id(session_factory)
    a, _b = _two_wa(session_factory, ws)
    _ensure_template(session_factory, a, name="tpl_101")
    _seed_open_contact(session_factory, ws, phone="+60111777102", open_window=True)
    before = _counts(session_factory)
    res = client.post(
        f"{BASE}/messages",
        json={"to": "+60111777102", "type": kind, **_NON_TEXT[kind]},
        headers=_hdr(client, ws),
    )
    _assert_channel_required(res)
    assert _counts(session_factory) == before
