"""Which meetings get a bot, and when (S2 plan §2, AC-S2-1..4).

A 60 s beat tick asks one question per tenant: is there a ``scheduled`` meeting
starting within the next two minutes? Everything else here is about the three
ways the answer can be "yes, but no bot":

* nobody who was invited still wants it captured -> ``skipped`` / ``opted_out``;
* the meeting is already over -> ``skipped`` / ``missed``;
* it started a while ago and no bot ever ran (the worker was down) -> dispatch
  anyway, with ``late`` on the payload so the run says so.

Idempotency is the STATUS, not a lock: a meeting is only ever picked while it is
``scheduled``, and picking it moves it to ``joining`` in the same commit. A
second tick a minute later sees nothing to do.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models import (
    STATUS_JOINING,
    STATUS_SCHEDULED,
    STATUS_SKIPPED,
    CalendarEvent,
    Meeting,
    MeetingParticipant,
    UserOptIn,
)

logger = logging.getLogger("foundryx.meetings")

BOT_RUN = "meetings.bot_run"

# The bot is dispatched this far ahead of the start, so it is in the lobby
# before the first human is (spine M6: "cutoff 2 min before start").
LEAD = timedelta(minutes=2)

# A meeting that started longer ago than this and still has no bot means the
# worker was down. It is still dispatched - a bot joining 20 minutes in records
# the rest of the meeting, which beats recording none of it - but the payload
# says ``late`` so the run is not mistaken for a healthy one.
LATE_AFTER = timedelta(minutes=15)

REASON_OPTED_OUT = "opted_out"
REASON_MISSED = "missed"


@dataclass
class DispatchResult:
    """What one tick did for one tenant."""

    dispatched: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def as_summary(self) -> dict:
        return {
            "dispatched": len(self.dispatched),
            "skipped": len(self.skipped),
            "errors": len(self.errors),
        }


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def due_meetings(db: Session, tenant_id: str, now: datetime) -> List[Meeting]:
    """Scheduled meetings whose start is inside the lead window.

    No lower bound: a meeting whose start has passed is still due (AC-S2-4), and
    the only thing that takes a meeting out of this query is its own status."""
    return (
        db.query(Meeting)
        .filter(
            Meeting.tenant_id == tenant_id,
            Meeting.status == STATUS_SCHEDULED,
            Meeting.starts_at <= now + LEAD,
        )
        # `id` breaks the tie: two meetings can share a start to the second.
        .order_by(Meeting.starts_at.asc(), Meeting.id.asc())
        .all()
    )


def wants_capture(db: Session, meeting: Meeting) -> bool:
    """Does anybody invited to this meeting still want it captured?

    Two switches, and BOTH have to be on for a given person: the master toggle
    (read LIVE, so switching it off before the meeting really stops the bot -
    the participant row's ``is_opted_in`` is only a snapshot for later minutes
    visibility) and that person's own opt-out on their mirrored calendar row.
    """
    participants = (
        db.query(MeetingParticipant)
        .filter(
            MeetingParticipant.meeting_id == meeting.id,
            MeetingParticipant.user_id.isnot(None),
        )
        .all()
    )
    if not participants:
        return False

    user_ids = [p.user_id for p in participants]
    enabled = {
        row.user_id
        for row in db.query(UserOptIn)
        .filter(
            UserOptIn.tenant_id == meeting.tenant_id,
            UserOptIn.user_id.in_(user_ids),
            UserOptIn.enabled.is_(True),
        )
        .all()
    }
    if not enabled:
        return False

    # The mirrored calendar row of each still-opted-in user, matched the way the
    # meeting was deduped in the first place: same link, same start.
    opted_out = {
        row.calendar_user_id
        for row in db.query(CalendarEvent)
        .filter(
            CalendarEvent.tenant_id == meeting.tenant_id,
            CalendarEvent.calendar_user_id.in_(list(enabled)),
            CalendarEvent.conference_url == meeting.conference_url,
            CalendarEvent.starts_at == meeting.starts_at,
            CalendarEvent.opted_out.is_(True),
        )
        .all()
    }
    return bool(enabled - opted_out)


def _skip(db: Session, meeting: Meeting, reason: str) -> None:
    meeting.status = STATUS_SKIPPED
    meeting.status_reason = reason
    db.flush()


def dispatch_tenant(
    db: Session, tenant_id: str, *, now: Optional[datetime] = None
) -> DispatchResult:
    """One tick for one tenant. Returns what it did."""
    from app.jobs.service import JobService

    now = now or datetime.now(timezone.utc)
    result = DispatchResult()
    service = JobService(db)

    for meeting in due_meetings(db, tenant_id, now):
        ends_at = _as_utc(meeting.ends_at)
        starts_at = _as_utc(meeting.starts_at) or now
        try:
            if ends_at is not None and ends_at < now:
                # Already over. Joining now would record an empty room and then
                # report it as a successful capture.
                _skip(db, meeting, REASON_MISSED)
                result.skipped.append(meeting.id)
                continue
            if not wants_capture(db, meeting):
                _skip(db, meeting, REASON_OPTED_OUT)
                result.skipped.append(meeting.id)
                continue

            late = starts_at < now - LATE_AFTER
            # Status first, in the SAME transaction as the job row: a crash
            # between the two would otherwise leave a meeting that is both
            # dispatched and still dispatchable.
            meeting.status = STATUS_JOINING
            meeting.status_reason = None
            db.flush()
            job = service.create(
                type=BOT_RUN,
                tenant_id=tenant_id,
                payload={
                    "meeting_id": meeting.id,
                    "tenant_id": tenant_id,
                    "late": late,
                },
            )
            enqueue_bot_run(db, job.id)
            result.dispatched.append(meeting.id)
        except Exception as exc:  # noqa: BLE001 — one meeting never breaks the tick
            logger.exception("meetings bot dispatch failed for %s", meeting.id)
            db.rollback()
            result.errors.append(f"{meeting.id}: {exc}")

    db.commit()
    return result


def enqueue_bot_run(db: Session, job_id: str) -> None:
    """Put the job on the ``bots`` queue - NOT on the app server's queues.

    Eager (dev/test) runs it INLINE on this session, exactly as
    ``JobService.enqueue`` does: the Celery eager path would open a second
    session that no test can steer."""
    from app.config import settings

    if settings.celery_task_always_eager:
        from app.jobs.service import run_job

        run_job(db, job_id)
        return
    from .. import worker

    worker.run_bot_job.delay(job_id)


def dispatch_due_bot_runs(db: Session, *, now: Optional[datetime] = None) -> int:
    """Beat tick across every tenant that has the module active. Returns how
    many bot runs were dispatched."""
    from .. import jobs as jobs_module

    dispatched = 0
    for tenant_id in jobs_module.active_tenants(db):
        try:
            dispatched += len(dispatch_tenant(db, tenant_id, now=now).dispatched)
        except Exception:  # noqa: BLE001 — one tenant never breaks the tick
            logger.exception("meetings bot dispatch tick failed for %s", tenant_id)
            db.rollback()
    return dispatched
