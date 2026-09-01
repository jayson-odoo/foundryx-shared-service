"""Calendar-sync background job (S0 plan §3).

Rides the EXISTING ``background_jobs`` table + ``register_job_handler`` (spine
M19) - the module adds no queue, no scheduler and no runner of its own.

The beat tick (``enqueue_due_calendar_syncs``) is deliberately narrow: it creates
a job only for a tenant that has the module ACTIVE, an ACTIVE Google connection,
at least one opted-in user, and no pass still in flight. A tenant that switched
everyone off, or never finished onboarding Google, costs nothing.
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.jobs.registry import JobHandlerDef, register_job_handler
from app.models.background_job import (
    JOB_DONE,
    JOB_FAILED,
    JOB_NEEDS_REVIEW,
    JOB_PENDING,
    JOB_RUNNING,
    BackgroundJob,
)
from app.models.connection import CONNECTION_STATUS_ERROR, Connection
from app.models.document import File, FileVersion
from app.secrets import decrypt_secret
from app.services.storage import storage_for_tenant

from .calendar.base import CalendarSourceError
from .models import UserOptIn
from .providers import GOOGLE_DWD_PROVIDER, calendar_source_from_connection
from .services.calendar_sync import record_sync_activity, sync_tenant
from .stt import SttResult, SttSegment, get_provider
from .stt.align import CaptionEvent, assign_speakers

logger = logging.getLogger("foundryx.meetings")

CALENDAR_SYNC = "meetings.calendar_sync"
# The orchestrator's job types. ``bot_run`` is the only job in the system that
# runs on the ``bots`` queue; ``transcribe`` (S3, ``run_transcribe`` below)
# rides the same shared workflow queue - R1's flock, not a fourth worker, is
# what keeps at most one transcription running at a time.
BOT_RUN = "meetings.bot_run"
TRANSCRIBE = "meetings.transcribe"
MODULE_NAME = "meetings"

# Non-terminal statuses = a pass is still in flight (mirrors the storage
# migration's ``_ACTIVE_JOB_STATUSES``). A tenant whose sync outruns the minute
# tick would otherwise accumulate jobs that race on the same ``sync_token`` and
# collide on ``uq_meetings_event_calendar``.
_ACTIVE_JOB_STATUSES = (JOB_PENDING, JOB_RUNNING, JOB_NEEDS_REVIEW)


def _google_connection(db: Session, tenant_id: str) -> Optional[Connection]:
    """The tenant's ACTIVE Google connection, or None if it has none."""
    return (
        db.query(Connection)
        .filter(
            Connection.tenant_id == tenant_id,
            Connection.provider == GOOGLE_DWD_PROVIDER,
            Connection.is_active.is_(True),
        )
        .first()
    )


def run_calendar_sync(db: Session, job: BackgroundJob) -> None:
    """Handler for ``meetings.calendar_sync`` - one tenant, one pass."""
    from app.jobs.service import JobService

    service = JobService(db)
    tenant_id = job.tenant_id

    connection = _google_connection(db, tenant_id)
    if connection is None:
        # Not an error: a tenant can install the module before onboarding Google.
        service.finish(job, status=JOB_DONE, result={"skipped": "no calendar connection"})
        return

    try:
        credentials = decrypt_secret(connection.credentials_json)
    except InvalidToken:
        # A stale ciphertext is an operator problem, not a crash - say which
        # connection to re-enter and stop.
        connection.status = CONNECTION_STATUS_ERROR
        connection.last_error = (
            "Stored credentials can no longer be decrypted. Re-enter the "
            "service-account key and save."
        )
        db.commit()
        service.finish(job, status=JOB_FAILED, error=connection.last_error)
        return

    try:
        source = calendar_source_from_connection(connection.config_json or {}, credentials)
    except CalendarSourceError as exc:
        service.finish(job, status=JOB_FAILED, error=str(exc))
        return

    result = sync_tenant(db, tenant_id, source)
    record_sync_activity(db, tenant_id, result)
    service.log(
        job,
        f"synced {result.users_synced} calendars, "
        f"{result.events_upserted} events upserted, {result.events_deleted} removed",
    )
    service.finish(job, status=JOB_DONE, result=result.as_summary())


