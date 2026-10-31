"""Plan 38 gap 3 - the `message.outbound` consumer webhook event, plus the
`message.status` SENT/FAILED companion (AC-38-01..12).

RED tests written BEFORE the implementation. Everything is asserted from the
outside: `webhook_deliveries` rows + their payload, or the HTTP route. No
private helper of the (unwritten) implementation is referenced.

Each test names its AC id(s). Every test seeds its own channel / contact / key
/ endpoints.
"""
from pathlib import Path

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import (
    Channel,
    ConversationMessage,
    WebhookDelivery,
    WebhookEndpoint,
)
from modules.omnichannel.security import encrypt_credentials
from modules.omnichannel.services import idempotency
from modules.omnichannel.services import webhook_delivery as wd
from modules.omnichannel.services.webhook_service import WebhookService
from tests.test_omnichannel_api_gateway import (
    _auth,
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
)
from tests.test_omnichannel_broadcasts import (
    _broadcasts_base,
    _create_payload,
    _ensure_template,
    _fixture,
)
from tests.test_omnichannel_webhooks import _process, _wa_payload

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 128
HOOK_URL = "https://hooks.example.com/w"
OUTBOUND = "message.outbound"
REPO_ROOT = Path(__file__).resolve().parents[2]


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


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
    """Never let an eager delivery attempt reach the network."""

    class _Resp:
        status_code = 200

    monkeypatch.setattr(wd.httpx, "post", lambda *a, **k: _Resp())


# ── helpers ──────────────────────────────────────────────────────────────────
def _register(client, hdr, events, url=HOOK_URL, name="w"):
    """Register an endpoint on the API key's workspace channel (public route)."""
    return client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": name, "url": url, "events": list(events)},
        headers=hdr,
    )


def _rig(client, session_factory, phone, *, events=(OUTBOUND,), pn="pn-test"):
    """Workspace + channel + open contact + API key (+ one endpoint on `events`)."""
    ws = _default_workspace_id(session_factory)
    channel_id = _seed_channel(session_factory, ws, phone_number_id=pn)
    cid = _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    key = _mint(client, ws).json()["fullKey"]
    hdr = {"Authorization": f"Bearer {key}"}
    endpoint_id = None
    if events:
        reg = _register(client, hdr, events)
        assert reg.status_code == 201, reg.text
        endpoint_id = reg.json()["endpoint"]["id"]
    return {"ws": ws, "channel_id": channel_id, "cid": cid, "hdr": hdr, "ep": endpoint_id}


def _api_text(client, hdr, phone, body="Hello from api", extra_headers=None):
    return client.post(
        "/api/v1/omnichannel/messages",
        json={"to": phone, "type": "text", "text": {"body": body}},
        headers={**hdr, **(extra_headers or {})},
    )


def _deliveries(session_factory, event_type=OUTBOUND):
    db = session_factory()
    try:
        rows = db.query(WebhookDelivery).filter(WebhookDelivery.event_type == event_type).all()
        return [
            {
                "endpoint_id": r.endpoint_id,
                "event_id": r.event_id,
                "payload": r.payload_json,
            }
            for r in rows
        ]
    finally:
        db.close()


def _only_outbound(session_factory):
    rows = _deliveries(session_factory)
    assert len(rows) == 1, f"expected exactly one {OUTBOUND} delivery, got {len(rows)}"
    return rows[0]


def _external_id(session_factory, message_id):
    db = session_factory()
    try:
        return (
            db.query(ConversationMessage)
            .filter(ConversationMessage.id == message_id)
            .first()
            .external_message_id
        )
    finally:
        db.close()


def _insert_foreign_endpoint(session_factory, *, tenant_id, workspace_id, channel_id, events):
    db = session_factory()
    try:
        db.add(
            WebhookEndpoint(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                channel_id=channel_id,
                name="foreign",
                url="https://foreign.example.com/hook",
                secret_encrypted="x",
                events_json=list(events),
                status="ACTIVE",
            )
        )
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-01 - the event type is valid, opt-in
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_01_public_route_accepts_message_outbound(client, session_factory):
    r = _rig(client, session_factory, "+601234567801", events=())
    reg = _register(client, r["hdr"], [OUTBOUND, "message.inbound"])
    assert reg.status_code == 201, reg.text
    assert set(reg.json()["endpoint"]["events"]) == {OUTBOUND, "message.inbound"}
    # control: an unknown event name is still rejected (so acceptance above is real)
    bad = _register(client, r["hdr"], ["message.nope"])
    assert bad.status_code in (400, 422)


def test_ac_38_01_session_route_accepts_message_outbound(client, session_factory):
    r = _rig(client, session_factory, "+601234567802", events=())
    res = client.post(
        f"/omnichannel/channels/{r['channel_id']}/webhooks",
        headers=_auth(client),
        json={"name": "EMS", "url": HOOK_URL, "events": [OUTBOUND]},
    )
    assert res.status_code == 201, res.text
    assert res.json()["endpoint"]["events"] == [OUTBOUND]
    bad = client.post(
        f"/omnichannel/channels/{r['channel_id']}/webhooks",
        headers=_auth(client),
        json={"name": "EMS", "url": HOOK_URL, "events": ["message.nope"]},
    )
    assert bad.status_code == 400


def test_ac_38_01_opt_in_unsubscribed_endpoint_gets_nothing(client, session_factory):
    r = _rig(client, session_factory, "+601234567803", events=("message.inbound", "message.status"))
    # a second endpoint DOES subscribe: proves the send emitted at all (control)
    assert _register(client, r["hdr"], [OUTBOUND], name="opt-in").status_code == 201
    assert _api_text(client, r["hdr"], "+601234567803").status_code == 202

    rows = _deliveries(session_factory)
    assert len(rows) == 1
    assert rows[0]["endpoint_id"] != r["ep"], "endpoint without message.outbound must get none"


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-02 / AC-38-03 - one delivery per ACTIVE subscribed endpoint, envelope
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_02_03_api_text_one_per_active_endpoint_envelope_and_source(client, session_factory):
    r = _rig(client, session_factory, "+601234567810")
    ep2 = _register(client, r["hdr"], [OUTBOUND], name="second").json()["endpoint"]["id"]
    off = _register(client, r["hdr"], [OUTBOUND], name="off").json()["endpoint"]["id"]
    assert client.post(f"/api/v1/omnichannel/webhooks/{off}/disable", headers=r["hdr"]).status_code == 200

    sent = _api_text(client, r["hdr"], "+601234567810", body="Hi envelope")
    assert sent.status_code == 202, sent.text
    mid = sent.json()["id"]

    rows = _deliveries(session_factory)
    assert sorted(x["endpoint_id"] for x in rows) == sorted([r["ep"], ep2])  # not the DISABLED one
    for row in rows:
        assert row["event_id"] == f"{mid}:outbound"
        env = row["payload"]
        assert env["id"] == f"{mid}:outbound"
        assert env["type"] == OUTBOUND
        assert env["channelId"] == r["channel_id"]
        assert set(env["data"]) == {"message", "contact", "source"}
        assert env["data"]["source"] == "api"
        assert env["data"]["message"]["id"] == mid
        assert env["data"]["message"]["body"] == "Hi envelope"
        assert env["data"]["message"]["senderType"] != "CONTACT"
        assert env["data"]["contact"]["id"] == r["cid"]


