"""Plan 32 (A7a) Slice S1 - shared Meta Graph plumbing, adapter registry, ONE
webhook ingress, Messenger inbound + PSID stitch, window columns.

AC-CHN-13..21 (see documentation/plans/sprint-4/
32-omnichannel-channels-messenger-instagram-acceptance-criteria.md).
"""
import importlib
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services import realtime
from tests.test_omnichannel_conversations import _auth
from tests.test_omnichannel_contact_data_model import _other_tenant_auth

ALEMBIC_REV = "0017_omni_meta_channels"


@pytest.fixture(autouse=True)
def _fake_realtime():
    client = fakeredis.FakeRedis(decode_responses=True)
    realtime.set_client(client)
    yield client
    realtime.set_client(None)


def _process(session_factory, channel_id, payload):
    from modules.omnichannel.services.inbound_service import InboundService

    db = session_factory()
    try:
        return InboundService(db).process_payload(channel_id, payload)
    finally:
        db.close()


def _fb_channel(session_factory, *, tenant_id=DEFAULT_TENANT_ID, external_account_id="pg-701", channel_id=None):
    from modules.omnichannel.models import Channel, Workspace
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.tenant_id == tenant_id, Workspace.is_default.is_(True)).first()
    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        workspace_id=ws.id,
        channel_type="FACEBOOK",
        name="Test Messenger",
        credentials_json=encrypt_credentials({"dev": True}),
        external_account_id=external_account_id,
        external_account_name="Test Page",
        is_active=True,
        status_id=statuses.status_id_for(db, tenant_id, "CHANNEL", "ACTIVE"),
    )
    db.add(channel)
    db.flush()
    db.commit()
    cid = channel.id
    db.close()
    return cid


def _messenger_payload(*, page_id="pg-701", psid="psid-1", mid="m.1", text="Hello there", timestamp=1717550000000):
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "time": timestamp,
                "messaging": [
                    {
                        "sender": {"id": psid},
                        "recipient": {"id": page_id},
                        "timestamp": timestamp,
                        "message": {"mid": mid, "text": text},
                    }
                ],
            }
        ],
    }


# ── AC-CHN-13/14: migration + backfill ───────────────────────────────────────
def test_migration_0017_revision_sanity():
    mod = importlib.import_module(f"modules.omnichannel.alembic.versions.{ALEMBIC_REV}")
    assert mod.revision == ALEMBIC_REV
    assert len(mod.revision) <= 32
    assert mod.down_revision == "0016_omni_business_hours"
    assert callable(mod.upgrade) and callable(mod.downgrade)


def test_channel_and_identity_columns_exist():
    from modules.omnichannel.models import Channel, ContactChannelIdentity

    assert hasattr(Channel, "external_account_id")
    assert hasattr(Channel, "external_account_name")
    assert hasattr(ContactChannelIdentity, "window_expires_at")
    assert hasattr(ContactChannelIdentity, "human_agent_expires_at")
    assert hasattr(ContactChannelIdentity, "last_inbound_at")


def test_backfill_identity_windows_stamps_existing_whatsapp_identities(session_factory):
    from modules.omnichannel.models import Channel, Contact, ContactChannelIdentity, Workspace
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import messaging_policy, statuses

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)).first()
    channel = Channel(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, channel_type="WHATSAPP",
        name="BF WhatsApp", credentials_json=encrypt_credentials({"dev": True}),
        phone_number_id="pn-bf-1", is_active=True,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
    )
    db.add(channel)
    db.flush()
    now = datetime.now(timezone.utc)
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, first_name="Backfill", phone="+60111000111",
        phone_digits="60111000111", priority="MEDIUM",
        csw_expires_at=now + timedelta(hours=10),
        last_incoming_message_at=now - timedelta(hours=1),
    )
    db.add(contact)
    db.flush()
    identity = ContactChannelIdentity(
        tenant_id=DEFAULT_TENANT_ID, contact_id=contact.id, channel_id=channel.id,
        external_user_id="60111000111",
    )
    db.add(identity)
    db.commit()

    assert identity.window_expires_at is None  # pre-backfill

    count = messaging_policy.backfill_identity_windows(db, DEFAULT_TENANT_ID)
    db.commit()
    assert count >= 1
    db.refresh(identity)
    assert identity.window_expires_at == contact.csw_expires_at
    assert identity.last_inbound_at == contact.last_incoming_message_at

    # Idempotent - a second call stamps nothing more for this identity.
    second = messaging_policy.backfill_identity_windows(db, DEFAULT_TENANT_ID)
    db.close()
    assert second == 0


