"""Consumer webhook slice (sprint-1/01 Slice 4): endpoint CRUD + signed delivery
+ retry/dead-letter/auto-disable + multi-number routing.

Delivery is exercised directly (`enqueue_event` writes the durable row on the
test session; `dispatch` runs one attempt) rather than through the eager Celery
task, whose `SessionLocal` binds to the app DB, not the test engine.
"""
import hashlib
import hmac
import json

import pytest

from modules.omnichannel.models import Channel, WebhookDelivery, WebhookEndpoint
from modules.omnichannel.services import webhook_delivery as wd
from modules.omnichannel.services.webhook_delivery import dispatch, enqueue_event, sign_body
from modules.omnichannel.services.webhook_service import (
    AUTO_DISABLE_THRESHOLD,
    WebhookError,
    WebhookService,
)
from tests.test_omnichannel_conversations import _auth
from tests.test_omnichannel_webhooks import _channel_id, _process, _wa_payload


class _Resp:
    def __init__(self, status_code: int):
        self.status_code = status_code


@pytest.fixture
def _capture_post(monkeypatch):
    """Patch the outbound POST; return the recorded calls + a settable status."""
    calls = []
    state = {"status": 200, "raise": None}

    def fake_post(url, content=None, headers=None, timeout=None):
        calls.append({"url": url, "body": content, "headers": headers})
        if state["raise"]:
            raise state["raise"]
        return _Resp(state["status"])

    monkeypatch.setattr(wd.httpx, "post", fake_post)
    return calls, state


def _make_channel(session_factory, phone_number_id: str, name="Num") -> str:
    from app.models import DEFAULT_TENANT_ID
    from modules.omnichannel.models import Workspace

    db = session_factory()
    try:
        ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID).first()
        ch = Channel(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=ws.id,
            channel_type="WHATSAPP",
            name=name,
            phone_number_id=phone_number_id,
            is_active=True,
        )
        db.add(ch)
        db.commit()
        return ch.id
    finally:
        db.close()


def _create_endpoint(session_factory, channel_id, events, url="https://consumer.example/hook"):
    from app.models import DEFAULT_TENANT_ID

    db = session_factory()
    try:
        row, secret = WebhookService(db).create(
            DEFAULT_TENANT_ID, channel_id, "EMS", url, events, created_by=None
        )
        return row.id, secret
    finally:
        db.close()


# ── CRUD + validation via the API ────────────────────────────────────────────
def test_create_and_list_via_api(client, session_factory):
    _from_seed = _channel_id  # noqa
    from tests.test_omnichannel_webhooks import _seed_thread

    _seed_thread(session_factory, messages=[{}])
    channel_id = _channel_id(session_factory)
    h = _auth(client)

    res = client.post(
        f"/omnichannel/channels/{channel_id}/webhooks",
        headers=h,
        json={"name": "EMS", "url": "https://ems.example/wa", "events": ["message.inbound"]},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["signingSecret"].startswith("whsec_")
    ep = body["endpoint"]
    assert ep["status"] == "ACTIVE" and ep["events"] == ["message.inbound"]

    lst = client.get(f"/omnichannel/channels/{channel_id}/webhooks", headers=h).json()["data"]
    assert len(lst) == 1
    assert "signingSecret" not in lst[0]  # secret never re-listed


def test_create_rejects_bad_url(client, session_factory):
    from tests.test_omnichannel_webhooks import _seed_thread

    _seed_thread(session_factory, messages=[{}])
    channel_id = _channel_id(session_factory)
    h = _auth(client)

    for url in ("http://ems.example/wa", "https://localhost/wa", "https://127.0.0.1/wa"):
        res = client.post(
            f"/omnichannel/channels/{channel_id}/webhooks",
            headers=h,
            json={"name": "X", "url": url, "events": ["message.inbound"]},
        )
        assert res.status_code == 400, url

    bad_event = client.post(
        f"/omnichannel/channels/{channel_id}/webhooks",
        headers=h,
        json={"name": "X", "url": "https://ems.example/wa", "events": ["nope"]},
    )
    assert bad_event.status_code == 400


def test_ssrf_guard_unit():
    from modules.omnichannel.services.webhook_service import validate_callback_url

    blocked = (
        "http://x.example",        # non-https
        "https://192.168.1.10/h",  # private literal
        "https://10.0.0.1",        # private literal
        "https://169.254.169.254", # link-local (cloud metadata)
        "https://localhost",       # localhost name
        "https://2130706433/",     # decimal-encoded 127.0.0.1 → resolves + blocks
        "https://0x7f000001/",     # hex-encoded 127.0.0.1 → resolves + blocks
    )
    for url in blocked:
        with pytest.raises(WebhookError):
            validate_callback_url(url)

    # A normal public https URL passes (host resolves off-box or DNS-fails-open).
    assert validate_callback_url("https://consumer.example/hook") == "https://consumer.example/hook"


# ── Signed delivery on inbound ───────────────────────────────────────────────
def test_inbound_message_forwards_signed(client, session_factory, _capture_post):
    from tests.test_omnichannel_webhooks import _seed_thread

    _seed_thread(session_factory, messages=[{}])
    channel_id = _channel_id(session_factory)
    endpoint_id, secret = _create_endpoint(session_factory, channel_id, ["message.inbound"])
    calls, _ = _capture_post

    # Inbound → hook creates a PENDING delivery row (committed).
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.fw-1", text="Hi EMS"))

    db = session_factory()
    try:
        rows = db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == endpoint_id).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.event_type == "message.inbound"
        assert row.payload_json["data"]["message"]["body"] == "Hi EMS"
        outcome = dispatch(db, row.id)
        assert outcome == "success"
        db.refresh(row)
        assert row.status == "SUCCESS" and row.response_status == 200
    finally:
        db.close()

    # Exactly one signed POST, signature verifies with the returned secret.
    assert len(calls) == 1
    hdrs = calls[0]["headers"]
    assert hdrs["X-Fx-Event-Type"] == "message.inbound"
    expected = sign_body(secret, hdrs["X-Fx-Timestamp"], calls[0]["body"])
    assert hmac.compare_digest(hdrs["X-Fx-Signature"], expected)
    # Envelope shape.
    env = json.loads(calls[0]["body"])
    assert env["type"] == "message.inbound" and env["channelId"] == channel_id
    assert env["id"] == "wamid.fw-1"


