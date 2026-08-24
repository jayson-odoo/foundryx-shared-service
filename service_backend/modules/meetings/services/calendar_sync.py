"""Calendar sync (S0 plan §3) — mirror each opted-in user's calendar.

One pass per tenant:

1. every user whose master toggle is ON, one read each through the tenant's
   ``CalendarSource``;
2. incremental where Google gave us a ``syncToken`` last time, a full 14-day
   window when it did not — when it rejects the token (HTTP 410), which is the
   only recovery Google documents, or every ``FULL_RESYNC_AFTER_HOURS`` so the
   window actually rolls forward (AC-S0-11);
3. upsert the events that carry a conference link, delete the ones that were
   cancelled or lost their link, and — on a FULL read only — delete the rows in
   the window the calendar stopped returning at all, which is the only way a
   cancellation shows up outside an incremental page (AC-S0-10). ``opted_out``
   is never touched: the user's decision outranks the calendar (AC-S0-8);
4. one ``meetings`` row per ``conference_url|starts_at`` so two invitees of the
   same meeting produce one bot, not two (AC-S0-12).

Nothing joins anything in S0: every meeting is created ``scheduled`` and stays
there until the orchestrator lands.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.user import User

from ..calendar.base import (
    CalendarSource,
    CalendarSourceError,
    RawEvent,
    SyncTokenInvalid,
    detect_platform,
)
from ..models import (
    STATUS_SCHEDULED,
    CalendarEvent,
    Meeting,
    MeetingParticipant,
    UserOptIn,
)

logger = logging.getLogger("foundryx.meetings")

# The window a full (non-incremental) read covers (S0 plan §3). The events
# service reads the same constant - one window, one definition.
WINDOW_DAYS = 14

# How long a stored ``syncToken`` may be used before the sync reads the whole
# window again. Google answers an incremental read against the timeMin/timeMax
# of the request that MINTED the token, so a token held forever means the window
# never rolls and a meeting first seen beyond 14 days never arrives at all.
FULL_RESYNC_AFTER_HOURS = 6

# One activity row per run (AC-S0-11). The source value is the module's own —
# see ``app/models/integration_activity.ACTIVITY_SOURCES``.
ACTIVITY_SOURCE = "meetings"
ACTIVITY_OPERATION = "calendar.sync"


@dataclass
class SyncResult:
    """What one tenant's pass did — the payload of the activity row."""

    users_synced: int = 0
    events_upserted: int = 0
    events_deleted: int = 0
    meetings_created: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_summary(self) -> dict:
        return {
            "usersSynced": self.users_synced,
            "eventsUpserted": self.events_upserted,
            "eventsDeleted": self.events_deleted,
            "meetingsCreated": self.meetings_created,
            "errors": len(self.errors),
        }


def dedupe_key(conference_url: str, starts_at: datetime) -> str:
    """``<conference_url>|<starts_at ISO in UTC>`` (spine M8).

    Normalised to UTC first: two invitees in different timezones must produce
    the SAME key, and a naive value is UTC by house convention."""
    aware = starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
    return f"{conference_url}|{aware.astimezone(timezone.utc).isoformat()}"


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def sync_tenant(
    db: Session,
    tenant_id: str,
    source: CalendarSource,
    *,
    now: Optional[datetime] = None,
) -> SyncResult:
    """Read every opted-in user's calendar for ONE tenant and mirror it."""
    now = now or datetime.now(timezone.utc)
    result = SyncResult()

    opt_ins = (
        db.query(UserOptIn)
        .filter(UserOptIn.tenant_id == tenant_id, UserOptIn.enabled.is_(True))
        .order_by(UserOptIn.user_id.asc())
        .all()
    )
    if not opt_ins:
        return result

    users = {
        user.id: user
        for user in db.query(User)
        .filter(User.tenant_id == tenant_id, User.id.in_([o.user_id for o in opt_ins]))
        .all()
    }
    # Email -> user id for THIS tenant only: participant resolution must never
    # reach across tenants, even when the same address exists in both.
    tenant_users_by_email = {
        (user.email or "").lower(): user.id
        for user in db.query(User).filter(User.tenant_id == tenant_id).all()
    }
    opted_in_user_ids = {o.user_id for o in opt_ins}

    for opt_in in opt_ins:
        user = users.get(opt_in.user_id)
        if user is None or not user.email:
            result.errors.append(f"No email for user {opt_in.user_id}")
            continue
        try:
            read = _read_calendar(source, user.email, opt_in, now)
        except CalendarSourceError as exc:
            # One broken calendar must not cost the tenant its whole run.
            logger.warning("meetings calendar read failed for %s: %s", user.email, exc)
            result.errors.append(f"{user.email}: {exc}")
            continue

        seen = set()
        for raw in read.events:
            seen.add(raw.external_id)
            _apply_event(
                db,
                tenant_id,
                opt_in.user_id,
                raw,
                result,
                tenant_users_by_email,
                opted_in_user_ids,
            )
        if read.full_window:
            result.events_deleted += _prune_missing(
                db,
                tenant_id,
                opt_in.user_id,
                seen,
                read.window_start,
                read.window_end,
            )
        opt_in.last_synced_at = now
        result.users_synced += 1

    db.commit()
    return result


