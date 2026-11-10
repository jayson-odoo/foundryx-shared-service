"""Plan 32 (A7a) Slice S4 - Instagram adapter, IG-only inbound kinds as
placeholders, IG policy + capabilities, dev seed `chn-demo-ig`.

AC-CHN-40..45 (see documentation/plans/sprint-4/
32-omnichannel-channels-messenger-instagram-acceptance-criteria.md).

Everything Instagram send/window/addressing already rides the type-blind
generalizations plan 32 S1/S2/S3 shipped (`messaging_policy.POLICIES/
CAPABILITIES["INSTAGRAM"]`, `channel_addressing`, `adapters.get_adapter`,
`meta_connect_service`) - this file's job is the ONE thing that is actually
new in S4: `InstagramAdapter._parse_one` (the IG-only inbound kinds) plus the
dev seed. Several tests below re-exercise already-generalized S1/S2/S3 code
paths end-to-end WITH an `object: "instagram"` payload / an INSTAGRAM channel
specifically, because that exact code path (this slice's AC ids) had no
Instagram-shaped coverage before this file.
"""
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services import realtime
from tests.test_omnichannel_channels_messenger import _fb_channel, _process
from tests.test_omnichannel_conversations import _auth
from tests.test_omnichannel_contact_data_model import _other_tenant_auth


@pytest.fixture(autouse=True)
def _fake_realtime():
    client = fakeredis.FakeRedis(decode_responses=True)
    realtime.set_client(client)
    yield client
    realtime.set_client(None)


def _ig_channel(session_factory, *, tenant_id=DEFAULT_TENANT_ID, external_account_id="ig-701", channel_id=None):
    from modules.omnichannel.models import Channel, Workspace
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.tenant_id == tenant_id, Workspace.is_default.is_(True)).first()
    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        workspace_id=ws.id,
        channel_type="INSTAGRAM",
        name="Test Instagram",
        credentials_json=encrypt_credentials({"dev": True}),
        external_account_id=external_account_id,
        external_account_name="Test IG Account",
        is_active=True,
        status_id=statuses.status_id_for(db, tenant_id, "CHANNEL", "ACTIVE"),
    )
    db.add(channel)
    db.flush()
    db.commit()
    cid = channel.id
    db.close()
    return cid


def _ig_payload(*, ig_id="ig-701", igsid="igsid-1", mid="m.ig1", text="Hello there", timestamp=1717550000000):
    return {
        "object": "instagram",
        "entry": [
            {
                "id": ig_id,
                "time": timestamp,
                "messaging": [
                    {
                        "sender": {"id": igsid},
                        "recipient": {"id": ig_id},
                        "timestamp": timestamp,
                        "message": {"mid": mid, "text": text},
                    }
                ],
            }
        ],
    }


# ── AC-CHN-40: object: "instagram" dispatch + Messenger normalizer reuse ────
def test_instagram_is_subclass_of_messenger_shared_code_inherited_not_copied():
    from modules.omnichannel.adapters.instagram import InstagramAdapter
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    assert issubclass(InstagramAdapter, MessengerAdapter)
    assert InstagramAdapter.channel_type == "INSTAGRAM"
    # `send`/`list_pages`/`test_connection`/`exchange_code` are NOT redefined
    # on InstagramAdapter - they resolve straight through to MessengerAdapter.
    for name in ("send", "list_pages", "test_connection", "exchange_code", "subscribe_webhook"):
        assert name not in InstagramAdapter.__dict__


def test_ig_webhook_object_dispatch_resolves_instagram_channel_by_external_account_id(client, session_factory):
    cid = _ig_channel(session_factory, external_account_id="ig-dispatch-1")

    counters = _process(session_factory, "meta", _ig_payload(ig_id="ig-dispatch-1", mid="m.ig-dispatch-1"))
    assert counters["messages"] == 1

    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    msg = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "m.ig-dispatch-1").first()
    assert msg.channel_id == cid
    db.close()


def test_ig_webhook_url_channel_id_is_last_resort_fallback(session_factory):
    cid = _ig_channel(session_factory, external_account_id="ig-fallback-1")
    counters = _process(
        session_factory, cid, _ig_payload(ig_id="ig-does-not-exist-anywhere", mid="m.ig-fb-1")
    )
    assert counters["messages"] == 1


