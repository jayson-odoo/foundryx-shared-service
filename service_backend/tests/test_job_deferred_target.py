"""Plan 45, AC-45-10 - a deferred jobs.abort / jobs.complete names a storage
migration job; any other job id answers as a missing one."""
from __future__ import annotations

import uuid

import pytest

from app.deferred_actions.service import PendingActionService, TargetNotFound
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from app.models.user import User
from tests.conftest import ACTIVE_EMAIL


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _job(db, job_type, status="needs_review") -> str:
    job = BackgroundJob(tenant_id=DEFAULT_TENANT_ID, type=job_type, status=status)
    db.add(job)
    db.commit()
    return job.id


def _park(db, action_key, entity_id):
    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    return PendingActionService(db).park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key=action_key, entity_type="background_job", entity_id=entity_id,
    )


@pytest.mark.parametrize("action_key", ["jobs.abort", "jobs.complete"])
def test_ac_45_10_storage_migration_job_is_accepted(db, action_key):
    row = _park(db, action_key, _job(db, "storage_migration"))
    assert row.action_key == action_key


@pytest.mark.parametrize("action_key", ["jobs.abort", "jobs.complete"])
@pytest.mark.parametrize("job_type", ["autocount_sync", "omnichannel.respondio_migration"])
def test_ac_45_10_other_job_answers_as_a_missing_id(db, action_key, job_type):
    other = _job(db, job_type)
    gone = str(uuid.uuid4())
    with pytest.raises(TargetNotFound) as missing:
        _park(db, action_key, gone)
    with pytest.raises(TargetNotFound) as wrong_type:
        _park(db, action_key, other)
    assert str(wrong_type.value).replace(other, "ID") == str(missing.value).replace(gone, "ID")
