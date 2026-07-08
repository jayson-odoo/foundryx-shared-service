"""Plan 12 Slice 1 — rich message types (media core).

Covers: model columns + mediaUrl property (AC-12-01), upload-by-id + async send
(AC-12-02/03), voice transcode (AC-12-04), blob-fetch media endpoint dual-auth
(AC-12-05), inbound media parse + voice flag (AC-12-09), gateway media send
JSON-url + multipart (AC-12-10), per-workspace caps clamp + reject (AC-12-12),
CSW across types (AC-12-25), tenant/workspace isolation (AC-12-27).
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services import idempotency
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 128
EXE = b"MZ" + b"\x00" * 128


def _now():
    return datetime.now(timezone.utc)


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
    set_storage(None)  # force a fresh LocalDiskStorage bound to tmp_path
    yield
    settings.media_root = prev
    set_storage(None)


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    return client.post("/auth/login", json={"email": email, "password": password}).json()[
        "access_token"
    ]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _default_workspace_id(session_factory) -> str:
    from modules.omnichannel.models import Workspace

    db = session_factory()
    wid = db.query(Workspace).filter(Workspace.is_default.is_(True)).first().id
    db.close()
    return wid


def _seed_channel(session_factory, workspace_id, phone_number_id="pn-rich"):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    ch = Channel(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=workspace_id,
        channel_type="WHATSAPP",
        name="Rich WA",
        credentials_json=encrypt_credentials({"dev": True}),
        phone_number_id=phone_number_id,
        display_phone_number="+60 11-111 1111",
        is_active=True,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
    )
    db.add(ch)
    db.commit()
    cid = ch.id
    db.close()
    return cid


def _seed_contact(session_factory, workspace_id, phone="+60123456700", open_window=True):
    from modules.omnichannel.models import Contact
    from modules.omnichannel.services import statuses

    db = session_factory()
    c = Contact(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=workspace_id,
        first_name="Media",
        last_name="Tester",
        phone=phone,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"),
        priority="MEDIUM",
        csw_expires_at=(_now() + timedelta(hours=20)) if open_window else None,
    )
    db.add(c)
    db.commit()
    cid = c.id
    db.close()
    return cid


def _mint_key(client, workspace_id, name="Rich key"):
    return client.post(
        f"/omnichannel/workspaces/{workspace_id}/api-keys",
        json={"name": name},
        headers=_auth(client),
    ).json()["fullKey"]


def _send_image(client, contact_id, content=PNG, kind="image", caption="hi"):
    return client.post(
        f"/omnichannel/contacts/{contact_id}/media",
        files={"file": ("a.png", content, "image/png")},
        data={"kind": kind, "caption": caption},
        headers=_auth(client),
    )


# ── AC-12-01 model + AC-12-02/03 pipeline + async send ───────────────────────
def test_media_send_stores_key_and_sends(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)

    res = _send_image(client, cid)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["messageType"] == "IMAGE"
    assert body["mediaMime"] == "image/png"
    # Eager task ran inline → SENT + a (dev) external id.
    assert body["deliveryStatus"] == "SENT"
    assert body["externalMessageId"]
    # mediaUrl is the wire property off media_key (not a stored URL).
    assert body["mediaUrl"] == f"/omnichannel/media/{body['id']}"

    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    row = db.query(ConversationMessage).filter(ConversationMessage.id == body["id"]).first()
    assert row.media_key and row.media_url is None
    assert row.media_size == len(PNG)
    db.close()


# ── AC-12-04 voice transcode ─────────────────────────────────────────────────
def test_voice_transcode_invoked(client, session_factory, monkeypatch):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)

    calls = {}

    def fake_transcode(content):
        calls["n"] = calls.get("n", 0) + 1
        return b"OggS" + b"\x00" * 64  # pretend ogg

    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.transcode_voice", fake_transcode
    )
    res = client.post(
        f"/omnichannel/contacts/{cid}/media",
        files={"file": ("v.webm", WEBM, "audio/webm")},
        data={"kind": "voice"},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    assert res.json()["deliveryStatus"] == "SENT"
    assert calls.get("n") == 1


def test_voice_transcode_failure_marks_failed(client, session_factory, monkeypatch):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)

    from modules.omnichannel.services.media_pipeline import MediaRejected

    def boom(content):
        raise MediaRejected("transcode_failed", "bad")

    monkeypatch.setattr("modules.omnichannel.services.send_runner.transcode_voice", boom)
    res = client.post(
        f"/omnichannel/contacts/{cid}/media",
        files={"file": ("v.webm", WEBM, "audio/webm")},
        data={"kind": "voice"},
        headers=_auth(client),
    )
    assert res.status_code == 201
    assert res.json()["deliveryStatus"] == "FAILED"


# ── AC-12-12 caps clamp + reject ─────────────────────────────────────────────
def test_oversize_rejected(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    # Set a tiny image cap via settings, then exceed it.
    client.put(
        f"/omnichannel/settings?workspaceId={ws}",
        json={"imageMaxBytes": 10},
        headers=_auth(client),
    )
    res = _send_image(client, cid, content=PNG)
    assert res.status_code == 422
    assert "limit" in res.json()["detail"].lower()


def test_bad_mime_rejected(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(
        f"/omnichannel/contacts/{cid}/media",
        files={"file": ("x.png", EXE, "image/png")},  # declared png, real MZ exe
        data={"kind": "image"},
        headers=_auth(client),
    )
    assert res.status_code == 422


def test_caps_clamped_to_meta_ceiling(client, session_factory):
    ws = _default_workspace_id(session_factory)
    # Configure an absurd cap → resolved effective is clamped to the Meta ceiling.
    client.put(
        f"/omnichannel/settings?workspaceId={ws}",
        json={"imageMaxBytes": 999_999_999},
        headers=_auth(client),
    )
    res = client.get(f"/omnichannel/settings?workspaceId={ws}", headers=_auth(client))
    body = res.json()
    assert body["effective"]["IMAGE"]["maxBytes"] == 5 * 1024 * 1024
    assert body["effective"]["IMAGE"]["ceilingBytes"] == 5 * 1024 * 1024


# ── AC-12-25 CSW across types ────────────────────────────────────────────────
def test_media_blocked_when_window_closed(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws, open_window=False)
    res = _send_image(client, cid)
    assert res.status_code == 422
    assert "window" in res.json()["detail"].lower()


# ── AC-12-05 blob endpoint dual-auth + isolation ─────────────────────────────
def test_media_endpoint_session_and_apikey(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    msg_id = _send_image(client, cid).json()["id"]

    # Session JWT (agent)
    r1 = client.get(f"/omnichannel/media/{msg_id}", headers=_auth(client))
    assert r1.status_code == 200
    assert r1.content == PNG
    assert r1.headers["content-security-policy"] == "sandbox"
    assert r1.headers["x-content-type-options"] == "nosniff"

    # Workspace API key (EMS)
    key = _mint_key(client, ws)
    r2 = client.get(
        f"/omnichannel/media/{msg_id}", headers={"Authorization": f"Bearer {key}"}
    )
    assert r2.status_code == 200
    assert r2.content == PNG

    # No auth → 401
    assert client.get(f"/omnichannel/media/{msg_id}").status_code == 401
    # Unknown id → 404
    assert client.get(f"/omnichannel/media/nope", headers=_auth(client)).status_code == 404


def test_media_endpoint_cross_workspace_apikey_404(client, session_factory):
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    msg_id = _send_image(client, cid).json()["id"]

    # A second workspace + its own key must NOT read workspace-1's media.
    db = session_factory()
    ws2 = Workspace(
        tenant_id=DEFAULT_TENANT_ID,
        name="WS2",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
    )
    db.add(ws2)
    db.commit()
    ws2_id = ws2.id
    db.close()
    key2 = _mint_key(client, ws2_id, name="ws2")
    r = client.get(
        f"/omnichannel/media/{msg_id}", headers={"Authorization": f"Bearer {key2}"}
    )
    assert r.status_code == 404


# ── AC-12-09 inbound media parse + voice flag ────────────────────────────────
def _inbound_payload(pnid, mtype, media, wa_from="60123456700", wamid="wamid.in-1"):
    obj = {"id": "media-xyz", **media}
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": pnid},
                            "contacts": [{"wa_id": wa_from, "profile": {"name": "In User"}}],
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": wa_from,
                                    "type": mtype,
                                    mtype: obj,
                                }
                            ],
                        },
                    }
                ]
            }
        ]
    }


def test_inbound_image_stored_and_voice_flag(session_factory, monkeypatch):
    from modules.omnichannel.adapters import whatsapp_cloud
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services.inbound_service import InboundService

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-in")

    # fetch_media stub → deterministic bytes.
    monkeypatch.setattr(
        whatsapp_cloud.WhatsAppCloudAdapter,
        "fetch_media",
        lambda self, creds, mid: {"content": PNG, "mime_type": "image/png"},
    )

    db = session_factory()
    InboundService(db).process_payload(
        "pn-in", _inbound_payload("pn-in", "image", {"mime_type": "image/png"})
    )
    row = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.external_message_id == "wamid.in-1")
        .first()
    )
    assert row.message_type == "IMAGE"
    assert row.media_key and row.media_mime == "image/png"
    assert row.media_size == len(PNG)
    db.close()

    # Voice: audio with voice==true → VOICE
    db = session_factory()
    monkeypatch.setattr(
        whatsapp_cloud.WhatsAppCloudAdapter,
        "fetch_media",
        lambda self, creds, mid: {"content": b"OggS0000", "mime_type": "audio/ogg"},
    )
    InboundService(db).process_payload(
        "pn-in",
        _inbound_payload(
            "pn-in", "audio", {"mime_type": "audio/ogg", "voice": True}, wamid="wamid.voice-1"
        ),
    )
    vrow = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.external_message_id == "wamid.voice-1")
        .first()
    )
    assert vrow.message_type == "VOICE"
    db.close()


# ── AC-12-10 gateway media send ──────────────────────────────────────────────
def test_gateway_media_multipart(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_contact(session_factory, ws, phone="+60123456701")
    key = _mint_key(client, ws)
    payload = {"to": "+60123456701", "type": "image", "media": {"caption": "hey"}}
    res = client.post(
        "/api/v1/omnichannel/messages",
        files={"file": ("a.png", PNG, "image/png")},
        data={"payload": json.dumps(payload)},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "queued" and body["id"]


def test_gateway_media_by_url(client, session_factory, monkeypatch):
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_contact(session_factory, ws, phone="+60123456702")
    key = _mint_key(client, ws)
    monkeypatch.setattr(PublicGatewayService, "_fetch_url", lambda self, url: PNG)
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+60123456702",
            "type": "image",
            "media": {"url": "https://example.com/a.png", "caption": "x"},
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 202, res.text
    assert res.json()["status"] == "queued"


def test_gateway_media_oversize_typed_error(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_contact(session_factory, ws, phone="+60123456703")
    client.put(
        f"/omnichannel/settings?workspaceId={ws}",
        json={"imageMaxBytes": 5},
        headers=_auth(client),
    )
    key = _mint_key(client, ws)
    res = client.post(
        "/api/v1/omnichannel/messages",
        files={"file": ("a.png", PNG, "image/png")},
        data={"payload": json.dumps({"to": "+60123456703", "type": "image"})},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "oversize"


# ── AC-12-26 WS realtime on every mutation ───────────────────────────────────
def test_ws_publish_on_outbound_send(client, session_factory, monkeypatch):
    """An outbound media send publishes the optimistic ``message.created`` AND
    the async ``message.status`` (SENT) to the workspace room (AC-12-26)."""
    from modules.omnichannel.services import realtime

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)

    events = []
    monkeypatch.setattr(realtime, "publish", lambda w, ev: events.append((w, ev)))

    res = _send_image(client, cid)
    assert res.status_code == 201, res.text
    types = [ev["type"] for _, ev in events]
    assert "message.created" in types  # optimistic bubble
    assert "message.status" in types  # async upload-by-id → SENT
    # Every publish targets the contact's workspace room.
    assert all(w == ws for w, _ in events)
    status_ev = next(ev for _, ev in events if ev["type"] == "message.status")
    assert status_ev["deliveryStatus"] == "SENT"
    assert status_ev["messageId"] == res.json()["id"]


def test_ws_publish_on_failed_send(client, session_factory, monkeypatch):
    """A transcode failure still publishes ``message.status`` = FAILED (no mutation
    path leaves inboxes stale, AC-12-26)."""
    from modules.omnichannel.services import realtime
    from modules.omnichannel.services.media_pipeline import MediaRejected

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)

    events = []
    monkeypatch.setattr(realtime, "publish", lambda w, ev: events.append(ev))
    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.transcode_voice",
        lambda content: (_ for _ in ()).throw(MediaRejected("transcode_failed", "bad")),
    )
    res = client.post(
        f"/omnichannel/contacts/{cid}/media",
        files={"file": ("v.webm", WEBM, "audio/webm")},
        data={"kind": "voice"},
        headers=_auth(client),
    )
    assert res.status_code == 201
    status_evs = [e for e in events if e["type"] == "message.status"]
    assert status_evs and status_evs[-1]["deliveryStatus"] == "FAILED"


# ── AC-12-11 / AC-12-26 inbound: WS publish + webhook media envelope ──────────
def test_inbound_publishes_ws_and_webhook_media_fields(session_factory, monkeypatch):
    """Inbound media publishes ``message.created`` on WS AND fans a consumer
    ``message.inbound`` whose ``data.message`` carries the ABSOLUTE API-key gateway
    ``mediaUrl`` + media metadata + the ``voice`` flag (AC-12-11 additive fields)."""
    from modules.omnichannel.adapters import whatsapp_cloud
    from modules.omnichannel.services import realtime, webhook_delivery
    from modules.omnichannel.services.inbound_service import InboundService

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-wh")

    monkeypatch.setattr(
        whatsapp_cloud.WhatsAppCloudAdapter,
        "fetch_media",
        lambda self, creds, mid: {"content": PNG, "mime_type": "image/png"},
    )
    ws_events = []
    monkeypatch.setattr(realtime, "publish", lambda w, ev: ws_events.append(ev))
    captured: dict = {}
    monkeypatch.setattr(
        webhook_delivery,
        "enqueue_event",
        lambda db, channel, event_type, event_id, data: captured.__setitem__(event_type, data),
    )

    db = session_factory()
    InboundService(db).process_payload(
        "pn-wh", _inbound_payload("pn-wh", "image", {"mime_type": "image/png"})
    )
    db.close()

    assert any(e["type"] == "message.created" for e in ws_events)
    msg = captured["message.inbound"]["message"]
    # Absolute gateway URL (not the inbox-relative path) so EMS can fetch it.
    assert msg["mediaUrl"].startswith("http")
    assert "/omnichannel/media/" in msg["mediaUrl"]
    # Consumer-facing envelope names (EMS integration ticket): mimeType/filename/size.
    assert msg["mimeType"] == "image/png"
    assert msg["size"] == len(PNG)
    assert "mediaMime" not in msg and "mediaSize" not in msg
    assert msg["voice"] is False


def test_inbound_status_receipt_publishes_ws(session_factory, monkeypatch):
    """A delivery receipt for an outbound message publishes ``message.status`` on
    WS (AC-12-26)."""
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services import realtime, webhook_delivery
    from modules.omnichannel.services.inbound_service import InboundService

    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-st")
    cid = _seed_contact(session_factory, ws, phone="+60123456777")

    db = session_factory()
    row = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID,
        contact_id=cid,
        channel_id=ch,
        sender_type="AGENT",
        message_type="TEXT",
        body="hi",
        external_message_id="wamid.out-1",
        delivery_status="SENT",
        created_at=_now(),
    )
    db.add(row)
    db.commit()
    db.close()

    events = []
    monkeypatch.setattr(realtime, "publish", lambda w, ev: events.append(ev))
    monkeypatch.setattr(
        webhook_delivery, "enqueue_event", lambda *a, **k: 0
    )
    status_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "pn-st"},
                            "statuses": [{"id": "wamid.out-1", "status": "delivered"}],
                        },
                    }
                ]
            }
        ]
    }
    db = session_factory()
    InboundService(db).process_payload("pn-st", status_payload)
    db.close()
    status_evs = [e for e in events if e["type"] == "message.status"]
    assert status_evs and status_evs[-1]["deliveryStatus"] == "DELIVERED"


# ── media pipeline unit checks (sniff) ───────────────────────────────────────
def test_sniff_rejects_executable():
    from modules.omnichannel.services.media_pipeline import detect_media_mime

    assert detect_media_mime(EXE) is None
    assert detect_media_mime(PNG) == "image/png"
    assert detect_media_mime(WEBM) == "video/webm"


# ── SSRF guard on gateway media-by-url (plan 12 review BLOCKER) ───────────────
def test_gateway_media_url_blocks_metadata_ip(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_contact(session_factory, ws, phone="+60123456799")
    key = _mint_key(client, ws)
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+60123456799",
            "type": "image",
            "media": {"url": "https://169.254.169.254/latest/meta-data/"},
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_media_url"


def test_gateway_media_url_requires_https(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_contact(session_factory, ws, phone="+60123456798")
    key = _mint_key(client, ws)
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60123456798", "type": "image", "media": {"url": "http://example.com/a.png"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_media_url"


# ── Media endpoint permission scoping (plan 12 review SHOULD-FIX 2) ───────────
def _limited_user_token(client, session_factory) -> str:
    from sqlalchemy.sql import func

    from app.models import Role, User, UserStatus
    from app.security import hash_password

    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="NoOmni", description="no perms", is_system=False)
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="noomni@example.com",
        password=hash_password("Passw0rd!x"),
        name="No Omni",
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()
    return client.post(
        "/auth/login", json={"email": "noomni@example.com", "password": "Passw0rd!x"}
    ).json()["access_token"]


def test_media_endpoint_requires_read_permission(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    msg_id = _send_image(client, cid).json()["id"]

    token = _limited_user_token(client, session_factory)
    r = client.get(f"/omnichannel/media/{msg_id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


# ── Send idempotency + transient handling (plan 12 review SHOULD-FIX 3/4) ─────
def _queued_text_row(session_factory, channel_id, contact_id) -> str:
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    row = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID,
        contact_id=contact_id,
        channel_id=channel_id,
        sender_type="AGENT",
        message_type="TEXT",
        body="hi",
        delivery_status="QUEUED",
    )
    db.add(row)
    db.commit()
    rid = row.id
    db.close()
    return rid


def test_run_send_no_double_send_on_reentry(session_factory, monkeypatch):
    from modules.omnichannel.adapters import whatsapp_cloud
    from modules.omnichannel.services.send_runner import run_send

    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    rid = _queued_text_row(session_factory, ch, cid)

    calls = {"n": 0}

    def fake_send(self, creds, phone, to, **kw):
        calls["n"] += 1
        return {"external_message_id": "wamid.once"}

    monkeypatch.setattr(whatsapp_cloud.WhatsAppCloudAdapter, "send", fake_send)
    db = session_factory()
    assert run_send(db, rid) == "SENT"
    # A retry of an already-sent row must NOT call adapter.send again.
    assert run_send(db, rid) == "SENT"
    db.close()
    assert calls["n"] == 1


def test_run_send_transient_requeues_and_raises(session_factory, monkeypatch):
    import pytest as _pytest

    from modules.omnichannel.adapters import whatsapp_cloud
    from modules.omnichannel.adapters.base import SendError
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services.send_runner import TransientSendError, run_send

    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    rid = _queued_text_row(session_factory, ch, cid)

    def boom(self, creds, phone, to, **kw):
        raise SendError("Meta 503", transient=True)

    monkeypatch.setattr(whatsapp_cloud.WhatsAppCloudAdapter, "send", boom)
    db = session_factory()
    with _pytest.raises(TransientSendError):
        run_send(db, rid)
    row = db.query(ConversationMessage).filter(ConversationMessage.id == rid).first()
    assert row.delivery_status == "QUEUED"  # requeued for a backoff retry
    db.close()


def test_run_send_permanent_meta_rejection_fails(session_factory, monkeypatch):
    from modules.omnichannel.adapters import whatsapp_cloud
    from modules.omnichannel.adapters.base import SendError
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services.send_runner import run_send

    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    rid = _queued_text_row(session_factory, ch, cid)

    def boom(self, creds, phone, to, **kw):
        raise SendError("Invalid recipient", transient=False)

    monkeypatch.setattr(whatsapp_cloud.WhatsAppCloudAdapter, "send", boom)
    db = session_factory()
    assert run_send(db, rid) == "FAILED"
    row = db.query(ConversationMessage).filter(ConversationMessage.id == rid).first()
    assert row.delivery_status == "FAILED"
    db.close()


# ══════════════════════════════════════════════════════════════════════════════
# Slice 2 — Interactive + structured types (AC-12-13..18)
# ══════════════════════════════════════════════════════════════════════════════
def _inbound_msg(pnid, message: dict, wa_from="60123456700"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": pnid},
                            "contacts": [{"wa_id": wa_from, "profile": {"name": "In User"}}],
                            "messages": [{"from": wa_from, **message}],
                        },
                    }
                ]
            }
        ]
    }


# ── AC-12-13 interactive send ────────────────────────────────────────────────
def test_send_interactive_buttons(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(
        f"/omnichannel/contacts/{cid}/interactive",
        json={
            "kind": "buttons",
            "body": "Pick one",
            "buttons": [{"id": "y", "title": "Yes"}, {"id": "n", "title": "No"}],
        },
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["messageType"] == "INTERACTIVE"
    assert body["deliveryStatus"] == "SENT"
    assert body["payload"]["kind"] == "buttons"
    assert len(body["payload"]["buttons"]) == 2


def test_send_interactive_too_many_buttons_422(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(
        f"/omnichannel/contacts/{cid}/interactive",
        json={
            "kind": "buttons",
            "body": "x",
            "buttons": [{"id": str(i), "title": f"b{i}"} for i in range(4)],
        },
        headers=_auth(client),
    )
    assert res.status_code == 422


def test_interactive_media_header_closed_window_no_orphan_blob(session_factory, monkeypatch):
    """A media-header interactive on a CLOSED 24h window must reject BEFORE storing
    the header blob — else the blob is orphaned (never sent) (reviewer #2)."""
    import app.services.storage as storage_mod
    from modules.omnichannel.services.message_service import MessageService, SendRejected

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws, phone="+60123456683", open_window=False)

    def _boom(*_a, **_k):  # storage must never be touched on a closed window
        raise AssertionError("storage_for_tenant should not be called on a closed window")

    monkeypatch.setattr(storage_mod, "storage_for_tenant", _boom)

    db = session_factory()
    svc = MessageService(db)
    with pytest.raises(SendRejected):
        svc.send_interactive(
            cid,
            DEFAULT_TENANT_ID,
            "usr-test",
            defn={
                "kind": "buttons",
                "body": "Hi",
                "header": {"type": "image"},
                "buttons": [{"id": "a", "title": "A"}],
            },
            header_content=PNG,
            header_filename="a.png",
        )
    db.close()


