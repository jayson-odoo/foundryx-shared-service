"""Plan 32 (A7a) Slice S5 - inbound media fetch (SSRF-guarded Meta CDN
allowlist), outbound attachment upload-by-id, watermark/`mids` receipts,
reactions and rate-limit transient classification.

AC-CHN-46..52 (see documentation/plans/sprint-4/
32-omnichannel-channels-messenger-instagram-acceptance-criteria.md).
"""
import json
from datetime import datetime, timedelta, timezone

import fakeredis
import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.adapters.base import SendError
from modules.omnichannel.adapters.instagram import InstagramAdapter
from modules.omnichannel.adapters.messenger import DEV_RATE_LIMIT_PSID, MessengerAdapter
from modules.omnichannel.services import realtime
from tests.test_omnichannel_channels_instagram import _ig_channel
from tests.test_omnichannel_channels_messenger import _fb_channel, _process
from tests.test_omnichannel_channels_send import _fb_contact_with_identity, _now


@pytest.fixture(autouse=True)
def _fake_realtime():
    client = fakeredis.FakeRedis(decode_responses=True)
    realtime.set_client(client)
    yield client
    realtime.set_client(None)


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")


def _watermark_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _seed_outbound_messages(session_factory, contact_id, channel_id, specs):
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    ids = []
    for spec in specs:
        row = ConversationMessage(
            tenant_id=DEFAULT_TENANT_ID,
            contact_id=contact_id,
            channel_id=channel_id,
            sender_type=spec.get("sender_type", "AGENT"),
            message_type="TEXT",
            body=spec.get("body", "hi"),
            external_message_id=spec.get("external_message_id"),
            delivery_status=spec.get("delivery_status", "SENT"),
            created_at=spec["created_at"],
        )
        db.add(row)
        db.flush()
        ids.append(row.id)
    db.commit()
    db.close()
    return ids


def _message_statuses(session_factory, contact_id):
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    rows = {
        r.external_message_id: r.delivery_status
        for r in db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact_id).all()
    }
    db.close()
    return rows


# ── AC-CHN-46/47: inbound CDN fetch - allowlist / SSRF / redirects / cap / sniff
def test_fetch_media_url_accepts_meta_cdn_host(monkeypatch):
    _configure(monkeypatch)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "scontent.xx.fbcdn.net"
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "https://scontent.xx.fbcdn.net/v/img.png"
    )
    assert result == {"content": png, "mime_type": "image/png"}


def test_fetch_media_url_rejects_non_cdn_host_never_fetches(monkeypatch):
    _configure(monkeypatch)
    called = {}

    def handler(request: httpx.Request) -> httpx.Response:
        called["hit"] = True
        return httpx.Response(200, content=b"x")

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url({"access_token": "tok"}, "https://evil.example.com/img.png")
    assert result is None
    assert "hit" not in called  # the disallowed host is never even hit


def test_fetch_media_url_rejects_http_scheme(monkeypatch):
    _configure(monkeypatch)
    fake = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "http://scontent.xx.fbcdn.net/img.png"
    )
    assert result is None


def test_fetch_media_url_ssrf_guard_rejects_even_an_allowlisted_host(monkeypatch):
    """A host that passes the CDN suffix allowlist but the SHARED SSRF guard
    (DNS rebinding / private-target resolution) refuses is still rejected -
    the allowlist is the first gate, not the only one (AC-CHN-47)."""
    _configure(monkeypatch)
    from modules.omnichannel.adapters import messenger as messenger_module

    def _reject(*_a, **_k):
        from app.services.url_guard import UrlGuardError

        raise UrlGuardError("blocked")

    monkeypatch.setattr(messenger_module, "assert_deliverable", _reject)
    fake = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "https://scontent.xx.fbcdn.net/img.png"
    )
    assert result is None


def test_fetch_media_url_redirect_to_private_host_rejected(monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "scontent.xx.fbcdn.net":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data"}
            )
        raise AssertionError("must never follow a redirect off the CDN allowlist")

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "https://scontent.xx.fbcdn.net/img.png"
    )
    assert result is None


