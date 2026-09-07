"""Plan 33 (roadmap A6), slice S3 - channel identities + message history
(AC-MIG-30..38).

Reuses S2's fixtures (`_make_connection`, `_make_job`, `_default_workspace`,
`_stub_client`) rather than duplicating them - the cross-test-helper-import
pattern this suite already uses elsewhere (`test_activity_trace.py` importing
from `test_omnichannel_webhooks.py`, etc.).
"""
from datetime import datetime, timezone

import httpx

from app.models import DEFAULT_TENANT_ID

from modules.omnichannel.models import (
    Channel,
    Contact,
    ContactChannelIdentity,
    ConversationMessage,
    MigrationRef,
)
from modules.omnichannel.respondio.channel_map import derive_external_user_id
from modules.omnichannel.respondio.shapes import MessageItem
from modules.omnichannel.services.migration_service import (
    MIGRATION_JOB_TYPE,
    run_migration_job,
)
from modules.omnichannel.services.migration_writer import (
    _map_delivery_status,
    _map_message_content,
    resolve_message_timestamps,
)

from tests.test_omnichannel_respondio_migration_jobs import (
    _default_workspace,
    _make_connection,
    _stub_client,
)


# ═══════════════════════════════════════════════════════════════════════════
# Pure helpers - timestamp inference, message-type map, delivery-status map
# (AC-MIG-34/35/36) - no DB, no stubbed transport needed.
# ═══════════════════════════════════════════════════════════════════════════


def _item(message_id, traffic="incoming", message=None, status=None, sender=None):
    return MessageItem(
        messageId=message_id,
        traffic=traffic,
        message=message or {"type": "text", "text": "x"},
        status=status,
        sender=sender,
    )


def test_timestamp_explicit_branch_uses_min_of_status_timestamps():
    fallback = datetime(2020, 1, 1, tzinfo=timezone.utc)
    item = _item(1, status=[{"value": "delivered", "timestamp": 5000}, {"value": "sent", "timestamp": 3000}])
    (dt, inferred), = resolve_message_timestamps([item], fallback)
    assert inferred is False
    assert dt == datetime.fromtimestamp(3000, tz=timezone.utc)


def test_timestamp_interpolated_branch_between_bracketing_anchors():
    fallback = datetime(2020, 1, 1, tzinfo=timezone.utc)
    items = [
        _item(1, status=[{"value": "sent", "timestamp": 1000}]),
        _item(2),  # no status - must interpolate
        _item(3, status=[{"value": "sent", "timestamp": 3000}]),
    ]
    results = resolve_message_timestamps(items, fallback)
    assert results[0][1] is False
    assert results[2][1] is False
    mid_dt, mid_inferred = results[1]
    assert mid_inferred is True
    assert mid_dt == datetime.fromtimestamp(2000, tz=timezone.utc)
    # Monotonic in messageId order (AC-MIG-34 - never reorders a conversation).
    assert results[0][0] < results[1][0] < results[2][0]


def test_timestamp_fallback_branch_when_no_bracket_exists():
    fallback = datetime(2020, 1, 1, tzinfo=timezone.utc)
    # No status anywhere in the contact's history - every message falls back.
    items = [_item(1), _item(2)]
    results = resolve_message_timestamps(items, fallback)
    assert results[0] == (fallback, True)
    assert results[1] == (fallback, True)


def test_timestamp_one_sided_anchor_is_not_a_bracket_falls_back():
    """A left-only OR right-only anchor is not "bracketing" (AC-MIG-34's own
    wording) - must fall to branch 3, never a one-sided extrapolation."""
    fallback = datetime(2020, 1, 1, tzinfo=timezone.utc)
    items = [_item(1), _item(2, status=[{"value": "sent", "timestamp": 5000}])]
    results = resolve_message_timestamps(items, fallback)
    assert results[0] == (fallback, True)  # no anchor BEFORE message 1
    assert results[1][1] is False


