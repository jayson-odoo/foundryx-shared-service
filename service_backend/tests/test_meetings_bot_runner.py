"""One container per meeting - AC-S2-5, AC-S2-6, AC-S2-7, AC-S2-8, AC-S2-10,
AC-S2-13, AC-S2-14.

No Docker daemon is involved. The runner's three jobs are shaping a container
spec from ONE tenant's rows, turning a stream of `[event]` lines into meeting
status, and turning an exit into a final status - and a fake daemon exercises all
three exactly as a real one would, including the cases a real one would make
expensive to reach (a denied join, a crash, a shutdown mid-call).
"""
import signal
from datetime import timedelta

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.meetings.models import (
    STATUS_FAILED,
    STATUS_JOINING,
    STATUS_NOT_ADMITTED,
    STATUS_PROCESSING,
    STATUS_RECORDING,
    STATUS_SKIPPED,
    STATUS_TRANSCRIBED,
    Meeting,
    MeetingParticipant,
)
from tests.conftest import ACTIVE_EMAIL
from tests.meetings_bot_fakes import (
    FakeArtifacts,
    FakeContainer,
    FakeDocker,
    RecordingStorage,
    bot_stdout,
    event_line,
)
from tests.meetings_helpers import make_admin_user, make_tenant, opt_in, utc

OTHER_TENANT_ID = "88888888-8888-8888-8888-888888888888"
MEET_URL = "https://meet.google.com/abc-defg-hij"
NOW = utc(2026, 9, 1, 2, 0)

def _opus_segment(seconds: float = 0.4) -> bytes:
    """A REAL opus/ogg segment, made with the same ffmpeg the worker uses.

    Fabricated bytes would pass an assertion and fail the only thing that
    matters here: ffmpeg really concatenating two of these into one playable
    file. Cheap enough to build per module load."""
    import subprocess
    import tempfile
    from pathlib import Path

    from modules.meetings.services.recordings import ffmpeg_exe

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "seg.ogg"
        subprocess.run(
            [
                ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                "-t", str(seconds), "-c:a", "libopus", "-b:a", "48k", str(out),
            ],
            check=True,
            capture_output=True,
        )
        return out.read_bytes()


OGG = _opus_segment()


@pytest.fixture
def db(meetings_session_factory):
    session = meetings_session_factory()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def local_storage(monkeypatch):
    """Every recording lands in an in-memory store, never a bucket or a disk.

    A finished call enqueues ``meetings.transcribe`` (S3) synchronously
    (eager jobs in tests), which re-downloads the SAME recording through its
    own ``storage_for_tenant`` import - so the fake has to cover that module
    too, not just where the recording was written."""
    from app.services import storage as storage_module

    recorder = RecordingStorage()
    monkeypatch.setattr(
        storage_module, "storage_for_tenant", lambda db, tenant_id: recorder
    )
    from modules.meetings.services import recordings as recordings_module

    monkeypatch.setattr(
        recordings_module, "storage_for_tenant", lambda db, tenant_id: recorder
    )
    from modules.meetings import jobs as jobs_module

    monkeypatch.setattr(jobs_module, "storage_for_tenant", lambda db, tenant_id: recorder)
    return recorder


@pytest.fixture(autouse=True)
def stt_provider_stub(monkeypatch):
    """None of THIS suite is about transcription content - a trivial provider
    lets the S3 job that S2's bot_run always enqueues finish cleanly, same as
    it always has, without every S2 test needing its own STT setup."""
    from modules.meetings import jobs as jobs_module
    from modules.meetings.stt import SttResult

    class _TrivialProvider:
        def transcribe(self, audio_path):
            return SttResult(language=None, segments=[])

    monkeypatch.setattr(jobs_module, "get_provider", lambda: _TrivialProvider())


def _demo_user(session):
    from app.models import User

    return session.query(User).filter(User.email == ACTIVE_EMAIL).one()


def _bot_connection(db, tenant_id=DEFAULT_TENANT_ID, *, email="notetaker@example.com"):
    from app.models.connection import Connection
    from app.secrets import encrypt_secret

    # One active connection per (tenant, provider) - reuse it across meetings.
    existing = (
        db.query(Connection)
        .filter(Connection.tenant_id == tenant_id, Connection.provider == "meet_bot")
        .first()
    )
    if existing is not None:
        return existing
    row = Connection(
        tenant_id=tenant_id,
        provider="meet_bot",
        type="meeting_bot",
        name="Notetaker",
        config_json={"email": email},
        credentials_json=encrypt_secret({"password": f"pw-for-{tenant_id}"}),
    )
    db.add(row)
    db.flush()
    return row