def test_fetch_media_url_bounded_redirects_then_success(monkeypatch):
    _configure(monkeypatch)
    png = b"\x89PNG\r\n\x1a\n" + b"1" * 16
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            assert request.url.host == "scontent.xx.fbcdn.net"
            return httpx.Response(302, headers={"location": "https://scontent2.xx.fbcdn.net/hop"})
        if calls["n"] == 2:
            assert request.url.host == "scontent2.xx.fbcdn.net"
            return httpx.Response(302, headers={"location": "https://lookaside.fbsbx.com/final"})
        assert request.url.host == "lookaside.fbsbx.com"
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "https://scontent.xx.fbcdn.net/img.png"
    )
    assert result == {"content": png, "mime_type": "image/png"}
    assert calls["n"] == 3  # within the bound (max 3 redirects)


def test_fetch_media_url_too_many_redirects_rejected(monkeypatch):
    _configure(monkeypatch)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(302, headers={"location": "https://scontent.xx.fbcdn.net/next"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "https://scontent.xx.fbcdn.net/img.png"
    )
    assert result is None
    assert calls["n"] == 4  # initial fetch + 3 bounded redirects, never more


def test_fetch_media_url_oversize_truncated_unavailable(monkeypatch):
    _configure(monkeypatch)
    from modules.omnichannel.adapters import messenger as messenger_module

    monkeypatch.setattr(messenger_module, "_MAX_FETCH_BYTES", 8)
    big = b"\x89PNG\r\n\x1a\n" + b"0" * 100

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big, headers={"content-type": "image/png"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "https://scontent.xx.fbcdn.net/img.png"
    )
    assert result is None


def test_fetch_media_url_sniff_mismatch_rejected(monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        # An executable disguised with an image content-type - the DECLARED
        # type is ignored; the magic-byte sniff is the gate.
        return httpx.Response(200, content=b"MZ\x90\x00fakeexe", headers={"content-type": "image/png"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "https://scontent.xx.fbcdn.net/img.png"
    )
    assert result is None


def test_fetch_media_url_transient_5xx_retried_then_succeeds(monkeypatch):
    _configure(monkeypatch)
    png = b"\x89PNG\r\n\x1a\n" + b"2" * 16
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "https://scontent.xx.fbcdn.net/img.png"
    )
    assert result == {"content": png, "mime_type": "image/png"}
    assert calls["n"] == 2  # ONE bounded inline retry


def test_fetch_media_url_transient_5xx_exhausts_retry_then_unavailable(monkeypatch):
    _configure(monkeypatch)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "https://scontent.xx.fbcdn.net/img.png"
    )
    assert result is None
    assert calls["n"] == 2  # bounded - never an unbounded retry loop


def test_fetch_media_url_dev_credentials_never_attempts_network():
    called = {}

    def handler(request: httpx.Request) -> httpx.Response:
        called["hit"] = True
        return httpx.Response(200, content=b"x")

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.fetch_media_url({"dev": True}, "https://scontent.xx.fbcdn.net/img.png")
    assert result is None
    assert "hit" not in called


# ── AC-CHN-46: the storage key convention + the full inbound pipeline ───────
def test_store_media_from_url_uses_existing_storage_key_convention(session_factory, monkeypatch, tmp_path):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.services import storage as storage_module
    from modules.omnichannel.services.inbound_service import InboundService
    from modules.omnichannel.services.storage import LocalDiskStorage

    storage_module.set_storage(LocalDiskStorage(str(tmp_path)))
    monkeypatch.setattr(
        MessengerAdapter,
        "fetch_media_url",
        lambda self, creds, url: {"content": b"\x89PNGdata", "mime_type": "image/png"},
    )
    channel_id = _fb_channel(session_factory, external_account_id="pg-store-1")
    db = session_factory()
    try:
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        stored = InboundService(db)._store_media_from_url(
            channel, "https://scontent.xx.fbcdn.net/img.png"
        )
    finally:
        db.close()
        storage_module.set_storage(None)
    assert stored is not None
    assert stored["key"].startswith(f"omnichannel/{DEFAULT_TENANT_ID}/")
    assert stored["mime"] == "image/png"


def test_inbound_messenger_image_attachment_stores_blob_and_clears_pending_url(
    session_factory, monkeypatch, tmp_path
):
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services import storage as storage_module
    from modules.omnichannel.services.storage import LocalDiskStorage

    storage_module.set_storage(LocalDiskStorage(str(tmp_path)))
    monkeypatch.setattr(
        MessengerAdapter,
        "fetch_media_url",
        lambda self, creds, url: {"content": b"\x89PNGimgdata", "mime_type": "image/png"},
    )
    channel_id = _fb_channel(session_factory, external_account_id="pg-img-1")
    payload = {
        "object": "page",
        "entry": [{"id": "pg-img-1", "messaging": [{
            "sender": {"id": "psid-img-1"}, "timestamp": 1,
            "message": {"mid": "m.img.1", "attachments": [
                {"type": "image", "payload": {"url": "https://scontent.xx.fbcdn.net/v/img.png"}}
            ]},
        }]}],
    }
    res = _process(session_factory, channel_id, payload)
    storage_module.set_storage(None)
    assert res["messages"] == 1

    db = session_factory()
    row = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "m.img.1").first()
    db.close()
    assert row.message_type == "IMAGE"
    assert row.media_key is not None
    assert row.payload_json is None  # `pendingMediaUrl` consumed, never left stale


