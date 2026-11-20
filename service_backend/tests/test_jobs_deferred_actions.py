"""background_jobs deferred actions (sprint-4/23, T5 fix round 1, item 15) -
`jobs.abort` / `jobs.complete` migrated off `confirm:`. The underlying
`StorageMigrationService.abort`/`.complete` mechanics are already exhaustively
covered by `tests/test_storage_migration.py`; these tests cover only the
deferred-action WRAPPING (registration, permission, park->lapse->commit
reaching the SAME terminal states), reusing that file's fixtures/helpers
rather than re-deriving the needs_review scenario from scratch.
"""
from datetime import datetime, timedelta, timezone

from app.deferred_actions.registry import deferred_action_for
from app.deferred_actions.service import PendingActionService
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_ABORTED, JOB_DONE
from app.models.pending_action import PendingAction
from app.models.user import User
from app.repositories.connection_repository import ConnectionRepository
from tests.conftest import ACTIVE_EMAIL
from tests.test_storage_migration import (  # noqa: F401 - reused fixtures
    FakeAdapter,
    _point_avatar,
    _start,
    _storage_conn,
    db,
    fakes,
    only_avatar_location,
    stub_probe,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _admin(db) -> User:
    return db.query(User).filter(User.email == ACTIVE_EMAIL).first()


def test_jobs_abort_and_complete_registered():
    for key, entity_type, window in (
        ("jobs.abort", "background_job", "reversible"),
        ("jobs.complete", "background_job", "destructive"),
    ):
        action_def = deferred_action_for(key)
        assert action_def.entity_type == entity_type
        assert action_def.window == window
        assert action_def.permission == "integrations.migrate_storage"


def test_jobs_abort_deferred_reaches_the_same_terminal_state(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")  # raw2 missing -> needs_review
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"])

    job = _start(db)
    assert job.status == "needs_review"

    admin = _admin(db)
    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="jobs.abort", entity_type="background_job", entity_id=job.id,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    result = svc.commit_one(row)
    assert result.status == "committed"

    db.refresh(job)
    db.refresh(a)
    assert job.status == JOB_ABORTED
    assert a.is_active is True  # A restored (StorageMigrationService.abort)


def test_jobs_complete_deferred_reaches_the_same_terminal_state(db, only_avatar_location, fakes, stub_probe):
    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")  # raw2 missing -> needs_review
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1", f"conn:{a.id}:raw2"])

    job = _start(db)
    assert job.status == "needs_review"

    admin = _admin(db)
    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="jobs.complete", entity_type="background_job", entity_id=job.id,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()

    result = svc.commit_one(row)
    assert result.status == "committed"

    db.refresh(job)
    assert job.status == JOB_DONE
    # The successfully-copied key (raw1) cut over to B.
    b_id = job.payload_json["toConnectionId"]
    db.expire_all()
    vals = {u.avatar_key for u in db.query(User).filter(User.avatar_key.isnot(None))}
    assert f"conn:{b_id}:raw1" in vals
    assert ConnectionRepository(db).get_by_id(b_id) is not None