def _meeting(db, *, tenant_id=DEFAULT_TENANT_ID, url=MEET_URL, title="Weekly product sync"):
    from modules.meetings.services.calendar_sync import dedupe_key

    starts_at = NOW
    row = Meeting(
        tenant_id=tenant_id,
        dedupe_key=dedupe_key(url, starts_at),
        title=title,
        conference_url=url,
        platform="meet",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        status=STATUS_JOINING,
    )
    db.add(row)
    db.flush()
    return row


def _prepare(db, *, tenant_id=DEFAULT_TENANT_ID, user=None, url=MEET_URL):
    """A tenant with a notetaker account and a meeting ready to be joined."""
    user = user or _demo_user(db)
    opt_in(db, tenant_id, user.id)
    _bot_connection(db, tenant_id, email=f"notetaker@{tenant_id[:4]}.example")
    meeting = _meeting(db, tenant_id=tenant_id, url=url)
    db.add(
        MeetingParticipant(
            tenant_id=tenant_id,
            meeting_id=meeting.id,
            email=user.email,
            display_name=user.name,
            user_id=user.id,
            is_opted_in=True,
        )
    )
    db.commit()
    return meeting


def _job(db, meeting, *, late=False):
    from app.jobs.service import JobService
    from modules.meetings.jobs import BOT_RUN

    return JobService(db).create(
        type=BOT_RUN,
        tenant_id=meeting.tenant_id,
        payload={"meeting_id": meeting.id, "tenant_id": meeting.tenant_id, "late": late},
    )


def _run(db, monkeypatch, meeting, *, lines, exit_code=0, artifacts=None, late=False):
    from modules.meetings.services import bot_runner

    container = FakeContainer(lines, exit_code=exit_code)
    docker = FakeDocker(container)
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)
    if artifacts is not None:
        real_build = bot_runner.build_spec
        monkeypatch.setattr(
            bot_runner,
            "build_spec",
            lambda db_, m: (real_build(db_, m)[0], artifacts),
        )
    job = _job(db, meeting, late=late)
    bot_runner.run_bot(db, job)
    db.refresh(meeting)
    db.refresh(job)
    return job, docker, container


# ── AC-S2-5 / AC-S2-13: the spec is built from ONE tenant's rows ─────────────


def test_the_container_carries_this_tenants_credentials_and_volume(db):
    from modules.meetings.services.bot_runner import build_spec

    meeting = _prepare(db)
    spec, _artifacts = build_spec(db, meeting)

    assert spec.image == "foundryx-shared-service:bot-spike"
    assert spec.name == f"meetings-bot-{meeting.id}"
    assert spec.command == ["--meet-url", MEET_URL]
    assert spec.environment["BOT_EMAIL"] == f"notetaker@{DEFAULT_TENANT_ID[:4]}.example"
    assert spec.environment["BOT_PASSWORD"] == f"pw-for-{DEFAULT_TENANT_ID}"
    assert spec.environment["BOT_HEADLESS"] == "1"
    assert spec.environment["BOT_FOR_USER"]
    # One profile volume per TENANT - the signed-in Chromium profile IS that
    # tenant's credential in cookie form.
    assert f"meetings-profile-{DEFAULT_TENANT_ID}" in spec.volumes
    # Logs and exit code are the only record of the run; they die with the
    # container, so it must never auto-remove.
    assert spec.as_kwargs()["auto_remove"] is False
    assert spec.as_kwargs()["shm_size"] == "1g"


def test_the_display_name_and_consent_come_from_the_tenants_settings(db):
    from modules.meetings.services.bot_runner import build_spec
    from modules.meetings.services.settings import MeetingsSettingsService

    meeting = _prepare(db)
    settings_row = MeetingsSettingsService(db).get(DEFAULT_TENANT_ID)
    settings_row.bot_display_name = "Acme Notetaker"
    settings_row.consent_message = "This call is being summarised."
    db.commit()

    spec, _ = build_spec(db, meeting)

    assert spec.environment["BOT_DISPLAY_NAME"] == "Acme Notetaker"
    assert spec.environment["BOT_CONSENT_TEXT"] == "This call is being summarised."


def test_two_tenants_meeting_at_once_share_nothing_but_the_image(db):
    """AC-S2-13: the whole isolation claim, asserted as a spec diff."""
    from app.services.app_store_service import AppStoreService
    from modules.meetings.services.bot_runner import build_spec

    a_meeting = _prepare(db)

    make_tenant(db, OTHER_TENANT_ID, "Other Co")
    AppStoreService(db).install(OTHER_TENANT_ID, "meetings")
    other_user = make_admin_user(db, OTHER_TENANT_ID, "other@example.com", name="Other")
    b_meeting = _prepare(
        db,
        tenant_id=OTHER_TENANT_ID,
        user=other_user,
        url="https://meet.google.com/zzz-yyyy-xxx",
    )

    a_spec, _ = build_spec(db, a_meeting)
    b_spec, _ = build_spec(db, b_meeting)

    a_values = " ".join(list(a_spec.environment.values()) + list(a_spec.volumes))
    b_values = " ".join(list(b_spec.environment.values()) + list(b_spec.volumes))

    assert f"pw-for-{OTHER_TENANT_ID}" not in a_values
    assert f"pw-for-{DEFAULT_TENANT_ID}" not in b_values
    assert OTHER_TENANT_ID not in a_values
    assert DEFAULT_TENANT_ID not in b_values
    assert a_spec.image == b_spec.image


