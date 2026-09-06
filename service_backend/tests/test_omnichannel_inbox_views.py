"""Inbox views, close reasons, close-with-reason route - plan 27 A3, S2.

Covers AC-IVE-15..31, 41, 42 (backend half). Reuses the existing conversation
test seams (`_seed_thread`, `_auth`) rather than duplicating fixture setup.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.sql import func

from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.test_omnichannel_contact_data_model import _other_tenant_auth
from tests.test_omnichannel_conversations import _auth, _seed_thread


def _workspace_id(client, h) -> str:
    data = client.get("/omnichannel/workspaces", headers=h).json()["data"]
    return next(w["id"] for w in data if w["isDefault"])


def _base(ws_id: str) -> str:
    return f"/omnichannel/workspaces/{ws_id}"


def _no_perm_auth(client, session_factory, email="ive-noperm@example.com"):
    db = session_factory()
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email=email,
            password=hash_password("noperm1234"),
            name="No Perm",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
    )
    db.commit()
    db.close()
    return _auth(client, email=email, password="noperm1234")


# ── AC-IVE-27: seeding on workspace create + backfill idempotency ──────────
def test_close_reasons_seeded_on_default_workspace(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.get(f"{_base(ws)}/close-reasons", headers=h)
    assert res.status_code == 200
    names = [r["name"] for r in res.json()]
    assert names == ["General Inquiry", "Sales Inquiry", "Payment Issue", "Others"]
    assert all(r["isActive"] for r in res.json())
    assert all(r["usesCount"] == 0 for r in res.json())


def test_close_reasons_seeded_on_new_workspace_create(client):
    h = _auth(client)
    res = client.post("/omnichannel/workspaces", headers=h, json={"name": "New WS", "status": "ACTIVE"})
    assert res.status_code == 201
    ws = res.json()["id"]
    reasons = client.get(f"{_base(ws)}/close-reasons", headers=h).json()
    assert len(reasons) == 4


def test_close_reason_backfill_tenant_idempotent(session_factory):
    from modules.omnichannel.models import CloseReason, Workspace
    from modules.omnichannel.services.close_reason_service import CloseReasonService

    db = session_factory()
    # Wipe the default workspace's seeded reasons to simulate a pre-existing
    # tenant that predates this slice.
    db.query(CloseReason).filter(CloseReason.tenant_id == DEFAULT_TENANT_ID).delete()
    db.commit()

    svc = CloseReasonService(db)
    seeded = svc.backfill_tenant(DEFAULT_TENANT_ID)
    assert seeded >= 1
    ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)).first()
    assert len(svc.list(ws.id, DEFAULT_TENANT_ID)) == 4

    # idempotent - a second run seeds nothing more.
    seeded2 = svc.backfill_tenant(DEFAULT_TENANT_ID)
    assert seeded2 == 0
    assert len(svc.list(ws.id, DEFAULT_TENANT_ID)) == 4
    db.close()


# ── AC-IVE-25: CRUD + permission gates ──────────────────────────────────────
def test_close_reason_crud(client):
    h = _auth(client)
    ws = _workspace_id(client, h)

    created = client.post(f"{_base(ws)}/close-reasons", headers=h, json={"name": "Refund"})
    assert created.status_code == 201, created.text
    reason_id = created.json()["id"]
    assert created.json()["sortOrder"] == 4  # after the 4 seeded rows

    dup = client.post(f"{_base(ws)}/close-reasons", headers=h, json={"name": "refund"})
    assert dup.status_code == 422
    assert "name" in dup.json()["detail"]["fieldErrors"]

    blank = client.post(f"{_base(ws)}/close-reasons", headers=h, json={"name": "  "})
    assert blank.status_code == 422

    updated = client.patch(
        f"{_base(ws)}/close-reasons/{reason_id}", headers=h, json={"name": "Refund Requested"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Refund Requested"

    deleted = client.delete(f"{_base(ws)}/close-reasons/{reason_id}", headers=h)
    assert deleted.status_code == 204

    missing = client.patch(f"{_base(ws)}/close-reasons/{reason_id}", headers=h, json={"name": "x"})
    assert missing.status_code == 404


def test_close_reason_permission_gates(client, session_factory):
    h_noperm = _no_perm_auth(client, session_factory)
    h = _auth(client)
    ws = _workspace_id(client, h)

    assert client.get(f"{_base(ws)}/close-reasons", headers=h_noperm).status_code == 403
    assert client.post(
        f"{_base(ws)}/close-reasons", headers=h_noperm, json={"name": "X"}
    ).status_code == 403


# ── AC-IVE-26: delete blocked while referenced, deactivate instead ──────────
def test_close_reason_delete_in_use_409_deactivate_ok(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    reasons = client.get(f"{_base(ws)}/close-reasons", headers=h).json()
    reason_id = reasons[0]["id"]

    close = client.post(
        f"/omnichannel/contacts/{cid}/close", headers=h, json={"closeReasonId": reason_id, "note": "done"}
    )
    assert close.status_code == 200, close.text

    delete = client.delete(f"{_base(ws)}/close-reasons/{reason_id}", headers=h)
    assert delete.status_code == 409
    assert delete.json()["detail"]["code"] == "close_reason_in_use"

    deactivate = client.patch(
        f"{_base(ws)}/close-reasons/{reason_id}", headers=h, json={"isActive": False}
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["isActive"] is False
    assert deactivate.json()["usesCount"] == 1


# ── Round-3 codex triage B14: a conversation closes with this reason BETWEEN
# the pre-check and the delete commit - IntegrityError, not a 500 ──────────
def test_close_reason_delete_race_is_409_not_500(session_factory):
    from sqlalchemy.exc import IntegrityError

    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services.close_reason_service import (
        CloseReasonInUse,
        CloseReasonService,
    )

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    svc = CloseReasonService(db)
    reasons = svc.list(ws.id, DEFAULT_TENANT_ID)
    reason = reasons[0]

    real_commit = db.commit
    calls = {"n": 0}

    def fake_commit(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("delete", {}, Exception("fk violation"))
        return real_commit(*a, **kw)

    db.commit = fake_commit
    try:
        with pytest.raises(CloseReasonInUse):
            svc.delete(reason.id, ws.id, DEFAULT_TENANT_ID)
    finally:
        db.commit = real_commit

    # The row survives - the rollback undid the ORM-side delete too.
    assert svc.get(reason.id, ws.id, DEFAULT_TENANT_ID) is not None


# ── AC-IVE-28/29: close route ────────────────────────────────────────────────
def test_close_route_happy_path(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    reason_id = client.get(f"{_base(ws)}/close-reasons", headers=h).json()[0]["id"]

    res = client.post(
        f"/omnichannel/contacts/{cid}/close",
        headers=h,
        json={"closeReasonId": reason_id, "note": "Resolved by refund"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "CLOSED"

    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert events[0]["eventType"] == "closed"
    assert events[0]["closeReasonId"] == reason_id
    assert events[0]["closeReasonName"]
    assert events[0]["note"] == "Resolved by refund"


def test_close_route_note_optional(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    reason_id = client.get(f"{_base(ws)}/close-reasons", headers=h).json()[0]["id"]

    res = client.post(
        f"/omnichannel/contacts/{cid}/close", headers=h, json={"closeReasonId": reason_id}
    )
    assert res.status_code == 200
    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert events[0]["note"] is None


def test_close_route_rejects_missing_reason(client, session_factory):
    h = _auth(client)
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])

    res = client.post(
        f"/omnichannel/contacts/{cid}/close", headers=h, json={"closeReasonId": "nope"}
    )
    assert res.status_code == 404

    thread = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert thread["status"] == "OPEN"


def test_close_route_rejects_inactive_reason(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    reason = client.get(f"{_base(ws)}/close-reasons", headers=h).json()[0]
    client.patch(f"{_base(ws)}/close-reasons/{reason['id']}", headers=h, json={"isActive": False})

    res = client.post(
        f"/omnichannel/contacts/{cid}/close", headers=h, json={"closeReasonId": reason["id"]}
    )
    assert res.status_code == 422
    assert "closeReasonId" in res.json()["detail"]["fieldErrors"]

    thread = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert thread["status"] == "OPEN"


def test_close_route_rejects_foreign_workspace_reason(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    other_ws = client.post(
        "/omnichannel/workspaces", headers=h, json={"name": "Other WS", "status": "ACTIVE"}
    ).json()["id"]
    foreign_reason_id = client.get(f"{_base(other_ws)}/close-reasons", headers=h).json()[0]["id"]

    res = client.post(
        f"/omnichannel/contacts/{cid}/close", headers=h, json={"closeReasonId": foreign_reason_id}
    )
    assert res.status_code == 404


def test_close_route_reopen_keeps_history(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    reason_id = client.get(f"{_base(ws)}/close-reasons", headers=h).json()[0]["id"]

    client.post(f"/omnichannel/contacts/{cid}/close", headers=h, json={"closeReasonId": reason_id})
    client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "OPEN"})

    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert [e["eventType"] for e in events] == ["reopened", "closed"]
    assert events[1]["closeReasonId"] == reason_id


def test_close_route_already_closed_409(client, session_factory):
    """Review round 1, finding 13: closing an ALREADY-CLOSED thread 409s
    (`already_closed`) rather than silently accepting - and dropping - a new
    reason/note. Reopen then close again is the way to change the reason."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    reasons = client.get(f"{_base(ws)}/close-reasons", headers=h).json()
    reason_id, other_reason_id = reasons[0]["id"], reasons[1]["id"]

    first = client.post(
        f"/omnichannel/contacts/{cid}/close",
        headers=h,
        json={"closeReasonId": reason_id, "note": "first close"},
    )
    assert first.status_code == 200

    again = client.post(
        f"/omnichannel/contacts/{cid}/close",
        headers=h,
        json={"closeReasonId": other_reason_id, "note": "should not apply"},
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "already_closed"

    # the original reason/note stand - nothing overwritten.
    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert events[0]["closeReasonId"] == reason_id
    assert events[0]["note"] == "first close"

    # reopen then close again DOES apply a new reason.
    client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"status": "OPEN"})
    reclose = client.post(
        f"/omnichannel/contacts/{cid}/close",
        headers=h,
        json={"closeReasonId": other_reason_id, "note": "second close"},
    )
    assert reclose.status_code == 200
    events2 = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assert events2[0]["closeReasonId"] == other_reason_id
    assert events2[0]["note"] == "second close"


