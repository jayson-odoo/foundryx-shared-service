"""``run_transcribe`` (S3 plan §3.3) - AC-S3-1, AC-S3-3, AC-S3-4, AC-S3-9,
AC-S3-10, R3.

The provider and the artifacts resolution are both faked: what is under test
here is the handler's own wiring (rows written, replace-on-rerun, status
transitions, failure isolation), never mlx or a real container.
"""
import json
from datetime import timedelta

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.meetings.models import (
    STATUS_FAILED,
    STATUS_JOINING,
    STATUS_PROCESSING,
    STATUS_SKIPPED,
    STATUS_TRANSCRIBED,
    Meeting,
    Transcript,
    TranscriptSegment,
)
from modules.meetings.stt import SttResult, SttSegment
from tests.meetings_bot_fakes import FakeArtifacts, RecordingStorage
from tests.meetings_helpers import utc

NOW = utc(2026, 9, 1, 2, 0)
_SEQUENCE = {"n": 0}


@pytest.fixture
def db(meetings_session_factory):
    session = meetings_session_factory()
    yield session
    session.close()


@pytest.fixture
def storage(monkeypatch):
    from modules.meetings import jobs as jobs_module

    recorder = RecordingStorage()
    monkeypatch.setattr(jobs_module, "storage_for_tenant", lambda db, tenant_id: recorder)
    return recorder


def _meeting_with_recording(db, storage, *, tenant_id=DEFAULT_TENANT_ID):
    from app.models.document import File, FileVersion, Folder
    from modules.meetings.services.calendar_sync import dedupe_key

    _SEQUENCE["n"] += 1
    url = f"https://meet.google.com/rec-{_SEQUENCE['n']:04d}"
    meeting = Meeting(
        tenant_id=tenant_id,
        dedupe_key=dedupe_key(url, NOW),
        title="Weekly sync",
        conference_url=url,
        platform="meet",
        starts_at=NOW,
        ends_at=NOW + timedelta(hours=1),
        status=STATUS_JOINING,
    )
    db.add(meeting)
    db.flush()

    folder = (
        db.query(Folder)
        .filter(Folder.tenant_id == tenant_id, Folder.parent_id.is_(None), Folder.name == "Meetings")
        .first()
    )
    if folder is None:
        folder = Folder(tenant_id=tenant_id, parent_id=None, name="Meetings")
        db.add(folder)
        db.flush()

    file = File(tenant_id=tenant_id, folder_id=folder.id, name="rec.ogg", created_by=None)
    db.add(file)
    db.flush()
    version = FileVersion(
        file_id=file.id, ordinal=1, storage_key="", size_bytes=4, mime="audio/ogg"
    )
    db.add(version)
    db.flush()
    version.storage_key = storage.save(f"meetings/{meeting.id}/{version.id}", b"OggS", "audio/ogg")
    file.current_version_id = version.id
    meeting.recording_file_id = file.id
    db.commit()
    return meeting


def _job(db, meeting):
    from app.jobs.service import JobService
    from modules.meetings.jobs import TRANSCRIBE

    return JobService(db).create(
        type=TRANSCRIBE, tenant_id=meeting.tenant_id, payload={"meeting_id": meeting.id}
    )


def _run(db, job_id):
    from app.jobs.service import run_job

    return run_job(db, job_id)


class _FakeProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def transcribe(self, audio_path):
        self.calls.append(audio_path)
        if self.error is not None:
            raise self.error
        return self.result


def _patch_provider(monkeypatch, provider):
    from modules.meetings import jobs as jobs_module

    monkeypatch.setattr(jobs_module, "get_provider", lambda: provider)


def _patch_artifacts(monkeypatch, blobs):
    from modules.meetings.services import bot_runner as bot_runner_module

    artifacts = FakeArtifacts(blobs)
    monkeypatch.setattr(bot_runner_module, "build_output", lambda db, meeting: ({}, {}, artifacts))


def _events(*rows) -> dict:
    raw = ("\n".join(json.dumps(r) for r in rows) + "\n").encode("utf-8")
    return {"events.jsonl": raw}


def _default_result():
    return SttResult(
        language="en",
        segments=[
            SttSegment(start_ms=1000, end_ms=3000, text="hello there", language="en")
        ],
    )