# ── AC-CHN-15: adapter registry ──────────────────────────────────────────────
def test_adapter_registry_resolves_all_three_and_rejects_unknown():
    from modules.omnichannel.adapters import get_adapter

    wa = get_adapter("WHATSAPP")
    fb = get_adapter("FACEBOOK")
    ig = get_adapter("INSTAGRAM")
    assert wa.channel_type == "WHATSAPP"
    assert fb.channel_type == "FACEBOOK"
    assert ig.channel_type == "INSTAGRAM"
    with pytest.raises(ValueError):
        get_adapter("DOUYIN")


def test_whatsapp_cloud_get_adapter_reexport_is_the_same_registry():
    from modules.omnichannel.adapters import get_adapter as registry_get_adapter
    from modules.omnichannel.adapters.whatsapp_cloud import get_adapter as reexported

    assert type(reexported("WHATSAPP")) is type(registry_get_adapter("WHATSAPP"))
    with pytest.raises(ValueError):
        reexported("DOUYIN")


def test_shared_meta_graph_plumbing_extracted_and_reimported():
    from modules.omnichannel.adapters import meta_graph, whatsapp_cloud

    # AC-CHN-15: the WhatsApp adapter is a MetaGraphMixin subclass and every
    # existing import site of these names off `whatsapp_cloud` still resolves
    # (services/activity.py imports GraphCall/GraphRecorder from here).
    assert issubclass(whatsapp_cloud.WhatsAppCloudAdapter, meta_graph.MetaGraphMixin)
    assert whatsapp_cloud.GraphCall is meta_graph.GraphCall
    assert whatsapp_cloud.GraphRecorder is meta_graph.GraphRecorder


# ── AC-CHN-16/17: ONE webhook ingress, object dispatch ───────────────────────
def test_webhook_object_dispatch_resolves_facebook_channel_by_external_account_id(client, session_factory):
    cid = _fb_channel(session_factory, external_account_id="pg-dispatch-1")

    counters = _process(session_factory, "meta", _messenger_payload(page_id="pg-dispatch-1"))
    assert counters["messages"] == 1

    h = _auth(client)
    threads = client.get("/omnichannel/contacts", headers=h).json()["data"]
    assert any(t["id"] for t in threads)  # a thread now exists via the FB channel
    # The message landed on the FB channel found by page id, not the URL id.
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    msg = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "m.1").first()
    assert msg.channel_id == cid
    db.close()


def test_webhook_object_dispatch_unknown_object_dropped_never_5xx(session_factory):
    counters = _process(session_factory, "meta", {"object": "unknown_product", "entry": []})
    assert counters == {"messages": 0, "statuses": 0, "skipped": 0}


def test_webhook_object_dispatch_malformed_payload_never_raises(session_factory):
    # Not even a dict-shaped entry/messaging - must be dropped, never 500.
    counters = _process(session_factory, "meta", {"object": "page", "entry": "garbage"})
    assert counters == {"messages": 0, "statuses": 0, "skipped": 0}


def test_webhook_url_channel_id_is_last_resort_fallback(session_factory):
    # A page id absent from the payload/DB falls back to the URL's channel id.
    cid = _fb_channel(session_factory, external_account_id="pg-fallback-1")
    counters = _process(
        session_factory, cid, _messenger_payload(page_id="pg-does-not-exist-anywhere")
    )
    assert counters["messages"] == 1