def test_close_route_permission_gate(client, session_factory):
    h_noperm = _no_perm_auth(client, session_factory, email="ive-close-noperm@example.com")
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    res = client.post(
        f"/omnichannel/contacts/{cid}/close", headers=h_noperm, json={"closeReasonId": "x"}
    )
    assert res.status_code == 403


# ── AC-IVE-15/16: thread-list filters + sorts ───────────────────────────────
def test_thread_list_channel_and_tag_filters(client, session_factory):
    from modules.omnichannel.models import Channel, Contact, ContactChannelIdentity, ContactTag, ContactTagLink

    cid_a = _seed_thread(session_factory, phone="+60111000001", messages=[{"body": "a"}])
    cid_b = _seed_thread(session_factory, phone="+60111000002", messages=[{"body": "b"}])
    h = _auth(client)
    ws = _workspace_id(client, h)

    db = session_factory()
    tag = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, name="VIP")
    db.add(tag)
    db.flush()
    db.add(ContactTagLink(tenant_id=DEFAULT_TENANT_ID, contact_id=cid_a, tag_id=tag.id))
    channel = db.query(Channel).first()
    # `_seed_thread` never populates `contact_channel_identities` (that's the
    # real inbound-stitch path) - the channel filter reads that table, so
    # attach both contacts to the channel directly for this test.
    db.add(ContactChannelIdentity(
        tenant_id=DEFAULT_TENANT_ID, contact_id=cid_a, channel_id=channel.id,
        external_user_id="60111000001",
    ))
    db.add(ContactChannelIdentity(
        tenant_id=DEFAULT_TENANT_ID, contact_id=cid_b, channel_id=channel.id,
        external_user_id="60111000002",
    ))
    db.commit()
    tag_id = tag.id
    channel_id = channel.id
    db.close()

    res = client.get("/omnichannel/contacts", headers=h, params={"tagIds": tag_id})
    ids = {t["id"] for t in res.json()["data"]}
    assert ids == {cid_a}

    res2 = client.get("/omnichannel/contacts", headers=h, params={"channelIds": channel_id})
    ids2 = {t["id"] for t in res2.json()["data"]}
    assert {cid_a, cid_b} <= ids2


