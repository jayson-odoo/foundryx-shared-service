"""Role management + RBAC endpoint tests (plan 03).

Covers: list with counts, permission catalog, implied-read normalization on
create/update, system-role delete guard, user assign/remove, the permission
catalog sync idempotency, and require_permission gating (403/200).
"""
import json

from sqlalchemy.sql import func

from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from app.services.permission_service import PermissionService
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _make_active_user(session_factory, email, password, *, role_names=None):
    db = session_factory()
    from app.models import Role

    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=email,
        password=hash_password(password),
        name="Limited",
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    if role_names:
        roles = db.query(Role).filter(Role.name.in_(role_names)).all()
        user.roles = roles
    db.add(user)
    db.commit()
    db.close()


# ---- list / counts ----


def test_list_roles_returns_counts(client):
    res = client.get("/roles", headers=_auth(client))
    assert res.status_code == 200
    body = res.json()
    assert {"data", "total", "page"} <= body.keys()
    admin = next(r for r in body["data"] if r["name"] == "Admin")
    assert admin["isSystem"] is True
    # Admin holds the ENTIRE catalog (core + any installed modules).
    catalog = client.get("/permissions", headers=_auth(client)).json()
    total_perms = sum(len(r["actions"]) for r in catalog)
    assert admin["permissionCount"] == total_perms
    assert admin["userCount"] == 1  # demo user assigned in conftest


# ---- permission catalog ----


def test_permission_catalog_grouped_with_custom_actions(client):
    res = client.get("/permissions", headers=_auth(client))
    assert res.status_code == 200
    catalog = res.json()
    orders = next(r for r in catalog if r["resource"] == "orders")
    actions = {a["action"] for a in orders["actions"]}
    assert "approve" in actions  # custom action survives the catalog
    reports = next(r for r in catalog if r["resource"] == "reports")
    assert {a["action"] for a in reports["actions"]} == {"read", "export"}


# ---- create + implied-read ----


def test_create_role_normalizes_implied_read(client):
    res = client.post(
        "/roles",
        headers=_auth(client),
        json={"name": "Editors", "description": "x", "permissionKeys": ["events.create"]},
    )
    assert res.status_code == 201
    keys = set(res.json()["permissionKeys"])
    assert {"events.create", "events.read"} <= keys


def test_create_custom_action_implies_read(client):
    res = client.post(
        "/roles",
        headers=_auth(client),
        json={"name": "Approvers", "permissionKeys": ["orders.approve"]},
    )
    assert res.status_code == 201
    keys = set(res.json()["permissionKeys"])
    assert "orders.read" in keys and "orders.approve" in keys


def test_create_duplicate_name_conflicts(client):
    client.post("/roles", headers=_auth(client), json={"name": "Dupe", "permissionKeys": []})
    res = client.post("/roles", headers=_auth(client), json={"name": "Dupe", "permissionKeys": []})
    assert res.status_code == 409


# ---- update ----


def test_update_replaces_and_normalizes_grants(client):
    created = client.post(
        "/roles", headers=_auth(client), json={"name": "Tweak", "permissionKeys": ["users.read"]}
    ).json()
    res = client.patch(
        f"/roles/{created['id']}",
        headers=_auth(client),
        json={"permissionKeys": ["users.delete"]},
    )
    assert res.status_code == 200
    keys = set(res.json()["permissionKeys"])
    assert keys == {"users.delete", "users.read"}  # old users.read kept via implied-read; replaced set


def test_update_toggle_is_system(client):
    created = client.post(
        "/roles", headers=_auth(client), json={"name": "Toggle", "permissionKeys": []}
    ).json()
    assert created["isSystem"] is False
    res = client.patch(f"/roles/{created['id']}", headers=_auth(client), json={"isSystem": True})
    assert res.json()["isSystem"] is True


# ---- delete + system guard ----


def test_delete_system_role_blocked(client):
    admin = next(
        r for r in client.get("/roles", headers=_auth(client)).json()["data"] if r["name"] == "Admin"
    )
    res = client.delete(f"/roles/{admin['id']}", headers=_auth(client))
    assert res.status_code == 409


def test_delete_custom_role_ok(client):
    created = client.post(
        "/roles", headers=_auth(client), json={"name": "Temp", "permissionKeys": []}
    ).json()
    res = client.delete(f"/roles/{created['id']}", headers=_auth(client))
    assert res.status_code == 204
    assert client.get(f"/roles/{created['id']}", headers=_auth(client)).status_code == 404


# ---- assign / remove users ----


