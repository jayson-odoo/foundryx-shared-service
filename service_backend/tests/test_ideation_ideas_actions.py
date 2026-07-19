"""Ideation Slice 4 — vote / priority / status / delete action APIs.

These are the write endpoints the FE prototype already calls (services/
ideation-service.ts: vote / reorderPriority / setStatus / remove):

- ``POST /ideation/ideas/{id}/vote {dir}`` — per-user toggle vote (one row per
  voter; clicking the same dir cancels, the other dir switches), recomputing
  ``upvotes`` / ``downvotes`` / ``myVote`` (partial AC-A-21 upvote idempotency).
- ``PUT  /ideation/ideas/reorder {orderedIds}`` — manual priority (index =
  priority, ascending = top).
- ``POST /ideation/ideas/{id}/status {status}`` — server-authoritative status
  engine transition (illegal refused); archive = → ``archived``; restore =
  ``archived`` → ``captured``.
- ``DELETE /ideation/ideas/{id}`` — hard delete.

Test-first (PRINCIPLES.md): written before the implementation exists.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql import func

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.security import hash_password
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


_IDEA_SEQ = [0]


def _insert_idea(
    factory,
    product_id,
    problem="Let CS export orders to Excel",
    status_key="captured",
    source="whatsapp",
    priority=0,
    created_at=None,
) -> str:
    from datetime import datetime, timedelta, timezone

    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    if created_at is None:
        _IDEA_SEQ[0] += 1
        created_at = datetime.now(timezone.utc) + timedelta(seconds=_IDEA_SEQ[0])

    db = factory()
    try:
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=product_id,
            status_id=idea_status_id(db, status_key),
            intake_definition_key="ideation",
            problem=problem,
            raw_text=problem,
            source=source,
            priority=priority,
            created_at=created_at,
        )
        db.add(idea)
        db.commit()
        return idea.id
    finally:
        db.close()


def _make_user(factory, email, password, perm_keys):
    from app.models import Role, User, UserStatus
    from app.models.permission import Permission

    db = factory()
    try:
        perms = db.query(Permission).filter(Permission.key.in_(list(perm_keys))).all()
        role = Role(
            tenant_id=DEFAULT_TENANT_ID,
            name=f"Role-{email}",
            description="Test role",
            is_system=False,
        )
        role.permissions = perms
        db.add(role)
        db.flush()
        user = User(
            tenant_id=DEFAULT_TENANT_ID,
            email=email,
            password=hash_password(password),
            name="Test User",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
        user.roles = [role]
        db.add(user)
        db.commit()
    finally:
        db.close()


# ── vote (AC-A-21 idempotency partial) ────────────────────────────────────────


def test_vote_up_increments_and_sets_my_vote(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid)

    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/vote", headers=h, json={"dir": "up"}
    )
    assert res.status_code == 200, res.text
    row = res.json()
    assert row["upvotes"] == 1
    assert row["downvotes"] == 0
    assert row["myVote"] == "up"


def test_vote_same_dir_twice_cancels(ideation_client):
    """Clicking the same direction again clears the vote (toggle)."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid)

    ideation_client.post(f"/ideation/ideas/{idea_id}/vote", headers=h, json={"dir": "up"})
    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/vote", headers=h, json={"dir": "up"}
    )
    assert res.status_code == 200, res.text
    row = res.json()
    assert row["upvotes"] == 0
    assert row["myVote"] is None