def test_status_receipt_forwards(client, session_factory, _capture_post):
    from tests.test_omnichannel_webhooks import _seed_thread

    _seed_thread(
        session_factory,
        messages=[{"body": "out", "sender_type": "AGENT", "external_message_id": "wamid.o1", "delivery_status": "SENT"}],
    )
    channel_id = _channel_id(session_factory)
    endpoint_id, _ = _create_endpoint(session_factory, channel_id, ["message.status"])

    _process(session_factory, channel_id, _wa_payload(statuses=[{"id": "wamid.o1", "status": "delivered"}]))

    db = session_factory()
    try:
        row = db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == endpoint_id).one()
        assert row.event_type == "message.status"
        assert row.payload_json["data"]["deliveryStatus"] == "DELIVERED"
    finally:
        db.close()


def _reaction_payload(*, target_wamid, emoji, from_="60123456789", wamid="wamid.rx"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"wa_id": from_, "profile": {"name": "Sarah Chen"}}],
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": from_,
                                    "timestamp": "1717550000",
                                    "type": "reaction",
                                    "reaction": {"message_id": target_wamid, "emoji": emoji},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def test_reaction_forwards_to_consumer(client, session_factory, _capture_post):
    """A contact reaction fans out on the consumer webhook (AC-12-20) with the
    documented data shape — targeting OUR durable id, never a raw wamid."""
    from tests.test_omnichannel_conversations import _seed_thread

    _seed_thread(
        session_factory,
        messages=[{"body": "out", "sender_type": "AGENT", "external_message_id": "wamid.rtgt", "delivery_status": "DELIVERED"}],
    )
    channel_id = _channel_id(session_factory)
    endpoint_id, _ = _create_endpoint(session_factory, channel_id, ["message.reaction"])

    _process(session_factory, channel_id, _reaction_payload(target_wamid="wamid.rtgt", emoji="👍"))

    db = session_factory()
    try:
        from modules.omnichannel.models import ConversationMessage

        target = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.external_message_id == "wamid.rtgt")
            .one()
        )
        row = db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == endpoint_id).one()
        assert row.event_type == "message.reaction"
        data = row.payload_json["data"]
        assert data["targetMessageId"] == target.id  # our durable id, not the wamid
        assert data["emoji"] == "👍" and data["reactorType"] == "CONTACT"
        assert data["removed"] is False
    finally:
        db.close()


def test_unsubscribed_event_not_forwarded(client, session_factory, _capture_post):
    from tests.test_omnichannel_webhooks import _seed_thread

    _seed_thread(session_factory, messages=[{}])
    channel_id = _channel_id(session_factory)
    # Endpoint only wants status — an inbound message must NOT enqueue.
    _create_endpoint(session_factory, channel_id, ["message.status"])
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.skip-1"))

    db = session_factory()
    try:
        assert db.query(WebhookDelivery).count() == 0
    finally:
        db.close()


# ── Retry + dead-letter + auto-disable ───────────────────────────────────────
def test_retry_then_dead_letter_and_auto_disable(session_factory, _capture_post):
    channel_id = _make_channel(session_factory, "pn-dead")
    endpoint_id, _ = _create_endpoint(session_factory, channel_id, ["message.inbound"])
    calls, state = _capture_post
    state["status"] = 500  # consumer always fails

    db = session_factory()
    try:
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        # One event → one delivery row.
        enqueue_event(db, channel, "message.inbound", "evt-dead", {"x": 1})
        row = db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == endpoint_id).one()

        outcomes = []
        for _ in range(wd.MAX_ATTEMPTS):
            db.refresh(row)
            if row.status != "PENDING":
                break
            row.next_attempt_at = None  # bypass backoff wait for the test
            outcomes.append(dispatch(db, row.id))
        assert outcomes[-1] == "dead"
        db.refresh(row)
        assert row.status == "FAILED"
        assert row.attempt_count == wd.MAX_ATTEMPTS  # attempts preserved

        # Endpoint failure counter bumped once (one dead-lettered delivery).
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).one()
        assert ep.consecutive_failures == 1
    finally:
        db.close()


