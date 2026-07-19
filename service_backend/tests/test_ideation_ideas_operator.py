"""Ideation — operator-facing in-app Idea create + edit.

Distinct from the conversational WhatsApp intake (``POST /ideation/intake/
create-idea``, which has the deterministic draft/collect/confirm gate). An
operator typing an idea directly IS deliberate, so:

- ``POST  /ideation/ideas``        — create straight into ``captured`` (rides the
  status engine draft→captured), submitter = the logged-in operator
  (``submitter_name`` set from the user, ``submitter_contact_id`` NULL). Gated by
  ``ideation.ideas.submit``.
- ``PATCH /ideation/ideas/{id}``   — edit ``productId`` / ``problem`` / ``rawText``
  (status moves stay on ``POST /{id}/status``). Gated by ``ideation.triage.manage``.

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


# ── create (operator, no confirm gate) ────────────────────────────────────────


def test_operator_create_returns_captured_idea(ideation_client):
    """An operator create lands the idea directly in ``captured`` (no draft/
    collect/confirm), submitter = the operator, and it appears in list + detail."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)

    res = ideation_client.post(
        "/ideation/ideas",
        headers=h,
        json={
            "productId": pid,
            "problem": "  Let CS export orders to Excel  ",
            "rawText": "  full context here  ",
        },
    )
    assert res.status_code == 201, res.text
    row = res.json()
    assert row["status"] == "captured"
    assert row["productId"] == pid
    assert row["productName"] == "Sorento CRM"
    assert row["problem"] == "Let CS export orders to Excel"  # trimmed
    assert row["rawText"] == "full context here"  # trimmed
    assert row["source"] == "manual"  # default
    # Submitter is the logged-in operator, human-readable (never a UUID).
    assert row["submitterName"] == "Demo User"
    assert row["attachments"] == []
    idea_id = row["id"]

    # Appears in the active list.
    listed = ideation_client.get(
        "/ideation/ideas", headers=h, params={"filter": "active"}
    ).json()
    assert idea_id in {r["id"] for r in listed}

    # And in detail.
    detail = ideation_client.get(f"/ideation/ideas/{idea_id}", headers=h)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "captured"


def test_operator_create_persists_segregated_fields(ideation_client):
    """The segregated intake fields (proposedSolution / impact / department) are
    accepted camelCase, persisted, and returned camelCase by the serializer."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)

    res = ideation_client.post(
        "/ideation/ideas",
        headers=h,
        json={
            "productId": pid,
            "problem": "Let CS export orders to Excel",
            "proposedSolution": "  Add an Export button on the orders list  ",
            "impact": "  Saves 30 minutes a day  ",
            "department": "  Customer Service  ",
        },
    )
    assert res.status_code == 201, res.text
    row = res.json()
    assert row["proposedSolution"] == "Add an Export button on the orders list"  # trimmed
    assert row["impact"] == "Saves 30 minutes a day"  # trimmed
    assert row["department"] == "Customer Service"  # trimmed
    idea_id = row["id"]

    # Round-trips through detail (serializer returns the camelCase columns).
    got = ideation_client.get(f"/ideation/ideas/{idea_id}", headers=h).json()
    assert got["proposedSolution"] == "Add an Export button on the orders list"
    assert got["impact"] == "Saves 30 minutes a day"
    assert got["department"] == "Customer Service"


def test_operator_create_segregated_fields_default_null(ideation_client):
    """Omitting the segregated fields leaves them null (only ``problem`` required)."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    res = ideation_client.post(
        "/ideation/ideas", headers=h, json={"productId": pid, "problem": "bare idea"}
    )
    assert res.status_code == 201, res.text
    row = res.json()
    assert row["proposedSolution"] is None
    assert row["impact"] is None
    assert row["department"] is None


