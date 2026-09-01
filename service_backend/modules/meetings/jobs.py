"""Calendar-sync background job (S0 plan §3).

Rides the EXISTING ``background_jobs`` table + ``register_job_handler`` (spine
M19) - the module adds no queue, no scheduler and no runner of its own.

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


def tenants_due(db: Session) -> List[str]:
    """Tenants worth a sync right now: module ACTIVE, an active Google
    connection, and at least one opted-in user.

    The connection filter is not an optimisation. Without it a tenant that
    installed the module but never onboarded Google gets a job every 60 seconds
    that can only finish ``skipped`` - forever."""
    from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule

    module = db.query(Module).filter(Module.name == MODULE_NAME).first()
    if module is None:
        return []
    active = {
        state.tenant_id
        for state in db.query(TenantModule)
        .filter(
            TenantModule.module_id == module.id,
            TenantModule.status == MODULE_STATUS_ACTIVE,
        )
        .all()
    }
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


def register_calendar_sync_handler() -> None:
    """Register the ``meetings.calendar_sync`` handler.

    !!  The Celery worker boots NO FastAPI lifespan.  !!
    A worker only sees handlers whose MODULE was imported, so
    ``app/workflow_engine/worker.py`` imports this module explicitly. Omitting
    that import leaves every sync job Pending forever with NO error."""
    register_job_handler(_HANDLER_DEF)


register_calendar_sync_handler()
