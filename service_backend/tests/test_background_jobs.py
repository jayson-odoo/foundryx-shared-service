"""Centralized background-jobs infra (sprint-4/10 Slice 1) — AC-10-01..03.

Covers: table shape + ApiModel wire, handler registry + dispatch + unknown-type
loud, atomic claim exactly-once, eager inline run, resume-from-cursor, retention
prune (terminal-only).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.jobs.registry import (
    JobHandlerDef,
    UnknownJobType,
    handler_for,
    register_job_handler,
)
from app.jobs.schemas import BackgroundJobOut
from app.jobs.service import JobService, prune_jobs, run_job
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    BackgroundJob,
)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ── shared test handlers (module-level def objects → idempotent re-register) ──

_RUN_LOG: list = []


def _counting_handler(db, job):
    _RUN_LOG.append(job.id)
    JobService(db).finish(job, status=JOB_DONE, result={"ran": True})


def _crashing_handler(db, job):
    raise RuntimeError("boom")


def _resume_handler(db, job):
    """Resumes from cursor_json: never re-processes an already-done index."""
    svc = JobService(db)
    items = (job.payload_json or {}).get("items", [])
    processed = list((job.result_json or {}).get("processed", []))
    index = (job.cursor_json or {}).get("index", 0)
    while index < len(items):
        processed.append(items[index])
        index += 1
        svc.set_cursor(job, {"index": index})
    svc.finish(job, status=JOB_DONE, result={"processed": processed})


_COUNTING = JobHandlerDef(type="test_counting", handler=_counting_handler, label="Counting")
_CRASHING = JobHandlerDef(type="test_crashing", handler=_crashing_handler, label="Crashing")
_RESUME = JobHandlerDef(type="test_resume", handler=_resume_handler, label="Resume")


@pytest.fixture(autouse=True)
def _register_handlers():
    _RUN_LOG.clear()
    register_job_handler(_COUNTING)
    register_job_handler(_CRASHING)
    register_job_handler(_RESUME)
    yield


# ── AC-10-01: table shape + ApiModel wire ─────────────────────────────────────


def test_background_job_row_shape(db):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID,
        type="storage_migration",
        status=JOB_PENDING,
        actor_user_id="user-1",
        payload_json={"fromConnectionId": "A", "toConnectionId": "B"},
    )
    db.add(job)
    db.commit()

    fetched = db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    # int defaults
    assert fetched.progress_total == 0
    assert fetched.progress_done == 0
    assert fetched.progress_failed == 0
    # JSON(none_as_null): unset JSON columns are SQL NULL, not JSON 'null'.
    assert fetched.result_json is None
    assert fetched.cursor_json is None
    assert fetched.error is None
    # created_at is aware-UTC (UTCDateTime).
    assert fetched.created_at.tzinfo is not None
    assert fetched.created_at.utcoffset() == timedelta(0)
    assert fetched.finished_at is None


def test_none_json_is_sql_null(db):
    """none_as_null: a job with no payload does NOT match IS NOT NULL."""
    job = BackgroundJob(tenant_id=DEFAULT_TENANT_ID, type="test_counting", status=JOB_PENDING)
    db.add(job)
    db.commit()
    matched = (
        db.query(BackgroundJob)
        .filter(BackgroundJob.id == job.id, BackgroundJob.payload_json.isnot(None))
        .first()
    )
    assert matched is None


def test_api_schema_is_camelcase_and_z_wire(db):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID,
        type="storage_migration",
        status=JOB_PENDING,
        payload_json={"x": 1},
    )
    db.add(job)
    db.commit()
    out = BackgroundJobOut.model_validate(job)
    dumped = out.model_dump(by_alias=True, mode="json")
    assert dumped["tenantId"] == DEFAULT_TENANT_ID
    assert dumped["progressTotal"] == 0
    assert dumped["payload"] == {"x": 1}
    # Z-suffixed datetime wire (ApiModel).
    assert dumped["createdAt"].endswith("Z")


# ── AC-10-02: handler registry + dispatch ─────────────────────────────────────


def test_unknown_type_is_loud():
    with pytest.raises(UnknownJobType):
        handler_for("no_such_type")


def test_create_rejects_unknown_type(db):
    with pytest.raises(UnknownJobType):
        JobService(db).create(type="no_such_type", tenant_id=DEFAULT_TENANT_ID)


def test_duplicate_registration_is_loud():
    other = JobHandlerDef(type="test_counting", handler=_crashing_handler, label="Dup")
    with pytest.raises(ValueError):
        register_job_handler(other)  # same type, different object → loud


def test_eager_enqueue_runs_inline(db):
    job = JobService(db).create_and_enqueue(type="test_counting", tenant_id=DEFAULT_TENANT_ID)
    db.refresh(job)
    assert job.status == JOB_DONE
    assert job.result_json == {"ran": True}
    assert _RUN_LOG == [job.id]


def test_atomic_claim_admits_exactly_one(db):
    svc = JobService(db)
    job = svc.create(type="test_counting", tenant_id=DEFAULT_TENANT_ID)
    assert svc.claim(job.id) is True  # pending → running
    assert svc.claim(job.id) is False  # already running → second attempt loses
    db.refresh(job)
    assert job.status == JOB_RUNNING


def test_run_job_dispatches_once_under_double_call(db):
    svc = JobService(db)
    job = svc.create(type="test_counting", tenant_id=DEFAULT_TENANT_ID)
    run_job(db, job.id)
    run_job(db, job.id)  # job now DONE → no second handler run
    assert _RUN_LOG == [job.id]


def test_handler_crash_is_isolated(db):
    svc = JobService(db)
    job = svc.create(type="test_crashing", tenant_id=DEFAULT_TENANT_ID)
    # run_job never propagates a handler crash.
    run_job(db, job.id)
    db.refresh(job)
    assert job.status == JOB_FAILED
    assert "boom" in (job.error or "")


# ── AC-10-03: resume + retention ──────────────────────────────────────────────


def test_resume_from_cursor_no_redo(db):
    """A crashed job (status=running, cursor at index 2) resumes without
    re-processing the first two items."""
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID,
        type="test_resume",
        status=JOB_RUNNING,
        payload_json={"items": ["a", "b", "c", "d"]},
        result_json={"processed": ["a", "b"]},
        cursor_json={"index": 2},
    )
    db.add(job)
    db.commit()

    run_job(db, job.id)
    db.refresh(job)
    assert job.status == JOB_DONE
    # Exactly-once per item — no duplicates from the resume.
    assert job.result_json["processed"] == ["a", "b", "c", "d"]


def test_prune_removes_only_old_terminal_jobs(db):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=999)

    old_done = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="test_counting", status=JOB_DONE, finished_at=old
    )
    old_failed = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="test_counting", status=JOB_FAILED, finished_at=old
    )
    old_aborted = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="test_counting", status=JOB_ABORTED, finished_at=old
    )
    recent_done = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="test_counting", status=JOB_DONE, finished_at=now
    )
    running = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="test_counting", status=JOB_RUNNING, started_at=old
    )
    pending = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="test_counting", status=JOB_PENDING
    )
    db.add_all([old_done, old_failed, old_aborted, recent_done, running, pending])
    db.commit()
    ids = {r.id for r in (old_done, old_failed, old_aborted, recent_done, running, pending)}

    deleted = prune_jobs(db, now=now)
    assert deleted == 3  # the three OLD terminal jobs

    survivors = {
        r.id
        for r in db.query(BackgroundJob).filter(BackgroundJob.id.in_(ids)).all()
    }
    assert survivors == {recent_done.id, running.id, pending.id}