def test_ig_reuses_messenger_normalizer_for_text_media_quickreply_postback_reaction():
    """AC-CHN-40: the SAME normalizer Messenger uses (image/video/audio,
    quick replies, postbacks, reactions) - identical shapes, identical
    results, on `InstagramAdapter`."""
    from modules.omnichannel.adapters.instagram import InstagramAdapter

    adapter = InstagramAdapter()

    text_events = adapter.parse_inbound(_ig_payload(text="Hi!"))
    assert text_events[0]["message_type"] == "TEXT"
    assert text_events[0]["body"] == "Hi!"
    assert text_events[0]["from"] == "igsid-1"

    media_events = adapter.parse_inbound({
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [{
            "sender": {"id": "igsid-2"}, "timestamp": 2,
            "message": {"mid": "m.ig2", "attachments": [
                {"type": "image", "payload": {"url": "https://scontent.cdninstagram.com/x.jpg"}}
            ]},
        }]}],
    })
    assert media_events[0]["message_type"] == "IMAGE"
    assert media_events[0]["media_url"] == "https://scontent.cdninstagram.com/x.jpg"

    qr_events = adapter.parse_inbound({
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [{
            "sender": {"id": "igsid-3"}, "timestamp": 3,
            "message": {"mid": "m.ig3", "text": "Yes", "quick_reply": {"payload": "YES_PAYLOAD"}},
        }]}],
    })
    assert qr_events[0]["message_type"] == "INTERACTIVE_REPLY"
    assert qr_events[0]["payload"] == {"kind": "quick_reply", "id": "YES_PAYLOAD", "title": "Yes"}

    pb_events = adapter.parse_inbound({
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [{
            "sender": {"id": "igsid-4"}, "timestamp": 4,
            "postback": {"title": "Get Started", "payload": "GET_STARTED"},
        }]}],
    })
    assert pb_events[0]["message_type"] == "INTERACTIVE_REPLY"
    assert pb_events[0]["payload"] == {"kind": "postback", "id": "GET_STARTED", "title": "Get Started"}

    reaction_events = adapter.parse_inbound({
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [
            {"sender": {"id": "igsid-5"}, "reaction": {"mid": "m.ig5", "emoji": "❤", "action": "react"}}
        ]}],
    })
    assert reaction_events[0]["kind"] == "reaction"
    assert reaction_events[0]["emoji"] == "❤"


def test_ig_document_attachment_still_falls_through_to_messenger_type_map():
    """Instagram never SENDS a file attachment (capability table) but an
    inbound `file` type is not one of the IG-only kinds this slice models -
    it still resolves through the inherited Messenger attachment map, not a
    story/share placeholder."""
    from modules.omnichannel.adapters.instagram import InstagramAdapter

    events = InstagramAdapter().parse_inbound({
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [{
            "sender": {"id": "igsid-doc-1"}, "timestamp": 1,
            "message": {"mid": "m.igdoc1", "attachments": [{"type": "file", "payload": {"url": "https://x/y.pdf"}}]},
        }]}],
    })
    assert events[0]["message_type"] == "DOCUMENT"


def test_ig_echo_produces_no_event():
    from modules.omnichannel.adapters.instagram import InstagramAdapter

    payload = {
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [{
            "sender": {"id": "ig-701"}, "timestamp": 1,
            "message": {"mid": "m.igecho", "text": "our own reply", "is_echo": True},
        }]}],
    }
    assert InstagramAdapter().parse_inbound(payload) == []


def test_full_pipeline_drops_ig_echo_never_creates_a_bubble(session_factory):
    _ig_channel(session_factory, external_account_id="ig-echo-1")
    payload = {
        "object": "instagram",
        "entry": [{"id": "ig-echo-1", "messaging": [{
            "sender": {"id": "ig-echo-1"}, "timestamp": 1,
            "message": {"mid": "m.igecho-1", "text": "sent by us", "is_echo": True},
        }]}],
    }
    counters = _process(session_factory, "meta", payload)
    assert counters == {"messages": 0, "statuses": 0, "skipped": 0}