@dataclass
class _CalendarRead:
    """One user's page plus WHICH read it was.

    ``full_window`` is what licenses the prune: an incremental page carries only
    what changed, so an absent event there means nothing, while on a full read an
    absent event is the only signal a cancellation ever gives us."""

    events: List[RawEvent] = field(default_factory=list)
    full_window: bool = False
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


def _token_is_stale(opt_in: UserOptIn, now: datetime) -> bool:
    """True once the held token is old enough that the window must roll."""
    last = _as_utc(opt_in.last_synced_at)
    if last is None:
        return True
    return (now - last) >= timedelta(hours=FULL_RESYNC_AFTER_HOURS)


def _read_calendar(
    source: CalendarSource, user_email: str, opt_in: UserOptIn, now: datetime
) -> _CalendarRead:
    """One user's events: incremental while the token is fresh (AC-S0-11)."""
    start, end = now, now + timedelta(days=WINDOW_DAYS)
    window = dict(time_min=start, time_max=end)

    if opt_in.sync_token and not _token_is_stale(opt_in, now):
        try:
            page = source.list_events(user_email=user_email, sync_token=opt_in.sync_token)
            if page.next_sync_token:
                opt_in.sync_token = page.next_sync_token
            return _CalendarRead(events=page.events, full_window=False)
        except SyncTokenInvalid:
            # Google expired the token — the documented recovery is a full read.
            pass

    # Full read: clear the token FIRST so a page that returns none leaves us
    # reading the whole window again rather than reusing a token we just retired.
    opt_in.sync_token = None
    page = source.list_events(user_email=user_email, **window)
    if page.next_sync_token:
        opt_in.sync_token = page.next_sync_token
    return _CalendarRead(
        events=page.events, full_window=True, window_start=start, window_end=end
    )


def _prune_missing(
    db: Session,
    tenant_id: str,
    calendar_user_id: str,
    seen: set,
    window_start: datetime,
    window_end: datetime,
) -> int:
    """Delete this user's rows INSIDE the read window that the page omitted.

    ``events.list`` defaults to ``showDeleted=false``, so a full read never
    reports a cancellation — it simply stops returning the event. Scoping the
    delete to the window that was actually read is what stops it eating rows the
    calendar was never asked about (a meeting that has since started)."""
    stale = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.tenant_id == tenant_id,
            CalendarEvent.calendar_user_id == calendar_user_id,
            CalendarEvent.starts_at >= window_start,
            CalendarEvent.starts_at <= window_end,
        )
        .all()
    )
    removed = 0
    for row in stale:
        if row.external_id in seen:
            continue
        db.delete(row)
        removed += 1
    db.flush()
    return removed


