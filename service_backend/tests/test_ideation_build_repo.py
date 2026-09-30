"""BR Send to build - S1: product -> repository mapping (AC-STB-01, AC-STB-03).

RED until ``product_delivery.build_repo`` + ``DeliveryConfigIn/Out.buildRepo``
land. Every test seeds its own product; nothing borrows seeded rows.
"""
import pytest

from app.models import DEFAULT_TENANT_ID
from tests.ideation_build_helpers import (  # noqa: F401
    OTHER_TENANT_ID,
    _auth,
    _make_user,
    _product,
    ensure_other_tenant,
    ideation_client,
)


def _put(client, h, pid, body):
    return client.put(f"/ideation/products/{pid}/delivery", headers=h, json=body)


def test_ac_stb_01_put_persists_build_repo_and_get_returns_it(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = _put(
        ideation_client,
        h,
        pid,
        {"productDomainBase": "https://fe-sorento.foundryx.my", "buildRepo": "jayson-odoo/sorento-crm"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["buildRepo"] == "jayson-odoo/sorento-crm"
    got = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h)
    assert got.status_code == 200, got.text
    assert got.json()["buildRepo"] == "jayson-odoo/sorento-crm"


def test_ac_stb_01_existing_domain_base_round_trip_unchanged(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = _put(
        ideation_client,
        h,
        pid,
        {"productDomainBase": "https://fe-sorento.foundryx.my", "buildRepo": "a/b"},
    )
    assert res.status_code == 200, res.text
    got = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h).json()
    assert got["productDomainBase"] == "https://fe-sorento.foundryx.my"
    assert got["productId"] == pid


def test_ac_stb_01_null_build_repo_clears_it(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    base = "https://fe-sorento.foundryx.my"
    assert _put(ideation_client, h, pid, {"productDomainBase": base, "buildRepo": "a/b"}).status_code == 200
    res = _put(ideation_client, h, pid, {"productDomainBase": base, "buildRepo": None})
    assert res.status_code == 200, res.text
    assert res.json()["buildRepo"] is None
    got = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h).json()
    assert got["buildRepo"] is None
    assert got["productDomainBase"] == base


def test_ac_stb_01_get_without_row_has_null_build_repo(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    got = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h)
    assert got.status_code == 200, got.text
    assert "buildRepo" in got.json()
    assert got.json()["buildRepo"] is None


@pytest.mark.parametrize(
    "bad",
    ["no-slash", "a/b/c", "/repo", "owner/", "owner/re po", "owner/re*po", "", "https://github.com/a/b"],
)
def test_ac_stb_01_bad_shape_is_422(ideation_client, bad):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = _put(
        ideation_client,
        h,
        pid,
        {"productDomainBase": "https://fe-sorento.foundryx.my", "buildRepo": bad},
    )
    assert res.status_code == 422, (bad, res.text)
    # Nothing persisted by the refused write.
    got = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h).json()
    assert got.get("buildRepo") is None


@pytest.mark.parametrize("good", ["a/b", "Jayson_Odoo/sorento.crm-2", "o-1/r_2.x"])
def test_ac_stb_01_valid_shapes_accepted(ideation_client, good):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = _put(
        ideation_client,
        h,
        pid,
        {"productDomainBase": "https://fe-sorento.foundryx.my", "buildRepo": good},
    )
    assert res.status_code == 200, res.text
    assert res.json()["buildRepo"] == good


def test_ac_stb_01_requires_products_manage(ideation_client, ideation_session_factory):
    _make_user(
        ideation_session_factory,
        "norepo@example.com",
        "NoRepo123!",
        {"ideation.business_requirements.read"},
    )
    admin = _auth(ideation_client)
    pid = _product(ideation_client, admin)
    h = _auth(ideation_client, email="norepo@example.com", password="NoRepo123!")
    res = _put(
        ideation_client,
        h,
        pid,
        {"productDomainBase": "https://fe-sorento.foundryx.my", "buildRepo": "a/b"},
    )
    assert res.status_code == 403, res.text


def test_ac_stb_03_other_tenants_product_is_404_and_never_written(
    ideation_client, ideation_session_factory
):
    """Tenant B's product id under tenant A's Maintainer: 404 (never 403, never
    a leak), and B's row gains no build_repo."""
    from app.models.catalog import Product
    from modules.ideation.models import ProductDelivery

    other = ensure_other_tenant(ideation_session_factory)
    db = ideation_session_factory()
    try:
        product = Product(tenant_id=other, name="Foreign", kind="software")
        db.add(product)
        db.commit()
        foreign_id = product.id
    finally:
        db.close()

    h = _auth(ideation_client)
    res = _put(
        ideation_client,
        h,
        foreign_id,
        {"productDomainBase": "https://fe-x.example.com", "buildRepo": "a/b"},
    )
    assert res.status_code == 404, res.text
    assert "a/b" not in res.text
    got = ideation_client.get(f"/ideation/products/{foreign_id}/delivery", headers=h)
    assert got.status_code == 404, got.text

    db = ideation_session_factory()
    try:
        assert (
            db.query(ProductDelivery)
            .filter(ProductDelivery.product_id == foreign_id)
            .count()
            == 0
        )
    finally:
        db.close()


def test_ac_stb_01_build_repo_column_exists_on_model():
    """Schema pin: the nullable ``build_repo`` column on product_delivery."""
    from modules.ideation.models import ProductDelivery

    col = ProductDelivery.__table__.c.build_repo
    assert col.nullable is True