def test_webhook_url_channel_id_fallback_drops_a_type_mismatched_channel(session_factory):
    """Nit, security review round 1 - the URL-id fallback (last resort, after
    `external_account_id` lookup misses) must still be TYPE-matched: a
    `page`-object payload naming a WhatsApp channel by URL id must be
    dropped, never handed to the wrong adapter."""
    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    from modules.omnichannel.models import Workspace

    ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)).first()
    wa = Channel(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws.id,
        channel_type="WHATSAPP",
        name="URL fallback WA",
        credentials_json=encrypt_credentials({"dev": True}),
        phone_number_id="pn-url-fallback",
        is_active=True,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
    )
    db.add(wa)
    db.commit()
    wa_id = wa.id
    db.close()

    counters = _process(
        session_factory, wa_id, _messenger_payload(page_id="pg-does-not-exist-anywhere-2")
    )
    assert counters == {"messages": 0, "statuses": 0, "skipped": 0}


def test_webhook_url_channel_id_fallback_drops_a_trashed_channel(session_factory):
    """Nit, security review round 1 - the URL-id fallback must also exclude
    a trashed channel (not a live routing target)."""
    from modules.omnichannel.models import Channel

    cid = _fb_channel(session_factory, external_account_id="pg-trashed-fallback")
    db = session_factory()
    ch = db.query(Channel).filter(Channel.id == cid).first()
    ch.is_trashed = True
    db.commit()
    db.close()

    counters = _process(
        session_factory, cid, _messenger_payload(page_id="pg-does-not-exist-anywhere-3")
    )
    assert counters == {"messages": 0, "statuses": 0, "skipped": 0}


def test_webhook_signature_and_handshake_apply_to_messenger_object(client, monkeypatch):
    import hashlib
    import hmac
    import json

    from app.config import settings
    from modules.omnichannel import worker

    # Same pattern as the existing WhatsApp signature test
    # (test_omnichannel_webhooks.test_post_signature_gate) - the fast-ACK
    # contract only cares that the HTTP layer accepts/rejects by signature;
    # the eager Celery task would otherwise run against the real app DB
    # engine (not this test's sqlite fixture), which is a separate concern.
    monkeypatch.setattr(worker.process_inbound_webhook, "delay", lambda *a, **k: None)

    monkeypatch_secret = "topsecret-messenger"
    settings.meta_app_secret = monkeypatch_secret
    try:
        body = json.dumps(_messenger_payload()).encode()
        good = hmac.new(monkeypatch_secret.encode(), body, hashlib.sha256).hexdigest()
        ok = client.post(
            "/omnichannel/webhooks/meta",
            content=body,
            headers={"X-Hub-Signature-256": f"sha256={good}", "Content-Type": "application/json"},
        )
        assert ok.status_code == 200

        forged = client.post(
            "/omnichannel/webhooks/meta",
            content=body,
            headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"},
        )
        assert forged.status_code == 403
    finally:
        settings.meta_app_secret = None


def test_webhook_handshake_works_on_the_meta_url_id(client):
    from app.config import settings

    res = client.get(
        "/omnichannel/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.meta_webhook_verify_token,
            "hub.challenge": "abc123",
        },
    )
    assert res.status_code == 200
    assert res.text == "abc123"


# ── AC-CHN-18: parse_inbound mapping ──────────────────────────────────────────
def test_messenger_parse_inbound_text():
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    events = MessengerAdapter().parse_inbound(_messenger_payload(text="Hi!"))
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "message"
    assert ev["message_type"] == "TEXT"
    assert ev["body"] == "Hi!"
    assert ev["from"] == "psid-1"


def test_messenger_parse_inbound_attachment_carries_url():
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    payload = {
        "object": "page",
        "entry": [{"id": "pg-701", "messaging": [{
            "sender": {"id": "psid-2"}, "timestamp": 2,
            "message": {"mid": "m.2", "attachments": [
                {"type": "image", "payload": {"url": "https://scontent.xx.fbcdn.net/x.jpg"}}
            ]},
        }]}],
    }
    events = MessengerAdapter().parse_inbound(payload)
    assert len(events) == 1
    assert events[0]["message_type"] == "IMAGE"
    assert events[0]["media_url"] == "https://scontent.xx.fbcdn.net/x.jpg"


