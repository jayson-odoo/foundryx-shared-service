"""Calendar sync — AC-S0-7, AC-S0-8, AC-S0-10, AC-S0-11, AC-S0-12, AC-S0-13.

Every test drives the real sync service against a scripted ``CalendarSource``
(``FakeCalendarSource``), so nothing here touches Google: what is pinned is the
sync's own behaviour — incremental token use, the HTTP-410 fallback, link
recognition per platform, the cancelled/link-removed cleanup, the one-meeting
dedupe across two invitees, and tenant scoping.
"""
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.meetings.calendar.base import SyncPage
from tests.conftest import ACTIVE_EMAIL
from tests.meetings_helpers import (
    FakeCalendarSource,
    make_admin_user,
    make_tenant,
    opt_in,
    raw_event,
    utc,
)

OTHER_TENANT_ID = "55555555-5555-5555-5555-555555555555"


@pytest.fixture
def db(meetings_session_factory):
    session = meetings_session_factory()
    yield session
    session.close()


def _demo_user(session):
    from app.models import User

    return session.query(User).filter(User.email == ACTIVE_EMAIL).one()


def _sync(session, source, tenant_id=DEFAULT_TENANT_ID):
    from modules.meetings.services.calendar_sync import sync_tenant

    return sync_tenant(session, tenant_id, source)


# ── AC-S0-7: the events that make it into the mirror ─────────────────────────


def test_only_opted_in_users_are_read(db):
    """A user with the master toggle off is never asked for at all."""
    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id, enabled=False)
    db.commit()

    source = FakeCalendarSource({})
    result = _sync(db, source)

    assert source.calls == []
    assert result.users_synced == 0


def test_meet_zoom_and_teams_links_are_all_mirrored(db):
    """AC-S0-7: Meet, Zoom and Teams links each land with the right platform."""
    from modules.meetings.models import CalendarEvent

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    source = FakeCalendarSource(
        {
            user.email: [
                SyncPage(
                    events=[
                        raw_event("g1", starts_at=utc(2026, 9, 1, 2)),
                        raw_event(
                            "z1",
                            starts_at=utc(2026, 9, 2, 2),
                            conference_url="https://us02web.zoom.us/j/8412345678",
                        ),
                        raw_event(
                            "t1",
                            starts_at=utc(2026, 9, 3, 2),
                            conference_url="https://teams.microsoft.com/l/meetup-join/19%3ameet",
                        ),
                    ],
                    next_sync_token="tok-1",
                )
            ]
        }
    )
    result = _sync(db, source)

    rows = {
        r.external_id: r
        for r in db.query(CalendarEvent)
        .filter(CalendarEvent.tenant_id == DEFAULT_TENANT_ID)
        .all()
    }
    assert set(rows) == {"g1", "z1", "t1"}
    assert rows["g1"].platform == "meet"
    assert rows["z1"].platform == "zoom"
    assert rows["t1"].platform == "teams"
    assert result.events_upserted == 3


def test_an_event_with_no_conference_link_is_not_mirrored(db):
    """A plain calendar block is not a meeting this module has any business with."""
    from modules.meetings.models import CalendarEvent

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    source = FakeCalendarSource(
        {
            user.email: [
                SyncPage(
                    events=[raw_event("lunch", starts_at=utc(2026, 9, 1, 5), conference_url=None)]
                )
            ]
        }
    )
    _sync(db, source)

    assert db.query(CalendarEvent).count() == 0


def test_upsert_refreshes_the_event_without_duplicating_it(db):
    """A second sync of the same event updates it in place."""
    from modules.meetings.models import CalendarEvent

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    first = FakeCalendarSource(
        {user.email: [SyncPage(events=[raw_event("g1", starts_at=utc(2026, 9, 1, 2))])]}
    )
    _sync(db, first)
    second = FakeCalendarSource(
        {
            user.email: [
                SyncPage(
                    events=[
                        raw_event("g1", starts_at=utc(2026, 9, 1, 4), title="Moved sync")
                    ]
                )
            ]
        }
    )
    _sync(db, second)

    rows = db.query(CalendarEvent).all()
    assert len(rows) == 1
    assert rows[0].title == "Moved sync"
    assert rows[0].starts_at == utc(2026, 9, 1, 4)


# ── AC-S0-8: the opt-out survives a sync ─────────────────────────────────────


def test_a_later_sync_never_flips_the_opt_out_back(db):
    """AC-S0-8: the user's decision outranks anything the calendar says."""
    from modules.meetings.models import CalendarEvent

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    source = FakeCalendarSource(
        {user.email: [SyncPage(events=[raw_event("g1", starts_at=utc(2026, 9, 1, 2))])]}
    )
    _sync(db, source)
    row = db.query(CalendarEvent).one()
    row.opted_out = True
    db.commit()

    _sync(db, source)
    assert db.query(CalendarEvent).one().opted_out is True