def test_a_tenant_with_no_notetaker_account_fails_loudly_without_a_container(db, monkeypatch):
    """Starting a bot that cannot sign in burns the meeting and reports a
    reason nobody can act on."""
    from modules.meetings.services import bot_runner

    meeting = _meeting(db)
    db.commit()
    docker = FakeDocker(FakeContainer([]))
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)

    job = _job(db, meeting)
    bot_runner.run_bot(db, job)

    db.refresh(meeting)
    assert docker.containers.runs == []
    assert meeting.status == STATUS_FAILED
    assert "notetaker account" in (meeting.status_reason or "")


# ── AC-S2-5: events move the meeting on while the call runs ──────────────────


def test_the_status_follows_the_bots_events(db, monkeypatch):
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    seen = []
    original = bot_runner._set_status

    def spy(db_, m, status):
        seen.append(status)
        original(db_, m, status)

    monkeypatch.setattr(bot_runner, "_set_status", spy)
    _run(
        db,
        monkeypatch,
        meeting,
        lines=bot_stdout(lobby=True, reason="room_empty"),
        artifacts=FakeArtifacts({"audio_0000.ogg": OGG}),
    )

    assert seen[:2] == ["in_lobby", STATUS_RECORDING]


def test_an_event_line_is_parsed_into_its_kind_and_payload():
    from modules.meetings.services.bot_runner import parse_event

    assert parse_event(event_line("joined", lobby=True)) == ("joined", {"lobby": True})
    assert parse_event("[event] captions_on") == ("captions_on", {})
    # The bot's final bare reason line is not an event.
    assert parse_event("room_empty") is None
    # Malformed JSON must not take the run down with it.
    assert parse_event("[event] finished {broken") is None


# ── AC-S2-6: a finished call becomes one file ────────────────────────────────


def test_a_finished_call_registers_one_recording_and_queues_transcription(db, monkeypatch, local_storage):
    from app.models.document import File, FileVersion, Folder
    from app.models.background_job import BackgroundJob
    from modules.meetings.jobs import TRANSCRIBE

    meeting = _prepare(db)
    artifacts = FakeArtifacts(
        {
            "audio_0000.ogg": OGG,
            "audio_0001.ogg": OGG,
            "events.jsonl": b'{"kind":"joined"}',
        }
    )
    job, _docker, _container = _run(
        db,
        monkeypatch,
        meeting,
        lines=bot_stdout(reason="room_empty", started_ts=1000.0, finished_ts=2800.0),
        artifacts=artifacts,
    )

    # S2 hands off to S3 (transcribe), which reaches `transcribed` (R2/R7/R8) -
    # `ready` stays reserved for minutes (S4).
    assert meeting.status == STATUS_TRANSCRIBED
    assert meeting.duration_s == 1800
    assert meeting.recording_file_id is not None

    file = db.query(File).filter(File.id == meeting.recording_file_id).one()
    folder = db.query(Folder).filter(Folder.id == file.folder_id).one()
    assert folder.name == "Meetings"
    assert file.name == "Weekly product sync 2026-09-01 0200.ogg"
    version = db.query(FileVersion).filter(FileVersion.file_id == file.id).one()
    assert version.mime == "audio/ogg"
    assert version.ordinal == 1
    assert version.storage_key in local_storage.saved

    # The segments are gone; events.jsonl stays for S3.
    assert artifacts.deleted == ["audio_0000.ogg", "audio_0001.ogg"]
    assert "events.jsonl" in artifacts.blobs

    assert job.status == "done"
    queued = (
        db.query(BackgroundJob).filter(BackgroundJob.type == TRANSCRIBE).all()
    )
    assert len(queued) == 1
    assert queued[0].payload_json["meeting_id"] == meeting.id


def test_every_normal_exit_word_counts_as_a_finished_call(db, monkeypatch):
    for reason in ("room_empty", "removed", "ended", "max_duration"):
        meeting = _prepare(db, url=f"https://meet.google.com/aaa-bbbb-{reason[:3]}")
        _run(
            db,
            monkeypatch,
            meeting,
            lines=bot_stdout(reason=reason),
            artifacts=FakeArtifacts({"audio_0000.ogg": OGG}),
        )
        assert meeting.status == STATUS_TRANSCRIBED, reason
        db.query(Meeting).filter(Meeting.id == meeting.id).delete()
        db.commit()