def test_messenger_parse_inbound_document_attachment_is_messenger_only():
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    payload = {
        "object": "page",
        "entry": [{"id": "pg-701", "messaging": [{
            "sender": {"id": "psid-3"}, "timestamp": 3,
            "message": {"mid": "m.3", "attachments": [{"type": "file", "payload": {"url": "https://x/y.pdf"}}]},
        }]}],
    }
    events = MessengerAdapter().parse_inbound(payload)
    assert events[0]["message_type"] == "DOCUMENT"


def test_messenger_parse_inbound_unmapped_attachment_kind_preserves_its_own_payload():
    """Security review round 1, nit - an attachment `type` outside
    `_ATTACHMENT_TYPES` (e.g. `location`, which carries `coordinates`, not a
    `url`) falls through to `UNSUPPORTED` but must keep ITS OWN payload
    (matching `InstagramAdapter._ig_placeholder`, AC-CHN-18) rather than
    dropping it because there is no `url` to stash as `pendingMediaUrl`."""
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    payload = {
        "object": "page",
        "entry": [{"id": "pg-701", "messaging": [{
            "sender": {"id": "psid-loc"}, "timestamp": 6,
            "message": {"mid": "m.loc", "attachments": [
                {"type": "location", "payload": {"coordinates": {"lat": 1.2, "long": 103.8}}}
            ]},
        }]}],
    }
    events = MessengerAdapter().parse_inbound(payload)
    assert len(events) == 1
    assert events[0]["message_type"] == "UNSUPPORTED"
    assert events[0]["media_url"] is None
    assert events[0]["payload"] == {"coordinates": {"lat": 1.2, "long": 103.8}}


def test_messenger_parse_inbound_quick_reply_and_postback():
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    qr_payload = {
        "object": "page",
        "entry": [{"id": "pg-701", "messaging": [{
            "sender": {"id": "psid-4"}, "timestamp": 4,
            "message": {"mid": "m.4", "text": "Yes", "quick_reply": {"payload": "YES_PAYLOAD"}},
        }]}],
    }
    events = MessengerAdapter().parse_inbound(qr_payload)
    assert events[0]["message_type"] == "INTERACTIVE_REPLY"
    assert events[0]["payload"] == {"kind": "quick_reply", "id": "YES_PAYLOAD", "title": "Yes"}

    pb_payload = {
        "object": "page",
        "entry": [{"id": "pg-701", "messaging": [{
            "sender": {"id": "psid-5"}, "timestamp": 5,
            "postback": {"title": "Get Started", "payload": "GET_STARTED"},
        }]}],
    }
    events = MessengerAdapter().parse_inbound(pb_payload)
    assert events[0]["message_type"] == "INTERACTIVE_REPLY"
    assert events[0]["payload"] == {"kind": "postback", "id": "GET_STARTED", "title": "Get Started"}
    assert events[0]["external_message_id"]  # synthesized, non-empty


def test_messenger_parse_inbound_reply_to_mid():
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    payload = {
        "object": "page",
        "entry": [{"id": "pg-701", "messaging": [{
            "sender": {"id": "psid-6"}, "timestamp": 6,
            "message": {"mid": "m.6", "text": "re: that", "reply_to": {"mid": "m.original"}},
        }]}],
    }
    events = MessengerAdapter().parse_inbound(payload)
    assert events[0]["reply_to_external_id"] == "m.original"


def test_messenger_parse_inbound_malformed_payload_never_raises():
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    adapter = MessengerAdapter()
    assert adapter.parse_inbound({}) == []
    assert adapter.parse_inbound({"entry": "not-a-list"}) == []
    assert adapter.parse_inbound({"entry": [{"id": "p", "messaging": "nope"}]}) == []
    assert adapter.parse_inbound({"entry": [{"id": "p", "messaging": [{}]}]}) == []