def test_send_interactive_list_over_10_rows_422(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    rows = [{"id": str(i), "title": f"r{i}"} for i in range(11)]
    res = client.post(
        f"/omnichannel/contacts/{cid}/interactive",
        json={"kind": "list", "body": "b", "list": {"button": "Open", "sections": [{"rows": rows}]}},
        headers=_auth(client),
    )
    assert res.status_code == 422


def test_send_interactive_cta_bad_url_422(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(
        f"/omnichannel/contacts/{cid}/interactive",
        json={"kind": "cta_url", "body": "b", "cta": {"displayText": "Go", "url": "javascript:alert(1)"}},
        headers=_auth(client),
    )
    assert res.status_code == 422


def test_send_interactive_media_header_multipart(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    defn = {
        "kind": "buttons",
        "header": {"type": "image"},
        "body": "See attached",
        "buttons": [{"id": "ok", "title": "OK"}],
    }
    res = client.post(
        f"/omnichannel/contacts/{cid}/interactive",
        files={"file": ("h.png", PNG, "image/png")},
        data={"payload": json.dumps(defn)},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    assert res.json()["messageType"] == "INTERACTIVE"
    assert res.json()["mediaMime"] == "image/png"


# ── AC-12-15 location send ───────────────────────────────────────────────────
def test_send_location(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(
        f"/omnichannel/contacts/{cid}/location",
        json={"lat": 3.15, "lng": 101.7, "name": "KLCC", "address": "Kuala Lumpur"},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["messageType"] == "LOCATION"
    assert body["payload"]["lat"] == 3.15 and body["payload"]["name"] == "KLCC"


def test_send_location_out_of_range_422(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(
        f"/omnichannel/contacts/{cid}/location",
        json={"lat": 999, "lng": 0},
        headers=_auth(client),
    )
    assert res.status_code == 422


# ── AC-12-16 contacts send ───────────────────────────────────────────────────
def test_send_contacts(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(
        f"/omnichannel/contacts/{cid}/contacts",
        json={"contacts": [{"name": "Jane Doe", "phones": [{"phone": "+60123", "type": "CELL"}]}]},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["messageType"] == "CONTACTS"
    assert body["payload"]["contacts"][0]["name"]["formatted_name"] == "Jane Doe"


def test_send_contacts_no_phone_422(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(
        f"/omnichannel/contacts/{cid}/contacts",
        json={"contacts": [{"name": "No Phone", "phones": []}]},
        headers=_auth(client),
    )
    assert res.status_code == 422


# ── AC-12-25 CSW applies to structured types ─────────────────────────────────
def test_structured_blocked_when_window_closed(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws, phone="+60123456690", open_window=False)
    res = client.post(
        f"/omnichannel/contacts/{cid}/location",
        json={"lat": 3.1, "lng": 101.6},
        headers=_auth(client),
    )
    assert res.status_code == 422
    assert "window" in res.json()["detail"].lower()


# ── AC-12-14 inbound interactive reply threaded ──────────────────────────────
def test_inbound_interactive_reply_threaded(session_factory):
    from modules.omnichannel.models import Contact, ConversationMessage
    from modules.omnichannel.services.inbound_service import InboundService

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-ir")
    # Seed the ORIGINAL outbound interactive the reply threads to.
    db = session_factory()
    from modules.omnichannel.models import Channel

    ch = db.query(Channel).filter(Channel.phone_number_id == "pn-ir").first()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, first_name="R", phone="+60123456700",
        priority="MEDIUM",
    )
    db.add(contact)
    db.flush()
    orig = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID, contact_id=contact.id, channel_id=ch.id, sender_type="AGENT",
        message_type="INTERACTIVE", body="Pick", external_message_id="wamid.orig",
        payload_json={"kind": "buttons", "body": "Pick"},
    )
    db.add(orig)
    db.commit()
    orig_id = orig.id
    db.close()

    db = session_factory()
    InboundService(db).process_payload(
        "pn-ir",
        _inbound_msg(
            "pn-ir",
            {
                "id": "wamid.reply",
                "type": "interactive",
                "interactive": {"type": "button_reply", "button_reply": {"id": "y", "title": "Yes"}},
                "context": {"id": "wamid.orig"},
            },
        ),
    )
    row = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.external_message_id == "wamid.reply")
        .first()
    )
    assert row.message_type == "INTERACTIVE_REPLY"
    assert row.payload_json["title"] == "Yes" and row.payload_json["kind"] == "button"
    assert (row.metadata_json or {}).get("reply_to", {}).get("id") == orig_id
    db.close()


# ── AC-12-15/16 inbound location + contacts parse ────────────────────────────
def test_inbound_location_and_contacts(session_factory):
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services.inbound_service import InboundService

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-lc")

    db = session_factory()
    InboundService(db).process_payload(
        "pn-lc",
        _inbound_msg(
            "pn-lc",
            {"id": "wamid.loc", "type": "location", "location": {"latitude": 1.3, "longitude": 103.8, "name": "Home"}},
        ),
    )
    InboundService(db).process_payload(
        "pn-lc",
        _inbound_msg(
            "pn-lc",
            {
                "id": "wamid.con",
                "type": "contacts",
                "contacts": [{"name": {"formatted_name": "Bob"}, "phones": [{"phone": "+60199"}]}],
            },
        ),
    )
    loc = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "wamid.loc").first()
    con = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "wamid.con").first()
    assert loc.message_type == "LOCATION" and loc.payload_json["lat"] == 1.3
    assert con.message_type == "CONTACTS" and con.payload_json["contacts"][0]["name"]["formatted_name"] == "Bob"
    db.close()


# ── AC-12-17 unknown-type placeholder ────────────────────────────────────────
def test_inbound_unknown_type_placeholder(session_factory):
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services.inbound_service import InboundService

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-unk")
    db = session_factory()
    res = InboundService(db).process_payload(
        "pn-unk", _inbound_msg("pn-unk", {"id": "wamid.order", "type": "order", "order": {"x": 1}})
    )
    assert res["messages"] == 1
    row = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "wamid.order").first()
    assert row.message_type == "UNSUPPORTED"
    db.close()


# ── AC-12-18 gateway interactive/location/contacts ───────────────────────────
def test_gateway_location(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_contact(session_factory, ws, phone="+60123456680")
    key = _mint_key(client, ws)
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60123456680", "type": "location", "location": {"lat": 3.1, "lng": 101.6, "name": "HQ"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 202, res.text
    assert res.json()["status"] == "queued"


def test_gateway_interactive_and_malformed(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_contact(session_factory, ws, phone="+60123456681")
    key = _mint_key(client, ws)
    ok = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+60123456681",
            "type": "interactive",
            "interactive": {"kind": "buttons", "body": "Hi", "buttons": [{"id": "a", "title": "A"}]},
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert ok.status_code == 202, ok.text
    bad = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+60123456681",
            "type": "interactive",
            "interactive": {"kind": "buttons", "body": "Hi", "buttons": []},
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert bad.status_code == 422


def test_gateway_interactive_bad_media_header_is_422(client, session_factory, monkeypatch):
    """An interactive with a media header whose URL yields non-image bytes must
    surface a typed 422 (MediaRejected), never an unhandled 500 (reviewer #1)."""
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_contact(session_factory, ws, phone="+60123456682")
    key = _mint_key(client, ws)
    # Fetched bytes are HTML, not an image → sniff rejects.
    monkeypatch.setattr(PublicGatewayService, "_fetch_url", lambda self, url: b"<html>nope</html>")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={
            "to": "+60123456682",
            "type": "interactive",
            "interactive": {
                "kind": "buttons",
                "body": "Hi",
                "header": {"type": "image", "url": "https://example.com/page.html"},
                "buttons": [{"id": "a", "title": "A"}],
            },
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 422, res.text


# ── structured.py unit checks ────────────────────────────────────────────────
def test_build_meta_interactive_shapes():
    from modules.omnichannel.services.structured import build_meta_interactive

    btn = build_meta_interactive(
        {"kind": "buttons", "body": "b", "buttons": [{"id": "x", "title": "X"}]}
    )
    assert btn["type"] == "button"
    assert btn["action"]["buttons"][0]["reply"]["id"] == "x"

    cta = build_meta_interactive(
        {"kind": "cta_url", "body": "b", "cta": {"displayText": "Go", "url": "https://x.io"}}
    )
    assert cta["type"] == "cta_url"
    assert cta["action"]["parameters"]["url"] == "https://x.io"

    img = build_meta_interactive(
        {"kind": "buttons", "header": {"type": "image"}, "body": "b", "buttons": [{"id": "x", "title": "X"}]},
        media_id="MID",
    )
    assert img["header"] == {"type": "image", "image": {"id": "MID"}}


# ── AC-12-19/20/21 reactions ─────────────────────────────────────────────────
def _seed_message(session_factory, contact_id, external_id, sender_type="CONTACT"):
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    row = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID,
        contact_id=contact_id,
        sender_type=sender_type,
        message_type="TEXT",
        body="hi",
        external_message_id=external_id,
        delivery_status="DELIVERED",
    )
    db.add(row)
    db.commit()
    mid = row.id
    db.close()
    return mid


def _reactions_count(session_factory):
    from modules.omnichannel.models import MessageReaction

    db = session_factory()
    n = db.query(MessageReaction).count()
    db.close()
    return n


def test_inbound_reaction_upserts_never_a_bubble(session_factory):
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services.inbound_service import InboundService

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-rx")
    cid = _seed_contact(session_factory, ws, phone="+60123456900")
    mid = _seed_message(session_factory, cid, "wamid.tgt1", sender_type="AGENT")

    db = session_factory()
    res = InboundService(db).process_payload(
        "pn-rx",
        _inbound_msg(
            "pn-rx",
            {"id": "wamid.rx1", "type": "reaction", "reaction": {"message_id": "wamid.tgt1", "emoji": "👍"}},
            wa_from="60123456900",
        ),
    )
    db.close()
    assert res.get("reactions") == 1
    # No REACTION message bubble stored.
    db = session_factory()
    bubbles = db.query(ConversationMessage).filter(ConversationMessage.message_type == "REACTION").count()
    db.close()
    assert bubbles == 0
    assert _reactions_count(session_factory) == 1

    # The chip rides the message wire.
    from modules.omnichannel.services.conversation_service import ConversationService

    db = session_factory()
    items = ConversationService(db).list_messages(cid, DEFAULT_TENANT_ID)
    db.close()
    target = next(i for i in items if i.id == mid)
    assert target.reactions and target.reactions[0]["emoji"] == "👍"

    # Empty emoji removes.
    db = session_factory()
    InboundService(db).process_payload(
        "pn-rx",
        _inbound_msg(
            "pn-rx",
            {"id": "wamid.rx2", "type": "reaction", "reaction": {"message_id": "wamid.tgt1", "emoji": ""}},
            wa_from="60123456900",
        ),
    )
    db.close()
    assert _reactions_count(session_factory) == 0


def test_inbound_reaction_unknown_target_dropped(session_factory):
    from modules.omnichannel.services.inbound_service import InboundService

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-rx2")
    _seed_contact(session_factory, ws, phone="+60123456901")
    db = session_factory()
    res = InboundService(db).process_payload(
        "pn-rx2",
        _inbound_msg(
            "pn-rx2",
            {"id": "wamid.rx3", "type": "reaction", "reaction": {"message_id": "wamid.nope", "emoji": "❤️"}},
            wa_from="60123456901",
        ),
    )
    db.close()
    assert res.get("reactions", 0) == 0
    assert res["skipped"] >= 1
    assert _reactions_count(session_factory) == 0


def test_agent_react_endpoint_and_wire(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-rx3")
    cid = _seed_contact(session_factory, ws, phone="+60123456902")
    mid = _seed_message(session_factory, cid, "wamid.tgt2")

    r = client.post(
        f"/omnichannel/contacts/{cid}/messages/{mid}/react",
        json={"emoji": "🎉"},
        headers=_auth(client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["removed"] is False
    assert _reactions_count(session_factory) == 1

    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=_auth(client)).json()
    target = next(m for m in msgs if m["id"] == mid)
    assert target["reactions"][0]["emoji"] == "🎉"

    # Re-react empty removes.
    r2 = client.post(
        f"/omnichannel/contacts/{cid}/messages/{mid}/react",
        json={"emoji": ""},
        headers=_auth(client),
    )
    assert r2.status_code == 200
    assert r2.json()["removed"] is True
    assert _reactions_count(session_factory) == 0


def test_agent_react_single_business_identity(session_factory):
    """Two DIFFERENT agents reacting on the same message keep ONE row — Meta
    stores one reaction per direction, so agent B overwrites agent A (reviewer)."""
    from modules.omnichannel.services.message_service import MessageService

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-rx8")
    cid = _seed_contact(session_factory, ws, phone="+60123456907")
    mid = _seed_message(session_factory, cid, "wamid.tgt7")

    db = session_factory()
    MessageService(db).react(mid, DEFAULT_TENANT_ID, "usr-agent-a", emoji="👍")
    db.close()
    db = session_factory()
    MessageService(db).react(mid, DEFAULT_TENANT_ID, "usr-agent-b", emoji="❤️")
    db.close()

    from modules.omnichannel.models import MessageReaction

    db = session_factory()
    rows = db.query(MessageReaction).filter(MessageReaction.target_message_id == mid).all()
    db.close()
    assert len(rows) == 1  # one agent chip, not two
    assert rows[0].emoji == "❤️"  # the later react wins


def test_agent_react_closed_window_409_via_422(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-rx4")
    cid = _seed_contact(session_factory, ws, phone="+60123456903", open_window=False)
    mid = _seed_message(session_factory, cid, "wamid.tgt3")
    r = client.post(
        f"/omnichannel/contacts/{cid}/messages/{mid}/react",
        json={"emoji": "👍"},
        headers=_auth(client),
    )
    assert r.status_code == 422  # CSW closed


def test_reaction_ws_publish(client, session_factory, monkeypatch):
    from modules.omnichannel.services import realtime

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-rx5")
    cid = _seed_contact(session_factory, ws, phone="+60123456904")
    mid = _seed_message(session_factory, cid, "wamid.tgt4")
    published: list = []
    monkeypatch.setattr(realtime, "publish", lambda wsid, ev: published.append(ev))
    client.post(
        f"/omnichannel/contacts/{cid}/messages/{mid}/react",
        json={"emoji": "🔥"},
        headers=_auth(client),
    )
    assert any(e.get("type") == "message.reaction" and e.get("emoji") == "🔥" for e in published)


def test_gateway_reaction_durable_id(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-rx6")
    cid = _seed_contact(session_factory, ws, phone="+60123456905")
    mid = _seed_message(session_factory, cid, "wamid.tgt5")
    key = _mint_key(client, ws)
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60123456905", "type": "reaction", "reaction": {"messageId": mid, "emoji": "😀"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 202, res.text
    assert _reactions_count(session_factory) == 1


def _seed_second_workspace(session_factory):
    from modules.omnichannel.models import Workspace

    db = session_factory()
    ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Second RX", is_default=False)
    db.add(ws)
    db.commit()
    wid = ws.id
    db.close()
    return wid


# ══════════════════════════════════════════════════════════════════════════════
# AC-12-22 — template media/button headers at send
# ══════════════════════════════════════════════════════════════════════════════
def _seed_template(session_factory, channel_id, components, name="tpl_rich", status="APPROVED"):
    from modules.omnichannel.models import WhatsappTemplate

    db = session_factory()
    t = WhatsappTemplate(
        tenant_id=DEFAULT_TENANT_ID,
        channel_id=channel_id,
        name=name,
        language="en",
        category="UTILITY",
        status=status,
        components_json=components,
    )
    db.add(t)
    db.commit()
    tid = t.id
    db.close()
    return tid


_TEXT_HEADER_BUTTON = [
    {"type": "HEADER", "format": "TEXT", "text": "Hi {{1}}"},
    {"type": "BODY", "text": "Your order {{1}} has shipped."},
    {
        "type": "BUTTONS",
        "buttons": [
            {"type": "URL", "text": "Track", "url": "https://track.example.com/{{1}}"},
            {"type": "QUICK_REPLY", "text": "Thanks"},
        ],
    },
]
_MEDIA_HEADER = [
    {"type": "HEADER", "format": "IMAGE"},
    {"type": "BODY", "text": "Hi {{1}}, see the flyer."},
]


def test_analyze_template_matrix():
    from modules.omnichannel.services.template_send import analyze_template

    s = analyze_template(_TEXT_HEADER_BUTTON)
    assert s.header_format == "TEXT"
    assert s.header_text_var_count == 1
    assert s.body_var_count == 1
    assert s.button_url_var_count == 1
    assert s.button_url_indices == [0]
    assert s.has_media_header is False

    m = analyze_template(_MEDIA_HEADER)
    assert m.header_format == "IMAGE"
    assert m.has_media_header is True
    assert m.header_text_var_count == 0
    assert m.body_var_count == 1

    # No header, no buttons.
    plain = analyze_template([{"type": "BODY", "text": "Hi {{1}} and {{2}}"}])
    assert plain.header_format is None
    assert plain.body_var_count == 2
    assert plain.button_url_var_count == 0


def test_build_and_inject_header_media_id():
    from modules.omnichannel.services.template_send import (
        build_send_components,
        inject_header_media_id,
    )

    comps = build_send_components(
        _MEDIA_HEADER, header_text_vars=[], body_vars=["Sarah"], button_vars=[], header_media_id=None
    )
    header = next(c for c in comps if c["type"] == "header")
    assert header["parameters"][0]["type"] == "image"
    assert header["parameters"][0]["image"]["id"] is None
    inject_header_media_id({"components": comps}, "MID-123")
    assert header["parameters"][0]["image"]["id"] == "MID-123"

    # TEXT header + body + dynamic URL button build.
    comps2 = build_send_components(
        _TEXT_HEADER_BUTTON,
        header_text_vars=["Sarah"],
        body_vars=["ORD-9"],
        button_vars=["ORD-9"],
    )
    kinds = [(c["type"], c.get("sub_type")) for c in comps2]
    assert ("header", None) in kinds and ("body", None) in kinds and ("button", "url") in kinds
    btn = next(c for c in comps2 if c["type"] == "button")
    assert btn["index"] == "0" and btn["parameters"][0]["text"] == "ORD-9"


def test_template_list_exposes_header_button_metadata(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-tpl-list")
    _seed_template(session_factory, ch, _TEXT_HEADER_BUTTON, name="rich_meta")
    res = client.get(f"/omnichannel/channels/{ch}/templates", headers=_auth(client))
    assert res.status_code == 200, res.text
    item = next(t for t in res.json() if t["name"] == "rich_meta")
    assert item["headerFormat"] == "TEXT"
    assert item["headerVariableCount"] == 1
    assert item["variableCount"] == 1
    assert item["buttonVariableCount"] == 1


def test_send_template_text_header_body_button_components(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-tpl-1")
    cid = _seed_contact(session_factory, ws, phone="+60123457001")
    tid = _seed_template(session_factory, ch, _TEXT_HEADER_BUTTON, name="order_shipped")

    res = client.post(
        f"/omnichannel/contacts/{cid}/template",
        json={
            "templateId": tid,
            "templateHeaderVariables": ["Sarah"],
            "templateVariables": ["ORD-9"],
            "templateButtonVariables": ["ORD-9"],
        },
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    assert res.json()["messageType"] == "TEMPLATE"
    assert res.json()["deliveryStatus"] == "SENT"

    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    row = db.query(ConversationMessage).filter(ConversationMessage.id == res.json()["id"]).first()
    comps = row.payload_json["template"]["components"]
    db.close()
    header = next(c for c in comps if c["type"] == "header")
    body = next(c for c in comps if c["type"] == "body")
    button = next(c for c in comps if c["type"] == "button")
    assert header["parameters"][0] == {"type": "text", "text": "Sarah"}
    assert body["parameters"][0] == {"type": "text", "text": "ORD-9"}
    assert button["sub_type"] == "url" and button["index"] == "0"
    assert button["parameters"][0]["text"] == "ORD-9"


def test_send_template_media_header_stores_key_and_headermedia(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-tpl-2")
    cid = _seed_contact(session_factory, ws, phone="+60123457002")
    tid = _seed_template(session_factory, ch, _MEDIA_HEADER, name="flyer_promo")

    res = client.post(
        f"/omnichannel/contacts/{cid}/template",
        files={"file": ("flyer.png", PNG, "image/png")},
        data={"payload": json.dumps({"templateId": tid, "templateVariables": ["Sarah"]})},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    assert res.json()["deliveryStatus"] == "SENT"

    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    row = db.query(ConversationMessage).filter(ConversationMessage.id == res.json()["id"]).first()
    assert row.media_key and row.media_mime == "image/png"
    assert row.payload_json["template"]["headerMedia"]["kind"] == "image"
    header = next(c for c in row.payload_json["template"]["components"] if c["type"] == "header")
    assert header["parameters"][0]["type"] == "image"
    db.close()


def test_send_template_media_header_missing_file_422(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-tpl-3")
    cid = _seed_contact(session_factory, ws, phone="+60123457003")
    tid = _seed_template(session_factory, ch, _MEDIA_HEADER, name="flyer_nofile")
    res = client.post(
        f"/omnichannel/contacts/{cid}/template",
        json={"templateId": tid, "templateVariables": ["Sarah"]},
        headers=_auth(client),
    )
    assert res.status_code == 422
    assert "media header" in res.json()["detail"].lower()


def test_send_template_count_mismatches_422(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-tpl-4")
    cid = _seed_contact(session_factory, ws, phone="+60123457004")
    tid = _seed_template(session_factory, ch, _TEXT_HEADER_BUTTON, name="order_counts")

    # Wrong body count.
    r_body = client.post(
        f"/omnichannel/contacts/{cid}/template",
        json={"templateId": tid, "templateHeaderVariables": ["S"], "templateVariables": [], "templateButtonVariables": ["x"]},
        headers=_auth(client),
    )
    assert r_body.status_code == 422 and "body" in r_body.json()["detail"].lower()

    # Wrong header count.
    r_head = client.post(
        f"/omnichannel/contacts/{cid}/template",
        json={"templateId": tid, "templateHeaderVariables": [], "templateVariables": ["ORD"], "templateButtonVariables": ["x"]},
        headers=_auth(client),
    )
    assert r_head.status_code == 422 and "header" in r_head.json()["detail"].lower()

    # Wrong button count.
    r_btn = client.post(
        f"/omnichannel/contacts/{cid}/template",
        json={"templateId": tid, "templateHeaderVariables": ["S"], "templateVariables": ["ORD"], "templateButtonVariables": []},
        headers=_auth(client),
    )
    assert r_btn.status_code == 422 and "button" in r_btn.json()["detail"].lower()


def test_send_template_via_messages_endpoint_still_works(client, session_factory):
    """Back-compat: a header-less/text template still sends via POST /messages."""
    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-tpl-5")
    cid = _seed_contact(session_factory, ws, phone="+60123457005")
    tid = _seed_template(
        session_factory, ch, [{"type": "BODY", "text": "Hi {{1}}, thanks!"}], name="plain_body"
    )
    res = client.post(
        f"/omnichannel/contacts/{cid}/messages",
        json={"messageType": "TEMPLATE", "templateId": tid, "templateVariables": ["Sarah"]},
        headers=_auth(client),
    )
    assert res.status_code == 201, res.text
    assert res.json()["deliveryStatus"] == "SENT"
    assert "Hi Sarah, thanks!" == res.json()["body"]


def test_gateway_reaction_cross_workspace_404(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-rx7")
    cid = _seed_contact(session_factory, ws, phone="+60123456906")
    mid = _seed_message(session_factory, cid, "wamid.tgt6")
    # A key minted on a DIFFERENT workspace must not react on this thread.
    other_ws = _seed_second_workspace(session_factory)
    _seed_channel(session_factory, other_ws, phone_number_id="pn-rx7b")
    key = _mint_key(client, other_ws, name="Other WS key")
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60123456906", "type": "reaction", "reaction": {"messageId": mid, "emoji": "😀"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 404
    assert _reactions_count(session_factory) == 0
