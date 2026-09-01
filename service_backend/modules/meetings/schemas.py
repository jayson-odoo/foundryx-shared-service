"""Meetings wire schemas (S0 plan §5).

camelCase over the wire, and every schema carrying a datetime inherits
``ApiModel`` so timestamps leave Z-suffixed UTC.

The read models are BUILT by their router from the ORM row rather than validated
off it, so they carry no ``validation_alias``: the snake→camel mapping is one
explicit line in the router, which is the only place that knows which of the
row's columns the wire actually exposes.
"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import EmailStr, Field, field_validator

from app.schemas.base import ApiModel


class OptInIn(ApiModel):
    enabled: bool
    # Omitted = keep the stored address; sent as null/blank = back to my login
    # email. Told apart by ``model_fields_set``, never by the value being None.
    calendarEmail: Optional[EmailStr] = None

    @field_validator("calendarEmail", mode="before")
    @classmethod
    def _blank_means_my_login_email(cls, value):
        """A cleared form field is "use my login email", not a bad address.

        Runs BEFORE ``EmailStr``, which would otherwise 422 the empty string a
        text input sends when someone deletes what they typed."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


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
    # S2: where the SHARED meeting behind this event has got to, and why it is
    # not on the happy path when it is not.
    meetingStatus: str
    statusReason: Optional[str] = None


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
    """Every field optional - an omitted key keeps the stored value."""

    minutesLanguage: Optional[str] = Field(default=None, max_length=16)
    # 0 = keep recordings forever (spine M15).
    audioRetentionDays: Optional[int] = Field(default=None, ge=0, le=3650)
    llmConnectionId: Optional[str] = None
    botDisplayName: Optional[str] = Field(default=None, max_length=120)
    consentMessage: Optional[str] = Field(default=None, max_length=2000)


class BotRunOut(ApiModel):
    """One bot run for the tenant admin's ops list (AC-S2-12)."""

    id: str
    meetingId: str
    meetingTitle: Optional[str] = None
    startsAt: datetime
    startedAt: Optional[datetime] = None
    endedAt: Optional[datetime] = None
    exitReason: Optional[str] = None
    durationS: Optional[int] = None
    meetingStatus: str


class BotRunListResponse(ApiModel):
    data: List[BotRunOut]


class TranscriptSegmentOut(ApiModel):
    """One aligned segment (S3 plan §3.4, AC-S3-8)."""

    speaker: Optional[str] = None
    startMs: int
    endMs: Optional[int] = None
    text: str
    # R3 amended 2026-09-01: the chunked runner detects language PER CHUNK,
    # so this is the segment's own real detected language, never a guess.
    language: Optional[str] = None


class TranscriptOut(ApiModel):
    """``GET /meetings/{id}/transcript`` - the evidence surface until S5."""

    sttProvider: str
    model: Optional[str] = None
    # The meeting's file-level detected language - the majority chunk
    # language (R3 amended 2026-09-01), ties broken by first occurrence.
    language: Optional[str] = None
    segments: List[TranscriptSegmentOut] = Field(default_factory=list)


# ── minutes (S4 plan §3.2) ───────────────────────────────────────────────────


class ActionItemOut(ApiModel):
    id: str
    text: str
    ownerEmail: Optional[str] = None
    dueOn: Optional[date] = None
    doneAt: Optional[datetime] = None


class ActionItemIn(ApiModel):
    text: str
    ownerEmail: Optional[str] = None
    # ISO date string ("YYYY-MM-DD") or null. Parsed server-side; an
    # unparseable value is stored as null rather than guessed.
    dueOn: Optional[str] = None


class TopicNoteOut(ApiModel):
    topic: str
    notes: str


class TopicNoteIn(ApiModel):
    topic: str
    notes: str


class MinutesVersionSummaryOut(ApiModel):
    """One entry in a minutes document's version history."""

    version: int
    createdBy: str
    createdAt: datetime


class MinutesOut(ApiModel):
    """``GET /meetings/{id}/minutes`` (+ ``/versions/{v}``) - the five M14
    sections, the canonical ``action_items`` rows (never the section's own
    copy - that one is the model's raw words), and the version list."""

    version: int
    createdBy: str
    createdAt: datetime
    promptVersionId: Optional[str] = None
    llmProvider: Optional[str] = None
    llmModel: Optional[str] = None
    summary: str
    decisions: List[str] = Field(default_factory=list)
    openQuestions: List[str] = Field(default_factory=list)
    topicNotes: List[TopicNoteOut] = Field(default_factory=list)
    actionItems: List[ActionItemOut] = Field(default_factory=list)
    versions: List[MinutesVersionSummaryOut] = Field(default_factory=list)


class MinutesSectionsIn(ApiModel):
    """``PUT /meetings/{id}/minutes`` body - a human edit of every section."""

    summary: str
    decisions: List[str] = Field(default_factory=list)
    actionItems: List[ActionItemIn] = Field(default_factory=list)
    openQuestions: List[str] = Field(default_factory=list)
    topicNotes: List[TopicNoteIn] = Field(default_factory=list)
