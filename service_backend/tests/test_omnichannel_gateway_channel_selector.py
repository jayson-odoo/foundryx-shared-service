"""Plan 32 (A7a) Slice S6 - public gateway channel preference/selector, `to`
prefixes, the two new error codes, widened read-shape `channelType`, and the
`omnichannel.message_received` trigger's `channelType` filter.

AC-CHN-53..58 (see documentation/plans/sprint-4/
32-omnichannel-channels-messenger-instagram-acceptance-criteria.md).
"""
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services import idempotency, realtime
from tests.test_omnichannel_api_gateway import (
    _auth,
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
)
from tests.test_omnichannel_channels_messenger import _fb_channel, _messenger_payload, _process


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


@pytest.fixture(autouse=True)
def _fake_realtime():
    client = fakeredis.FakeRedis(decode_responses=True)
    realtime.set_client(client)
    yield client
    realtime.set_client(None)


def _key(client, workspace_id) -> str:
    return _mint(client, workspace_id).json()["fullKey"]


def _send(client, key, body):
    return client.post(
        "/api/v1/omnichannel/messages", json=body, headers={"Authorization": f"Bearer {key}"}
    )


# ── AC-CHN-53: implicit preference + explicit selector ──────────────────────
def test_implicit_choice_prefers_whatsapp_over_an_older_messenger_channel(client, session_factory):
    ws = _default_workspace_id(session_factory)
    # Messenger channel created FIRST (would win the old "oldest active" rule).
    _fb_channel(session_factory, external_account_id="pg-801")
    _seed_channel(session_factory, ws, phone_number_id="pn-pref")
    _seed_open_contact(session_factory, ws, phone="+60129998888", open_window=True)
    key = _key(client, ws)

    r = _send(client, key, {"to": "+60129998888", "type": "text", "text": {"body": "hi"}})
    assert r.status_code == 202, r.text

    from modules.omnichannel.models import ConversationMessage, Channel

    db = session_factory()
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == r.json()["id"]).first()
    channel = db.query(Channel).filter(Channel.id == msg.channel_id).first()
    assert channel.channel_type == "WHATSAPP"
    db.close()


def test_explicit_channel_id_wins_over_the_whatsapp_preference(client, session_factory):
    ws = _default_workspace_id(session_factory)
    fb_id = _fb_channel(session_factory, external_account_id="pg-802")
    _seed_channel(session_factory, ws, phone_number_id="pn-pref2")
    key = _key(client, ws)

    # Seed a Messenger identity via a real inbound message (also opens the window).
    _process(session_factory, fb_id, _messenger_payload(page_id="pg-802", psid="psid-802", mid="m.802"))

    r = _send(
        client, key,
        {"to": "psid:psid-802", "channelId": fb_id, "type": "text", "text": {"body": "hi"}},
    )
    assert r.status_code == 202, r.text

    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == r.json()["id"]).first()
    assert msg.channel_id == fb_id
    db.close()


def test_explicit_channel_id_wins_for_a_second_whatsapp_channel_not_a_silent_fallback(
    client, session_factory
):
    """Security review round 1, blocker 2 - `_override_for` must return the
    CHOSEN channel unconditionally. A workspace with two active WhatsApp
    channels where the contact's existing identity sits on the FIRST one:
    an explicit `channelId` naming the SECOND must win outright, never
    silently re-resolve through `via_identity` back to the first (that is
    exactly "a silent fallback to another channel", AC-CHN-53)."""
    from modules.omnichannel.models import Channel, Contact, ContactChannelIdentity

    ws = _default_workspace_id(session_factory)
    first_id = _seed_channel(session_factory, ws, phone_number_id="pn-w1")
    second_id = _seed_channel(session_factory, ws, phone_number_id="pn-w2")
    phone = "+60129990001"
    contact_id = _seed_open_contact(session_factory, ws, phone=phone, open_window=True)

    db = session_factory()
    db.add(
        ContactChannelIdentity(
            tenant_id=DEFAULT_TENANT_ID,
            contact_id=contact_id,
            channel_id=first_id,
            external_user_id=phone,
        )
    )
    db.commit()
    db.close()

    key = _key(client, ws)
    r = _send(
        client, key,
        {"to": phone, "channelId": second_id, "type": "text", "text": {"body": "hi"}},
    )
    assert r.status_code == 202, r.text

    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == r.json()["id"]).first()
    assert msg.channel_id == second_id
    db.close()


