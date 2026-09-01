"""Ideation Slice 7 - triage board API + drag authorization (AC-A-33, AC-A-37).

The FE triage board (service_frontend/app/(protected)/ideation/board/page.tsx)
renders ideas as cards in columns keyed by Idea status
(captured / triaged / linked / building / delivered), drags a card to another
column to transition status, and reorders within a column to set priority.

This slice adds the server board read:

- ``GET /ideation/ideas/board`` - ideas grouped by status column, columns in the
  lifecycle order, cards within a column ordered by priority; archived/terminal
  ideas are off the board. Gated by ``ideation.triage.manage`` (the Triager
  surface - AC-A-33/AC-A-36).

Drag = status transition and within-column reorder reuse the slice-4
``POST /ideation/ideas/{id}/status`` and ``PUT /ideation/ideas/reorder``
endpoints (server-authoritative - illegal drags refused; both require
``ideation.triage.manage``). Server enforces the key regardless of the UI
(AC-A-37).

Test-first (PRINCIPLES.md): written before the board endpoint exists.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql import func

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

# Board columns (key, title) - must match the FE IDEA_BOARD_COLUMNS order.
BOARD_COLUMNS = [
    ("captured", "New"),
    ("triaged", "Triaged"),
    ("linked", "Linked to BR"),
    ("building", "Building"),
    ("delivered", "Delivered"),
]


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


def _columns(board: dict) -> dict:
    """{status_key: [idea_id, ...]} from a board payload (preserves order)."""
    return {c["key"]: [i["id"] for i in c["ideas"]] for c in board["columns"]}


# ── board grouping shape (AC-A-33) ─────────────────────────────────────────────


def test_board_returns_columns_in_lifecycle_order(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.get("/ideation/ideas/board", headers=h)
    assert res.status_code == 200, res.text
    board = res.json()
    assert [c["key"] for c in board["columns"]] == [k for k, _ in BOARD_COLUMNS]
    assert [c["title"] for c in board["columns"]] == [t for _, t in BOARD_COLUMNS]


def test_board_groups_ideas_by_status(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    cap = _insert_idea(ideation_client._factory, pid, problem="cap idea", status_key="captured")
    tri = _insert_idea(ideation_client._factory, pid, problem="tri idea", status_key="triaged")
    bld = _insert_idea(ideation_client._factory, pid, problem="bld idea", status_key="building")

    res = ideation_client.get("/ideation/ideas/board", headers=h)
    assert res.status_code == 200, res.text
    cols = _columns(res.json())
    assert cap in cols["captured"]
    assert tri in cols["triaged"]
    assert bld in cols["building"]
    # Each idea lands in exactly one column.
    assert cap not in cols["triaged"] and cap not in cols["building"]


def test_board_card_shape_is_human_readable(ideation_client):
    """Cards carry problem + product + submitter + upvotes, never a raw UUID."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h, name="Sorento CRM")
    _insert_idea(ideation_client._factory, pid, problem="cap idea", status_key="captured")

    board = ideation_client.get("/ideation/ideas/board", headers=h).json()
    captured = next(c for c in board["columns"] if c["key"] == "captured")
    card = captured["ideas"][0]
    assert card["problem"] == "cap idea"
    assert card["productName"] == "Sorento CRM"
    assert card["submitterName"] == "Unknown"  # no submitter contact
    assert card["upvotes"] == 0
    assert card["status"] == "captured"


def test_board_excludes_archived_and_terminal(ideation_client):
    """Only board-lifecycle statuses appear; archived / closed / off-ramp do not."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    on_board = _insert_idea(ideation_client._factory, pid, status_key="captured")
    archived = _insert_idea(ideation_client._factory, pid, status_key="archived")
    closed = _insert_idea(ideation_client._factory, pid, status_key="closed")
    rejected = _insert_idea(ideation_client._factory, pid, status_key="rejected")

    board = ideation_client.get("/ideation/ideas/board", headers=h).json()
    all_ids = {i for ids in _columns(board).values() for i in ids}
    assert on_board in all_ids
    assert archived not in all_ids
    assert closed not in all_ids
    assert rejected not in all_ids


def test_board_within_column_ordered_by_priority(ideation_client):
    """Within a column, cards are ordered by priority ascending (top = highest)."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    low = _insert_idea(ideation_client._factory, pid, problem="low", status_key="captured", priority=2)
    top = _insert_idea(ideation_client._factory, pid, problem="top", status_key="captured", priority=0)
    mid = _insert_idea(ideation_client._factory, pid, problem="mid", status_key="captured", priority=1)

    board = ideation_client.get("/ideation/ideas/board", headers=h).json()
    captured = _columns(board)["captured"]
    assert captured == [top, mid, low]


