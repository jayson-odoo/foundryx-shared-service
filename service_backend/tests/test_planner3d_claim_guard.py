"""The claim UPDATE must itself refuse a job that is no longer queued (AC-S3-04)."""
from __future__ import annotations

from tests.planner3d_helpers import (  # noqa: F401 - pytest fixtures
    WORKER,
    OTHER_WORKER,
    claim,
    p3,
    staff,
    submit_model,
    worker_token,
)


class _StaleQuery:
    """Stands in for the candidate select: always names one fixed job id."""

    def __init__(self, job_id):
        self._id = job_id

    def filter(self, *a, **k):
        return self

    order_by = with_for_update = filter

    def first(self):
        return (self._id,)


class _StaleCandidateSession:
    def __init__(self, real, job_id):
        self._real, self._id = real, job_id

    def query(self, *entities, **k):
        # only the candidate select (selecting the id column) is faked
        if len(entities) == 1 and getattr(entities[0], "key", None) == "id":
            return _StaleQuery(self._id)
        return self._real.query(*entities, **k)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_ac04_claim_update_refuses_a_candidate_that_is_already_running(client, staff, p3):
    from modules.planner3d import models
    from modules.planner3d.repositories import job_repository as repo

    job_id = submit_model(client, staff).json()["id"]
    assert claim(client, ["model"], name=WORKER).status_code == 200  # running, held by WORKER

    db = p3()
    try:
        before = db.get(models.P3Job, job_id)
        held = (before.worker_name, before.claimed_at, before.status)
        assert held[0] == WORKER and held[2] == "running"
        db.expire_all()
        got = repo.claim_oldest(_StaleCandidateSession(db, job_id), ["model"], OTHER_WORKER)
        assert got is None
        db.expire_all()
        after = db.get(models.P3Job, job_id)
        assert (after.worker_name, after.claimed_at, after.status) == held
    finally:
        db.close()


def test_ac04_claim_update_takes_a_queued_candidate_control(client, staff, p3):
    from modules.planner3d import models
    from modules.planner3d.repositories import job_repository as repo

    job_id = submit_model(client, staff).json()["id"]
    db = p3()
    try:
        got = repo.claim_oldest(_StaleCandidateSession(db, job_id), ["model"], OTHER_WORKER)
        assert got is not None and got.id == job_id and got.worker_name == OTHER_WORKER
        db.commit()
    finally:
        db.close()
