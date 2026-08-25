"""Calendar-sync background job (S0 plan §3).

Rides the EXISTING ``background_jobs`` table + ``register_job_handler`` (spine
M19) — the module adds no queue, no scheduler and no runner of its own.

The beat tick (``enqueue_due_calendar_syncs``) is deliberately narrow: it creates
a job only for a tenant that has the module ACTIVE, an ACTIVE Google connection,
at least one opted-in user, and no pass still in flight. A tenant that switched
everyone off, or never finished onboarding Google, costs nothing.
"""
from __future__ import annotations

import logging
from typing import List, Optional

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
from app.secrets import decrypt_secret

from .calendar.base import CalendarSourceError
from .models import UserOptIn
from .providers import GOOGLE_DWD_PROVIDER, calendar_source_from_connection
from .services.calendar_sync import record_sync_activity, sync_tenant

logger = logging.getLogger("foundryx.meetings")

CALENDAR_SYNC = "meetings.calendar_sync"
# The orchestrator's two types (S2). ``bot_run`` is the only job in the system
# that runs on the ``bots`` queue; ``transcribe`` is S3's, and its S2 handler
# does nothing but log and mark the meeting ready so the UI path can be seen.
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
    """Handler for ``meetings.calendar_sync`` — one tenant, one pass."""
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
        # A stale ciphertext is an operator problem, not a crash — say which
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


def run_transcribe(db: Session, job: BackgroundJob) -> None:
    """Handler for ``meetings.transcribe`` - a STUB until S3.

    It exists now so the recording path has somewhere real to hand off to and
    the UI reaches ``ready``; it produces no transcript. S3 replaces the body,
    not the wiring."""
    from app.jobs.service import JobService
    from app.models.background_job import JOB_DONE

    from .models import STATUS_READY, Meeting

    service = JobService(db)
    meeting_id = str((job.payload_json or {}).get("meeting_id") or "")
    meeting = (
        db.query(Meeting)
        .filter(Meeting.tenant_id == job.tenant_id, Meeting.id == meeting_id)
        .first()
    )
    if meeting is None:
        service.finish(job, status=JOB_DONE, result={"skipped": "meeting is gone"})
        return
    service.log(job, "transcription is not built yet (S3); marking the meeting ready")
    meeting.status = STATUS_READY
    db.commit()
    service.finish(job, status=JOB_DONE, result={"stub": True})


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
        except Exception:  # noqa: BLE001 — one tenant never breaks the tick
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