def test_a_successful_run_writes_the_transcript_and_reaches_transcribed(
    db, storage, monkeypatch
):
    """AC-S3-1: one transcripts row + its segments, start_ms < end_ms,
    non-empty text, meeting reaches transcribed."""
    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(
        monkeypatch,
        _events(
            {"ts": 1000.0, "kind": "recording_started"},
            {"ts": 1002.0, "kind": "caption", "speaker": "Alice", "text": "hi"},
        ),
    )
    provider = _FakeProvider(result=_default_result())
    _patch_provider(monkeypatch, provider)

    from app.models.background_job import JOB_DONE

    finished = _run(db, _job(db, meeting).id)

    assert finished.status == JOB_DONE
    assert provider.calls  # the provider actually ran, against a real path

    db.refresh(meeting)
    assert meeting.status == STATUS_TRANSCRIBED
    assert meeting.language == "en"

    transcripts = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).all()
    assert len(transcripts) == 1
    segments = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.transcript_id == transcripts[0].id)
        .all()
    )
    assert len(segments) == 1
    seg = segments[0]
    assert seg.start_ms < seg.end_ms
    assert seg.text == "hello there"
    assert seg.speaker == "Alice"
    # R3 AMENDED: the provider's real per-segment language lands on the row.
    assert seg.language == "en"


def test_a_rerun_leaves_exactly_one_transcript_row(db, storage, monkeypatch):
    """AC-S3-9: re-running on a meeting that already has a transcript leaves
    ONE row - the new one."""
    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(monkeypatch, {})

    _patch_provider(monkeypatch, _FakeProvider(result=_default_result()))
    _run(db, _job(db, meeting).id)
    first_id = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).one().id

    second_result = SttResult(
        language="ms", segments=[SttSegment(start_ms=0, end_ms=500, text="selamat pagi")]
    )
    _patch_provider(monkeypatch, _FakeProvider(result=second_result))
    _run(db, _job(db, meeting).id)

    transcripts = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).all()
    assert len(transcripts) == 1
    assert transcripts[0].id != first_id
    db.refresh(meeting)
    assert meeting.language == "ms"
    segments = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.transcript_id == transcripts[0].id)
        .all()
    )
    assert [s.text for s in segments] == ["selamat pagi"]


def test_captions_absent_still_transcribes_with_null_speakers(db, storage, monkeypatch):
    """AC-S3-3: no events.jsonl at all -> still transcribed, every speaker
    NULL, and the job log says why."""
    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(monkeypatch, {})  # no events.jsonl in the artifacts at all
    _patch_provider(monkeypatch, _FakeProvider(result=_default_result()))

    finished = _run(db, _job(db, meeting).id)

    from app.models.background_job import JOB_DONE

    assert finished.status == JOB_DONE
    db.refresh(meeting)
    assert meeting.status == STATUS_TRANSCRIBED

    transcript = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).one()
    segments = (
        db.query(TranscriptSegment).filter(TranscriptSegment.transcript_id == transcript.id).all()
    )
    assert segments and all(s.speaker is None for s in segments)
    messages = " ".join(entry["message"] for entry in (finished.logs_json or []))
    assert "captions were absent" in messages


def test_empty_caption_events_also_count_as_absent(db, storage, monkeypatch):
    """AC-S3-3: the file exists but carries no ``caption`` rows - same
    NULL-speaker outcome as a missing file."""
    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(monkeypatch, _events({"ts": 1000.0, "kind": "recording_started"}))
    _patch_provider(monkeypatch, _FakeProvider(result=_default_result()))

    _run(db, _job(db, meeting).id)

    db.refresh(meeting)
    assert meeting.status == STATUS_TRANSCRIBED
    transcript = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).one()
    segments = (
        db.query(TranscriptSegment).filter(TranscriptSegment.transcript_id == transcript.id).all()
    )
    assert all(s.speaker is None for s in segments)


def test_a_caption_read_failure_still_writes_the_transcript(db, storage, monkeypatch):
    """S2 (review): captions are read AFTER the provider has already
    succeeded - a caption-READ failure (decrypted-credentials error, an S3
    list error, ...) must not discard a transcription that is otherwise done.
    Proceed with no captions, same as ``events.jsonl`` simply being absent."""
    from modules.meetings.services import bot_runner as bot_runner_module

    meeting = _meeting_with_recording(db, storage)

    def boom(db_, meeting_):
        raise RuntimeError("stored storage credentials are unreadable")

    monkeypatch.setattr(bot_runner_module, "build_output", boom)
    _patch_provider(monkeypatch, _FakeProvider(result=_default_result()))

    from app.models.background_job import JOB_DONE

    finished = _run(db, _job(db, meeting).id)

    assert finished.status == JOB_DONE
    db.refresh(meeting)
    assert meeting.status == STATUS_TRANSCRIBED
    transcript = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).one()
    segments = (
        db.query(TranscriptSegment).filter(TranscriptSegment.transcript_id == transcript.id).all()
    )
    assert segments and all(s.speaker is None for s in segments)
    messages = " ".join(entry["message"] for entry in (finished.logs_json or []))
    assert "captions" in messages