def test_thread_list_lifecycle_filter(client, session_factory):
    from modules.omnichannel.models import Contact
    from modules.omnichannel.services.lifecycle_service import initial_status_id

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    h = _auth(client)
    ws = _workspace_id(client, h)

    db = session_factory()
    contact = db.query(Contact).filter(Contact.id == cid).first()
    stage_id = initial_status_id(db, DEFAULT_TENANT_ID, ws)
    contact.lifecycle_status_id = stage_id
    db.commit()
    db.close()

    res = client.get("/omnichannel/contacts", headers=h, params={"lifecycleStageIds": stage_id})
    ids = {t["id"] for t in res.json()["data"]}
    assert cid in ids

    res2 = client.get("/omnichannel/contacts", headers=h, params={"lifecycleStageIds": "nope"})
    assert cid not in {t["id"] for t in res2.json()["data"]}


def test_thread_list_unreplied_filter(client, session_factory):
    from modules.omnichannel.models import Contact

    replied = _seed_thread(
        session_factory, phone="+60122000001",
        messages=[{"body": "hi"}, {"sender_type": "AGENT", "body": "hey"}],
    )
    unreplied = _seed_thread(session_factory, phone="+60122000002", messages=[{"body": "hi"}])
    h = _auth(client)

    db = session_factory()
    for cid, agent_reply in ((replied, True), (unreplied, False)):
        c = db.query(Contact).filter(Contact.id == cid).first()
        if agent_reply:
            c.last_agent_message_at = c.last_message_at
    db.commit()
    db.close()

    res = client.get("/omnichannel/contacts", headers=h, params={"unreplied": "true"})
    ids = {t["id"] for t in res.json()["data"]}
    assert unreplied in ids
    assert replied not in ids


def test_thread_list_sorts(client, session_factory):
    from modules.omnichannel.models import Contact

    now = datetime.now(timezone.utc)
    old_replied = _seed_thread(session_factory, phone="+60133000001", messages=[{"body": "old"}])
    new_unreplied = _seed_thread(session_factory, phone="+60133000002", messages=[{"body": "new"}])
    h = _auth(client)

    db = session_factory()
    a = db.query(Contact).filter(Contact.id == old_replied).first()
    a.last_message_at = now - timedelta(hours=2)
    a.last_incoming_message_at = now - timedelta(hours=2)
    a.last_agent_message_at = now - timedelta(hours=1)
    b = db.query(Contact).filter(Contact.id == new_unreplied).first()
    b.last_message_at = now - timedelta(minutes=5)
    b.last_incoming_message_at = now - timedelta(minutes=5)
    b.last_agent_message_at = None
    db.commit()
    db.close()

    newest = client.get("/omnichannel/contacts", headers=h, params={"sort": "newest"}).json()["data"]
    assert [t["id"] for t in newest if t["id"] in (old_replied, new_unreplied)] == [
        new_unreplied, old_replied,
    ]

    oldest = client.get("/omnichannel/contacts", headers=h, params={"sort": "oldest"}).json()["data"]
    assert [t["id"] for t in oldest if t["id"] in (old_replied, new_unreplied)] == [
        old_replied, new_unreplied,
    ]

    unreplied_first = client.get(
        "/omnichannel/contacts", headers=h, params={"sort": "unreplied_first"}
    ).json()["data"]
    assert unreplied_first[0]["id"] == new_unreplied

    longest_waiting = client.get(
        "/omnichannel/contacts", headers=h, params={"sort": "longest_waiting"}
    ).json()["data"]
    assert longest_waiting[0]["id"] == new_unreplied


def test_thread_list_sort_stable_pagination(client, session_factory):
    for i in range(5):
        _seed_thread(session_factory, phone=f"+6019900000{i}", messages=[{"body": f"m{i}"}])
    h = _auth(client)
    page0 = client.get(
        "/omnichannel/contacts", headers=h, params={"sort": "newest", "page": 0, "pageSize": 2}
    ).json()["data"]
    page1 = client.get(
        "/omnichannel/contacts", headers=h, params={"sort": "newest", "page": 1, "pageSize": 2}
    ).json()["data"]
    ids0 = {t["id"] for t in page0}
    ids1 = {t["id"] for t in page1}
    assert not (ids0 & ids1)


def test_thread_list_assignee_user_mode(client, session_factory):
    admin_thread = _seed_thread(
        session_factory, phone="+60144000001", assigned_email=ACTIVE_EMAIL, messages=[{"body": "hi"}]
    )
    other_thread = _seed_thread(session_factory, phone="+60144000002", messages=[{"body": "hi"}])
    h = _auth(client)
    db = session_factory()
    admin_id = db.query(User).filter(User.email == ACTIVE_EMAIL).first().id
    db.close()

    res = client.get(
        "/omnichannel/contacts", headers=h, params={"assignee": "user", "assigneeUserIds": admin_id}
    )
    ids = {t["id"] for t in res.json()["data"]}
    assert admin_thread in ids
    assert other_thread not in ids


