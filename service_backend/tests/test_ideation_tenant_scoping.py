"""Ideation FIX 1 - operator reads are tenant-scoped, and chat-captured (intake)
ideas are visible to the *same-tenant* operator, never leaked to another tenant.

Root cause this pins down: intake ``create_idea`` writes an Idea under the
workspace key's tenant (``api_ws.tenant_id``); the operator Ideas surface reads
under ``current_user.tenant_id``. The two MUST resolve the same tenant for a
given workspace, and every read (``list`` / ``board`` / ``get``) MUST be
tenant-scoped so nothing leaks across tenants.

Also covers the new optional ``product_id`` scope on ``list`` / ``board`` (the
canonical ideation scope - an idea belongs to a product, which belongs to a
tenant); the product filter never widens visibility across tenants.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"


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


def _set_delivery(client, h, product_id, base="https://fe-sorento.foundryx.my") -> None:
    res = client.put(
        f"/ideation/products/{product_id}/delivery",
        headers=h,
        json={"productDomainBase": base},
    )
    assert res.status_code == 200, res.text


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


def _make_contact(factory, phone="+60123456789") -> str:
    from modules.omnichannel.models import Contact

    db = factory()
    try:
        c = Contact(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=_default_workspace_id(db),
            first_name="Jayson",
            last_name="Tan",
            phone=phone,
        )
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


_FULL_FIELDS = {
    "proposed_solution": "Add an Export to Excel button on the orders list",
    "impact": "Saves 30 minutes a day",
    "department": "Customer Service",
}


def _capture_idea_via_intake(client, key, contact_id, product_id) -> str:
    """Drive the deterministic intake to a *completed* (status=captured) Idea -
    exactly the chat-capture path the sorento brain calls. Returns the idea id."""
    # Turn 1: seed problem + all fields -> review (never auto-completes).
    r1 = client.post(
        "/ideation/intake/create-idea",
        headers=_key_auth(key),
        json={
            "product_id": product_id,
            "submitter_contact_id": contact_id,
            "message_text": "Let CS export orders to Excel",
            "fields": _FULL_FIELDS,
        },
    )
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["status"] == "review", body
    draft_id = body["draft_id"]
    # Turn 2: confirm -> complete (draft -> captured).
    r2 = client.post(
        "/ideation/intake/create-idea",
        headers=_key_auth(key),
        json={
            "product_id": product_id,
            "submitter_contact_id": contact_id,
            "message_text": "confirm",
            "draft_id": draft_id,
            "confirm": True,
        },
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "complete", r2.text
    return draft_id


# ── the fix: chat-captured idea is visible to the same-tenant operator ─────────


def test_intake_captured_idea_visible_to_same_tenant_operator(ideation_client):
    """AC: an idea created via intake under workspace tenant T is returned by the
    operator ``list`` AND ``board`` for a user of tenant T (the must-fix)."""
    factory = ideation_client._factory
    h = _auth(ideation_client)  # operator on DEFAULT tenant (== workspace tenant)
    pid = _create_software_product(ideation_client, h)
    _set_delivery(ideation_client, h, pid)
    contact_id = _make_contact(factory)
    key = _mint_key(factory)

    idea_id = _capture_idea_via_intake(ideation_client, key, contact_id, pid)

    # Operator list (tenant T) sees the chat-captured idea.
    listed = ideation_client.get("/ideation/ideas", headers=h).json()
    assert idea_id in {r["id"] for r in listed}

    # Operator board (tenant T) shows it in the "captured" column.
    board = ideation_client.get("/ideation/ideas/board", headers=h).json()
    captured = next(c for c in board["columns"] if c["key"] == "captured")
    assert idea_id in {i["id"] for i in captured["ideas"]}


def test_reads_are_tenant_scoped_no_cross_tenant_leak(ideation_client):
    """list / board / get are all tenant-scoped: an idea under DEFAULT tenant is
    NOT returned to another tenant, and ``get`` refuses cross-tenant (no leak)."""
    from modules.ideation.services.ideas import IdeaReadService

    factory = ideation_client._factory
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    _set_delivery(ideation_client, h, pid)
    contact_id = _make_contact(factory)
    key = _mint_key(factory)
    idea_id = _capture_idea_via_intake(ideation_client, key, contact_id, pid)

    db = factory()
    try:
        svc = IdeaReadService(db)

        # Same tenant → visible via all three reads.
        assert idea_id in {i.id for i in svc.list(DEFAULT_TENANT_ID, filter="all")}
        board_ids = {
            i.id for c in svc.board(DEFAULT_TENANT_ID).columns for i in c.ideas
        }
        assert idea_id in board_ids
        assert svc.get(DEFAULT_TENANT_ID, idea_id).id == idea_id

        # Different tenant → list/board empty of it, get raises 404 (no leak).
        assert idea_id not in {i.id for i in svc.list(OTHER_TENANT_ID, filter="all")}
        other_board_ids = {
            i.id for c in svc.board(OTHER_TENANT_ID).columns for i in c.ideas
        }
        assert idea_id not in other_board_ids
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            svc.get(OTHER_TENANT_ID, idea_id)
        assert exc.value.status_code == 404
    finally:
        db.close()


# ── the new optional product_id scope ─────────────────────────────────────────


def test_product_id_filter_scopes_list_and_board_within_tenant(ideation_client):
    """``product_id`` narrows list/board to one product; it never crosses tenants
    and defaults (None) to every product in the tenant."""
    from modules.ideation.services.ideas import IdeaReadService

    factory = ideation_client._factory
    h = _auth(ideation_client)
    pid_a = _create_software_product(ideation_client, h, name="Sorento CRM")
    pid_b = _create_software_product(ideation_client, h, name="Rigel POS")
    _set_delivery(ideation_client, h, pid_a)
    _set_delivery(ideation_client, h, pid_b)
    contact_id = _make_contact(factory)
    key = _mint_key(factory)
    idea_a = _capture_idea_via_intake(ideation_client, key, contact_id, pid_a)
    idea_b = _capture_idea_via_intake(ideation_client, key, contact_id, pid_b)

    db = factory()
    try:
        svc = IdeaReadService(db)

        # No filter → both products' ideas.
        all_ids = {i.id for i in svc.list(DEFAULT_TENANT_ID, filter="all")}
        assert {idea_a, idea_b} <= all_ids

        # Filter to product A → only A's idea (list + board).
        a_ids = {
            i.id
            for i in svc.list(DEFAULT_TENANT_ID, filter="all", product_id=pid_a)
        }
        assert idea_a in a_ids and idea_b not in a_ids
        a_board = {
            i.id
            for c in svc.board(DEFAULT_TENANT_ID, product_id=pid_a).columns
            for i in c.ideas
        }
        assert idea_a in a_board and idea_b not in a_board

        # product_id filter never crosses tenants (empty for the other tenant).
        assert svc.list(OTHER_TENANT_ID, filter="all", product_id=pid_a) == []
    finally:
        db.close()


def test_list_router_product_id_query_param(ideation_client):
    """The operator ``list`` endpoint honours the optional ``productId`` query."""
    factory = ideation_client._factory
    h = _auth(ideation_client)
    pid_a = _create_software_product(ideation_client, h, name="Sorento CRM")
    pid_b = _create_software_product(ideation_client, h, name="Rigel POS")
    _set_delivery(ideation_client, h, pid_a)
    _set_delivery(ideation_client, h, pid_b)
    contact_id = _make_contact(factory)
    key = _mint_key(factory)
    idea_a = _capture_idea_via_intake(ideation_client, key, contact_id, pid_a)
    idea_b = _capture_idea_via_intake(ideation_client, key, contact_id, pid_b)

    scoped = ideation_client.get(
        "/ideation/ideas", headers=h, params={"productId": pid_a, "filter": "all"}
    ).json()
    ids = {r["id"] for r in scoped}
    assert idea_a in ids and idea_b not in ids
