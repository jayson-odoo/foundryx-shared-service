"""Deferred actions - the grace-window engine (sprint-4/23, T5).

Covers AC-DLA-37..41: park/idempotent/409/400/403, cancel before/after,
current lazy-commit, sweeper isolation (a due row commits via a directly
back-dated `commit_at` rather than mocking the wall clock - deterministic and
simpler), handler failure isolation, cross-tenant 404, window from settings,
impersonation actor, and `users.trash` end to end.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.sql import func

from app.deferred_actions.registry import (
    DeferredActionDef,
    _reset_registry_for_tests,
    deferred_action_for,
    register_deferred_action,
)
from app.deferred_actions.handlers import register_deferred_actions
from app.deferred_actions.service import PendingActionService
from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.pending_action import (
    PENDING_ACTION_CANCELLED,
    PENDING_ACTION_COMMITTED,
    PENDING_ACTION_FAILED,
    PENDING_ACTION_PENDING,
    PendingAction,
)
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

TEST_ENTITY = "widget"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _register():
    """Re-register the first-party handlers + a synthetic test one after any
    test that reset the registry - idempotent (same def objects)."""
    register_deferred_actions()
    yield


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _login(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> dict:
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _make_user(session_factory, email, *, perm_keys, password="pw12345678", tenant_id=DEFAULT_TENANT_ID) -> str:
    db = session_factory()
    user = User(
        tenant_id=tenant_id,
        email=email,
        password=hash_password(password),
        name=email.split("@")[0].title(),
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    role = Role(tenant_id=tenant_id, name=f"role-{email}")
    role.permissions = PermissionRepository(db).get_by_keys(perm_keys)
    db.add(role)
    db.flush()
    user.roles = [role]
    db.add(user)
    db.commit()
    uid = user.id
    db.close()
    return uid


# ── registry ──────────────────────────────────────────────────────────────


def test_deferred_action_for_unknown_key_raises():
    from app.deferred_actions.registry import UnknownDeferredAction

    with pytest.raises(UnknownDeferredAction):
        deferred_action_for("nope.delete")


def test_duplicate_registration_of_a_different_def_is_loud():
    a = DeferredActionDef(
        key="widget.test_dup", entity_type=TEST_ENTITY, permission="users.delete",
        window="destructive", label="Delete", execute=lambda *a, **k: None,
    )
    b = DeferredActionDef(
        key="widget.test_dup", entity_type=TEST_ENTITY, permission="users.delete",
        window="destructive", label="Delete (other)", execute=lambda *a, **k: None,
    )
    register_deferred_action(a)
    with pytest.raises(ValueError):
        register_deferred_action(b)
    # Re-registering the SAME def object is tolerated (idempotent boot).
    register_deferred_action(a)


def test_first_party_actions_registered():
    for key in (
        "users.trash", "roles.delete", "workflows.delete", "forms.delete",
        "templates.delete", "connections.delete", "ai_agents.delete",
        "ai_skills.delete", "documents.trash", "tenants.archive",
    ):
        assert deferred_action_for(key).key == key


# ── a synthetic widget entity for the service-level tests ──────────────────

_WIDGET_STATE: dict = {}


def _widget_execute(db, tenant_id, entity_id, payload, actor_user_id):
    if entity_id in _WIDGET_STATE.get("boom_ids", set()):
        raise RuntimeError("handler exploded")
    _WIDGET_STATE[entity_id] = {"deleted": True, "actor": actor_user_id, "payload": payload}


WIDGET_DELETE = DeferredActionDef(
    key="widget.delete",
    entity_type=TEST_ENTITY,
    permission="users.delete",
    window="destructive",
    label="Delete widget",
    execute=_widget_execute,
)
WIDGET_ARCHIVE = DeferredActionDef(
    key="widget.archive",
    entity_type=TEST_ENTITY,
    permission="users.update",
    window="reversible",
    label="Archive widget",
    execute=lambda *a, **k: None,
)


@pytest.fixture(autouse=True)
def _register_widget():
    _WIDGET_STATE.clear()
    register_deferred_action(WIDGET_DELETE)
    register_deferred_action(WIDGET_ARCHIVE)
    yield
    _WIDGET_STATE.clear()


# ── AC-DLA-39: park / idempotent / 409 / 400 / 403 ──────────────────────────


def test_park_returns_202_with_commit_at_and_window(client):
    h = _login(client)
    res = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w1"},
        headers=h,
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["windowSeconds"] == 10  # destructive default
    assert body["id"]
    assert body["commitAt"].endswith("Z")
    # Nothing applied yet.
    assert "w1" not in _WIDGET_STATE


def test_double_park_same_key_is_idempotent(client):
    h = _login(client)
    first = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w2"},
        headers=h,
    ).json()
    second = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w2"},
        headers=h,
    ).json()
    assert first["id"] == second["id"]


def test_different_key_same_record_is_409(client):
    h = _login(client)
    client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w3"},
        headers=h,
    )
    res = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.archive", "entityType": TEST_ENTITY, "entityId": "w3"},
        headers=h,
    )
    assert res.status_code == 409


def test_unknown_action_key_is_400(client):
    h = _login(client)
    res = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "nope.delete", "entityType": TEST_ENTITY, "entityId": "w4"},
        headers=h,
    )
    assert res.status_code == 400


def test_missing_permission_is_403(client, session_factory):
    _make_user(session_factory, "noperm@foundryx.io", perm_keys=["users.read"])
    h = _login(client, "noperm@foundryx.io", "pw12345678")
    res = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w5"},
        headers=h,
    )
    assert res.status_code == 403


# ── AC-DLA-40: cancel before/after, current lazy commit, cross-tenant 404 ──


def test_cancel_before_window_closes(client):
    h = _login(client)
    row = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w6"},
        headers=h,
    ).json()
    res = client.post(f"/api/v1/pending-actions/{row['id']}/cancel", headers=h)
    assert res.status_code == 200
    assert res.json()["status"] == PENDING_ACTION_CANCELLED
    assert "w6" not in _WIDGET_STATE


def test_cancel_after_window_closes_commits_first_then_409(client, db):
    h = _login(client)
    row = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w7"},
        headers=h,
    ).json()
    pa = db.get(PendingAction, row["id"])
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    res = client.post(f"/api/v1/pending-actions/{row['id']}/cancel", headers=h)
    assert res.status_code == 409
    assert _WIDGET_STATE["w7"]["deleted"] is True


def test_current_lazily_commits_an_overdue_row(client, db):
    h = _login(client)
    row = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w8"},
        headers=h,
    ).json()
    pa = db.get(PendingAction, row["id"])
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    res = client.get(
        "/api/v1/pending-actions/current",
        params={"entityType": TEST_ENTITY, "entityId": "w8"},
        headers=h,
    )
    body = res.json()
    assert body["pending"] is None
    assert body["lastOutcome"]["status"] == PENDING_ACTION_COMMITTED
    assert _WIDGET_STATE["w8"]["deleted"] is True


def test_current_with_nothing_parked(client):
    h = _login(client)
    res = client.get(
        "/api/v1/pending-actions/current",
        params={"entityType": TEST_ENTITY, "entityId": "w-none"},
        headers=h,
    )
    body = res.json()
    assert body["pending"] is None
    assert body["lastOutcome"] is None


def test_cross_tenant_cancel_is_uniform_404(client, session_factory):
    from app.services.tenant_service import TenantService

    h = _login(client)
    row = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w9"},
        headers=h,
    ).json()

    db = session_factory()
    TenantService(db).provision(
        name="Acme", slug="acme-dla", admin_name="Kay", admin_email="admin@acme-dla.example.com",
        admin_password="pw12345678",
    )
    db.close()
    other_h = _login(client, "admin@acme-dla.example.com", "pw12345678", tenant_slug="acme-dla")

    res = client.post(f"/api/v1/pending-actions/{row['id']}/cancel", headers=other_h)
    assert res.status_code == 404


# ── AC-DLA-41: sweeper isolation ────────────────────────────────────────────


def test_commit_due_sweeps_every_overdue_row_isolated(db):
    """A handler failure on ONE overdue row never blocks the rest of the sweep,
    and the failed row's entity is left untouched (AC-DLA-41)."""
    admin = _admin(db)
    svc = PendingActionService(db)
    _WIDGET_STATE["boom_ids"] = {"sweep-boom"}
    ok = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="widget.delete", entity_type=TEST_ENTITY, entity_id="sweep-ok",
    )
    boom_row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="widget.delete", entity_type=TEST_ENTITY, entity_id="sweep-boom",
    )
    for row in (ok, boom_row):
        pa = db.get(PendingAction, row.id)
        pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    committed = svc.commit_due()
    assert committed == 2

    ok_row = db.get(PendingAction, ok.id)
    boom_row_after = db.get(PendingAction, boom_row.id)
    assert ok_row.status == PENDING_ACTION_COMMITTED
    assert "sweep-ok" in _WIDGET_STATE
    assert boom_row_after.status == PENDING_ACTION_FAILED
    assert boom_row_after.error_text and "exploded" in boom_row_after.error_text
    assert "sweep-boom" not in _WIDGET_STATE  # entity left untouched


