"""Ideation round 2 (#94) - requester status updates event feed
(AC-94-61..71; AC-94-72's contract doc is a reviewer checklist item, not a
test).

TEST-FIRST (PRINCIPLES.md): `idea_status_events` (table + model), the
`services/status_events.py` subscriber, `GET /ideation/intake/status-events`
and the merge/unmerge event writes don't exist yet (plan section 7). Every
test here is expected to fail with an `ImportError` (no `IdeaStatusEvent`
model, no `status_events` module) or a 404 (missing feed route) until slice
S4 lands.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


# ── fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def ideation_client(ideation_session_factory):
    def override_get_db():
        db = ideation_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = ideation_session_factory
        yield c
    app.dependency_overrides.clear()


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _create_software_product(client, h, name="Sorento CRM") -> str:
    res = client.post("/products", headers=h, json={"name": name, "kind": "software"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _default_workspace_id(db) -> str:
    from modules.omnichannel.models import Workspace

    ws = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True))
        .first()
    )
    assert ws is not None, "omnichannel default workspace not seeded"
    return ws.id


def _mint_key(factory) -> str:
    from modules.omnichannel.services.api_key_service import ApiKeyService

    db = factory()
    try:
        _row, full_key = ApiKeyService(db).mint(
            DEFAULT_TENANT_ID, _default_workspace_id(db), "intake", None
        )
        return full_key
    finally:
        db.close()


def _key_auth(key) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _make_contact(factory, first_name="Ah", last_name="Seng", phone="+60123456789") -> str:
    from modules.omnichannel.models import Contact

    db = factory()
    try:
        c = Contact(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=_default_workspace_id(db),
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


def _insert_idea(
    factory,
    product_id,
    *,
    problem="a whatsapp-captured idea",
    status_key="captured",
    tenant_id=DEFAULT_TENANT_ID,
    is_test=False,
    submitter_contact_id=None,
) -> str:
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    db = factory()
    try:
        idea = Idea(
            tenant_id=tenant_id,
            product_id=product_id,
            status_id=idea_status_id(db, status_key, tenant_id),
            intake_definition_key="ideation",
            problem=problem,
            raw_text=problem,
            source="whatsapp",
            is_test=is_test,
            submitter_contact_id=submitter_contact_id,
            captured_json={"problem": problem},
        )
        db.add(idea)
        db.commit()
        return idea.id
    finally:
        db.close()


def _transition(client, h, idea_id, status_key):
    return client.post(f"/ideation/ideas/{idea_id}/status", headers=h, json={"status": status_key})


def _setup_with_contact(ideation_client, *, problem="a whatsapp-captured idea", phone="+60123456789"):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    factory = ideation_client._factory
    contact_id = _make_contact(factory, phone=phone)
    idea_id = _insert_idea(
        factory, pid, problem=problem, status_key="captured", submitter_contact_id=contact_id
    )
    key = _mint_key(factory)
    return {
        "client": ideation_client,
        "h": h,
        "product_id": pid,
        "idea_id": idea_id,
        "contact_id": contact_id,
        "key": key,
        "phone": phone,
    }


def _events_for(factory, idea_id):
    from modules.ideation.models import IdeaStatusEvent

    db = factory()
    try:
        return (
            db.query(IdeaStatusEvent)
            .filter(IdeaStatusEvent.idea_id == idea_id)
            .order_by(IdeaStatusEvent.seq.asc())
            .all()
        )
    finally:
        db.close()


def _age_events(factory, idea_id, seconds=10):
    """Push every event row for `idea_id` outside the 5s settle window
    (AC-94-68) without a real `time.sleep` in the test suite."""
    from modules.ideation.models import IdeaStatusEvent

    db = factory()
    try:
        for row in db.query(IdeaStatusEvent).filter(IdeaStatusEvent.idea_id == idea_id):
            row.created_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        db.commit()
    finally:
        db.close()


def _insert_raw_event(factory, *, tenant_id, idea_id, kind="status_changed", is_test=False, age_seconds=10):
    from modules.ideation.models import IdeaStatusEvent

    db = factory()
    try:
        db.add(
            IdeaStatusEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                idea_id=idea_id,
                kind=kind,
                is_test=is_test,
                payload_json={"event_id": str(uuid.uuid4()), "idea_id": idea_id},
                created_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
            )
        )
        db.commit()
    finally:
        db.close()


# ── AC-94-61 ───────────────────────────────────────────────────────────────

PLATFORM_EDGES = [
    ("captured", "triaged"),
    ("triaged", "linked"),
    ("linked", "building"),
    ("building", "delivered"),
    ("delivered", "closed"),
    ("captured", "rejected"),
    ("captured", "duplicate"),
    ("captured", "archived"),
    ("archived", "captured"),
]


@pytest.mark.parametrize("from_key, to_key", PLATFORM_EDGES)
def test_status_change_writes_event(ideation_client, from_key, to_key):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    factory = ideation_client._factory
    contact_id = _make_contact(factory, phone="+60177778888")
    idea_id = _insert_idea(
        factory, pid, problem="platform edge idea", status_key=from_key, submitter_contact_id=contact_id
    )

    res = _transition(ideation_client, h, idea_id, to_key)
    assert res.status_code == 200, res.text

    events = _events_for(factory, idea_id)
    assert len(events) == 1
    assert events[0].kind == "status_changed"


# ── AC-94-62 ───────────────────────────────────────────────────────────────


def test_no_event_from_initial_or_without_requester(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    factory = ideation_client._factory
    contact_id = _make_contact(factory, phone="+60133334444")

    # draft -> captured / rejected / duplicate: the FROM status is_initial.
    for to_key in ("captured", "rejected", "duplicate"):
        idea_id = _insert_idea(
            factory, pid, problem=f"draft to {to_key}", status_key="draft", submitter_contact_id=contact_id
        )
        res = _transition(ideation_client, h, idea_id, to_key)
        assert res.status_code == 200, res.text
        assert _events_for(factory, idea_id) == []

    # An operator-authored idea (no submitter contact) never gets an event.
    operator_idea = _insert_idea(
        factory, pid, problem="operator idea", status_key="captured", submitter_contact_id=None
    )
    res2 = _transition(ideation_client, h, operator_idea, "triaged")
    assert res2.status_code == 200, res2.text
    assert _events_for(factory, operator_idea) == []


# ── AC-94-63 ───────────────────────────────────────────────────────────────


def test_event_payload_exact_keys(ideation_client):
    s = _setup_with_contact(ideation_client)
    res = _transition(ideation_client, s["h"], s["idea_id"], "triaged")
    assert res.status_code == 200, res.text

    events = _events_for(ideation_client._factory, s["idea_id"])
    assert len(events) == 1
    payload = events[0].payload_json

    assert set(payload.keys()) == {
        "event_id", "seq", "kind", "occurred_at", "idea_id", "idea_number",
        "idea_title", "product_id", "status_label", "from_status_label",
        "track_url", "requester_phone", "merged_into", "separated_from", "is_test",
    }
    assert payload["kind"] == "status_changed"
    assert payload["status_label"] == "Triaged"
    assert payload["from_status_label"] == "New"
    assert payload["idea_id"] == s["idea_id"]
    assert payload["requester_phone"] == s["phone"]
    assert payload["merged_into"] is None
    assert payload["separated_from"] is None
    assert payload["is_test"] is False
    assert payload["track_url"]


# ── AC-94-64 ───────────────────────────────────────────────────────────────


def test_merge_event_per_child(ideation_client):
    s = _setup_with_contact(ideation_client, problem="child idea", phone="+60155556666")
    survivor_id = _insert_idea(
        ideation_client._factory, s["product_id"], problem="survivor idea", status_key="triaged"
    )

    res = ideation_client.post(
        "/ideation/ideas/merge",
        headers=s["h"],
        json={"survivorId": survivor_id, "ideaIds": [survivor_id, s["idea_id"]]},
    )
    assert res.status_code == 200, res.text

    events = _events_for(ideation_client._factory, s["idea_id"])
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "merged"
    assert ev.payload_json["merged_into"]["idea_number"]
    assert ev.payload_json["status_label"] == "Triaged"

    # No event for the survivor itself.
    assert _events_for(ideation_client._factory, survivor_id) == []


def test_unmerge_event_per_child(ideation_client):
    s = _setup_with_contact(ideation_client, problem="child idea", phone="+60166667777")
    survivor_id = _insert_idea(
        ideation_client._factory, s["product_id"], problem="survivor idea", status_key="triaged"
    )
    merge_res = ideation_client.post(
        "/ideation/ideas/merge",
        headers=s["h"],
        json={"survivorId": survivor_id, "ideaIds": [survivor_id, s["idea_id"]]},
    )
    assert merge_res.status_code == 200, merge_res.text

    res = ideation_client.post(f"/ideation/ideas/{s['idea_id']}/unmerge", headers=s["h"])
    assert res.status_code == 200, res.text

    events = [e for e in _events_for(ideation_client._factory, s["idea_id"]) if e.kind == "unmerged"]
    assert len(events) == 1
    ev = events[0]
    assert ev.payload_json["separated_from"]["idea_number"]
    assert ev.payload_json["merged_into"] is None
    assert ev.payload_json["status_label"] == "New"  # its own restored (captured) status


def test_flatten_writes_a_merged_event_for_the_repointed_grandchild(ideation_client):
    """Review round 1 NIT #10: flattening (C merged into M, then M merged
    into S) writes a SECOND "merged" event for C, naming the NEW survivor S -
    C's requester was already told it tracks M, and now needs telling it
    tracks S instead. No event for M itself (never a requester recipient)."""
    s = _setup_with_contact(ideation_client, problem="grandchild idea", phone="+60177778888")
    m = _insert_idea(ideation_client._factory, s["product_id"], problem="intermediate idea")
    survivor_id = _insert_idea(
        ideation_client._factory, s["product_id"], problem="new survivor", status_key="triaged"
    )

    first = ideation_client.post(
        "/ideation/ideas/merge",
        headers=s["h"],
        json={"survivorId": m, "ideaIds": [m, s["idea_id"]]},
    )
    assert first.status_code == 200, first.text

    second = ideation_client.post(
        "/ideation/ideas/merge",
        headers=s["h"],
        json={"survivorId": survivor_id, "ideaIds": [survivor_id, m]},
    )
    assert second.status_code == 200, second.text

    events = [
        e for e in _events_for(ideation_client._factory, s["idea_id"]) if e.kind == "merged"
    ]
    assert len(events) == 2  # the original merge into M, then the flatten onto S
    flatten_event = events[-1]
    assert flatten_event.payload_json["merged_into"]["idea_number"] == (
        ideation_client.get(f"/ideation/ideas/{survivor_id}", headers=s["h"]).json()["ideaNumber"]
    )
    assert flatten_event.payload_json["status_label"] == "Triaged"

    # No event for the intermediate member itself.
    assert _events_for(ideation_client._factory, m) == []


# ── AC-94-65 ───────────────────────────────────────────────────────────────


def test_survivor_change_fans_out_deduped_by_phone(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    factory = ideation_client._factory
    contact_a = _make_contact(factory, phone="+60111111111")
    contact_b = _make_contact(factory, phone="+60222222222")
    contact_c = _make_contact(factory, phone="+60111111111")  # same phone as A - dedup

    survivor = _insert_idea(
        factory, pid, problem="survivor", status_key="triaged", submitter_contact_id=contact_a
    )
    child_b = _insert_idea(factory, pid, problem="child b", submitter_contact_id=contact_b)
    child_c = _insert_idea(factory, pid, problem="child c", submitter_contact_id=contact_c)

    merge_res = ideation_client.post(
        "/ideation/ideas/merge",
        headers=h,
        json={"survivorId": survivor, "ideaIds": [survivor, child_b, child_c]},
    )
    assert merge_res.status_code == 200, merge_res.text

    res = _transition(ideation_client, h, survivor, "linked")
    assert res.status_code == 200, res.text

    from modules.ideation.models import IdeaStatusEvent

    db = factory()
    try:
        events = (
            db.query(IdeaStatusEvent).filter(IdeaStatusEvent.kind == "status_changed").all()
        )
    finally:
        db.close()
    recipients = {e.idea_id for e in events}
    # child_b always gets its own event; A and C share a phone, so only ONE of
    # {survivor, child_c} gets one (the survivor's own row wins the dedupe).
    assert child_b in recipients
    assert len({survivor, child_c} & recipients) == 1


# ── AC-94-66 ───────────────────────────────────────────────────────────────


def test_feed_cursor_and_tenant_scope(ideation_client):
    s = _setup_with_contact(ideation_client)
    res = _transition(ideation_client, s["h"], s["idea_id"], "triaged")
    assert res.status_code == 200, res.text
    _age_events(ideation_client._factory, s["idea_id"])

    # A different tenant's event must never leak into this key's feed - insert
    # one directly (bypassing the workspace-bound write path) to prove tenant
    # scoping at READ time, regardless of how it got written.
    _insert_raw_event(ideation_client._factory, tenant_id="tenant-x", idea_id="other-tenant-idea")

    res = ideation_client.get("/ideation/intake/status-events", headers=_key_auth(s["key"]))
    assert res.status_code == 200, res.text
    body = res.json()
    ids = {e["idea_id"] for e in body["events"]}
    assert s["idea_id"] in ids
    assert "other-tenant-idea" not in ids

    first_seq = next(e["seq"] for e in body["events"] if e["idea_id"] == s["idea_id"])
    res2 = ideation_client.get(
        "/ideation/intake/status-events", headers=_key_auth(s["key"]), params={"after": first_seq}
    )
    assert res2.status_code == 200, res2.text
    assert all(e["idea_id"] != s["idea_id"] for e in res2.json()["events"])

    res3 = ideation_client.get("/ideation/intake/status-events")
    assert res3.status_code == 401

    res4 = ideation_client.get(
        "/ideation/intake/status-events", headers={"Authorization": "Bearer not-a-real-key"}
    )
    assert res4.status_code == 401


# ── AC-94-67 ───────────────────────────────────────────────────────────────


def test_feed_excludes_test_events(ideation_client):
    s = _setup_with_contact(ideation_client)
    from modules.ideation.models import Idea

    db = ideation_client._factory()
    try:
        idea = db.query(Idea).filter(Idea.id == s["idea_id"]).first()
        idea.is_test = True
        db.commit()
    finally:
        db.close()

    res = _transition(ideation_client, s["h"], s["idea_id"], "triaged")
    assert res.status_code == 200, res.text
    _age_events(ideation_client._factory, s["idea_id"])

    default_feed = ideation_client.get(
        "/ideation/intake/status-events", headers=_key_auth(s["key"])
    )
    assert default_feed.status_code == 200, default_feed.text
    assert all(e["idea_id"] != s["idea_id"] for e in default_feed.json()["events"])

    with_test = ideation_client.get(
        "/ideation/intake/status-events", headers=_key_auth(s["key"]), params={"includeTest": True}
    )
    assert with_test.status_code == 200, with_test.text
    matches = [e for e in with_test.json()["events"] if e["idea_id"] == s["idea_id"]]
    assert len(matches) == 1
    assert matches[0]["is_test"] is True


# ── AC-94-68 ───────────────────────────────────────────────────────────────


def test_feed_order_and_settle_window(ideation_client):
    s = _setup_with_contact(ideation_client)
    assert _transition(ideation_client, s["h"], s["idea_id"], "triaged").status_code == 200
    assert _transition(ideation_client, s["h"], s["idea_id"], "linked").status_code == 200

    # Freshly committed rows (inside the 5s settle window) are withheld.
    res_fresh = ideation_client.get("/ideation/intake/status-events", headers=_key_auth(s["key"]))
    assert res_fresh.status_code == 200, res_fresh.text
    assert res_fresh.json()["events"] == []

    _age_events(ideation_client._factory, s["idea_id"], seconds=10)
    res = ideation_client.get("/ideation/intake/status-events", headers=_key_auth(s["key"]))
    assert res.status_code == 200, res.text
    events = res.json()["events"]
    assert len(events) == 2
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)
    assert len({e["event_id"] for e in events}) == 2


# ── AC-94-69 ───────────────────────────────────────────────────────────────


def test_event_failure_isolated(ideation_client, monkeypatch):
    s = _setup_with_contact(ideation_client)

    from modules.ideation.services import status_events as status_events_module

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(status_events_module, "on_domain_event", _boom)

    res = _transition(ideation_client, s["h"], s["idea_id"], "triaged")
    assert res.status_code == 200, res.text
    detail = ideation_client.get(f"/ideation/ideas/{s['idea_id']}", headers=s["h"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "triaged"


# ── AC-94-70 ───────────────────────────────────────────────────────────────


def test_requester_lookup_tenant_scoped(ideation_client):
    from app.models.tenant import Tenant
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id
    from modules.omnichannel.models import Contact, Workspace

    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)

    db = ideation_client._factory()
    try:
        default_tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
        other = Tenant(
            name="Other Co", slug="other-status-events-94", status_id=default_tenant.status_id
        )
        db.add(other)
        db.flush()
        ws = Workspace(tenant_id=other.id, name="Other WS", is_default=True)
        db.add(ws)
        db.flush()
        other_contact = Contact(
            tenant_id=other.id, workspace_id=ws.id, first_name="Alice", phone="+60199999999"
        )
        db.add(other_contact)
        db.flush()
        other_contact_id = other_contact.id
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=pid,
            status_id=idea_status_id(db, "captured", DEFAULT_TENANT_ID),
            problem="cross tenant requester",
            captured_json={"problem": "cross tenant requester"},
            submitter_contact_id=other_contact_id,  # cross-tenant polymorphic ref
        )
        db.add(idea)
        db.commit()
        idea_id = idea.id
    finally:
        db.close()

    res = _transition(ideation_client, h, idea_id, "triaged")
    assert res.status_code == 200, res.text
    assert _events_for(ideation_client._factory, idea_id) == []


# ── AC-94-71 ───────────────────────────────────────────────────────────────


def test_uninstall_clears_events(ideation_client):
    s = _setup_with_contact(ideation_client)
    assert _transition(ideation_client, s["h"], s["idea_id"], "triaged").status_code == 200

    from modules.ideation.bootstrap import uninstall_tenant
    from modules.ideation.models import IdeaStatusEvent

    db = ideation_client._factory()
    try:
        before = (
            db.query(IdeaStatusEvent).filter(IdeaStatusEvent.tenant_id == DEFAULT_TENANT_ID).count()
        )
        assert before >= 1
        uninstall_tenant(db, DEFAULT_TENANT_ID)
        db.commit()
        after = (
            db.query(IdeaStatusEvent).filter(IdeaStatusEvent.tenant_id == DEFAULT_TENANT_ID).count()
        )
        assert after == 0
    finally:
        db.close()
