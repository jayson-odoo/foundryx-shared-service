"""Conversation events - plan 27 A3 (roadmap A9 prerequisite), slice S1.

Covers AC-IVE-01..14, 33, 42: the `conversation_events` table shape, the nine
writer call sites (opened x2, reopened/unsnoozed auto, closed/reopened/
snoozed/unsnoozed manual, assigned/unassigned, first_agent_reply,
lifecycle_changed, comment_added), actor tenant-scoping, `last_agent_
message_at` maintenance, the `backfill_tenant` function, the
`GET /{id}/events` read route (shape, pagination, tenant isolation), and
uninstall cleanup. Reuses the existing conversation/webhook/gateway test seams
rather than duplicating fixture setup.
"""
from datetime import datetime, timezone

import pytest

from app.models import DEFAULT_TENANT_ID, User
from tests.conftest import ACTIVE_EMAIL
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seeded,
)
from tests.test_omnichannel_contact_data_model import _other_tenant_auth
from tests.test_omnichannel_conversations import _auth, _seed_thread
from tests.test_omnichannel_webhooks import _channel_id, _process, _wa_payload


# ── AC-IVE-01: table shape ───────────────────────────────────────────────────
def test_conversation_events_table_shape():
    from modules.omnichannel.models import ConversationEvent

    cols = {c.name for c in ConversationEvent.__table__.columns}
    assert cols == {
        "id", "tenant_id", "workspace_id", "contact_id", "event_type",
        "actor_user_id", "actor_external_agent_id", "from_value", "to_value",
        "close_reason_id", "note", "payload_json", "created_at",
    }
    index_names = {ix.name for ix in ConversationEvent.__table__.indexes}
    assert {
        "ix_conv_events_ws_created",
        "ix_conv_events_contact_created",
        "ix_conv_events_type_created",
    } <= index_names


# ── AC-IVE-02: same unit of work as the mutation ─────────────────────────────
def test_event_write_rolls_back_with_its_mutation(session_factory):
    from modules.omnichannel.models import Contact, ConversationEvent
    from modules.omnichannel.services.conversation_service import (
        ConversationService,
        InvalidPatch,
    )

    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    db = session_factory()
    original_status_id = db.query(Contact).filter(Contact.id == cid).first().status_id

    svc = ConversationService(db)
    with pytest.raises(InvalidPatch):
        # status change flushes (contact + event) BEFORE the invalid priority
        # raises - nothing is ever committed.
        svc.patch_thread(cid, DEFAULT_TENANT_ID, status="CLOSED", priority="BOGUS")
    db.close()  # implicit ROLLBACK of the shared connection's pending txn

    db2 = session_factory()
    contact = db2.query(Contact).filter(Contact.id == cid).first()
    assert contact.status_id == original_status_id
    assert (
        db2.query(ConversationEvent).filter(ConversationEvent.contact_id == cid).count() == 0
    )
    db2.close()


# ── AC-IVE-03: opened (new thread), both creation paths ──────────────────────
def test_opened_event_new_thread_inbound(session_factory):
    _seed_thread(session_factory, phone="+60199999999", messages=[{"body": "seed"}])
    channel_id = _channel_id(session_factory)

    res = _process(
        session_factory, channel_id, _wa_payload(wamid="wamid.new1", from_="60177777777", text="first")
    )
    assert res["messages"] == 1

    from modules.omnichannel.models import Contact, ConversationEvent

    db = session_factory()
    contact = db.query(Contact).filter(Contact.phone == "+60177777777").first()
    assert contact is not None
    events = db.query(ConversationEvent).filter(ConversationEvent.contact_id == contact.id).all()
    assert [e.event_type for e in events] == ["opened"]
    assert events[0].to_value == contact.status_id
    db.close()


def test_opened_event_gateway_create(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    key = _mint(client, ws).json()["fullKey"]

    client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60321000111", "type": "text", "text": {"body": "hi"}},
        headers={"Authorization": f"Bearer {key}"},
    )

    from modules.omnichannel.models import Contact, ConversationEvent

    db = session_factory()
    contact = db.query(Contact).filter(Contact.phone == "60321000111").first()
    assert contact is not None
    events = db.query(ConversationEvent).filter(ConversationEvent.contact_id == contact.id).all()
    assert [e.event_type for e in events] == ["opened"]
    assert events[0].to_value == contact.status_id
    db.close()


