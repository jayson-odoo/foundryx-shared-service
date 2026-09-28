"""Ideation round 2 (#94) - status labels/colours/transitions from the
statuses engine (AC-94-49..54, 60 BE half).

TEST-FIRST (PRINCIPLES.md): `IdeaOut` doesn't carry `statusId`/`statusLabel`/
`statusColor`/`statusIsArchived`/`transitions`/`advanceTransitionId` yet;
`POST /{id}/status` doesn't accept `toStatusId`; the board still derives from
the hardcoded `BOARD_COLUMNS`/`_ARCHIVED_KEYS` (plan section 6). Every test
here is expected to fail with a `KeyError` on a missing response field, or on
`assert ... not in source` for constants that still exist, until slice S2
lands.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


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


def _insert_idea(
    factory, product_id, *, problem="idea", status_key="captured", tenant_id=DEFAULT_TENANT_ID
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
            captured_json={"problem": problem},
        )
        db.add(idea)
        db.commit()
        return idea.id
    finally:
        db.close()


# ── AC-94-49 ───────────────────────────────────────────────────────────────


def test_ideaout_status_display(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, status_key="captured")

    res = ideation_client.get(f"/ideation/ideas/{a}", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "captured"
    assert body["statusId"]
    assert body["statusLabel"] == "New"
    assert body["statusColor"] == "blue"
    assert body["statusIsArchived"] is False


# ── AC-94-50 ───────────────────────────────────────────────────────────────


def test_rename_flows_through(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, status_key="triaged")

    graph = ideation_client.get("/statuses", params={"entityType": "idea"}, headers=h)
    assert graph.status_code == 200, graph.text
    triaged = next(s for s in graph.json()["statuses"] if s["key"] == "triaged")
    rename = ideation_client.patch(
        f"/statuses/{triaged['id']}", json={"label": "Discussed"}, headers=h
    )
    assert rename.status_code == 200, rename.text

    detail = ideation_client.get(f"/ideation/ideas/{a}", headers=h).json()
    assert detail["statusLabel"] == "Discussed"

    board = ideation_client.get("/ideation/ideas/board", headers=h).json()
    titles = {c["key"]: c["title"] for c in board["columns"]}
    assert "Discussed" in titles.values()

    from modules.ideation.models import Idea

    db = ideation_client._factory()
    try:
        idea_row = db.query(Idea).filter(Idea.id == a).first()
        token = "tok94rn" + idea_row.id.replace("-", "")[:12]
        idea_row.status_token = token
        idea_row.idea_number = "IDEA-9450"
        db.commit()
    finally:
        db.close()

    public = ideation_client.get(f"/public/ideas/{token}")
    assert public.status_code == 200, public.text
    assert public.json()["status"] == "Discussed"


# ── AC-94-51 ───────────────────────────────────────────────────────────────


def test_transitions_are_fireable_only(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, status_key="captured")

    res = ideation_client.get(f"/ideation/ideas/{a}", headers=h)
    assert res.status_code == 200, res.text
    transitions = res.json()["transitions"]
    labels = {t["label"] for t in transitions}
    assert "Triage" in labels  # captured -> triaged is fireable
    for t in transitions:
        assert set(t.keys()) == {"id", "label", "toStatusId", "toStatusLabel"}

    delivered_idea = _insert_idea(ideation_client._factory, pid, status_key="delivered")
    res2 = ideation_client.get(f"/ideation/ideas/{delivered_idea}", headers=h)
    labels2 = {t["label"] for t in res2.json()["transitions"]}
    assert "Close" in labels2  # delivered -> closed


# ── AC-94-52 ───────────────────────────────────────────────────────────────


def test_advance_follows_sort_order(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, status_key="captured")

    res = ideation_client.get(f"/ideation/ideas/{a}", headers=h)
    body = res.json()
    assert body["advanceTransitionId"] is not None
    advance_edge = next(t for t in body["transitions"] if t["id"] == body["advanceTransitionId"])
    assert advance_edge["toStatusLabel"] == "Triaged"

    closed_idea = _insert_idea(ideation_client._factory, pid, status_key="closed")
    res2 = ideation_client.get(f"/ideation/ideas/{closed_idea}", headers=h)
    assert res2.json()["advanceTransitionId"] is None  # terminal - nothing to advance to


def test_advance_never_skips_to_an_off_ramp_when_next_edge_is_role_blocked(ideation_client):
    """Review round 1 #5 (AC-94-52 revised): ``advanceTransitionId`` is the
    edge to the IMMEDIATELY next non-archived status, only when THAT edge is
    fireable for the caller - never a later reachable status, and never an
    off-ramp like Duplicate/Rejected. Role-block the true next edge
    (captured -> triaged) for this actor: the OLD "smallest sort_order among
    fireable edges" rule would have skipped ahead to "Mark duplicate"
    (captured -> duplicate, still fireable, the next-smallest target sort
    order) - the revised rule must return null instead, and must never
    surface Duplicate as the advance target."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, status_key="captured")

    from app.models import Role
    from app.models.status_transition import StatusTransition

    db = ideation_client._factory()
    try:
        edge = (
            db.query(StatusTransition)
            .filter(StatusTransition.id == "idea-tr-triage")
            .first()
        )
        blocking_role = Role(
            tenant_id=DEFAULT_TENANT_ID,
            name="Nobody-Holds-This-94-52",
            description="test-only role, held by no user",
            is_system=False,
        )
        db.add(blocking_role)
        db.flush()
        edge.roles = [blocking_role]
        db.commit()
    finally:
        db.close()

    res = ideation_client.get(f"/ideation/ideas/{a}", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    labels = {t["label"] for t in body["transitions"]}
    assert "Triage" not in labels  # role-blocked for this actor
    assert "Mark duplicate" in labels  # still fireable and still reachable
    assert body["advanceTransitionId"] is None  # never skips to that off-ramp


# ── AC-94-53 ───────────────────────────────────────────────────────────────


def test_status_move_by_id(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, status_key="captured")

    graph = ideation_client.get("/statuses", params={"entityType": "idea"}, headers=h).json()
    triaged_id = next(s["id"] for s in graph["statuses"] if s["key"] == "triaged")
    delivered_id = next(s["id"] for s in graph["statuses"] if s["key"] == "delivered")

    res = ideation_client.post(
        f"/ideation/ideas/{a}/status", headers=h, json={"toStatusId": triaged_id}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "triaged"

    # A target outside the idea entity (the core tenant lifecycle's own status
    # id) is refused (422).
    from app.models.status import TENANT_STATUS_ACTIVE, TENANT_STATUS_IDS

    bad = ideation_client.post(
        f"/ideation/ideas/{a}/status",
        headers=h,
        json={"toStatusId": TENANT_STATUS_IDS[TENANT_STATUS_ACTIVE]},
    )
    assert bad.status_code == 422, bad.text

    # A missing edge (no direct triaged -> delivered path) is 409.
    illegal = ideation_client.post(
        f"/ideation/ideas/{a}/status", headers=h, json={"toStatusId": delivered_id}
    )
    assert illegal.status_code == 409, illegal.text

    # The key form still works (kept for the deferred Archive handler).
    key_form = ideation_client.post(
        f"/ideation/ideas/{a}/status", headers=h, json={"status": "linked"}
    )
    assert key_form.status_code == 200, key_form.text
    assert key_form.json()["status"] == "linked"


# ── AC-94-54 ───────────────────────────────────────────────────────────────


def test_board_columns_from_flags(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    _insert_idea(ideation_client._factory, pid, status_key="captured")
    _insert_idea(ideation_client._factory, pid, status_key="archived")

    res = ideation_client.get("/ideation/ideas/board", headers=h)
    assert res.status_code == 200, res.text
    columns = res.json()["columns"]
    keys = [c["key"] for c in columns]
    assert "archived" not in keys and "draft" not in keys
    for c in columns:
        assert set(c.keys()) >= {"statusId", "key", "title", "color", "ideas"}

    import inspect

    from modules.ideation.services import ideas as ideas_service

    source = inspect.getsource(ideas_service)
    assert "BOARD_COLUMNS" not in source
    assert "_ARCHIVED_KEYS" not in source


# ── AC-94-60 (BE half - the archived filter + its restore transition) ───────


def test_archived_idea_carries_restore_transition(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, status_key="archived")

    res = ideation_client.get("/ideation/ideas", headers=h, params={"filter": "archived"})
    assert res.status_code == 200, res.text
    row = next(r for r in res.json() if r["id"] == a)
    assert row["statusIsArchived"] is True
    assert any(t["toStatusLabel"] == "New" for t in row["transitions"])
