"""Integration-activity retention + settings (sprint-4/12 Slice 3, AC-DLC-21/22).

Covers the per-tenant beat pruner (prunes only past-window rows; respects a
per-tenant override vs the global default) and the tenant-scoped, gated
``GET/PUT /integration-logs/settings`` endpoints.
"""
from datetime import datetime, timedelta, timezone

from app.activity_log.retention import prune_integration_activity
from app.activity_log.service import ActivityLogService
from app.config import settings
from app.models.integration_activity import (
    IntegrationActivity,
    SOURCE_INBOUND_API,
)
from app.models.integration_log_settings import IntegrationLogSettings
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, DEFAULT_TENANT_ID

OTHER_TENANT = "tenant-retention-other"


def _headers(client):
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _row(db, tenant_id, *, age_days: float) -> str:
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    row = IntegrationActivity(
        tenant_id=tenant_id,
        source=SOURCE_INBOUND_API,
        operation="POST /messages",
        status="success",
        created_at=created,
    )
    db.add(row)
    db.commit()
    return row.id


# ── prune: only past-window, per-tenant override ─────────────────────────────
def test_prune_deletes_only_past_window_rows(session_factory):
    db = session_factory()
    default = settings.integration_activity_retention_days  # 30
    old_id = _row(db, DEFAULT_TENANT_ID, age_days=default + 5)
    fresh_id = _row(db, DEFAULT_TENANT_ID, age_days=default - 5)

    deleted = prune_integration_activity(db)
    assert deleted == 1
    ids = {r.id for r in db.query(IntegrationActivity).all()}
    assert old_id not in ids
    assert fresh_id in ids
    db.close()


def test_prune_respects_per_tenant_override(session_factory):
    db = session_factory()
    default = settings.integration_activity_retention_days  # 30
    # OTHER_TENANT keeps only 7 days — a 10-day-old row is pruned for it but a
    # 10-day-old row for the default tenant (30d default) survives.
    db.add(IntegrationLogSettings(tenant_id=OTHER_TENANT, retention_days=7))
    db.commit()
    other_old = _row(db, OTHER_TENANT, age_days=10)
    other_fresh = _row(db, OTHER_TENANT, age_days=3)
    default_same_age = _row(db, DEFAULT_TENANT_ID, age_days=10)

    deleted = prune_integration_activity(db)
    ids = {r.id for r in db.query(IntegrationActivity).all()}
    assert other_old not in ids  # past the 7-day override
    assert other_fresh in ids
    assert default_same_age in ids  # within the 30-day global default
    assert deleted == 1
    db.close()


# ── settings endpoints: tenant-scoped + gated ────────────────────────────────
def test_get_settings_default(client):
    res = client.get("/integration-logs/settings", headers=_headers(client))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["retentionDays"] == settings.integration_activity_retention_days
    assert body["isDefault"] is True


def test_put_then_get_settings_override(client):
    hdrs = _headers(client)
    put = client.put(
        "/integration-logs/settings", json={"retentionDays": 14}, headers=hdrs
    )
    assert put.status_code == 200, put.text
    assert put.json() == {"retentionDays": 14, "isDefault": False}

    get = client.get("/integration-logs/settings", headers=hdrs)
    assert get.json() == {"retentionDays": 14, "isDefault": False}


def test_put_settings_validates_range(client):
    hdrs = _headers(client)
    assert (
        client.put(
            "/integration-logs/settings", json={"retentionDays": 0}, headers=hdrs
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/integration-logs/settings", json={"retentionDays": 99999}, headers=hdrs
        ).status_code
        == 422
    )


def test_settings_requires_manage_permission(client, session_factory):
    """A user WITHOUT integration_logs.manage is 403 (backend is the boundary)."""
    from app.models import Role, User, UserStatus
    from app.security import hash_password

    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="LogViewer", is_system=False)
    db.add(role)
    db.flush()
    # Grant read only (no manage).
    from app.repositories.permission_repository import PermissionRepository

    read_perm = next(
        p for p in PermissionRepository(db).list_all() if p.key == "integration_logs.read"
    )
    role.permissions = [read_perm]
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="logviewer@example.com",
        name="Log Viewer",
        password=hash_password("viewer1234"),
        status=UserStatus.ACTIVE.value,
        roles=[role],
    )
    db.add(user)
    db.commit()
    db.close()

    res = client.post(
        "/auth/login", json={"email": "logviewer@example.com", "password": "viewer1234"}
    )
    hdrs = {"Authorization": f"Bearer {res.json()['access_token']}"}
    # read endpoint OK, manage endpoint 403.
    assert client.get("/integration-logs", headers=hdrs).status_code == 200
    assert client.get("/integration-logs/settings", headers=hdrs).status_code == 403
    assert (
        client.put(
            "/integration-logs/settings", json={"retentionDays": 10}, headers=hdrs
        ).status_code
        == 403
    )


def test_set_retention_is_tenant_scoped(session_factory):
    """set_retention writes only the caller's tenant row."""
    db = session_factory()
    ActivityLogService(db).set_retention(DEFAULT_TENANT_ID, 21)
    rows = db.query(IntegrationLogSettings).all()
    assert len(rows) == 1
    assert rows[0].tenant_id == DEFAULT_TENANT_ID
    assert rows[0].retention_days == 21
    # OTHER_TENANT still resolves the global default (no row).
    days, is_default = ActivityLogService(db).get_retention(OTHER_TENANT)
    assert is_default is True
    assert days == settings.integration_activity_retention_days
    db.close()