# ── AC-CHN-41: IG-only kinds -> UNSUPPORTED placeholder, never dropped/raised
def test_ig_story_reply_stored_as_placeholder_with_story_reference():
    from modules.omnichannel.adapters.instagram import InstagramAdapter

    events = InstagramAdapter().parse_inbound({
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [{
            "sender": {"id": "igsid-story-1"}, "timestamp": 1,
            "message": {
                "mid": "m.storyreply-1",
                "text": "Nice pic!",
                "reply_to": {"story": {"url": "https://cdninstagram.com/story.jpg", "id": "story-99"}},
            },
        }]}],
    })
    assert len(events) == 1
    ev = events[0]
    assert ev["message_type"] == "UNSUPPORTED"
    assert ev["original_type"] == "story_reply"
    assert ev["body"] == "Nice pic!"
    assert ev["payload"] == {"kind": "story_reply", "storyId": "story-99", "storyUrl": "https://cdninstagram.com/story.jpg"}


def test_ig_story_mention_stored_as_placeholder_with_permalink():
    from modules.omnichannel.adapters.instagram import InstagramAdapter

    events = InstagramAdapter().parse_inbound({
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [{
            "sender": {"id": "igsid-mention-1"}, "timestamp": 1,
            "message": {
                "mid": "m.mention-1",
                "attachments": [{"type": "story_mention", "payload": {"url": "https://cdninstagram.com/mention.jpg"}}],
            },
        }]}],
    })
    assert len(events) == 1
    ev = events[0]
    assert ev["message_type"] == "UNSUPPORTED"
    assert ev["original_type"] == "story_mention"
    assert ev["payload"] == {"kind": "story_mention", "url": "https://cdninstagram.com/mention.jpg"}


def test_ig_shared_post_stored_as_placeholder_with_permalink():
    from modules.omnichannel.adapters.instagram import InstagramAdapter

    events = InstagramAdapter().parse_inbound({
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [{
            "sender": {"id": "igsid-share-1"}, "timestamp": 1,
            "message": {
                "mid": "m.share-1",
                "attachments": [{"type": "share", "payload": {"url": "https://instagram.com/p/abc123/"}}],
            },
        }]}],
    })
    assert len(events) == 1
    ev = events[0]
    assert ev["message_type"] == "UNSUPPORTED"
    assert ev["original_type"] == "share"
    assert ev["payload"] == {"kind": "share", "url": "https://instagram.com/p/abc123/"}


def test_ig_unsend_is_deleted_stored_as_placeholder():
    from modules.omnichannel.adapters.instagram import InstagramAdapter

    events = InstagramAdapter().parse_inbound({
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [{
            "sender": {"id": "igsid-unsend-1"}, "timestamp": 1,
            "message": {"mid": "m.unsend-1", "is_deleted": True},
        }]}],
    })
    assert len(events) == 1
    ev = events[0]
    assert ev["message_type"] == "UNSUPPORTED"
    assert ev["original_type"] == "unsend"
    assert ev["payload"] == {"kind": "unsend"}


def test_ig_is_unsupported_flag_stored_as_placeholder():
    from modules.omnichannel.adapters.instagram import InstagramAdapter

    events = InstagramAdapter().parse_inbound({
        "object": "instagram",
        "entry": [{"id": "ig-701", "messaging": [{
            "sender": {"id": "igsid-unsupported-1"}, "timestamp": 1,
            "message": {"mid": "m.unsupported-1", "is_unsupported": True},
        }]}],
    })
    assert len(events) == 1
    ev = events[0]
    assert ev["message_type"] == "UNSUPPORTED"
    assert ev["original_type"] == "is_unsupported"
    assert ev["payload"] == {"kind": "unsupported"}