def test_inbound_messenger_image_fetch_failure_marks_unavailable_never_drops_message(
    session_factory, monkeypatch
):
    from modules.omnichannel.models import ConversationMessage

    monkeypatch.setattr(MessengerAdapter, "fetch_media_url", lambda self, creds, url: None)
    channel_id = _fb_channel(session_factory, external_account_id="pg-img-2")
    payload = {
        "object": "page",
        "entry": [{"id": "pg-img-2", "messaging": [{
            "sender": {"id": "psid-img-2"}, "timestamp": 1,
            "message": {"mid": "m.img.2", "attachments": [
                {"type": "image", "payload": {"url": "https://scontent.xx.fbcdn.net/v/img.png"}}
            ]},
        }]}],
    }
    res = _process(session_factory, channel_id, payload)
    assert res["messages"] == 1  # a media hiccup never drops the message

    db = session_factory()
    row = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "m.img.2").first()
    db.close()
    assert row.media_key is None
    assert row.payload_json == {"mediaUnavailable": True}


# ── AC-CHN-48: outbound upload-by-id, never a public URL ────────────────────
def test_upload_media_real_posts_multipart_and_returns_attachment_id(monkeypatch):
    _configure(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("content-type", "")
        text = request.content.decode("utf-8", errors="ignore")
        captured["text"] = text
        return httpx.Response(200, json={"attachment_id": "att-123"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.upload_media({"access_token": "tok"}, "pg-1", b"\x89PNGdata", "image/png")
    assert result == "att-123"
    assert captured["url"].endswith("/me/message_attachments")
    assert "multipart/form-data" in captured["content_type"]
    assert '"is_reusable": true' in captured["text"]
    assert '"type": "image"' in captured["text"]
    assert 'name="filedata"' in captured["text"]
    assert '"url"' not in captured["text"]  # never a public URL, only bytes


def test_send_media_uses_attachment_id_never_a_public_url(monkeypatch):
    _configure(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message_id": "mid.999"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.send(
        {"access_token": "tok"}, "pg-1", "psid-1",
        media={"kind": "image", "id": "att-123", "caption": "hi"},
        messaging_type="RESPONSE",
    )
    assert result["external_message_id"] == "mid.999"
    attachment = captured["body"]["message"]["attachment"]
    assert attachment["payload"]["attachment_id"] == "att-123"
    assert "url" not in attachment["payload"]


# ── AC-CHN-49: watermark / mids receipts ─────────────────────────────────────
def test_watermark_receipt_advances_outbound_before_watermark_forward_only(session_factory):
    channel_id = _fb_channel(session_factory, external_account_id="pg-wm-1")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="psid-wm-1")
    base = _now() - timedelta(minutes=10)
    _seed_outbound_messages(session_factory, contact_id, channel_id, [
        {"created_at": base, "external_message_id": "m.wm.1"},
        {"created_at": base + timedelta(minutes=1), "external_message_id": "m.wm.2"},
        {"created_at": base + timedelta(minutes=5), "external_message_id": "m.wm.3"},
    ])
    payload = {
        "object": "page",
        "entry": [{"id": "pg-wm-1", "messaging": [
            {"sender": {"id": "psid-wm-1"}, "delivery": {"watermark": _watermark_ms(base + timedelta(minutes=2))}}
        ]}],
    }
    res = _process(session_factory, channel_id, payload)
    assert res["statuses"] == 1

    statuses = _message_statuses(session_factory, contact_id)
    assert statuses["m.wm.1"] == "DELIVERED"
    assert statuses["m.wm.2"] == "DELIVERED"
    assert statuses["m.wm.3"] == "SENT"  # sent AFTER the watermark - untouched


def test_watermark_receipt_never_regresses_a_later_status(session_factory):
    channel_id = _fb_channel(session_factory, external_account_id="pg-wm-2")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="psid-wm-2")
    base = _now() - timedelta(minutes=10)
    _seed_outbound_messages(session_factory, contact_id, channel_id, [
        {"created_at": base, "external_message_id": "m.wm.4", "delivery_status": "READ"},
    ])
    payload = {
        "object": "page",
        "entry": [{"id": "pg-wm-2", "messaging": [
            {"sender": {"id": "psid-wm-2"}, "delivery": {"watermark": _watermark_ms(base + timedelta(minutes=1))}}
        ]}],
    }
    res = _process(session_factory, channel_id, payload)
    assert res["skipped"] == 1  # a late DELIVERED watermark after READ is a no-op
    assert _message_statuses(session_factory, contact_id)["m.wm.4"] == "READ"


def test_mids_receipt_targets_exact_messages_ignores_watermark_breadth(session_factory):
    channel_id = _fb_channel(session_factory, external_account_id="pg-wm-3")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="psid-wm-3")
    base = _now() - timedelta(minutes=10)
    _seed_outbound_messages(session_factory, contact_id, channel_id, [
        {"created_at": base, "external_message_id": "m.wm.5"},
        {"created_at": base + timedelta(minutes=1), "external_message_id": "m.wm.6"},
    ])
    payload = {
        "object": "page",
        "entry": [{"id": "pg-wm-3", "messaging": [{
            "sender": {"id": "psid-wm-3"},
            "delivery": {"mids": ["m.wm.6"], "watermark": _watermark_ms(base + timedelta(minutes=5))},
        }]}],
    }
    _process(session_factory, channel_id, payload)
    statuses = _message_statuses(session_factory, contact_id)
    assert statuses["m.wm.6"] == "DELIVERED"
    assert statuses["m.wm.5"] == "SENT"  # mids present -> exact targeting only


