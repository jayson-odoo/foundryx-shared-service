"""App Store tests (plan 08) - catalog, per-tenant lifecycle, require_module
gating, Admin-grant model, per-tenant data wipe, operator endpoints."""
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


def _demo_headers(client):
    return _headers(_login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD))


def _platform_headers(client):
    return _headers(_login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform"))


def _provision(client, slug="acme", name="Acme Events"):
    """Provision a fresh tenant; returns (tenant_id, admin_headers)."""
    ph = _platform_headers(client)
    res = client.post(
        "/platform/tenants",
        json={
            "name": name,
            "slug": slug,
            "adminName": "Kay Meister",
            "adminEmail": f"admin-{slug}@example.com",
            "adminPassword": "ChangeMe1!",
        },
        headers=ph,
    )
    assert res.status_code == 201, res.text
    tenant_id = res.json()["id"]
    ah = _headers(_login(client, f"admin-{slug}@example.com", "ChangeMe1!", slug))
    return tenant_id, ah


def _module(client, headers, name="omnichannel"):
    res = client.get("/app-store/modules", headers=headers)
    assert res.status_code == 200, res.text
    return next(m for m in res.json() if m["name"] == name)


# ---- catalog ----


def test_catalog_lists_omnichannel_installed_for_default_tenant(client):
    h = _demo_headers(client)
    mod = _module(client, h)
    assert mod["status"] == "ACTIVE"
    assert mod["installedVersion"] == mod["version"]
    assert mod["updateAvailable"] is False
    assert mod["title"]  # manifest display fields synced
    assert mod["description"]


def test_installed_endpoint_lists_active_modules(client):
    h = _demo_headers(client)
    res = client.get("/app-store/installed", headers=h)
    assert res.status_code == 200
    rows = res.json()
    assert {"module": "omnichannel", "status": "ACTIVE", "version": rows[0]["version"]} in rows


def test_app_store_requires_permission(client):
    # No token → 401; the routes are perm-gated (app_store.read).
    assert client.get("/app-store/modules").status_code == 401


# ---- lifecycle: fresh tenant installs / deactivates / uninstalls ----


def test_fresh_tenant_starts_uninstalled_and_installs(client):
    tenant_id, ah = _provision(client, slug="acme")

    mod = _module(client, ah)
    assert mod["status"] is None  # not installed for the new tenant

    # Module routes 403 before install.
    res = client.get("/omnichannel/workspaces", headers=ah)
    assert res.status_code == 403
    assert "not installed" in res.json()["detail"].lower()

    # Install → ACTIVE at the current code version, default workspace seeded.
    res = client.post("/app-store/modules/omnichannel/install", headers=ah)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ACTIVE"

    res = client.get("/omnichannel/workspaces", headers=ah)
    assert res.status_code == 200
    names = [w["name"] for w in res.json()["data"]]
    assert "General" in names


def test_install_grants_module_keys_to_admin(client):
    tenant_id, ah = _provision(client, slug="borneo")

    me = _login(client, "admin-borneo@example.com", "ChangeMe1!", "borneo").json()["user"]
    assert "workspaces.read" not in me["permissions"]  # not installed yet
    assert "users.read" in me["permissions"]  # core keys present

    client.post("/app-store/modules/omnichannel/install", headers=ah)
    me = _login(client, "admin-borneo@example.com", "ChangeMe1!", "borneo").json()["user"]
    assert "workspaces.read" in me["permissions"]
    assert "conversations.reply" in me["permissions"]


def test_install_twice_conflicts(client):
    h = _demo_headers(client)
    res = client.post("/app-store/modules/omnichannel/install", headers=h)
    assert res.status_code == 409


def test_unknown_module_404(client):
    h = _demo_headers(client)
    res = client.post("/app-store/modules/nope/install", headers=h)
    assert res.status_code == 404


def test_deactivate_blocks_routes_keeps_data(client):
    h = _demo_headers(client)

    res = client.post("/app-store/modules/omnichannel/deactivate", headers=h)
    assert res.status_code == 200
    assert res.json()["status"] == "INACTIVE"

    # Routes 403 while inactive…
    assert client.get("/omnichannel/workspaces", headers=h).status_code == 403

    # …but reactivation restores everything (data kept, grants inert-not-removed).
    res = client.post("/app-store/modules/omnichannel/reactivate", headers=h)
    assert res.status_code == 200
    res = client.get("/omnichannel/workspaces", headers=h)
    assert res.status_code == 200
    assert any(w["name"] == "General" for w in res.json()["data"])


def test_deactivate_requires_active_state(client):
    h = _demo_headers(client)
    client.post("/app-store/modules/omnichannel/deactivate", headers=h)
    res = client.post("/app-store/modules/omnichannel/deactivate", headers=h)
    assert res.status_code == 409


def test_uninstall_needs_typed_confirmation(client):
    h = _demo_headers(client)
    res = client.post(
        "/app-store/modules/omnichannel/uninstall",
        headers=h,
        json={"confirmName": "omni"},
    )
    assert res.status_code == 422


def test_uninstall_wipes_only_that_tenant(client, session_factory):
    # Two tenants, both with omnichannel data; uninstall for one.
    tenant_id, ah = _provision(client, slug="citrus")
    client.post("/app-store/modules/omnichannel/install", headers=ah)

    dh = _demo_headers(client)
    assert client.get("/omnichannel/workspaces", headers=dh).status_code == 200
    assert client.get("/omnichannel/workspaces", headers=ah).status_code == 200

    res = client.post(
        "/app-store/modules/omnichannel/uninstall",
        headers=dh,
        json={"confirmName": "omnichannel"},
    )
    assert res.status_code == 200, res.text

    # Default tenant: gone - catalog shows not-installed, routes 403, perms revoked.
    assert _module(client, dh)["status"] is None
    assert client.get("/omnichannel/workspaces", headers=dh).status_code == 403
    me = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD).json()["user"]
    assert "workspaces.read" not in me["permissions"]

    # Other tenant untouched.
    res = client.get("/omnichannel/workspaces", headers=ah)
    assert res.status_code == 200
    assert any(w["name"] == "General" for w in res.json()["data"])

    # Tenant rows physically wiped (module schema kept for other tenants).
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.omnichannel.models import Workspace

    db = session_factory()
    try:
        assert (
            db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID).count() == 0
        )
        assert db.query(Workspace).filter(Workspace.tenant_id == tenant_id).count() > 0
    finally:
        db.close()