@pytest.mark.parametrize(
    "message",
    [
        {"mid": "m.p1", "is_deleted": True},
        {"mid": "m.p2", "is_unsupported": True},
        {"mid": "m.p3", "text": "hey", "reply_to": {"story": {"id": "s1", "url": "https://x/s1.jpg"}}},
        {"mid": "m.p4", "attachments": [{"type": "story_mention", "payload": {"url": "https://x/m1.jpg"}}]},
        {"mid": "m.p5", "attachments": [{"type": "share", "payload": {"url": "https://x/share1"}}]},
    ],
)
def test_ig_only_kinds_never_raise_and_never_dropped_through_full_pipeline(session_factory, message):
    """AC-CHN-41: "never dropped and never crashing the pipeline" - runs each
    IG-only shape through `InboundService.process_payload` end to end (not
    just the parser) and asserts a row landed."""
    _ig_channel(session_factory, external_account_id="ig-placeholder-pipe")
    payload = {
        "object": "instagram",
        "entry": [{"id": "ig-placeholder-pipe", "messaging": [
            {"sender": {"id": f"igsid-{message['mid']}"}, "timestamp": 1, "message": message}
        ]}],
    }
    counters = _process(session_factory, "meta", payload)
    assert counters["messages"] == 1

    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    row = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == message["mid"]).first()
    assert row is not None
    assert row.message_type == "UNSUPPORTED"
    assert row.payload_json is not None
    db.close()


# ── AC-CHN-42: Instagram capabilities (independent policy/capability row) ──
def test_ig_capabilities_row_is_independent_of_messenger():
    from modules.omnichannel.services.messaging_policy import CAPABILITIES, POLICIES, assert_kind_supported

    ig_caps = CAPABILITIES["INSTAGRAM"]
    fb_caps = CAPABILITIES["FACEBOOK"]
    assert ig_caps.channel_type == "INSTAGRAM"
    # Diverges from Messenger on document only (capability table §5.5).
    assert ig_caps.document is False and fb_caps.document is True
    assert POLICIES["INSTAGRAM"].window_hours == 24
    assert POLICIES["INSTAGRAM"].human_agent_hours == 168
    assert POLICIES["INSTAGRAM"].reengage_mode == "human_agent"

    # Sendable: TEXT/IMAGE/VIDEO/AUDIO/quick-reply buttons.
    for kind, sub_kind in (("TEXT", None), ("IMAGE", None), ("VIDEO", None), ("AUDIO", None), ("INTERACTIVE", "buttons")):
        assert_kind_supported("INSTAGRAM", kind, sub_kind=sub_kind)  # no raise

    # Not sendable: document, template, list, location, contacts, outbound reaction.
    from modules.omnichannel.services.messaging_policy import PolicyRejected

    for kind, sub_kind in (
        ("DOCUMENT", None), ("TEMPLATE", None), ("INTERACTIVE", "list"),
        ("LOCATION", None), ("CONTACTS", None), ("REACTION", None),
    ):
        with pytest.raises(PolicyRejected):
            assert_kind_supported("INSTAGRAM", kind, sub_kind=sub_kind)


# ── AC-CHN-43: IGSID stitch, no phone, no cross-channel auto-merge ──────────
def test_ig_inbound_creates_new_contact_no_phone(session_factory):
    _ig_channel(session_factory, external_account_id="ig-new-1")
    counters = _process(session_factory, "meta", _ig_payload(ig_id="ig-new-1", igsid="igsid-new-1", mid="m.ignew-1"))
    assert counters["messages"] == 1

    from modules.omnichannel.models import Contact, ContactChannelIdentity, ConversationEvent

    db = session_factory()
    identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.external_user_id == "igsid-new-1").first()
    assert identity is not None
    contact = db.query(Contact).filter(Contact.id == identity.contact_id).first()
    assert contact.phone is None
    assert contact.phone_digits is None
    assert contact.lifecycle_status_id is not None
    opened = db.query(ConversationEvent).filter(
        ConversationEvent.contact_id == contact.id, ConversationEvent.event_type == "opened"
    ).first()
    assert opened is not None
    db.close()


def test_ig_inbound_second_message_reuses_same_contact(session_factory):
    _ig_channel(session_factory, external_account_id="ig-reuse-1")
    _process(session_factory, "meta", _ig_payload(ig_id="ig-reuse-1", igsid="igsid-reuse-1", mid="m.igr1", text="first"))
    _process(session_factory, "meta", _ig_payload(ig_id="ig-reuse-1", igsid="igsid-reuse-1", mid="m.igr2", text="second"))

    from modules.omnichannel.models import ContactChannelIdentity, ConversationMessage

    db = session_factory()
    identities = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.external_user_id == "igsid-reuse-1").all()
    assert len(identities) == 1
    msgs = db.query(ConversationMessage).filter(ConversationMessage.contact_id == identities[0].contact_id).all()
    assert len(msgs) == 2
    db.close()