def test_invalid_provider_segments_are_dropped_and_logged(db, storage, monkeypatch):
    """AC-S3-1 must hold for ANY provider, not just ``mlx_runner`` (which
    already only ever emits well-formed segments) - a bad ``start_ms >=
    end_ms`` or empty-text segment from a different driver is dropped rather
    than written as garbage, and the job log says so."""
    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(monkeypatch, {})
    bad_result = SttResult(
        language="en",
        segments=[
            SttSegment(start_ms=0, end_ms=1000, text="hello there"),
            SttSegment(start_ms=2000, end_ms=2000, text="zero-length"),
            SttSegment(start_ms=3000, end_ms=2500, text="backwards"),
            SttSegment(start_ms=4000, end_ms=5000, text="   "),
        ],
    )
    _patch_provider(monkeypatch, _FakeProvider(result=bad_result))

    from app.models.background_job import JOB_DONE

    finished = _run(db, _job(db, meeting).id)

    assert finished.status == JOB_DONE
    db.refresh(meeting)
    assert meeting.status == STATUS_TRANSCRIBED

    transcript = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).one()
    segments = (
        db.query(TranscriptSegment).filter(TranscriptSegment.transcript_id == transcript.id).all()
    )
    assert [s.text for s in segments] == ["hello there"]
    # This provider segment carried no language - the write path tolerates
    # None rather than requiring every provider to set it.
    assert segments[0].language is None
    assert finished.result_json["segments"] == 1
    messages = " ".join(entry["message"] for entry in (finished.logs_json or []))
    assert "invalid" in messages.lower()


def test_a_transcription_failure_marks_the_job_and_the_meeting_failed(db, storage, monkeypatch):
    """AC-S3-4: subprocess-style failure -> job FAILED, meeting failed, error
    logged; fixing the cause and re-running produces a transcript with no
    duplicate rows."""
    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(monkeypatch, {})
    _patch_provider(monkeypatch, _FakeProvider(error=RuntimeError("mlx exited 1: OOM")))

    from app.models.background_job import JOB_FAILED

    finished = _run(db, _job(db, meeting).id)

    assert finished.status == JOB_FAILED
    assert "OOM" in (finished.error or "")
    db.refresh(meeting)
    assert meeting.status == STATUS_FAILED
    assert "OOM" in (meeting.status_reason or "")
    assert db.query(Transcript).filter(Transcript.meeting_id == meeting.id).count() == 0

    # The cause is "fixed" - a re-run now succeeds and leaves one transcript.
    _patch_provider(monkeypatch, _FakeProvider(result=_default_result()))
    second = _run(db, _job(db, meeting).id)

    from app.models.background_job import JOB_DONE

    assert second.status == JOB_DONE
    db.refresh(meeting)
    assert meeting.status == STATUS_TRANSCRIBED
    assert db.query(Transcript).filter(Transcript.meeting_id == meeting.id).count() == 1


def test_a_write_path_failure_still_fails_the_meeting_not_just_the_job(db, storage, monkeypatch):
    """S1 (review): the try only wrapped the READ path (``_transcribe``) - a
    failure while WRITING the transcript (e.g. a unique-violation on
    ``uq_meetings_transcript_meeting`` from a concurrent retry) left the job
    FAILED but the meeting stuck in whatever status it was already in
    (``processing``), forever, since nothing else would ever move it on."""
    meeting = _meeting_with_recording(db, storage)
    meeting.status = STATUS_PROCESSING
    db.commit()
    _patch_artifacts(monkeypatch, {})
    _patch_provider(monkeypatch, _FakeProvider(result=_default_result()))

    real_add = db.add

    def boom(instance):
        if isinstance(instance, Transcript):
            raise RuntimeError(
                'duplicate key value violates unique constraint "uq_meetings_transcript_meeting"'
            )
        return real_add(instance)

    monkeypatch.setattr(db, "add", boom)

    from app.models.background_job import JOB_FAILED

    finished = _run(db, _job(db, meeting).id)

    assert finished.status == JOB_FAILED
    assert "unique constraint" in (finished.error or "")
    db.refresh(meeting)
    assert meeting.status == STATUS_FAILED
    assert "unique constraint" in (meeting.status_reason or "")


