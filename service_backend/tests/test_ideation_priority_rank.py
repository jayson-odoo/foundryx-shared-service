"""Ideation round 2 (#94) - priority rank (AC-94-41..45).

TEST-FIRST (PRINCIPLES.md): `IdeaOut.rank` doesn't exist yet, capture never
appends a real priority, and `/reorder` still overwrites every requested id's
priority by its position in the CALL (not slot-preserving). Every test here
is expected to fail with a `KeyError` on `rank` or a priority collision until
slice S2 lands (plan section 5).
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
    factory,
    product_id,
    *,
    problem="idea",
    status_key="captured",
    tenant_id=DEFAULT_TENANT_ID,
    is_test=False,
    priority=0,
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
            priority=priority,
            captured_json={"problem": problem},
        )
        db.add(idea)
        db.commit()
        return idea.id
    finally:
        db.close()


# ── AC-94-41 ───────────────────────────────────────────────────────────────


def test_rank_is_one_based(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a", priority=0)
    b = _insert_idea(ideation_client._factory, pid, problem="b", priority=1)
    c = _insert_idea(ideation_client._factory, pid, problem="c", priority=2)
    archived = _insert_idea(
        ideation_client._factory, pid, problem="gone", status_key="archived", priority=3
    )

    res = ideation_client.get("/ideation/ideas", headers=h)
    assert res.status_code == 200, res.text
    by_id = {r["id"]: r["rank"] for r in res.json()}
    assert by_id[a] == 1 and by_id[b] == 2 and by_id[c] == 3

    res_all = ideation_client.get("/ideation/ideas", headers=h, params={"filter": "all"})
    by_id_all = {r["id"]: r["rank"] for r in res_all.json()}
    assert by_id_all[archived] is None


# ── AC-94-42 ───────────────────────────────────────────────────────────────


def test_rank_scope(ideation_client):
    h = _auth(ideation_client)
    pid1 = _create_software_product(ideation_client, h, name="Product A")
    pid2 = _create_software_product(ideation_client, h, name="Product B")
    _insert_idea(ideation_client._factory, pid1, problem="a1", priority=0)
    _insert_idea(ideation_client._factory, pid1, problem="a2", priority=1)
    b1 = _insert_idea(ideation_client._factory, pid2, problem="b1", priority=10)
    b2 = _insert_idea(ideation_client._factory, pid2, problem="b2", priority=11)

    scoped = {
        r["id"]: r["rank"]
        for r in ideation_client.get(
            "/ideation/ideas", headers=h, params={"productId": pid2}
        ).json()
    }
    assert scoped[b1] == 1 and scoped[b2] == 2  # product-scoped: own #1/#2

    unscoped = {
        r["id"]: r["rank"] for r in ideation_client.get("/ideation/ideas", headers=h).json()
    }
    assert unscoped[b1] == 3 and unscoped[b2] == 4  # tenant-wide: after pid1's two

    # The test lane ranks separately from the real lane, within its own product.
    pid3 = _create_software_product(ideation_client, h, name="Product C")
    real_idea = _insert_idea(ideation_client._factory, pid3, problem="real", priority=0)
    test_idea = _insert_idea(
        ideation_client._factory, pid3, problem="test", priority=0, is_test=True
    )
    lane = {
        r["id"]: r["rank"]
        for r in ideation_client.get(
            "/ideation/ideas", headers=h, params={"productId": pid3, "includeTest": True}
        ).json()
    }
    assert lane[real_idea] == 1
    assert lane[test_idea] == 1  # its own lane's #1, not colliding with the real one


# ── AC-94-43 ───────────────────────────────────────────────────────────────


def test_detail_rank_matches_list(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    ids = [
        _insert_idea(ideation_client._factory, pid, problem=f"idea {i}", priority=i)
        for i in range(5)
    ]
    x = ids[3]

    listed = {r["id"]: r["rank"] for r in ideation_client.get("/ideation/ideas", headers=h).json()}
    assert listed[x] == 4

    detail = ideation_client.get(f"/ideation/ideas/{x}", headers=h).json()
    assert detail["rank"] == 4


# ── AC-94-44 ───────────────────────────────────────────────────────────────


def test_new_capture_appends(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    for i in range(5):
        _insert_idea(ideation_client._factory, pid, problem=f"idea {i}", priority=i)

    res = ideation_client.post(
        "/ideation/ideas", headers=h, json={"productId": pid, "problem": "new capture via operator"}
    )
    assert res.status_code == 201, res.text
    assert res.json()["rank"] == 6

    # The WhatsApp sink path (draft -> captured) also appends at the end.
    from modules.ideation.models import Idea
    from modules.ideation.services.sinks import ideation_on_complete_sink
    from modules.ideation.services.statuses import initial_idea_status_id

    db = ideation_client._factory()
    try:
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=pid,
            status_id=initial_idea_status_id(db, DEFAULT_TENANT_ID),
            problem="a whatsapp draft about to be captured",
            captured_json={"problem": "a whatsapp draft about to be captured"},
        )
        db.add(idea)
        db.flush()
        ideation_on_complete_sink(db, idea, DEFAULT_TENANT_ID)
        db.commit()
        idea_id = idea.id
    finally:
        db.close()

    detail = ideation_client.get(f"/ideation/ideas/{idea_id}", headers=h).json()
    assert detail["rank"] == 7


# ── AC-94-45 ───────────────────────────────────────────────────────────────


def test_reorder_is_slot_preserving(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    ids = [
        _insert_idea(ideation_client._factory, pid, problem=f"idea {i}", priority=i)
        for i in range(15)
    ]
    page2 = ids[10:15]

    res = ideation_client.put(
        "/ideation/ideas/reorder", headers=h, json={"orderedIds": list(reversed(page2))}
    )
    assert res.status_code == 200, res.text

    listed = {r["id"]: r["rank"] for r in ideation_client.get("/ideation/ideas", headers=h).json()}
    # Slots 1..10 (ids[0..9]) are untouched by a page-2-only reorder call.
    for i in range(10):
        assert listed[ids[i]] == i + 1
    # Slots 11..15 hold the reversed page-2 order, still unique.
    assert [listed[i] for i in reversed(page2)] == [11, 12, 13, 14, 15]
    assert len(set(listed.values())) == 15
