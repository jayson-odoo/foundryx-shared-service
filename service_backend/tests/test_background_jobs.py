"""Centralized background-jobs infra (sprint-4/10 Slice 1) - AC-10-01..03.

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
# Declares a queue override (sprint-5 prod-enablement) - the fixture every
# routing test below dispatches through, mirroring ``meetings.transcribe``.
_QUEUED = JobHandlerDef(
    type="test_queued", handler=_counting_handler, label="Queued", queue="stt"
)


@pytest.fixture(autouse=True)
def _register_handlers():
    _RUN_LOG.clear()
    register_job_handler(_COUNTING)
    register_job_handler(_CRASHING)
    register_job_handler(_RESUME)
    register_job_handler(_QUEUED)
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


def test_queue_for_type_reads_the_registered_override():
    from app.jobs.registry import queue_for_type

    assert queue_for_type("test_queued") == "stt"


def test_queue_for_type_is_none_without_an_override_or_a_registration():
    from app.jobs.registry import queue_for_type

    assert queue_for_type("test_counting") is None  # registered, no override
    assert queue_for_type("no_such_type") is None  # not registered at all


def test_eager_enqueue_runs_inline(db):
    job = JobService(db).create_and_enqueue(type="test_counting", tenant_id=DEFAULT_TENANT_ID)
    db.refresh(job)
    assert job.status == JOB_DONE
    assert job.result_json == {"ran": True}
    assert _RUN_LOG == [job.id]


# ── Queue routing (sprint-5 prod-enablement) ──────────────────────────────────
# ``JobService.enqueue`` normally short-circuits to the eager inline path in
# tests; these force the non-eager (prod-shaped) branch to pin WHERE a job
# gets published, mirroring the "wrong worker looks healthy but never runs the
# job" failure class the ``bots`` queue already guards against.


def test_enqueue_routes_a_queued_type_onto_its_declared_queue(db, monkeypatch):
    """A handler that declares ``queue=`` is dispatched with Celery's routing
    kwarg via ``apply_async``, never the plain default-queue ``.delay``."""
    from app.config import settings
    from app.jobs import worker as worker_module

    monkeypatch.setattr(settings, "celery_task_always_eager", False)
    calls = []
    monkeypatch.setattr(
        worker_module.run_job_task,
        "apply_async",
        lambda args=None, queue=None, **kw: calls.append((args, queue)),
    )
    job = JobService(db).create(type="test_queued", tenant_id=DEFAULT_TENANT_ID)

    JobService(db).enqueue(job.id)

    assert calls == [([job.id], "stt")]


def test_enqueue_uses_plain_delay_for_a_type_with_no_queue_override(db, monkeypatch):
    """A type with no ``queue`` declared keeps riding the worker's default
    queue via plain ``.delay`` - unchanged behavior for every existing type."""
    from app.config import settings
    from app.jobs import worker as worker_module

    monkeypatch.setattr(settings, "celery_task_always_eager", False)
    delayed = []
    monkeypatch.setattr(
        worker_module.run_job_task, "delay", lambda job_id: delayed.append(job_id)
    )
    job = JobService(db).create(type="test_counting", tenant_id=DEFAULT_TENANT_ID)

    JobService(db).enqueue(job.id)

    assert delayed == [job.id]


def test_enqueue_falls_back_to_delay_for_an_unregistered_type(db, monkeypatch):
    """A job row whose type has no registered handler at all - ``create()``
    refuses to persist one, but a stray row (an older type retired from the
    registry, say) must still enqueue rather than crash the caller."""
    from app.config import settings
    from app.jobs import worker as worker_module

    monkeypatch.setattr(settings, "celery_task_always_eager", False)
    delayed = []
    monkeypatch.setattr(
        worker_module.run_job_task, "delay", lambda job_id: delayed.append(job_id)
    )
    job = BackgroundJob(tenant_id=DEFAULT_TENANT_ID, type="no_such_type", status=JOB_PENDING)
    db.add(job)
    db.commit()

    JobService(db).enqueue(job.id)

    assert delayed == [job.id]


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
    # Exactly-once per item - no duplicates from the resume.
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


# ── Worker registration (prod-hang regression) ───────────────────────────────
# The workflow Celery worker (`celery -A app.workflow_engine.worker`) runs no
# FastAPI lifespan, so any task/handler in another package must be imported by
# the worker module itself. When it wasn't, the worker received `jobs.run`,
# found it UNREGISTERED, and DISCARDED the message (KeyError: 'jobs.run') -
# storage migrations hung Pending forever with no error. These pin the wiring so
# the next background-job type added can't silently reintroduce the stall.


def test_workflow_worker_registers_jobs_run_task():
    """The `jobs.run` Celery task must be registered on the workflow worker app,
    else Celery discards the message (silent Pending stall in prod)."""
    import app.workflow_engine.worker as worker

    assert "jobs.run" in worker.celery_app.tasks


def test_workflow_worker_registers_storage_migration_handler():
    """Importing the workflow worker entrypoint must register the
    storage_migration job handler - else `jobs.run` runs but `handler_for`
    raises and the job flips to failed."""
    import importlib

    import app.workflow_engine.worker  # noqa: F401 - triggers cross-package imports

    registry = importlib.import_module("app.jobs.registry")
    handler_def = registry.handler_for("storage_migration")
    assert handler_def.type == "storage_migration"
    assert callable(handler_def.handler)