def test_read_watermark_advances_status_to_read(session_factory):
    channel_id = _fb_channel(session_factory, external_account_id="pg-wm-5")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="psid-wm-5")
    base = _now() - timedelta(minutes=10)
    _seed_outbound_messages(session_factory, contact_id, channel_id, [
        {"created_at": base, "external_message_id": "m.wm.9", "delivery_status": "DELIVERED"},
    ])
    payload = {
        "object": "page",
        "entry": [{"id": "pg-wm-5", "messaging": [
            {"sender": {"id": "psid-wm-5"}, "read": {"watermark": _watermark_ms(base + timedelta(minutes=1))}}
        ]}],
    }
    _process(session_factory, channel_id, payload)
    assert _message_statuses(session_factory, contact_id)["m.wm.9"] == "READ"


def test_watermark_receipt_publishes_and_enqueues_for_each_targeted_message(session_factory, monkeypatch):
    from modules.omnichannel.services import realtime as realtime_module
    from modules.omnichannel.services import webhook_delivery as webhook_delivery_module

    published = []
    enqueued = []
    monkeypatch.setattr(realtime_module, "publish", lambda *a, **k: published.append(a))
    monkeypatch.setattr(
        webhook_delivery_module, "enqueue_event", lambda *a, **k: enqueued.append(a)
    )

    channel_id = _fb_channel(session_factory, external_account_id="pg-wm-6")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="psid-wm-6")
    base = _now() - timedelta(minutes=10)
    _seed_outbound_messages(session_factory, contact_id, channel_id, [
        {"created_at": base, "external_message_id": "m.wm.7"},
        {"created_at": base + timedelta(minutes=1), "external_message_id": "m.wm.8"},
    ])
    payload = {
        "object": "page",
        "entry": [{"id": "pg-wm-6", "messaging": [
            {"sender": {"id": "psid-wm-6"}, "delivery": {"watermark": _watermark_ms(base + timedelta(minutes=5))}}
        ]}],
    }
    _process(session_factory, channel_id, payload)
    assert len(published) == 2
    assert len(enqueued) == 2