def test_ac_38_03_event_id_stable_across_two_sends_is_per_message(client, session_factory):
    r = _rig(client, session_factory, "+601234567811")
    a = _api_text(client, r["hdr"], "+601234567811", body="one").json()["id"]
    b = _api_text(client, r["hdr"], "+601234567811", body="two").json()["id"]
    ids = sorted(x["event_id"] for x in _deliveries(session_factory))
    assert ids == sorted([f"{a}:outbound", f"{b}:outbound"])


def test_ac_38_02_api_template(client, session_factory):
    r = _rig(client, session_factory, "+601234567812")
    _ensure_template(session_factory, r["channel_id"], name="tpl_out")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+601234567812",
            "type": "template",
            "template": {"name": "tpl_out", "variables": ["Sam", "shipped"]},
        },
        headers=r["hdr"],
    )
    assert res.status_code == 202, res.text
    row = _only_outbound(session_factory)
    assert row["event_id"] == f"{res.json()['id']}:outbound"
    assert row["payload"]["data"]["source"] == "api"
    assert row["payload"]["data"]["message"]["messageType"] == "TEMPLATE"


def test_ac_38_02_04_api_media_has_absolute_media_url(client, session_factory, monkeypatch):
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    monkeypatch.setattr(PublicGatewayService, "_fetch_url", lambda self, url: PNG)
    r = _rig(client, session_factory, "+601234567813")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+601234567813",
            "type": "image",
            "media": {"url": "https://files.example.com/a.png", "caption": "pic"},
        },
        headers=r["hdr"],
    )
    assert res.status_code == 202, res.text
    mid = res.json()["id"]
    row = _only_outbound(session_factory)
    msg = row["payload"]["data"]["message"]
    assert row["payload"]["data"]["source"] == "api"
    # AC-38-04: same absolute, API-key-authed form as message.inbound
    assert msg["mediaUrl"].startswith("http")
    assert f"/omnichannel/media/{mid}" in msg["mediaUrl"]
    assert msg["mimeType"] == "image/png"
    assert "mediaMime" not in msg


def test_ac_38_02_api_structured_location(client, session_factory):
    r = _rig(client, session_factory, "+601234567814")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+601234567814", "type": "location", "location": {"lat": 3.1, "lng": 101.6, "name": "HQ"}},
        headers=r["hdr"],
    )
    assert res.status_code == 202, res.text
    row = _only_outbound(session_factory)
    assert row["event_id"] == f"{res.json()['id']}:outbound"
    assert row["payload"]["data"]["source"] == "api"


def test_ac_38_02_workflow_send_node_source_workflow(client, session_factory):
    from modules.omnichannel.services.workflow_actions import omnichannel_send_message

    r = _rig(client, session_factory, "+601234567815")
    db = session_factory()
    try:
        out = omnichannel_send_message(
            db, DEFAULT_TENANT_ID, {"contactId": r["cid"], "mode": "text", "message": "from workflow"}, {}
        )
    finally:
        db.close()
    row = _only_outbound(session_factory)
    assert row["event_id"] == f"{out['messageId']}:outbound"
    assert row["payload"]["data"]["source"] == "workflow"
    assert row["payload"]["data"]["message"]["body"] == "from workflow"


PDF = b"%PDF-1.4\n" + b"0" * 128


@pytest.mark.parametrize(
    "kind,payload_bytes,mime_fragment",
    [("voice", WEBM, None), ("document", PDF, "pdf")],
)
def test_ac_38_02_api_voice_and_document_media(
    client, session_factory, monkeypatch, kind, payload_bytes, mime_fragment
):
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    monkeypatch.setattr(PublicGatewayService, "_fetch_url", lambda self, url: payload_bytes)
    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.transcode_voice",
        lambda content: b"OggS" + b"\x00" * 64,
    )
    phone = "+601234567871" if kind == "voice" else "+601234567872"
    r = _rig(client, session_factory, phone)
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": phone, "type": kind, "media": {"url": "https://files.example.com/f"}},
        headers=r["hdr"],
    )
    assert res.status_code == 202, res.text
    mid = res.json()["id"]
    row = _only_outbound(session_factory)
    msg = row["payload"]["data"]["message"]
    assert row["event_id"] == f"{mid}:outbound"
    assert row["payload"]["data"]["source"] == "api"
    assert msg["mediaUrl"].startswith("http") and f"/omnichannel/media/{mid}" in msg["mediaUrl"]
    if mime_fragment:
        assert mime_fragment in msg["mimeType"]


def test_ac_38_02_api_interactive(client, session_factory):
    r = _rig(client, session_factory, "+601234567873")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+601234567873",
            "type": "interactive",
            "interactive": {"kind": "buttons", "body": "Pick", "buttons": [{"id": "a", "title": "A"}]},
        },
        headers=r["hdr"],
    )
    assert res.status_code == 202, res.text
    row = _only_outbound(session_factory)
    assert row["event_id"] == f"{res.json()['id']}:outbound"
    assert row["payload"]["data"]["source"] == "api"


def test_ac_38_02_api_contacts(client, session_factory):
    r = _rig(client, session_factory, "+601234567874")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+601234567874",
            "type": "contacts",
            "contacts": [{"name": "Jane Doe", "phones": [{"phone": "+60123", "type": "CELL"}]}],
        },
        headers=r["hdr"],
    )
    assert res.status_code == 202, res.text
    row = _only_outbound(session_factory)
    assert row["event_id"] == f"{res.json()['id']}:outbound"
    assert row["payload"]["data"]["source"] == "api"


def test_ac_38_05_sandbox_row_emits_no_outbound_and_no_status(client, session_factory):
    from modules.omnichannel.services.workflow_actions import omnichannel_send_message

    r = _rig(client, session_factory, "+601234567875", events=(OUTBOUND, "message.status"))
    # control: a normal workflow send emits outbound AND a SENT status
    db = session_factory()
    try:
        real = omnichannel_send_message(
            db, DEFAULT_TENANT_ID, {"contactId": r["cid"], "mode": "text", "message": "real"}, {}
        )
    finally:
        db.close()
    assert [x["event_id"] for x in _deliveries(session_factory)] == [f"{real['messageId']}:outbound"]
    assert f"{real['messageId']}:SENT" in [x["event_id"] for x in _deliveries(session_factory, "message.status")]

    db = session_factory()
    try:
        sb = omnichannel_send_message(
            db,
            DEFAULT_TENANT_ID,
            {"contactId": r["cid"], "mode": "text", "message": "sandbox"},
            {"_workflow.sandboxOnly": True},
        )
    finally:
        db.close()
    sid = sb["messageId"]
    assert sid != real["messageId"]
    assert [x["event_id"] for x in _deliveries(session_factory)] == [f"{real['messageId']}:outbound"]
    assert [x for x in _status_rows(session_factory, sid)] == []


