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


# ── SEC F3: path-traversal / dot-segment / leading-dash shapes ───────────────


@pytest.mark.parametrize("bad", ["../user", "./x", "a/..", "a/.", "-/x"])
def test_sec_f3_ac_stb_01_traversal_shapes_are_422(ideation_client, bad):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = _put(
        ideation_client,
        h,
        pid,
        {"productDomainBase": "https://fe-sorento.foundryx.my", "buildRepo": bad},
    )
    assert res.status_code == 422, (bad, res.text)
    got = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h).json()
    assert got.get("buildRepo") is None


@pytest.mark.parametrize("good", ["jayson-odoo/crew-intake-sandbox", "a.b/c_d-e"])
def test_sec_f3_ac_stb_01_legitimate_shapes_still_accepted(ideation_client, good):
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


# ── R6: productDomainBase optional on the delivery PUT ───────────────────────


def test_r6_ac_stb_01_put_only_build_repo_without_a_domain_base(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)  # no delivery row yet, so no domain base
    res = _put(ideation_client, h, pid, {"buildRepo": "owner/repo"})
    assert res.status_code == 200, res.text
    assert res.json()["buildRepo"] == "owner/repo"
    assert res.json()["productDomainBase"] is None
    got = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h).json()
    assert got["buildRepo"] == "owner/repo" and got["productDomainBase"] is None


def test_r6_ac_stb_01_omitted_domain_base_is_left_untouched(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    base = "https://fe-sorento.foundryx.my"
    assert _put(ideation_client, h, pid, {"productDomainBase": base, "buildRepo": "a/b"}).status_code == 200
    res = _put(ideation_client, h, pid, {"buildRepo": "c/d"})
    assert res.status_code == 200, res.text
    assert res.json()["productDomainBase"] == base
    assert res.json()["buildRepo"] == "c/d"


def test_r6_ac_stb_01_present_domain_base_is_still_validated(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    for bad in ("not a url", "https://x.example.com/path"):
        res = _put(ideation_client, h, pid, {"productDomainBase": bad, "buildRepo": "a/b"})
        assert res.status_code == 422, (bad, res.text)
    got = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h).json()
    assert got["buildRepo"] is None  # the refused write persisted nothing


def test_r6_ac_stb_01_empty_body_leaves_everything_untouched(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    base = "https://fe-sorento.foundryx.my"
    assert _put(ideation_client, h, pid, {"productDomainBase": base, "buildRepo": "a/b"}).status_code == 200
    res = _put(ideation_client, h, pid, {})
    assert res.status_code == 200, res.text
    assert res.json()["productDomainBase"] == base and res.json()["buildRepo"] == "a/b"


@pytest.mark.parametrize("bad", ["no-slash", "../user", "a/b/c", ""])
def test_r6_ac_stb_01_invalid_build_repo_422_body_has_message_and_field_errors(
    ideation_client, bad
):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = _put(ideation_client, h, pid, {"buildRepo": bad})
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert isinstance(detail, dict), detail
    assert isinstance(detail["message"], str) and detail["message"]
    assert isinstance(detail["fieldErrors"]["buildRepo"], str) and detail["fieldErrors"]["buildRepo"]
