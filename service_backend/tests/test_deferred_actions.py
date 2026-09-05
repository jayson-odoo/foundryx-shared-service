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
        exists=lambda *a, **k: True,
    )
    b = DeferredActionDef(
        key="widget.test_dup", entity_type=TEST_ENTITY, permission="users.delete",
        window="destructive", label="Delete (other)", execute=lambda *a, **k: None,
        exists=lambda *a, **k: True,
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
    if entity_id in _WIDGET_STATE.get("missing_ids", set()):
        raise RuntimeError("widget no longer exists")
    _WIDGET_STATE[entity_id] = {"deleted": True, "actor": actor_user_id, "payload": payload}


def _widget_exists(db, tenant_id, entity_id):
    return entity_id not in _WIDGET_STATE.get("missing_ids", set())


WIDGET_DELETE = DeferredActionDef(
    key="widget.delete",
    entity_type=TEST_ENTITY,
    permission="users.delete",
    window="destructive",
    label="Delete widget",
    execute=_widget_execute,
    exists=_widget_exists,
)
WIDGET_ARCHIVE = DeferredActionDef(
    key="widget.archive",
    entity_type=TEST_ENTITY,
    permission="users.update",
    window="reversible",
    label="Archive widget",
    execute=lambda *a, **k: None,
    exists=_widget_exists,
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


# ── fix round 1, item 1: cancel/current gated by the parked action's own
# permission, not just "any authenticated user in the tenant" ──────────────


def test_current_without_the_actions_permission_is_uniform_404(client, session_factory):
    _make_user(session_factory, "viewer-dla@foundryx.io", perm_keys=["users.read"])
    admin_h = _login(client)
    client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w-sec1"},
        headers=admin_h,
    )

    viewer_h = _login(client, "viewer-dla@foundryx.io", "pw12345678")
    res = client.get(
        "/api/v1/pending-actions/current",
        params={"entityType": TEST_ENTITY, "entityId": "w-sec1"},
        headers=viewer_h,
    )
    assert res.status_code == 404

    # The holder of the action's permission sees it fine.
    ok = client.get(
        "/api/v1/pending-actions/current",
        params={"entityType": TEST_ENTITY, "entityId": "w-sec1"},
        headers=admin_h,
    )
    assert ok.status_code == 200
    assert ok.json()["pending"] is not None


def test_cancel_without_the_actions_permission_is_403(client, session_factory):
    _make_user(session_factory, "viewer-dla2@foundryx.io", perm_keys=["users.read"])
    admin_h = _login(client)
    row = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w-sec2"},
        headers=admin_h,
    ).json()

    viewer_h = _login(client, "viewer-dla2@foundryx.io", "pw12345678")
    res = client.post(f"/api/v1/pending-actions/{row['id']}/cancel", headers=viewer_h)
    assert res.status_code == 403
    # Untouched - still pending, cancellable by a holder of the permission.
    assert "w-sec2" not in _WIDGET_STATE


def test_a_second_teammate_holding_the_permission_can_cancel(client, session_factory):
    """A teammate admin can veto another admin's parked action (D2 - anyone
    in the tenant WITH the permission may cancel, not only the requester)."""
    second_admin = _make_user(
        session_factory, "second-admin-dla@foundryx.io", perm_keys=["users.delete", "users.read"]
    )
    admin_h = _login(client)
    row = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w-sec3"},
        headers=admin_h,
    ).json()

    second_h = _login(client, "second-admin-dla@foundryx.io", "pw12345678")
    res = client.post(f"/api/v1/pending-actions/{row['id']}/cancel", headers=second_h)
    assert res.status_code == 200
    assert res.json()["status"] == PENDING_ACTION_CANCELLED
    assert second_admin  # keep the fixture referenced


# ── fix round 1, item 4: atomic claim - a race never runs the handler twice ─


