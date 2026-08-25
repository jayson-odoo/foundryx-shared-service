"""Core catalog tests (sprint-4/08) - products + categories in core public.

kind registry (core + ems-registered, active filter) · currency default + override
· product soft-delete only + reference-guard delete-block · category tree + cycle
guard · tenant default currency settings.
"""
from app.models.tenant import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _admin(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_product_crud_and_currency_override(client):
    h = _admin(client)
    # kinds: core good/service (EMS-registered kinds are stripped from this fork)
    kinds = {k["key"] for k in client.get("/products/kinds", headers=h).json()}
    assert {"good", "service"} <= kinds

    r = client.post("/products", headers=h, json={"name": "VIP Pass", "kind": "service", "defaultPrice": 199.5, "currency": "usd"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["kind"] == "service" and p["kindLabel"] == "Service"
    assert p["defaultPrice"] == 199.5 and p["currency"] == "USD"

    # unknown kind rejected
    assert client.post("/products", headers=h, json={"name": "X", "kind": "bogus"}).status_code == 422

    # list + get
    assert client.get("/products", headers=h).json()["total"] >= 1
    assert client.get(f"/products/{p['id']}", headers=h).json()["name"] == "VIP Pass"


def test_tenant_default_currency(client):
    h = _admin(client)
    assert client.get("/settings/general", headers=h).json()["defaultCurrency"]  # app default
    assert client.put("/settings/general", headers=h, json={"defaultCurrency": "myr"}).json()["defaultCurrency"] == "MYR"
    assert client.put("/settings/general", headers=h, json={"defaultCurrency": "US"}).status_code == 422


def test_product_soft_delete_only(client, session_factory):
    # NOTE: the CRM quotation reference-guard leg was dropped - the CRM module
    # (which registered products-in-quotations into the reference-count registry)
    # is stripped from this shared-service fork. Core coverage kept: a product
    # soft-deletes (never hard delete) when nothing references it.
    h = _admin(client)
    # an unreferenced product soft-deletes (never hard delete)
    free = client.post("/products", headers=h, json={"name": "Free", "kind": "good"}).json()
    assert client.delete(f"/products/{free['id']}", headers=h).status_code == 204
    with session_factory() as db:
        from app.models.catalog import Product

        row = db.query(Product).filter(Product.id == free["id"]).first()
        assert row is not None and row.is_deleted is True  # soft, still present


def test_category_tree_and_cycle_guard(client):
    h = _admin(client)
    root = client.post("/product-categories", headers=h, json={"name": "Tickets"}).json()
    child = client.post("/product-categories", headers=h, json={"name": "VIP", "parentId": root["id"]}).json()
    # cycle: make root a child of its own descendant → 422
    assert client.patch(f"/product-categories/{root['id']}", headers=h, json={"parentId": child["id"]}).status_code == 422
    # delete guard: root has a child
    assert client.delete(f"/product-categories/{root['id']}", headers=h).status_code == 409
    # leaf deletes
    assert client.delete(f"/product-categories/{child['id']}", headers=h).status_code == 204