def test_assign_and_remove_users(client, session_factory):
    _make_active_user(session_factory, "assignee@dreamz.io", "pw12345678")
    role = client.post(
        "/roles", headers=_auth(client), json={"name": "Squad", "permissionKeys": ["events.read"]}
    ).json()

    # assignable contains the new user
    assignable = client.get(f"/roles/{role['id']}/assignable", headers=_auth(client)).json()
    target = next(u for u in assignable if u["email"] == "assignee@dreamz.io")

    client.post(
        f"/roles/{role['id']}/users", headers=_auth(client), json={"userIds": [target["id"]]}
    )
    assigned = client.get(f"/roles/{role['id']}/users", headers=_auth(client)).json()
    assert any(u["email"] == "assignee@dreamz.io" for u in assigned)
    assert assigned[0]["assignedAt"] is not None

    # role list count reflects the assignment
    listed = client.get("/roles?search=Squad", headers=_auth(client)).json()["data"][0]
    assert listed["userCount"] == 1

    client.request(
        "DELETE", f"/roles/{role['id']}/users/{target['id']}", headers=_auth(client)
    )
    assigned2 = client.get(f"/roles/{role['id']}/users", headers=_auth(client)).json()
    assert not any(u["email"] == "assignee@dreamz.io" for u in assigned2)


# ---- search ----


def test_filter_roles_by_system_flag_and_rejects_unknown_field(client):
    # A custom (non-system) role to distinguish from the seeded system roles.
    client.post("/roles", headers=_auth(client), json={"name": "CustomX", "permissionKeys": []})

    flt = {
        "kind": "group",
        "combinator": "and",
        "rules": [{"kind": "condition", "field": "system", "operator": "is_false", "value": None}],
    }
    res = client.get(f"/roles?filter={json.dumps(flt)}", headers=_auth(client))
    assert res.status_code == 200
    names = [r["name"] for r in res.json()["data"]]
    assert "CustomX" in names
    assert "Admin" not in names  # Admin is a system role

    # Non-whitelisted field is rejected (can't reach arbitrary columns).
    bad = {
        "kind": "group",
        "combinator": "and",
        "rules": [{"kind": "condition", "field": "tenant_id", "operator": "eq", "value": "x"}],
    }
    assert client.get(f"/roles?filter={json.dumps(bad)}", headers=_auth(client)).status_code == 422


def test_search_by_permission_and_user(client):
    # Admin holds orders.approve and has the demo user → both should match.
    by_perm = client.get("/roles?search=orders.approve", headers=_auth(client)).json()["data"]
    assert any(r["name"] == "Admin" for r in by_perm)
    by_user = client.get("/roles?search=Demo", headers=_auth(client)).json()["data"]
    assert any(r["name"] == "Admin" for r in by_user)


# ---- record-nav ----


def test_role_at_index(client):
    res = client.get("/roles/at?index=0&sort_by=name&sort_dir=asc", headers=_auth(client)).json()
    assert res["total"] >= 1
    assert res["role"] is not None
    assert "permissionKeys" in res["role"]


# ---- require_permission gating ----


def test_no_permission_user_gets_403(client, session_factory):
    _make_active_user(session_factory, "noperm@dreamz.io", "pw12345678")
    headers = _auth(client, email="noperm@dreamz.io", password="pw12345678")
    assert client.get("/users", headers=headers).status_code == 403
    assert client.get("/roles", headers=headers).status_code == 403
    assert client.get("/permissions", headers=headers).status_code == 403


def test_admin_passes_gates(client):
    assert client.get("/users", headers=_auth(client)).status_code == 200
    assert client.get("/roles", headers=_auth(client)).status_code == 200


def test_login_response_includes_permissions(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    perms = res.json()["user"]["permissions"]
    assert isinstance(perms, list)
    assert "users.create" in perms and "roles.delete" in perms  # admin holds all


# ---- catalog sync idempotency ----


def test_sync_core_is_idempotent(session_factory):
    from app.services.permission_service import CORE_CSV, CORE_MODULE, load_csv

    db = session_factory()
    before = len(PermissionRepository(db).all_keys())
    PermissionService(db).sync_core()
    after = len(PermissionRepository(db).all_keys())
    core_rows = [p for p in PermissionRepository(db).list_all() if p.module == CORE_MODULE]
    assert before == after  # idempotent — sync_core adds/removes nothing on re-run
    assert len(core_rows) == len(load_csv(CORE_CSV))  # core catalog matches its CSV
    db.close()
