"""Platform Console tenant tests (plan 07) - operator RBAC, provisioning,
lifecycle enforcement, slug rules, BL-015 association tenant_id."""
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


def _platform_headers(client):
    res = _login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform")
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _demo_headers(client):
    res = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _provision(client, headers, slug="acme", name="Acme Events", **overrides):
    payload = {
        "name": name,
        "slug": slug,
        "contactName": "Kay Meister",
        "contactEmail": "kay@acme-events.com",
        "adminName": "Kay Meister",
        "adminEmail": "kay@acme-events.com",
        "adminPassword": "ChangeMe1!",
    }
    payload.update(overrides)
    return client.post("/platform/tenants", json=payload, headers=headers)


# ---- operator login + RBAC boundary ----


def test_platform_admin_logs_in_at_platform_slug(client):
    res = _login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform")
    assert res.status_code == 200
    user = res.json()["user"]
    assert user["isPlatformTenant"] is True
    assert "tenants.read" in user["permissions"]


def test_platform_admin_lists_tenants(client):
    headers = _platform_headers(client)
    res = client.get("/platform/tenants", headers=headers)
    assert res.status_code == 200
    body = res.json()
    slugs = {t["slug"] for t in body["data"]}
    assert {"default", "platform"} <= slugs
    platform_row = next(t for t in body["data"] if t["slug"] == "platform")
    assert platform_row["isPlatform"] is True
    assert platform_row["status"] == "ACTIVE"


def test_tenant_admin_blocked_from_platform_endpoints(client):
    headers = _demo_headers(client)
    res = client.get("/platform/tenants", headers=headers)
    assert res.status_code == 403  # missing tenants.read (platform module key)


def test_login_to_unknown_slug_is_uniform_401(client):
    res = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD, "nope-nope")
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password."


def test_default_tenant_user_cannot_login_via_platform_slug(client):
    res = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD, "platform")
    assert res.status_code == 401  # demo user doesn't exist in the platform tenant


def test_permission_catalog_hides_platform_module_for_tenant_admin(client):
    demo = _demo_headers(client)
    catalog = client.get("/permissions", headers=demo).json()
    assert all(r["module"] != "platform" for r in catalog)

    operator = _platform_headers(client)
    catalog = client.get("/permissions", headers=operator).json()
    assert any(r["module"] == "platform" for r in catalog)


# ---- provisioning (plan 07 §7) ----