def test_the_job_result_carries_provider_wall_clock_timing(db, storage, monkeypatch):
    """S7 (review) / plan 3.3 step 5: ``background_jobs`` result carries
    counts AND timing - measured around the provider call, the one step whose
    wall-clock actually varies run to run."""
    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(monkeypatch, {})

    class _SlowProvider(_FakeProvider):
        def transcribe(self, audio_path):
            import time

            time.sleep(0.01)
            return super().transcribe(audio_path)

    _patch_provider(monkeypatch, _SlowProvider(result=_default_result()))

    finished = _run(db, _job(db, meeting).id)

    assert finished.result_json["transcribeMs"] >= 10


def test_an_unbuilt_provider_fails_loudly_naming_itself(db, storage, monkeypatch):
    """AC-S3-10: a configured-but-unbuilt provider must not silently fall
    back to mlx_local - the error names it."""
    from app.config import settings

    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(monkeypatch, {})
    monkeypatch.setattr(settings, "meetings_stt_provider", "deepgram")

    from app.models.background_job import JOB_FAILED

    finished = _run(db, _job(db, meeting).id)

    assert finished.status == JOB_FAILED
    assert "deepgram" in (finished.error or "")
    db.refresh(meeting)
    assert meeting.status == STATUS_FAILED
    assert "deepgram" in (meeting.status_reason or "")


def test_a_missing_meeting_id_in_the_payload_fails_the_job_loudly(db, storage, monkeypatch):
    """The enqueuer (``bot_runner._enqueue_transcribe``) always sends a real
    ``meeting_id`` - an EMPTY payload is a wiring bug, not a meeting that
    disappeared, and must fail loudly rather than finish as a silent skip
    indistinguishable from the normal "meeting is gone" case."""
    from app.jobs.service import JobService
    from app.models.background_job import JOB_FAILED
    from modules.meetings.jobs import TRANSCRIBE

    job = JobService(db).create(type=TRANSCRIBE, tenant_id=DEFAULT_TENANT_ID, payload={})

    finished = _run(db, job.id)

    assert finished.status == JOB_FAILED
    assert "meeting_id" in (finished.error or "")


def test_a_meeting_id_that_no_longer_exists_is_a_clean_skip(db, storage, monkeypatch):
    """A REAL ``meeting_id`` whose row has since been deleted (not this
    module's business why) is the normal case - a clean skip, not a
    failure."""
    from app.jobs.service import JobService
    from app.models.background_job import JOB_DONE
    from modules.meetings.jobs import TRANSCRIBE

    job = JobService(db).create(
        type=TRANSCRIBE, tenant_id=DEFAULT_TENANT_ID, payload={"meeting_id": "does-not-exist"}
    )

    finished = _run(db, job.id)

    assert finished.status == JOB_DONE
    assert finished.result_json == {"skipped": "meeting is gone"}


def test_a_recording_with_zero_humans_ever_seen_skips_transcription(db, storage, monkeypatch):
    """Fix 2 (review), defense in depth: a recording WAS registered (an older
    bot image, a race, a redelivered job before this fix landed, ...) but
    ``events.jsonl``'s own ``participants`` events show nobody ever joined -
    silent audio only produces a hallucinated transcript ("Thank you" at 30s
    boundaries, live evidence). Skip the same way a bot-level `no_show`
    does, and never even call the provider."""
    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(
        monkeypatch,
        _events(
            {"ts": 1000.0, "kind": "recording_started"},
            {"ts": 1002.0, "kind": "participants", "humans": 0, "tiles": []},
            {"ts": 1050.0, "kind": "participants", "humans": 0, "tiles": []},
        ),
    )
    provider = _FakeProvider(result=_default_result())
    _patch_provider(monkeypatch, provider)

    from app.models.background_job import JOB_DONE

    finished = _run(db, _job(db, meeting).id)

    assert finished.status == JOB_DONE
    assert finished.result_json == {"skipped": "no_show"}
    assert provider.calls == []  # must never run the provider on silence
    db.refresh(meeting)
    assert meeting.status == STATUS_SKIPPED
    assert meeting.status_reason == "no_show"
    assert db.query(Transcript).filter(Transcript.meeting_id == meeting.id).count() == 0