def _admin(db) -> User:
    return db.query(User).filter(User.email == ACTIVE_EMAIL).first()


# ── window from settings ────────────────────────────────────────────────────


def test_window_seconds_read_from_tenant_settings(client):
    h = _login(client)
    res = client.put(
        "/settings/general",
        json={"deferredDestructiveSeconds": 3, "deferredReversibleSeconds": 2},
        headers=h,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["deferredDestructiveSeconds"] == 3
    assert body["deferredReversibleSeconds"] == 2

    park = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w-window"},
        headers=h,
    ).json()
    assert park["windowSeconds"] == 3

    park2 = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.archive", "entityType": TEST_ENTITY, "entityId": "w-window-2"},
        headers=h,
    ).json()
    assert park2["windowSeconds"] == 2


def test_default_settings_have_no_row_needed():
    """AC-DLA-37: existing tenants need no backfill - NULL = the defaults."""
    from app.services.catalog_service import TenantSettingsService

    class _FakeDb:
        def get(self, *a, **k):
            return None

    out = TenantSettingsService(_FakeDb()).get(DEFAULT_TENANT_ID)
    assert out["deferredDestructiveSeconds"] == 10
    assert out["deferredReversibleSeconds"] == 5


# ── impersonation actor ─────────────────────────────────────────────────────