def test_messenger_parse_inbound_read_delivery_reaction_kinds():
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    adapter = MessengerAdapter()
    delivery = adapter.parse_inbound({
        "object": "page",
        "entry": [{"id": "pg-701", "messaging": [
            {"sender": {"id": "psid-7"}, "delivery": {"mids": ["m.7"], "watermark": 123}}
        ]}],
    })
    assert delivery[0]["kind"] == "status" and delivery[0]["status"] == "DELIVERED"
    assert "external_message_id" not in delivery[0]  # parsed only, S5 applies it

    read = adapter.parse_inbound({
        "object": "page",
        "entry": [{"id": "pg-701", "messaging": [
            {"sender": {"id": "psid-8"}, "read": {"watermark": 456}}
        ]}],
    })
    assert read[0]["kind"] == "status" and read[0]["status"] == "READ"

    reaction = adapter.parse_inbound({
        "object": "page",
        "entry": [{"id": "pg-701", "messaging": [
            {"sender": {"id": "psid-9"}, "reaction": {"mid": "m.9", "emoji": "❤", "action": "react"}}
        ]}],
    })
    assert reaction[0]["kind"] == "reaction" and reaction[0]["emoji"] == "❤"


# ── AC-CHN-19: echo dropped ───────────────────────────────────────────────────
def test_messenger_echo_produces_no_event():
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    payload = {
        "object": "page",
        "entry": [{"id": "pg-701", "messaging": [{
            "sender": {"id": "pg-701"}, "timestamp": 1,
            "message": {"mid": "m.echo", "text": "our own reply", "is_echo": True},
        }]}],
    }
    assert MessengerAdapter().parse_inbound(payload) == []


def test_full_pipeline_drops_echo_never_creates_a_bubble(session_factory):
    _fb_channel(session_factory, external_account_id="pg-echo-1")
    payload = {
        "object": "page",
        "entry": [{"id": "pg-echo-1", "messaging": [{
            "sender": {"id": "pg-echo-1"}, "timestamp": 1,
            "message": {"mid": "m.echo-1", "text": "sent by us", "is_echo": True},
        }]}],
    }
    counters = _process(session_factory, "meta", payload)
    assert counters == {"messages": 0, "statuses": 0, "skipped": 0}


# ── AC-CHN-20: PSID stitch, new contact, no phone stitch, reuse, per-channel isolation
def test_messenger_inbound_creates_new_contact_no_phone(client, session_factory):
    _fb_channel(session_factory, external_account_id="pg-new-1")
    counters = _process(session_factory, "meta", _messenger_payload(page_id="pg-new-1", psid="psid-new-1", mid="m.new-1"))
    assert counters["messages"] == 1

    from modules.omnichannel.models import Contact, ContactChannelIdentity

    db = session_factory()
    identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.external_user_id == "psid-new-1").first()
    assert identity is not None
    contact = db.query(Contact).filter(Contact.id == identity.contact_id).first()
    assert contact.phone is None
    assert contact.phone_digits is None
    assert contact.lifecycle_status_id is not None
    db.close()

    from modules.omnichannel.models import ConversationEvent

    db = session_factory()
    opened = db.query(ConversationEvent).filter(
        ConversationEvent.contact_id == contact.id, ConversationEvent.event_type == "opened"
    ).first()
    assert opened is not None
    db.close()


