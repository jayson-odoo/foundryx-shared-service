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
    r = _rig(client, session_factory, "+60380000001", events=())
    reg = _register(client, r["hdr"], [OUTBOUND, "message.inbound"])
    assert reg.status_code == 201, reg.text
    assert set(reg.json()["endpoint"]["events"]) == {OUTBOUND, "message.inbound"}
    # control: an unknown event name is still rejected (so acceptance above is real)
    bad = _register(client, r["hdr"], ["message.nope"])
    assert bad.status_code in (400, 422)


def test_ac_38_01_session_route_accepts_message_outbound(client, session_factory):
    r = _rig(client, session_factory, "+60380000002", events=())
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
    r = _rig(client, session_factory, "+60380000003", events=("message.inbound", "message.status"))
    # a second endpoint DOES subscribe: proves the send emitted at all (control)
    assert _register(client, r["hdr"], [OUTBOUND], name="opt-in").status_code == 201
    assert _api_text(client, r["hdr"], "+60380000003").status_code == 202

    rows = _deliveries(session_factory)
    assert len(rows) == 1
    assert rows[0]["endpoint_id"] != r["ep"], "endpoint without message.outbound must get none"


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-02 / AC-38-03 - one delivery per ACTIVE subscribed endpoint, envelope
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_02_03_api_text_one_per_active_endpoint_envelope_and_source(client, session_factory):
    r = _rig(client, session_factory, "+60380000010")
    ep2 = _register(client, r["hdr"], [OUTBOUND], name="second").json()["endpoint"]["id"]
    off = _register(client, r["hdr"], [OUTBOUND], name="off").json()["endpoint"]["id"]
    assert client.post(f"/api/v1/omnichannel/webhooks/{off}/disable", headers=r["hdr"]).status_code == 200

    sent = _api_text(client, r["hdr"], "+60380000010", body="Hi envelope")
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
    r = _rig(client, session_factory, "+60380000011")
    a = _api_text(client, r["hdr"], "+60380000011", body="one").json()["id"]
    b = _api_text(client, r["hdr"], "+60380000011", body="two").json()["id"]
    ids = sorted(x["event_id"] for x in _deliveries(session_factory))
    assert ids == sorted([f"{a}:outbound", f"{b}:outbound"])


def test_ac_38_02_api_template(client, session_factory):
    r = _rig(client, session_factory, "+60380000012")
    _ensure_template(session_factory, r["channel_id"], name="tpl_out")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+60380000012",
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
    r = _rig(client, session_factory, "+60380000013")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+60380000013",
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
    r = _rig(client, session_factory, "+60380000014")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60380000014", "type": "location", "location": {"lat": 3.1, "lng": 101.6, "name": "HQ"}},
        headers=r["hdr"],
    )
    assert res.status_code == 202, res.text
    row = _only_outbound(session_factory)
    assert row["event_id"] == f"{res.json()['id']}:outbound"
    assert row["payload"]["data"]["source"] == "api"


def test_ac_38_02_workflow_send_node_source_workflow(client, session_factory):
    from modules.omnichannel.services.workflow_actions import omnichannel_send_message

    r = _rig(client, session_factory, "+60380000015")
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
    phone = "+60380000071" if kind == "voice" else "+60380000072"
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
    r = _rig(client, session_factory, "+60380000073")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+60380000073",
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
    r = _rig(client, session_factory, "+60380000074")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+60380000074",
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

    r = _rig(client, session_factory, "+60380000075", events=(OUTBOUND, "message.status"))
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
    r = _rig(client, session_factory, "+60380000016")
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
    r = _rig(client, session_factory, "+60380000017")
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
    r = _rig(client, session_factory, "+60380000018")
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

    r = _rig(client, session_factory, "+60380000020")
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
    _process(session_factory, r["channel_id"], _wa_payload(wamid="wamid.in-x", from_="60380000020", text="yo"))
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
    cid = _seed_contact(session_factory, ws, first="Mig", last="Rated", phone="+60 38-000 0021")
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
    r = _rig(client, session_factory, "+60380000030")
    hdr = {"Idempotency-Key": "outbound-replay-1"}
    r1 = _api_text(client, r["hdr"], "+60380000030", extra_headers=hdr)
    r2 = _api_text(client, r["hdr"], "+60380000030", extra_headers=hdr)
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
    r = _rig(client, session_factory, "+60380000040")
    real = wd.enqueue_event
    attempts = {"outbound": 0}

    def boom(db, channel, event_type, event_id, data):
        if event_type == OUTBOUND:
            attempts["outbound"] += 1
            raise RuntimeError("enqueue exploded")
        return real(db, channel, event_type, event_id, data)

    monkeypatch.setattr(wd, "enqueue_event", boom)

    res = _api_text(client, r["hdr"], "+60380000040", body="still sent")
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
    r = _rig(client, session_factory, "+60380000050")
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
            "to": "+60380000050",
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
    r = _rig(client, session_factory, "+60380000060", events=("message.status",))
    sent = _api_text(client, r["hdr"], "+60380000060")
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
    r = _rig(client, session_factory, "+60380000061", events=("message.status",))
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
    r = _rig(client, session_factory, "+60380000062", events=("message.status",))
    mid = _api_text(client, r["hdr"], "+60380000062").json()["id"]
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

    def send(self, *a, **k):
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

    r = _rig(client, session_factory, "+60380000080", events=("message.status",))
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

    r = _rig(client, session_factory, "+60380000081", events=("message.status",))
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
    r = _rig(client, session_factory, "+60380000082", events=("message.status",))
    _use_adapter(monkeypatch, _provider_error("Re-engagement message", code="131047"))
    mid = _inbox_text(client, r["cid"]).json()["id"]
    failed = [x for x in _status_rows(session_factory, mid) if x["event_id"] == f"{mid}:FAILED"]
    assert len(failed) == 1
    assert str(failed[0]["payload"]["data"]["errorCode"]) == "131047"
    assert failed[0]["payload"]["data"]["errorMessage"] == "Re-engagement message"


def test_ac_38_16_long_provider_error_is_capped_at_300_characters(client, session_factory, monkeypatch):
    r = _rig(client, session_factory, "+60380000083", events=("message.status",))
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
    r = _rig(client, session_factory, "+60380000084", events=("message.status",))
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
    r = _rig(client, session_factory, "+60380000085")
    h = _auth(client)
    normal = _inbox_text(client, r["cid"], body="normal one").json()["id"]
    note = client.post(
        f"/omnichannel/contacts/{r['cid']}/notes", json={"body": "NOTE-SECRET-FAKE refund abuse"}, headers=h
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
    assert "NOTE-SECRET-FAKE" not in str(_deliveries(session_factory))


def test_ac_38_18_same_channel_id_under_another_tenant_or_workspace_gets_nothing(client, session_factory):
    r = _rig(client, session_factory, "+60380000086")
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
    assert _api_text(client, r["hdr"], "+60380000086").status_code == 202
    rows = _deliveries(session_factory)
    assert [x["endpoint_id"] for x in rows] == [r["ep"]]  # right endpoint got it, nobody else


def test_ac_38_19_guide_states_sender_fields_and_apikey_sender_id():
    guide = (REPO_ROOT / "documentation/omnichannel/consumer-integration-guide.md").read_text()
    assert "apikey:" in guide
    i = guide.index("apikey:")
    window = guide[max(0, i - 800) : i + 800].lower()
    assert "sender" in window and "message.outbound" in guide
