""""Re-push all" as a deferred (grace-window) action (sprint-5/07 review
round - D2/D13: no confirm dialog, a server-parked countdown committed by
the SAME core engine `omnichannel`/`ideation` extend). Covers registration,
park->lapse->commit end to end (hashes cleared, reconcile armed, actor
recorded), the permission/tenant-scoping guards at park time, and the
in-flight guard surfacing as a FAILED commit (never a silent success) with
the wipe rolled back.

Rig/consumer/auth helpers are the ones `test_autocount_etl_task_routes`
already drives an activated `sql_db` task with (same precedent as
`test_autocount_preview_consumer_error.py`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.deferred_actions.registry import deferred_action_for
from app.deferred_actions.service import PendingActionService
from app.models import DEFAULT_TENANT_ID, User
from app.models.background_job import JOB_RUNNING, BackgroundJob
from app.models.integration_activity import IntegrationActivity
from app.models.pending_action import PendingAction
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import AcEntityConfig, AcRowHash
from tests.test_autocount_etl_task_routes import (  # noqa: F401 - fixtures re-exported
    OTHER_TENANT,
    _activated,
    _auth,
    _clean_runtime,
    _company,
    _limited_user,
    _other_tenant,
    consumer,
    rig,
)

ACTION_KEY = "autocount_etl_task.repush"
ENTITY_TYPE = "autocount_etl_task"
PARK_URL = "/api/v1/pending-actions"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _admin(db) -> User:
    return db.query(User).filter(User.email == "demo@example.com").first()


def _customer_config_id(db, company_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> str:
    row = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == tenant_id,
            AcEntityConfig.company_id == company_id,
            AcEntityConfig.entity_type == ENTITY_CUSTOMER,
        )
        .one()
    )
    return row.id


def _row_hash_count(db, *, company_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> int:
    return (
        db.query(AcRowHash)
        .filter(
            AcRowHash.tenant_id == tenant_id,
            AcRowHash.company_id == company_id,
            AcRowHash.entity_type == ENTITY_CUSTOMER,
        )
        .count()
    )


def _park_and_lapse(db, admin, entity_id: str) -> PendingAction:
    """Park, force the window closed, commit - the same shape every other
    deferred-action test file's own `_park_and_lapse` uses."""
    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID,
        actor=admin,
        requested_by_id=admin.id,
        action_key=ACTION_KEY,
        entity_type=ENTITY_TYPE,
        entity_id=entity_id,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()
    return svc.commit_one(row)


def test_repush_action_is_registered():
    action_def = deferred_action_for(ACTION_KEY)
    assert action_def.key == ACTION_KEY
    assert action_def.entity_type == ENTITY_TYPE
    assert action_def.permission == "autocount.companies.manage"
    assert action_def.window == "destructive"


def test_park_via_the_pending_actions_api_as_a_manage_user_returns_202(
    client, session_factory, rig, consumer,
):
    company_id, _sql_id = rig
    _activated(client, company_id)
    db = session_factory()
    entity_id = _customer_config_id(db, company_id)
    db.close()

    response = client.post(
        PARK_URL,
        headers=_auth(client),
        json={"actionKey": ACTION_KEY, "entityType": ENTITY_TYPE, "entityId": entity_id},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["commitAt"]
    assert body["windowSeconds"] > 0


def test_commit_clears_hashes_arms_the_reconcile_and_records_the_actor(
    client, session_factory, rig, consumer,
):
    company_id, _sql_id = rig
    _activated(client, company_id)
    db = session_factory()
    entity_id = _customer_config_id(db, company_id)
    db.add(AcRowHash(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=ENTITY_CUSTOMER,
        source_ref="a1", row_hash="h",
    ))
    db.add(AcRowHash(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=ENTITY_CUSTOMER,
        source_ref="a2", row_hash="h",
    ))
    db.commit()
    admin = _admin(db)
    admin_id = admin.id

    result = _park_and_lapse(db, admin, entity_id)
    assert result.status == "committed", result.error_text

    assert _row_hash_count(db, company_id=company_id) == 0

    config = db.get(AcEntityConfig, entity_id)
    assert config.next_reconcile_at is not None, "an active task must arm the next reconcile"

    activity = (
        db.query(IntegrationActivity)
        .filter(
            IntegrationActivity.tenant_id == DEFAULT_TENANT_ID,
            IntegrationActivity.source == "autocount",
            IntegrationActivity.operation.ilike("%repush%"),
        )
        .order_by(IntegrationActivity.created_at.desc())
        .first()
    )
    assert activity is not None
    assert (activity.response_summary_json or {}).get("actorUserId") == admin_id
    db.close()


def test_park_by_a_sync_run_only_user_is_403(client, session_factory, rig, consumer):
    company_id, _sql_id = rig
    _activated(client, company_id)
    db = session_factory()
    entity_id = _customer_config_id(db, company_id)
    _limited_user(db, ["autocount.sync.run"], "syncrunner-repush@example.com")
    db.close()

    response = client.post(
        PARK_URL,
        headers=_auth(client, "syncrunner-repush@example.com", "limited1234"),
        json={"actionKey": ACTION_KEY, "entityType": ENTITY_TYPE, "entityId": entity_id},
    )
    assert response.status_code == 403, response.text


def test_park_on_another_tenants_config_id_is_404(client, session_factory):
    db = session_factory()
    _other_tenant(db)
    other_company = _company(db, tenant_id=OTHER_TENANT, database_name="THEIRS_DEFERRED")
    entity_id = _customer_config_id(db, other_company.id, tenant_id=OTHER_TENANT)
    db.close()

    response = client.post(
        PARK_URL,
        headers=_auth(client),
        json={"actionKey": ACTION_KEY, "entityType": ENTITY_TYPE, "entityId": entity_id},
    )
    assert response.status_code == 404, response.text


def test_commit_while_a_run_is_in_flight_fails_with_the_409_message_hashes_intact(
    client, session_factory, rig, consumer,
):
    company_id, _sql_id = rig
    _activated(client, company_id)
    db = session_factory()
    entity_id = _customer_config_id(db, company_id)
    db.add(AcRowHash(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=ENTITY_CUSTOMER,
        source_ref="untouched", row_hash="h",
    ))
    db.add(BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="autocount_sync", status=JOB_RUNNING,
        payload_json={"companyId": company_id, "entityType": ENTITY_CUSTOMER},
    ))
    db.commit()
    admin = _admin(db)

    result = _park_and_lapse(db, admin, entity_id)
    assert result.status == "failed"
    assert "still going" in (result.error_text or "").lower()

    assert _row_hash_count(db, company_id=company_id) == 1, (
        "a run in flight at commit time must leave the tracked rows untouched"
    )
    db.close()


def test_cancel_before_commit_clears_nothing(client, session_factory, rig, consumer):
    company_id, _sql_id = rig
    _activated(client, company_id)
    db = session_factory()
    entity_id = _customer_config_id(db, company_id)
    db.add(AcRowHash(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=ENTITY_CUSTOMER,
        source_ref="untouched", row_hash="h",
    ))
    db.commit()
    admin = _admin(db)

    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key=ACTION_KEY, entity_type=ENTITY_TYPE, entity_id=entity_id,
    )
    cancelled = svc.cancel(DEFAULT_TENANT_ID, row.id, admin)
    assert cancelled.status == "cancelled"

    assert _row_hash_count(db, company_id=company_id) == 1
    db.close()