# ── Round-3 codex triage B10: `assignee=user` with no ids is a 422, never
# "every thread regardless of assignee" ─────────────────────────────────────
def test_thread_list_assignee_user_without_ids_is_422(client, session_factory):
    _seed_thread(session_factory, phone="+60144000003", messages=[{"body": "hi"}])
    h = _auth(client)

    res = client.get("/omnichannel/contacts", headers=h, params={"assignee": "user"})
    assert res.status_code == 422

    res2 = client.get(
        "/omnichannel/contacts", headers=h, params={"assignee": "user", "assigneeUserIds": ""}
    )
    assert res2.status_code == 422


# ── Round-3 codex triage B11: a tag/channel id foreign to the tenant is a
# 422, never a silently-empty result set ────────────────────────────────────
def test_thread_list_foreign_tag_id_is_422(client, session_factory):
    _seed_thread(session_factory, phone="+60144000004", messages=[{"body": "hi"}])
    h = _auth(client)

    res = client.get("/omnichannel/contacts", headers=h, params={"tagIds": "not-a-real-tag-id"})
    assert res.status_code == 422


def test_thread_list_view_with_since_deleted_tag_degrades_not_422(client, session_factory):
    """A saved view's stored `tagIds` were already validated at save time -
    if the tag is later hard-deleted, the view keeps degrading gracefully
    (the repo's EXISTS predicate narrows to zero matches) rather than 422ing
    forever. Only a FRESH, explicitly-supplied bogus id (the tests above)
    is rejected."""
    from modules.omnichannel.models import ContactTag
    from modules.omnichannel.schemas import InboxViewCreate
    from modules.omnichannel.services.contact_tag_service import ContactTagService
    from modules.omnichannel.services.inbox_view_service import InboxViewService

    _seed_thread(session_factory, phone="+60144000006", messages=[{"body": "hi"}])
    h = _auth(client)
    ws = _workspace_id(client, h)

    db = session_factory()
    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    tag = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, name="Temp")
    db.add(tag)
    db.flush()
    view = InboxViewService(db).create(
        ws, DEFAULT_TENANT_ID, admin.id,
        InboxViewCreate(name="Stale tag view", isShared=False, filter={"tagIds": [tag.id]}),
    )
    db.commit()
    view_id = view.id
    ContactTagService(db).delete(tag.id, ws, DEFAULT_TENANT_ID)
    db.close()

    res = client.get(
        "/omnichannel/contacts", headers=h, params={"viewId": view_id, "workspaceId": ws}
    )
    assert res.status_code == 200
    assert res.json()["data"] == []


def test_thread_list_foreign_channel_id_is_422(client, session_factory):
    _seed_thread(session_factory, phone="+60144000005", messages=[{"body": "hi"}])
    h = _auth(client)

    res = client.get(
        "/omnichannel/contacts", headers=h, params={"channelIds": "not-a-real-channel-id"}
    )
    assert res.status_code == 422


