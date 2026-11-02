"""Plan 45, AC-45-05 - meetings handlers that catch an error themselves fail
the job with a fixed sentence naming the exception class, never its text."""
from __future__ import annotations

import json

import pytest

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


# ── meetings.calendar_sync (jobs.py :126, fed by google_dwd.py :88 and :133) ──
# Covered by unit tests of the two functions that build the stored text: the
# job handler stores the CalendarSourceError message verbatim, and the only
# foreign text reaches it through these two sites.
def test_ac_45_05_calendar_credentials_failure_message_holds_the_class_name_only(monkeypatch):
    from google.oauth2 import service_account

    from modules.meetings.calendar import google_dwd

    def boom(info, scopes=None):
        raise ValueError(SECRET)

    monkeypatch.setattr(service_account.Credentials, "from_service_account_info", boom)
    with pytest.raises(CalendarSourceError) as err:
        google_dwd._service_account_credentials('{"client_email": "a@example.com"}', [], None)
    assert "MARKER" not in str(err.value)
    assert "ValueError" in str(err.value)


def test_ac_45_05_directory_listing_failure_message_holds_the_class_name_only(monkeypatch):
    from modules.meetings.calendar import google_dwd

    class _Chain:
        def users(self):
            return self

        def list(self, **kw):
            return self

        def execute(self):
            raise Marker(SECRET)

    monkeypatch.setattr(google_dwd, "_service_account_credentials", lambda *a, **k: object())
    monkeypatch.setattr(google_dwd, "_build", lambda *a, **k: _Chain())
    with pytest.raises(CalendarSourceError) as err:
        google_dwd.list_directory_users(
            service_account_json="{}", impersonate_email="admin@example.com", limit=1
        )
    assert "MARKER" not in str(err.value)
    assert "Marker" in str(err.value)