def test_operator_edit_updates_segregated_fields(ideation_client):
    """PATCH updates the segregated fields; blank clears an optional one."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    created = ideation_client.post(
        "/ideation/ideas",
        headers=h,
        json={
            "productId": pid,
            "problem": "p",
            "proposedSolution": "old solution",
            "impact": "old impact",
            "department": "Ops",
        },
    ).json()
    idea_id = created["id"]

    res = ideation_client.patch(
        f"/ideation/ideas/{idea_id}",
        headers=h,
        json={"proposedSolution": "new solution", "department": ""},
    )
    assert res.status_code == 200, res.text
    row = res.json()
    assert row["proposedSolution"] == "new solution"
    assert row["department"] is None  # blank clears it
    assert row["impact"] == "old impact"  # untouched


def test_operator_create_source_override(ideation_client):
    """``source`` is accepted when provided (defaults to ``manual`` otherwise)."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)

    res = ideation_client.post(
        "/ideation/ideas",
        headers=h,
        json={"productId": pid, "problem": "voice captured idea", "source": "voice"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["source"] == "voice"


def test_operator_create_unknown_product_rejected(ideation_client):
    """A product that does not resolve for the tenant is refused (not a 2xx)."""
    h = _auth(ideation_client)
    res = ideation_client.post(
        "/ideation/ideas",
        headers=h,
        json={"productId": "does-not-exist", "problem": "x"},
    )
    assert res.status_code in (400, 404, 422), res.text


def test_operator_create_permission_denied_403(ideation_client):
    """Without ``ideation.ideas.submit`` the create is refused."""
    _make_user(
        ideation_client._factory,
        "viewonly@example.com",
        "viewonly1234",
        {"ideation.ideas.view"},
    )
    h_admin = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h_admin)
    h = _auth(ideation_client, email="viewonly@example.com", password="viewonly1234")
    res = ideation_client.post(
        "/ideation/ideas", headers=h, json={"productId": pid, "problem": "x"}
    )
    assert res.status_code == 403, res.text


def test_operator_created_idea_has_null_submitter_contact(ideation_client):
    """Operator-authored ideas carry NO submitter contact (the column is
    nullable) — the display name comes from the operator, not a contact."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    res = ideation_client.post(
        "/ideation/ideas", headers=h, json={"productId": pid, "problem": "nullable check"}
    )
    assert res.status_code == 201, res.text
    idea_id = res.json()["id"]
    assert res.json()["submitterName"] == "Demo User"

    from modules.ideation.models import Idea

    db = ideation_client._factory()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        assert idea is not None
        assert idea.submitter_contact_id is None
    finally:
        db.close()


# ── edit (operator) ───────────────────────────────────────────────────────────


def test_operator_edit_updates_fields(ideation_client):
    """PATCH updates the editable fields and persists them."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    pid2 = _create_software_product(ideation_client, h, name="EcoHub")
    created = ideation_client.post(
        "/ideation/ideas", headers=h, json={"productId": pid, "problem": "before"}
    ).json()
    idea_id = created["id"]

    res = ideation_client.patch(
        f"/ideation/ideas/{idea_id}",
        headers=h,
        json={"productId": pid2, "problem": "  after  ", "rawText": "  new notes  "},
    )
    assert res.status_code == 200, res.text
    row = res.json()
    assert row["productId"] == pid2
    assert row["productName"] == "EcoHub"
    assert row["problem"] == "after"
    assert row["rawText"] == "new notes"
    # Status is untouched by an edit.
    assert row["status"] == "captured"

    # Persisted — a fresh GET reflects it.
    got = ideation_client.get(f"/ideation/ideas/{idea_id}", headers=h).json()
    assert got["problem"] == "after"
    assert got["productId"] == pid2


def test_operator_edit_partial_leaves_untouched_fields(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    created = ideation_client.post(
        "/ideation/ideas",
        headers=h,
        json={"productId": pid, "problem": "keep me", "rawText": "keep notes"},
    ).json()
    idea_id = created["id"]

    res = ideation_client.patch(
        f"/ideation/ideas/{idea_id}", headers=h, json={"problem": "changed"}
    )
    assert res.status_code == 200, res.text
    row = res.json()
    assert row["problem"] == "changed"
    assert row["rawText"] == "keep notes"  # untouched
    assert row["productId"] == pid  # untouched


def test_operator_edit_404_missing_idea(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.patch(
        "/ideation/ideas/nope", headers=h, json={"problem": "x"}
    )
    assert res.status_code == 404, res.text


def test_operator_edit_unknown_product_rejected(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    created = ideation_client.post(
        "/ideation/ideas", headers=h, json={"productId": pid, "problem": "x"}
    ).json()
    res = ideation_client.patch(
        f"/ideation/ideas/{created['id']}",
        headers=h,
        json={"productId": "does-not-exist"},
    )
    assert res.status_code in (400, 404, 422), res.text


def test_operator_edit_permission_denied_403(ideation_client):
    """Without ``ideation.triage.manage`` the edit is refused."""
    _make_user(
        ideation_client._factory,
        "submitter@example.com",
        "submitter1234",
        {"ideation.ideas.view", "ideation.ideas.submit"},
    )
    h_admin = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h_admin)
    created = ideation_client.post(
        "/ideation/ideas", headers=h_admin, json={"productId": pid, "problem": "x"}
    ).json()
    h = _auth(ideation_client, email="submitter@example.com", password="submitter1234")
    res = ideation_client.patch(
        f"/ideation/ideas/{created['id']}", headers=h, json={"problem": "y"}
    )
    assert res.status_code == 403, res.text