def test_reinstall_after_uninstall_reseeds(client):
    h = _demo_headers(client)
    client.post(
        "/app-store/modules/omnichannel/uninstall",
        headers=h,
        json={"confirmName": "omnichannel"},
    )
    res = client.post("/app-store/modules/omnichannel/install", headers=h)
    assert res.status_code == 200
    res = client.get("/omnichannel/workspaces", headers=h)
    assert res.status_code == 200
    assert any(w["name"] == "General" for w in res.json()["data"])


# ---- permission catalog narrows to installed modules (plan 08 §6) ----


def test_catalog_hides_uninstalled_module_permissions(client):
    tenant_id, ah = _provision(client, slug="delta")
    res = client.get("/permissions", headers=ah)
    assert res.status_code == 200
    resources = {r["resource"] for r in res.json()}
    assert "workspaces" not in resources  # omnichannel not installed
    assert "users" in resources

    client.post("/app-store/modules/omnichannel/install", headers=ah)
    res = client.get("/permissions", headers=ah)
    resources = {r["resource"] for r in res.json()}
    assert "workspaces" in resources


def test_uninstalled_module_keys_not_grantable(client):
    tenant_id, ah = _provision(client, slug="evergreen")
    res = client.post(
        "/roles",
        headers=ah,
        json={
            "name": "Support",
            "description": "Support crew",
            "permissionKeys": ["users.read", "workspaces.read"],
        },
    )
    assert res.status_code == 201, res.text
    keys = set(res.json()["permissionKeys"])
    assert "workspaces.read" not in keys  # uninstalled module key silently dropped
    assert "users.read" in keys


# ---- operator endpoints ----


def test_operator_manages_other_tenants_modules(client):
    tenant_id, ah = _provision(client, slug="festiva")
    ph = _platform_headers(client)

    res = client.get(f"/platform/tenants/{tenant_id}/modules", headers=ph)
    assert res.status_code == 200
    omni = next(m for m in res.json() if m["name"] == "omnichannel")
    assert omni["status"] is None

    res = client.post(
        f"/platform/tenants/{tenant_id}/modules/omnichannel/install", headers=ph
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ACTIVE"

    # The tenant's admin sees + uses it immediately.
    assert client.get("/omnichannel/workspaces", headers=ah).status_code == 200


def test_operator_endpoints_blocked_for_tenant_admin(client):
    tenant_id, ah = _provision(client, slug="gamma")
    res = client.get(f"/platform/tenants/{tenant_id}/modules", headers=ah)
    assert res.status_code == 403


def test_platform_tenant_never_installs(client):
    ph = _platform_headers(client)
    res = client.post("/app-store/modules/omnichannel/install", headers=ph)
    assert res.status_code == 409