def test_watermark_receipt_unknown_identity_dropped(session_factory):
    channel_id = _fb_channel(session_factory, external_account_id="pg-wm-7")
    payload = {
        "object": "page",
        "entry": [{"id": "pg-wm-7", "messaging": [
            {"sender": {"id": "psid-no-such-identity"}, "delivery": {"watermark": _watermark_ms(_now())}}
        ]}],
    }
    res = _process(session_factory, channel_id, payload)
    assert res["skipped"] == 1


# ── AC-CHN-50: reactions - the existing inbound reaction path, generalized ──
def test_messenger_reaction_react_upserts_never_creates_a_bubble(session_factory):
    from modules.omnichannel.models import ConversationMessage, MessageReaction

    channel_id = _fb_channel(session_factory, external_account_id="pg-rx-1")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="psid-rx-1")
    _seed_outbound_messages(session_factory, contact_id, channel_id, [
        {"created_at": _now(), "external_message_id": "m.rx.1"},
    ])
    payload = {
        "object": "page",
        "entry": [{"id": "pg-rx-1", "messaging": [
            {"sender": {"id": "psid-rx-1"}, "reaction": {"mid": "m.rx.1", "emoji": "\U0001F60D", "action": "react"}}
        ]}],
    }
    res = _process(session_factory, channel_id, payload)
    assert res.get("reactions") == 1

    db = session_factory()
    message_count = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact_id).count()
    reaction = db.query(MessageReaction).filter(MessageReaction.reactor == "psid-rx-1").first()
    db.close()
    assert message_count == 1  # never created a bubble
    assert reaction.emoji == "\U0001F60D"


def test_messenger_reaction_unreact_removes(session_factory):
    from modules.omnichannel.models import MessageReaction

    channel_id = _fb_channel(session_factory, external_account_id="pg-rx-2")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="psid-rx-2")
    _seed_outbound_messages(session_factory, contact_id, channel_id, [
        {"created_at": _now(), "external_message_id": "m.rx.2"},
    ])
    react = {
        "object": "page",
        "entry": [{"id": "pg-rx-2", "messaging": [
            {"sender": {"id": "psid-rx-2"}, "reaction": {"mid": "m.rx.2", "emoji": "\U0001F44D", "action": "react"}}
        ]}],
    }
    _process(session_factory, channel_id, react)
    unreact = {
        "object": "page",
        "entry": [{"id": "pg-rx-2", "messaging": [
            {"sender": {"id": "psid-rx-2"}, "reaction": {"mid": "m.rx.2", "action": "unreact"}}
        ]}],
    }
    _process(session_factory, channel_id, unreact)

    db = session_factory()
    remaining = db.query(MessageReaction).filter(MessageReaction.reactor == "psid-rx-2").count()
    db.close()
    assert remaining == 0


