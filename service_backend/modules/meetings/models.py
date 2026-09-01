"""Meetings module models - all ten tables live in the ``app_meetings`` schema.

The full shape from the program spine (``PLAN-meetings-program.md`` §3) lands in
ONE migration even though S0 only writes four of the tables (``user_opt_ins``,
``calendar_events``, ``meetings``, ``meeting_participants``) - one migration, one
shape, no drip.

Refs to core rows are PLAIN INDEXED COLUMNS (``tenant_id``, ``user_id``,
``recording_file_id`` → core ``files``, ``llm_connection_id`` → core
``connections``), never cross-schema FKs: the module never ALTERs core and the
core row's lifetime is not this module's business. FKs INSIDE the module schema
are real, so an uninstall/delete cascades cleanly.

Every tenant-scoped table carries ``tenant_id``. Datetimes are ``UTCDateTime``
(tz-aware UTC), never plain ``DateTime``.
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.types import JSON as GenericJSON

from app.models.utc_datetime import UTCDateTime

from .db import MeetingsBase

# A cleared JSON column is SQL NULL, not JSON ``'null'`` (house gotcha).
_JSON = GenericJSON(none_as_null=True)

# Conference platforms we recognise on a calendar event.
PLATFORM_MEET = "meet"
PLATFORM_ZOOM = "zoom"
PLATFORM_TEAMS = "teams"
PLATFORM_OTHER = "other"

# Meeting lifecycle - a plain machine-driven enum column, NOT the status engine
# (spine M19): no tenant ever edits these and no transition is a human action.
STATUS_SCHEDULED = "scheduled"
STATUS_JOINING = "joining"
STATUS_IN_LOBBY = "in_lobby"
STATUS_RECORDING = "recording"
STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_NOT_ADMITTED = "not_admitted"
STATUS_SKIPPED = "skipped"

# Who authored a minutes version.
MINUTES_AUTHOR_LLM = "llm"


def _uuid() -> str:
    return str(uuid.uuid4())


class UserOptIn(MeetingsBase):
    """The master toggle, one row per tenant user (spine M6).

    ``enabled`` is the user's own decision - off until they flip it, and nothing
    of theirs is ever synced while it is off. ``sync_token`` is Google's
    incremental ``syncToken`` for THIS user's calendar; it is dropped whenever
    Google rejects it (HTTP 410) and the next run refetches the full window.
    """

    __tablename__ = "user_opt_ins"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_meetings_optin_user"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    # Core ``public.users.id`` - plain indexed column, no cross-schema FK.
    user_id = Column(String, nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=False, server_default="0")
    sync_token = Column(Text, nullable=True)
    last_synced_at = Column(UTCDateTime(), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CalendarEvent(MeetingsBase):
    """One calendar event that carries a conference link, mirrored per calendar.

    Two invitees of the same tenant each get their OWN row for the same meeting
    (their calendars are two sources) - the shared ``meetings`` row is what
    dedupes them. ``opted_out`` is the per-event switch; a later sync refreshes
    the event's own fields but NEVER resets this flag.
    """

    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "calendar_user_id",
            "external_id",
            name="uq_meetings_event_calendar",
        ),
        Index("ix_meetings_events_tenant_start", "tenant_id", "starts_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    # Google's event id, unique within the calendar it came from.
    external_id = Column(String, nullable=False)
    # Core ``public.users.id`` whose calendar this row was read from.
    calendar_user_id = Column(String, nullable=False, index=True)
    title = Column(Text, nullable=True)
    organiser_email = Column(String, nullable=True)
    # [{"email": …, "displayName": …, "responseStatus": …}, …]
    attendees_json = Column(_JSON, nullable=True)
    conference_url = Column(Text, nullable=False)
    platform = Column(String, nullable=False, default=PLATFORM_OTHER)
    starts_at = Column(UTCDateTime(), nullable=False)
    ends_at = Column(UTCDateTime(), nullable=True)
    opted_out = Column(Boolean, nullable=False, default=False, server_default="0")
    synced_at = Column(UTCDateTime(), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Meeting(MeetingsBase):
    """One meeting per conference link + start (spine M8) - the dedupe row.

    ``dedupe_key`` is ``<conference_url>|<starts_at ISO in UTC>``; it is what
    stops two invitees producing two bots for one meeting. S0 only ever creates
    it in ``scheduled``; S2 owns every other status.
    """

    __tablename__ = "meetings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedupe_key", name="uq_meetings_dedupe"),
        Index("ix_meetings_tenant_start", "tenant_id", "starts_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    dedupe_key = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    conference_url = Column(Text, nullable=False)
    platform = Column(String, nullable=False, default=PLATFORM_OTHER)
    starts_at = Column(UTCDateTime(), nullable=False)
    ends_at = Column(UTCDateTime(), nullable=True)
    status = Column(String, nullable=False, default=STATUS_SCHEDULED)
    # Core ``public.files.id`` holding the recorded audio - plain column (S2).
    recording_file_id = Column(String, nullable=True, index=True)
    language = Column(String, nullable=True)
    not_admitted_reason = Column(Text, nullable=True)
    duration_s = Column(Integer, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MeetingParticipant(MeetingsBase):
    """Who was invited to (later: seen in) a meeting.

    ``user_id`` is resolved by email against the tenant's users and stays NULL
    for an external attendee. ``is_opted_in`` is a SNAPSHOT of that user's master
    toggle when the participant row was written - minutes visibility in S5 reads
    it rather than re-deriving history.
    """

    __tablename__ = "meeting_participants"
    __table_args__ = (
        UniqueConstraint("meeting_id", "email", name="uq_meetings_participant"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    meeting_id = Column(
        String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    # Core ``public.users.id`` when the email matches a tenant user, else NULL.
    user_id = Column(String, nullable=True, index=True)
    is_opted_in = Column(Boolean, nullable=False, default=False, server_default="0")

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Transcript(MeetingsBase):
    """One transcript per meeting; a re-run REPLACES it (S3)."""

    __tablename__ = "transcripts"
    __table_args__ = (
        UniqueConstraint("meeting_id", name="uq_meetings_transcript_meeting"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    meeting_id = Column(
        String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stt_provider = Column(String, nullable=False)
    model = Column(String, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class TranscriptSegment(MeetingsBase):
    """One diarised utterance (S3). ``language`` is per segment - a meeting may
    switch language mid-sentence and the transcript stays verbatim (spine M14).
    The ``pg_trgm`` index on ``text`` is added by the migration (Postgres only).
    """

    __tablename__ = "transcript_segments"
    __table_args__ = (
        Index("ix_meetings_segments_transcript_start", "transcript_id", "start_ms"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    transcript_id = Column(
        String,
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    speaker = Column(String, nullable=True)
    start_ms = Column(Integer, nullable=False, default=0)
    end_ms = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    language = Column(String, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class Minutes(MeetingsBase):
    """A versioned minutes document (S4). Version 1 is the LLM's; every human
    edit adds a version, so the original is never lost (spine M14)."""

    __tablename__ = "minutes"
    __table_args__ = (
        UniqueConstraint("meeting_id", "version", name="uq_meetings_minutes_version"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    meeting_id = Column(
        String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version = Column(Integer, nullable=False, default=1)
    # {"summary": …, "decisions": [...], "openQuestions": [...], "topics": [...]}
    sections_json = Column(_JSON, nullable=True)
    # Core ``public.users.id`` for a human edit, or the literal ``"llm"``.
    created_by = Column(String, nullable=False, default=MINUTES_AUTHOR_LLM)
    prompt_version_id = Column(String, nullable=True)
    llm_provider = Column(String, nullable=True)
    llm_model = Column(String, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ActionItem(MeetingsBase):
    """One extracted action item, tickable by a human (S4)."""

    __tablename__ = "action_items"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    minutes_id = Column(
        String, ForeignKey("minutes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text = Column(Text, nullable=False)
    owner_email = Column(String, nullable=True)
    due_on = Column(Date, nullable=True)
    done_at = Column(UTCDateTime(), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Share(MeetingsBase):
    """A user-to-user share of one meeting (S5). Share LINKS are deferred."""

    __tablename__ = "shares"
    __table_args__ = (
        UniqueConstraint("meeting_id", "user_id", name="uq_meetings_share"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    meeting_id = Column(
        String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Core ``public.users.id`` - recipient and sharer.
    user_id = Column(String, nullable=False, index=True)
    shared_by = Column(String, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class MeetingsTenantSettings(MeetingsBase):
    """The module's per-tenant settings, one row per tenant.

    Everything past S0 reads these; S0 stores them so the tenant is configured
    before the first bot ever runs. Defaults are the platform's, so a tenant that
    never opens the page still behaves sanely.
    """

    __tablename__ = "tenant_settings"

    tenant_id = Column(String, primary_key=True)
    minutes_language = Column(String, nullable=False, default="en")
    # 0 = keep audio forever (spine M15).
    audio_retention_days = Column(Integer, nullable=False, default=90)
    # Core ``public.connections.id`` of the tenant's chosen LLM - plain column.
    llm_connection_id = Column(String, nullable=True)
    bot_display_name = Column(String, nullable=True)
    consent_message = Column(Text, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