def active_tenants(db: Session) -> List[str]:
    """Tenants with the meetings module ACTIVE. The floor every tick stands on."""
    from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule

    module = db.query(Module).filter(Module.name == MODULE_NAME).first()
    if module is None:
        return []
    return sorted(
        state.tenant_id
        for state in db.query(TenantModule)
        .filter(
            TenantModule.module_id == module.id,
            TenantModule.status == MODULE_STATUS_ACTIVE,
        )
        .all()
    )


def _events_jsonl(raw: bytes) -> Tuple[Optional[float], List[CaptionEvent]]:
    """``events.jsonl`` bytes -> (recording start epoch, caption events).

    The recording start epoch is the ``ts`` of the bot's ``recording_started``
    event (plan §2 - "the ts of the first recorder segment event"). A
    malformed line is skipped, never a crash - the container's writer is
    append-only text, not a validated contract."""
    start_epoch: Optional[float] = None
    captions: List[CaptionEvent] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        kind = row.get("kind")
        if kind == "recording_started" and start_epoch is None:
            ts = row.get("ts")
            if ts is not None:
                start_epoch = float(ts)
        elif kind == "caption":
            ts = row.get("ts")
            speaker = row.get("speaker")
            if ts is not None and speaker:
                captions.append(CaptionEvent(ts=float(ts), speaker=str(speaker)))
    return start_epoch, captions


def _ever_saw_a_human(raw: bytes) -> Optional[bool]:
    """From ``events.jsonl``'s own ``participants`` events: True if any of
    them ever reported a human in the room, False if there were participants
    events and EVERY one said zero, None if there is no evidence either way.

    ``None`` is never treated as "confirmed empty" - only a POSITIVE zero-
    humans reading skips transcription (S2 live-run fix: a no_show meeting
    whose recording is pure silence hallucinates a transcript, but a file
    this can't read a verdict from is `_read_captions`'s problem to tolerate,
    not this one's to punish)."""
    seen_any = False
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("kind") != "participants":
            continue
        seen_any = True
        if (row.get("humans") or 0) > 0:
            return True
    return False if seen_any else None


def _recording_has_no_humans(db: Session, meeting) -> bool:
    """True only on POSITIVE evidence (see ``_ever_saw_a_human``) that nobody
    ever joined this meeting - defense in depth alongside the bot's own
    `no_show` exit reason (``bot_runner.py``), for a recording that got
    registered anyway (an older image, a race, a redelivered job before that
    fix landed)."""
    from .services.bot_runner import build_output

    try:
        _, _, artifacts = build_output(db, meeting)
        if "events.jsonl" not in artifacts.names():
            return False
        return _ever_saw_a_human(artifacts.read("events.jsonl")) is False
    except Exception:  # noqa: BLE001 - can't prove it, so don't skip on it
        return False


def _download_recording(db: Session, meeting) -> bytes:
    """The registered ``recording.ogg`` bytes, via the same core storage the
    file was originally saved through (``recordings.py`` §S2) - never the
    artifacts location, which S2 deletes the audio segments from once the
    joined file is safely stored."""
    if not meeting.recording_file_id:
        raise RuntimeError("This meeting has no recording to transcribe.")
    file = (
        db.query(File)
        .filter(File.tenant_id == meeting.tenant_id, File.id == meeting.recording_file_id)
        .first()
    )
    if file is None or not file.current_version_id:
        raise RuntimeError("The meeting's recording file could not be found.")
    version = db.query(FileVersion).filter(FileVersion.id == file.current_version_id).first()
    if version is None:
        raise RuntimeError("The meeting's recording has no stored version.")
    content, _mime = storage_for_tenant(db, meeting.tenant_id).fetch(version.storage_key)
    return content