def _apply_event(
    db: Session,
    tenant_id: str,
    calendar_user_id: str,
    raw: RawEvent,
    result: SyncResult,
    tenant_users_by_email: Dict[str, str],
    opted_in_user_ids: set,
) -> None:
    existing = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.tenant_id == tenant_id,
            CalendarEvent.calendar_user_id == calendar_user_id,
            CalendarEvent.external_id == raw.external_id,
        )
        .first()
    )

    # Cancelled, or no longer a meeting at all: the mirror drops it (AC-S0-10).
    # The `meetings` row is deliberately left alone — once S2 has scheduled or
    # run a bot for it, deleting it is that slice's decision, not this one's.
    if raw.cancelled or not raw.conference_url or not raw.starts_at:
        if existing is not None:
            db.delete(existing)
            result.events_deleted += 1
        return

    starts_at = _as_utc(raw.starts_at)
    ends_at = _as_utc(raw.ends_at)
    platform = detect_platform(raw.conference_url)
    now = datetime.now(timezone.utc)

    if existing is None:
        existing = CalendarEvent(
            tenant_id=tenant_id,
            external_id=raw.external_id,
            calendar_user_id=calendar_user_id,
            conference_url=raw.conference_url,
            platform=platform,
            starts_at=starts_at,
        )
        db.add(existing)
    # `opted_out` is absent on purpose: a sync refreshes what the CALENDAR owns
    # and nothing the USER owns (AC-S0-8).
    existing.title = raw.title
    existing.organiser_email = raw.organiser_email
    existing.attendees_json = raw.attendees or []
    existing.conference_url = raw.conference_url
    existing.platform = platform
    existing.starts_at = starts_at
    existing.ends_at = ends_at
    existing.synced_at = now
    db.flush()
    result.events_upserted += 1

    _ensure_meeting(
        db, tenant_id, raw, platform, starts_at, ends_at, result, tenant_users_by_email, opted_in_user_ids
    )


def _ensure_meeting(
    db: Session,
    tenant_id: str,
    raw: RawEvent,
    platform: str,
    starts_at: datetime,
    ends_at: Optional[datetime],
    result: SyncResult,
    tenant_users_by_email: Dict[str, str],
    opted_in_user_ids: set,
) -> Meeting:
    """The shared row two invitees of one meeting both point at (AC-S0-12)."""
    key = dedupe_key(raw.conference_url, starts_at)
    meeting = (
        db.query(Meeting)
        .filter(Meeting.tenant_id == tenant_id, Meeting.dedupe_key == key)
        .first()
    )
    if meeting is None:
        meeting = Meeting(
            tenant_id=tenant_id,
            dedupe_key=key,
            conference_url=raw.conference_url,
            platform=platform,
            starts_at=starts_at,
            ends_at=ends_at,
            status=STATUS_SCHEDULED,
        )
        db.add(meeting)
        db.flush()
        result.meetings_created += 1
    meeting.title = raw.title or meeting.title
    meeting.ends_at = ends_at or meeting.ends_at

    _ensure_participants(
        db, tenant_id, meeting, raw, tenant_users_by_email, opted_in_user_ids
    )
    return meeting


def _ensure_participants(
    db: Session,
    tenant_id: str,
    meeting: Meeting,
    raw: RawEvent,
    tenant_users_by_email: Dict[str, str],
    opted_in_user_ids: set,
) -> None:
    known = {
        p.email.lower(): p
        for p in db.query(MeetingParticipant)
        .filter(MeetingParticipant.meeting_id == meeting.id)
        .all()
    }
    for entry in raw.attendees or []:
        if not isinstance(entry, dict):
            continue
        email = (entry.get("email") or "").strip()
        if not email:
            continue
        user_id = tenant_users_by_email.get(email.lower())
        row = known.get(email.lower())
        if row is None:
            row = MeetingParticipant(
                tenant_id=tenant_id, meeting_id=meeting.id, email=email
            )
            db.add(row)
            known[email.lower()] = row
        row.display_name = entry.get("displayName")
        row.user_id = user_id
        row.is_opted_in = bool(user_id and user_id in opted_in_user_ids)
    db.flush()


def record_sync_activity(db: Session, tenant_id: str, result: SyncResult) -> None:
    """One ``integration_activity`` row per run, with the counts (AC-S0-11).

    The write is failure-isolated inside ``ActivityLogService`` — a logging
    problem can never be what breaks a sync."""
    from app.activity_log.service import ActivityLogService

    ActivityLogService(db).record(
        tenant_id=tenant_id,
        source=ACTIVITY_SOURCE,
        operation=ACTIVITY_OPERATION,
        status="success" if result.ok else "error",
        error_message="; ".join(result.errors) if result.errors else None,
        response=result.as_summary(),
    )