def test_messenger_inbound_never_stitches_by_phone_even_with_numeric_psid(session_factory):
    """A numeric-looking PSID must never match an existing phone-based contact
    (D-A7-4) - the phone stitch is not attempted for FACEBOOK at all."""
    from modules.omnichannel.models import Contact, Workspace
    from modules.omnichannel.services import lifecycle_service

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)).first()
    existing = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, first_name="Phone", last_name="Owner",
        phone="+60123456999", phone_digits="60123456999", priority="MEDIUM",
        lifecycle_status_id=lifecycle_service.initial_status_id(db, DEFAULT_TENANT_ID, ws.id),
    )
    db.add(existing)
    db.commit()
    existing_id = existing.id
    db.close()

    _fb_channel(session_factory, external_account_id="pg-nostitch-1")
    # PSID happens to be all-digits and matches the existing contact's digits.
    _process(
        session_factory, "meta",
        _messenger_payload(page_id="pg-nostitch-1", psid="60123456999", mid="m.nostitch-1"),
    )

    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    identity = db.query(ContactChannelIdentity).filter(
        ContactChannelIdentity.external_user_id == "60123456999",
        ContactChannelIdentity.tenant_id == DEFAULT_TENANT_ID,
    ).first()
    assert identity is not None
    assert identity.contact_id != existing_id  # a NEW contact, never the phone owner
    db.close()


def test_messenger_inbound_second_message_reuses_same_contact(session_factory):
    _fb_channel(session_factory, external_account_id="pg-reuse-1")
    _process(session_factory, "meta", _messenger_payload(page_id="pg-reuse-1", psid="psid-reuse-1", mid="m.r1", text="first"))
    _process(session_factory, "meta", _messenger_payload(page_id="pg-reuse-1", psid="psid-reuse-1", mid="m.r2", text="second"))

    from modules.omnichannel.models import ContactChannelIdentity, ConversationMessage

    db = session_factory()
    identities = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.external_user_id == "psid-reuse-1").all()
    assert len(identities) == 1
    msgs = db.query(ConversationMessage).filter(ConversationMessage.contact_id == identities[0].contact_id).all()
    assert len(msgs) == 2
    db.close()


def test_same_psid_on_different_channel_is_a_separate_contact(session_factory):
    _fb_channel(session_factory, external_account_id="pg-iso-a")
    _fb_channel(session_factory, external_account_id="pg-iso-b")
    _process(session_factory, "meta", _messenger_payload(page_id="pg-iso-a", psid="psid-shared", mid="m.iso-a"))
    _process(session_factory, "meta", _messenger_payload(page_id="pg-iso-b", psid="psid-shared", mid="m.iso-b"))

    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    identities = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.external_user_id == "psid-shared").all()
    assert len(identities) == 2
    assert identities[0].contact_id != identities[1].contact_id
    db.close()


# ── AC-CHN-21: window stamped on the identity; dual write WhatsApp only ─────
def test_messenger_inbound_stamps_identity_window_never_contact_csw(session_factory):
    _fb_channel(session_factory, external_account_id="pg-window-1")
    before = datetime.now(timezone.utc)
    _process(session_factory, "meta", _messenger_payload(page_id="pg-window-1", psid="psid-window-1", mid="m.win-1"))

    from modules.omnichannel.models import Contact, ContactChannelIdentity

    db = session_factory()
    identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.external_user_id == "psid-window-1").first()
    contact = db.query(Contact).filter(Contact.id == identity.contact_id).first()
    assert identity.window_expires_at is not None
    assert identity.window_expires_at >= before + timedelta(hours=23)
    assert identity.human_agent_expires_at is not None
    assert identity.human_agent_expires_at >= before + timedelta(hours=167)
    assert identity.last_inbound_at is not None
    # F4: contacts.csw_expires_at is a WhatsApp-only mirror - a Messenger
    # contact's copy stays null.
    assert contact.csw_expires_at is None
    assert contact.last_incoming_message_at is None
    db.close()


