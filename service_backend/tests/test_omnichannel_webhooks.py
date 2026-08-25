"""Webhook pipeline tests - plan 05 Phase B-4.

Receiver: verify handshake, signature gate, fast-ACK enqueue.
Worker logic (InboundService driven directly): contact resolution & stitching,
idempotency, CSW re-open, delivery receipts, reply context, realtime publish.
"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services import realtime
from tests.test_omnichannel_conversations import _auth, _seed_thread


@pytest.fixture(autouse=True)
def _fake_realtime():
    client = fakeredis.FakeRedis(decode_responses=True)
    realtime.set_client(client)
    yield client
    realtime.set_client(None)


def _channel_id(session_factory):
    from modules.omnichannel.models import Channel

    db = session_factory()
    cid = db.query(Channel).first().id
    db.close()
    return cid


def _wa_payload(
    *,
    wamid="wamid.in-1",
    from_="60103069306",
    name="Test Customer",
    text="Hello!",
    context_id=None,
    statuses=None,
):
    value = {}
    if statuses is None:
        msg = {
            "id": wamid,
            "from": from_,
            "timestamp": "1717550000",
            "type": "text",
            "text": {"body": text},
        }
        if context_id:
            msg["context"] = {"id": context_id}
        value = {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": from_, "profile": {"name": name}}],
            "messages": [msg],
        }
    else:
        value = {"messaging_product": "whatsapp", "statuses": statuses}
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": value}]}],
    }


def _process(session_factory, channel_id, payload):
    from modules.omnichannel.services.inbound_service import InboundService

    db = session_factory()
    try:
        return InboundService(db).process_payload(channel_id, payload)
    finally:
        db.close()


# ── Receiver ─────────────────────────────────────────────────────────────────
def test_verify_handshake(client):
    res = client.get(
        "/omnichannel/webhooks/chn-x",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.meta_webhook_verify_token,
            "hub.challenge": "12345",
        },
    )
    assert res.status_code == 200
    assert res.text == "12345"

    bad = client.get(
        "/omnichannel/webhooks/chn-x",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "x"},
    )
    assert bad.status_code == 403


def test_post_enqueues_fast_ack(client, monkeypatch):
    from modules.omnichannel import worker

    calls = []
    monkeypatch.setattr(
        worker.process_inbound_webhook, "delay", lambda *a, **k: calls.append(a)
    )
    res = client.post("/omnichannel/webhooks/chn-1", json=_wa_payload())
    assert res.status_code == 200
    assert res.json() == {"status": "queued"}
    assert calls and calls[0][0] == "chn-1"


def test_post_signature_gate(client, monkeypatch):
    from modules.omnichannel import worker

    monkeypatch.setattr(worker.process_inbound_webhook, "delay", lambda *a, **k: None)
    monkeypatch.setattr(settings, "meta_app_secret", "topsecret")

    body = json.dumps(_wa_payload()).encode()
    good = hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()

    ok = client.post(
        "/omnichannel/webhooks/chn-1",
        content=body,
        headers={"X-Hub-Signature-256": f"sha256={good}", "Content-Type": "application/json"},
    )
    assert ok.status_code == 200

    bad = client.post(
        "/omnichannel/webhooks/chn-1",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"},
    )
    assert bad.status_code == 403

    unsigned = client.post("/omnichannel/webhooks/chn-1", content=body)
    assert unsigned.status_code == 403


# ── Worker: inbound messages ─────────────────────────────────────────────────
def test_inbound_creates_contact_identity_message(client, session_factory, _fake_realtime):
    _seed_thread(session_factory, messages=[{}])  # ensures a channel exists
    channel_id = _channel_id(session_factory)
    sub = _fake_realtime.pubsub()
    sub.psubscribe("omnichannel:ws:*")
    sub.get_message(timeout=0.1)  # consume the subscribe ack

    counters = _process(
        session_factory,
        channel_id,
        _wa_payload(wamid="wamid.new-1", from_="60103069306", name="Priya Raj", text="Hi there"),
    )
    assert counters["messages"] == 1

    h = _auth(client)
    threads = client.get("/omnichannel/contacts?search=Priya", headers=h).json()["data"]
    assert len(threads) == 1
    t = threads[0]
    assert t["name"] == "Priya Raj"
    assert t["phone"] == "+60103069306"
    assert t["status"] == "OPEN"
    assert t["unreadCount"] == 1
    assert t["cswExpiresAt"] is not None

    msgs = client.get(f"/omnichannel/contacts/{t['id']}/messages", headers=h).json()
    assert msgs[-1]["body"] == "Hi there"
    assert msgs[-1]["senderType"] == "CONTACT"

    # Realtime event fanned out to the workspace room.
    evt = sub.get_message(timeout=1)
    assert evt and json.loads(evt["data"])["type"] == "message.created"


def test_inbound_idempotent_by_wamid(client, session_factory):
    _seed_thread(session_factory, messages=[{}])
    channel_id = _channel_id(session_factory)
    payload = _wa_payload(wamid="wamid.dup-1", from_="60111222333", name="Dup Person")

    first = _process(session_factory, channel_id, payload)
    second = _process(session_factory, channel_id, payload)
    assert first["messages"] == 1
    assert second["messages"] == 0 and second["skipped"] == 1

    threads = client.get("/omnichannel/contacts?search=Dup", headers=_auth(client)).json()["data"]
    assert threads[0]["unreadCount"] == 1  # one bubble, not two


def test_inbound_stitches_existing_contact_by_phone(client, session_factory):
    # Seeded contact phone +60123456789 - webhook from 60123456789 must stitch,
    # not create a duplicate contact.
    cid = _seed_thread(session_factory, name="Sarah Chen", phone="+60123456789", messages=[{}])
    channel_id = _channel_id(session_factory)

    _process(
        session_factory,
        channel_id,
        _wa_payload(wamid="wamid.stitch-1", from_="60123456789", name="Sarah C", text="It's me"),
    )

    h = _auth(client)
    threads = client.get("/omnichannel/contacts?search=Sarah", headers=h).json()["data"]
    assert [t["id"] for t in threads] == [cid]  # same thread, no duplicate
    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=h).json()
    assert msgs[-1]["body"] == "It's me"

    # Second inbound reuses the identity row (unique channel+wa_id).
    _process(
        session_factory,
        channel_id,
        _wa_payload(wamid="wamid.stitch-2", from_="60123456789", text="again"),
    )
    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=h).json()
    assert msgs[-1]["body"] == "again"


def test_inbound_reopens_closed_thread_and_resets_csw(client, session_factory):
    from modules.omnichannel.models import Contact
    from modules.omnichannel.services import statuses as st

    cid = _seed_thread(session_factory, phone="+60777888999", messages=[{}])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    db.query(Contact).filter(Contact.id == cid).update(
        {
            "status_id": st.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "CLOSED"),
            "csw_expires_at": datetime.now(timezone.utc) - timedelta(hours=5),
        }
    )
    db.commit()
    db.close()

    _process(
        session_factory,
        channel_id,
        _wa_payload(wamid="wamid.reopen-1", from_="60777888999", text="Hello again"),
    )

    t = client.get(f"/omnichannel/contacts/{cid}", headers=_auth(client)).json()
    assert t["status"] == "OPEN"
    expires = datetime.fromisoformat(t["cswExpiresAt"].replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    assert expires > datetime.now(timezone.utc) + timedelta(hours=23)


def test_inbound_reply_context_maps_quote(client, session_factory):
    cid = _seed_thread(
        session_factory,
        phone="+60123123123",
        messages=[
            {
                "body": "Saturday is free - move it?",
                "sender_type": "AGENT",
                "external_message_id": "wamid.agent-q",
                "delivery_status": "READ",
            }
        ],
    )
    channel_id = _channel_id(session_factory)

    _process(
        session_factory,
        channel_id,
        _wa_payload(
            wamid="wamid.reply-1",
            from_="60123123123",
            text="Yes please!",
            context_id="wamid.agent-q",
        ),
    )

    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=_auth(client)).json()
    assert msgs[-1]["body"] == "Yes please!"
    assert msgs[-1]["replyTo"]["body"] == "Saturday is free - move it?"
    assert msgs[-1]["replyTo"]["senderType"] == "AGENT"


# ── Worker: delivery receipts ────────────────────────────────────────────────
def test_status_receipts_move_forward_only(client, session_factory):
    cid = _seed_thread(
        session_factory,
        messages=[
            {
                "body": "Out msg",
                "sender_type": "AGENT",
                "external_message_id": "wamid.out-1",
                "delivery_status": "SENT",
            }
        ],
    )
    channel_id = _channel_id(session_factory)

    def status_payload(s, errors=None):
        row = {"id": "wamid.out-1", "status": s, "timestamp": "1717550001"}
        if errors:
            row["errors"] = errors
        return _wa_payload(statuses=[row])

    h = _auth(client)
    _process(session_factory, channel_id, status_payload("delivered"))
    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=h).json()
    assert msgs[-1]["deliveryStatus"] == "DELIVERED"

    _process(session_factory, channel_id, status_payload("read"))
    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=h).json()
    assert msgs[-1]["deliveryStatus"] == "READ"

    # Late DELIVERED after READ is dropped.
    res = _process(session_factory, channel_id, status_payload("delivered"))
    assert res["skipped"] == 1
    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=h).json()
    assert msgs[-1]["deliveryStatus"] == "READ"


def test_status_failed_carries_error(client, session_factory):
    cid = _seed_thread(
        session_factory,
        messages=[
            {
                "body": "Out msg",
                "sender_type": "AGENT",
                "external_message_id": "wamid.out-2",
                "delivery_status": "SENT",
            }
        ],
    )
    channel_id = _channel_id(session_factory)

    _process(
        session_factory,
        channel_id,
        _wa_payload(
            statuses=[
                {
                    "id": "wamid.out-2",
                    "status": "failed",
                    "errors": [{"code": 131047, "title": "Re-engagement message"}],
                }
            ]
        ),
    )
    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=_auth(client)).json()
    assert msgs[-1]["deliveryStatus"] == "FAILED"
    assert msgs[-1]["errorCode"] == "131047"
    assert "Re-engagement" in msgs[-1]["errorMessage"]


def test_unknown_channel_dropped(session_factory):
    res = _process(session_factory, "no-such-channel", _wa_payload())
    assert res == {"messages": 0, "statuses": 0, "skipped": 0}


# ── StorageService URL shape (Phase B-6) ────────────────────────────────────
def test_local_storage_put_url_shape(client, tmp_path, monkeypatch):
    # The legacy unauthenticated /omnichannel/media/{path} serve route was removed
    # in plan 12 (it co-served outbound blobs under media_root with no auth). All
    # blobs now flow through the authed GET /omnichannel/media/{message_id}. This
    # only asserts the LocalDiskStorage.put() URL SHAPE (still used by the URL
    # contract), not unauthenticated serving.
    from modules.omnichannel.services.storage import LocalDiskStorage

    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    storage = LocalDiskStorage(str(tmp_path))
    url = storage.put("default/media-1", b"fake-image-bytes", "image/jpeg")
    assert "/omnichannel/media/default/media-1-" in url
    assert url.endswith(".jpg")
    # The path is no longer served unauthenticated.
    rel = url.split("/omnichannel/media/")[1]
    assert client.get(f"/omnichannel/media/{rel}").status_code in (401, 404)


def test_media_route_blocks_traversal(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    res = client.get("/omnichannel/media/../../etc/passwd")
    assert res.status_code == 404


def test_inbound_media_message_stores_blob(client, session_factory, tmp_path, monkeypatch):
    """Media inbound: adapter.fetch_media → StorageService → media_url persisted."""
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
    from modules.omnichannel.services import storage as storage_module
    from modules.omnichannel.services.storage import LocalDiskStorage

    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    storage_module.set_storage(LocalDiskStorage(str(tmp_path)))
    monkeypatch.setattr(
        WhatsAppCloudAdapter,
        "fetch_media",
        lambda self, creds, media_id: {"content": b"img", "mime_type": "image/png"},
    )

    cid = _seed_thread(session_factory, phone="+60555666777", messages=[{}])
    channel_id = _channel_id(session_factory)
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "messages", "value": {
            "contacts": [{"wa_id": "60555666777", "profile": {"name": "Pic Sender"}}],
            "messages": [{
                "id": "wamid.media-1", "from": "60555666777", "type": "image",
                "image": {"id": "media-123", "caption": "Floor plan"},
            }],
        }}]}],
    }
    _process(session_factory, channel_id, payload)
    storage_module.set_storage(None)

    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=_auth(client)).json()
    assert msgs[-1]["messageType"] == "IMAGE"
    assert msgs[-1]["body"] == "Floor plan"
    assert "/omnichannel/media/" in msgs[-1]["mediaUrl"]