# ── AC-IVE-04: auto reopen/unsnooze on inbound, no-op if already OPEN ────────
def test_auto_reopen_and_unsnooze_events_on_inbound(session_factory):
    closed_cid = _seed_thread(
        session_factory, phone="+60111111111", status_key="CLOSED",
        messages=[{"sender_type": "AGENT", "body": "bye"}],
    )
    snoozed_cid = _seed_thread(
        session_factory, phone="+60122222222", status_key="SNOOZED",
        messages=[{"sender_type": "AGENT", "body": "later"}],
    )
    open_cid = _seed_thread(
        session_factory, phone="+60133333333", status_key="OPEN", messages=[{"body": "hi"}]
    )
    channel_id = _channel_id(session_factory)

    _process(session_factory, channel_id, _wa_payload(wamid="wamid.r1", from_="60111111111", text="back"))
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.r2", from_="60122222222", text="hey"))
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.r3", from_="60133333333", text="again"))

    from modules.omnichannel.models import ConversationEvent

    db = session_factory()

    def types_for(cid):
        return [
            e.event_type
            for e in db.query(ConversationEvent).filter(ConversationEvent.contact_id == cid).all()
        ]

    assert types_for(closed_cid) == ["reopened"]
    assert types_for(snoozed_cid) == ["unsnoozed"]
    assert types_for(open_cid) == []  # already OPEN -> no event
    db.close()


# ── AC-IVE-05: manual status changes ─────────────────────────────────────────
def test_manual_status_change_events(client, session_factory):
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    h = _auth(client)

    assert client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "SNOOZED"}).status_code == 200
    assert client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "OPEN"}).status_code == 200
    assert client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "CLOSED"}).status_code == 200
    assert client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "OPEN"}).status_code == 200

    before = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["total"]
    # re-sending the CURRENT status writes nothing.
    assert client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "OPEN"}).status_code == 200
    after = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["total"]
    assert after == before == 4

    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert [e["eventType"] for e in events] == ["reopened", "closed", "unsnoozed", "snoozed"]


# ── AC-IVE-06: assign / unassign ──────────────────────────────────────────────
def test_assign_unassign_events(client, session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    h = _auth(client)
    db = session_factory()
    admin_id = db.query(User).filter(User.email == ACTIVE_EMAIL).first().id
    db.close()

    assert client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": admin_id}
    ).status_code == 200

    before = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["total"]
    # re-sending the SAME assignee writes nothing.
    assert client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": admin_id}
    ).status_code == 200
    after = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["total"]
    assert after == before == 1

    assert client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": None}
    ).status_code == 200

    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert [e["eventType"] for e in events] == ["unassigned", "assigned"]
    assigned_event = events[1]
    assert assigned_event["toValue"] == admin_id
    assert assigned_event["toLabel"]  # resolved to the admin's display name
    assert assigned_event["payload"]["assigneeKind"] == "user"
    unassigned_event = events[0]
    assert unassigned_event["fromValue"] == admin_id


# ── AC-IVE-07: first_agent_reply once per open cycle ─────────────────────────
def test_first_agent_reply_once_per_open_cycle(client, session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    h = _auth(client)

    r1 = client.post(
        f"/omnichannel/contacts/{cid}/messages", headers=h, json={"messageType": "TEXT", "body": "Hello!"}
    )
    assert r1.status_code == 201
    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert events[0]["eventType"] == "first_agent_reply"
    assert "responseSeconds" in events[0]["payload"]

    # a second agent send in the SAME cycle writes no second event.
    r2 = client.post(
        f"/omnichannel/contacts/{cid}/messages", headers=h, json={"messageType": "TEXT", "body": "Still here"}
    )
    assert r2.status_code == 201
    events2 = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert sum(e["eventType"] == "first_agent_reply" for e in events2) == 1

    # an internal note is NEVER a reply.
    note = client.post(f"/omnichannel/contacts/{cid}/notes", headers=h, json={"body": "internal"})
    assert note.status_code == 201
    events3 = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert sum(e["eventType"] == "first_agent_reply" for e in events3) == 1

    # close -> auto-reopen (inbound) -> reply again -> a SECOND first_agent_reply.
    client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "CLOSED"})
    channel_id = _channel_id(session_factory)
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.reopen1", from_="60123456789", text="back"))
    r3 = client.post(
        f"/omnichannel/contacts/{cid}/messages", headers=h, json={"messageType": "TEXT", "body": "welcome back"}
    )
    assert r3.status_code == 201
    events4 = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert sum(e["eventType"] == "first_agent_reply" for e in events4) == 2


