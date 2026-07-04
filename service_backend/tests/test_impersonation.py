"""Impersonation tests (plan 03 §13).

Verifies the permission gate on /start, the validity rules, and the core security
property: the X-Impersonate-User-Id header swaps the *effective* user (so the
target's permissions apply) only while an active session exists.
"""
from sqlalchemy.sql import func

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    return client.post(
        "/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _make_user(session_factory, email, password, *, perm_keys=None) -> str:
    db = session_factory()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=email,
        password=hash_password(password),
        name=email.split("@")[0].title(),
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    if perm_keys is not None:
        role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"role-{email}")
        role.permissions = PermissionRepository(db).get_by_keys(perm_keys)
        db.add(role)
        db.flush()
        user.roles = [role]
    db.add(user)
    db.commit()
    uid = user.id
    db.close()
    return uid


# ---- permission gate ----


def test_start_requires_impersonate_permission(client, session_factory):
    # A user with only roles.read cannot impersonate.
    _make_user(session_factory, "limited@foundryx.io", "pw12345678", perm_keys=["roles.read"])
    target = _make_user(session_factory, "target@foundryx.io", "pw12345678", perm_keys=["roles.read"])
    headers = _auth(client, email="limited@foundryx.io", password="pw12345678")
    res = client.post("/impersonation/start", headers=headers, json={"targetUserId": target})
    assert res.status_code == 403


def test_admin_can_start_and_get_current(client, session_factory):
    target = _make_user(session_factory, "t1@foundryx.io", "pw12345678", perm_keys=["roles.read"])
    res = client.post("/impersonation/start", headers=_auth(client), json={"targetUserId": target})
    assert res.status_code == 200
    body = res.json()
    assert body["targetUser"]["email"] == "t1@foundryx.io"
    assert "roles.read" in body["permissions"]
    assert "users.read" not in body["permissions"]  # target's keys, not the admin's

    cur = client.get("/impersonation/current", headers=_auth(client)).json()
    assert cur["targetUser"]["id"] == target


def test_cannot_impersonate_self(client):
    me = client.get("/auth/me", headers=_auth(client)).json()
    res = client.post(
        "/impersonation/start", headers=_auth(client), json={"targetUserId": me["id"]}
    )
    assert res.status_code == 400


def test_cannot_impersonate_another_impersonator(client, session_factory):
    other = _make_user(
        session_factory, "admin2@foundryx.io", "pw12345678", perm_keys=["users.impersonate"]
    )
    res = client.post("/impersonation/start", headers=_auth(client), json={"targetUserId": other})
    assert res.status_code == 400


def test_cannot_impersonate_more_privileged_user(client, session_factory):
    # A limited impersonator cannot escalate by impersonating a higher-priv user.
    _make_user(
        session_factory,
        "support@foundryx.io",
        "pw12345678",
        perm_keys=["users.impersonate", "users.read"],
    )
    target = _make_user(
        session_factory,
        "privileged@foundryx.io",
        "pw12345678",
        perm_keys=["roles.read", "roles.delete"],
    )
    headers = _auth(client, email="support@foundryx.io", password="pw12345678")
    res = client.post("/impersonation/start", headers=headers, json={"targetUserId": target})
    assert res.status_code == 403


def test_cannot_impersonate_inactive(client, session_factory):
    db = session_factory()
    u = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="dormant@foundryx.io",
        password=hash_password("pw12345678"),
        name="Dormant",
        status=UserStatus.INACTIVE.value,
    )
    db.add(u)
    db.commit()
    uid = u.id
    db.close()
    res = client.post("/impersonation/start", headers=_auth(client), json={"targetUserId": uid})
    assert res.status_code == 400


# ---- effective-user swap (the security property) ----


def test_header_swaps_effective_user_only_with_active_session(client, session_factory):
    # Target can read roles but NOT users.
    target = _make_user(session_factory, "t2@foundryx.io", "pw12345678", perm_keys=["roles.read"])

    # Header WITHOUT an active session → ignored → admin stays admin → 200.
    pre = client.get(
        "/users", headers={**_auth(client), "X-Impersonate-User-Id": target}
    )
    assert pre.status_code == 200

    client.post("/impersonation/start", headers=_auth(client), json={"targetUserId": target})

    # With the active session, the header swaps the effective user → target lacks
    # users.read → 403, but can still read roles → 200.
    blocked = client.get("/users", headers={**_auth(client), "X-Impersonate-User-Id": target})
    assert blocked.status_code == 403
    allowed = client.get("/roles", headers={**_auth(client), "X-Impersonate-User-Id": target})
    assert allowed.status_code == 200

    # /auth/me reflects the effective (target) user while impersonating.
    me = client.get("/auth/me", headers={**_auth(client), "X-Impersonate-User-Id": target}).json()
    assert me["email"] == "t2@foundryx.io"


def test_stop_ends_session(client, session_factory):
    target = _make_user(session_factory, "t3@foundryx.io", "pw12345678", perm_keys=["roles.read"])
    client.post("/impersonation/start", headers=_auth(client), json={"targetUserId": target})
    assert client.post("/impersonation/stop", headers=_auth(client)).json()["ended"] is True
    assert client.get("/impersonation/current", headers=_auth(client)).json() is None
    # Header no longer honored → admin sees users again.
    res = client.get("/users", headers={**_auth(client), "X-Impersonate-User-Id": target})
    assert res.status_code == 200