def test_a_call_that_recorded_nothing_still_finishes_without_a_file(db, monkeypatch):
    """A meeting where the mic produced no segment is not a failure - there is
    simply nothing to register, and inventing an empty file would be worse."""
    meeting = _prepare(db)
    _run(
        db,
        monkeypatch,
        meeting,
        lines=bot_stdout(reason="room_empty", segments=0),
        artifacts=FakeArtifacts({"events.jsonl": b"{}"}),
    )

    assert meeting.recording_file_id is None
    # bot_run still enqueues transcribe (unconditionally); with nothing to
    # transcribe, S3 skips cleanly and leaves the status bot_run itself set.
    assert meeting.status == STATUS_PROCESSING


# ── AC-S2-7: not admitted ────────────────────────────────────────────────────


def test_a_denied_join_is_not_admitted_with_the_reason_and_no_files(db, monkeypatch):
    from app.models.document import File

    meeting = _prepare(db)
    artifacts = FakeArtifacts({"last.png": b"\x89PNG"})
    job, _docker, _container = _run(
        db,
        monkeypatch,
        meeting,
        lines=[event_line("denied", stage="landing"), event_line("finished", reason="denied", segments=0), "denied"],
        artifacts=artifacts,
    )

    assert meeting.status == STATUS_NOT_ADMITTED
    assert meeting.status_reason == "denied"
    assert meeting.recording_file_id is None
    assert db.query(File).count() == 0
    assert job.status == "done"


def test_a_lobby_timeout_is_not_admitted_too(db, monkeypatch):
    meeting = _prepare(db)
    _run(
        db,
        monkeypatch,
        meeting,
        lines=[
            event_line("in_lobby"),
            event_line("not_admitted", waited_s=180),
            event_line("finished", reason="not_admitted", segments=0),
            "not_admitted",
        ],
        artifacts=FakeArtifacts({}),
    )

    assert meeting.status == STATUS_NOT_ADMITTED
    assert meeting.status_reason == "not_admitted"


# ── S2 live-run fix: a late host must not be recorded as an empty room ───────


def test_a_no_show_is_skipped_with_no_recording_and_never_transcribed(db, monkeypatch):
    """Live evidence: the bot joined alone, its old empty-room grace fired at
    +2min - exactly when the late host arrived - and it registered ~123s of
    silent audio that hallucinated a transcript. The container now leaves
    `no_show` only after BOT_NO_SHOW_TIMEOUT_S with zero humans EVER seen;
    the orchestrator must not register that audio or enqueue transcription
    for it - silence only produces a hallucinated transcript."""
    from app.models.document import File

    meeting = _prepare(db)
    artifacts = FakeArtifacts({"audio_0000.ogg": OGG, "events.jsonl": b"{}"})
    job, _docker, _container = _run(
        db,
        monkeypatch,
        meeting,
        lines=[
            event_line("joined", lobby=False),
            event_line("recording_started", ts=1_000.0),
            event_line("participants", humans=0, tiles=[]),
            event_line("finished", reason="no_show", segments=1),
            "no_show",
        ],
        artifacts=artifacts,
    )

    assert meeting.status == STATUS_SKIPPED
    assert meeting.status_reason == "no_show"
    assert meeting.recording_file_id is None
    assert db.query(File).count() == 0
    assert job.status == "done"


# ── AC-S2-8: a crash ─────────────────────────────────────────────────────────


def test_a_non_zero_exit_fails_the_meeting_and_keeps_the_screenshot(db, monkeypatch):
    meeting = _prepare(db)
    artifacts = FakeArtifacts({"last.png": b"\x89PNG", "events.jsonl": b"{}"}, prefix="t/m")
    job, _docker, _container = _run(
        db,
        monkeypatch,
        meeting,
        lines=[
            event_line("finished", reason="error:TimeoutError:waiting for join button", segments=0),
            "error:TimeoutError:waiting for join button",
        ],
        exit_code=1,
        artifacts=artifacts,
    )

    assert meeting.status == STATUS_FAILED
    assert "TimeoutError" in (meeting.status_reason or "")
    assert meeting.screenshot_key == "t/m/last.png"
    assert job.status == "failed"
    assert job.result_json["screenshotKey"] == "t/m/last.png"


