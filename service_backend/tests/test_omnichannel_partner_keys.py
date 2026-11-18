"""S6 - partner API key (tenant-scoped `fxp_live_`), dashboard issuance and
`GET /api/v1/omnichannel/partner/me`.

Behaviour: a tenant admin holding `partner_keys.manage` mints (full key shown
once), lists, revokes and edits a key's return origins; the key resolves to
exactly one tenant; a workspace key is refused on partner routes and a partner
key is refused on the workspace-key routes, which behave exactly as before;
revoked key 401; per-key limits; suspended tenant or inactive module 403;
one-shot Admin grant sweep; migration chain. Fake values only.
"""
import ast
from pathlib import Path

import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.test_omnichannel_api_gateway import _default_workspace_id, _mint, _seed_channel
from tests.test_omnichannel_contact_erase_staff import _admin_has, _drop_key_everywhere, _run_install
from tests.test_omnichannel_contacts_module import _no_perm_auth

BASE = "/omnichannel/partner-keys"
ME = "/api/v1/omnichannel/partner/me"
VERSIONS = Path(__file__).resolve().parents[1] / "modules" / "omnichannel" / "alembic" / "versions"


# ── helpers ──────────────────────────────────────────────────────────────────
def _auth(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> dict:
    body = {"email": email, "password": password}
    if tenant_slug:
        body["tenantSlug"] = tenant_slug
    token = client.post("/auth/login", json=body).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def other_tenant(client, session_factory, slug="partner-other"):
    """A second tenant with omnichannel installed: (tenant_id, admin headers)."""
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name=f"Tenant {slug}", slug=slug, admin_email=f"admin-{slug}@example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    AppStoreService(db).install(tenant.id, "omnichannel")
    db.commit()
    tid = tenant.id
    db.close()
    return tid, _auth(client, email=f"admin-{slug}@example.com", password="Password123!", tenant_slug=slug)


def mint_partner(client, headers=None, name="EcoHub", origins=None):
    body = {"name": name}
    if origins is not None:
        body["allowedReturnOrigins"] = origins
    return client.post(BASE, json=body, headers=headers or _auth(client))


def partner_headers(client, headers=None, name="EcoHub") -> dict:
    res = mint_partner(client, headers, name)
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['fullKey']}"}


# ── issuance ─────────────────────────────────────────────────────────────────
def test_mint_shows_the_full_key_once_and_stores_only_a_hash(client, session_factory):
    res = mint_partner(client, origins=["https://app.ecohub.example", "https://app.ecohub.example:443"])
    assert res.status_code == 201, res.text
    body = res.json()
    full = body["fullKey"]
    assert full.startswith("fxp_live_")
    assert body["key"]["status"] == "ACTIVE"
    assert body["key"]["maskedKey"].startswith("fxp_live_") and "••••" in body["key"]["maskedKey"]
    assert body["key"]["allowedReturnOrigins"] == ["https://app.ecohub.example"]

    listed = client.get(BASE, headers=_auth(client))
    assert listed.status_code == 200
    items = listed.json()["data"]
    assert [i["id"] for i in items] == [body["key"]["id"]]
    assert "fullKey" not in items[0] and full not in listed.text

    from modules.omnichannel.models import PartnerApiKey

    db = session_factory()
    row = db.query(PartnerApiKey).one()
    assert row.tenant_id == DEFAULT_TENANT_ID
    assert len(row.key_hash) == 64 and row.key_hash != full and full not in row.key_hash
    assert len(row.key_prefix) == 8
    assert row.created_by
    db.close()


def test_me_returns_the_key_tenant_and_name(client, session_factory):
    hdr = partner_headers(client, name="EcoHub partner")
    res = client.get(ME, headers=hdr)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tenantId"] == DEFAULT_TENANT_ID
    assert body["tenantName"]
    assert body["keyName"] == "EcoHub partner"
    assert body["keyId"]


def test_each_tenant_key_resolves_to_its_own_tenant_and_lists_are_scoped(client, session_factory):
    tid_b, admin_b = other_tenant(client, session_factory)
    hdr_a = partner_headers(client, name="A")
    hdr_b = partner_headers(client, admin_b, name="B")
    assert client.get(ME, headers=hdr_a).json()["tenantId"] == DEFAULT_TENANT_ID
    assert client.get(ME, headers=hdr_b).json()["tenantId"] == tid_b
    names_a = [k["name"] for k in client.get(BASE, headers=_auth(client)).json()["data"]]
    names_b = [k["name"] for k in client.get(BASE, headers=admin_b).json()["data"]]
    assert names_a == ["A"] and names_b == ["B"]