def test_vote_switch_direction(ideation_client):
    """Clicking the other direction switches the vote (not additive)."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid)

    ideation_client.post(f"/ideation/ideas/{idea_id}/vote", headers=h, json={"dir": "up"})
    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/vote", headers=h, json={"dir": "down"}
    )
    assert res.status_code == 200, res.text
    row = res.json()
    assert row["upvotes"] == 0
    assert row["downvotes"] == 1
    assert row["myVote"] == "down"


def test_vote_idempotent_one_row_per_user_two_voters(ideation_client):
    """Distinct voters each get one vote; re-voting the same dir is a no-op net
    change (idempotent). Two up-voters => upvotes == 2."""
    _make_user(
        ideation_client._factory,
        "voter2@example.com",
        "voter21234",
        {"ideation.ideas.view", "ideation.ideas.upvote"},
    )
    h1 = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h1)
    idea_id = _insert_idea(ideation_client._factory, pid)
    h2 = _auth(ideation_client, email="voter2@example.com", password="voter21234")

    ideation_client.post(f"/ideation/ideas/{idea_id}/vote", headers=h1, json={"dir": "up"})
    # user1 votes up again via a fresh request — must NOT double-count (idempotent
    # toggle), so re-assert up by toggling twice back to up.
    ideation_client.post(f"/ideation/ideas/{idea_id}/vote", headers=h1, json={"dir": "up"})
    ideation_client.post(f"/ideation/ideas/{idea_id}/vote", headers=h1, json={"dir": "up"})
    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/vote", headers=h2, json={"dir": "up"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["upvotes"] == 2  # one per distinct voter


def test_vote_404_missing_idea(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.post(
        "/ideation/ideas/does-not-exist/vote", headers=h, json={"dir": "up"}
    )
    assert res.status_code == 404, res.text


def test_vote_permission_denied_403(ideation_client):
    _make_user(
        ideation_client._factory, "viewonly@example.com", "viewonly1234", {"ideation.ideas.view"}
    )
    h_admin = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h_admin)
    idea_id = _insert_idea(ideation_client._factory, pid)
    h = _auth(ideation_client, email="viewonly@example.com", password="viewonly1234")
    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/vote", headers=h, json={"dir": "up"}
    )
    assert res.status_code == 403, res.text


# ── reorder priority ──────────────────────────────────────────────────────────


def test_reorder_persists_priority(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="idea A")
    b = _insert_idea(ideation_client._factory, pid, problem="idea B")
    c = _insert_idea(ideation_client._factory, pid, problem="idea C")

    res = ideation_client.put(
        "/ideation/ideas/reorder", headers=h, json={"orderedIds": [c, a, b]}
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert isinstance(data, list)
    # Returned ascending by priority == the requested order.
    assert [r["id"] for r in data[:3]] == [c, a, b]
    # Priority persisted ascending (c highest priority == lowest number).
    by_id = {r["id"]: r["priority"] for r in data}
    assert by_id[c] < by_id[a] < by_id[b]


def test_reorder_permission_denied_403(ideation_client):
    _make_user(
        ideation_client._factory,
        "novote@example.com",
        "novote1234",
        {"ideation.ideas.view", "ideation.ideas.upvote"},
    )
    h_admin = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h_admin)
    a = _insert_idea(ideation_client._factory, pid)
    h = _auth(ideation_client, email="novote@example.com", password="novote1234")
    res = ideation_client.put(
        "/ideation/ideas/reorder", headers=h, json={"orderedIds": [a]}
    )
    assert res.status_code == 403, res.text


# ── status transition (advance / archive / restore) ───────────────────────────


def test_status_advance_follows_lifecycle(ideation_client):
    """captured -> triaged is a legal advance (IDEA_NEXT_STATUS)."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid, status_key="captured")

    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/status", headers=h, json={"status": "triaged"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "triaged"


def test_illegal_transition_refused(ideation_client):
    """captured -> delivered has no edge — refused (not a 2xx)."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid, status_key="captured")

    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/status", headers=h, json={"status": "delivered"}
    )
    assert res.status_code in (400, 403, 409), res.text
    # State unchanged.
    got = ideation_client.get(f"/ideation/ideas/{idea_id}", headers=h).json()
    assert got["status"] == "captured"


def test_archive_and_restore(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid, status_key="captured")

    # Archive.
    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/status", headers=h, json={"status": "archived"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "archived"
    # Now appears under the archived filter, not the active one.
    active = ideation_client.get(
        "/ideation/ideas", headers=h, params={"filter": "active"}
    ).json()
    assert idea_id not in {r["id"] for r in active}
    archived = ideation_client.get(
        "/ideation/ideas", headers=h, params={"filter": "archived"}
    ).json()
    assert idea_id in {r["id"] for r in archived}

    # Restore.
    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/status", headers=h, json={"status": "captured"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "captured"


def test_status_404_missing_idea(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.post(
        "/ideation/ideas/nope/status", headers=h, json={"status": "triaged"}
    )
    assert res.status_code == 404, res.text


def test_status_permission_denied_403(ideation_client):
    _make_user(
        ideation_client._factory,
        "upvoteonly@example.com",
        "upvoteonly1234",
        {"ideation.ideas.view", "ideation.ideas.upvote"},
    )
    h_admin = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h_admin)
    idea_id = _insert_idea(ideation_client._factory, pid, status_key="captured")
    h = _auth(ideation_client, email="upvoteonly@example.com", password="upvoteonly1234")
    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/status", headers=h, json={"status": "triaged"}
    )
    assert res.status_code == 403, res.text


# ── hard delete ───────────────────────────────────────────────────────────────


def test_hard_delete_removes_idea(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid)
    # Give it a vote so we prove vote rows are cleaned up too.
    ideation_client.post(f"/ideation/ideas/{idea_id}/vote", headers=h, json={"dir": "up"})

    res = ideation_client.delete(f"/ideation/ideas/{idea_id}", headers=h)
    assert res.status_code in (200, 204), res.text
    # Gone.
    assert ideation_client.get(f"/ideation/ideas/{idea_id}", headers=h).status_code == 404
    # Vote rows cleaned up.
    from modules.ideation.models import IdeaVote

    db = ideation_client._factory()
    try:
        assert db.query(IdeaVote).filter(IdeaVote.idea_id == idea_id).count() == 0
    finally:
        db.close()


def test_delete_404_missing_idea(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.delete("/ideation/ideas/nope", headers=h)
    assert res.status_code == 404, res.text


def test_delete_permission_denied_403(ideation_client):
    _make_user(
        ideation_client._factory,
        "nodelete@example.com",
        "nodelete1234",
        {"ideation.ideas.view", "ideation.ideas.upvote"},
    )
    h_admin = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h_admin)
    idea_id = _insert_idea(ideation_client._factory, pid)
    h = _auth(ideation_client, email="nodelete@example.com", password="nodelete1234")
    res = ideation_client.delete(f"/ideation/ideas/{idea_id}", headers=h)
    assert res.status_code == 403, res.text