def test_ac_38_02_inbox_text_source_inbox(client, session_factory):
    r = _rig(client, session_factory, "+601234567816")
    res = client.post(
        f"/omnichannel/contacts/{r['cid']}/messages",
        json={"messageType": "TEXT", "body": "from inbox"},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    row = _only_outbound(session_factory)
    assert row["event_id"] == f"{res.json()['id']}:outbound"
    assert row["payload"]["data"]["source"] == "inbox"
    assert row["payload"]["data"]["contact"]["id"] == r["cid"]


def test_ac_38_02_04_inbox_media_source_inbox_and_media_url(client, session_factory):
    r = _rig(client, session_factory, "+601234567817")
    res = client.post(
        f"/omnichannel/contacts/{r['cid']}/media",
        files={"file": ("a.png", PNG, "image/png")},
        data={"kind": "image", "caption": "hi"},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    row = _only_outbound(session_factory)
    msg = row["payload"]["data"]["message"]
    assert row["payload"]["data"]["source"] == "inbox"
    assert msg["mediaUrl"].startswith("http")
    assert f"/omnichannel/media/{res.json()['id']}" in msg["mediaUrl"]


def test_ac_38_02_inbox_structured_location(client, session_factory):
    r = _rig(client, session_factory, "+601234567818")
    res = client.post(
        f"/omnichannel/contacts/{r['cid']}/location",
        json={"lat": 3.1, "lng": 101.6, "name": "HQ"},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    row = _only_outbound(session_factory)
    assert row["payload"]["data"]["source"] == "inbox"
    assert row["event_id"] == f"{res.json()['id']}:outbound"


def test_ac_38_02_broadcast_send_source_broadcast(client, session_factory):
    from modules.omnichannel.models import BroadcastRecipient

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    db = session_factory()
    try:
        WebhookService(db).create(
            DEFAULT_TENANT_ID, channel_id, "EMS", HOOK_URL, [OUTBOUND], created_by=None
        )
    finally:
        db.close()
    created = client.post(
        _broadcasts_base(ws),
        headers=h,
        json=_create_payload(
            channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]}
        ),
    ).json()
    sent = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert sent.status_code == 200, sent.text

    db = session_factory()
    try:
        mid = (
            db.query(BroadcastRecipient)
            .filter(BroadcastRecipient.broadcast_id == created["id"])
            .first()
            .message_id
        )
    finally:
        db.close()
    row = _only_outbound(session_factory)
    assert row["event_id"] == f"{mid}:outbound"
    assert row["payload"]["data"]["source"] == "broadcast"
    assert row["payload"]["data"]["message"]["id"] == mid


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-05 - what must NOT emit (each has a positive control in the same test)
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_05_note_reaction_inbound_sandbox_do_not_emit(client, session_factory):
    from modules.omnichannel.services.workflow_actions import omnichannel_send_message

    r = _rig(client, session_factory, "+601234567820")
    h = _auth(client)
    # control: a normal send DOES emit exactly once
    sent = client.post(
        f"/omnichannel/contacts/{r['cid']}/messages",
        json={"messageType": "TEXT", "body": "real"},
        headers=h,
    )
    assert sent.status_code == 201, sent.text
    mid = sent.json()["id"]
    assert len(_deliveries(session_factory)) == 1

    # internal note
    assert client.post(
        f"/omnichannel/contacts/{r['cid']}/notes", json={"body": "internal"}, headers=h
    ).status_code == 201
    # reaction (stays message.reaction)
    reacted = client.post(
        f"/omnichannel/contacts/{r['cid']}/messages/{mid}/react", json={"emoji": "\U0001F44D"}, headers=h
    )
    assert reacted.status_code == 200, reacted.text
    # inbound message
    _process(session_factory, r["channel_id"], _wa_payload(wamid="wamid.in-x", from_="601234567820", text="yo"))
    # workflow test sandbox row
    db = session_factory()
    try:
        omnichannel_send_message(
            db,
            DEFAULT_TENANT_ID,
            {"contactId": r["cid"], "mode": "text", "message": "sandbox"},
            {"_workflow.sandboxOnly": True},
        )
    finally:
        db.close()

    rows = _deliveries(session_factory)
    assert len(rows) == 1, [x["payload"]["data"]["message"]["body"] for x in rows]
    assert rows[0]["event_id"] == f"{mid}:outbound"


def test_ac_38_05_migration_import_does_not_emit(session_factory, monkeypatch):
    """A migrated-history row (`migrated_from` set, no send path) with a
    subscribed endpoint present yields zero deliveries. Regression guard only:
    it cannot prove the writer stays silent without running a full migration
    job; it fails today solely because the endpoint cannot subscribe yet."""
    from datetime import datetime, timezone

    from modules.omnichannel.models import Contact
    from tests.test_omnichannel_contacts_module import _ensure_channel, _seed_contact, _workspace_id  # noqa: F401

    ws = _default_workspace_id(session_factory)
    channel_id = _ensure_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws, first="Mig", last="Rated", phone="+60 12-345 6781")
    db = session_factory()
    try:
        WebhookService(db).create(DEFAULT_TENANT_ID, channel_id, "EMS", HOOK_URL, [OUTBOUND], created_by=None)
        row = ConversationMessage(
            tenant_id=DEFAULT_TENANT_ID,
            contact_id=cid,
            channel_id=channel_id,
            sender_type="AGENT",
            message_type="TEXT",
            body="imported history",
            delivery_status="SENT",
            migrated_from="respondio",
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        assert db.query(Contact).filter(Contact.id == cid).first()
    finally:
        db.close()
    assert _deliveries(session_factory) == []


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-06 - idempotent replay
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_06_idempotent_replay_emits_once(client, session_factory):
    r = _rig(client, session_factory, "+601234567830")
    hdr = {"Idempotency-Key": "outbound-replay-1"}
    r1 = _api_text(client, r["hdr"], "+601234567830", extra_headers=hdr)
    r2 = _api_text(client, r["hdr"], "+601234567830", extra_headers=hdr)
    assert r1.status_code == 202 and r2.status_code == 202
    assert r2.json()["idempotencyReplay"] is True
    assert r1.json()["id"] == r2.json()["id"]
    # control: the first call did emit, the replay did not add a second
    rows = _deliveries(session_factory)
    assert [x["event_id"] for x in rows] == [f"{r1.json()['id']}:outbound"]


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-07 - enqueue failure never fails or rolls back the send
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_07_enqueue_failure_does_not_fail_send(client, session_factory, monkeypatch):
    r = _rig(client, session_factory, "+601234567840")
    real = wd.enqueue_event
    attempts = {"outbound": 0}

    def boom(db, channel, event_type, event_id, data):
        if event_type == OUTBOUND:
            attempts["outbound"] += 1
            raise RuntimeError("enqueue exploded")
        return real(db, channel, event_type, event_id, data)

    monkeypatch.setattr(wd, "enqueue_event", boom)

    res = _api_text(client, r["hdr"], "+601234567840", body="still sent")
    assert res.status_code == 202, res.text
    mid = res.json()["id"]
    inbox = client.post(
        f"/omnichannel/contacts/{r['cid']}/messages",
        json={"messageType": "TEXT", "body": "inbox still sent"},
        headers=_auth(client),
    )
    assert inbox.status_code == 201, inbox.text
    assert inbox.json()["deliveryStatus"] in ("SENT", "QUEUED")

    # the emit was genuinely attempted (so the patch was in the path) ...
    assert attempts["outbound"] >= 2
    # ... and the rows survived with their normal outcome
    db = session_factory()
    try:
        row = db.query(ConversationMessage).filter(ConversationMessage.id == mid).first()
        assert row is not None and row.body == "still sent"
        assert row.delivery_status in ("SENT", "SENDING", "QUEUED")
        assert row.delivery_status != "FAILED"
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-08 - isolation: other channel / workspace / tenant never receives
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_08_other_channel_workspace_tenant_get_nothing(client, session_factory):
    r = _rig(client, session_factory, "+601234567850")
    ws = r["ws"]
    # another channel in the SAME workspace + endpoint subscribed to outbound
    other_channel = _seed_channel(session_factory, ws, phone_number_id="pn-other")
    db = session_factory()
    try:
        WebhookService(db).create(
            DEFAULT_TENANT_ID, other_channel, "other-ch", HOOK_URL, [OUTBOUND], created_by=None
        )
    finally:
        db.close()
    # another workspace (same tenant) and another tenant: foreign channel + endpoint rows
    for tenant_id, workspace_id, label in (
        (DEFAULT_TENANT_ID, "other-workspace-id", "ws"),
        ("other-tenant-id", "other-tenant-ws", "tenant"),
    ):
        db = session_factory()
        try:
            ch = Channel(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                channel_type="WHATSAPP",
                name=f"foreign-{label}",
                phone_number_id=f"pn-foreign-{label}",
                is_active=True,
            )
            db.add(ch)
            db.commit()
            foreign_channel = ch.id
        finally:
            db.close()
        _insert_foreign_endpoint(
            session_factory,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            channel_id=foreign_channel,
            events=[OUTBOUND],
        )

    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+601234567850",
            "channelId": r["channel_id"],
            "type": "text",
            "text": {"body": "isolated"},
        },
        headers=r["hdr"],
    )
    assert res.status_code == 202, res.text

    rows = _deliveries(session_factory)
    # control: the right endpoint got exactly one; nobody else got anything
    assert [x["endpoint_id"] for x in rows] == [r["ep"]]


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-09 / 10 / 11 - message.status companion
# ═════════════════════════════════════════════════════════════════════════════
def _status_rows(session_factory, mid):
    return [x for x in _deliveries(session_factory, "message.status") if x["payload"]["data"]["messageId"] == mid]