def test_auto_disable_after_threshold(session_factory, _capture_post):
    channel_id = _make_channel(session_factory, "pn-auto")
    endpoint_id, _ = _create_endpoint(session_factory, channel_id, ["message.inbound"])
    _, state = _capture_post
    state["status"] = 500

    db = session_factory()
    try:
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        for i in range(AUTO_DISABLE_THRESHOLD):
            enqueue_event(db, channel, "message.inbound", f"evt-{i}", {"i": i})
            row = (
                db.query(WebhookDelivery)
                .filter(WebhookDelivery.endpoint_id == endpoint_id, WebhookDelivery.event_id == f"evt-{i}")
                .one()
            )
            for _ in range(wd.MAX_ATTEMPTS):
                db.refresh(row)
                if row.status != "PENDING":
                    break
                row.next_attempt_at = None
                dispatch(db, row.id)
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).one()
        assert ep.consecutive_failures >= AUTO_DISABLE_THRESHOLD
        assert ep.status == "AUTO_DISABLED"
        assert ep.disabled_reason
    finally:
        db.close()


def test_success_resets_failure_counter(session_factory, _capture_post):
    channel_id = _make_channel(session_factory, "pn-reset")
    endpoint_id, _ = _create_endpoint(session_factory, channel_id, ["message.inbound"])
    _, state = _capture_post

    db = session_factory()
    try:
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).one()
        ep.consecutive_failures = 3
        db.commit()

        state["status"] = 200
        enqueue_event(db, channel, "message.inbound", "evt-ok", {"x": 1})
        row = db.query(WebhookDelivery).filter(WebhookDelivery.event_id == "evt-ok").one()
        assert dispatch(db, row.id) == "success"
        db.refresh(ep)
        assert ep.consecutive_failures == 0 and ep.last_success_at is not None
    finally:
        db.close()


# ── Multi-number routing (the AC-01-20 pivot) ────────────────────────────────
def test_multi_number_routing_isolates(session_factory, _capture_post):
    """Two numbers → an event tagged with number A's phone_number_id routes to
    A's channel + A's endpoints only, even if POSTed to B's URL path."""
    from app.models import DEFAULT_TENANT_ID

    ch_a = _make_channel(session_factory, "pn-AAA", name="Number A")
    ch_b = _make_channel(session_factory, "pn-BBB", name="Number B")
    ep_a, _ = _create_endpoint(session_factory, ch_a, ["message.inbound"], url="https://a.example/hook")
    ep_b, _ = _create_endpoint(session_factory, ch_b, ["message.inbound"], url="https://b.example/hook")

    # Payload carries A's phone_number_id but is delivered to B's webhook path.
    payload = _wa_payload(wamid="wamid.route-1", from_="60100000001", text="for A")
    payload["entry"][0]["changes"][0]["value"]["metadata"] = {"phone_number_id": "pn-AAA"}
    _process(session_factory, ch_b, payload)  # URL says B, payload says A

    db = session_factory()
    try:
        a_rows = db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == ep_a).all()
        b_rows = db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == ep_b).all()
        assert len(a_rows) == 1  # routed to A by phone_number_id
        assert len(b_rows) == 0  # B's endpoint not touched
        assert a_rows[0].payload_json["channelId"] == ch_a
    finally:
        db.close()


# ── Endpoint lifecycle: rotate / disable / delete ────────────────────────────
def test_rotate_disable_delete(client, session_factory, _capture_post):
    from tests.test_omnichannel_webhooks import _seed_thread

    _seed_thread(session_factory, messages=[{}])
    channel_id = _channel_id(session_factory)
    endpoint_id, secret1 = _create_endpoint(session_factory, channel_id, ["message.inbound"])
    h = _auth(client)

    rot = client.post(f"/omnichannel/webhooks/{endpoint_id}/rotate", headers=h)
    assert rot.status_code == 200
    assert rot.json()["signingSecret"] != secret1

    # Disable → an inbound must NOT enqueue.
    dis = client.post(f"/omnichannel/webhooks/{endpoint_id}/disable", headers=h)
    assert dis.json()["status"] == "DISABLED"
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.dis-1"))
    db = session_factory()
    try:
        assert db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == endpoint_id).count() == 0
    finally:
        db.close()

    # Re-enable clears counters.
    en = client.post(f"/omnichannel/webhooks/{endpoint_id}/enable", headers=h)
    assert en.json()["status"] == "ACTIVE"

    dele = client.delete(f"/omnichannel/webhooks/{endpoint_id}", headers=h)
    assert dele.status_code == 204
    assert client.get(f"/omnichannel/channels/{channel_id}/webhooks", headers=h).json()["data"] == []