def test_a_failed_run_is_never_retried(db, monkeypatch):
    """A meeting happens once. Re-joining later would join an empty room and
    report a successful capture of nothing."""
    from app.models.background_job import BackgroundJob
    from modules.meetings.jobs import BOT_RUN

    meeting = _prepare(db)
    _run(
        db,
        monkeypatch,
        meeting,
        lines=[event_line("finished", reason="error:boom", segments=0), "error:boom"],
        exit_code=1,
        artifacts=FakeArtifacts({}),
    )

    assert (
        db.query(BackgroundJob).filter(BackgroundJob.type == BOT_RUN).count() == 1
    )


def test_a_container_that_cannot_start_is_a_failed_meeting_not_a_crash(db, monkeypatch):
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    docker = FakeDocker(run_error=RuntimeError("No such image: bot-spike"))
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)

    job = _job(db, meeting)
    bot_runner.run_bot(db, job)

    db.refresh(meeting)
    db.refresh(job)
    assert meeting.status == STATUS_FAILED
    assert "No such image" in (meeting.status_reason or "")
    assert job.status == "failed"


# ── AC-S2-10: shutdown ───────────────────────────────────────────────────────


def test_sigterm_stops_the_container_the_polite_way_and_lets_celery_shut_down():
    from modules.meetings.services.bot_runner import (
        STOP_TIMEOUT_SECONDS,
        graceful_stop_on_sigterm,
    )

    container = FakeContainer([])
    delegated = []
    previous_handler = lambda *a: delegated.append(a)  # noqa: E731 - identity matters
    previous = signal.signal(signal.SIGTERM, previous_handler)
    try:
        with graceful_stop_on_sigterm(container):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        # The handler is put back EXACTLY, so a later shutdown is Celery's alone.
        assert signal.getsignal(signal.SIGTERM) is previous_handler
    finally:
        signal.signal(signal.SIGTERM, previous)

    # `docker stop` sends the container ITS OWN sigterm, which the bot handles
    # by leaving the call and flushing its tail - segments so far survive.
    assert container.stopped_with == STOP_TIMEOUT_SECONDS
    assert len(delegated) == 1


# ── AC-S2-12 half: a run is what verifies the notetaker account ──────────────


def test_a_run_that_reached_meet_marks_the_notetaker_connection_active(db, monkeypatch):
    """S0 refused to claim the account works without evidence. This is it."""
    from app.models.connection import CONNECTION_STATUS_UNVERIFIED, Connection

    meeting = _prepare(db)
    connection = (
        db.query(Connection).filter(Connection.provider == "meet_bot").one()
    )
    assert connection.status == CONNECTION_STATUS_UNVERIFIED

    _run(
        db,
        monkeypatch,
        meeting,
        lines=bot_stdout(reason="room_empty"),
        artifacts=FakeArtifacts({"audio_0000.ogg": OGG}),
    )

    db.refresh(connection)
    assert connection.status == "ACTIVE"
    assert connection.last_tested_at is not None


# ── AC-S2-14: the worker refuses to look healthy when it is not ──────────────


def test_the_worker_refuses_to_boot_on_the_wrong_queue():
    from modules.meetings.worker import WorkerBootError, check_worker_boot

    with pytest.raises(WorkerBootError) as excinfo:
        check_worker_boot(["workflow"], client_factory=lambda: FakeDocker())
    assert "bots" in str(excinfo.value)

    with pytest.raises(WorkerBootError):
        check_worker_boot([], client_factory=lambda: FakeDocker())

    # Consuming bots AND something else is just as wrong: the extra queue's
    # tasks are unregistered here and get discarded.
    with pytest.raises(WorkerBootError):
        check_worker_boot(["bots", "workflow"], client_factory=lambda: FakeDocker())


def test_the_worker_refuses_to_boot_without_docker():
    from modules.meetings.worker import WorkerBootError, check_worker_boot

    def unreachable():
        return FakeDocker(info_error=RuntimeError("permission denied on /var/run/docker.sock"))

    with pytest.raises(WorkerBootError) as excinfo:
        check_worker_boot(["bots"], client_factory=unreachable)
    assert "permission denied" in str(excinfo.value)
    assert "DOCKER_HOST" in str(excinfo.value)


def test_the_worker_boots_when_the_queue_and_the_socket_are_both_right():
    from modules.meetings.worker import check_worker_boot

    check_worker_boot(["bots"], client_factory=lambda: FakeDocker())