def test_a_run_with_a_human_present_transcribes_normally(db, storage, monkeypatch):
    """The zero-humans robustness check must not false-positive on a normal
    meeting that genuinely had someone in it."""
    meeting = _meeting_with_recording(db, storage)
    _patch_artifacts(
        monkeypatch,
        _events(
            {"ts": 1000.0, "kind": "recording_started"},
            {"ts": 1002.0, "kind": "participants", "humans": 1, "tiles": ["Alice"]},
            {"ts": 1005.0, "kind": "caption", "speaker": "Alice", "text": "hi"},
        ),
    )
    provider = _FakeProvider(result=_default_result())
    _patch_provider(monkeypatch, provider)

    from app.models.background_job import JOB_DONE

    finished = _run(db, _job(db, meeting).id)

    assert finished.status == JOB_DONE
    assert provider.calls  # the provider DID run - a human was present
    db.refresh(meeting)
    assert meeting.status == STATUS_TRANSCRIBED


def test_a_meeting_with_no_recording_is_skipped_not_failed(db, storage, monkeypatch):
    """``bot_run`` (S2) enqueues ``transcribe`` unconditionally, including a
    call that recorded nothing (an empty room) - that is not a failure, there
    is simply nothing to transcribe."""
    from modules.meetings.services.calendar_sync import dedupe_key

    meeting = Meeting(
        tenant_id=DEFAULT_TENANT_ID,
        dedupe_key=dedupe_key("https://meet.google.com/no-rec", NOW),
        title="No recording",
        conference_url="https://meet.google.com/no-rec",
        platform="meet",
        starts_at=NOW,
        ends_at=NOW + timedelta(hours=1),
        status=STATUS_JOINING,
    )
    db.add(meeting)
    db.commit()

    from app.models.background_job import JOB_DONE

    finished = _run(db, _job(db, meeting).id)

    assert finished.status == JOB_DONE
    assert finished.result_json == {"skipped": "meeting has no recording"}
    db.refresh(meeting)
    assert meeting.status == STATUS_JOINING  # untouched
    assert db.query(Transcript).filter(Transcript.meeting_id == meeting.id).count() == 0


# ── queue routing (sprint-5 prod-enablement, AC-STT-Q1) ──────────────────────
# ``run_transcribe`` itself is exercised above; what changes here is WHERE the
# job gets dispatched to, not what it does once it runs.


def test_transcribe_is_registered_on_its_own_stt_queue():
    """The registered handler declares ``stt``, never the default ``workflow``
    queue the compose worker consumes."""
    from app.jobs.registry import queue_for_type
    from modules.meetings.jobs import TRANSCRIBE

    assert queue_for_type(TRANSCRIBE) == "stt"


def test_enqueue_routes_a_transcribe_job_onto_the_stt_queue(db, monkeypatch):
    """Non-eager (prod-shaped) enqueue of a real ``meetings.transcribe`` job
    publishes with Celery's ``queue=`` routing kwarg, never plain ``.delay`` -
    the compose ``workflow`` worker never consumes ``stt``, so landing there
    used to fail every transcribe job instantly instead of waiting for the
    pilot host's dedicated worker."""
    from app.config import settings
    from app.jobs import worker as worker_module
    from app.jobs.service import JobService
    from modules.meetings.jobs import TRANSCRIBE

    monkeypatch.setattr(settings, "celery_task_always_eager", False)
    calls = []
    monkeypatch.setattr(
        worker_module.run_job_task,
        "apply_async",
        lambda args=None, queue=None, **kw: calls.append((args, queue)),
    )
    job = JobService(db).create(
        type=TRANSCRIBE, tenant_id=DEFAULT_TENANT_ID, payload={"meeting_id": "m"}
    )

    JobService(db).enqueue(job.id)

    assert calls == [([job.id], "stt")]


def test_calendar_sync_still_rides_the_default_queue(db, monkeypatch):
    """The OTHER meetings job type keeps using the worker's default queue via
    plain ``.delay`` - only ``transcribe`` moved onto ``stt``."""
    from app.config import settings
    from app.jobs import worker as worker_module
    from app.jobs.service import JobService
    from modules.meetings.jobs import CALENDAR_SYNC

    monkeypatch.setattr(settings, "celery_task_always_eager", False)
    delayed = []
    monkeypatch.setattr(
        worker_module.run_job_task, "delay", lambda job_id: delayed.append(job_id)
    )
    job = JobService(db).create(type=CALENDAR_SYNC, tenant_id=DEFAULT_TENANT_ID)

    JobService(db).enqueue(job.id)

    assert delayed == [job.id]