def test_provision_creates_tenant_roles_and_admin(client):
    headers = _platform_headers(client)
    res = _provision(client, headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["slug"] == "acme"
    assert body["status"] == "ACTIVE"
    assert body["userCount"] == 1

    # The new admin can sign in at the tenant's slug…
    res = _login(client, "kay@acme-events.com", "ChangeMe1!", "acme")
    assert res.status_code == 200
    user = res.json()["user"]
    assert user["isPlatformTenant"] is False
    assert {r["name"] for r in user["roles"]} == {"Admin"}
    # …holding the tenant-admin grant (core keys, no platform keys).
    assert "users.read" in user["permissions"]
    assert not any(k.startswith("tenants.") for k in user["permissions"])


def test_provision_rejects_invalid_reserved_and_taken_slugs(client):
    headers = _platform_headers(client)
    assert _provision(client, headers, slug="Bad Slug").status_code == 422
    assert _provision(client, headers, slug="ab").status_code == 422
    assert _provision(client, headers, slug="platform").status_code == 422
    assert _provision(client, headers, slug="www").status_code == 422

    assert _provision(client, headers, slug="taken-slug").status_code == 201
    assert _provision(client, headers, slug="taken-slug").status_code == 409


# ---- lifecycle (plan 07 §4) ----


def test_suspend_blocks_login_and_live_sessions(client):
    operator = _platform_headers(client)
    tenant_id = _provision(client, operator, slug="suspendee").json()["id"]

    user_login = _login(client, "kay@acme-events.com", "ChangeMe1!", "suspendee")
    assert user_login.status_code == 200
    user_headers = {"Authorization": f"Bearer {user_login.json()['access_token']}"}
    assert client.get("/auth/me", headers=user_headers).status_code == 200

    res = client.post(f"/platform/tenants/{tenant_id}/suspend", headers=operator)
    assert res.status_code == 200
    assert res.json()["status"] == "SUSPENDED"

    # Login blocked with a clear message…
    res = _login(client, "kay@acme-events.com", "ChangeMe1!", "suspendee")
    assert res.status_code == 403
    assert "suspended" in res.json()["detail"].lower()
    # …and the live session dies on its next request.
    assert client.get("/auth/me", headers=user_headers).status_code == 403

    # Reactivate restores access.
    res = client.post(f"/platform/tenants/{tenant_id}/reactivate", headers=operator)
    assert res.status_code == 200
    assert _login(client, "kay@acme-events.com", "ChangeMe1!", "suspendee").status_code == 200
    assert client.get("/auth/me", headers=user_headers).status_code == 200


def test_archive_moves_tenant_to_trashed_view(client):
    operator = _platform_headers(client)
    tenant_id = _provision(client, operator, slug="archivee", name="Archivee").json()["id"]

    res = client.post(f"/platform/tenants/{tenant_id}/archive", headers=operator)
    assert res.status_code == 200
    assert res.json()["status"] == "ARCHIVED"

    default_view = client.get("/platform/tenants", headers=operator).json()
    assert all(t["id"] != tenant_id for t in default_view["data"])

    trashed_view = client.get(
        "/platform/tenants", params={"status_view": "trashed"}, headers=operator
    ).json()
    assert any(t["id"] == tenant_id for t in trashed_view["data"])


def test_platform_tenant_lifecycle_protected(client):
    operator = _platform_headers(client)
    tenants = client.get("/platform/tenants", headers=operator).json()["data"]
    platform_id = next(t["id"] for t in tenants if t["isPlatform"])

    assert client.post(f"/platform/tenants/{platform_id}/suspend", headers=operator).status_code == 409
    assert client.post(f"/platform/tenants/{platform_id}/archive", headers=operator).status_code == 409


def test_invalid_transitions_conflict(client):
    operator = _platform_headers(client)
    tenant_id = _provision(client, operator, slug="transitions").json()["id"]

    # Reactivating an active tenant is a no-op conflict.
    assert client.post(f"/platform/tenants/{tenant_id}/reactivate", headers=operator).status_code == 409
    # Suspending twice conflicts.
    assert client.post(f"/platform/tenants/{tenant_id}/suspend", headers=operator).status_code == 200
    assert client.post(f"/platform/tenants/{tenant_id}/suspend", headers=operator).status_code == 409


# ---- update + export ----


def test_update_patches_editable_fields(client):
    operator = _platform_headers(client)
    tenant_id = _provision(client, operator, slug="editable").json()["id"]

    res = client.patch(
        f"/platform/tenants/{tenant_id}",
        json={"name": "Renamed Co", "contactEmail": "new@editable-co.com", "notes": "VIP"},
        headers=operator,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Renamed Co"
    assert body["contactEmail"] == "new@editable-co.com"
    assert body["notes"] == "VIP"
    assert body["slug"] == "editable"  # immutable


def test_duplicate_custom_domain_conflicts(client):
    operator = _platform_headers(client)
    a = _provision(client, operator, slug="domain-a").json()["id"]
    b = _provision(client, operator, slug="domain-b").json()["id"]

    res = client.patch(
        f"/platform/tenants/{a}", json={"customDomain": "events.acme.com"}, headers=operator
    )
    assert res.status_code == 200

    res = client.patch(
        f"/platform/tenants/{b}", json={"customDomain": "events.acme.com"}, headers=operator
    )
    assert res.status_code == 409
    assert "domain" in res.json()["detail"].lower()


def test_export_csv(client):
    operator = _platform_headers(client)
    res = client.post(
        "/platform/tenants/export",
        json={"columns": ["tenant", "slug", "status"]},
        headers=operator,
    )
    assert res.status_code == 200
    lines = res.text.strip().splitlines()
    assert lines[0] == "tenant,slug,status"
    assert any("default" in line for line in lines[1:])


# ---- BL-015: association tenant_id ----


def test_association_tenant_id_follows_the_role(client, session_factory):
    operator = _platform_headers(client)
    _provision(client, operator, slug="assoc-check")

    db = session_factory()
    try:
        from sqlalchemy import text

        tenant_id = db.execute(
            text("SELECT id FROM tenants WHERE slug = 'assoc-check'")
        ).scalar()
        # The provisioned admin's user_roles row carries the NEW tenant, not the default.
        rows = db.execute(
            text(
                "SELECT ur.tenant_id FROM user_roles ur "
                "JOIN users u ON u.id = ur.user_id WHERE u.tenant_id = :tid"
            ),
            {"tid": tenant_id},
        ).fetchall()
        assert rows, "expected the provisioned admin to hold a role"
        assert all(r[0] == tenant_id for r in rows)

        # role_permissions for the new tenant's Admin grant carry the new tenant too.
        rp = db.execute(
            text(
                "SELECT rp.tenant_id FROM role_permissions rp "
                "JOIN roles r ON r.id = rp.role_id WHERE r.tenant_id = :tid"
            ),
            {"tid": tenant_id},
        ).fetchall()
        assert rp, "expected the new Admin role to carry grants"
        assert all(r[0] == tenant_id for r in rp)
    finally:
        db.close()


# ---- hard delete / purge (BL-035, sprint-2/02) ----


def test_purge_requires_archived_and_typed_slug(client):
    operator = _platform_headers(client)
    tenant_id = _provision(client, operator, slug="purgee", name="Purgee").json()["id"]

    # Active tenant: refused (two-step safety - archive first).
    res = client.post(
        f"/platform/tenants/{tenant_id}/purge",
        json={"confirmSlug": "purgee"},
        headers=operator,
    )
    assert res.status_code == 409
    assert "archive" in res.json()["detail"].lower()

    assert client.post(f"/platform/tenants/{tenant_id}/archive", headers=operator).status_code == 200

    # Wrong typed confirmation: 422.
    res = client.post(
        f"/platform/tenants/{tenant_id}/purge",
        json={"confirmSlug": "wrong"},
        headers=operator,
    )
    assert res.status_code == 422

    # Correct: gone for good - list (both views) no longer knows it.
    res = client.post(
        f"/platform/tenants/{tenant_id}/purge",
        json={"confirmSlug": "purgee"},
        headers=operator,
    )
    assert res.status_code == 204
    assert client.get(f"/platform/tenants/{tenant_id}", headers=operator).status_code == 404
    res = client.get(
        "/platform/tenants", params={"status_view": "trashed"}, headers=operator
    )
    assert all(r["id"] != tenant_id for r in res.json()["data"])


def test_purge_cascades_tenant_rows(client, session_factory):
    operator = _platform_headers(client)
    tenant_id = _provision(client, operator, slug="purge-deep", name="Purge Deep").json()["id"]
    client.post(f"/platform/tenants/{tenant_id}/archive", headers=operator)
    res = client.post(
        f"/platform/tenants/{tenant_id}/purge",
        json={"confirmSlug": "purge-deep"},
        headers=operator,
    )
    assert res.status_code == 204, res.text

    from sqlalchemy import text

    db = session_factory()
    try:
        for table in ("users", "roles", "tenant_modules"):
            count = db.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
                {"t": tenant_id},
            ).scalar()
            assert count == 0, table
    finally:
        db.close()


def test_purge_platform_tenant_refused_and_permission_gated(client, session_factory):
    operator = _platform_headers(client)
    res = client.get("/platform/tenants", headers=operator)
    platform_id = next(r["id"] for r in res.json()["data"] if r["isPlatform"])
    res = client.post(
        f"/platform/tenants/{platform_id}/purge",
        json={"confirmSlug": "platform"},
        headers=operator,
    )
    assert res.status_code == 409

    # Tenant admin (no platform membership) is locked out.
    demo = _demo_headers(client)
    res = client.post(
        f"/platform/tenants/{platform_id}/purge",
        json={"confirmSlug": "platform"},
        headers=demo,
    )
    assert res.status_code == 403