def test_unknown_channel_id_is_a_typed_422_never_a_silent_fallback(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60121110000", open_window=True)
    key = _key(client, ws)

    r = _send(
        client, key,
        {"to": "+60121110000", "channelId": "not-a-real-channel", "type": "text", "text": {"body": "hi"}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_channel"


def test_foreign_channel_id_from_another_workspace_is_rejected(client, session_factory):
    from modules.omnichannel.models import Workspace

    ws = _default_workspace_id(session_factory)
    db = session_factory()
    other_ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Other WS")
    db.add(other_ws)
    db.commit()
    other_ws_id = other_ws.id
    db.close()
    other_channel_id = _seed_channel(session_factory, other_ws_id, phone_number_id="pn-foreign")
    key = _key(client, ws)

    r = _send(
        client, key,
        {"to": "+60122223333", "channelId": other_channel_id, "type": "text", "text": {"body": "hi"}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_channel"


# ── AC-CHN-54: "to" prefixes ─────────────────────────────────────────────────
def test_to_psid_resolves_the_existing_identity_and_sends(client, session_factory):
    ws = _default_workspace_id(session_factory)
    fb_id = _fb_channel(session_factory, external_account_id="pg-810")
    key = _key(client, ws)
    _process(session_factory, fb_id, _messenger_payload(page_id="pg-810", psid="psid-810", mid="m.810"))

    r = _send(
        client, key,
        {"to": "psid:psid-810", "channelId": fb_id, "type": "text", "text": {"body": "hi there"}},
    )
    assert r.status_code == 202, r.text


def test_to_psid_that_resolves_nothing_is_422_and_never_creates_a_contact(client, session_factory):
    ws = _default_workspace_id(session_factory)
    fb_id = _fb_channel(session_factory, external_account_id="pg-811")
    key = _key(client, ws)

    from modules.omnichannel.models import Contact

    db = session_factory()
    before = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID).count()
    db.close()

    r = _send(
        client, key,
        {"to": "psid:no-such-psid", "channelId": fb_id, "type": "text", "text": {"body": "hi"}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_recipient"

    db = session_factory()
    after = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID).count()
    db.close()
    assert after == before


def test_to_igsid_that_resolves_nothing_is_422_invalid_recipient(client, session_factory):
    from tests.test_omnichannel_channels_instagram import _ig_channel

    ws = _default_workspace_id(session_factory)
    ig_id = _ig_channel(session_factory, external_account_id="ig-810")
    key = _key(client, ws)

    r = _send(
        client, key,
        {"to": "igsid:no-such-igsid", "channelId": ig_id, "type": "text", "text": {"body": "hi"}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_recipient"


def test_to_id_resolves_an_existing_contact_by_foundryx_id(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_open_contact(session_factory, ws, phone="+60177778888", open_window=True)
    key = _key(client, ws)

    r = _send(client, key, {"to": f"id:{cid}", "type": "text", "text": {"body": "hi"}})
    assert r.status_code == 202, r.text


def test_bare_phone_still_resolves_and_sends_whatsapp_unchanged(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60188889999", open_window=True)
    key = _key(client, ws)

    r = _send(client, key, {"to": "+60188889999", "type": "text", "text": {"body": "hi"}})
    assert r.status_code == 202, r.text


# ── AC-CHN-55: WhatsApp keeps csw_window_closed; Messenger/IG get a NEW code ─
def test_whatsapp_closed_window_keeps_the_verbatim_csw_code(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60199990000", open_window=False)
    key = _key(client, ws)

    r = _send(client, key, {"to": "+60199990000", "type": "text", "text": {"body": "hi"}})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "csw_window_closed"


def test_messenger_closed_window_gets_the_new_distinct_code(client, session_factory):
    ws = _default_workspace_id(session_factory)
    fb_id = _fb_channel(session_factory, external_account_id="pg-820")
    key = _key(client, ws)
    _process(session_factory, fb_id, _messenger_payload(page_id="pg-820", psid="psid-820", mid="m.820"))

    # Push the identity's window fully closed (past even the human-agent window).
    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    identity = (
        db.query(ContactChannelIdentity)
        .filter(ContactChannelIdentity.channel_id == fb_id, ContactChannelIdentity.external_user_id == "psid-820")
        .first()
    )
    identity.window_expires_at = _now() - timedelta(hours=200)
    identity.human_agent_expires_at = _now() - timedelta(hours=1)
    db.commit()
    db.close()

    r = _send(
        client, key,
        {"to": "psid:psid-820", "channelId": fb_id, "type": "text", "text": {"body": "hi"}},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "messaging_window_closed"
    assert r.json()["error"]["code"] != "csw_window_closed"


def test_gateway_send_inside_human_agent_window_is_automation_refused_as_messaging_window_closed(
    client, session_factory
):
    """The gateway is API-key automation by construction (D-A7-6) - it can
    never use the human-agent extension, so it surfaces the SAME public code
    as fully-closed, not a THIRD public code."""
    ws = _default_workspace_id(session_factory)
    fb_id = _fb_channel(session_factory, external_account_id="pg-821")
    key = _key(client, ws)
    _process(session_factory, fb_id, _messenger_payload(page_id="pg-821", psid="psid-821", mid="m.821"))

    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    identity = (
        db.query(ContactChannelIdentity)
        .filter(ContactChannelIdentity.channel_id == fb_id, ContactChannelIdentity.external_user_id == "psid-821")
        .first()
    )
    identity.window_expires_at = _now() - timedelta(hours=1)  # standard window closed
    identity.human_agent_expires_at = _now() + timedelta(hours=100)  # still in the human-agent window
    db.commit()
    db.close()

    r = _send(
        client, key,
        {"to": "psid:psid-821", "channelId": fb_id, "type": "text", "text": {"body": "hi"}},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "messaging_window_closed"


# ── channel_not_available_for_contact ────────────────────────────────────────
def test_no_identity_on_the_chosen_channel_is_channel_not_available_for_contact(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    fb_id = _fb_channel(session_factory, external_account_id="pg-830")
    # A WhatsApp-only contact (no Messenger identity at all).
    cid = _seed_open_contact(session_factory, ws, phone="+60155556666", open_window=True)
    key = _key(client, ws)

    r = _send(
        client, key,
        {"to": f"id:{cid}", "channelId": fb_id, "type": "text", "text": {"body": "hi"}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "channel_not_available_for_contact"


# ── AC-CHN-56: widened channelType on both read shapes, lossless ────────────
def test_default_and_rio_shapes_carry_facebook_channel_type(client, session_factory):
    ws = _default_workspace_id(session_factory)
    fb_id = _fb_channel(session_factory, external_account_id="pg-840")
    key = _key(client, ws)
    _process(session_factory, fb_id, _messenger_payload(page_id="pg-840", psid="psid-840", mid="m.840"))

    hdr = {"Authorization": f"Bearer {key}"}
    default = client.get(
        "/api/v1/omnichannel/contacts", headers=hdr, params={"search": ""}
    ).json()
    fb_thread = next(t for t in default["data"] if t["channelId"] == fb_id)
    assert fb_thread["channelType"] == "FACEBOOK"
    assert fb_thread["cswExpiresAt"] is None  # WhatsApp-only mirror stays null
    assert fb_thread["windowExpiresAt"] is not None

    rio = client.get(
        "/api/v1/omnichannel/contacts", headers=hdr, params={"format": "rio"}
    ).json()
    fb_rio = next(i for i in rio["items"] if i["channelId"] == fb_id)
    assert fb_rio["channelType"] == "FACEBOOK"
    assert fb_rio["windowExpiresAt"] is not None


def test_message_item_carries_channel_type_on_both_shapes(client, session_factory):
    ws = _default_workspace_id(session_factory)
    fb_id = _fb_channel(session_factory, external_account_id="pg-841")
    key = _key(client, ws)
    _process(session_factory, fb_id, _messenger_payload(page_id="pg-841", psid="psid-841", mid="m.841"))

    hdr = {"Authorization": f"Bearer {key}"}
    contact = client.get("/api/v1/omnichannel/contacts", headers=hdr).json()["data"][0]
    cid = contact["id"]

    default = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages", headers=hdr).json()
    assert default["data"][0]["channelType"] == "FACEBOOK"

    rio = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages", headers=hdr, params={"format": "rio"}
    ).json()
    assert rio["items"][0]["channelType"] == "FACEBOOK"


def test_rio_message_shape_emits_media_unavailable_for_a_non_media_unsupported_row(
    client, session_factory, monkeypatch
):
    """Security review round 1, nit - the `{"mediaUnavailable": true}`
    internal marker can land on a row whose `message_type` did NOT resolve
    to a known media kind (an unmapped Messenger attachment kind with a
    `url` still falls through to `UNSUPPORTED`). The rio shape must keep
    emitting the flag rather than nulling it back to `None` just because
    `is_media` reads false - lossless vs the internal item."""
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    monkeypatch.setattr(MessengerAdapter, "fetch_media_url", lambda self, creds, url, kind=None: None)

    ws = _default_workspace_id(session_factory)
    fb_id = _fb_channel(session_factory, external_account_id="pg-850")
    key = _key(client, ws)

    payload = {
        "object": "page",
        "entry": [{"id": "pg-850", "messaging": [{
            "sender": {"id": "psid-850"}, "timestamp": 1,
            # "fallback" is not in `_ATTACHMENT_TYPES` - resolves to
            # UNSUPPORTED, but carries a `url` so the fetch (and its
            # failure) still runs.
            "message": {"mid": "m.850", "attachments": [
                {"type": "fallback", "payload": {"url": "https://scontent.xx.fbcdn.net/v/x"}}
            ]},
        }]}],
    }
    _process(session_factory, fb_id, payload)

    hdr = {"Authorization": f"Bearer {key}"}
    contact = client.get("/api/v1/omnichannel/contacts", headers=hdr).json()["data"][0]
    cid = contact["id"]
    rio = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages", headers=hdr, params={"format": "rio"}
    ).json()
    item = next(m for m in rio["items"] if m["channelMessageId"] == "m.850")
    assert item["message"]["type"] == "unsupported"
    assert item["message"]["mediaUnavailable"] is True


def test_consumer_guide_documents_the_channel_selector_and_new_codes():
    import pathlib

    guide = (
        pathlib.Path(__file__).resolve().parents[2]
        / "documentation"
        / "omnichannel"
        / "consumer-integration-guide.md"
    ).read_text()
    assert "channelId" in guide
    assert "psid:" in guide
    assert "igsid:" in guide
    assert "messaging_window_closed" in guide
    assert "channel_not_available_for_contact" in guide
    assert "invalid_channel" in guide
    assert "windowExpiresAt" in guide
    assert "humanAgentExpiresAt" in guide
    # Security review round 1, should-fix - a `Rio*` schema change without
    # the matching guide change is an automatic review finding (CLAUDE.md).
    assert "mediaUnavailable" in guide


# ── AC-CHN-58: message_received channelType filter ───────────────────────────
def test_message_received_channel_type_filter_matches_only_that_type(session_factory):
    from modules.omnichannel import workflow_nodes

    ev = {
        "action": "received",
        "extra": {"channelId": "chn-1", "channelType": "FACEBOOK", "isFirstMessage": True},
    }
    assert workflow_nodes._message_received_refine({"channelType": "FACEBOOK"}, ev) is True
    assert workflow_nodes._message_received_refine({"channelType": "INSTAGRAM"}, ev) is False
    # Unset = any type (unchanged default behaviour).
    assert workflow_nodes._message_received_refine({}, ev) is True
    # Composable with the existing channel-id filter.
    assert (
        workflow_nodes._message_received_refine({"channelId": "chn-1", "channelType": "FACEBOOK"}, ev)
        is True
    )
    assert (
        workflow_nodes._message_received_refine({"channelId": "chn-2", "channelType": "FACEBOOK"}, ev)
        is False
    )


def test_message_received_trigger_declares_the_channel_type_field():
    from app.workflow_engine.registry import get_trigger

    trig = get_trigger("omnichannel.message_received")
    field = next(f for f in trig.fields if f.key == "channelType")
    # Plan 34 / A7b S6 (AC-WEB-61) adds WEBCHAT to this same static list.
    assert {o["value"] for o in field.options} == {"WHATSAPP", "FACEBOOK", "INSTAGRAM", "WEBCHAT"}
    assert field.required is False


def test_inbound_extra_carries_channel_type_for_the_executor_context():
    """The executor's `_ctx_from_payload` flattens ANY `omnichannel` extra
    dict into `trigger.channelType` unconditionally (AC-CHN-58) - pins the
    wire this slice adds `inbound_service.py`'s `extra["channelType"]` onto
    (checked by field/refine tests above)."""
    from app.workflow_engine.entity_events import build_event_trigger_payload
    from app.workflow_engine.executor import _ctx_from_payload

    ev = {
        "action": "received",
        "actor": None,
        "record_id": "m.850",
        "changes": None,
        "record_facts": {},
        "extra": {
            "channelId": "chn-850",
            "channelName": "Test Messenger",
            "channelType": "FACEBOOK",
            "contactId": "c1",
            "contactName": "",
            "contactPhone": "",
            "conversationId": "c1",
            "messageId": "m.850",
            "messageType": "TEXT",
            "messageText": "Hello there",
            "mediaUrl": None,
            "mediaMime": None,
            "isFirstMessage": True,
        },
    }
    payload = build_event_trigger_payload(ev)
    ctx = _ctx_from_payload(payload)
    assert ctx["trigger.channelType"] == "FACEBOOK"


def test_inbound_service_stamps_channel_type_on_the_dispatched_extra(session_factory, monkeypatch):
    """Real inbound path (plan 32 / A7a S6) - `inbound_service._handle_message`
    passes `extra["channelType"]` to `notify_entity_event` for a Messenger
    message, captured here without needing a published workflow."""
    captured = {}

    def _fake_notify(db, entity_type, action, record, *, tenant_id, extra=None):
        captured["extra"] = extra

    monkeypatch.setattr(
        "app.workflow_engine.entity_events.notify_entity_event", _fake_notify
    )
    fb_id = _fb_channel(session_factory, external_account_id="pg-851")
    _process(session_factory, fb_id, _messenger_payload(page_id="pg-851", psid="psid-851", mid="m.851"))

    assert captured.get("extra", {}).get("channelType") == "FACEBOOK"