def _read_captions(db, meeting) -> Tuple[Optional[float], List[CaptionEvent], bool]:
    """(start_epoch, captions, captions_missing) for one meeting.

    ``captions_missing`` is True whenever nothing usable came out of
    ``events.jsonl`` - file absent, empty, no caption events, no
    ``recording_started`` to anchor them to, OR the read itself failing (a
    storage connection whose credentials no longer decrypt, an S3 list
    error, ...). AC-S3-3: a host with captions disabled must still produce a
    transcript, not fail the job - and the same is true of a caption READ
    that blows up: by the time this runs the provider has already succeeded,
    so a caption failure must never discard a transcription that is
    otherwise done."""
    from .services.bot_runner import build_output

    try:
        _, _, artifacts = build_output(db, meeting)
        if "events.jsonl" not in artifacts.names():
            return None, [], True
        start_epoch, captions = _events_jsonl(artifacts.read("events.jsonl"))
        if start_epoch is None or not captions:
            return None, [], True
        return start_epoch, captions, False
    except Exception:  # noqa: BLE001 - see docstring: never fails the whole run
        logger.warning(
            "meetings caption read failed for %s; transcribing without them", meeting.id
        )
        return None, [], True


def _valid_segment_pairs(
    speakers: List[Optional[str]], segments: List[SttSegment]
) -> Tuple[List[Tuple[Optional[str], SttSegment]], int]:
    """Drop any segment a provider got wrong: AC-S3-1 (``start_ms < end_ms``,
    non-empty text) must hold for ANY driver, not just ``mlx_runner`` - the
    one this codebase ships, which already only ever emits well-formed
    segments. Returns ``(valid pairs, how many were dropped)``."""
    pairs: List[Tuple[Optional[str], SttSegment]] = []
    dropped = 0
    for speaker, segment in zip(speakers, segments):
        if segment.start_ms >= segment.end_ms or not (segment.text or "").strip():
            dropped += 1
            continue
        pairs.append((speaker, segment))
    return pairs, dropped


def _transcribe(
    db: Session, meeting
) -> Tuple[SttResult, List[Optional[str]], bool, int]:
    """Everything that can fail: download, provider call, caption alignment.
    Raises on any failure - the caller marks the job/meeting failed.

    ``transcribe_ms`` is measured around the provider call only (plan 3.3 step
    5's "timing") - the one step whose wall-clock actually varies run to run;
    download and caption-alignment are comparatively fixed overhead."""
    with tempfile.TemporaryDirectory() as tmp:
        audio_path = Path(tmp) / "recording.ogg"
        audio_path.write_bytes(_download_recording(db, meeting))
        provider = get_provider()
        started = time.monotonic()
        result = provider.transcribe(audio_path)
        transcribe_ms = int((time.monotonic() - started) * 1000)

    start_epoch, captions, captions_missing = _read_captions(db, meeting)
    speakers = assign_speakers(result.segments, captions, start_epoch or 0.0)
    return result, speakers, captions_missing, transcribe_ms


