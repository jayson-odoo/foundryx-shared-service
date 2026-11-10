"""Omnichannel Contacts module - plan 26 S2 (manual create + bulk
assign/tags/lifecycle). Covers AC-CTM-24..33.
"""
from datetime import datetime, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.phone import digits_only
from tests.conftest import ACTIVE_EMAIL
from tests.test_omnichannel_contacts_module import (
    _auth,
    _base,
    _ensure_channel,
    _lifecycle_ids,
    _no_perm_auth,
    _other_tenant_auth,
    _seed_contact,
    _tag_id,
    _workspace_id,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── AC-CTM-24: create happy path ─────────────────────────────────────────────
def test_create_happy_path(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    lifecycle = _lifecycle_ids(session_factory, ws)

    res = client.post(
        f"{_base(ws)}/contacts",
        headers=h,
        json={"firstName": "Nadia", "lastName": "Khan", "phone": "+60 12-999 8877", "email": "nadia@example.com"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["firstName"] == "Nadia"
    assert body["lastName"] == "Khan"
    assert body["phone"] == "+60129998877"
    assert body["email"] == "nadia@example.com"
    assert body["status"] == "OPEN"
    assert body["priority"] == "MEDIUM"
    assert body["channels"] == []
    # Default lifecycle stage = the workspace's is_initial stage.
    assert body["lifecycle"]["statusId"] == lifecycle["new_lead"]

    from modules.omnichannel.models import Contact

    db = session_factory()
    row = db.query(Contact).filter(Contact.id == body["id"]).first()
    assert row.phone_digits == "60129998877"
    db.close()


def test_create_sets_explicit_lifecycle_stage(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    lifecycle = _lifecycle_ids(session_factory, ws)

    res = client.post(
        f"{_base(ws)}/contacts",
        headers=h,
        json={"phone": "+60 12-000 1111", "lifecycleStatusId": lifecycle["hot_lead"]},
    )
    assert res.status_code == 201
    assert res.json()["lifecycle"]["statusId"] == lifecycle["hot_lead"]


def test_create_with_tags_and_custom_fields(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(f"{_base(ws)}/contact-fields", headers=h, json={"key": "company", "label": "Company", "type": "text"})
    tag = client.post(f"{_base(ws)}/contact-tags", headers=h, json={"name": "Lead"}).json()

    res = client.post(
        f"{_base(ws)}/contacts",
        headers=h,
        json={
            "phone": "+60 12-222 3344",
            "tagIds": [tag["id"]],
            "customFields": {"company": "Acme"},
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert [t["id"] for t in body["tags"]] == [tag["id"]]
    assert body["customFields"] == {"company": "Acme"}


# ── AC-CTM-25: phone required + normalized + unique per workspace ───────────
def test_create_phone_required_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    # Omitted entirely - FastAPI's own pydantic required-field 422 (list-shaped
    # `detail`, since `phone` has no default).
    res = client.post(f"{_base(ws)}/contacts", headers=h, json={"firstName": "NoPhone"})
    assert res.status_code == 422
    # Sent blank - reaches the service's own validation (dict-shaped `fieldErrors`).
    res2 = client.post(f"{_base(ws)}/contacts", headers=h, json={"phone": ""})
    assert res2.status_code == 422
    assert "phone" in res2.json()["detail"]["fieldErrors"]


def test_create_phone_no_digits_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(f"{_base(ws)}/contacts", headers=h, json={"phone": "n/a"})
    assert res.status_code == 422
    assert "phone" in res.json()["detail"]["fieldErrors"]


def test_create_duplicate_phone_422_nothing_written(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    _seed_contact(session_factory, ws, first="First", phone="+60 12-345 6789")

    before = client.get(f"{_base(ws)}/contacts", headers=h).json()["total"]
    # Same digits, different formatting - the uniqueness check is digit-based.
    res = client.post(f"{_base(ws)}/contacts", headers=h, json={"firstName": "Dup", "phone": "+60-12-345-6789"})
    assert res.status_code == 422
    assert "phone" in res.json()["detail"]["fieldErrors"]
    after = client.get(f"{_base(ws)}/contacts", headers=h).json()["total"]
    assert after == before


def test_create_customfield_and_tag_422_writes_nothing(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    before = client.get(f"{_base(ws)}/contacts", headers=h).json()["total"]

    res = client.post(
        f"{_base(ws)}/contacts",
        headers=h,
        json={"phone": "+60 19-000 2222", "customFields": {"nope": "x"}},
    )
    assert res.status_code == 422
    assert "customFields.nope" in res.json()["detail"]["fieldErrors"]

    res2 = client.post(
        f"{_base(ws)}/contacts",
        headers=h,
        json={"phone": "+60 19-000 3333", "tagIds": ["not-a-real-tag"]},
    )
    assert res2.status_code == 422
    assert "tagIds" in res2.json()["detail"]["fieldErrors"]

    after = client.get(f"{_base(ws)}/contacts", headers=h).json()["total"]
    assert after == before


def test_create_unknown_lifecycle_id_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(
        f"{_base(ws)}/contacts", headers=h, json={"phone": "+60 19-555 6666", "lifecycleStatusId": "not-a-stage"}
    )
    assert res.status_code == 422
    assert "lifecycleStatusId" in res.json()["detail"]["fieldErrors"]


def test_create_bad_language_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(
        f"{_base(ws)}/contacts", headers=h, json={"phone": "+60 19-777 8888", "language": "not-a-valid-tag!!"}
    )
    assert res.status_code == 422
    assert "language" in res.json()["detail"]["fieldErrors"]


# ── AC-CTM-26: stitch equivalence - create then inbound from same number ────
def test_create_then_inbound_stitches_onto_same_contact(client, session_factory):
    """The create path normalizes phone exactly the way the stitch compares it
    (`ContactRepository.find_by_phone_digits`/`find_by_phone_in_workspace` -
    the SAME lookup `InboundService._resolve_contact` calls) - a manually
    created contact with phone X must be the contact an inbound from X
    stitches onto, never a duplicate row."""
    from modules.omnichannel.repositories.contact_repository import ContactRepository

    h = _auth(client)
    ws = _workspace_id(client, h)
    _ensure_channel(session_factory, ws, channel_type="WHATSAPP")

    res = client.post(f"{_base(ws)}/contacts", headers=h, json={"firstName": "Stitchy", "phone": "+60 17-333 4455"})
    assert res.status_code == 201
    created_id = res.json()["id"]

    db = session_factory()
    found = ContactRepository(db).find_by_phone_in_workspace(
        digits_only("+60 17-333 4455"), ws, DEFAULT_TENANT_ID
    )
    assert found is not None and found.id == created_id
    db.close()


# ── AC-CTM-27: phone_digits maintained, indexed lookup ──────────────────────
def test_create_stamps_phone_digits(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    from modules.omnichannel.models import Contact

    res = client.post(f"{_base(ws)}/contacts", headers=h, json={"phone": "+60 13-222 1111"})
    cid = res.json()["id"]
    db = session_factory()
    row = db.query(Contact).filter(Contact.id == cid).first()
    assert row.phone_digits == "60132221111"
    db.close()


# ── AC-CTM-28: PATCH /contacts/{id} phone stays rejected (pre-existing S1
# guard - regression-pinned here since S2 is the phone-write-path slice) ────
def test_patch_thread_phone_still_rejected(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    target = _seed_contact(session_factory, ws, first="Immutable", phone="+60 11-000 0000")

    res = client.patch(f"/omnichannel/contacts/{target}", headers=h, json={"phone": "+60 11-999 9999"})
    assert res.status_code == 422
    assert "phone" in res.json()["detail"]["fieldErrors"]

    db = session_factory()
    from modules.omnichannel.models import Contact

    row = db.query(Contact).filter(Contact.id == target).first()
    assert row.phone == "+60 11-000 0000"
    db.close()


# ── AC-CTM-29: bulk assign ───────────────────────────────────────────────────
def test_bulk_assign_partial_failure_isolated(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    a = _seed_contact(session_factory, ws, first="A")
    b = _seed_contact(session_factory, ws, first="B")
    me = client.get("/auth/me", headers=h).json()

    res = client.post(
        f"{_base(ws)}/contacts/bulk/assign",
        headers=h,
        json={"ids": [a, b, "bogus-id"], "assigneeUserId": me["id"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body["ok"]) == {a, b}
    assert body["failed"] == [{"id": "bogus-id", "error": "not_found"}]

    from modules.omnichannel.models import Contact

    db = session_factory()
    assert db.query(Contact).filter(Contact.id == a).first().assigned_user_id == me["id"]
    assert db.query(Contact).filter(Contact.id == b).first().assigned_user_id == me["id"]
    db.close()


def test_bulk_assign_spans_multiple_batches_failure_in_second_batch(client, session_factory, monkeypatch):
    """Nit 22 (review round 1, AC-CTM-32): a request spanning MORE than one
    `BULK_BATCH_SIZE` chunk, with the failing id in the SECOND batch - the
    first batch's successes must commit independently (per-batch `commit()`,
    never all-or-nothing across the whole id set)."""
    from modules.omnichannel.services import contact_admin_service as svc

    monkeypatch.setattr(svc, "BULK_BATCH_SIZE", 2)
    h = _auth(client)
    ws = _workspace_id(client, h)
    a = _seed_contact(session_factory, ws, first="A")
    b = _seed_contact(session_factory, ws, first="B")
    c = _seed_contact(session_factory, ws, first="C")
    me = client.get("/auth/me", headers=h).json()

    # batch 1 = [a, b] (both valid), batch 2 = [c, bogus] (one fails).
    res = client.post(
        f"{_base(ws)}/contacts/bulk/assign",
        headers=h,
        json={"ids": [a, b, c, "bogus-id"], "assigneeUserId": me["id"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body["ok"]) == {a, b, c}
    assert body["failed"] == [{"id": "bogus-id", "error": "not_found"}]

    from modules.omnichannel.models import Contact

    db = session_factory()
    for cid in (a, b, c):
        assert db.query(Contact).filter(Contact.id == cid).first().assigned_user_id == me["id"]
    db.close()


def test_bulk_assign_unassign_with_null(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    me = client.get("/auth/me", headers=h).json()
    a = _seed_contact(session_factory, ws, first="A", assigned_email=ACTIVE_EMAIL)

    res = client.post(
        f"{_base(ws)}/contacts/bulk/assign", headers=h, json={"ids": [a], "assigneeUserId": None}
    )
    assert res.status_code == 200
    assert res.json()["ok"] == [a]

    from modules.omnichannel.models import Contact

    db = session_factory()
    assert db.query(Contact).filter(Contact.id == a).first().assigned_user_id is None
    db.close()


def test_bulk_assign_unknown_assignee_fails_every_id(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    a = _seed_contact(session_factory, ws, first="A")
    b = _seed_contact(session_factory, ws, first="B")

    res = client.post(
        f"{_base(ws)}/contacts/bulk/assign",
        headers=h,
        json={"ids": [a, b], "assigneeUserId": "not-a-real-user"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] == []
    assert {f["id"] for f in body["failed"]} == {a, b}
    assert all(f["error"] == "Assignee not found in this tenant." for f in body["failed"])


def test_bulk_assign_cross_tenant_and_cross_workspace_ids_are_not_found(client, session_factory):
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    h = _auth(client)
    ws = _workspace_id(client, h)
    own = _seed_contact(session_factory, ws, first="Own")

    db = session_factory()
    other_ws = Workspace(
        tenant_id=DEFAULT_TENANT_ID, name="Second WS",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
    )
    db.add(other_ws)
    db.commit()
    other_ws_id = other_ws.id
    db.close()
    foreign_ws_contact = _seed_contact(session_factory, other_ws_id, first="ForeignWs")

    h2 = _other_tenant_auth(client, session_factory)
    ws2 = _workspace_id(client, h2)
    foreign_tenant_contact = _seed_contact(session_factory, ws2, first="ForeignTenant")

    res = client.post(
        f"{_base(ws)}/contacts/bulk/assign",
        headers=h,
        json={"ids": [own, foreign_ws_contact, foreign_tenant_contact], "assigneeUserId": None},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] == [own]
    reasons = {f["id"]: f["error"] for f in body["failed"]}
    assert reasons[foreign_ws_contact] == "not_found"
    assert reasons[foreign_tenant_contact] == "not_found"


def test_bulk_ids_cap_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(
        f"{_base(ws)}/contacts/bulk/assign",
        headers=h,
        json={"ids": [f"id-{i}" for i in range(501)], "assigneeUserId": None},
    )
    assert res.status_code == 422


def test_bulk_assign_permission_403_and_tenant_404(client, session_factory):
    h_none = _no_perm_auth(client, session_factory)
    h = _auth(client)
    ws = _workspace_id(client, h)
    a = _seed_contact(session_factory, ws, first="A")

    assert client.post(
        f"{_base(ws)}/contacts/bulk/assign", headers=h_none, json={"ids": [a], "assigneeUserId": None}
    ).status_code == 403

    h2 = _other_tenant_auth(client, session_factory, slug="ctm-bulk-tenant")
    assert client.post(
        f"{_base(ws)}/contacts/bulk/assign", headers=h2, json={"ids": [a], "assigneeUserId": None}
    ).status_code == 404


# ── AC-CTM-30: bulk tags ─────────────────────────────────────────────────────
def test_bulk_tags_add_and_remove_math(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(f"{_base(ws)}/contact-tags", headers=h, json={"name": "VIP"})
    client.post(f"{_base(ws)}/contact-tags", headers=h, json={"name": "Cold"})
    vip = _tag_id(session_factory, ws, "VIP")
    cold = _tag_id(session_factory, ws, "Cold")
    a = _seed_contact(session_factory, ws, first="A", tag_names=["Cold"])
    b = _seed_contact(session_factory, ws, first="B")

    res = client.post(
        f"{_base(ws)}/contacts/bulk/tags",
        headers=h,
        json={"ids": [a, b], "mode": "add", "tagIds": [vip]},
    )
    assert res.status_code == 200
    assert set(res.json()["ok"]) == {a, b}

    res2 = client.get(f"{_base(ws)}/contacts", headers=h).json()["data"]
    by_id = {c["id"]: {t["id"] for t in c["tags"]} for c in res2}
    assert by_id[a] == {vip, cold}
    assert by_id[b] == {vip}

    res3 = client.post(
        f"{_base(ws)}/contacts/bulk/tags",
        headers=h,
        json={"ids": [a], "mode": "remove", "tagIds": [cold]},
    )
    assert res3.status_code == 200
    res4 = client.get(f"{_base(ws)}/contacts", headers=h).json()["data"]
    by_id2 = {c["id"]: {t["id"] for t in c["tags"]} for c in res4}
    assert by_id2[a] == {vip}


def test_bulk_tags_foreign_tag_id_422_writes_nothing(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    a = _seed_contact(session_factory, ws, first="A", tag_names=[])

    res = client.post(
        f"{_base(ws)}/contacts/bulk/tags",
        headers=h,
        json={"ids": [a], "mode": "add", "tagIds": ["not-a-real-tag"]},
    )
    assert res.status_code == 422
    assert "tagIds" in res.json()["detail"]["fieldErrors"]

    data = client.get(f"{_base(ws)}/contacts", headers=h).json()["data"]
    row = next(c for c in data if c["id"] == a)
    assert row["tags"] == []


def test_bulk_tags_partial_failure_isolated(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(f"{_base(ws)}/contact-tags", headers=h, json={"name": "VIP"})
    vip = _tag_id(session_factory, ws, "VIP")
    a = _seed_contact(session_factory, ws, first="A")

    res = client.post(
        f"{_base(ws)}/contacts/bulk/tags",
        headers=h,
        json={"ids": [a, "bogus-id"], "mode": "add", "tagIds": [vip]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] == [a]
    assert body["failed"] == [{"id": "bogus-id", "error": "not_found"}]


# ── AC-CTM-31: bulk lifecycle ─────────────────────────────────────────────────
def test_bulk_lifecycle_move_and_no_edge_failure(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    lifecycle = _lifecycle_ids(session_factory, ws)
    a = _seed_contact(session_factory, ws, first="A", lifecycle_key="new_lead")
    won = _seed_contact(session_factory, ws, first="Won", lifecycle_key="customer")  # terminal, no outgoing edges

    res = client.post(
        f"{_base(ws)}/contacts/bulk/lifecycle",
        headers=h,
        json={"ids": [a, won], "toStatusId": lifecycle["hot_lead"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] == [a]
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == won
    assert "No transition" in body["failed"][0]["error"]

    from modules.omnichannel.models import Contact

    db = session_factory()
    assert db.query(Contact).filter(Contact.id == a).first().lifecycle_status_id == lifecycle["hot_lead"]
    assert db.query(Contact).filter(Contact.id == won).first().lifecycle_status_id == lifecycle["customer"]
    db.close()


def test_bulk_lifecycle_unknown_target_stage_fails_every_record(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    a = _seed_contact(session_factory, ws, first="A", lifecycle_key="new_lead")
    b = _seed_contact(session_factory, ws, first="B", lifecycle_key="new_lead")

    res = client.post(
        f"{_base(ws)}/contacts/bulk/lifecycle",
        headers=h,
        json={"ids": [a, b], "toStatusId": "not-a-real-stage"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] == []
    assert {f["id"] for f in body["failed"]} == {a, b}
    assert all(f["error"] == "Lifecycle stage not found in this workspace." for f in body["failed"])


def test_bulk_lifecycle_permission_403_and_response_shape(client, session_factory):
    h_none = _no_perm_auth(client, session_factory)
    h = _auth(client)
    ws = _workspace_id(client, h)
    a = _seed_contact(session_factory, ws, first="A", lifecycle_key="new_lead")
    lifecycle = _lifecycle_ids(session_factory, ws)

    assert client.post(
        f"{_base(ws)}/contacts/bulk/lifecycle",
        headers=h_none,
        json={"ids": [a], "toStatusId": lifecycle["hot_lead"]},
    ).status_code == 403

    res = client.post(
        f"{_base(ws)}/contacts/bulk/lifecycle",
        headers=h,
        json={"ids": [a], "toStatusId": lifecycle["hot_lead"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"ok", "failed"}
    assert isinstance(body["ok"], list) and isinstance(body["failed"], list)


# ── AC-CTM-33: create + bulk publish contact.updated (realtime + webhook) ──
def test_create_and_bulk_publish_contact_updated(client, session_factory, monkeypatch):
    from modules.omnichannel.services import realtime

    published = []
    monkeypatch.setattr(realtime, "publish", lambda ws_id, payload: published.append((ws_id, payload)))

    h = _auth(client)
    ws = _workspace_id(client, h)

    res = client.post(f"{_base(ws)}/contacts", headers=h, json={"phone": "+60 18-111 2222"})
    assert res.status_code == 201
    assert any(p[1].get("type") == "contact.updated" for p in published)

    published.clear()
    a = _seed_contact(session_factory, ws, first="A")
    client.post(
        f"{_base(ws)}/contacts/bulk/assign", headers=h, json={"ids": [a], "assigneeUserId": None}
    )
    assert any(p[1].get("type") == "contact.updated" for p in published)
