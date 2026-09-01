"""Ideation Slice 3 - Idea entity + status engine + list/detail read.

Covers AC-A-09 (Idea entity fields in ``app_ideation.ideas``; no embedding
column), AC-A-10 (Idea rides the core status engine as a tenant-owned entity -
lifecycle draft→captured→…→closed +duplicate/+rejected, initial draft,
transitions via ``status_machine``; legal transition succeeds, illegal refused)
and AC-A-12 (``GET /ideation/ideas`` list + ``GET /ideation/ideas/{id}`` detail,
matching the FE Idea shape - every section present, submitter human-readable).

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


def _default_workspace_id(db) -> str:
    from modules.omnichannel.models import Workspace

    ws = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True))
        .first()
    )
    assert ws is not None, "omnichannel default workspace not seeded"
    return ws.id


def _make_contact(factory, first_name="Jayson", last_name="Tan", phone="+60123456789") -> str:
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


_IDEA_SEQ = [0]


def _insert_idea(
    factory,
    product_id,
    problem="Let CS export orders to Excel",
    raw_text=None,
    status_key="draft",
    source="whatsapp",
    submitter_contact_id=None,
    upvotes=0,
    priority=0,
    created_at=None,
) -> str:
    from datetime import datetime, timedelta, timezone

    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    # Distinct, strictly-increasing timestamps so "newest first" is deterministic
    # (SQLite CURRENT_TIMESTAMP only has 1s resolution - rapid inserts would tie).
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
            raw_text=raw_text if raw_text is not None else problem,
            source=source,
            submitter_contact_id=submitter_contact_id,
            upvotes=upvotes,
            priority=priority,
            created_at=created_at,
        )
        db.add(idea)
        db.commit()
        return idea.id
    finally:
        db.close()


def _make_limited_user(factory, email, password, perm_keys):
    from app.models import Role, User, UserStatus
    from app.models.permission import Permission

    db = factory()
    try:
        perms = db.query(Permission).filter(Permission.key.in_(list(perm_keys))).all()
        role = Role(
            tenant_id=DEFAULT_TENANT_ID,
            name="Limited",
            description="Limited role",
            is_system=False,
        )
        role.permissions = perms
        db.add(role)
        db.flush()
        user = User(
            tenant_id=DEFAULT_TENANT_ID,
            email=email,
            password=hash_password(password),
            name="Limited User",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
        user.roles = [role]
        db.add(user)
        db.commit()
    finally:
        db.close()


# ── AC-A-10: Idea rides the status engine (tenant-owned) ──────────────────────


def test_idea_registered_as_tenant_owned_status_entity(ideation_session_factory):
    # Force module boot so register_engine_entities runs.
    ideation_session_factory()
    from app.status_engine.registry import get_status_entity

    entity = get_status_entity("idea")
    assert entity is not None, "idea status entity not registered"
    assert entity.entity_type == "idea"
    assert entity.module == "ideation"
    assert entity.platform_owned is False  # tenant-owned
    assert entity.scoped is False


def test_idea_statuses_seeded_with_draft_initial(ideation_session_factory):
    from app.models.status import Status

    db = ideation_session_factory()
    try:
        rows = (
            db.query(Status)
            .filter(Status.entity_type == "idea", Status.tenant_id.is_(None))
            .all()
        )
        keys = {r.key for r in rows}
        assert {
            "draft",
            "captured",
            "triaged",
            "linked",
            "building",
            "delivered",
            "closed",
            "duplicate",
            "rejected",
        } <= keys
        initials = [r for r in rows if r.is_initial]
        assert len(initials) == 1 and initials[0].key == "draft"
        # Off-ramps are terminal.
        by_key = {r.key: r for r in rows}
        assert by_key["closed"].is_terminal
        assert by_key["rejected"].is_terminal
        assert by_key["duplicate"].is_terminal
    finally:
        db.close()


def test_legal_transition_draft_to_captured(ideation_session_factory):
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id
    from app.services import status_machine

    factory = ideation_session_factory
    db = factory()
    try:
        # Need a product to satisfy the FK; create one inline.
        from app.models.catalog import Product

        product = Product(tenant_id=DEFAULT_TENANT_ID, name="P", kind="software")
        db.add(product)
        db.flush()
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=product.id,
            status_id=idea_status_id(db, "draft"),
            problem="x",
            raw_text="x",
            source="manual",
        )
        db.add(idea)
        db.commit()

        captured_id = idea_status_id(db, "captured")
        status_machine.transition(
            db, "idea", idea, captured_id, tenant_id=DEFAULT_TENANT_ID
        )
        db.refresh(idea)
        assert idea.status_id == captured_id
    finally:
        db.close()


def test_illegal_transition_refused(ideation_session_factory):
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id
    from app.services import status_machine
    from app.services.status_machine import TransitionNotAllowed

    factory = ideation_session_factory
    db = factory()
    try:
        from app.models.catalog import Product

        product = Product(tenant_id=DEFAULT_TENANT_ID, name="P", kind="software")
        db.add(product)
        db.flush()
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=product.id,
            status_id=idea_status_id(db, "draft"),
            problem="x",
            raw_text="x",
            source="manual",
        )
        db.add(idea)
        db.commit()

        delivered_id = idea_status_id(db, "delivered")
        with pytest.raises(TransitionNotAllowed):
            status_machine.transition(
                db, "idea", idea, delivered_id, tenant_id=DEFAULT_TENANT_ID
            )
    finally:
        db.close()


# ── AC-A-09: Idea entity has no embedding column ──────────────────────────────


def test_idea_model_has_no_embedding_column():
    from modules.ideation.models import Idea

    cols = set(Idea.__table__.c.keys())
    assert "embedding" not in cols
    # Core §4 fields present.
    assert {
        "id",
        "tenant_id",
        "product_id",
        "status_id",
        "intake_definition_key",
        "problem",
        "raw_text",
        "source",
        "submitter_contact_id",
        "captured_json",
        "upvotes",
        "priority",
        "created_at",
        "updated_at",
    } <= cols


# ── AC-A-12: list read ────────────────────────────────────────────────────────


def test_list_ideas_returns_rows_newest_first(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    contact_id = _make_contact(ideation_client._factory)
    _insert_idea(
        ideation_client._factory, pid, problem="older", status_key="captured",
        submitter_contact_id=contact_id,
    )
    _insert_idea(
        ideation_client._factory, pid, problem="newer", status_key="triaged",
        submitter_contact_id=contact_id,
    )

    res = ideation_client.get("/ideation/ideas", headers=h)
    assert res.status_code == 200, res.text
    data = res.json()
    assert isinstance(data, list) and len(data) == 2
    # Newest first.
    assert data[0]["problem"] == "newer"
    # FE Idea shape.
    row = data[0]
    assert row["productId"] == pid
    assert row["productName"] == "Sorento CRM"
    assert row["status"] == "triaged"
    assert row["submitterName"] == "Jayson Tan"  # human-readable, not a UUID
    assert row["source"] == "whatsapp"
    assert "upvotes" in row and "priority" in row
    assert row["attachments"] == []


def test_list_ideas_search_filters_by_problem(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    _insert_idea(ideation_client._factory, pid, problem="export orders to excel")
    _insert_idea(ideation_client._factory, pid, problem="supplier lead time on PO")

    res = ideation_client.get("/ideation/ideas", headers=h, params={"search": "excel"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data) == 1
    assert "export" in data[0]["problem"]


def test_list_ideas_active_vs_archived_filter(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    _insert_idea(ideation_client._factory, pid, problem="active one", status_key="captured")
    _insert_idea(ideation_client._factory, pid, problem="rejected one", status_key="rejected")

    active = ideation_client.get(
        "/ideation/ideas", headers=h, params={"filter": "active"}
    ).json()
    assert {r["problem"] for r in active} == {"active one"}

    archived = ideation_client.get(
        "/ideation/ideas", headers=h, params={"filter": "archived"}
    ).json()
    assert {r["problem"] for r in archived} == {"rejected one"}

    all_rows = ideation_client.get(
        "/ideation/ideas", headers=h, params={"filter": "all"}
    ).json()
    assert len(all_rows) == 2


# ── AC-A-12: detail read ──────────────────────────────────────────────────────


def test_get_idea_detail_shape(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    contact_id = _make_contact(ideation_client._factory, first_name="Director", last_name="Lim")
    idea_id = _insert_idea(
        ideation_client._factory, pid, problem="show lead time",
        status_key="captured", submitter_contact_id=contact_id, upvotes=3,
    )

    res = ideation_client.get(f"/ideation/ideas/{idea_id}", headers=h)
    assert res.status_code == 200, res.text
    row = res.json()
    assert row["id"] == idea_id
    assert row["productName"] == "Sorento CRM"
    assert row["submitterName"] == "Director Lim"
    assert row["status"] == "captured"
    assert row["upvotes"] == 3
    # Every section present with an empty state.
    assert row["attachments"] == []
    assert "rawText" in row and "createdAt" in row


def test_get_idea_detail_unknown_submitter(ideation_client):
    """An idea with no resolvable submitter still renders (empty-state name)."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    idea_id = _insert_idea(ideation_client._factory, pid, submitter_contact_id=None)

    res = ideation_client.get(f"/ideation/ideas/{idea_id}", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["submitterName"] == "Unknown"


def test_get_idea_404(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.get("/ideation/ideas/does-not-exist", headers=h)
    assert res.status_code == 404, res.text


def test_ideas_read_permission_denied_403(ideation_client):
    _make_limited_user(
        ideation_client._factory, "limited@example.com", "limited1234", {"products.read"}
    )
    h = _auth(ideation_client, email="limited@example.com", password="limited1234")
    res = ideation_client.get("/ideation/ideas", headers=h)
    assert res.status_code == 403, res.text