# ── AC-S0-10: cancelled / link removed ───────────────────────────────────────


def test_a_cancelled_event_disappears(db):
    """AC-S0-10: the calendar dropped it, so the mirror drops it."""
    from modules.meetings.models import CalendarEvent

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    _sync(
        db,
        FakeCalendarSource(
            {user.email: [SyncPage(events=[raw_event("g1", starts_at=utc(2026, 9, 1, 2))])]}
        ),
    )
    assert db.query(CalendarEvent).count() == 1

    result = _sync(
        db,
        FakeCalendarSource(
            {
                user.email: [
                    SyncPage(events=[raw_event("g1", starts_at=utc(2026, 9, 1, 2), cancelled=True)])
                ]
            }
        ),
    )
    assert db.query(CalendarEvent).count() == 0
    assert result.events_deleted == 1


def test_removing_the_link_removes_the_row(db):
    """AC-S0-10: an event that lost its Meet link is no longer a meeting."""
    from modules.meetings.models import CalendarEvent

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    _sync(
        db,
        FakeCalendarSource(
            {user.email: [SyncPage(events=[raw_event("g1", starts_at=utc(2026, 9, 1, 2))])]}
        ),
    )
    result = _sync(
        db,
        FakeCalendarSource(
            {
                user.email: [
                    SyncPage(
                        events=[
                            raw_event("g1", starts_at=utc(2026, 9, 1, 2), conference_url=None)
                        ]
                    )
                ]
            }
        ),
    )
    assert db.query(CalendarEvent).count() == 0
    assert result.events_deleted == 1


# ── AC-S0-11: incremental token + the 410 fallback + the activity row ────────


def test_the_sync_token_is_stored_and_reused(db):
    """AC-S0-11: the first read is a full window; the next carries the token."""
    from modules.meetings.models import UserOptIn

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    source = FakeCalendarSource(
        {
            user.email: [
                SyncPage(events=[raw_event("g1", starts_at=utc(2026, 9, 1, 2))], next_sync_token="tok-1"),
                SyncPage(events=[], next_sync_token="tok-2"),
            ]
        }
    )
    _sync(db, source)
    row = db.query(UserOptIn).filter(UserOptIn.user_id == user.id).one()
    assert row.sync_token == "tok-1"
    assert row.last_synced_at is not None
    assert source.calls[0]["sync_token"] is None
    assert source.calls[0]["time_min"] is not None
    assert source.calls[0]["time_max"] is not None

    _sync(db, source)
    assert source.calls[1]["sync_token"] == "tok-1"
    assert db.query(UserOptIn).filter(UserOptIn.user_id == user.id).one().sync_token == "tok-2"


def test_an_expired_token_falls_back_to_the_full_window(db):
    """AC-S0-11: HTTP 410 drops the token and refetches 14 days."""
    from modules.meetings.models import CalendarEvent, UserOptIn

    user = _demo_user(db)
    row = opt_in(db, DEFAULT_TENANT_ID, user.id)
    row.sync_token = "stale"
    db.commit()

    source = FakeCalendarSource(
        {
            user.email: [
                SyncPage(events=[raw_event("g1", starts_at=utc(2026, 9, 1, 2))], next_sync_token="fresh")
            ]
        },
        invalid_token_for=user.email,
    )
    result = _sync(db, source)

    assert [c["sync_token"] for c in source.calls] == ["stale", None]
    assert source.calls[1]["time_min"] is not None and source.calls[1]["time_max"] is not None
    assert db.query(CalendarEvent).count() == 1
    assert db.query(UserOptIn).filter(UserOptIn.user_id == user.id).one().sync_token == "fresh"
    assert result.errors == []


def test_a_calendar_error_is_recorded_and_does_not_stop_the_run(db):
    """One user's broken calendar must not cost the tenant its whole sync."""
    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    source = FakeCalendarSource({}, error_for=user.email)
    result = _sync(db, source)

    assert result.errors and "calendar usage limits exceeded" in result.errors[0]
    assert result.users_synced == 0


def test_the_run_writes_one_integration_activity_row(db):
    """AC-S0-11: one row per run, carrying the counts."""
    from app.models.integration_activity import IntegrationActivity
    from modules.meetings.services.calendar_sync import record_sync_activity

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    source = FakeCalendarSource(
        {user.email: [SyncPage(events=[raw_event("g1", starts_at=utc(2026, 9, 1, 2))])]}
    )
    result = _sync(db, source)
    record_sync_activity(db, DEFAULT_TENANT_ID, result)

    rows = (
        db.query(IntegrationActivity)
        .filter(IntegrationActivity.tenant_id == DEFAULT_TENANT_ID)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].source == "meetings"
    assert rows[0].operation == "calendar.sync"
    assert rows[0].status == "success"
    assert rows[0].response_summary_json["eventsUpserted"] == 1
    assert rows[0].response_summary_json["usersSynced"] == 1


