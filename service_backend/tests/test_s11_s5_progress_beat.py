"""Sprint-5/11 S5 - AC-11-40, contract 1: ``JobService.beat_progress(job_id,
*, done, total, stage)`` writes ``heartbeat_at``, ``progress_done``,
``progress_total`` and ``cursor_json['stage']`` in ONE UPDATE statement - so
a per-page beat under concurrency (S6) costs exactly what a bare heartbeat
costs today, never a second write.

RED before the coder: ``JobService.beat_progress`` does not exist yet - every
test below fails with an EXPLICIT, named ``pytest.fail``/assertion (never a
bare AttributeError that could be mistaken for a typo in this file), so a
collection run still surfaces every OTHER test in the suite untouched.

Driven directly against ``JobService`` (never through a router) - this is
core `app/jobs/service.py`, the same seam `test_s11_soft_time_limit.py` and
the orphan-sweep suites already use for this module.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event

from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_RUNNING, BackgroundJob


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _running_job(db, **overrides) -> BackgroundJob:
    kwargs = dict(
        tenant_id=DEFAULT_TENANT_ID,
        type="autocount_source_preview",
        status=JOB_RUNNING,
        payload_json={"scope": "full"},
    )
    kwargs.update(overrides)
    job = BackgroundJob(**kwargs)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _require_beat_progress() -> None:
    if not hasattr(JobService, "beat_progress"):
        pytest.fail(
            "JobService.beat_progress does not exist yet (sprint-5/11 S5, "
            "AC-11-40) - the coder has not built the single-UPDATE progress "
            "helper both the pull-snapshot build and the preview job must "
            "share."
        )


class _UpdateStatementCounter:
    """Counts UPDATE statements issued against ``background_jobs`` while
    active - the mechanism for pinning AC-11-40's "the SAME UPDATE as its
    heartbeat ... costs exactly what it costs today" (ONE statement, not a
    bare heartbeat write plus a separate progress write)."""

    def __init__(self, engine):
        self.engine = engine
        self.count = 0

    def _listener(self, conn, cursor, statement, parameters, context, executemany):
        text = statement.lower()
        if "update" in text and "background_jobs" in text:
            self.count += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._listener)
        return self

    def __exit__(self, *exc_info):
        event.remove(self.engine, "before_cursor_execute", self._listener)


def test_beat_progress_writes_heartbeat_done_total_and_stage_in_one_update(db):
    _require_beat_progress()

    job = _running_job(db)
    assert job.heartbeat_at is None

    engine = db.get_bind()
    with _UpdateStatementCounter(engine) as counter:
        JobService(db).beat_progress(job.id, done=3, total=10, stage="source")

    assert counter.count == 1, (
        f"beat_progress issued {counter.count} UPDATE statement(s) against "
        "background_jobs; AC-11-40 requires exactly one (the heartbeat and "
        "the progress write are the SAME UPDATE)."
    )

    db.expire(job)
    db.refresh(job)
    assert job.progress_done == 3
    assert job.progress_total == 10
    assert job.cursor_json == {"stage": "source"}
    assert job.heartbeat_at is not None


def test_beat_progress_total_none_leaves_progress_total_untouched(db):
    _require_beat_progress()

    job = _running_job(db)
    JobService(db).beat_progress(job.id, done=1, total=7, stage="source")
    db.expire(job)
    db.refresh(job)
    assert job.progress_total == 7

    # A later beat in the SAME walk (a page count that is still unknown, or
    # a stage with no page count at all, e.g. "mapping") must never zero out
    # or otherwise disturb a total a previous beat already established.
    JobService(db).beat_progress(job.id, done=2, total=None, stage="combine")
    db.expire(job)
    db.refresh(job)
    assert job.progress_total == 7, "total=None must leave progress_total untouched"
    assert job.progress_done == 2
    assert job.cursor_json == {"stage": "combine"}


def test_beat_progress_preserves_other_cursor_json_keys(db):
    """``cursor_json`` is reassigned as a FRESH dict (the house JSON-column
    gotcha - SQLAlchemy misses in-place mutation), and any OTHER key a
    caller already stored there (a resume cursor, a watermark position)
    must survive a progress beat untouched - never clobbered wholesale."""
    _require_beat_progress()

    job = _running_job(db, cursor_json={"resumeToken": "abc-123"})
    JobService(db).beat_progress(job.id, done=1, total=3, stage="lookup:uom")
    db.expire(job)
    db.refresh(job)
    assert job.cursor_json == {"resumeToken": "abc-123", "stage": "lookup:uom"}


def test_beat_progress_second_call_advances_stage_and_done_independently(db):
    """A realistic multi-beat sequence within one job's life: `done`/`stage`
    move forward beat to beat, and each beat is still exactly one UPDATE."""
    _require_beat_progress()

    job = _running_job(db)
    engine = db.get_bind()

    with _UpdateStatementCounter(engine) as counter:
        JobService(db).beat_progress(job.id, done=1, total=4, stage="source")
    assert counter.count == 1

    with _UpdateStatementCounter(engine) as counter:
        JobService(db).beat_progress(job.id, done=4, total=4, stage="mapping")
    assert counter.count == 1

    db.expire(job)
    db.refresh(job)
    assert job.progress_done == 4
    assert job.progress_total == 4
    assert job.cursor_json == {"stage": "mapping"}