# ── credential separation ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "hdr", [None, "Bearer nope", "Bearer fxp_live_deadbeef", "Bearer fxp_live_", "garbage", "Basic abc"]
)
def test_invalid_partner_credentials_get_a_uniform_401(client, hdr):
    headers = {"Authorization": hdr} if hdr else {}
    res = client.get(ME, headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_api_key"


def test_a_workspace_key_is_refused_on_partner_routes(client, session_factory):
    ws = _default_workspace_id(session_factory)
    workspace_key = _mint(client, ws).json()["fullKey"]
    res = client.get(ME, headers={"Authorization": f"Bearer {workspace_key}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_api_key"


def test_a_partner_key_is_refused_on_workspace_routes_which_behave_as_before(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-partner-sep")
    workspace_hdr = {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}
    partner_hdr = partner_headers(client)
    for path in ("/api/v1/omnichannel/channels", "/api/v1/omnichannel/templates", "/api/v1/omnichannel/contacts"):
        before = client.get(path, headers=workspace_hdr)
        assert before.status_code == 200, before.text
        refused = client.get(path, headers=partner_hdr)
        assert refused.status_code == 401, refused.text
        assert refused.json() == {"error": {"code": "invalid_api_key", "message": "Invalid API key."}}
        after = client.get(path, headers=workspace_hdr)
        assert after.status_code == 200 and after.json() == before.json()


# ── revoke, limits, tenant and module state ──────────────────────────────────
def test_a_revoked_key_gets_401_and_revoke_is_idempotent(client, session_factory):
    res = mint_partner(client)
    key_id, full = res.json()["key"]["id"], res.json()["fullKey"]
    hdr = {"Authorization": f"Bearer {full}"}
    assert client.get(ME, headers=hdr).status_code == 200
    rev = client.post(f"{BASE}/{key_id}/revoke", headers=_auth(client))
    assert rev.status_code == 200 and rev.json()["status"] == "REVOKED"
    first_revoked_at = rev.json()["revokedAt"]
    again = client.post(f"{BASE}/{key_id}/revoke", headers=_auth(client))
    assert again.status_code == 200 and again.json()["revokedAt"] == first_revoked_at
    refused = client.get(ME, headers=hdr)
    assert refused.status_code == 401 and refused.json()["error"]["code"] == "invalid_api_key"


def test_per_key_rate_limit_applies_to_partner_keys(client, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 2)
    hdr = partner_headers(client)
    assert client.get(ME, headers=hdr).status_code == 200
    assert client.get(ME, headers=hdr).status_code == 200
    third = client.get(ME, headers=hdr)
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limited"
    assert int(third.headers["Retry-After"]) >= 1
    # a second key has its own budget
    assert client.get(ME, headers=partner_headers(client, name="other")).status_code == 200


def test_suspended_tenant_gets_403_and_reactivation_restores(client, session_factory):
    from app.services.tenant_service import TenantService

    hdr = partner_headers(client)
    db = session_factory()
    TenantService(db).suspend(DEFAULT_TENANT_ID)
    db.close()
    res = client.get(ME, headers=hdr)
    assert res.status_code == 403 and res.json()["error"]["code"] == "service_not_enabled"
    db = session_factory()
    TenantService(db).reactivate(DEFAULT_TENANT_ID)
    db.close()
    assert client.get(ME, headers=hdr).status_code == 200


def test_inactive_module_gets_403(client, session_factory):
    from app.services.app_store_service import AppStoreService

    hdr = partner_headers(client)
    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.close()
    res = client.get(ME, headers=hdr)
    assert res.status_code == 403 and res.json()["error"]["code"] == "service_not_enabled"


# ── permission and dashboard routes ──────────────────────────────────────────
def test_every_dashboard_route_needs_the_permission(client, session_factory):
    key_id = mint_partner(client).json()["key"]["id"]
    noperm = _no_perm_auth(client, session_factory, email="partner-noperm@example.com")
    assert client.get(BASE, headers=noperm).status_code == 403
    assert client.post(BASE, json={"name": "x"}, headers=noperm).status_code == 403
    assert client.patch(f"{BASE}/{key_id}", json={"allowedReturnOrigins": []}, headers=noperm).status_code == 403
    assert client.post(f"{BASE}/{key_id}/revoke", headers=noperm).status_code == 403
    # api_keys.manage alone is not enough
    from app.security import hash_password
    from app.models import Role, User, UserStatus
    from app.repositories.permission_repository import PermissionRepository

    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Workspace keys only")
    role.permissions = PermissionRepository(db).get_by_keys(["api_keys.manage", "api_keys.read"])
    user = User(tenant_id=DEFAULT_TENANT_ID, email="keys-only@example.com", name="Keys",
                password=hash_password("Password123!"), status=UserStatus.ACTIVE.value)
    user.roles = [role]
    db.add_all([role, user])
    db.commit()
    db.close()
    keys_only = _auth(client, email="keys-only@example.com", password="Password123!")
    assert client.post(BASE, json={"name": "x"}, headers=keys_only).status_code == 403


def test_return_origins_are_validated_replaced_and_cleared(client):
    key_id = mint_partner(client).json()["key"]["id"]
    ok = client.patch(
        f"{BASE}/{key_id}",
        json={"allowedReturnOrigins": ["https://a.example", "http://localhost:3000", "https://a.example"]},
        headers=_auth(client),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["allowedReturnOrigins"] == ["https://a.example", "http://localhost:3000"]
    for bad in (["https://a.example/path"], ["http://a.example"], ["https://*.a.example"], ["ftp://a.example"]):
        res = client.patch(f"{BASE}/{key_id}", json={"allowedReturnOrigins": bad}, headers=_auth(client))
        assert res.status_code == 422, bad
    kept = client.get(BASE, headers=_auth(client)).json()["data"][0]["allowedReturnOrigins"]
    assert kept == ["https://a.example", "http://localhost:3000"]
    cleared = client.patch(f"{BASE}/{key_id}", json={"allowedReturnOrigins": []}, headers=_auth(client))
    assert cleared.status_code == 200 and cleared.json()["allowedReturnOrigins"] == []
    assert mint_partner(client, origins=["https://x.example/"]).status_code == 422


def test_another_tenants_key_id_is_404_on_dashboard_routes(client, session_factory):
    _, admin_b = other_tenant(client, session_factory, slug="partner-other-404")
    key_b = mint_partner(client, admin_b).json()["key"]["id"]
    assert client.post(f"{BASE}/{key_b}/revoke", headers=_auth(client)).status_code == 404
    assert client.patch(f"{BASE}/{key_b}", json={"allowedReturnOrigins": []}, headers=_auth(client)).status_code == 404
    assert client.get(BASE, headers=admin_b).json()["data"][0]["status"] == "ACTIVE"


# ── grant sweep ──────────────────────────────────────────────────────────────
def test_sweep_grants_the_key_to_admin_once_when_first_created(session_factory, monkeypatch):
    from sqlalchemy import select

    from app.models import Role
    from app.models.permission import Permission, role_permissions

    _drop_key_everywhere(session_factory, "partner_keys.manage")
    assert _admin_has(session_factory, "partner_keys.manage") is None
    _run_install(session_factory, monkeypatch)
    assert _admin_has(session_factory, "partner_keys.manage") is True
    db = session_factory()
    try:
        perm_id = db.query(Permission).filter(Permission.key == "partner_keys.manage").one().id
        admin = db.query(Role).filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin",
                                      Role.is_system.is_(True)).one()
        db.execute(role_permissions.delete().where(role_permissions.c.role_id == admin.id,
                                                   role_permissions.c.permission_id == perm_id))
        db.commit()
        holders = db.execute(select(role_permissions.c.role_id).where(
            role_permissions.c.permission_id == perm_id)).all()
        assert holders == []
    finally:
        db.close()
    _run_install(session_factory, monkeypatch)
    assert _admin_has(session_factory, "partner_keys.manage") is False  # removal respected


# ── migration chain ──────────────────────────────────────────────────────────
def _assigns(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                out[target.id] = node.value.value
    return out


def test_partner_key_migration_revises_the_previous_head():
    meta = _assigns(VERSIONS / "0028_omni_partner_api_keys.py")
    assert meta["revision"] == "0028_omni_partner_api_keys"
    assert meta["down_revision"] == "0027_omni_payload_version"
    assert len(meta["revision"]) <= 32
