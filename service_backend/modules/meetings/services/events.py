"""Events service (S0 plan §5) — the caller's own upcoming meetings.

Two scopes apply to every query and neither is negotiable: the tenant comes from
the JWT, and the calendar is the CALLER'S. A colleague's mirrored row is not the
caller's to read or to switch off, so a foreign id is a 404 rather than a 403 —
the caller has no business learning it exists.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import STATUS_SCHEDULED, CalendarEvent, Meeting, UserOptIn
from .calendar_sync import WINDOW_DAYS, dedupe_key


class EventsService:
    def __init__(self, db: Session):
        self.db = db

    def list_for_user(
        self,
        tenant_id: str,
        user_id: str,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        now: Optional[datetime] = None,
    ) -> List[CalendarEvent]:
        """The caller's mirrored events inside the window, soonest first.

        Nothing is listed while the master toggle is off: an opted-out user has
        no synced calendar, and their older rows are kept but not shown
        (AC-S0-9)."""
        opt_in = (
            self.db.query(UserOptIn)
            .filter(UserOptIn.tenant_id == tenant_id, UserOptIn.user_id == user_id)
            .first()
        )
        if opt_in is None or not opt_in.enabled:
            return []

        now = now or datetime.now(timezone.utc)
        start = start or now
        # The same window the sync mirrors - one definition, one horizon.
        end = end or (start + timedelta(days=WINDOW_DAYS))
        return (
            self.db.query(CalendarEvent)
            .filter(
                CalendarEvent.tenant_id == tenant_id,
                CalendarEvent.calendar_user_id == user_id,
                CalendarEvent.starts_at >= start,
                CalendarEvent.starts_at <= end,
            )
            # `id` breaks the tie: two events can share a start to the second.
            .order_by(CalendarEvent.starts_at.asc(), CalendarEvent.id.asc())
            .all()
        )

    def get_own(self, tenant_id: str, user_id: str, event_id: str) -> CalendarEvent:
        row = (
            self.db.query(CalendarEvent)
            .filter(
                CalendarEvent.tenant_id == tenant_id,
                CalendarEvent.calendar_user_id == user_id,
                CalendarEvent.id == event_id,
            )
            .first()
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
            )
        return row

    def set_opt_out(
        self, tenant_id: str, user_id: str, event_id: str, opted_out: bool
    ) -> CalendarEvent:
        """Switch one event out of (or back into) capture (AC-S0-8)."""
        row = self.get_own(tenant_id, user_id, event_id)
        row.opted_out = opted_out
        self.db.commit()
        self.db.refresh(row)
        return row


def attendees_of(event: CalendarEvent) -> List[dict]:
    """The event's attendee list, normalised to ``{email, displayName}``.

    Google sends a list of objects; anything without an email is dropped rather
    than rendered as a blank pill."""
    rows = event.attendees_json or []
    out = []
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        email = entry.get("email")
        if not email:
            continue
        out.append({"email": email, "displayName": entry.get("displayName")})
    return out


def meeting_status_for(
    db: Session, tenant_id: str, events: List[CalendarEvent]
) -> Dict[str, Tuple[str, Optional[str]]]:
    """``event id -> (meeting status, reason)`` for a whole page of rows.

    The link is the dedupe key the sync already built (``<url>|<start ISO>``),
    so two invitees of one meeting see the SAME status - which is the point of
    there being one meeting row (AC-S0-12, AC-S2-3). An event with no meeting row
    yet reads ``scheduled``: the sync creates the event and the meeting in the
    same pass, so this is a transient state, not a missing one.
    """
    if not events:
        return {}
    by_key = {dedupe_key(e.conference_url, e.starts_at): e.id for e in events}
    rows = (
        db.query(Meeting)
        .filter(Meeting.tenant_id == tenant_id, Meeting.dedupe_key.in_(list(by_key)))
        .all()
    )
    found = {
        by_key[row.dedupe_key]: (row.status, row.status_reason)
        for row in rows
        if row.dedupe_key in by_key
    }
    return {e.id: found.get(e.id, (STATUS_SCHEDULED, None)) for e in events}