def test_messenger_reaction_unknown_target_dropped(session_factory):
    channel_id = _fb_channel(session_factory, external_account_id="pg-rx-3")
    payload = {
        "object": "page",
        "entry": [{"id": "pg-rx-3", "messaging": [
            {"sender": {"id": "psid-rx-3"}, "reaction": {"mid": "m.nope", "emoji": "\U0001F44D", "action": "react"}}
        ]}],
    }
    res = _process(session_factory, channel_id, payload)
    assert res["skipped"] == 1


# ── AC-CHN-51: rate-limit / throttling -> transient, permission/param -> permanent
@pytest.mark.parametrize("code", [4, 17, 32, 613])
def test_send_rate_limit_error_codes_are_transient(monkeypatch, code):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "throttled", "code": code}},
            headers={"X-Business-Use-Case-Usage": '{"pg-1":[{"type":"messages"}]}'},
        )

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    with pytest.raises(SendError) as exc:
        adapter.send({"access_token": "tok"}, "pg-1", "psid-1", text="hi")
    assert exc.value.transient is True
    assert "usage" in str(exc.value).lower()


def test_send_bare_429_is_transient(monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "too many"}})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    with pytest.raises(SendError) as exc:
        adapter.send({"access_token": "tok"}, "pg-1", "psid-1", text="hi")
    assert exc.value.transient is True


@pytest.mark.parametrize("code", [10, 100, 200])
def test_send_permission_and_param_errors_are_permanent(monkeypatch, code):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad request", "code": code}})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    with pytest.raises(SendError) as exc:
        adapter.send({"access_token": "tok"}, "pg-1", "psid-1", text="hi")
    assert exc.value.transient is False


def test_upload_media_rate_limit_is_transient(monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "throttled", "code": 613}})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    with pytest.raises(SendError) as exc:
        adapter.upload_media({"access_token": "tok"}, "pg-1", b"data", "image/png")
    assert exc.value.transient is True


def test_dev_safe_rate_limit_magic_recipient_raises_transient():
    adapter = MessengerAdapter()
    with pytest.raises(SendError) as exc:
        adapter.send({"dev": True}, "pg-1", DEV_RATE_LIMIT_PSID, text="hi")
    assert exc.value.transient is True


def test_send_runner_requeues_transient_rate_limit(session_factory):
    """AC-CHN-51 end to end: `send_runner`'s EXISTING bounded-backoff path
    (`TransientSendError` -> row reset to QUEUED, never FAILED) applies to
    the Messenger rate-limit magic recipient exactly as it would a real
    Meta 613/429."""
    from modules.omnichannel.models import Contact, ConversationMessage, Workspace
    from modules.omnichannel.services import statuses
    from modules.omnichannel.services.send_runner import TransientSendError, run_send

    channel_id = _fb_channel(session_factory, external_account_id="pg-run-rl")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id, psid=DEV_RATE_LIMIT_PSID
    )
    db = session_factory()
    row = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID, contact_id=contact_id, channel_id=channel_id,
        sender_type="AGENT", message_type="TEXT", body="hi", delivery_status="QUEUED",
    )
    db.add(row)
    db.commit()
    with pytest.raises(TransientSendError):
        run_send(db, row.id)
    db.refresh(row)
    assert row.delivery_status == "QUEUED"  # requeued for backoff, never FAILED
    assert "rate limit" in (row.error_message or "").lower()
    db.close()