def test_the_bots_worker_consumes_only_its_own_queue():
    """Three Celery apps share one Redis; without per-app queues their tasks
    cross over and get discarded as unregistered."""
    from modules.meetings.worker import BOTS_QUEUE, celery_app

    assert celery_app.conf.task_default_queue == BOTS_QUEUE
    # One bot per slot for the whole meeting: prefetching a second job a slot
    # cannot start for an hour hides it from an idle sibling worker.
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_the_boot_check_runs_as_a_bootstep_not_a_signal():
    """AC-S2-14's teeth. Celery CATCHES whatever a signal receiver raises, logs
    it and carries on ("send and send_robust do the same thing"), so a
    `worker_init` handler cannot stop a worker - it would sit there consuming
    the wrong queue with an error two screens up the log, which is exactly the
    silent idle worker this AC forbids. Verified live: the first cut used the
    signal and booted happily on `-Q workflow`; as a bootstep the same worker
    exits 1 with the message. A bootstep raising propagates out of the worker's
    own constructor."""
    from celery.signals import worker_init

    from modules.meetings.worker import BootChecks, celery_app

    assert BootChecks in celery_app.steps["worker"]
    assert not [
        r for r in worker_init.receivers if "meetings" in repr(r)
    ], "the boot check must not be a signal handler - celery swallows those"


# ── review round: failures that must not strand a meeting in `joining` ───────


def test_any_setup_failure_marks_the_meeting_failed_not_just_a_known_one(db, monkeypatch):
    """A meeting only leaves `scheduled` once, so anything that escapes here
    strands it in `joining` FOREVER - dispatch never looks at it again and no
    human ever sees why. `BotRunError` was only the failure we thought of; a
    storage connection whose credentials no longer decrypt raises `InvalidToken`
    from a completely different layer."""
    from cryptography.fernet import InvalidToken

    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    docker = FakeDocker(FakeContainer([]))
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)

    def boom(db_, m):
        raise InvalidToken("stored storage credentials are unreadable")

    monkeypatch.setattr(bot_runner, "build_output", boom)

    job = _job(db, meeting)
    bot_runner.run_bot(db, job)

    db.refresh(meeting)
    db.refresh(job)
    assert docker.containers.runs == []
    assert meeting.status == STATUS_FAILED
    assert meeting.status != STATUS_JOINING
    assert "could not be prepared" in (meeting.status_reason or "")
    assert job.status == "failed"


# ── review round: a redelivered task must not kill a live container ──────────


def test_a_redelivered_task_reattaches_to_the_container_already_running(db, monkeypatch):
    """``task_acks_late`` plus a fixed container name is a live hazard: kill the
    worker mid-meeting and Celery redelivers the job while the container is
    STILL RECORDING. Calling ``containers.run`` again hits Docker's name
    conflict, and the old code turned that into `failed` on a meeting that was
    going perfectly well. Re-attach instead."""
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    existing = FakeContainer(bot_stdout(reason="room_empty"), exit_code=0)
    docker = FakeDocker(FakeContainer([]))
    docker.existing[f"meetings-bot-{meeting.id}"] = existing
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)
    real_build = bot_runner.build_spec
    artifacts = FakeArtifacts({"audio_0000.ogg": OGG})
    monkeypatch.setattr(
        bot_runner, "build_spec", lambda db_, m: (real_build(db_, m)[0], artifacts)
    )

    job = _job(db, meeting)
    bot_runner.run_bot(db, job)
    db.refresh(meeting)

    # It attached to the running container and never tried to start a second.
    assert docker.containers.runs == []
    assert existing.waited is True
    assert meeting.status == STATUS_TRANSCRIBED


def test_a_first_delivery_still_starts_a_container(db, monkeypatch):
    """The other branch: nothing of that name exists, so one is started."""
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    _run(
        db,
        monkeypatch,
        meeting,
        lines=bot_stdout(reason="room_empty"),
        artifacts=FakeArtifacts({"audio_0000.ogg": OGG}),
    )

    assert meeting.status == STATUS_TRANSCRIBED


def test_a_running_container_is_reattached_never_removed(db, monkeypatch):
    """The re-attach path exists to survive a worker restart mid-meeting - a
    RUNNING container must never be torn down."""
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    existing = FakeContainer(bot_stdout(reason="room_empty"), exit_code=0, status="running")
    docker = FakeDocker(FakeContainer([]))
    docker.existing[f"meetings-bot-{meeting.id}"] = existing
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)
    real_build = bot_runner.build_spec
    artifacts = FakeArtifacts({"audio_0000.ogg": OGG})
    monkeypatch.setattr(
        bot_runner, "build_spec", lambda db_, m: (real_build(db_, m)[0], artifacts)
    )

    job = _job(db, meeting)
    bot_runner.run_bot(db, job)
    db.refresh(meeting)

    assert existing.removed_with_force is None
    assert docker.containers.runs == []
    assert meeting.status == STATUS_TRANSCRIBED