# ── AC-S0-12: one meeting per link + start, across two invitees ──────────────


def test_two_invitees_produce_two_events_but_one_meeting(db):
    """AC-S0-12: the dedupe key is the conference link plus the start."""
    from modules.meetings.models import CalendarEvent, Meeting, MeetingParticipant

    demo = _demo_user(db)
    colleague = make_admin_user(db, DEFAULT_TENANT_ID, "colleague@example.com", name="Colleague")
    opt_in(db, DEFAULT_TENANT_ID, demo.id)
    opt_in(db, DEFAULT_TENANT_ID, colleague.id)
    db.commit()

    attendees = [
        {"email": demo.email, "displayName": "Demo User"},
        {"email": colleague.email, "displayName": "Colleague"},
        {"email": "outsider@vendor.example", "displayName": None},
    ]
    shared = dict(
        starts_at=utc(2026, 9, 1, 2),
        ends_at=utc(2026, 9, 1, 3),
        conference_url="https://meet.google.com/abc-defg-hij",
        attendees=attendees,
    )
    source = FakeCalendarSource(
        {
            demo.email: [SyncPage(events=[raw_event("demo-copy", **shared)])],
            colleague.email: [SyncPage(events=[raw_event("colleague-copy", **shared)])],
        }
    )
    _sync(db, source)

    assert db.query(CalendarEvent).count() == 2
    meetings = db.query(Meeting).all()
    assert len(meetings) == 1
    assert meetings[0].dedupe_key == "https://meet.google.com/abc-defg-hij|2026-09-01T02:00:00+00:00"
    assert meetings[0].status == "scheduled"

    participants = (
        db.query(MeetingParticipant)
        .filter(MeetingParticipant.meeting_id == meetings[0].id)
        .all()
    )
    by_email = {p.email: p for p in participants}
    assert set(by_email) == {demo.email, colleague.email, "outsider@vendor.example"}
    # Tenant users resolve to a user_id and carry their opt-in snapshot; an
    # external attendee resolves to neither.
    assert by_email[demo.email].user_id == demo.id
    assert by_email[demo.email].is_opted_in is True
    assert by_email["outsider@vendor.example"].user_id is None
    assert by_email["outsider@vendor.example"].is_opted_in is False


def test_the_same_link_at_a_different_start_is_a_different_meeting(db):
    """A recurring standup on the same room link is one meeting PER occurrence."""
    from modules.meetings.models import Meeting

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    source = FakeCalendarSource(
        {
            user.email: [
                SyncPage(
                    events=[
                        raw_event("mon", starts_at=utc(2026, 9, 1, 2)),
                        raw_event("tue", starts_at=utc(2026, 9, 2, 2)),
                    ]
                )
            ]
        }
    )
    _sync(db, source)

    assert db.query(Meeting).count() == 2


def test_a_second_sync_does_not_duplicate_the_meeting(db):
    """The dedupe row is created once, however often the sync runs."""
    from modules.meetings.models import Meeting, MeetingParticipant

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    source = FakeCalendarSource(
        {
            user.email: [
                SyncPage(
                    events=[
                        raw_event(
                            "g1",
                            starts_at=utc(2026, 9, 1, 2),
                            attendees=[{"email": user.email, "displayName": "Demo User"}],
                        )
                    ]
                )
            ]
        }
    )
    _sync(db, source)
    _sync(db, source)

    assert db.query(Meeting).count() == 1
    assert db.query(MeetingParticipant).count() == 1


# ── AC-S0-13: the sync itself is tenant-scoped ───────────────────────────────


def test_sync_writes_only_into_its_own_tenant(db):
    """AC-S0-13: syncing tenant B leaves tenant A's rows alone, same email or not."""
    from app.services.app_store_service import AppStoreService
    from modules.meetings.models import CalendarEvent

    demo = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, demo.id)
    make_tenant(db, OTHER_TENANT_ID, "Other Co")
    AppStoreService(db).install(OTHER_TENANT_ID, "meetings")
    other = make_admin_user(db, OTHER_TENANT_ID, "other@example.com")
    opt_in(db, OTHER_TENANT_ID, other.id)
    db.commit()

    source = FakeCalendarSource(
        {
            demo.email: [SyncPage(events=[raw_event("mine", starts_at=utc(2026, 9, 1, 2))])],
            other.email: [SyncPage(events=[raw_event("theirs", starts_at=utc(2026, 9, 1, 2))])],
        }
    )
    _sync(db, source, tenant_id=OTHER_TENANT_ID)

    assert [c["user_email"] for c in source.calls] == [other.email]
    assert (
        db.query(CalendarEvent).filter(CalendarEvent.tenant_id == DEFAULT_TENANT_ID).count() == 0
    )
    assert (
        db.query(CalendarEvent).filter(CalendarEvent.tenant_id == OTHER_TENANT_ID).count() == 1
    )