def test_whatsapp_inbound_still_dual_writes_contact_csw(session_factory):
    from tests.test_omnichannel_conversations import _seed_thread
    from tests.test_omnichannel_webhooks import _channel_id, _wa_payload

    _seed_thread(session_factory, messages=[{}])
    _process(session_factory, _channel_id(session_factory), _wa_payload(wamid="wamid.dualwrite-1", from_="60199988877"))

    from modules.omnichannel.models import Contact, ContactChannelIdentity

    db = session_factory()
    identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.external_user_id == "60199988877").first()
    contact = db.query(Contact).filter(Contact.id == identity.contact_id).first()
    assert contact.csw_expires_at is not None  # unchanged WhatsApp behaviour
    assert contact.last_incoming_message_at is not None
    assert identity.window_expires_at is not None  # AND the new identity column
    assert identity.human_agent_expires_at is None  # WhatsApp has no human-agent window
    db.close()


def test_whatsapp_channel_still_reopens_thread_with_events(session_factory):
    """Reopen/unsnoozed event behaviour is unchanged for every type (AC-CHN-21) -
    this pins the pre-existing WhatsApp path stays intact after the shared
    `_handle_message` refactor."""
    from tests.test_omnichannel_conversations import _seed_thread
    from tests.test_omnichannel_webhooks import _channel_id, _wa_payload

    _seed_thread(session_factory, messages=[{}])
    counters = _process(session_factory, _channel_id(session_factory), _wa_payload(wamid="wamid.reopen-check-1", from_="60177766655"))
    assert counters["messages"] == 1


# ── Cross-tenant isolation ────────────────────────────────────────────────────
def test_page_id_owned_by_tenant_b_never_lands_in_tenant_a(client, session_factory):
    _fb_channel(session_factory, tenant_id=DEFAULT_TENANT_ID, external_account_id="pg-tenant-a")

    _other_tenant_auth(client, session_factory, slug="other-chn-msgr")
    from app.models import Tenant

    db = session_factory()
    tenant_b = db.query(Tenant).filter(Tenant.slug == "other-chn-msgr").first()
    tenant_b_id = tenant_b.id
    db.close()
    _fb_channel(session_factory, tenant_id=tenant_b_id, external_account_id="pg-tenant-b")

    _process(session_factory, "meta", _messenger_payload(page_id="pg-tenant-b", psid="psid-cross-1", mid="m.cross-1"))

    from modules.omnichannel.models import Contact, ContactChannelIdentity

    db = session_factory()
    identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.external_user_id == "psid-cross-1").first()
    assert identity is not None
    assert identity.tenant_id == tenant_b_id
    contact = db.query(Contact).filter(Contact.id == identity.contact_id).first()
    assert contact.tenant_id == tenant_b_id
    # Nothing leaked into tenant A.
    leaked = db.query(Contact).filter(
        Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone.is_(None),
    ).join(ContactChannelIdentity, ContactChannelIdentity.contact_id == Contact.id).filter(
        ContactChannelIdentity.external_user_id == "psid-cross-1"
    ).first()
    assert leaked is None
    db.close()


# ── plan-31 resume hook + message_received trigger fire for Messenger too ──
def _publish_trigger_only_workflow(db, *, channel_id, agent_id):
    """A minimal `omnichannel.message_received` -> `ai_agent.run` workflow with
    NO outbound send node - S1 is inbound-only (`MessengerAdapter.send` is a
    dev-stub the outbound generalization in plan 32 S2 completes), so this
    intentionally never exercises the outbound path, only that the TRIGGER
    fires for a Messenger channel exactly as it does for WhatsApp."""
    from app.services.workflow_service import WorkflowService

    doc = {
        "schemaVersion": 1,
        "nodes": [
            {
                "id": "trg_1",
                "kind": "trigger",
                "type": "omnichannel.message_received",
                "config": {"channelId": channel_id} if channel_id else {},
            },
            {
                "id": "ai_1",
                "kind": "action",
                "type": "ai_agent.run",
                "config": {
                    "agentId": agent_id,
                    "instructions": "Classify intent, domain, urgency.",
                    "inputText": "{{ trigger.message.text }}",
                    "outputParams": [
                        {"key": "intent", "type": "string", "required": True},
                        {"key": "domain", "type": "string", "required": True},
                        {"key": "urgency", "type": "string", "required": True},
                    ],
                },
            },
        ],
        "edges": [{"id": "e1", "source": "trg_1", "target": "ai_1", "sourcePort": "out"}],
    }
    service = WorkflowService(db)
    wf = service.create(
        DEFAULT_TENANT_ID, name="Test messenger trigger-only workflow", description="", draft=doc, actor_id=None
    )
    service.set_active(wf.id, DEFAULT_TENANT_ID, True)
    service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
    db.refresh(wf)
    return wf


