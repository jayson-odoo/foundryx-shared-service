"""User management endpoint tests — list/sort/search/filter/paginate + CRUD,
trash/restore, invite + set-password, roles, preferences, export.
"""
import json

from app.models import DEFAULT_TENANT_ID, InviteToken, Role
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _token(client) -> str:
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    return res.json()["access_token"]


def _auth(client) -> dict:
    return {"Authorization": f"Bearer {_token(client)}"}


# ---- list / sort / search / filter / paginate ----


def test_list_returns_active_users(client):
    res = client.get("/users", headers=_auth(client))
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2  # Demo User + Inactive User (seeded, not trashed)
    assert {"data", "total", "page"} <= body.keys()
    assert all("roles" in u for u in body["data"])


def test_list_sort_by_name_asc_then_desc(client):
    asc = client.get(
        "/users?sort_by=user&sort_dir=asc", headers=_auth(client)
    ).json()["data"]
    desc = client.get(
        "/users?sort_by=user&sort_dir=desc", headers=_auth(client)
    ).json()["data"]
    asc_names = [u["name"] for u in asc]
    desc_names = [u["name"] for u in desc]
    assert asc_names == ["Demo User", "Inactive User"]
    assert desc_names == ["Inactive User", "Demo User"]


def test_list_sort_by_status_and_joined(client):
    # Both sortable columns should return 200 and a stable order.
    for col in ("status", "joined", "lastSignIn", "email"):
        res = client.get(f"/users?sort_by={col}&sort_dir=asc", headers=_auth(client))
        assert res.status_code == 200, col


def test_search_matches_name_and_email(client):
    res = client.get("/users?search=inactive", headers=_auth(client))
    data = res.json()["data"]
    assert len(data) == 1
    assert data[0]["email"] == "inactive@example.com"


def test_filter_status_eq(client):
    flt = {
        "kind": "group",
        "combinator": "and",
        "rules": [
            {"kind": "condition", "field": "status", "operator": "eq", "value": "INACTIVE"}
        ],
    }
    res = client.get(
        f"/users?filter={json.dumps(flt)}", headers=_auth(client)
    )
    data = res.json()["data"]
    assert len(data) == 1
    assert data[0]["status"] == "INACTIVE"


def test_pagination(client):
    res = client.get("/users?page=0&page_size=1", headers=_auth(client))
    body = res.json()
    assert len(body["data"]) == 1
    assert body["total"] == 2


def test_invalid_filter_field_rejected(client):
    flt = {
        "kind": "group",
        "combinator": "and",
        "rules": [
            {"kind": "condition", "field": "password", "operator": "eq", "value": "x"}
        ],
    }
    res = client.get(f"/users?filter={json.dumps(flt)}", headers=_auth(client))
    assert res.status_code == 422


# ---- create (invite) / get / update ----


def test_create_user_is_invited_and_listed(client):
    res = client.post(
        "/users",
        headers=_auth(client),
        json={"name": "New Hire", "email": "new.hire@dreamz.io", "roleIds": [], "status": "ACTIVE"},
    )
    assert res.status_code == 201
    created = res.json()
    assert created["status"] == "INVITED"  # invite flow overrides requested status
    assert created["name"] == "New Hire"

    listed = client.get("/users?search=new.hire", headers=_auth(client)).json()["data"]
    assert any(u["email"] == "new.hire@dreamz.io" for u in listed)


def test_create_duplicate_email_conflicts(client):
    res = client.post(
        "/users",
        headers=_auth(client),
        json={"name": "Dup", "email": ACTIVE_EMAIL, "roleIds": [], "status": "ACTIVE"},
    )
    assert res.status_code == 409


