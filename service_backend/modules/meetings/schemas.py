"""Meetings wire schemas (S0 plan §5).

camelCase over the wire, and every schema carrying a datetime inherits
``ApiModel`` so timestamps leave Z-suffixed UTC.

The read models are BUILT by their router from the ORM row rather than validated
off it, so they carry no ``validation_alias``: the snake→camel mapping is one
explicit line in the router, which is the only place that knows which of the
row's columns the wire actually exposes.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import Field

from app.schemas.base import ApiModel


class OptInIn(ApiModel):
    enabled: bool
    # Omitted = keep the stored address; sent as null/blank = back to my login
    # email. Told apart by ``model_fields_set``, never by the value being None.
    calendarEmail: Optional[str] = Field(default=None, max_length=254)


class OptInOut(ApiModel):
    enabled: bool
    lastSyncedAt: Optional[datetime] = None
    # The calendar this user's events are read from; null = their login email.
    calendarEmail: Optional[str] = None
    # The address to share a calendar with; null = no Google connection yet.
    serviceAccountEmail: Optional[str] = None


class AttendeeOut(ApiModel):
    email: str
    displayName: Optional[str] = None


class EventOut(ApiModel):
    id: str
    title: Optional[str] = None
    organiserEmail: Optional[str] = None
    attendees: List[AttendeeOut] = Field(default_factory=list)
    attendeeCount: int = 0
    conferenceUrl: str
    platform: str
    startsAt: datetime
    endsAt: Optional[datetime] = None
    optedOut: bool


class EventListResponse(ApiModel):
    data: List[EventOut]


class EventOptOutIn(ApiModel):
    optedOut: bool


class SettingsOut(ApiModel):
    # Read-only: the connection's own service-account address, so the operator
    # knows what to share calendars with. Never the key.
    calendarServiceAccountEmail: Optional[str] = None
    minutesLanguage: str
    audioRetentionDays: int
    llmConnectionId: Optional[str] = None
    botDisplayName: Optional[str] = None
    consentMessage: Optional[str] = None


class SettingsIn(ApiModel):
    """Every field optional — an omitted key keeps the stored value."""

    minutesLanguage: Optional[str] = Field(default=None, max_length=16)
    # 0 = keep recordings forever (spine M15).
    audioRetentionDays: Optional[int] = Field(default=None, ge=0, le=3650)
    llmConnectionId: Optional[str] = None
    botDisplayName: Optional[str] = Field(default=None, max_length=120)
    consentMessage: Optional[str] = Field(default=None, max_length=2000)