def run_transcribe(db: Session, job: BackgroundJob) -> None:
    """Handler for ``meetings.transcribe`` (S3 plan §3.3).

    Downloads the registered recording, runs the configured ``SttProvider``,
    aligns segments to caption-derived speaker names, and replaces the
    meeting's transcript (AC-S3-9: a re-run leaves exactly one). ANY failure
    from here on - reading an existing recording (unbuilt provider, subprocess
    crash/timeout, a corrupt/missing stored file) OR writing the new rows (a
    concurrent retry's unique-violation on ``uq_meetings_transcript_meeting``,
    say) - marks BOTH the job and the meeting failed (AC-S3-4); the job stays
    re-runnable. A write failure left uncaught would strand the meeting in
    whatever status it already had (``processing``) forever - nothing else
    ever moves it on.

    ``bot_run`` (S2, not this module's to change) enqueues ``transcribe``
    unconditionally on every normal exit, including a call that recorded
    NOTHING (an empty room). That is not a failure - there is simply nothing
    to transcribe - so it is a clean skip, same as a meeting that vanished."""
    from app.config import settings
    from app.jobs.service import JobService
    from app.models.background_job import JOB_DONE

    from .models import (
        STATUS_FAILED,
        STATUS_SKIPPED,
        STATUS_TRANSCRIBED,
        Meeting,
        Transcript,
        TranscriptSegment,
    )

    service = JobService(db)
    raw_meeting_id = (job.payload_json or {}).get("meeting_id")
    if not raw_meeting_id:
        # The enqueuer (``bot_runner._enqueue_transcribe``) always sends a
        # real meeting_id - an absent one is a wiring bug, not a meeting that
        # disappeared, and must not be indistinguishable from that normal case.
        error = "meetings.transcribe job payload is missing meeting_id"
        logger.error(error)
        service.finish(job, status=JOB_FAILED, error=error)
        return
    meeting_id = str(raw_meeting_id)
    meeting = (
        db.query(Meeting)
        .filter(Meeting.tenant_id == job.tenant_id, Meeting.id == meeting_id)
        .first()
    )
    if meeting is None:
        service.finish(job, status=JOB_DONE, result={"skipped": "meeting is gone"})
        return
    if not meeting.recording_file_id:
        service.finish(job, status=JOB_DONE, result={"skipped": "meeting has no recording"})
        return
    if _recording_has_no_humans(db, meeting):
        # S2 live-run fix, defense in depth: the bot's own `no_show` exit
        # (bot_runner.py) already skips this normally - this catches a
        # recording that got registered anyway. Silence only hallucinates.
        meeting.status = STATUS_SKIPPED
        meeting.status_reason = "no_show"
        db.commit()
        service.finish(job, status=JOB_DONE, result={"skipped": "no_show"})
        return

    try:
        result, speakers, captions_missing, transcribe_ms = _transcribe(db, meeting)
        valid_pairs, dropped_segments = _valid_segment_pairs(speakers, result.segments)

        # Replace-on-rerun (AC-S3-9): one transcript row per meeting, ever.
        existing = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).first()
        if existing is not None:
            db.delete(existing)
            db.flush()

        transcript = Transcript(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            stt_provider=settings.meetings_stt_provider,
            model=settings.meetings_stt_model,
        )
        db.add(transcript)
        db.flush()
        for speaker, segment in valid_pairs:
            db.add(
                TranscriptSegment(
                    tenant_id=meeting.tenant_id,
                    transcript_id=transcript.id,
                    speaker=speaker,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=segment.text,
                    # R3 AMENDED (S3 code-switch fix, 2026-09-01): the chunked
                    # mlx_runner detects language PER CHUNK, so this is real
                    # detected data from the provider, never a guess.
                    language=segment.language,
                )
            )
        meeting.language = result.language
        meeting.status = STATUS_TRANSCRIBED
        db.commit()
    except Exception as exc:  # noqa: BLE001 - every failure mode, read or write, lands here
        db.rollback()
        meeting = (
            db.query(Meeting)
            .filter(Meeting.tenant_id == job.tenant_id, Meeting.id == meeting_id)
            .first()
        )
        error = str(exc)
        logger.exception("meetings transcription failed for meeting %s", meeting_id)
        if meeting is not None:
            meeting.status = STATUS_FAILED
            meeting.status_reason = error
            db.commit()
        service.finish(job, status=JOB_FAILED, error=error)
        return

    if captions_missing:
        service.log(job, "captions were absent or unusable; every segment's speaker is NULL")
    if dropped_segments:
        service.log(
            job,
            f"dropped {dropped_segments} invalid segment(s) from the provider "
            "(bad start/end or empty text)",
        )
    service.log(
        job,
        f"transcribed {len(valid_pairs)} segments via {settings.meetings_stt_provider}",
    )
    service.finish(
        job,
        status=JOB_DONE,
        result={
            "segments": len(valid_pairs),
            "provider": settings.meetings_stt_provider,
            "model": settings.meetings_stt_model,
            "language": result.language,
            "transcribeMs": transcribe_ms,
        },
    )