def test_board_permission_denied_403(ideation_client):
    """A view-only user (no triage key) cannot open the triage board (AC-A-37)."""
    _make_user(
        ideation_client._factory,
        "boardviewer@example.com",
        "boardviewer1234",
        {"ideation.ideas.view", "ideation.ideas.upvote"},
    )
    h = _auth(ideation_client, email="boardviewer@example.com", password="boardviewer1234")
    res = ideation_client.get("/ideation/ideas/board", headers=h)
    assert res.status_code == 403, res.text


# ── drag = status transition (AC-A-33 / AC-A-37) ───────────────────────────────


def test_legal_drag_transitions_status(ideation_client):
    """Dragging captured -> triaged moves the idea to the triaged column."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid, status_key="captured")

    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/status", headers=h, json={"status": "triaged"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "triaged"

    cols = _columns(ideation_client.get("/ideation/ideas/board", headers=h).json())
    assert idea_id in cols["triaged"]
    assert idea_id not in cols["captured"]


def test_illegal_drag_refused(ideation_client):
    """Dragging captured -> delivered has no edge - refused, state unchanged."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid, status_key="captured")

    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/status", headers=h, json={"status": "delivered"}
    )
    assert res.status_code in (400, 409), res.text
    cols = _columns(ideation_client.get("/ideation/ideas/board", headers=h).json())
    assert idea_id in cols["captured"]
    assert idea_id not in cols["delivered"]


def test_drag_permission_denied_403(ideation_client):
    """A user without the triage key cannot transition status regardless of UI."""
    _make_user(
        ideation_client._factory,
        "dragviewer@example.com",
        "dragviewer1234",
        {"ideation.ideas.view", "ideation.ideas.upvote"},
    )
    h_admin = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h_admin)
    idea_id = _insert_idea(ideation_client._factory, pid, status_key="captured")
    h = _auth(ideation_client, email="dragviewer@example.com", password="dragviewer1234")
    res = ideation_client.post(
        f"/ideation/ideas/{idea_id}/status", headers=h, json={"status": "triaged"}
    )
    assert res.status_code == 403, res.text


# ── within-column reorder = priority (AC-A-33) ─────────────────────────────────


def test_within_column_reorder_sets_priority(ideation_client):
    """Reordering within a column persists priority and reorders the board column."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="A", status_key="captured")
    b = _insert_idea(ideation_client._factory, pid, problem="B", status_key="captured")
    c = _insert_idea(ideation_client._factory, pid, problem="C", status_key="captured")

    res = ideation_client.put(
        "/ideation/ideas/reorder", headers=h, json={"orderedIds": [c, a, b]}
    )
    assert res.status_code == 200, res.text
    by_id = {r["id"]: r["priority"] for r in res.json()}
    assert by_id[c] < by_id[a] < by_id[b]

    # The board column reflects the new order.
    cols = _columns(ideation_client.get("/ideation/ideas/board", headers=h).json())
    assert cols["captured"] == [c, a, b]


def test_reorder_permission_denied_403(ideation_client):
    """Reorder requires the triage key server-side (AC-A-37)."""
    _make_user(
        ideation_client._factory,
        "reorderviewer@example.com",
        "reorderviewer1234",
        {"ideation.ideas.view"},
    )
    h_admin = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h_admin)
    a = _insert_idea(ideation_client._factory, pid, status_key="captured")
    h = _auth(ideation_client, email="reorderviewer@example.com", password="reorderviewer1234")
    res = ideation_client.put(
        "/ideation/ideas/reorder", headers=h, json={"orderedIds": [a]}
    )
    assert res.status_code == 403, res.text