def test_a_created_but_not_yet_started_container_is_reattached_not_removed(db, monkeypatch):
    """Between ``create()`` and ``start()`` a container is briefly `created`,
    not `running` - a redelivered task landing in that gap must not treat it
    as a corpse (S6: only `exited`/`dead` are removed) and tear it down out
    from under the real start."""
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    existing = FakeContainer(bot_stdout(reason="room_empty"), exit_code=0, status="created")
    docker = FakeDocker(FakeContainer([]))
    docker.existing[f"meetings-bot-{meeting.id}"] = existing
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)
    real_build = bot_runner.build_spec
    artifacts = FakeArtifacts({"audio_0000.ogg": OGG})
    monkeypatch.setattr(
        bot_runner, "build_spec", lambda db_, m: (real_build(db_, m)[0], artifacts)
    )

    job = _job(db, meeting)
    bot_runner.run_bot(db, job)
    db.refresh(meeting)

    assert existing.removed_with_force is None
    assert docker.containers.runs == []
    assert meeting.status == STATUS_TRANSCRIBED


# ── S2 live-run fix: an exited corpse is removed, not re-adopted ─────────────


def test_an_exited_container_is_removed_and_a_fresh_one_starts(db, monkeypatch):
    """A failed run leaves its exited container behind (``auto_remove=False``,
    wanted for logs). Re-attaching to it here would mark the meeting failed
    again in ~0.1s, and the fixed container name then blocks every retry with
    a name conflict forever. The dead container must be removed so a fresh one
    can be started in the SAME run."""
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    dead = FakeContainer([], exit_code=1, status="exited")
    fresh = FakeContainer(bot_stdout(reason="room_empty"), exit_code=0)
    docker = FakeDocker(fresh)
    docker.existing[f"meetings-bot-{meeting.id}"] = dead
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)
    real_build = bot_runner.build_spec
    artifacts = FakeArtifacts({"audio_0000.ogg": OGG})
    monkeypatch.setattr(
        bot_runner, "build_spec", lambda db_, m: (real_build(db_, m)[0], artifacts)
    )

    job = _job(db, meeting)
    bot_runner.run_bot(db, job)
    db.refresh(meeting)
    db.refresh(job)

    assert dead.removed_with_force is True
    # One helper run for the stale profile lock, one for the fresh bot.
    assert len(docker.containers.runs) == 2
    assert meeting.status == STATUS_TRANSCRIBED
    assert job.status == "done"


def test_a_container_removal_failure_fails_the_run_not_a_silent_skip(db, monkeypatch):
    """A dead container that cannot even be removed must not be quietly
    ignored - the meeting fails with the docker error, and nothing is
    started."""
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    dead = FakeContainer(
        [], exit_code=1, status="exited", remove_error=RuntimeError("container is locked")
    )
    docker = FakeDocker(FakeContainer([]))
    docker.existing[f"meetings-bot-{meeting.id}"] = dead
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)

    job = _job(db, meeting)
    bot_runner.run_bot(db, job)

    db.refresh(meeting)
    db.refresh(job)
    assert meeting.status == STATUS_FAILED
    assert "container is locked" in (meeting.status_reason or "")
    assert "could not be removed" in (meeting.status_reason or "")
    assert docker.containers.runs == []
    assert job.status == "failed"


# ── S2 live-run fix: a stale Chromium profile lock is cleared before a start ─


def test_a_stale_profile_lock_is_cleared_before_the_container_starts(db, monkeypatch):
    """The S1 spike's run.sh always did ``rm -f $PROFILE/Singleton*`` before a
    join; the orchestrator never did. Left behind by an interactive re-login
    on the same profile volume, those files make the next bot's Chromium exit
    immediately ("profile appears to be in use by another Chromium process ...
    on another computer")."""
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    job, docker, container = _run(
        db,
        monkeypatch,
        meeting,
        lines=bot_stdout(reason="room_empty"),
        artifacts=FakeArtifacts({"audio_0000.ogg": OGG}),
    )

    assert len(docker.containers.runs) == 2
    cleanup_kwargs, run_kwargs = docker.containers.runs
    assert cleanup_kwargs["entrypoint"] == [
        "sh",
        "-c",
        "rm -f /profile/Singleton* 2>/dev/null || true",
    ]
    assert cleanup_kwargs["remove"] is True
    profile_volume = f"meetings-profile-{DEFAULT_TENANT_ID}"
    # Targets exactly the tenant's profile volume - nothing else in it.
    assert cleanup_kwargs["volumes"] == {profile_volume: {"bind": "/profile", "mode": "rw"}}
    assert run_kwargs["volumes"][profile_volume] == {"bind": "/profile", "mode": "rw"}


def test_a_profile_lock_cleanup_failure_fails_the_run_not_a_silent_skip(db, monkeypatch):
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    docker = FakeDocker(FakeContainer([]), run_error=RuntimeError("permission denied"))
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)

    job = _job(db, meeting)
    bot_runner.run_bot(db, job)

    db.refresh(meeting)
    db.refresh(job)
    assert meeting.status == STATUS_FAILED
    assert "permission denied" in (meeting.status_reason or "")
    assert "profile lock" in (meeting.status_reason or "")
    assert job.status == "failed"