def test_same_id_on_linked_facebook_page_and_instagram_account_is_a_separate_contact(session_factory):
    """AC-CHN-43: "the same person messaging the linked Facebook Page creates
    a SEPARATE contact - this slice performs NO cross-channel auto-merge."""
    _fb_channel(session_factory, external_account_id="pg-shared-link")
    _ig_channel(session_factory, external_account_id="ig-shared-link")
    _process(session_factory, "meta", {
        "object": "page",
        "entry": [{"id": "pg-shared-link", "messaging": [{
            "sender": {"id": "shared-external-id"}, "timestamp": 1,
            "message": {"mid": "m.fb-shared", "text": "hi from Messenger"},
        }]}],
    })
    _process(session_factory, "meta", {
        "object": "instagram",
        "entry": [{"id": "ig-shared-link", "messaging": [{
            "sender": {"id": "shared-external-id"}, "timestamp": 1,
            "message": {"mid": "m.ig-shared", "text": "hi from Instagram"},
        }]}],
    })

    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    identities = db.query(ContactChannelIdentity).filter(
        ContactChannelIdentity.external_user_id == "shared-external-id"
    ).all()
    assert len(identities) == 2
    assert identities[0].contact_id != identities[1].contact_id
    db.close()


def test_ig_channel_isolated_from_tenant_a_when_owned_by_tenant_b(client, session_factory):
    _ig_channel(session_factory, tenant_id=DEFAULT_TENANT_ID, external_account_id="ig-tenant-a")

    _other_tenant_auth(client, session_factory, slug="other-chn-ig")
    from app.models import Tenant

    db = session_factory()
    tenant_b = db.query(Tenant).filter(Tenant.slug == "other-chn-ig").first()
    tenant_b_id = tenant_b.id
    db.close()
    _ig_channel(session_factory, tenant_id=tenant_b_id, external_account_id="ig-tenant-b")

    _process(session_factory, "meta", _ig_payload(ig_id="ig-tenant-b", igsid="igsid-cross-1", mid="m.igcross-1"))

    from modules.omnichannel.models import Contact, ContactChannelIdentity

    db = session_factory()
    identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.external_user_id == "igsid-cross-1").first()
    assert identity is not None
    assert identity.tenant_id == tenant_b_id
    contact = db.query(Contact).filter(Contact.id == identity.contact_id).first()
    assert contact.tenant_id == tenant_b_id
    leaked = db.query(Contact).filter(
        Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone.is_(None),
    ).join(ContactChannelIdentity, ContactChannelIdentity.contact_id == Contact.id).filter(
        ContactChannelIdentity.external_user_id == "igsid-cross-1"
    ).first()
    assert leaked is None
    db.close()


# ── AC-CHN-44: connect flow - only page-linked IG accounts offered ──────────
def test_ig_meta_pages_only_offers_page_linked_instagram_accounts(client):
    h = _auth(client)
    res = client.post(
        "/omnichannel/onboarding/meta/pages", headers=h,
        json={"channelType": "INSTAGRAM", "code": "code-ig-44"},
    )
    assert res.status_code == 200
    pages = res.json()["pages"]
    ids = {p["id"] for p in pages}
    # pg-703 (`_DEV_PAGES` in adapters/messenger.py) has no linked Instagram
    # account (D-A7-14/44) - never offered for the Instagram product.
    assert "pg-703" not in ids
    assert ids == {"pg-701", "pg-702"}
    for p in pages:
        assert p["igAccountId"]
        assert p["igUsername"]