def test_message_received_trigger_fires_for_messenger_inbound(session_factory):
    from app.ai.stub import StubResponse, stub_fixtures
    from app.models.workflow import RUN_SUCCESS, WorkflowRun
    from tests.test_omnichannel_workflow_triggers import _make_agent

    fb_channel_id = _fb_channel(session_factory, external_account_id="pg-trigger-1")
    db = session_factory()
    try:
        agent = _make_agent(db, key="k-messenger")
        wf = _publish_trigger_only_workflow(db, channel_id=None, agent_id=agent.id)
        wf_id = wf.id
    finally:
        db.close()

    with stub_fixtures(StubResponse(structured={"intent": "support", "domain": "billing", "urgency": "low"})):
        _process(
            session_factory, "meta",
            _messenger_payload(page_id="pg-trigger-1", psid="psid-trigger-1", mid="m.trigger-1", text="Need help"),
        )

    db = session_factory()
    runs = db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf_id).all()
    assert len(runs) == 1
    assert runs[0].status == RUN_SUCCESS
    assert runs[0].trigger_payload_json["omnichannel"]["channelId"] == fb_channel_id
    assert runs[0].trigger_payload_json["omnichannel"]["messageText"] == "Need help"
    db.close()


def test_resume_from_inbound_consumed_answer_skips_messenger_trigger(session_factory, monkeypatch):
    """The plan-31 resume hook is channel-blind (operates on `contact` only) -
    when it claims the message as an answer, NO `message_received` run is
    created, exactly like the WhatsApp path (D-A5-8 / F2)."""
    from app.models.workflow import WorkflowRun
    from tests.test_omnichannel_workflow_triggers import _make_agent

    _fb_channel(session_factory, external_account_id="pg-consumed-1")
    db = session_factory()
    try:
        agent = _make_agent(db, key="k-messenger-consumed")
        wf = _publish_trigger_only_workflow(db, channel_id=None, agent_id=agent.id)
        wf_id = wf.id
    finally:
        db.close()

    # `_handle_message` imports `resume_from_inbound` lazily inside itself
    # (`from .workflow_waits import resume_from_inbound`) - patching the NAME
    # on the source module is what the lazy import picks up.
    from modules.omnichannel.services import workflow_waits

    monkeypatch.setattr(workflow_waits, "resume_from_inbound", lambda *a, **k: True)

    _process(
        session_factory, "meta",
        _messenger_payload(page_id="pg-consumed-1", psid="psid-consumed-1", mid="m.consumed-1", text="42"),
    )

    db = session_factory()
    runs = db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf_id).all()
    assert len(runs) == 0
    db.close()


# ── Dev seed ─────────────────────────────────────────────────────────────────
def test_dev_seed_creates_chn_demo_fb(session_factory):
    from modules.omnichannel.bootstrap import seed_demo_conversations
    from modules.omnichannel.models import Channel

    db = session_factory()
    seed_demo_conversations(db, DEFAULT_TENANT_ID)
    channel = db.query(Channel).filter(Channel.id == "chn-demo-fb", Channel.tenant_id == DEFAULT_TENANT_ID).first()
    assert channel is not None
    assert channel.channel_type == "FACEBOOK"
    assert channel.external_account_id == "pg-demo-1"
    db.close()

    # Idempotent re-run.
    db = session_factory()
    seed_demo_conversations(db, DEFAULT_TENANT_ID)
    count = db.query(Channel).filter(Channel.id == "chn-demo-fb", Channel.tenant_id == DEFAULT_TENANT_ID).count()
    assert count == 1
    db.close()