def test_ac_38_09_meta_accept_emits_sent_and_late_sent_receipt_adds_none(client, session_factory):
    r = _rig(client, session_factory, "+601234567860", events=("message.status",))
    sent = _api_text(client, r["hdr"], "+601234567860")
    assert sent.status_code == 202, sent.text
    mid = sent.json()["id"]

    rows = _status_rows(session_factory, mid)
    assert [x["event_id"] for x in rows] == [f"{mid}:SENT"]
    assert rows[0]["payload"]["data"]["deliveryStatus"] == "SENT"

    ext = _external_id(session_factory, mid)
    assert ext
    _process(
        session_factory,
        r["channel_id"],
        _wa_payload(statuses=[{"id": ext, "status": "sent", "timestamp": "1717550001"}]),
    )
    assert [x["event_id"] for x in _status_rows(session_factory, mid)] == [f"{mid}:SENT"]


def test_ac_38_10_sync_failure_emits_failed_with_error_fields(client, session_factory, monkeypatch):
    from modules.omnichannel.services.media_pipeline import MediaRejected

    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.transcode_voice",
        lambda content: (_ for _ in ()).throw(MediaRejected("transcode_failed", "bad audio")),
    )
    r = _rig(client, session_factory, "+601234567861", events=("message.status",))
    res = client.post(
        f"/omnichannel/contacts/{r['cid']}/media",
        files={"file": ("v.webm", WEBM, "audio/webm")},
        data={"kind": "voice"},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    mid = res.json()["id"]

    rows = _status_rows(session_factory, mid)
    assert [x["event_id"] for x in rows] == [f"{mid}:FAILED"]
    data = rows[0]["payload"]["data"]
    assert data["deliveryStatus"] == "FAILED"
    assert data["messageId"] == mid and data["contactId"] == r["cid"]
    assert data["errorMessage"]
    assert "errorCode" in data and "externalMessageId" in data  # documented shape


def test_ac_38_11_delivered_read_unchanged_and_never_backward(client, session_factory):
    r = _rig(client, session_factory, "+601234567862", events=("message.status",))
    mid = _api_text(client, r["hdr"], "+601234567862").json()["id"]
    ext = _external_id(session_factory, mid)
    assert ext

    def receipt(status):
        _process(
            session_factory,
            r["channel_id"],
            _wa_payload(statuses=[{"id": ext, "status": status, "timestamp": "1717550002"}]),
        )

    receipt("delivered")
    receipt("read")
    receipt("delivered")  # backward: must be ignored
    receipt("sent")  # backward: must be ignored

    ids = sorted(x["event_id"] for x in _status_rows(session_factory, mid) if not x["event_id"].endswith(":SENT"))
    assert ids == sorted([f"{mid}:DELIVERED", f"{mid}:READ"])
    db = session_factory()
    try:
        row = db.query(ConversationMessage).filter(ConversationMessage.id == mid).first()
        assert row.delivery_status == "READ"
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-12 - contract: guide + frontend event type list
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_12_guide_and_frontend_type_list_message_outbound():
    guide = (REPO_ROOT / "documentation/omnichannel/consumer-integration-guide.md").read_text()
    fe = (REPO_ROOT / "service_frontend/types/whatsapp-webhook.ts").read_text()
    assert OUTBOUND in guide
    assert OUTBOUND in fe


# ═════════════════════════════════════════════════════════════════════════════
# Security round (AC-38-14..19). Fake values only.
# ═════════════════════════════════════════════════════════════════════════════
RAW_TRANSIENT = (
    "GET https://store.invalid/x?RAWDETAIL=FAKE "
    "failed at /internal/x"
)


class _FakeAdapter:
    """Patched at the send_runner boundary (`get_adapter`)."""

    def __init__(self, exc=None):
        self.exc = exc

    def upload_media(self, *a, **k):
        return "media-fake"

    sends = 0

    def send(self, *a, **k):
        self.sends += 1
        if self.exc is not None:
            raise self.exc
        return {"external_message_id": "wamid.fake-sec"}


def _use_adapter(monkeypatch, exc=None):
    adapter = _FakeAdapter(exc)
    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.get_adapter", lambda *a, **k: adapter
    )
    return adapter