def _run_bot(db: Session, job: BackgroundJob) -> None:
    """Forwarder for ``meetings.bot_run``. Deliberately thin: it keeps the
    ``docker`` import inside the handler, so the API process registers the type
    without needing the Docker SDK present at all."""
    from .services.bot_runner import run_bot

    run_bot(db, job)


def tenants_due(db: Session) -> List[str]:
    """Tenants worth a sync right now: module ACTIVE, an active Google
    connection, and at least one opted-in user.

    The connection filter is not an optimisation. Without it a tenant that
    installed the module but never onboarded Google gets a job every 60 seconds
    that can only finish ``skipped`` - forever."""
    active = set(active_tenants(db))
    if not active:
        return []
    opted_in = {
        row.tenant_id
        for row in db.query(UserOptIn)
        .filter(UserOptIn.enabled.is_(True), UserOptIn.tenant_id.in_(active))
        .all()
    }
    if not opted_in:
        return []
    connected = {
        row.tenant_id
        for row in db.query(Connection)
        .filter(
            Connection.provider == GOOGLE_DWD_PROVIDER,
            Connection.is_active.is_(True),
            Connection.tenant_id.in_(opted_in),
        )
        .all()
    }
    return sorted(connected)


def _sync_in_flight(db: Session, tenant_id: str) -> bool:
    """True while this tenant's previous pass is still pending or running."""
    from app.jobs.repository import BackgroundJobRepository

    return bool(
        BackgroundJobRepository(db).active_of_type(
            tenant_id, CALENDAR_SYNC, _ACTIVE_JOB_STATUSES
        )
    )


def enqueue_due_calendar_syncs(db: Session) -> int:
    """Beat tick: one job per due tenant. Returns how many were enqueued.

    A tenant whose previous pass has not finished is SKIPPED rather than queued
    behind itself - two concurrent passes over one calendar race on the stored
    ``sync_token`` and collide on ``uq_meetings_event_calendar``."""
    from app.jobs.service import JobService

    service = JobService(db)
    enqueued = 0
    for tenant_id in tenants_due(db):
        try:
            if _sync_in_flight(db, tenant_id):
                logger.info("meetings calendar sync still in flight for %s", tenant_id)
                continue
            service.create_and_enqueue(type=CALENDAR_SYNC, tenant_id=tenant_id)
            enqueued += 1
        except Exception:  # noqa: BLE001 - one tenant never breaks the tick
            logger.exception("meetings calendar sync enqueue failed for %s", tenant_id)
            db.rollback()
    return enqueued


# ── boot registration (idempotent) ────────────────────────────────────────────
# The SAME def object re-registers cleanly (the registry tolerates identity).
_HANDLER_DEF = JobHandlerDef(CALENDAR_SYNC, run_calendar_sync, "Meetings calendar sync")
_BOT_RUN_DEF = JobHandlerDef(BOT_RUN, _run_bot, "Meetings bot run")
_TRANSCRIBE_DEF = JobHandlerDef(TRANSCRIBE, run_transcribe, "Meetings transcription")


def register_calendar_sync_handler() -> None:
    """Register every meetings job handler.

    !!  The Celery workers boot NO FastAPI lifespan.  !!
    A worker only sees handlers whose MODULE was imported, so
    ``app/workflow_engine/worker.py`` and ``modules/meetings/worker.py`` import
    this module explicitly. Omitting that import leaves the job Pending forever
    with NO error.

    ``bot_run`` is registered in EVERY process, the API one included, because
    ``JobService.create`` refuses to persist a job whose type is unregistered -
    the dispatch tick runs on the app server and would create nothing."""
    register_job_handler(_HANDLER_DEF)
    register_job_handler(_BOT_RUN_DEF)
    register_job_handler(_TRANSCRIBE_DEF)


register_calendar_sync_handler()
