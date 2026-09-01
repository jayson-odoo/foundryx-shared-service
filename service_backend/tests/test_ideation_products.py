"""Ideation Slice 2 - unified Product: software kind + delivery config + adapters.

Covers AC-A-05 (one Product entity; ideation registers the ``software`` kind, so
the active kind set is good|service|software and ``/products/kinds`` returns it),
AC-A-06 (software delivery config - validated absolute ``product_domain_base`` in
the ideation extension table, set/get), AC-A-07 (polymorphic adapter-kind registry
- ``embed_connection`` wired, github/agent_runner/deploy registered-but-dormant),
AC-A-08 (product CRUD reuses the CORE catalog API; delivery config is an ideation
route gated by ``ideation.products.manage``).

Test-first (PRINCIPLES.md): these were written before the implementation exists.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


# ── fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def ideation_client(ideation_session_factory):
    """A TestClient bound to a session where BOTH omnichannel and ideation are
    installed for the default tenant (mirrors conftest ``client``)."""

    def override_get_db():
        db = ideation_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = ideation_session_factory  # for setup writes
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


def _make_limited_user(factory, email, password, perm_keys):
    """Create a user whose role holds ONLY ``perm_keys`` (no ideation keys)."""
    from app.models import Role, User, UserStatus
    from app.models.permission import Permission
    from sqlalchemy.sql import func

    db = factory()
    try:
        perms = (
            db.query(Permission).filter(Permission.key.in_(list(perm_keys))).all()
        )
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


# ── AC-A-05: software product kind registered by ideation ─────────────────────


def test_software_kind_active_when_ideation_installed(ideation_session_factory):
    from app.catalog.kinds import active_kinds

    db = ideation_session_factory()
    try:
        keys = {k.key for k in active_kinds(db, DEFAULT_TENANT_ID)}
        assert {"good", "service", "software"} <= keys
    finally:
        db.close()


def test_software_kind_hidden_without_ideation(session_factory):
    """Visibility gate: software is registered globally at boot but hidden for a
    tenant that has NOT installed ideation (session_factory = omnichannel only)."""
    from app.catalog.kinds import active_kinds

    db = session_factory()
    try:
        keys = {k.key for k in active_kinds(db, DEFAULT_TENANT_ID)}
        assert "software" not in keys
        assert {"good", "service"} <= keys
    finally:
        db.close()


def test_products_kinds_endpoint_lists_software(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.get("/products/kinds", headers=h)
    assert res.status_code == 200, res.text
    keys = {k["key"] for k in res.json()}
    assert "software" in keys


# ── AC-A-07: adapter-kind registry ────────────────────────────────────────────


def test_adapter_kind_registry_wired_and_dormant():
    from modules.ideation.adapters import (
        active_adapter_kind,
        is_valid_adapter_kind,
        registered_adapter_kinds,
    )

    keys = {k.key for k in registered_adapter_kinds()}
    assert keys == {"embed_connection", "github", "agent_runner", "deploy"}
    # embed_connection is the only Phase-A-wired kind; the rest are dormant.
    assert active_adapter_kind("embed_connection").wired is True
    for dormant in ("github", "agent_runner", "deploy"):
        assert active_adapter_kind(dormant).wired is False
    assert is_valid_adapter_kind("embed_connection")
    assert not is_valid_adapter_kind("nonsense")


# ── AC-A-06 / AC-A-08: delivery config set/get + validation ───────────────────


def test_set_and_get_delivery_config(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)

    # No config yet → productDomainBase is null.
    got = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h)
    assert got.status_code == 200, got.text
    assert got.json()["productId"] == pid
    assert got.json()["productDomainBase"] is None

    put = ideation_client.put(
        f"/ideation/products/{pid}/delivery",
        headers=h,
        json={"productDomainBase": "https://fe-sorento.foundryx.my"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["productDomainBase"] == "https://fe-sorento.foundryx.my"

    # Round-trips + upsert (a second PUT overwrites, no duplicate row).
    again = ideation_client.put(
        f"/ideation/products/{pid}/delivery",
        headers=h,
        json={"productDomainBase": "https://sorento.foundryx.my"},
    )
    assert again.status_code == 200, again.text
    got2 = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h)
    assert got2.json()["productDomainBase"] == "https://sorento.foundryx.my"


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-url",
        "ftp://foo.bar",
        "https://",
        "example.com",
        "https://foo.bar/some/path",
        "https://foo.bar?q=1",
    ],
)
def test_invalid_origin_rejected(ideation_client, bad):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    res = ideation_client.put(
        f"/ideation/products/{pid}/delivery",
        headers=h,
        json={"productDomainBase": bad},
    )
    assert res.status_code == 422, f"{bad!r} should be rejected: {res.text}"


def test_delivery_permission_denied_403(ideation_client):
    _make_limited_user(
        ideation_client._factory, "limited@example.com", "limited1234", {"products.read"}
    )
    h = _auth(ideation_client, email="limited@example.com", password="limited1234")
    admin_h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, admin_h)

    got = ideation_client.get(f"/ideation/products/{pid}/delivery", headers=h)
    assert got.status_code == 403, got.text
    put = ideation_client.put(
        f"/ideation/products/{pid}/delivery",
        headers=h,
        json={"productDomainBase": "https://foo.bar"},
    )
    assert put.status_code == 403, put.text


def test_delivery_on_missing_product_404(ideation_client):
    h = _auth(ideation_client)
    got = ideation_client.get("/ideation/products/does-not-exist/delivery", headers=h)
    assert got.status_code == 404, got.text
    put = ideation_client.put(
        "/ideation/products/does-not-exist/delivery",
        headers=h,
        json={"productDomainBase": "https://foo.bar"},
    )
    assert put.status_code == 404, put.text