def _provider_error(message, code=None, transient=False):
    from modules.omnichannel.adapters.base import SendError

    exc = SendError(message, transient=transient)
    if code is not None:
        # the exact attribute is the coder's choice; set the likely spellings
        exc.code = code
        exc.error_code = code
    return exc


def _inbox_text(client, cid, body="sec round"):
    return client.post(
        f"/omnichannel/contacts/{cid}/messages",
        json={"messageType": "TEXT", "body": body},
        headers=_auth(client),
    )


def _row(session_factory, mid):
    db = session_factory()
    try:
        r = db.query(ConversationMessage).filter(ConversationMessage.id == mid).first()
        return r.delivery_status, r.error_code, r.error_message
    finally:
        db.close()


def _set_row_error(session_factory, mid, code, message):
    db = session_factory()
    try:
        r = db.query(ConversationMessage).filter(ConversationMessage.id == mid).first()
        r.error_code, r.error_message = code, message
        db.commit()
    finally:
        db.close()


def test_ac_38_14_transient_error_text_never_stored_cleared_on_success_and_logged(
    client, session_factory, monkeypatch, caplog
):
    import logging

    from modules.omnichannel.services.send_runner import run_send

    r = _rig(client, session_factory, "+601234567880", events=("message.status",))
    _use_adapter(monkeypatch, _provider_error(RAW_TRANSIENT, transient=True))
    with caplog.at_level(logging.DEBUG):
        res = _inbox_text(client, r["cid"])
    assert res.status_code == 201, res.text
    mid = res.json()["id"]

    status, _code, message = _row(session_factory, mid)
    assert status == "QUEUED"  # control: it really was a requeued transient failure
    for raw in ("RAWDETAIL", "/internal", "store.invalid"):
        assert raw not in (message or ""), f"raw transient error stored on the row: {message!r}"
    assert "RAWDETAIL=FAKE" in caplog.text, "the real error must reach the log"

    _use_adapter(monkeypatch, None)
    db = session_factory()
    try:
        assert run_send(db, mid) == "SENT"
    finally:
        db.close()
    status, _code, message = _row(session_factory, mid)
    assert status == "SENT" and message is None, message
    blob = str(_deliveries(session_factory, "message.status"))
    assert "RAWDETAIL" not in blob and "/internal" not in blob


def test_ac_38_15_sent_and_delivered_carry_null_error_fields_failed_carries_them(
    client, session_factory, monkeypatch
):
    from modules.omnichannel.services.send_runner import run_send

    r = _rig(client, session_factory, "+601234567881", events=("message.status",))
    # first attempt requeues (transient), then a stale error is planted, then success
    _use_adapter(monkeypatch, _provider_error("blip", transient=True))
    mid = _inbox_text(client, r["cid"]).json()["id"]
    _set_row_error(session_factory, mid, "131000", "stale boom")
    _use_adapter(monkeypatch, None)
    db = session_factory()
    try:
        assert run_send(db, mid) == "SENT"
    finally:
        db.close()
    sent = [x for x in _status_rows(session_factory, mid) if x["event_id"] == f"{mid}:SENT"]
    assert len(sent) == 1
    assert sent[0]["payload"]["data"]["errorCode"] is None
    assert sent[0]["payload"]["data"]["errorMessage"] is None

    # receipt path: a stale error on the row must not ride DELIVERED either
    _set_row_error(session_factory, mid, "131000", "stale boom")
    ext = _external_id(session_factory, mid)
    _process(
        session_factory,
        r["channel_id"],
        _wa_payload(statuses=[{"id": ext, "status": "delivered", "timestamp": "1717550003"}]),
    )
    delivered = [x for x in _status_rows(session_factory, mid) if x["event_id"] == f"{mid}:DELIVERED"]
    assert len(delivered) == 1  # control: the receipt produced its event
    assert delivered[0]["payload"]["data"]["errorCode"] is None
    assert delivered[0]["payload"]["data"]["errorMessage"] is None

    # control: FAILED does carry them
    mid2 = None
    _use_adapter(monkeypatch, _provider_error("Re-engagement message", code="131047"))
    mid2 = _inbox_text(client, r["cid"], body="will fail").json()["id"]
    failed = [x for x in _status_rows(session_factory, mid2) if x["event_id"] == f"{mid2}:FAILED"]
    assert len(failed) == 1
    assert failed[0]["payload"]["data"]["errorMessage"]


def test_ac_38_16_failed_event_uses_provider_code_when_there_is_one(client, session_factory, monkeypatch):
    r = _rig(client, session_factory, "+601234567882", events=("message.status",))
    _use_adapter(monkeypatch, _provider_error("Re-engagement message", code="131047"))
    mid = _inbox_text(client, r["cid"]).json()["id"]
    failed = [x for x in _status_rows(session_factory, mid) if x["event_id"] == f"{mid}:FAILED"]
    assert len(failed) == 1
    assert str(failed[0]["payload"]["data"]["errorCode"]) == "131047"
    assert failed[0]["payload"]["data"]["errorMessage"] == "Re-engagement message"


def test_ac_38_16_long_provider_error_is_capped_at_300_characters(client, session_factory, monkeypatch):
    r = _rig(client, session_factory, "+601234567883", events=("message.status",))
    long_text = "E" * 50 + "x" * 700
    _use_adapter(monkeypatch, _provider_error(long_text, code="100"))
    mid = _inbox_text(client, r["cid"]).json()["id"]
    failed = [x for x in _status_rows(session_factory, mid) if x["event_id"] == f"{mid}:FAILED"]
    assert len(failed) == 1
    msg = failed[0]["payload"]["data"]["errorMessage"]
    assert msg and len(msg) <= 300, len(msg or "")
    assert msg.startswith("E" * 50)  # control: capped, not replaced


def test_ac_38_16_local_failure_has_null_error_code(client, session_factory, monkeypatch):
    from modules.omnichannel.services.media_pipeline import MediaRejected

    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.transcode_voice",
        lambda content: (_ for _ in ()).throw(MediaRejected("transcode_failed", "bad audio")),
    )
    r = _rig(client, session_factory, "+601234567884", events=("message.status",))
    res = client.post(
        f"/omnichannel/contacts/{r['cid']}/media",
        files={"file": ("v.webm", WEBM, "audio/webm")},
        data={"kind": "voice"},
        headers=_auth(client),
    )
    mid = res.json()["id"]
    failed = [x for x in _status_rows(session_factory, mid) if x["event_id"] == f"{mid}:FAILED"]
    assert len(failed) == 1  # control
    assert failed[0]["payload"]["data"]["errorCode"] is None
    assert failed[0]["payload"]["data"]["errorMessage"]