def test_message_type_map_every_branch_and_unmapped():
    cases = [
        ({"type": "text", "text": "hi"}, ("TEXT", "hi", None)),
        ({"type": "attachment", "attachment": {"type": "image", "url": "http://x/img.jpg"}}, ("IMAGE", None, None)),
        ({"type": "attachment", "attachment": {"type": "video", "url": "http://x/v.mp4"}}, ("VIDEO", None, None)),
        ({"type": "attachment", "attachment": {"type": "audio", "url": "http://x/a.mp3"}}, ("AUDIO", None, None)),
        ({"type": "attachment", "attachment": {"type": "file", "url": "http://x/f.pdf"}}, ("DOCUMENT", None, None)),
        ({"type": "quick_reply", "title": "Pick one", "replies": ["A", "B"]}, ("INTERACTIVE", "Pick one", None)),
        (
            {"type": "whatsapp_template", "template": {"name": "welcome", "languageCode": "en",
                                                         "components": [{"type": "BODY", "text": "Hello there"}]}},
            ("TEXT", "Hello there", None),
        ),
        ({"type": "email", "text": "body", "subject": "Hi"}, ("TEXT", "body", None)),
        ({"type": "custom_payload", "foo": "bar"}, ("TEXT", None, None)),
        ({"type": "some_future_type"}, ("TEXT", None, None)),
    ]
    for raw_message, (expected_type, expected_body, _unused) in cases:
        item = _item(1, message=raw_message)
        message_type, body, payload_extra, pending_media = _map_message_content(item)
        assert message_type == expected_type, raw_message
        assert body == expected_body, raw_message

    unmapped_item = _item(1, message={"type": "some_future_type"})
    _, _, payload_extra, _ = _map_message_content(unmapped_item)
    assert payload_extra == {"migration": {"unmappedType": "some_future_type"}}

    custom_item = _item(1, message={"type": "custom_payload", "foo": "bar", "baz": 1})
    _, _, payload_extra, _ = _map_message_content(custom_item)
    assert payload_extra == {"custom": {"foo": "bar", "baz": 1}}

    attachment_item = _item(1, message={"type": "attachment", "attachment": {"type": "image", "url": "http://x/i.jpg"}})
    _, _, _, pending_media = _map_message_content(attachment_item)
    assert pending_media == {"url": "http://x/i.jpg", "attachmentType": "image"}

    quick_reply_item = _item(1, message={"type": "quick_reply", "title": "Pick", "replies": ["A", "B"]})
    _, _, payload_extra, _ = _map_message_content(quick_reply_item)
    assert payload_extra == {"buttons": ["A", "B"]}


def test_delivery_status_map_last_element_and_no_status_is_null():
    assert _map_delivery_status(_item(1, status=None)) is None
    assert _map_delivery_status(_item(1, status=[{"value": "pending", "timestamp": 1}])) == "QUEUED"
    assert _map_delivery_status(_item(1, status=[{"value": "sent", "timestamp": 1}])) == "SENT"
    assert _map_delivery_status(_item(1, status=[{"value": "delivered", "timestamp": 1}])) == "DELIVERED"
    assert _map_delivery_status(_item(1, status=[{"value": "read", "timestamp": 1}])) == "READ"
    assert _map_delivery_status(_item(1, status=[{"value": "failed", "timestamp": 1}])) == "FAILED"
    # LAST element wins, not a max-by-timestamp scan (§5.4's own wording).
    out_of_order = _item(1, status=[{"value": "read", "timestamp": 500}, {"value": "sent", "timestamp": 100}])
    assert _map_delivery_status(out_of_order) == "SENT"


def test_identity_deriver_whatsapp_prefers_meta_then_contact_phone_then_none():
    assert derive_external_user_id("WHATSAPP", {"phone": "+1 (555) 000-1111"}, None) == "15550001111"
    assert derive_external_user_id("WHATSAPP", None, "+15550002222") == "15550002222"
    assert derive_external_user_id("WHATSAPP", {}, None) is None
    assert derive_external_user_id("FACEBOOK", {"phone": "1"}, None) is None  # no deriver row yet (A7a)


# ═══════════════════════════════════════════════════════════════════════════
# DB-backed handler tests (identities + messages phases end to end)
# ═══════════════════════════════════════════════════════════════════════════


def _make_channel(db, tenant_id, workspace_id, *, channel_type="WHATSAPP", name="Test WA"):
    channel = Channel(
        tenant_id=tenant_id, workspace_id=workspace_id, channel_type=channel_type, name=name,
        is_active=True, is_trashed=False,
    )
    db.add(channel)
    db.flush()
    return channel