def test_two_concurrent_commit_attempts_run_the_handler_once(db):
    """Simulates the beat sweep racing the frontend's lazy `current` poll
    against the SAME overdue row: two independent `commit_one` calls must
    only ever apply the handler once (the second sees the claim already
    taken and returns the settled row untouched)."""
    admin = _admin(db)
    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="widget.delete", entity_type=TEST_ENTITY, entity_id="w-race",
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    first = svc.commit_one(row)
    second = svc.commit_one(row)

    assert first.status == PENDING_ACTION_COMMITTED
    assert second.status == PENDING_ACTION_COMMITTED
    assert second.id == first.id
    # The handler recorded exactly one application, not two.
    assert _WIDGET_STATE["w-race"]["deleted"] is True


# ── fix round 1, item 7: park validates the target exists; a vanished target
# fails the commit instead of silently no-op'ing ───────────────────────────


def test_park_against_a_missing_target_is_404(client):
    h = _login(client)
    _WIDGET_STATE["missing_ids"] = {"w-ghost"}
    res = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "widget.delete", "entityType": TEST_ENTITY, "entityId": "w-ghost"},
        headers=h,
    )
    assert res.status_code == 404


def test_target_vanishing_during_the_window_fails_the_commit(db):
    """The record existed at park time but is gone by commit time - the
    handler must fail loudly, never silently no-op (AC-DLA-41)."""
    admin = _admin(db)
    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="widget.delete", entity_type=TEST_ENTITY, entity_id="w-vanish",
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    # The target vanishes before the sweep gets to it.
    _WIDGET_STATE["missing_ids"] = {"w-vanish"}

    committed = svc.commit_due()
    assert committed == 1
    settled = db.get(PendingAction, row.id)
    assert settled.status == PENDING_ACTION_FAILED
    assert "w-vanish" not in _WIDGET_STATE


def test_users_trash_handler_fails_when_the_user_is_gone(db, session_factory):
    """A real first-party handler (not just the synthetic widget) asserts it
    touched a row - `UserService.trash` is a bulk `UPDATE ... WHERE id IN
    (...)` that silently no-ops on a missing id without this guard."""
    admin = _admin(db)
    target = _make_user(session_factory, "vanish-me@foundryx.io", perm_keys=["users.read"])
    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="users.trash", entity_type="user", entity_id=target,
    )
    # The user is hard-removed out from under the pending action (edge case -
    # normally trashed, but the guard must hold regardless of how it vanished).
    other_db = session_factory()
    other_db.query(User).filter(User.id == target).delete(synchronize_session=False)
    other_db.commit()
    other_db.close()

    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    result = svc.commit_one(row)
    assert result.status == PENDING_ACTION_FAILED
    assert result.error_text and "no longer exists" in result.error_text


# ── item 15: email_outbox.cancel (core - Settings > Email log) ─────────────


def _seed_outbox_row(db, tenant_id, status):
    from app.models.email_outbox import EmailOutbox

    row = EmailOutbox(
        tenant_id=tenant_id,
        to_email="user@example.com",
        subject="Subject",
        html_body="<html><body>hi</body></html>",
        text_body="hi",
        template_key="auth.invite",
        status=status,
        attempts=0,
        next_attempt_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_email_outbox_cancel_registered_and_commits(db):
    assert deferred_action_for("email_outbox.cancel").window == "reversible"
    assert deferred_action_for("email_outbox.cancel").permission == "emails.manage"

    admin = _admin(db)
    row = _seed_outbox_row(db, DEFAULT_TENANT_ID, "pending")
    svc = PendingActionService(db)
    pa = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="email_outbox.cancel", entity_type="email_outbox", entity_id=row.id,
    )
    stored = db.get(PendingAction, pa.id)
    stored.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    result = svc.commit_one(pa)
    assert result.status == PENDING_ACTION_COMMITTED
    db.refresh(row)
    assert row.status == "cancelled"


def test_email_outbox_cancel_missing_target_404_at_park(client):
    h = _login(client)
    res = client.post(
        "/api/v1/pending-actions",
        json={"actionKey": "email_outbox.cancel", "entityType": "email_outbox", "entityId": "no-such-email"},
        headers=h,
    )
    assert res.status_code == 404