# ── AC-IVE-08: lifecycle_changed ──────────────────────────────────────────────
def test_lifecycle_changed_event(client, session_factory):
    from modules.omnichannel.models import Contact
    from modules.omnichannel.services.lifecycle_service import initial_status_id

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    contact = db.query(Contact).filter(Contact.id == cid).first()
    contact.lifecycle_status_id = initial_status_id(db, DEFAULT_TENANT_ID, contact.workspace_id)
    db.commit()
    db.close()

    h = _auth(client)
    moves = client.get(f"/omnichannel/contacts/{cid}/lifecycle-moves", headers=h).json()
    assert moves
    target = moves[0]["toStatusId"]

    r = client.post(f"/omnichannel/contacts/{cid}/lifecycle", headers=h, json={"toStatusId": target})
    assert r.status_code == 200

    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert events[0]["eventType"] == "lifecycle_changed"
    assert events[0]["toValue"] == target
    assert events[0]["toLabel"]  # resolved core lifecycle-status label


# ── AC-IVE-09: comment_added (internal note, both native + gateway) ──────────
def test_comment_added_event_native(client, session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    h = _auth(client)

    note = client.post(f"/omnichannel/contacts/{cid}/notes", headers=h, json={"body": "Handle with care"})
    assert note.status_code == 201
    msg_id = note.json()["id"]

    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert events[0]["eventType"] == "comment_added"
    assert events[0]["payload"]["messageId"] == msg_id


def test_comment_added_event_gateway(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555222999")

    r = client.post(
        f"/api/v1/omnichannel/contacts/{cid}/comments", json={"body": "internal via gateway"}, headers=hdr
    )
    assert r.status_code == 201

    from modules.omnichannel.models import ConversationEvent

    db = session_factory()
    types = {
        e.event_type
        for e in db.query(ConversationEvent).filter(ConversationEvent.contact_id == cid).all()
    }
    assert "comment_added" in types
    db.close()


def test_gateway_close_writes_closed_event(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555222998")

    r = client.post(f"/api/v1/omnichannel/contacts/{cid}/conversation/close", headers=hdr)
    assert r.status_code == 200

    from modules.omnichannel.models import ConversationEvent

    db = session_factory()
    types = {
        e.event_type
        for e in db.query(ConversationEvent).filter(ConversationEvent.contact_id == cid).all()
    }
    assert "closed" in types
    db.close()


# ── AC-IVE-10: actor validated at save, resolved tenant-scoped at read ───────
def test_actor_tenant_scoped_save_and_read(session_factory):
    from app.services.tenant_service import TenantService
    from modules.omnichannel.models import Contact, ConversationEvent
    from modules.omnichannel.services import event_service

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    other = TenantService(db).provision(
        name="Other IVE", slug="other-ive-actor",
        admin_email="admin-other-ive-actor@example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    db.commit()
    contact = db.query(Contact).filter(Contact.id == cid).first()
    other_user = db.query(User).filter(User.tenant_id == other.id).first()

    # save-time validation drops a foreign actor id - never stored.
    saved = event_service.record(db, contact, "assigned", actor_id=other_user.id, to_value="x")
    assert saved.actor_user_id is None
    db.commit()

    # a planted/corrupt row (bypassing record()) must still resolve empty at
    # read - defense-in-depth against a stray/corrupt id, not just save-time.
    planted = ConversationEvent(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=contact.workspace_id, contact_id=contact.id,
        event_type="assigned", actor_user_id=other_user.id, to_value="x",
        created_at=datetime.now(timezone.utc),
    )
    db.add(planted)
    db.commit()

    items = event_service.to_items(db, [planted], DEFAULT_TENANT_ID)
    assert items[0].actorName is None
    db.close()


# ── AC-IVE-11: last_agent_message_at maintained by sends only ───────────────
def test_last_agent_message_at_maintained_by_sends_not_notes(client, session_factory):
    from modules.omnichannel.models import Contact

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    h = _auth(client)

    db = session_factory()
    assert db.query(Contact).filter(Contact.id == cid).first().last_agent_message_at is None
    db.close()

    client.post(f"/omnichannel/contacts/{cid}/notes", headers=h, json={"body": "note"})
    db = session_factory()
    assert db.query(Contact).filter(Contact.id == cid).first().last_agent_message_at is None
    db.close()

    client.post(f"/omnichannel/contacts/{cid}/messages", headers=h, json={"messageType": "TEXT", "body": "hey"})
    db = session_factory()
    assert db.query(Contact).filter(Contact.id == cid).first().last_agent_message_at is not None
    db.close()


# ── AC-IVE-12: backfill_tenant (install_tenant/update_tenant self-healing) ──
def test_backfill_tenant_function(session_factory):
    from modules.omnichannel.models import Contact, ConversationEvent
    from modules.omnichannel.services import event_service

    open_cid = _seed_thread(
        session_factory, phone="+60155500001", status_key="OPEN",
        messages=[{"sender_type": "AGENT", "body": "hey"}],
    )
    closed_cid = _seed_thread(
        session_factory, phone="+60155500002", status_key="CLOSED",
        messages=[{"sender_type": "AGENT", "body": "bye"}],
    )

    db = session_factory()
    admin_id = db.query(User).filter(User.email == ACTIVE_EMAIL).first().id
    contact = db.query(Contact).filter(Contact.id == open_cid).first()
    contact.assigned_user_id = admin_id
    db.commit()

    result = event_service.backfill_tenant(db, DEFAULT_TENANT_ID)
    assert result["contactsBackfilled"] == 2

    open_events = {
        e.event_type
        for e in db.query(ConversationEvent).filter(ConversationEvent.contact_id == open_cid).all()
    }
    assert open_events == {"opened", "assigned"}
    closed_events = {
        e.event_type
        for e in db.query(ConversationEvent).filter(ConversationEvent.contact_id == closed_cid).all()
    }
    assert closed_events == {"opened", "closed"}

    refreshed = db.query(Contact).filter(Contact.id == open_cid).first()
    assert refreshed.last_agent_message_at is not None

    # idempotent - a second run is a no-op.
    before = db.query(ConversationEvent).count()
    result2 = event_service.backfill_tenant(db, DEFAULT_TENANT_ID)
    after = db.query(ConversationEvent).count()
    assert before == after
    assert result2["contactsBackfilled"] == 0
    db.close()


def test_seed_demo_conversations_backfills_events(session_factory):
    """Review round 1, finding 3 (AC-IVE-03): the dev demo inbox seed must not
    leave its five fixed threads without `opened` events / `last_agent_
    message_at` - Unreplied and Longest-waiting evidence would be
    meaningless otherwise. `seed_demo_conversations` now calls
    `event_service.backfill_tenant` before its own commit."""
    from modules.omnichannel import bootstrap
    from modules.omnichannel.models import Contact, ConversationEvent

    db = session_factory()
    bootstrap.seed_demo_conversations(db, DEFAULT_TENANT_ID)
    db.close()

    db = session_factory()
    demo_ids = ["cnt-001", "cnt-002", "cnt-003", "cnt-004", "cnt-005"]
    for cid in demo_ids:
        events = {
            e.event_type
            for e in db.query(ConversationEvent).filter(ConversationEvent.contact_id == cid).all()
        }
        assert "opened" in events, f"{cid} missing its opened event"
    closed_events = {
        e.event_type
        for e in db.query(ConversationEvent).filter(ConversationEvent.contact_id == "cnt-005").all()
    }
    assert "closed" in closed_events

    # cnt-001/cnt-002/cnt-004/cnt-005 have an AGENT message in the seed
    # (cnt-003 does not) - `last_agent_message_at` must be filled for the
    # sort/unreplied filters.
    for cid in ("cnt-001", "cnt-002", "cnt-004", "cnt-005"):
        c = db.query(Contact).filter(Contact.id == cid).first()
        assert c.last_agent_message_at is not None, f"{cid} missing last_agent_message_at"
    db.close()


# ── pre-merge follow-up item 4: dev seed is gated to the default tenant ─────
def test_seed_demo_conversations_refuses_a_non_default_tenant(session_factory):
    """`seed_demo_conversations` writes fixed literal ids (`chn-demo`,
    `cnt-001`..`005`) shared verbatim across every call site's dev seed data -
    a second tenant would collide on those SAME ids. The dormant multi-tenant
    path must fail LOUDLY (a clear ``ValueError``) instead of half-writing
    cross-tenant rows or silently resolving the DEFAULT tenant's `chn-demo`
    channel via an unscoped lookup."""
    from modules.omnichannel import bootstrap

    db = session_factory()
    with pytest.raises(ValueError, match="default tenant only"):
        bootstrap.seed_demo_conversations(db, "some-other-tenant-id")
    db.close()


def test_backfill_tenant_is_batched_not_n_plus_one(session_factory):
    """Review round 1, finding 4: `backfill_tenant` must run a small CONSTANT
    number of SELECTs against `conversation_events`/`conversation_messages`
    regardless of contact count (previously one of each per contact)."""
    from sqlalchemy import event

    from modules.omnichannel.services import event_service

    for i in range(12):
        _seed_thread(
            session_factory, phone=f"+601566{i:05d}", status_key="OPEN",
            messages=[{"sender_type": "AGENT", "body": "hey"}],
        )

    engine = session_factory.kw["bind"]
    selects = {"n": 0}

    def _before(conn, cursor, statement, *a):
        upper = statement.lstrip().upper()
        if upper.startswith("SELECT") and (
            "CONVERSATION_EVENTS" in upper or "CONVERSATION_MESSAGES" in upper
        ):
            selects["n"] += 1

    db = session_factory()
    event.listen(engine, "before_cursor_execute", _before)
    try:
        result = event_service.backfill_tenant(db, DEFAULT_TENANT_ID)
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    db.close()

    assert result["contactsBackfilled"] == 12
    # ONE query for existing events + ONE (grouped) query for latest AGENT
    # message - never a per-contact pair (24 for 12 contacts pre-fix).
    assert selects["n"] <= 2, f"expected 2 batched SELECTs, got {selects['n']}"


def test_install_tenant_self_heals_events(session_factory):
    """`install_tenant` calls `event_service.backfill_tenant` unconditionally
    (self-healing, like the lifecycle backfill it already runs) - a contact
    that predates the events table gets backfilled on the NEXT install call."""
    from modules.omnichannel import bootstrap
    from modules.omnichannel.models import ConversationEvent

    _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    assert db.query(ConversationEvent).count() == 0
    bootstrap.install_tenant(db, DEFAULT_TENANT_ID)
    db.commit()
    assert db.query(ConversationEvent).count() >= 1
    db.close()


# ── AC-IVE-13/42: read route shape + pagination + tenant isolation ──────────
def test_list_events_route_shape_pagination_and_tenant_isolation(client, session_factory):
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    h = _auth(client)
    for status in ("SNOOZED", "OPEN", "CLOSED"):
        assert client.patch(
            f"/omnichannel/contacts/{cid}", headers=h, json={"status": status}
        ).status_code == 200

    res = client.get(f"/omnichannel/contacts/{cid}/events", headers=h, params={"pageSize": 2})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert len(body["data"]) == 2
    created_ats = [e["createdAt"] for e in body["data"]]
    assert created_ats == sorted(created_ats, reverse=True)  # newest-first
    assert created_ats[0].endswith("Z")

    page1 = client.get(
        f"/omnichannel/contacts/{cid}/events", headers=h, params={"pageSize": 2, "page": 1}
    ).json()
    assert len(page1["data"]) == 1

    # cross-tenant: a foreign tenant gets a uniform 404, never data.
    h2 = _other_tenant_auth(client, session_factory)
    res2 = client.get(f"/omnichannel/contacts/{cid}/events", headers=h2)
    assert res2.status_code == 404


# ── AC-IVE-14: uninstall wipes conversation_events with the rest ────────────
def test_uninstall_tenant_deletes_conversation_events(session_factory):
    from app.services.app_store_service import AppStoreService
    from modules.omnichannel.models import CloseReason, Contact, ConversationEvent, InboxView
    from modules.omnichannel.schemas import InboxViewCreate
    from modules.omnichannel.services import event_service
    from modules.omnichannel.services.inbox_view_service import InboxViewService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    contact = db.query(Contact).filter(Contact.id == cid).first()
    event_service.record(db, contact, "opened", to_value=contact.status_id)
    db.commit()
    assert (
        db.query(ConversationEvent).filter(ConversationEvent.tenant_id == DEFAULT_TENANT_ID).count()
        >= 1
    )

    # AC-IVE-14 (review round 1, finding 11): close_reasons/inbox_views are
    # ALSO wiped - both are plain OmniBase tenant-scoped tables, so they ride
    # the same generic per-table delete loop as conversation_events.
    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    InboxViewService(db).create(
        contact.workspace_id, DEFAULT_TENANT_ID, admin.id,
        InboxViewCreate(name="Uninstall check", isShared=False),
    )
    assert (
        db.query(CloseReason).filter(CloseReason.tenant_id == DEFAULT_TENANT_ID).count() >= 1
    )
    assert (
        db.query(InboxView).filter(InboxView.tenant_id == DEFAULT_TENANT_ID).count() >= 1
    )

    AppStoreService(db).uninstall(DEFAULT_TENANT_ID, "omnichannel", "omnichannel")
    db.commit()
    assert (
        db.query(ConversationEvent).filter(ConversationEvent.tenant_id == DEFAULT_TENANT_ID).count()
        == 0
    )
    assert (
        db.query(CloseReason).filter(CloseReason.tenant_id == DEFAULT_TENANT_ID).count() == 0
    )
    assert (
        db.query(InboxView).filter(InboxView.tenant_id == DEFAULT_TENANT_ID).count() == 0
    )
    db.close()