def test_ac_38_17_reply_target_must_be_a_message(
    client, session_factory
):
    r = _rig(client, session_factory, "+601234567885")
    h = _auth(client)
    normal = _inbox_text(client, r["cid"], body="normal one").json()["id"]
    note = client.post(
        f"/omnichannel/contacts/{r['cid']}/notes", json={"body": "NOTE-TEXT-FAKE internal remark"}, headers=h
    )
    assert note.status_code == 201, note.text
    note_id = note.json()["id"]

    def reply_to(target):
        return client.post(
            f"/omnichannel/contacts/{r['cid']}/messages",
            json={"messageType": "TEXT", "body": "replying", "replyToMessageId": target},
            headers=h,
        )

    ok = reply_to(normal)
    assert ok.status_code == 201, ok.text  # control: replying to a normal message works
    unknown = reply_to("00000000-0000-0000-0000-000000000000")
    assert unknown.status_code >= 400  # control: unknown id is an error
    to_note = reply_to(note_id)
    assert to_note.status_code == unknown.status_code
    assert to_note.json() == unknown.json()
    assert "NOTE-TEXT-FAKE" not in str(_deliveries(session_factory))


def test_ac_38_18_same_channel_id_under_another_tenant_or_workspace_gets_nothing(client, session_factory):
    r = _rig(client, session_factory, "+601234567886")
    for tenant_id, workspace_id in (
        ("other-tenant-id", "other-tenant-ws"),
        (DEFAULT_TENANT_ID, "other-workspace-id"),
    ):
        _insert_foreign_endpoint(
            session_factory,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            channel_id=r["channel_id"],
            events=[OUTBOUND],
        )
    assert _api_text(client, r["hdr"], "+601234567886").status_code == 202
    rows = _deliveries(session_factory)
    assert [x["endpoint_id"] for x in rows] == [r["ep"]]  # right endpoint got it, nobody else


def test_ac_38_19_guide_states_sender_fields_and_apikey_sender_id():
    guide = (REPO_ROOT / "documentation/omnichannel/consumer-integration-guide.md").read_text()
    assert "apikey:" in guide
    i = guide.index("apikey:")
    window = guide[max(0, i - 800) : i + 800].lower()
    assert "sender" in window and "message.outbound" in guide


# ═════════════════════════════════════════════════════════════════════════════
# Code review round (AC-38-30..33)
# ═════════════════════════════════════════════════════════════════════════════
def _drive_worker(monkeypatch, session_factory, mid):
    """Run the Celery task the way the worker does (autoretry up to
    max_retries), on the test engine."""
    import app.database as appdb
    from modules.omnichannel.worker import celery_app, omnichannel_send_message

    monkeypatch.setattr(appdb, "SessionLocal", session_factory)
    # The omni app propagates eager errors, so the first Retry would escape
    # `apply`; let every retry run, as the worker does. Explicit save and
    # restore (the key may be absent from the conf view in some environments,
    # which a monkeypatch undo cannot handle).
    previous = celery_app.conf.get("task_eager_propagates", True)
    celery_app.conf.update(task_eager_propagates=False)
    try:
        return omnichannel_send_message.apply(args=[mid])
    except Exception:  # noqa: BLE001 - eager Celery may still re-raise the last error; the outcome is what counts
        return None
    finally:
        celery_app.conf.update(task_eager_propagates=previous)


def test_ac_38_30a_retries_exhausted_ends_failed_with_one_failed_event(client, session_factory, monkeypatch):
    r = _rig(client, session_factory, "+60123456780", events=("message.status",))
    adapter = _use_adapter(monkeypatch, _provider_error(RAW_TRANSIENT, transient=True))
    mid = _inbox_text(client, r["cid"]).json()["id"]
    # control: a transient error with retries remaining emits NOTHING yet
    assert _row(session_factory, mid)[0] == "QUEUED"
    assert _status_rows(session_factory, mid) == []

    before = adapter.sends
    _drive_worker(monkeypatch, session_factory, mid)
    assert adapter.sends - before > 1, "control: the task must have run more than one attempt"

    status, _code, message = _row(session_factory, mid)
    assert status == "FAILED", status
    failed = [x["event_id"] for x in _status_rows(session_factory, mid)]
    assert failed == [f"{mid}:FAILED"], failed
    assert "RAWDETAIL" not in str(_deliveries(session_factory, "message.status"))


def test_ac_38_30b_unexpected_adapter_error_ends_failed_with_generic_text(client, session_factory, monkeypatch):
    from modules.omnichannel.services.send_runner import run_send

    r = _rig(client, session_factory, "+60123456781", events=("message.status",))
    _use_adapter(monkeypatch, _provider_error("blip", transient=True))
    mid = _inbox_text(client, r["cid"]).json()["id"]
    assert _row(session_factory, mid)[0] == "QUEUED"  # control

    _use_adapter(monkeypatch, RuntimeError("internal detail"))
    db = session_factory()
    try:
        try:
            run_send(db, mid)
        except Exception:  # noqa: BLE001 - the contract is the outcome, not whether it re-raises
            pass
    finally:
        db.close()

    status, _code, message = _row(session_factory, mid)
    assert status == "FAILED", f"row left in {status}"
    assert "internal detail" not in (message or "")
    failed = [x["event_id"] for x in _status_rows(session_factory, mid)]
    assert failed == [f"{mid}:FAILED"], failed
    assert "internal detail" not in str(_deliveries(session_factory, "message.status"))


def test_ac_38_31_receipt_right_after_commit_still_gives_one_sent_and_no_duplicate_delivered(
    client, session_factory, monkeypatch
):
    from modules.omnichannel.services import realtime

    r = _rig(client, session_factory, "+60123456782", events=("message.status",))
    _use_adapter(monkeypatch, None)  # external id "wamid.fake-sec"
    real_publish = realtime.publish
    state = {"fired": False}

    def publish_then_receipt(workspace_id, event):
        real_publish(workspace_id, event)
        if event.get("type") == "message.status" and not state["fired"]:
            state["fired"] = True
            _process(
                session_factory,
                r["channel_id"],
                _wa_payload(statuses=[{"id": "wamid.fake-sec", "status": "delivered", "timestamp": "1717550009"}]),
            )

    monkeypatch.setattr(realtime, "publish", publish_then_receipt)
    mid = _inbox_text(client, r["cid"]).json()["id"]
    assert state["fired"], "control: the receipt really arrived between the commit and the emit"
    ids = [x["event_id"] for x in _status_rows(session_factory, mid)]
    assert ids.count(f"{mid}:SENT") == 1, ids
    assert ids.count(f"{mid}:DELIVERED") == 1, ids  # only the receipt path produced it