# ── AC-CHN-52: the EXISTING outbound_meta telemetry seam, no second path ────
def test_messenger_send_records_outbound_meta_activity_row(session_factory):
    from app.models.integration_activity import SOURCE_OUTBOUND_META, IntegrationActivity
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services.send_runner import run_send

    channel_id = _fb_channel(session_factory, external_account_id="pg-tel-1")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="psid-tel-1")
    db = session_factory()
    row = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID, contact_id=contact_id, channel_id=channel_id,
        sender_type="AGENT", message_type="TEXT", body="hi", delivery_status="QUEUED",
    )
    db.add(row)
    db.commit()
    status = run_send(db, row.id)
    db.close()
    assert status == "SENT"

    check = session_factory()
    rows = (
        check.query(IntegrationActivity)
        .filter(
            IntegrationActivity.tenant_id == DEFAULT_TENANT_ID,
            IntegrationActivity.source == SOURCE_OUTBOUND_META,
        )
        .all()
    )
    check.close()
    assert any(r.operation == "graph:send" for r in rows)


# ── Instagram inherits every S5 path (D-A7-14, one test per path) ───────────
def test_instagram_fetch_media_url_accepts_cdninstagram_host(monkeypatch):
    _configure(monkeypatch)
    png = b"\x89PNG\r\n\x1a\n" + b"3" * 16

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.endswith("cdninstagram.com")
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = InstagramAdapter(client=fake)
    result = adapter.fetch_media_url(
        {"access_token": "tok"}, "https://scontent.cdninstagram.com/img.png"
    )
    assert result == {"content": png, "mime_type": "image/png"}


def test_instagram_upload_media_real_uses_the_same_endpoint(monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/me/message_attachments")
        return httpx.Response(200, json={"attachment_id": "att-ig-1"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = InstagramAdapter(client=fake)
    result = adapter.upload_media({"access_token": "tok"}, "ig-1", b"\x89PNGdata", "image/png")
    assert result == "att-ig-1"


def test_instagram_send_rate_limit_is_transient(monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "throttled", "code": 613}})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = InstagramAdapter(client=fake)
    with pytest.raises(SendError) as exc:
        adapter.send({"access_token": "tok"}, "ig-1", "igsid-1", text="hi")
    assert exc.value.transient is True


def test_instagram_watermark_receipt_applies_via_object_dispatch(session_factory):
    from modules.omnichannel.models import ConversationMessage

    channel_id = _ig_channel(session_factory, external_account_id="ig-wm-1")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="igsid-wm-1")
    base = _now() - timedelta(minutes=5)
    _seed_outbound_messages(session_factory, contact_id, channel_id, [
        {"created_at": base, "external_message_id": "m.igwm.1", "delivery_status": "SENT"},
    ])
    payload = {
        "object": "instagram",
        "entry": [{"id": "ig-wm-1", "messaging": [
            {"sender": {"id": "igsid-wm-1"}, "read": {"watermark": _watermark_ms(_now())}}
        ]}],
    }
    res = _process(session_factory, channel_id, payload)
    assert res["statuses"] == 1

    db = session_factory()
    row = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "m.igwm.1").first()
    db.close()
    assert row.delivery_status == "READ"


def test_instagram_reaction_react_upserts(session_factory):
    from modules.omnichannel.models import MessageReaction

    channel_id = _ig_channel(session_factory, external_account_id="ig-rx-1")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="igsid-rx-1")
    _seed_outbound_messages(session_factory, contact_id, channel_id, [
        {"created_at": _now(), "external_message_id": "m.igrx.1"},
    ])
    payload = {
        "object": "instagram",
        "entry": [{"id": "ig-rx-1", "messaging": [
            {"sender": {"id": "igsid-rx-1"}, "reaction": {"mid": "m.igrx.1", "emoji": "\U0001F525", "action": "react"}}
        ]}],
    }
    res = _process(session_factory, channel_id, payload)
    assert res.get("reactions") == 1
    db = session_factory()
    reaction = db.query(MessageReaction).filter(MessageReaction.reactor == "igsid-rx-1").first()
    db.close()
    assert reaction.emoji == "\U0001F525"