def _make_full_job(db, tenant_id, *, connection_id, workspace_id, mode="run", cursor=None, result=None,
                    channel_map=None, user_map=None):
    """Like S2's `_make_job` but with `contactsOnly=False` so the identities
    and messages phases actually run - a real S3 job."""
    from app.models.background_job import JOB_RUNNING, BackgroundJob

    job = BackgroundJob(
        tenant_id=tenant_id, type=MIGRATION_JOB_TYPE, status=JOB_RUNNING,
        payload_json={
            "mode": mode, "source": "api", "connectionId": connection_id, "workspaceId": workspace_id,
            "channelMap": channel_map or [], "userMap": user_map or [], "teamMap": [], "lifecycleMap": [],
            "contactsOnly": False, "mappingHash": "test",
        },
        cursor_json=cursor,
        result_json=result,
    )
    db.add(job)
    db.commit()
    return job


def _pages_handler_full(contact_pages, custom_fields=None, channels_by_contact=None, messages_by_contact=None):
    """A stubbed transport that answers `/contact/list`, `/space/custom_field`,
    `/contact/{id}` (single-object), `/contact/{id}/channels` and
    `/contact/{id}/message/list` (paginated) all from static dicts."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        path = request.url.path
        if path.endswith("/space/custom_field"):
            return httpx.Response(200, json={"items": custom_fields or [], "pagination": {"next": None}})
        if path.endswith("/contact/list"):
            cursor = request.url.params.get("cursorId")
            items, next_cursor = contact_pages[cursor]
            return httpx.Response(200, json={"items": items, "pagination": {"next": next_cursor}})
        if path.endswith("/channels"):
            identifier = path.split("/contact/")[1].split("/channels")[0]
            rows = (channels_by_contact or {}).get(identifier, [])
            return httpx.Response(200, json={"items": rows, "pagination": {"next": None}})
        if path.endswith("/message/list"):
            identifier = path.split("/contact/")[1].split("/message/list")[0]
            cursor = request.url.params.get("cursorId")
            pages = (messages_by_contact or {}).get(identifier) or {None: ([], None)}
            items, next_cursor = pages[cursor]
            return httpx.Response(200, json={"items": items, "pagination": {"next": next_cursor}})
        # bare GET /contact/{identifier} (single object, not an envelope)
        identifier = path.split("/contact/")[1]
        contact_row = (contact_pages.get(None) or ([], None))[0]
        match = next((c for c in contact_row if f"id:{c['id']}" == identifier), None)
        return httpx.Response(200, json=match or {"id": identifier})

    handler.calls = calls
    return handler


def test_identity_written_for_mapped_whatsapp_channel(session_factory, monkeypatch):
    """AC-MIG-30: a mapped source channel derives `external_user_id` from the
    contact's phone (WhatsApp deriver); an unmappable meta -> skipped and
    reported, never a fabricated id."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()

    # Deliberately NO `phone` on the source contact - proves the identity
    # write is genuinely underivable for channel 502 (`meta: {}`), rather than
    # silently succeeding off the contact's own phone fallback (which channel
    # 501 exercises instead, via its OWN meta).
    contact_row = {"id": 910001, "firstName": "Iden", "lastName": "Tity", "email": "iden@example.com"}
    channels_by_contact = {
        "id:910001": [
            {"id": 501, "name": "WA Main", "source": "whatsapp", "meta": {"phone": "+15559990000"}},
            {"id": 502, "name": "Weird", "source": "whatsapp", "meta": {}},
        ]
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, channels_by_contact=channels_by_contact)
    _stub_client(monkeypatch, handler)

    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        channel_map=[{"sourceChannelId": "501", "targetChannelId": wa_channel.id},
                     {"sourceChannelId": "502", "targetChannelId": wa_channel.id}],
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.email == "iden@example.com").first()
    assert contact is not None
    identities = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == contact.id).all()
    assert len(identities) == 1
    assert identities[0].external_user_id == "15559990000"
    assert identities[0].channel_id == wa_channel.id

    failures = job.result_json["failures"]["rows"]
    assert any(f["entity"] == "identities" and f["action"] == "skipped" for f in failures)
    report = job.result_json["report"]["entities"]["identities"]
    assert report["fetched"] == 2
    assert report["wouldCreate"] == 1
    assert report["wouldSkip"] == 1
    db.close()