def test_ac_38_32_voice_outbound_reports_the_transcoded_type_and_matches_get(client, session_factory, monkeypatch):
    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.transcode_voice",
        lambda content: b"OggS" + b"\x00" * 64,
    )
    r = _rig(client, session_factory, "+60123456783")
    res = client.post(
        f"/omnichannel/contacts/{r['cid']}/media",
        files={"file": ("v.webm", WEBM, "audio/webm")},
        data={"kind": "voice"},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    mid = res.json()["id"]
    msg = _only_outbound(session_factory)["payload"]["data"]["message"]
    got = [m for m in client.get(f"/omnichannel/contacts/{r['cid']}/messages", headers=_auth(client)).json() if m["id"] == mid][0]
    assert got["mediaMime"] == "audio/ogg"  # control: what GET reports afterwards
    assert msg["mimeType"] == "audio/ogg"


def test_ac_38_33_no_subscriber_builds_no_outbound_payload(client, session_factory, monkeypatch):
    calls = {"n": 0}
    real = wd.consumer_message_payload

    def spy(item, row):
        calls["n"] += 1
        return real(item, row)

    monkeypatch.setattr(wd, "consumer_message_payload", spy)

    # no endpoint at all, and an endpoint that does not subscribe to message.outbound
    r = _rig(client, session_factory, "+60123456784", events=())
    assert _inbox_text(client, r["cid"]).status_code == 201
    assert calls["n"] == 0
    assert _register(client, r["hdr"], ["message.inbound", "message.status"]).status_code == 201
    assert _inbox_text(client, r["cid"], body="still none").status_code == 201
    assert calls["n"] == 0

    # control: with a subscriber the payload IS built, exactly once per send
    assert _register(client, r["hdr"], [OUTBOUND], name="sub").status_code == 201
    assert _inbox_text(client, r["cid"], body="now built").status_code == 201
    assert calls["n"] == 1


# ── kill-test gaps ───────────────────────────────────────────────────────────
def test_embed_agent_send_reports_source_inbox(client, session_factory):
    from tests.test_omnichannel_embed import (
        _assertion,
        _bearer,
        _channel_in_workspace,
        _exchange,
        _make_connection,
        _seed_contact,
        _workspace_id,
    )

    conn = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    contact_id = _seed_contact(session_factory, workspace_id=wid)
    channel_id = _channel_in_workspace(session_factory, wid)
    db = session_factory()
    try:
        WebhookService(db).create(DEFAULT_TENANT_ID, channel_id, "EMS", HOOK_URL, [OUTBOUND], created_by=None)
    finally:
        db.close()
    token = _exchange(client, _assertion(iss=conn, workspace_id=wid, name="Alice Agent")).json()["accessToken"]
    send = client.post(
        f"/omnichannel/contacts/{contact_id}/messages",
        json={"body": "from the widget"},
        headers=_bearer(token),
    )
    assert send.status_code == 201, send.text
    assert send.json()["senderExternalAgentId"]  # control: it is a real embed-agent send
    row = _only_outbound(session_factory)
    assert row["payload"]["data"]["source"] == "inbox"
    assert row["payload"]["data"]["message"]["id"] == send.json()["id"]


def test_emit_helpers_never_resolve_a_channel_of_another_tenant(client, session_factory):
    from modules.omnichannel.services.message_service import MessageService
    from modules.omnichannel.services.send_runner import _emit_status_webhook

    r = _rig(client, session_factory, "+60123456785", events=())
    mid = _inbox_text(client, r["cid"]).json()["id"]
    # a channel of another tenant with an endpoint subscribed to both events
    db = session_factory()
    try:
        foreign = Channel(
            tenant_id="other-tenant-id",
            workspace_id="other-tenant-ws",
            channel_type="WHATSAPP",
            name="foreign",
            phone_number_id="pn-foreign-emit",
            is_active=True,
        )
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id
    finally:
        db.close()
    _insert_foreign_endpoint(
        session_factory,
        tenant_id="other-tenant-id",
        workspace_id="other-tenant-ws",
        channel_id=foreign_id,
        events=[OUTBOUND, "message.status"],
    )
    # a message row whose channel belongs to another tenant
    db = session_factory()
    try:
        row = db.query(ConversationMessage).filter(ConversationMessage.id == mid).first()
        row.channel_id = foreign_id
        db.commit()
        svc = MessageService(db)
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.id == r["cid"]).first()
        item = svc.conversations.message_items([row])[0]
        svc._emit_outbound(row, contact, item)
        row.delivery_status = "SENT"
        _emit_status_webhook(db, row)
    finally:
        db.close()
    assert _deliveries(session_factory, OUTBOUND) == []
    assert _deliveries(session_factory, "message.status") == []


def test_status_emit_enqueue_failure_does_not_fail_the_send(client, session_factory, monkeypatch):
    r = _rig(client, session_factory, "+60123456786", events=("message.status",))
    real = wd.enqueue_event
    attempts = {"status": 0}

    def boom(db, channel, event_type, event_id, data):
        if event_type == "message.status":
            attempts["status"] += 1
            raise RuntimeError("status enqueue exploded")
        return real(db, channel, event_type, event_id, data)

    monkeypatch.setattr(wd, "enqueue_event", boom)
    res = _inbox_text(client, r["cid"])
    assert res.status_code == 201, res.text
    assert attempts["status"] >= 1  # control: the emit was genuinely attempted
    assert _row(session_factory, res.json()["id"])[0] == "SENT"


# ═════════════════════════════════════════════════════════════════════════════
# Error text round (AC-38-34..37). Fake values only.
# ═════════════════════════════════════════════════════════════════════════════
FAKE_URL = "https://docs.example.invalid/errors?ref=FAKEREF"
FAKE_OPAQUE = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789FAKEOPAQUE"
PROVIDER_BODY_LONG = f"Invalid parameter, see {FAKE_URL} for token {FAKE_OPAQUE} details"


def _real_adapter_with_provider_reply(monkeypatch, session_factory, channel_id, message, status=400):
    """Exercise the real WhatsApp adapter against a mocked HTTP boundary."""
    import httpx

    from app.config import settings
    from modules.omnichannel.adapters import get_adapter as real_get_adapter

    monkeypatch.setattr(settings, "meta_app_id", "fake-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "fake-app-secret")
    db = session_factory()
    try:
        ch = db.query(Channel).filter(Channel.id == channel_id).first()
        ch.credentials_json = encrypt_credentials({"access_token": "fake-access-token"})
        db.commit()
    finally:
        db.close()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": message, "code": 100}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.get_adapter",
        lambda channel_type="WHATSAPP", recorder=None, **k: real_get_adapter(
            channel_type, client=client, recorder=recorder
        ),
    )


def _activity_errors(session_factory):
    from app.models.integration_activity import SOURCE_OUTBOUND_META, IntegrationActivity

    db = session_factory()
    try:
        rows = db.query(IntegrationActivity).filter(IntegrationActivity.source == SOURCE_OUTBOUND_META).all()
        return [r.error_message or "" for r in rows]
    finally:
        db.close()


def _assert_normalised(text):
    assert "https://" not in text and "docs.example.invalid" not in text, text
    assert FAKE_OPAQUE not in text, text


def test_ac_38_34_send_path_provider_text_is_normalised_in_row_event_and_activity_log(
    client, session_factory, monkeypatch
):
    r = _rig(client, session_factory, "+60123456790", events=("message.status",))
    _real_adapter_with_provider_reply(monkeypatch, session_factory, r["channel_id"], PROVIDER_BODY_LONG)
    mid = _inbox_text(client, r["cid"]).json()["id"]

    status, _code, message = _row(session_factory, mid)
    assert status == "FAILED"  # control: a permanent provider rejection
    failed = [x for x in _status_rows(session_factory, mid) if x["event_id"] == f"{mid}:FAILED"]
    assert len(failed) == 1
    event_text = failed[0]["payload"]["data"]["errorMessage"]
    activity = _activity_errors(session_factory)
    assert any(activity), "control: the send was recorded in the activity log"
    for text in [message or "", event_text or "", *activity]:
        _assert_normalised(text)
    assert "Invalid parameter" in (message or "")  # readable words survive


