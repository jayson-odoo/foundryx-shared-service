"""Conversation (inbox) endpoint tests - plan 05 Phase B-2.

Threads list + filters (assignee/status/priority/search), thread get,
messages (+read marker), PATCH field-level gating (assign vs reply),
camelCase mapping incl. replyTo from metadata_json.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.sql import func

from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_thread(
    session_factory,
    *,
    name="Sarah Chen",
    phone="+60123456789",
    assigned_email=None,
    status_key="OPEN",
    priority="HIGH",
    messages=(),
):
    """Insert a workspace-scoped contact + messages directly (repo-level seed)."""
    from modules.omnichannel.models import Channel, Contact, ConversationMessage, Workspace
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    channel = db.query(Channel).first()
    if channel is None:
        channel = Channel(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=ws.id,
            channel_type="WHATSAPP",
            name="Test WhatsApp",
            credentials_json=encrypt_credentials({"dev": True}),
            phone_number_id="pn-1",
            display_phone_number="+60 11-111 1111",
            is_active=True,
            status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
        )
        db.add(channel)
        db.flush()

    assigned_id = None
    if assigned_email:
        assigned_id = db.query(User).filter(User.email == assigned_email).first().id

    first, *rest = name.split(" ", 1)
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws.id,
        first_name=first,
        last_name=rest[0] if rest else None,
        phone=phone,
        assigned_user_id=assigned_id,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", status_key),
        priority=priority,
        csw_expires_at=_now() + timedelta(hours=20),
    )
    db.add(contact)
    db.flush()

    last_at = None
    last_in_at = None
    for i, m in enumerate(messages):
        created = _now() - timedelta(minutes=len(messages) - i)
        row = ConversationMessage(
            tenant_id=DEFAULT_TENANT_ID,
            contact_id=contact.id,
            channel_id=channel.id,
            sender_type=m.get("sender_type", "CONTACT"),
            sender_id=m.get("sender_id"),
            message_type=m.get("message_type", "TEXT"),
            body=m.get("body", f"msg {i}"),
            external_message_id=m.get("external_message_id"),
            delivery_status=m.get("delivery_status"),
            metadata_json=m.get("metadata_json"),
            created_at=created,
        )
        db.add(row)
        last_at = created
        if row.sender_type == "CONTACT":
            last_in_at = created
    contact.last_message_at = last_at
    contact.last_incoming_message_at = last_in_at
    db.commit()
    contact_id = contact.id
    db.close()
    return contact_id


# ── Threads list ─────────────────────────────────────────────────────────────
def test_list_threads_sorted_and_shaped(client, session_factory):
    _seed_thread(session_factory, name="Old Thread", messages=[{"body": "old"}])
    newest = _seed_thread(
        session_factory,
        name="New Thread",
        messages=[{"body": "newest message"}],
    )

    res = client.get("/omnichannel/contacts", headers=_auth(client))
    assert res.status_code == 200
    data = res.json()["data"]
    assert data[0]["id"] == newest
    item = data[0]
    assert item["name"] == "New Thread"
    assert item["lastMessagePreview"] == "newest message"
    assert item["status"] == "OPEN"
    assert item["channelType"] == "WHATSAPP"
    assert item["unreadCount"] == 1  # one inbound, never opened


def test_list_threads_filters(client, session_factory):
    mine = _seed_thread(
        session_factory, name="Mine T", assigned_email=ACTIVE_EMAIL, messages=[{}]
    )
    unassigned = _seed_thread(session_factory, name="Nobody T", messages=[{}])
    snoozed = _seed_thread(
        session_factory, name="Snoozed T", status_key="SNOOZED", priority="LOW", messages=[{}]
    )

    h = _auth(client)
    me = client.get("/omnichannel/contacts?assignee=me", headers=h).json()["data"]
    assert [t["id"] for t in me] == [mine]

    un = client.get("/omnichannel/contacts?assignee=unassigned", headers=h).json()["data"]
    assert unassigned in [t["id"] for t in un]
    assert mine not in [t["id"] for t in un]

    sn = client.get("/omnichannel/contacts?status=SNOOZED", headers=h).json()["data"]
    assert [t["id"] for t in sn] == [snoozed]

    lo = client.get("/omnichannel/contacts?priority=LOW", headers=h).json()["data"]
    assert [t["id"] for t in lo] == [snoozed]

    found = client.get("/omnichannel/contacts?search=Nobody", headers=h).json()["data"]
    assert [t["id"] for t in found] == [unassigned]


# ── Messages ─────────────────────────────────────────────────────────────────
def test_messages_shape_and_read_marker(client, session_factory):
    cid = _seed_thread(
        session_factory,
        messages=[
            {"body": "Hi!", "sender_type": "CONTACT", "external_message_id": "wamid.1"},
            {
                "body": "Hello Sarah",
                "sender_type": "AGENT",
                "delivery_status": "READ",
                "metadata_json": {
                    "reply_to": {
                        "id": "x",
                        "body": "Hi!",
                        "senderType": "CONTACT",
                        "senderName": None,
                    }
                },
            },
        ],
    )
    h = _auth(client)

    before = client.get("/omnichannel/contacts", headers=h).json()["data"]
    assert next(t for t in before if t["id"] == cid)["unreadCount"] == 1

    res = client.get(f"/omnichannel/contacts/{cid}/messages", headers=h)
    assert res.status_code == 200
    msgs = res.json()
    assert [m["body"] for m in msgs] == ["Hi!", "Hello Sarah"]
    assert msgs[1]["replyTo"]["body"] == "Hi!"
    assert msgs[1]["deliveryStatus"] == "READ"

    # Opening the thread reset the unread counter.
    after = client.get("/omnichannel/contacts", headers=h).json()["data"]
    assert next(t for t in after if t["id"] == cid)["unreadCount"] == 0


def test_get_thread_404_cross_tenant_safe(client):
    res = client.get("/omnichannel/contacts/nope", headers=_auth(client))
    assert res.status_code == 404


# ── PATCH (assign / lifecycle) ───────────────────────────────────────────────
def test_patch_assign_and_lifecycle(client, session_factory):
    cid = _seed_thread(session_factory, messages=[{}])
    h = _auth(client)

    me = client.get("/auth/me", headers=h).json()
    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": me["id"]}
    )
    assert res.status_code == 200
    assert res.json()["assignedUserId"] == me["id"]
    assert res.json()["assignedUserName"]

    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "SNOOZED"})
    assert res.json()["status"] == "SNOOZED"

    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"priority": "URGENT"})
    assert res.json()["priority"] == "URGENT"

    # Explicit null unassigns.
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": None})
    assert res.status_code == 200
    assert res.json()["assignedUserId"] is None

    # Unknown assignee rejected.
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": "ghost"})
    assert res.status_code == 422

    # Invalid status rejected.
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "NOPE"})
    assert res.status_code == 422


def test_conversations_permission_gating(client, session_factory):
    cid = _seed_thread(session_factory, messages=[{}])
    db = session_factory()
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email="noperm2@example.com",
            password=hash_password("noperm1234"),
            name="No Perm",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
    )
    db.commit()
    db.close()

    h = _auth(client, email="noperm2@example.com", password="noperm1234")
    assert client.get("/omnichannel/contacts", headers=h).status_code == 403
    assert client.get(f"/omnichannel/contacts/{cid}/messages", headers=h).status_code == 403
    assert (
        client.patch(
            f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": None}
        ).status_code
        == 403
    )
    assert (
        client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "CLOSED"}).status_code
        == 403
    )


# ── Outbound send (plan 05 §5 - Phase B-3) ──────────────────────────────────
def _seed_template(session_factory, channel_id=None, status="APPROVED"):
    from modules.omnichannel.models import Channel, WhatsappTemplate

    db = session_factory()
    cid = channel_id or db.query(Channel).first().id
    tpl = WhatsappTemplate(
        tenant_id=DEFAULT_TENANT_ID,
        channel_id=cid,
        name="booking_update",
        language="en",
        category="UTILITY",
        status=status,
        components_json=[
            {"type": "BODY", "text": "Hi {{1}}, update: {{2}}."},
        ],
    )
    db.add(tpl)
    db.commit()
    tpl_id = tpl.id
    db.close()
    return tpl_id


def test_send_free_form_inside_window(client, session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "Hi"}])
    h = _auth(client)

    res = client.post(
        f"/omnichannel/contacts/{cid}/messages", headers=h, json={"messageType": "TEXT", "body": "Hello!"}
    )
    assert res.status_code == 201, res.text
    msg = res.json()
    assert msg["senderType"] == "AGENT"
    assert msg["deliveryStatus"] == "SENT"
    assert msg["externalMessageId"].startswith("wamid.dev-")  # dev adapter stub
    assert msg["senderName"]  # actor resolved

    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=h).json()
    assert msgs[-1]["body"] == "Hello!"


def test_send_free_form_rejected_outside_window(client, session_factory):
    from modules.omnichannel.models import Contact

    cid = _seed_thread(session_factory, messages=[{"body": "Hi"}])
    db = session_factory()
    db.query(Contact).filter(Contact.id == cid).update(
        {"csw_expires_at": _now() - timedelta(hours=1)}
    )
    db.commit()
    db.close()

    res = client.post(
        f"/omnichannel/contacts/{cid}/messages",
        headers=_auth(client),
        json={"messageType": "TEXT", "body": "Hello?"},
    )
    assert res.status_code == 422
    assert "24-hour window" in res.json()["detail"]


def test_send_template_outside_window(client, session_factory):
    from modules.omnichannel.models import Contact

    cid = _seed_thread(session_factory, messages=[{"body": "Hi"}])
    tpl_id = _seed_template(session_factory)
    db = session_factory()
    db.query(Contact).filter(Contact.id == cid).update(
        {"csw_expires_at": _now() - timedelta(hours=1)}
    )
    db.commit()
    db.close()

    res = client.post(
        f"/omnichannel/contacts/{cid}/messages",
        headers=_auth(client),
        json={
            "messageType": "TEMPLATE",
            "templateId": tpl_id,
            "templateVariables": ["Marcus", "slot moved to 4pm"],
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["messageType"] == "TEMPLATE"
    assert res.json()["body"] == "Hi Marcus, update: slot moved to 4pm."


def test_send_unapproved_template_rejected(client, session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "Hi"}])
    tpl_id = _seed_template(session_factory, status="PENDING")

    res = client.post(
        f"/omnichannel/contacts/{cid}/messages",
        headers=_auth(client),
        json={"messageType": "TEMPLATE", "templateId": tpl_id, "templateVariables": ["x"]},
    )
    assert res.status_code == 422
    assert "not approved" in res.json()["detail"].lower()


def test_send_reply_threads_quote(client, session_factory):
    cid = _seed_thread(
        session_factory,
        messages=[{"body": "Can I change my booking?", "external_message_id": "wamid.target"}],
    )
    h = _auth(client)
    target = client.get(f"/omnichannel/contacts/{cid}/messages", headers=h).json()[0]

    res = client.post(
        f"/omnichannel/contacts/{cid}/messages",
        headers=h,
        json={"messageType": "TEXT", "body": "Yes!", "replyToMessageId": target["id"]},
    )
    assert res.status_code == 201, res.text
    assert res.json()["replyTo"]["id"] == target["id"]
    assert res.json()["replyTo"]["body"] == "Can I change my booking?"

    # Replying to a message from ANOTHER thread is rejected.
    other = _seed_thread(session_factory, name="Other Person", messages=[{"body": "hey"}])
    other_msg = client.get(f"/omnichannel/contacts/{other}/messages", headers=h).json()[0]
    res = client.post(
        f"/omnichannel/contacts/{cid}/messages",
        headers=h,
        json={"messageType": "TEXT", "body": "x", "replyToMessageId": other_msg["id"]},
    )
    assert res.status_code == 422


def test_internal_note_endpoint(client, session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "Hi"}])
    h = _auth(client)

    res = client.post(
        f"/omnichannel/contacts/{cid}/notes", headers=h, json={"body": "VIP - escalate"}
    )
    assert res.status_code == 201
    assert res.json()["senderType"] == "SYSTEM"
    assert res.json()["deliveryStatus"] is None


def test_templates_and_quick_replies_endpoints(client, session_factory):
    from modules.omnichannel.models import Channel, QuickReply, Workspace

    _seed_thread(session_factory, messages=[{"body": "Hi"}])  # ensures channel exists
    tpl_id = _seed_template(session_factory)
    _seed_template(session_factory, status="REJECTED")

    db = session_factory()
    channel_id = db.query(Channel).first().id
    ws_id = db.query(Workspace).filter(Workspace.is_default.is_(True)).first().id
    db.add(
        QuickReply(
            tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, shortcut="/hi", body="Hello there!"
        )
    )
    db.commit()
    db.close()

    h = _auth(client)
    tpls = client.get(f"/omnichannel/channels/{channel_id}/templates", headers=h)
    assert tpls.status_code == 200
    data = tpls.json()
    assert [t["id"] for t in data] == [tpl_id]  # APPROVED only
    assert data[0]["bodyText"] == "Hi {{1}}, update: {{2}}."
    assert data[0]["variableCount"] == 2

    qrs = client.get(f"/omnichannel/workspaces/{ws_id}/quick-replies", headers=h)
    assert qrs.status_code == 200
    assert qrs.json()[0]["shortcut"] == "/hi"


def test_send_requires_reply_permission(client, session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "Hi"}])
    db = session_factory()
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email="noperm3@example.com",
            password=hash_password("noperm1234"),
            name="No Perm",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
    )
    db.commit()
    db.close()

    h = _auth(client, email="noperm3@example.com", password="noperm1234")
    res = client.post(
        f"/omnichannel/contacts/{cid}/messages", headers=h, json={"messageType": "TEXT", "body": "x"}
    )
    assert res.status_code == 403


def test_search_matches_message_bodies(client, session_factory):
    """WhatsApp-style search: a term only present inside a message body finds
    the thread (alongside name/phone matches)."""
    hit = _seed_thread(
        session_factory,
        name="Body Hit",
        phone="+60100000001",
        messages=[{"body": "the quotation includes catering xyzzy"}],
    )
    _seed_thread(
        session_factory,
        name="Body Miss",
        phone="+60100000002",
        messages=[{"body": "unrelated message"}],
    )

    h = _auth(client)
    found = client.get("/omnichannel/contacts?search=xyzzy", headers=h).json()["data"]
    assert [t["id"] for t in found] == [hit]

    # Name search still works.
    found = client.get("/omnichannel/contacts?search=Body Miss", headers=h).json()["data"]
    assert len(found) == 1 and found[0]["name"] == "Body Miss"


def test_send_template_rejects_wrong_variable_count(client, session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "Hi"}])
    tpl_id = _seed_template(session_factory)  # body has {{1}} and {{2}}

    res = client.post(
        f"/omnichannel/contacts/{cid}/messages",
        headers=_auth(client),
        json={"messageType": "TEMPLATE", "templateId": tpl_id, "templateVariables": ["only-one"]},
    )
    assert res.status_code == 422
    assert "2 variable" in res.json()["detail"]


def test_internal_note_broadcasts_realtime(client, session_factory):
    import fakeredis
    from modules.omnichannel.services import realtime

    fake = fakeredis.FakeRedis(decode_responses=True)
    realtime.set_client(fake)
    try:
        cid = _seed_thread(session_factory, messages=[{"body": "Hi"}])
        # Find the workspace room the note should publish to.
        from modules.omnichannel.models import Contact
        db = session_factory()
        ws_id = db.query(Contact).filter(Contact.id == cid).first().workspace_id
        db.close()

        sub = fake.pubsub()
        sub.subscribe(f"omnichannel:ws:{ws_id}")
        sub.get_message(timeout=0.1)  # subscribe ack

        client.post(f"/omnichannel/contacts/{cid}/notes", headers=_auth(client), json={"body": "note"})

        import json as _json
        evt = sub.get_message(timeout=1)
        assert evt and _json.loads(evt["data"])["type"] == "message.created"
        assert _json.loads(evt["data"])["message"]["senderType"] == "SYSTEM"
    finally:
        realtime.set_client(None)
