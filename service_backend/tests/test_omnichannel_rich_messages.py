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


# ── media pipeline unit checks (sniff) ───────────────────────────────────────
def test_sniff_rejects_executable():
    from modules.omnichannel.services.media_pipeline import detect_media_mime

    assert detect_media_mime(EXE) is None
    assert detect_media_mime(PNG) == "image/png"
    assert detect_media_mime(WEBM) == "video/webm"
