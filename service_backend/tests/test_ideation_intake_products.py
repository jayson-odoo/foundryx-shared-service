"""Ideation intake read route - ``GET /ideation/intake/products``.

Public (workspace-key authed) lookup the sorento admin uses to bind a workspace to
a software Product by NAME (no UUID pasting). Covers:

- returns the KEY's tenant's ``kind == 'software'`` products (excludes goods);
- excludes other tenants' products (tenant derived from the key, never the request);
- excludes soft-deleted products;
- 401 without a valid workspace key (uniform ``{error:{code,message}}`` envelope).
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


def _create_product(client, h, name, kind) -> str:
    res = client.post("/products", headers=h, json={"name": name, "kind": kind})
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


def test_lists_tenant_software_products(ideation_client):
    """Returns the tenant's software products (id/name/kind); excludes goods."""
    h = _auth(ideation_client)
    sw_id = _create_product(ideation_client, h, "Sorento CRM", "software")
    _create_product(ideation_client, h, "A4 Paper Ream", "good")
    key = _mint_key(ideation_client._factory)

    res = ideation_client.get("/ideation/intake/products", headers=_key_auth(key))
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body, list)
    names = {p["name"] for p in body}
    assert "Sorento CRM" in names
    assert "A4 Paper Ream" not in names
    row = next(p for p in body if p["name"] == "Sorento CRM")
    assert row["id"] == sw_id
    assert row["kind"] == "software"


def test_excludes_soft_deleted(ideation_client):
    """A soft-deleted software product is not returned."""
    h = _auth(ideation_client)
    _create_product(ideation_client, h, "Live Product", "software")
    dead_id = _create_product(ideation_client, h, "Dead Product", "software")

    # Soft-delete directly against the DB (delete API may be reference-guarded).
    factory = ideation_client._factory
    db = factory()
    try:
        from app.models.catalog import Product

        db.query(Product).filter(Product.id == dead_id).update({"is_deleted": True})
        db.commit()
    finally:
        db.close()

    key = _mint_key(factory)
    res = ideation_client.get("/ideation/intake/products", headers=_key_auth(key))
    assert res.status_code == 200, res.text
    names = {p["name"] for p in res.json()}
    assert "Live Product" in names
    assert "Dead Product" not in names


def test_excludes_other_tenants(ideation_client):
    """A software product owned by another tenant is never returned - tenancy is
    derived from the key, never from the request."""
    h = _auth(ideation_client)
    _create_product(ideation_client, h, "Mine", "software")

    factory = ideation_client._factory
    db = factory()
    try:
        from app.models.catalog import Product

        other = Product(
            tenant_id="other-tenant-xyz",
            name="Theirs",
            kind="software",
        )
        db.add(other)
        db.commit()
    finally:
        db.close()

    key = _mint_key(factory)
    res = ideation_client.get("/ideation/intake/products", headers=_key_auth(key))
    assert res.status_code == 200, res.text
    names = {p["name"] for p in res.json()}
    assert "Mine" in names
    assert "Theirs" not in names


def test_auth_required(ideation_client):
    """No key -> 401 with the uniform envelope; a garbage key -> 401 too."""
    res = ideation_client.get("/ideation/intake/products")
    assert res.status_code == 401, res.text
    assert set(res.json()["error"].keys()) >= {"code", "message"}

    res2 = ideation_client.get(
        "/ideation/intake/products", headers=_key_auth("fxw_live_garbage")
    )
    assert res2.status_code == 401, res2.text
