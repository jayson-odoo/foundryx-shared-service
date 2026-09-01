"""Upcoming-events routes (S0 plan §5, AC-S0-7 / AC-S0-8).

HTTP + Pydantic only. Both the tenant and the calendar owner come from the JWT;
an id that belongs to anyone else is a 404, never a 403.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..models import CalendarEvent
from ..schemas import EventListResponse, EventOptOutIn, EventOut
from ..services.events import EventsService, attendees_of

router = APIRouter()


def _out(row: CalendarEvent) -> EventOut:
    attendees = attendees_of(row)
    return EventOut(
        id=row.id,
        title=row.title,
        organiserEmail=row.organiser_email,
        attendees=attendees,
        attendeeCount=len(attendees),
        conferenceUrl=row.conference_url,
        platform=row.platform,
        startsAt=row.starts_at,
        endsAt=row.ends_at,
        optedOut=row.opted_out,
    )


@router.get("", response_model=EventListResponse)
def list_events(
    start: Optional[datetime] = Query(default=None, alias="from"),
    end: Optional[datetime] = Query(default=None, alias="to"),
    current_user: User = Depends(require_permission("meetings.view")),
    db: Session = Depends(get_db),
) -> EventListResponse:
    rows = EventsService(db).list_for_user(
        current_user.tenant_id, current_user.id, start=start, end=end
    )
    return EventListResponse(data=[_out(row) for row in rows])


@router.put("/{event_id}/opt-out", response_model=EventOut)
def set_event_opt_out(
    event_id: str,
    body: EventOptOutIn,
    current_user: User = Depends(require_permission("meetings.view")),
    db: Session = Depends(get_db),
) -> EventOut:
    row = EventsService(db).set_opt_out(
        current_user.tenant_id, current_user.id, event_id, body.optedOut
    )
    return _out(row)