def test_park_under_impersonation_records_the_real_admin(client, session_factory):
    target = _make_user(session_factory, "target-dla@foundryx.io", perm_keys=["users.delete"])
    admin_h = _login(client)
    start = client.post(
        "/impersonation/start", headers=admin_h, json={"targetUserId": target}
    )
    assert start.status_code == 200, start.text

    db = session_factory()
    admin_id = db.query(User).filter(User.email == ACTIVE_EMAIL).first().id
    db.close()

    row = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w-imp"},
        headers={**admin_h, "X-Impersonate-User-Id": target},
    ).json()

    db = session_factory()
    pa = db.get(PendingAction, row["id"])
    assert pa.requested_by_id == admin_id
    assert pa.requested_by_id != target
    db.close()


# ── users.trash end to end ──────────────────────────────────────────────────


def test_users_trash_end_to_end_commits_and_restores(client, session_factory):
    target = _make_user(session_factory, "trash-me@foundryx.io", perm_keys=["users.read"])
    h = _login(client)

    row = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "users.trash", "entityType": "user", "entityId": target},
        headers=h,
    ).json()
    assert row["windowSeconds"] == 10

    db = session_factory()
    pa = db.get(PendingAction, row["id"])
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()
    db.close()

    cur = client.get(
        "/api/v1/pending-actions/current",
        params={"entityType": "user", "entityId": target},
        headers=h,
    ).json()
    assert cur["pending"] is None
    assert cur["lastOutcome"]["status"] == PENDING_ACTION_COMMITTED

    db = session_factory()
    user = db.query(User).filter(User.id == target).first()
    assert user.is_trashed is True
    db.close()

    # Restorable from the Trashed view (the same endpoint the UI's Restore uses).
    restore = client.post("/users/restore", json={"ids": [target]}, headers=h)
    assert restore.status_code == 204, restore.text
    db = session_factory()
    user = db.query(User).filter(User.id == target).first()
    assert user.is_trashed is False
    db.close()