# ── AC-CHN-45: external_account_id pins inbound routing AND outbound addressing
def test_ig_external_account_id_pins_inbound_routing_and_outbound_addressing(client, session_factory):
    h = _auth(client)
    ws_res = client.get("/omnichannel/workspaces", headers=h)
    ws_id = next(w["id"] for w in ws_res.json()["data"] if w["isDefault"])

    pages = client.post(
        "/omnichannel/onboarding/meta/pages", headers=h,
        json={"channelType": "INSTAGRAM", "code": "code-ig-45"},
    ).json()
    connect = client.post(
        "/omnichannel/onboarding/meta/connect", headers=h,
        json={
            "sessionId": pages["sessionId"], "workspaceId": ws_id, "channelType": "INSTAGRAM",
            "pageId": "pg-701", "igAccountId": "ig-701",
        },
    )
    assert connect.status_code == 201
    channel_id = connect.json()["id"]
    assert connect.json()["externalAccountId"] == "ig-701"

    # Inbound routing: a webhook whose entry[].id matches the STORED
    # external_account_id resolves to THIS channel.
    counters = _process(session_factory, "meta", _ig_payload(ig_id="ig-701", igsid="igsid-45-1", mid="m.ig45-1"))
    assert counters["messages"] == 1

    from modules.omnichannel.models import Channel, ConversationMessage

    db = session_factory()
    msg = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == "m.ig45-1").first()
    assert msg.channel_id == channel_id
    channel = db.query(Channel).filter(Channel.id == channel_id).first()

    # Outbound addressing: `channel_addressing.sender_ref` resolves to the
    # SAME `external_account_id` the connect flow stored (never
    # `phone_number_id`, which an Instagram channel never has).
    from modules.omnichannel.services import channel_addressing
    from modules.omnichannel.repositories.contact_repository import ContactRepository

    assert channel_addressing.sender_ref(channel) == "ig-701"

    identity = ContactRepository(db).find_identity(channel_id, "igsid-45-1")
    contact = ContactRepository(db).get_by_id(identity.contact_id, DEFAULT_TENANT_ID)
    assert channel_addressing.recipient_ref(db, channel, contact) == "igsid-45-1"
    db.close()


def test_ig_connect_with_mismatching_ig_account_id_is_refused_and_creates_no_channel(
    client, session_factory
):
    """Security review round 1, blocker 1 - `igAccountId` must be validated
    against the PAGE's own linked account, never trusted as-is: it becomes
    the unauthenticated webhook routing key (`InboundService._resolve_
    channel`). A client claiming an Instagram account it does not administer
    through THIS page must be refused, not stamped onto
    `external_account_id`."""
    h = _auth(client)
    ws_res = client.get("/omnichannel/workspaces", headers=h)
    ws_id = next(w["id"] for w in ws_res.json()["data"] if w["isDefault"])

    pages = client.post(
        "/omnichannel/onboarding/meta/pages", headers=h,
        json={"channelType": "INSTAGRAM", "code": "code-ig-mismatch"},
    ).json()
    connect = client.post(
        "/omnichannel/onboarding/meta/connect", headers=h,
        json={
            "sessionId": pages["sessionId"], "workspaceId": ws_id, "channelType": "INSTAGRAM",
            # pg-701 is linked to ig-701 (see `_DEV_PAGES`) - claiming
            # ig-702 (pg-702's own linked account) must be refused.
            "pageId": "pg-701", "igAccountId": "ig-702",
        },
    )
    assert connect.status_code == 404

    from modules.omnichannel.models import Channel

    db = session_factory()
    leaked = db.query(Channel).filter(Channel.external_account_id == "ig-702").first()
    assert leaked is None
    also_absent = db.query(Channel).filter(Channel.external_account_id == "ig-701").first()
    assert also_absent is None
    db.close()


def test_ig_connect_without_ig_account_id_uses_the_pages_linked_account(client, session_factory):
    """A connect that omits `igAccountId` (the field is optional on the
    wire) still succeeds, using the page's own server-derived account."""
    h = _auth(client)
    ws_res = client.get("/omnichannel/workspaces", headers=h)
    ws_id = next(w["id"] for w in ws_res.json()["data"] if w["isDefault"])

    pages = client.post(
        "/omnichannel/onboarding/meta/pages", headers=h,
        json={"channelType": "INSTAGRAM", "code": "code-ig-noid"},
    ).json()
    connect = client.post(
        "/omnichannel/onboarding/meta/connect", headers=h,
        json={
            "sessionId": pages["sessionId"], "workspaceId": ws_id, "channelType": "INSTAGRAM",
            "pageId": "pg-702",
        },
    )
    assert connect.status_code == 201
    assert connect.json()["externalAccountId"] == "ig-702"