def test_identity_composite_ref_key_no_cross_contact_collision(session_factory, monkeypatch):
    """The migration_refs key for an identity is `<contactExternalId>:<channel
    row id>` - two DIFFERENT contacts reporting the SAME ContactChannel.id
    (plausible per the vendor's own shape, see shapes.py docstring) must both
    get their own identity row, never silently skip the second."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()

    contact_a = {"id": 920001, "firstName": "A", "phone": "+15550001"}
    contact_b = {"id": 920002, "firstName": "B", "phone": "+15550002"}
    # BOTH contacts report a ContactChannel with the SAME `id` (501).
    channels_by_contact = {
        "id:920001": [{"id": 501, "name": "WA", "source": "whatsapp", "meta": {"phone": "+15550001"}}],
        "id:920002": [{"id": 501, "name": "WA", "source": "whatsapp", "meta": {"phone": "+15550002"}}],
    }
    handler = _pages_handler_full(
        {None: ([contact_a, contact_b], None)}, channels_by_contact=channels_by_contact,
    )
    _stub_client(monkeypatch, handler)

    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        channel_map=[{"sourceChannelId": "501", "targetChannelId": wa_channel.id}],
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    identities = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.channel_id == wa_channel.id).all()
    assert len(identities) == 2, "both contacts must get their own identity row"
    assert {i.external_user_id for i in identities} == {"15550001", "15550002"}
    refs = db.query(MigrationRef).filter(MigrationRef.entity_type == "identity").all()
    assert len(refs) == 2
    db.close()


def test_rerun_identities_and_messages_creates_no_duplicates(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()

    contact_row = {"id": 930001, "firstName": "Re", "lastName": "Run", "phone": "+15551234567"}
    channels_by_contact = {
        "id:930001": [{"id": 601, "name": "WA", "source": "whatsapp", "meta": {"phone": "+15551234567"}}],
    }
    messages_by_contact = {
        "id:930001": {
            None: (
                [
                    {"messageId": 1, "traffic": "incoming", "channelId": 601,
                     "message": {"type": "text", "text": "hello"}},
                    {"messageId": 2, "traffic": "outgoing", "channelId": 601,
                     "message": {"type": "text", "text": "hi back"},
                     "status": [{"value": "sent", "timestamp": 1700000000}]},
                ],
                None,
            )
        }
    }
    handler = _pages_handler_full(
        {None: ([contact_row], None)}, channels_by_contact=channels_by_contact,
        messages_by_contact=messages_by_contact,
    )
    _stub_client(monkeypatch, handler)

    channel_map = [{"sourceChannelId": "601", "targetChannelId": wa_channel.id}]

    job1 = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run", channel_map=channel_map)
    run_migration_job(db, job1)
    db.refresh(job1)
    assert job1.status == "done", job1.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15551234567").first()
    msgs_after_1 = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).all()
    assert len(msgs_after_1) == 2
    identities_after_1 = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == contact.id).count()
    assert identities_after_1 == 1

    job2 = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run", channel_map=channel_map)
    run_migration_job(db, job2)
    db.refresh(job2)
    assert job2.status == "done", job2.error

    msgs_after_2 = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).count()
    assert msgs_after_2 == 2, "a re-run must not duplicate migrated messages"
    identities_after_2 = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == contact.id).count()
    assert identities_after_2 == 1, "a re-run must not duplicate the identity"
    db.close()


def test_sender_mapping_user_mapped_and_every_other_source_records_sender_source(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()

    from app.models.user import User

    agent_user = db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID).first()
    assert agent_user is not None

    contact_row = {"id": 940001, "firstName": "Sender", "lastName": "Test", "phone": "+15559998888"}
    sources = ["user", "ai_agent", "workflow", "api", "echo", "broadcast"]
    messages = [
        {"messageId": i + 1, "traffic": "outgoing", "channelId": 701,
         "message": {"type": "text", "text": f"msg {src}"},
         "sender": {"source": src, "userId": 4242 if src == "user" else None}}
        for i, src in enumerate(sources)
    ]
    # One incoming message too (sender_type CONTACT, no sender_id ever).
    messages.append({"messageId": 100, "traffic": "incoming", "channelId": 701,
                      "message": {"type": "text", "text": "inbound"}})

    messages_by_contact = {"id:940001": {None: (messages, None)}}
    handler = _pages_handler_full(
        {None: ([contact_row], None)}, messages_by_contact=messages_by_contact,
    )
    _stub_client(monkeypatch, handler)

    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        channel_map=[{"sourceChannelId": "701", "targetChannelId": wa_channel.id}],
        user_map=[{"sourceUserId": "4242", "targetUserId": agent_user.id}],
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15559998888").first()
    rows = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.contact_id == contact.id)
        .order_by(ConversationMessage.created_at.asc())
        .all()
    )
    by_body = {r.body: r for r in rows}

    user_row = by_body["msg user"]
    assert user_row.sender_type == "AGENT"
    assert user_row.sender_id == agent_user.id

    for src in ("ai_agent", "workflow", "api", "echo", "broadcast"):
        row = by_body[f"msg {src}"]
        assert row.sender_type == "AGENT"
        assert row.sender_id is None
        assert row.payload_json["migration"]["senderSource"] == src

    inbound_row = by_body["inbound"]
    assert inbound_row.sender_type == "CONTACT"
    assert inbound_row.sender_id is None
    db.close()


def test_sender_user_source_unmapped_user_id_records_sender_source_too(session_factory, monkeypatch):
    """`sender.source == "user"` but `userMap` does not resolve the id ->
    `sender_id` stays NULL and `senderSource` is still recorded (AC-MIG-32)."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()

    contact_row = {"id": 940101, "firstName": "Unmapped", "phone": "+15551110000"}
    messages_by_contact = {
        "id:940101": {None: ([
            {"messageId": 1, "traffic": "outgoing", "channelId": 701,
             "message": {"type": "text", "text": "hi"}, "sender": {"source": "user", "userId": 9999}},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)

    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        channel_map=[{"sourceChannelId": "701", "targetChannelId": wa_channel.id}],
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15551110000").first()
    row = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).first()
    assert row.sender_id is None
    assert row.payload_json["migration"]["senderSource"] == "user"
    db.close()


def test_message_never_writes_external_message_id_and_channel_less_when_unmapped(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 950001, "firstName": "No", "lastName": "Channel", "phone": "+15552223333"}
    # channelId 999 has NO entry in channelMap - channel-less history.
    messages_by_contact = {
        "id:950001": {None: ([{"messageId": 1, "traffic": "incoming", "channelId": 999,
                                "message": {"type": "text", "text": "hi"}}], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15552223333").first()
    row = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).first()
    assert row.external_message_id is None
    assert row.channel_id is None
    assert row.migrated_from == "respondio"
    db.close()


def test_per_contact_recompute_after_message_phase(session_factory, monkeypatch):
    """AC-MIG-37 - exactly one recompute; agent_last_read_at = last_message_at
    (never a wall of unread); csw_expires_at untouched."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 960001, "firstName": "Recompute", "phone": "+15554445555"}
    messages_by_contact = {
        "id:960001": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 801,
             "message": {"type": "text", "text": "in1"},
             "status": [{"value": "sent", "timestamp": 1700000000}]},
            {"messageId": 2, "traffic": "outgoing", "channelId": 801,
             "message": {"type": "text", "text": "out1"},
             "status": [{"value": "sent", "timestamp": 1700000500}]},
            {"messageId": 3, "traffic": "incoming", "channelId": 801,
             "message": {"type": "text", "text": "in2"},
             "status": [{"value": "sent", "timestamp": 1700001000}]},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15554445555").first()
    db.refresh(contact)
    from datetime import datetime as _dt, timezone as _tz

    assert contact.last_message_at == _dt.fromtimestamp(1700001000, tz=_tz.utc)
    assert contact.last_incoming_message_at == _dt.fromtimestamp(1700001000, tz=_tz.utc)
    assert contact.last_agent_message_at == _dt.fromtimestamp(1700000500, tz=_tz.utc)
    assert contact.agent_last_read_at == contact.last_message_at
    assert contact.csw_expires_at is None  # never touched by the migration
    db.close()


def test_dry_run_identities_and_messages_write_nothing_real_mode_control(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()

    contact_row = {"id": 970001, "firstName": "Dry", "lastName": "Three", "phone": "+15556667777"}
    channels_by_contact = {"id:970001": [{"id": 901, "name": "WA", "source": "whatsapp",
                                           "meta": {"phone": "+15556667777"}}]}
    messages_by_contact = {"id:970001": {None: ([
        {"messageId": 1, "traffic": "incoming", "channelId": 901, "message": {"type": "text", "text": "hi"}},
    ], None)}}
    handler = _pages_handler_full(
        {None: ([contact_row], None)}, channels_by_contact=channels_by_contact,
        messages_by_contact=messages_by_contact,
    )
    _stub_client(monkeypatch, handler)
    channel_map = [{"sourceChannelId": "901", "targetChannelId": wa_channel.id}]

    def _counts():
        return (
            db.query(ContactChannelIdentity).count(),
            db.query(ConversationMessage).filter(ConversationMessage.tenant_id == DEFAULT_TENANT_ID).count(),
            db.query(MigrationRef).filter(MigrationRef.entity_type.in_(["identity", "message"])).count(),
        )

    before = _counts()
    dry_job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="dry_run", channel_map=channel_map)
    run_migration_job(db, dry_job)
    db.refresh(dry_job)
    assert dry_job.status == "done", dry_job.error
    assert _counts() == before, "dry run must write zero identity/message rows (AC-MIG-27 extended to S3)"
    dry_report = dry_job.result_json["report"]["entities"]
    assert dry_report["identities"]["wouldCreate"] == 1
    assert dry_report["messages"]["wouldCreate"] == 1

    # Control: same data, mode=run, DOES persist.
    real_job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run", channel_map=channel_map)
    run_migration_job(db, real_job)
    db.refresh(real_job)
    assert real_job.status == "done", real_job.error
    after = _counts()
    assert after[0] == before[0] + 1
    assert after[1] == before[1] + 1
    assert after[2] == before[2] + 2
    db.close()


def test_no_realtime_publish_or_entity_event_during_identities_or_messages(session_factory, monkeypatch):
    """AC-MIG-33, extended to S3's two new phases (S2 pinned it for contacts
    only)."""
    calls = {"publish": 0, "emit": 0, "notify": 0}

    import modules.omnichannel.services.realtime as realtime_module
    import app.workflow_engine.entity_events as entity_events_module

    monkeypatch.setattr(realtime_module, "publish", lambda *a, **k: calls.__setitem__("publish", calls["publish"] + 1))
    monkeypatch.setattr(entity_events_module, "emit_entity_event", lambda *a, **k: calls.__setitem__("emit", calls["emit"] + 1))
    monkeypatch.setattr(entity_events_module, "notify_entity_event", lambda *a, **k: calls.__setitem__("notify", calls["notify"] + 1))

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()

    contact_row = {"id": 980001, "firstName": "Quiet", "lastName": "Two", "phone": "+15558889999"}
    channels_by_contact = {"id:980001": [{"id": 1001, "name": "WA", "source": "whatsapp",
                                           "meta": {"phone": "+15558889999"}}]}
    messages_by_contact = {"id:980001": {None: ([
        {"messageId": 1, "traffic": "incoming", "channelId": 1001, "message": {"type": "text", "text": "hi"}},
        {"messageId": 2, "traffic": "outgoing", "channelId": 1001, "message": {"type": "text", "text": "hey"},
         "status": [{"value": "read", "timestamp": 1700000000}]},
    ], None)}}
    handler = _pages_handler_full(
        {None: ([contact_row], None)}, channels_by_contact=channels_by_contact,
        messages_by_contact=messages_by_contact,
    )
    _stub_client(monkeypatch, handler)

    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        channel_map=[{"sourceChannelId": "1001", "targetChannelId": wa_channel.id}],
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    assert calls == {"publish": 0, "emit": 0, "notify": 0}
    db.close()


def test_underivable_identity_never_fabricates_and_message_channel_less_report():
    """Static coverage of D-A6-10's own wording - already exercised via the
    end-to-end test above; this asserts the pure deriver contract in
    isolation too (belt and braces, cheap)."""
    assert derive_external_user_id("WHATSAPP", {"phone": ""}, "") is None
    assert derive_external_user_id("WHATSAPP", None, None) is None