def test_ac_38_34_short_provider_message_keeps_its_words(client, session_factory, monkeypatch):
    r = _rig(client, session_factory, "+60123456791", events=("message.status",))
    _real_adapter_with_provider_reply(monkeypatch, session_factory, r["channel_id"], "Re-engagement message")
    mid = _inbox_text(client, r["cid"]).json()["id"]
    _status, _code, message = _row(session_factory, mid)
    assert message == "Re-engagement message"
    assert any("Re-engagement message" in a for a in _activity_errors(session_factory))


def test_ac_38_34_media_upload_path_provider_text_is_normalised(client, session_factory, monkeypatch):
    r = _rig(client, session_factory, "+60123456792", events=("message.status",))
    _real_adapter_with_provider_reply(monkeypatch, session_factory, r["channel_id"], PROVIDER_BODY_LONG)
    res = client.post(
        f"/omnichannel/contacts/{r['cid']}/media",
        files={"file": ("a.png", PNG, "image/png")},
        data={"kind": "image"},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    mid = res.json()["id"]
    status, _code, message = _row(session_factory, mid)
    assert status == "FAILED"  # control: the upload was rejected
    failed = [x for x in _status_rows(session_factory, mid) if x["event_id"] == f"{mid}:FAILED"]
    assert len(failed) == 1
    for text in [message or "", failed[0]["payload"]["data"]["errorMessage"] or ""]:
        _assert_normalised(text)
    assert "Invalid parameter" in (message or "")


# ── AC-38-35 ─────────────────────────────────────────────────────────────────
def test_ac_38_35_storage_read_failure_carries_the_status_not_the_query_string(
    client, session_factory, monkeypatch, caplog
):
    import logging

    import httpx

    import app.services.storage as st

    r = _rig(client, session_factory, "+60123456793", events=())
    real_for = st.storage_for_tenant
    fake_url = "https://bucket.invalid/o/a.png?X-Amz-Signature=FAKESIG&X-Amz-Credential=FAKECRED"

    class _Wrap:
        def __init__(self, real):
            self._real = real

        def save(self, *a, **k):
            return self._real.save(*a, **k)

        def resolve(self, key):
            return ("presigned", fake_url)

    monkeypatch.setattr(st, "storage_for_tenant", lambda db, tid: _Wrap(real_for(db, tid)))
    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.httpx.get",
        lambda u, timeout=None: httpx.Response(503, request=httpx.Request("GET", u)),
    )
    with caplog.at_level(logging.DEBUG):
        res = client.post(
            f"/omnichannel/contacts/{r['cid']}/media",
            files={"file": ("a.png", PNG, "image/png")},
            data={"kind": "image"},
            headers=_auth(client),
        )
    assert res.status_code == 201, res.text
    assert _row(session_factory, res.json()["id"])[0] == "QUEUED"  # control: the read really failed
    assert "503" in caplog.text
    assert "FAKESIG" not in caplog.text and "FAKECRED" not in caplog.text

    from modules.omnichannel.services.send_runner import _read_media

    db = session_factory()
    try:
        with pytest.raises(Exception) as exc:
            _read_media(db, DEFAULT_TENANT_ID, "any-key")
    finally:
        db.close()
    assert "503" in str(exc.value)
    assert "FAKESIG" not in str(exc.value) and "FAKECRED" not in str(exc.value)


# ── AC-38-36 ─────────────────────────────────────────────────────────────────
def test_ac_38_36_broadcast_unexpected_error_stores_generic_text_and_logs_the_detail(
    client, session_factory, monkeypatch, caplog
):
    import logging

    from modules.omnichannel.models import BroadcastRecipient
    from modules.omnichannel.services.message_service import MessageService

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(
        _broadcasts_base(ws),
        headers=h,
        json=_create_payload(channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]}),
    ).json()

    def boom(self, *a, **k):
        raise RuntimeError("connect to db-host-fake.internal.invalid:5432 failed")

    monkeypatch.setattr(MessageService, "send_message", boom)
    with caplog.at_level(logging.DEBUG):
        sent = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert sent.status_code == 200, sent.text

    db = session_factory()
    try:
        rec = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == created["id"]).first()
        assert rec.state == "failed"  # control: the recipient really failed
        assert rec.error_text and "db-host-fake" not in rec.error_text
    finally:
        db.close()
    assert "db-host-fake.internal.invalid" in caplog.text, "the detail must reach the log"
    assert "db-host-fake" not in str(sent.json())


# ── AC-38-37 ─────────────────────────────────────────────────────────────────
@pytest.fixture
def _failing_delivery_insert():
    """Make the webhook delivery INSERT fail inside a real flush, so the session
    needs a rollback afterwards. `only` narrows it to one event type."""
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError

    state = {"only": None, "fired": 0}

    def before_insert(mapper, connection, target):
        if state["only"] is None or target.event_type == state["only"]:
            state["fired"] += 1
            raise OperationalError("INSERT INTO webhook_deliveries", {}, Exception("database failure"))

    event.listen(WebhookDelivery, "before_insert", before_insert)
    yield state
    event.remove(WebhookDelivery, "before_insert", before_insert)


def test_ac_38_37_failed_delivery_insert_never_fails_or_strands_an_api_send(
    client, session_factory, _failing_delivery_insert
):
    r = _rig(client, session_factory, "+60123456794", events=(OUTBOUND, "message.status"))
    res = _api_text(client, r["hdr"], "+60123456794")
    assert res.status_code == 202, res.text
    mid = res.json()["id"]
    assert _failing_delivery_insert["fired"] >= 1, "control: the insert really failed"
    assert _deliveries(session_factory, OUTBOUND) == []
    status, _code, _msg = _row(session_factory, mid)
    assert status == "SENT", status  # dispatched, not stranded
    # the application still serves the next request normally
    assert _api_text(client, r["hdr"], "+60123456794", body="next").status_code == 202


def test_ac_38_37_failed_status_insert_after_the_send_keeps_the_send_result(
    client, session_factory, _failing_delivery_insert
):
    _failing_delivery_insert["only"] = "message.status"
    r = _rig(client, session_factory, "+60123456795", events=(OUTBOUND, "message.status"))
    res = _inbox_text(client, r["cid"])
    assert res.status_code == 201, res.text
    mid = res.json()["id"]
    assert _failing_delivery_insert["fired"] >= 1, "control: the status insert really failed"
    assert [x["event_id"] for x in _deliveries(session_factory, OUTBOUND)] == [f"{mid}:outbound"]
    assert _status_rows(session_factory, mid) == []
    status, _code, _msg = _row(session_factory, mid)
    assert status == "SENT", status
    assert res.json()["deliveryStatus"] == "SENT"