def test_a_live_sibling_on_the_tenant_profile_volume_skips_the_lock_cleanup(db, monkeypatch):
    """B1: the profile volume is per TENANT, not per meeting - a `-c 2` worker
    can have two overlapping meetings on the same tenant sharing ONE volume.
    Clearing Singleton* here while a SIBLING meeting's Chromium is still using
    it would let two Chromiums share one profile mid-call and corrupt the
    signed-in notetaker session - the tenant's credential. Skip the cleanup
    and let Chromium's own lock stand (the OLD failure mode, and the safe
    one) instead of failing or corrupting the session."""
    from modules.meetings.services import bot_runner

    meeting = _prepare(db)
    fresh = FakeContainer(bot_stdout(reason="room_empty"), exit_code=0)
    docker = FakeDocker(fresh)
    volume = f"meetings-profile-{DEFAULT_TENANT_ID}"
    docker.containers.by_volume[volume] = [FakeContainer([], name="meetings-bot-sibling")]
    monkeypatch.setattr(bot_runner, "docker_client", lambda: docker)
    real_build = bot_runner.build_spec
    artifacts = FakeArtifacts({"audio_0000.ogg": OGG})
    monkeypatch.setattr(
        bot_runner, "build_spec", lambda db_, m: (real_build(db_, m)[0], artifacts)
    )

    job = _job(db, meeting)
    bot_runner.run_bot(db, job)
    db.refresh(meeting)

    # No cleanup helper ran (its call always carries `entrypoint`) - only the
    # ONE real bot container.
    assert len(docker.containers.runs) == 1
    assert "entrypoint" not in docker.containers.runs[0]
    assert volume in {c["volume"] for c in docker.containers.list_calls if c}
    assert meeting.status == STATUS_TRANSCRIBED


# ── review round: SIGTERM must actually terminate the process ────────────────


def test_sigterm_still_terminates_when_the_previous_handler_was_the_default():
    """``signal.SIG_DFL`` is the integer 0, so ``if callable(previous)`` skipped
    it - the process stopped its containers and then carried on running, which
    on a real shutdown means the supervisor eventually SIGKILLs it and the bot
    never gets its 45 s. Re-raise the signal against the restored handler."""
    import os

    from modules.meetings.services.bot_runner import graceful_stop_on_sigterm

    container = FakeContainer([])
    killed = {}
    real_kill = os.kill

    def fake_kill(pid, sig):
        killed["pid"], killed["sig"] = pid, sig

    previous = signal.signal(signal.SIGTERM, signal.SIG_DFL)
    try:
        import modules.meetings.services.bot_runner as runner

        runner.os.kill = fake_kill
        try:
            with graceful_stop_on_sigterm(container):
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        finally:
            runner.os.kill = real_kill
    finally:
        signal.signal(signal.SIGTERM, previous)

    assert container.stopped_with is not None
    assert killed == {"pid": os.getpid(), "sig": signal.SIGTERM}


def test_the_previous_sigterm_handler_is_put_back_exactly():
    """Not "is not None" - that passes even when the handler was left as ours."""
    from modules.meetings.services.bot_runner import graceful_stop_on_sigterm

    marker = lambda *a: None  # noqa: E731 - identity is the whole assertion
    previous = signal.signal(signal.SIGTERM, marker)
    try:
        with graceful_stop_on_sigterm(FakeContainer([])):
            assert signal.getsignal(signal.SIGTERM) is not marker
        assert signal.getsignal(signal.SIGTERM) is marker
    finally:
        signal.signal(signal.SIGTERM, previous)


# ── review round: the bootstep really carries the checks ─────────────────────


def test_the_bootstep_runs_the_docker_check_when_a_worker_builds_it():
    """Asserting the queue name proves nothing about AC-S2-14. Build the
    bootstep the way a worker does and watch it reject an unreachable daemon."""
    from modules.meetings.worker import BootChecks, WorkerBootError, celery_app

    assert BootChecks in celery_app.steps["worker"]

    class FakeAmqp:
        queues = {"bots": object()}

    class FakeApp:
        amqp = FakeAmqp()
        steps = {"worker": set()}

    class FakeParent:
        app = FakeApp()

    import modules.meetings.services.bot_runner as runner

    real = runner.docker_client
    runner.docker_client = lambda: FakeDocker(info_error=RuntimeError("socket missing"))
    try:
        with pytest.raises(WorkerBootError) as excinfo:
            BootChecks(FakeParent())
        assert "socket missing" in str(excinfo.value)
    finally:
        runner.docker_client = real