def test_update_name_and_status(client):
    user = client.get("/users?search=inactive", headers=_auth(client)).json()["data"][0]
    res = client.patch(
        f"/users/{user['id']}",
        headers=_auth(client),
        json={"name": "Renamed", "status": "ACTIVE"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"
    assert res.json()["status"] == "ACTIVE"


def test_update_assigns_roles(client, session_factory):
    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Coordinator")
    db.add(role)
    db.commit()
    role_id = role.id
    db.close()

    user = client.get("/users?search=demo", headers=_auth(client)).json()["data"][0]
    res = client.patch(
        f"/users/{user['id']}", headers=_auth(client), json={"roleIds": [role_id]}
    )
    assert res.status_code == 200
    assert [r["name"] for r in res.json()["roles"]] == ["Coordinator"]


def test_invited_status_not_overwritten_by_update(client):
    created = client.post(
        "/users",
        headers=_auth(client),
        json={"name": "Pending", "email": "pending@dreamz.io", "roleIds": [], "status": "ACTIVE"},
    ).json()
    res = client.patch(
        f"/users/{created['id']}", headers=_auth(client), json={"status": "ACTIVE"}
    )
    # INVITED is system-managed — a profile save must not flip it.
    assert res.json()["status"] == "INVITED"


# ---- trash / restore ----


def test_trash_then_restore(client):
    user = client.get("/users?search=inactive", headers=_auth(client)).json()["data"][0]
    uid = user["id"]

    client.post("/users/trash", headers=_auth(client), json={"ids": [uid]})
    active = client.get("/users", headers=_auth(client)).json()
    assert all(u["id"] != uid for u in active["data"])
    trashed = client.get("/users?status_view=trashed", headers=_auth(client)).json()
    assert any(u["id"] == uid for u in trashed["data"])

    client.post("/users/restore", headers=_auth(client), json={"ids": [uid]})
    active2 = client.get("/users", headers=_auth(client)).json()
    assert any(u["id"] == uid for u in active2["data"])


# ---- record-nav neighbour ----


def test_user_at_index(client):
    first = client.get("/users/at?index=0&sort_by=user&sort_dir=asc", headers=_auth(client)).json()
    assert first["total"] == 2
    assert first["user"]["name"] == "Demo User"
    second = client.get("/users/at?index=1&sort_by=user&sort_dir=asc", headers=_auth(client)).json()
    assert second["user"]["name"] == "Inactive User"


# ---- invite + set-password ----


def test_set_password_activates_invited_user(client, session_factory):
    created = client.post(
        "/users",
        headers=_auth(client),
        json={"name": "Invitee", "email": "invitee@dreamz.io", "roleIds": [], "status": "ACTIVE"},
    ).json()

    db = session_factory()
    token_row = (
        db.query(InviteToken).filter(InviteToken.user_id == created["id"]).first()
    )
    token = token_row.token
    db.close()

    res = client.post(
        "/auth/set-password", json={"token": token, "password": "NewPass1!"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ACTIVE"

    # New password works for login.
    login = client.post(
        "/auth/login", json={"email": "invitee@dreamz.io", "password": "NewPass1!"}
    )
    assert login.status_code == 200


def test_set_password_invalid_token(client):
    res = client.post(
        "/auth/set-password", json={"token": "nope", "password": "Whatever1!"}
    )
    assert res.status_code == 400


# ---- roles / preferences / export ----


def test_roles_options_endpoint(client, session_factory):
    db = session_factory()
    db.add(Role(tenant_id=DEFAULT_TENANT_ID, name="Finance"))
    db.commit()
    db.close()
    res = client.get("/roles/options", headers=_auth(client))
    assert res.status_code == 200
    assert "Finance" in [r["name"] for r in res.json()]


def test_preferences_roundtrip(client):
    prefs = {"order": ["user", "status"], "widths": {"user": 280}, "hidden": ["email"]}
    saved = client.patch(
        "/me/preferences/users.list", headers=_auth(client), json=prefs
    )
    assert saved.status_code == 200
    got = client.get("/me/preferences/users.list", headers=_auth(client)).json()
    assert got["order"] == ["user", "status"]
    assert got["hidden"] == ["email"]


def test_export_csv(client):
    res = client.post(
        "/users/export",
        headers=_auth(client),
        json={"columns": ["user", "email", "status"]},
    )
    assert res.status_code == 200
    lines = res.text.strip().splitlines()
    assert lines[0] == "user,email,status"
    assert len(lines) == 3  # header + 2 users


# ---- auth contract ----


def test_login_returns_roles_array(client):
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    user = res.json()["user"]
    assert "roles" in user
    assert isinstance(user["roles"], list)
    assert "roleId" not in user
