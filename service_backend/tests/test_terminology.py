"""Terminology tests (sprint-3/08, F10) — AC-08-04/05/06/07/14/17.

Registry seed · merged map = defaults ⊕ overrides · PUT upsert + 422 unknown
key + blank-reject · DELETE reset → fallback · tenant isolation · perm gate
(manage for PUT/DELETE, authenticated GET).
"""
from app.models.role import Role
from app.models.user import User, UserStatus
from app.models.tenant import DEFAULT_TENANT_ID
from app.security import hash_password
from tests.conftest import (
    ACTIVE_EMAIL,
    ACTIVE_PASSWORD,
    PLATFORM_EMAIL,
    PLATFORM_PASSWORD,
)


def _login(client, email, password, tenant_slug=None):
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    return client.post("/auth/login", json=payload)


def _headers(res) -> dict:
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _admin_headers(client):
    return _headers(_login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD))


def _make_noperm_user(session_factory, email="noperm@example.com", pw="NoPerm1!"):
    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="ViewerNoTerm", is_system=False)
    role.permissions = []
    db.add(role)
    db.flush()
    u = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=email,
        password=hash_password(pw),
        name="No Perm",
        status=UserStatus.ACTIVE.value,
    )
    u.roles = [role]
    db.add(u)
    db.commit()
    db.close()
    return email, pw


# ---- AC-08: registry + merged map ----


def test_registry_seed_present(client):
    """AC-08 — core relabelable entities registered (catalog non-empty)."""
    h = _admin_headers(client)
    res = client.get("/terminology/catalog", headers=h)
    assert res.status_code == 200, res.text
    keys = {item["key"] for item in res.json()}
    assert {"form", "workflow", "template", "document", "connection", "role", "import"} <= keys
    # Deliberately excluded (D2 seed) — relabeling these confuses RBAC/admin.
    assert "user" not in keys and "tenant" not in keys and "permission" not in keys


def test_merged_map_defaults_then_overrides(client):
    """AC-08-04 — GET /terminology = defaults ⊕ tenant overrides."""
    h = _admin_headers(client)
    res = client.get("/terminology", headers=h)
    assert res.status_code == 200
    assert res.json()["form"] == {"singular": "Form", "plural": "Forms"}

    # Override and re-read.
    client.put("/terminology/form", json={"singular": "Survey", "plural": "Surveys"}, headers=h)
    res = client.get("/terminology", headers=h)
    assert res.json()["form"] == {"singular": "Survey", "plural": "Surveys"}
    # An untouched key still resolves to its default.
    assert res.json()["workflow"] == {"singular": "Workflow", "plural": "Workflows"}


# ---- AC-08-03 / -14: PUT upsert + validation ----


def test_put_upsert_and_returns_entry(client):
    h = _admin_headers(client)
    res = client.put(
        "/terminology/form", json={"singular": "Survey", "plural": "Surveys"}, headers=h
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"singular": "Survey", "plural": "Surveys"}
    # Catalog reflects the override + resolved labels.
    cat = {i["key"]: i for i in client.get("/terminology/catalog", headers=h).json()}
    assert cat["form"]["overrideSingular"] == "Survey"
    assert cat["form"]["singular"] == "Survey"
    assert cat["form"]["defaultSingular"] == "Form"


def test_put_unknown_key_422(client):
    h = _admin_headers(client)
    res = client.put(
        "/terminology/not_a_real_entity",
        json={"singular": "X", "plural": "Xs"},
        headers=h,
    )
    assert res.status_code == 422


def test_put_blank_rejected(client):
    h = _admin_headers(client)
    assert client.put(
        "/terminology/form", json={"singular": "  ", "plural": "Surveys"}, headers=h
    ).status_code == 422
    assert client.put(
        "/terminology/form", json={"singular": "Survey", "plural": ""}, headers=h
    ).status_code == 422


# ---- AC-08-02 / -14: DELETE reset → fallback ----


def test_delete_resets_to_default(client):
    h = _admin_headers(client)
    client.put("/terminology/form", json={"singular": "Survey", "plural": "Surveys"}, headers=h)
    assert client.delete("/terminology/form", headers=h).status_code == 204
    res = client.get("/terminology", headers=h)
    assert res.json()["form"] == {"singular": "Form", "plural": "Forms"}
    # Idempotent — deleting an absent override still 204s.
    assert client.delete("/terminology/form", headers=h).status_code == 204


# ---- AC-08-07: tenant isolation ----


def test_tenant_isolation(client):
    """AC-08-07 — tenant A's rename invisible to tenant B."""
    # Provision tenant B.
    ph = _headers(_login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform"))
    res = client.post(
        "/platform/tenants",
        json={
            "name": "Beta Co",
            "slug": "beta",
            "adminName": "B Admin",
            "adminEmail": "admin-beta@example.com",
            "adminPassword": "ChangeMe1!",
        },
        headers=ph,
    )
    assert res.status_code == 201, res.text

    # Tenant A (default) renames Form→Survey.
    ha = _admin_headers(client)
    client.put("/terminology/form", json={"singular": "Survey", "plural": "Surveys"}, headers=ha)

    # Tenant B unaffected.
    hb = _headers(_login(client, "admin-beta@example.com", "ChangeMe1!", "beta"))
    assert client.get("/terminology", headers=hb).json()["form"] == {
        "singular": "Form",
        "plural": "Forms",
    }


# ---- AC-08-06: perm gate ----


def test_get_terminology_authenticated_only_no_manage(client, session_factory):
    email, pw = _make_noperm_user(session_factory)
    h = _headers(_login(client, email, pw))
    # GET /terminology works for any authenticated user.
    assert client.get("/terminology", headers=h).status_code == 200
    # Catalog + writes require terminology.manage → 403.
    assert client.get("/terminology/catalog", headers=h).status_code == 403
    assert client.put(
        "/terminology/form", json={"singular": "S", "plural": "Ss"}, headers=h
    ).status_code == 403
    assert client.delete("/terminology/form", headers=h).status_code == 403


def test_admin_has_terminology_manage(client):
    """AC-08-17 — terminology.manage in the tenant Admin grant (CSV synced)."""
    h = _admin_headers(client)
    assert client.get("/terminology/catalog", headers=h).status_code == 200