def test_ig_test_connection_pings_external_account_id(session_factory):
    """AC-CHN-37/45 (Instagram side): `test_connection` addresses the IG
    account id, never a phone number id."""
    cid = _ig_channel(session_factory, external_account_id="ig-routing-check")
    db = session_factory()
    from modules.omnichannel.services.channel_service import ChannelService

    result = ChannelService(db).test_connection(cid, DEFAULT_TENANT_ID)
    db.close()
    assert result.ok is True  # dev-safe stub


# ── Dev seed: chn-demo-ig gets two seeded threads, one open one expired ─────
def test_dev_seed_creates_chn_demo_ig_and_two_threads(session_factory):
    from modules.omnichannel import bootstrap
    from modules.omnichannel.models import Channel, Contact, ContactChannelIdentity

    db = session_factory()
    bootstrap.seed_demo_conversations(db, DEFAULT_TENANT_ID)

    channel = db.query(Channel).filter(Channel.id == "chn-demo-ig", Channel.tenant_id == DEFAULT_TENANT_ID).first()
    assert channel is not None
    assert channel.channel_type == "INSTAGRAM"
    assert channel.external_account_id == "ig-702"

    contacts = {
        c.id: c
        for c in db.query(Contact).filter(Contact.id.in_(["cnt-ig-001", "cnt-ig-002"])).all()
    }
    assert set(contacts) == {"cnt-ig-001", "cnt-ig-002"}
    for cid, contact in contacts.items():
        assert contact.phone is None
        identity = (
            db.query(ContactChannelIdentity)
            .filter(ContactChannelIdentity.contact_id == cid)
            .first()
        )
        assert identity is not None
        assert identity.external_user_id.startswith("igsid-demo-")

    now = datetime.now(timezone.utc)
    open_identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == "cnt-ig-001").first()
    assert open_identity.window_expires_at > now
    assert open_identity.human_agent_expires_at > now

    expired_identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == "cnt-ig-002").first()
    assert expired_identity.window_expires_at < now
    assert expired_identity.human_agent_expires_at < now
    db.close()

    # Idempotent re-run does not duplicate.
    db = session_factory()
    bootstrap.seed_demo_conversations(db, DEFAULT_TENANT_ID)
    assert db.query(Contact).filter(Contact.id == "cnt-ig-001").count() == 1
    assert db.query(Channel).filter(Channel.id == "chn-demo-ig", Channel.tenant_id == DEFAULT_TENANT_ID).count() == 1
    db.close()


def test_dev_seed_ig_thread_windows_drive_authorize_open_vs_locked(session_factory):
    """The seeded windows are not just cosmetic - `messaging_policy.authorize`
    actually allows the open thread and refuses the expired one."""
    from modules.omnichannel import bootstrap
    from modules.omnichannel.models import Channel, ContactChannelIdentity
    from modules.omnichannel.repositories.contact_repository import ContactRepository
    from modules.omnichannel.services import messaging_policy

    db = session_factory()
    bootstrap.seed_demo_conversations(db, DEFAULT_TENANT_ID)
    channel = db.query(Channel).filter(Channel.id == "chn-demo-ig", Channel.tenant_id == DEFAULT_TENANT_ID).first()
    repo = ContactRepository(db)

    open_identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == "cnt-ig-001").first()
    open_contact = repo.get_by_id(open_identity.contact_id, DEFAULT_TENANT_ID)
    decision = messaging_policy.authorize(db, open_contact, channel, kind="TEXT", actor_is_human=False)
    assert decision.messaging_type == messaging_policy.MESSAGING_TYPE_RESPONSE

    expired_identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == "cnt-ig-002").first()
    expired_contact = repo.get_by_id(expired_identity.contact_id, DEFAULT_TENANT_ID)
    for actor_is_human in (True, False):
        with pytest.raises(messaging_policy.PolicyRejected) as exc:
            messaging_policy.authorize(db, expired_contact, channel, kind="TEXT", actor_is_human=actor_is_human)
        assert exc.value.code == "messaging_window_closed"
    db.close()
