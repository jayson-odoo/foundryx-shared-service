"""Plan 45, AC-45-05 - meetings handlers that catch an error themselves fail
the job with a fixed sentence naming the exception class, never its text."""
from __future__ import annotations

import json

from modules.meetings.calendar.base import CalendarSourceError
from tests.meetings_bot_fakes import FakeContainer, FakeDocker, FakeArtifacts, bot_stdout
from tests.test_meetings_bot_runner import (  # noqa: F401 - fixtures re-exported
    _job as _bot_job,
    _prepare,
    _run as _bot_run,
    db,
    local_storage,
    stt_provider_stub,
)
from tests.test_meetings_stt_jobs import (  # noqa: F401 - fixtures re-exported
    _FakeProvider,
    _job as _stt_job,
    _meeting_with_recording,
    _patch_artifacts,
    _patch_provider,
    _run as _stt_run,
    storage,
)

SECRET = "MARKER-CRASH text"


class Marker(RuntimeError):
    pass


def _assert_clean(job) -> None:
    assert job.status == "failed"
    assert "Marker" in (job.error or ""), job.error
    parts = [job.error, job.result_json, job.logs_json, job.payload_json, job.cursor_json]
    assert "MARKER" not in json.dumps(parts, default=str)


# ── meetings.transcribe (jobs.py :426) ───────────────────────────────────────
def test_ac_45_05_transcribe_failure_stores_the_class_name_only(db, storage, monkeypatch):
    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(monkeypatch, {})
    _patch_provider(monkeypatch, _FakeProvider(error=Marker(SECRET)))
    finished = _stt_run(db, _stt_job(db, meeting).id)
    _assert_clean(finished)


# ── meetings.bot_run (bot_runner.py :543, :552, :564, :600) ──────────────────
def test_ac_45_05_bot_prepare_failure_stores_the_class_name_only(db, monkeypatch):
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    monkeypatch.setattr(bot_runner, "docker_client", lambda: FakeDocker(FakeContainer([])))

    def boom(db_, m):
        raise Marker(SECRET)

    monkeypatch.setattr(bot_runner, "build_spec", boom)
    job = _bot_job(db, meeting)
    bot_runner.run_bot(db, job)
    db.refresh(job)
    _assert_clean(job)


def test_ac_45_05_bot_container_start_failure_stores_the_class_name_only(db, monkeypatch):
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    monkeypatch.setattr(
        bot_runner, "docker_client", lambda: FakeDocker(run_error=Marker(SECRET))
    )
    job = _bot_job(db, meeting)
    bot_runner.run_bot(db, job)
    db.refresh(job)
    _assert_clean(job)


def test_ac_45_05_bot_run_failure_stores_the_class_name_only(db, monkeypatch):
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)

    def boom(db_, m, container):
        raise Marker(SECRET)

    monkeypatch.setattr(bot_runner, "follow", boom)
    job, _docker, _container = _bot_run(db, monkeypatch, meeting, lines=[])
    _assert_clean(job)


def test_ac_45_05_bot_recording_store_failure_stores_the_class_name_only(db, monkeypatch):
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)

    def boom(db_, m, artifacts):
        raise Marker(SECRET)

    monkeypatch.setattr(bot_runner, "register_recording", boom)
    job, _docker, _container = _bot_run(
        db, monkeypatch, meeting,
        lines=bot_stdout(reason="room_empty", started_ts=1000.0, finished_ts=2800.0),
        artifacts=FakeArtifacts({"audio_0000.ogg": b"OggS", "events.jsonl": b'{"kind":"joined"}'}),
    )
    _assert_clean(job)


# ── meetings.calendar_sync (jobs.py :126) ────────────────────────────────────
def test_ac_45_05_calendar_sync_source_failure_stores_the_class_name_only(db, monkeypatch):
    from app.jobs.service import JobService
    from app.models import DEFAULT_TENANT_ID
    from app.models.connection import Connection
    from app.secrets import encrypt_secret
    from modules.meetings import jobs as meetings_jobs

    db.add(
        Connection(
            tenant_id=DEFAULT_TENANT_ID, provider=meetings_jobs.GOOGLE_DWD_PROVIDER,
            type="calendar", name="Calendar", config_json={}, is_active=True,
            credentials_json=encrypt_secret({"serviceAccountJson": "{}"}),
        )
    )
    db.commit()

    def boom(config, credentials):
        raise CalendarSourceError(SECRET)

    monkeypatch.setattr(meetings_jobs, "calendar_source_from_connection", boom)
    job = JobService(db).create(type=meetings_jobs.CALENDAR_SYNC, tenant_id=DEFAULT_TENANT_ID)
    meetings_jobs.run_calendar_sync(db, job)
    db.refresh(job)
    assert job.status == "failed"
    assert "CalendarSourceError" in (job.error or ""), job.error
    parts = [job.error, job.result_json, job.logs_json, job.payload_json]
    assert "MARKER" not in json.dumps(parts, default=str)