# ── AC-IVE-18/19: saved-view CRUD + typed filter + permission split ─────────
def test_inbox_view_create_read_own(client):
    h = _auth(client)
    ws = _workspace_id(client, h)

    created = client.post(
        f"{_base(ws)}/inbox-views",
        headers=h,
        json={"name": "My Open", "isShared": False, "filter": {"statuses": ["OPEN"], "unreplied": True}},
    )
    assert created.status_code == 201, created.text
    view_id = created.json()["id"]
    assert created.json()["ownerUserId"]

    listed = client.get(f"{_base(ws)}/inbox-views", headers=h).json()
    assert any(v["id"] == view_id for v in listed)

    updated = client.patch(
        f"{_base(ws)}/inbox-views/{view_id}", headers=h, json={"name": "My Open Renamed"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "My Open Renamed"

    deleted = client.delete(f"{_base(ws)}/inbox-views/{view_id}", headers=h)
    assert deleted.status_code == 204


def test_inbox_view_unknown_filter_key_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(
        f"{_base(ws)}/inbox-views",
        headers=h,
        json={"name": "Bad", "isShared": False, "filter": {"bogusKey": 1}},
    )
    assert res.status_code == 422


def test_inbox_view_id_validated_against_workspace(client, session_factory):
    from modules.omnichannel.models import ContactTag

    h = _auth(client)
    ws = _workspace_id(client, h)
    other_ws = client.post(
        "/omnichannel/workspaces", headers=h, json={"name": "Other WS 2", "status": "ACTIVE"}
    ).json()["id"]

    db = session_factory()
    foreign_tag = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=other_ws, name="Foreign")
    db.add(foreign_tag)
    db.commit()
    foreign_tag_id = foreign_tag.id
    db.close()

    res = client.post(
        f"{_base(ws)}/inbox-views",
        headers=h,
        json={"name": "Bad Tag", "isShared": False, "filter": {"tagIds": [foreign_tag_id]}},
    )
    assert res.status_code == 422


def test_inbox_view_name_unique_case_insensitive(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(
        f"{_base(ws)}/inbox-views", headers=h, json={"name": "Waiting", "isShared": False, "filter": {}}
    )
    dup = client.post(
        f"{_base(ws)}/inbox-views", headers=h, json={"name": "waiting", "isShared": False, "filter": {}}
    )
    assert dup.status_code == 422


def test_inbox_view_own_vs_shared_permission_split(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    h_noperm = _no_perm_auth(client, session_factory, email="ive-view-noperm@example.com")

    # A personal view needs only conversations.read - but noperm has NO
    # permissions at all, so it still 403s (base gate); confirm the ADMIN
    # (who has conversations.read but not inbox_views.manage in a limited
    # role) can create/edit/delete an OWN, non-shared view without manage -
    # since the seeded Admin role holds every module key, prove the split via
    # direct service calls instead (the router branch under test).
    from modules.omnichannel.services.inbox_view_service import InboxViewService
    from modules.omnichannel.schemas import InboxViewCreate

    db = session_factory()
    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    svc = InboxViewService(db)
    personal = svc.create(
        ws, DEFAULT_TENANT_ID, admin.id, InboxViewCreate(name="Personal", isShared=False)
    )
    shared = svc.create(
        ws, DEFAULT_TENANT_ID, admin.id, InboxViewCreate(name="Shared", isShared=True)
    )
    personal_is_shared = personal.is_shared
    shared_is_shared = shared.is_shared
    db.close()

    # Creating a SHARED view without inbox_views.manage 403s at the router.
    assert client.post(
        f"{_base(ws)}/inbox-views",
        headers=h_noperm,
        json={"name": "X", "isShared": True, "filter": {}},
    ).status_code == 403

    assert personal_is_shared is False
    assert shared_is_shared is True


# ── AC-IVE-17: viewId expansion + explicit override + cross-workspace 404 ──
def test_view_id_expansion_and_override(client, session_factory):
    replied = _seed_thread(
        session_factory, phone="+60155000001",
        messages=[{"body": "hi"}, {"sender_type": "AGENT", "body": "hey"}],
    )
    unreplied = _seed_thread(session_factory, phone="+60155000002", messages=[{"body": "hi"}])
    h = _auth(client)
    ws = _workspace_id(client, h)

    from modules.omnichannel.models import Contact

    db = session_factory()
    db.query(Contact).filter(Contact.id == replied).first().last_agent_message_at = (
        db.query(Contact).filter(Contact.id == replied).first().last_message_at
    )
    db.commit()
    db.close()

    view = client.post(
        f"{_base(ws)}/inbox-views",
        headers=h,
        json={"name": "Unreplied View", "isShared": False, "filter": {"unreplied": True}},
    ).json()

    # `workspaceId` sent explicitly (review round 1, finding 7: viewId no
    # longer resolves a workspace on its own - the caller's resolved
    # workspace must match).
    res = client.get(
        "/omnichannel/contacts", headers=h, params={"viewId": view["id"], "workspaceId": ws}
    )
    ids = {t["id"] for t in res.json()["data"]}
    assert unreplied in ids
    assert replied not in ids

    # explicit unreplied=false OVERRIDES the view's stored true.
    res2 = client.get(
        "/omnichannel/contacts",
        headers=h,
        params={"viewId": view["id"], "workspaceId": ws, "unreplied": "false"},
    )
    ids2 = {t["id"] for t in res2.json()["data"]}
    assert replied in ids2


def test_inbox_view_team_ids_saved_validated_and_expanded(client, session_factory):
    """AC-TEM-46 (review round 1, finding 9) - `InboxViewFilter.teamIds` is
    validated tenant-scoped via `team.resolve@1` at save time, and the
    thread-list `viewId` expansion filters by that team (unless an explicit
    `teamId` query param overrides it - AC-IVE-17's same rule)."""
    from modules.omnichannel.models import Contact

    h = _auth(client)
    ws = _workspace_id(client, h)

    team = client.post("/teams", headers=h, json={"name": "Saved View Team", "members": []}).json()
    other_team = client.post("/teams", headers=h, json={"name": "Other Saved Team", "members": []}).json()

    on_team = _seed_thread(session_factory, phone="+60155100001", messages=[{"body": "hi"}])
    off_team = _seed_thread(session_factory, phone="+60155100002", messages=[{"body": "hi"}])
    db = session_factory()
    db.query(Contact).filter(Contact.id == on_team).update({"assigned_team_id": team["id"]})
    db.commit()
    db.close()

    # Unknown team id is rejected at save.
    bad = client.post(
        f"{_base(ws)}/inbox-views",
        headers=h,
        json={"name": "Bad Team View", "isShared": False, "filter": {"teamIds": ["nope"]}},
    )
    assert bad.status_code == 422

    view = client.post(
        f"{_base(ws)}/inbox-views",
        headers=h,
        json={"name": "Team View", "isShared": False, "filter": {"teamIds": [team["id"]]}},
    ).json()
    assert view["filter"]["teamIds"] == [team["id"]]

    res = client.get(
        "/omnichannel/contacts", headers=h, params={"viewId": view["id"], "workspaceId": ws}
    )
    ids = {t["id"] for t in res.json()["data"]}
    assert on_team in ids
    assert off_team not in ids

    # Explicit teamId overrides the view's stored teamIds.
    res2 = client.get(
        "/omnichannel/contacts",
        headers=h,
        params={"viewId": view["id"], "workspaceId": ws, "teamId": other_team["id"]},
    )
    ids2 = {t["id"] for t in res2.json()["data"]}
    assert on_team not in ids2


def test_view_id_unknown_or_cross_tenant_404(client, session_factory):
    h = _auth(client)
    res = client.get("/omnichannel/contacts", headers=h, params={"viewId": "nope"})
    assert res.status_code == 404

    h2 = _other_tenant_auth(client, session_factory, slug="other-ive-view")
    res2 = client.get("/omnichannel/contacts", headers=h2, params={"viewId": "nope"})
    assert res2.status_code == 404


def test_view_id_cross_workspace_404(client, session_factory):
    """Review round 1, finding 7 (AC-IVE-17): a `viewId` from ANOTHER
    workspace of the same tenant 404s - both when the caller sends an
    explicitly conflicting `workspaceId`, AND when the caller sends none at
    all (no cross-workspace portability)."""
    h = _auth(client)
    ws1 = _workspace_id(client, h)
    ws2 = client.post(
        "/omnichannel/workspaces", headers=h, json={"name": "Other WS", "status": "ACTIVE"}
    ).json()["id"]
    view = client.post(
        f"{_base(ws1)}/inbox-views",
        headers=h,
        json={"name": "WS1 View", "isShared": False, "filter": {}},
    ).json()

    # explicit conflicting workspaceId.
    res = client.get(
        "/omnichannel/contacts", headers=h, params={"viewId": view["id"], "workspaceId": ws2}
    )
    assert res.status_code == 404

    # no workspaceId at all - still 404 (view stays scoped to its own
    # workspace, never silently adopted).
    res2 = client.get("/omnichannel/contacts", headers=h, params={"viewId": view["id"]})
    assert res2.status_code == 404

    # matching workspaceId succeeds.
    res3 = client.get(
        "/omnichannel/contacts", headers=h, params={"viewId": view["id"], "workspaceId": ws1}
    )
    assert res3.status_code == 200


def test_segment_id_not_available(client):
    h = _auth(client)
    res = client.get("/omnichannel/contacts", headers=h, params={"segmentId": "seg-1"})
    assert res.status_code == 422


# ── Round-3 codex triage B18: a saved view carrying `segmentId` 422s at
# save AND at expansion - never silently discarded ─────────────────────────
def test_inbox_view_segment_id_rejected_at_create(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(
        f"{_base(ws)}/inbox-views",
        headers=h,
        json={"name": "Segment view", "isShared": False, "filter": {"segmentId": "seg-1"}},
    )
    assert res.status_code == 422


def test_inbox_view_segment_id_rejected_at_expansion(client, session_factory):
    """A row that predates the save-time guard (or is otherwise planted) must
    still 422 on expansion, not silently ignore `segmentId`."""
    from modules.omnichannel.models import InboxView

    h = _auth(client)
    ws = _workspace_id(client, h)

    db = session_factory()
    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    row = InboxView(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, name="Legacy segment view",
        owner_user_id=admin.id, is_shared=False, filter_json={"segmentId": "seg-1"},
    )
    db.add(row)
    db.commit()
    view_id = row.id
    db.close()

    res = client.get(
        "/omnichannel/contacts", headers=h, params={"viewId": view_id, "workspaceId": ws}
    )
    assert res.status_code == 422


# ── Round-3 codex triage B17: a name-uniqueness race is a 422, never a 500 ──
def test_inbox_view_create_race_is_422_not_500(session_factory):
    from sqlalchemy.exc import IntegrityError

    from modules.omnichannel.schemas import InboxViewCreate
    from modules.omnichannel.services.inbox_view_service import (
        InboxViewService,
        InboxViewValidationError,
    )

    db = session_factory()
    ws = _workspace_id_direct(db)
    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    svc = InboxViewService(db)
    svc._find_by_name = lambda *a, **k: None

    real_commit = db.commit
    calls = {"n": 0}

    def fake_commit(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("insert", {}, Exception("duplicate key value"))
        return real_commit(*a, **kw)

    db.commit = fake_commit
    try:
        with pytest.raises(InboxViewValidationError):
            svc.create(ws, DEFAULT_TENANT_ID, admin.id, InboxViewCreate(name="Racy View", isShared=False))
    finally:
        db.commit = real_commit

    from modules.omnichannel.models import InboxView

    assert (
        db.query(InboxView.id)
        .filter(InboxView.workspace_id == ws, InboxView.name == "Racy View")
        .count()
        == 0
    )


# ── AC-IVE-41/42: permission CSV + tenant isolation on every new route ──────
def test_permission_csv_new_keys_present():
    from app.services.permission_service import load_csv
    from modules.omnichannel.bootstrap import MODULE_CSV

    rows = load_csv(MODULE_CSV)
    keys = {(r["resource"], r["action"]) for r in rows}
    assert ("close_reasons", "manage") in keys
    assert ("inbox_views", "manage") in keys
    assert ("conversations", "shortcut") in keys


def test_admin_grant_includes_new_keys_after_module_update(session_factory):
    """AC-IVE-41: the App Store update path grants the new keys to the
    tenant's Admin role. Simulate a tenant stuck on a version before this
    slice, then run the same update the App Store would."""
    from app.models.module import TenantModule
    from app.models.role import Role
    from app.services.app_store_service import AppStoreService

    db = session_factory()
    state = (
        db.query(TenantModule)
        .join(TenantModule.module)
        .filter(TenantModule.tenant_id == DEFAULT_TENANT_ID)
        .first()
    )
    state.installed_version = "0.3.0"
    db.commit()

    AppStoreService(db).update(DEFAULT_TENANT_ID, "omnichannel")
    admin = db.query(Role).filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin").first()
    keys = {p.key for p in admin.permissions}
    assert "close_reasons.manage" in keys
    assert "inbox_views.manage" in keys
    assert "conversations.shortcut" in keys
    db.close()


# ── AC-IVE-18: cap 50 saved views per workspace ─────────────────────────────
def test_inbox_view_cap_50_per_workspace(client, session_factory):
    from modules.omnichannel.schemas import InboxViewCreate
    from modules.omnichannel.services.inbox_view_service import (
        InboxViewService,
        InboxViewValidationError,
    )

    h = _auth(client)
    ws = _workspace_id(client, h)
    db = session_factory()
    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    svc = InboxViewService(db)
    for i in range(50):
        svc.create(ws, DEFAULT_TENANT_ID, admin.id, InboxViewCreate(name=f"View {i}"))
    try:
        svc.create(ws, DEFAULT_TENANT_ID, admin.id, InboxViewCreate(name="One too many"))
        raised = False
    except InboxViewValidationError:
        raised = True
    assert raised
    db.close()


# ── AC-IVE-25: cap 100 close reasons per workspace ──────────────────────────
def test_close_reason_cap_100_per_workspace(session_factory):
    from modules.omnichannel.services.close_reason_service import (
        CloseReasonService,
        CloseReasonValidationError,
    )

    class _Payload:
        def __init__(self, name):
            self.name = name
            self.sortOrder = None
            self.isActive = None

    db = session_factory()
    svc = CloseReasonService(db)
    ws = _workspace_id_direct(db)
    # 4 are already seeded; fill up to 100.
    for i in range(96):
        svc.create(ws, DEFAULT_TENANT_ID, _Payload(f"Reason {i}"))
    try:
        svc.create(ws, DEFAULT_TENANT_ID, _Payload("One too many"))
        raised = False
    except CloseReasonValidationError:
        raised = True
    assert raised
    db.close()


def _workspace_id_direct(db) -> str:
    from modules.omnichannel.models import Workspace

    return (
        db.query(Workspace)
        .filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True))
        .first()
        .id
    )


# ── AC-IVE-19: own-vs-shared permission split, router-enforced ─────────────
def _limited_role_auth(client, session_factory, *, keys, email):
    from app.models import Role
    from app.repositories.permission_repository import PermissionRepository

    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"Limited {email}")
    role.permissions = PermissionRepository(db).get_by_keys(keys)
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email=email, name="Limited",
        password=hash_password("Password123!"), status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    user_id = user.id
    db.close()
    return _auth(client, email=email, password="Password123!"), user_id


def test_inbox_view_own_view_needs_only_conversations_read(client, session_factory):
    ws = _workspace_id(client, _auth(client))
    h_limited, _ = _limited_role_auth(
        client, session_factory, keys=["conversations.read"], email="ive-view-limited@example.com"
    )

    created = client.post(
        f"{_base(ws)}/inbox-views",
        headers=h_limited,
        json={"name": "My Own View", "isShared": False, "filter": {}},
    )
    assert created.status_code == 201, created.text
    view_id = created.json()["id"]

    updated = client.patch(
        f"{_base(ws)}/inbox-views/{view_id}", headers=h_limited, json={"name": "Renamed Own"}
    )
    assert updated.status_code == 200

    deleted = client.delete(f"{_base(ws)}/inbox-views/{view_id}", headers=h_limited)
    assert deleted.status_code == 204


def test_inbox_view_someone_elses_view_needs_manage(client, session_factory):
    h_admin = _auth(client)
    ws = _workspace_id(client, h_admin)
    others_view = client.post(
        f"{_base(ws)}/inbox-views",
        headers=h_admin,
        json={"name": "Admin's Own", "isShared": False, "filter": {}},
    ).json()

    h_limited, _ = _limited_role_auth(
        client, session_factory, keys=["conversations.read"], email="ive-view-limited2@example.com"
    )

    assert client.patch(
        f"{_base(ws)}/inbox-views/{others_view['id']}", headers=h_limited, json={"name": "Hijack"}
    ).status_code == 403
    assert client.delete(
        f"{_base(ws)}/inbox-views/{others_view['id']}", headers=h_limited
    ).status_code == 403


def test_inbox_view_shared_view_needs_manage_to_edit(client, session_factory):
    from modules.omnichannel.schemas import InboxViewCreate
    from modules.omnichannel.services.inbox_view_service import InboxViewService

    ws = _workspace_id(client, _auth(client))
    h_limited, limited_user_id = _limited_role_auth(
        client, session_factory, keys=["conversations.read", "inbox_views.manage"],
        email="ive-view-manage@example.com",
    )

    # A shared view owned by someone else - even WITH inbox_views.manage the
    # user may edit it (that IS the manage grant's purpose), but creating a
    # NEW shared view needs it too - prove both directions.
    created_shared = client.post(
        f"{_base(ws)}/inbox-views",
        headers=h_limited,
        json={"name": "Team View", "isShared": True, "filter": {}},
    )
    assert created_shared.status_code == 201, created_shared.text

    h_readonly, _ = _limited_role_auth(
        client, session_factory, keys=["conversations.read"], email="ive-view-readonly@example.com",
    )
    assert client.patch(
        f"{_base(ws)}/inbox-views/{created_shared.json()['id']}",
        headers=h_readonly,
        json={"name": "Hijack Shared"},
    ).status_code == 403


# ── AC-IVE-28 (fan-out): close route publishes contact.updated exactly once ─
def test_close_route_publishes_contact_updated_once(client, session_factory):
    from modules.omnichannel.models import Channel, ContactChannelIdentity, WebhookDelivery
    from modules.omnichannel.services.webhook_service import WebhookService

    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    reason_id = client.get(f"{_base(ws)}/close-reasons", headers=h).json()[0]["id"]

    db = session_factory()
    channel = db.query(Channel).first()
    db.add(ContactChannelIdentity(
        tenant_id=DEFAULT_TENANT_ID, contact_id=cid, channel_id=channel.id,
        external_user_id="60123456789",
    ))
    db.commit()
    WebhookService(db).create(
        DEFAULT_TENANT_ID, channel.id,
        "probe", "https://example.com/webhook", ["contact.updated"], None,
    )
    db.commit()
    db.close()

    res = client.post(
        f"/omnichannel/contacts/{cid}/close", headers=h, json={"closeReasonId": reason_id}
    )
    assert res.status_code == 200

    db2 = session_factory()
    deliveries = (
        db2.query(WebhookDelivery)
        .filter(WebhookDelivery.tenant_id == DEFAULT_TENANT_ID, WebhookDelivery.event_type == "contact.updated")
        .all()
    )
    assert len(deliveries) == 1
    db2.close()


def test_tenant_isolation_on_new_routes(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    reason_id = client.get(f"{_base(ws)}/close-reasons", headers=h).json()[0]["id"]
    view = client.post(
        f"{_base(ws)}/inbox-views", headers=h, json={"name": "Mine", "isShared": False, "filter": {}}
    ).json()

    h2 = _other_tenant_auth(client, session_factory, slug="other-ive-iso")
    assert client.get(f"{_base(ws)}/close-reasons", headers=h2).status_code == 404
    assert client.post(
        f"{_base(ws)}/close-reasons", headers=h2, json={"name": "X"}
    ).status_code == 404
    assert client.patch(
        f"{_base(ws)}/close-reasons/{reason_id}", headers=h2, json={"name": "X"}
    ).status_code == 404
    assert client.delete(f"{_base(ws)}/close-reasons/{reason_id}", headers=h2).status_code == 404

    assert client.get(f"{_base(ws)}/inbox-views", headers=h2).status_code == 404
    assert client.post(
        f"{_base(ws)}/inbox-views", headers=h2, json={"name": "X", "isShared": False, "filter": {}}
    ).status_code == 404
    assert client.patch(
        f"{_base(ws)}/inbox-views/{view['id']}", headers=h2, json={"name": "X"}
    ).status_code == 404
    assert client.delete(f"{_base(ws)}/inbox-views/{view['id']}", headers=h2).status_code == 404

    assert client.post(
        f"/omnichannel/contacts/{cid}/close", headers=h2, json={"closeReasonId": reason_id}
    ).status_code == 404


# ── review round 1, finding 2: migration timestamps carry server_default ───
def test_migration_0009a_declares_created_updated_defaults(monkeypatch):
    """Asserted by READING the revision (pytest never runs module Alembic -
    it is Postgres-only, `run_module_migrations` no-ops under sqlite). House
    convention (`0008`) is `server_default=sa.func.now()` on `created_at` AND
    `updated_at` - without it a row inserted through raw DDL on a live
    Postgres host (rather than the ORM's own `UTCDateTime(server_default=...)`
    default) would violate NOT NULL."""
    import importlib.util
    import pathlib
    import types

    spec = importlib.util.spec_from_file_location(
        "_omni_rev_0009a",
        pathlib.Path(__file__).resolve().parents[1]
        / "modules/omnichannel/alembic/versions/0009a_omni_inbox_views.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert len(module.revision) <= 32
    assert module.down_revision == "0009_omni_conversation_events"

    created_tables: dict = {}

    def fake_create_table(name, *columns, **kwargs):
        created_tables[name] = {c.name: c for c in columns}

    class _FakeInspector:
        def get_table_names(self, schema=None):
            return []

        def get_indexes(self, table, schema=None):
            return []

        def get_foreign_keys(self, table, schema=None):
            return []

    monkeypatch.setattr(module.sa, "inspect", lambda bind: _FakeInspector())
    module.op = types.SimpleNamespace(
        get_bind=lambda: None,
        create_table=fake_create_table,
        create_foreign_key=lambda *a, **k: None,
        execute=lambda *a, **k: None,
    )
    module.upgrade()

    assert set(created_tables) == {"close_reasons", "inbox_views"}
    for table_name in ("close_reasons", "inbox_views"):
        cols = created_tables[table_name]
        for col_name in ("created_at", "updated_at"):
            col = cols[col_name]
            assert col.nullable is False
            assert col.server_default is not None, (
                f"{table_name}.{col_name} must carry server_default=sa.func.now()"
            )


# ── Round-3 codex triage B12: saved-view visibility ("me" ownership) and
# `assignee=me` authorize as the EFFECTIVE user under impersonation, not the
# real admin's attribution id ────────────────────────────────────────────────
def test_view_and_assignee_me_resolve_as_effective_user_under_impersonation(client, session_factory):
    from app.models import Role
    from app.repositories.permission_repository import PermissionRepository
    from modules.omnichannel.schemas import InboxViewCreate
    from modules.omnichannel.services.inbox_view_service import InboxViewService

    h = _auth(client)
    ws = _workspace_id(client, h)
    mine = _seed_thread(session_factory, phone="+60166000001", messages=[{"body": "hi"}])

    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Impersonated Agent (IVE B12)")
    role.permissions = PermissionRepository(db).get_by_keys(["conversations.read"])
    db.add(role)
    db.flush()
    target = User(
        tenant_id=DEFAULT_TENANT_ID, email="ive-b12-target@example.com", name="Target Agent",
        password=hash_password("Password123!"), status=UserStatus.ACTIVE.value,
    )
    target.roles = [role]
    db.add(target)
    db.flush()
    target_id = target.id

    from modules.omnichannel.models import Contact

    db.query(Contact).filter(Contact.id == mine).first().assigned_user_id = target_id

    personal_view = InboxViewService(db).create(
        ws, DEFAULT_TENANT_ID, target_id, InboxViewCreate(name="Target's own", isShared=False)
    )
    view_id = personal_view.id
    db.commit()
    db.close()

    start = client.post("/impersonation/start", headers=h, json={"targetUserId": target_id})
    assert start.status_code == 200, start.text
    headers = {**h, "X-Impersonate-User-Id": target_id}

    # `viewId` expansion: the view is owned by the EFFECTIVE user (the
    # impersonated target) - if the bug regresses (checked against the real
    # admin's id instead) this 404s.
    res = client.get(
        "/omnichannel/contacts", headers=headers, params={"viewId": view_id, "workspaceId": ws}
    )
    assert res.status_code == 200, res.text

    # `assignee=me` resolves to the EFFECTIVE user's assigned threads.
    res2 = client.get("/omnichannel/contacts", headers=headers, params={"assignee": "me"})
    assert res2.status_code == 200
    ids2 = {t["id"] for t in res2.json()["data"]}
    assert mine in ids2
