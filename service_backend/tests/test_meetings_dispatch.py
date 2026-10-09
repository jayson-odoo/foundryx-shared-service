"""Who gets a bot, and when - AC-S2-1, AC-S2-2, AC-S2-3, AC-S2-4, AC-S2-9.

The tick is the only thing in S2 with no human in the loop at all, so what is
pinned here is every way it can decide NOT to dispatch, and that deciding twice
never dispatches twice.
"""
from datetime import timedelta

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.meetings.models import (
    STATUS_JOINING,
    STATUS_SCHEDULED,
    STATUS_SKIPPED,
    CalendarEvent,
    Meeting,
    MeetingParticipant,
)
from tests.conftest import ACTIVE_EMAIL
from tests.meetings_helpers import make_admin_user, make_tenant, opt_in, utc

OTHER_TENANT_ID = "77777777-7777-7777-7777-777777777777"
MEET_URL = "https://meet.google.com/abc-defg-hij"
NOW = utc(2026, 9, 1, 2, 0)


@pytest.fixture
def db(meetings_session_factory):
    session = meetings_session_factory()
    yield session
    session.close()


def _demo_user(session):
    from app.models import User

    return session.query(User).filter(User.email == ACTIVE_EMAIL).one()


# "not given" is not the same as "the calendar gave no end time", and a helper
# that conflates them silently stopped the NULL-ends_at test from testing
# anything at all.
_UNSET = object()


def _meeting(
    db,
    *,
    tenant_id=DEFAULT_TENANT_ID,
    starts_at=None,
    ends_at=_UNSET,
    url=MEET_URL,
    status=STATUS_SCHEDULED,
    title="Weekly product sync",
):
    from modules.meetings.services.calendar_sync import dedupe_key

    starts_at = starts_at or (NOW + timedelta(minutes=1))
    row = Meeting(
        tenant_id=tenant_id,
        dedupe_key=dedupe_key(url, starts_at),
        title=title,
        conference_url=url,
        platform="meet",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1) if ends_at is _UNSET else ends_at,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def _participant(db, meeting, user, *, opted_in=True):
    row = MeetingParticipant(
        tenant_id=meeting.tenant_id,
        meeting_id=meeting.id,
        email=user.email,
        display_name=user.name,
        user_id=user.id,
        is_opted_in=opted_in,
    )
    db.add(row)
    db.flush()
    return row


def _calendar_row(db, meeting, user, *, opted_out=False, external_id="g1"):
    row = CalendarEvent(
        tenant_id=meeting.tenant_id,
        external_id=external_id,
        calendar_user_id=user.id,
        title=meeting.title,
        conference_url=meeting.conference_url,
        platform="meet",
        starts_at=meeting.starts_at,
        ends_at=meeting.ends_at,
        opted_out=opted_out,
    )
    db.add(row)
    db.flush()
    return row


def _ready_meeting(db, **kwargs):
    """A meeting with one opted-in participant who has not opted the event out."""
    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    meeting = _meeting(db, **kwargs)
    _participant(db, meeting, user)
    _calendar_row(db, meeting, user)
    db.commit()
    return meeting, user


def _bot_jobs(db, tenant_id=DEFAULT_TENANT_ID):
    from app.models.background_job import BackgroundJob
    from modules.meetings.jobs import BOT_RUN

    return (
        db.query(BackgroundJob)
        .filter(BackgroundJob.tenant_id == tenant_id, BackgroundJob.type == BOT_RUN)
        .all()
    )


@pytest.fixture(autouse=True)
def no_inline_run(monkeypatch):
    """Dispatch is what is under test, not the run. Eager mode would otherwise
    execute the bot handler inline and reach for Docker.

    Hands the REAL function back, so the two tests that are about the enqueue
    seam itself can call it without the fixture standing in their way."""
    from modules.meetings.services import dispatch as dispatch_module

    original = dispatch_module.enqueue_bot_run
    monkeypatch.setattr(dispatch_module, "enqueue_bot_run", lambda db, job_id: None)
    return original


# ── AC-S2-1: the happy path, exactly once ────────────────────────────────────


def test_a_meeting_about_to_start_gets_exactly_one_bot(db):
    from modules.meetings.services.dispatch import dispatch_tenant

    meeting, _ = _ready_meeting(db)

    dispatched = dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    assert dispatched == [meeting.id]
    jobs = _bot_jobs(db)
    assert len(jobs) == 1
    assert jobs[0].payload_json["meeting_id"] == meeting.id
    assert jobs[0].payload_json["late"] is False
    db.refresh(meeting)
    assert meeting.status == STATUS_JOINING


def test_a_second_tick_does_not_dispatch_it_again(db):
    """AC-S2-1: idempotent by STATUS - the meeting left `scheduled` on the way
    out, so the next tick has nothing to pick up."""
    from modules.meetings.services.dispatch import dispatch_tenant

    _ready_meeting(db)
    dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)
    second = dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW + timedelta(seconds=60))

    assert second == []
    assert len(_bot_jobs(db)) == 1


def test_a_meeting_further_out_than_the_lead_is_left_alone(db):
    """The lead is two minutes; a meeting in an hour is not this tick's."""
    from modules.meetings.services.dispatch import dispatch_tenant

    meeting, _ = _ready_meeting(db, starts_at=NOW + timedelta(hours=1))

    assert dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW) == []
    db.refresh(meeting)
    assert meeting.status == STATUS_SCHEDULED


# ── AC-S2-2: nobody wants it ─────────────────────────────────────────────────


def test_a_meeting_everyone_opted_out_of_is_skipped(db):
    from modules.meetings.services.dispatch import REASON_OPTED_OUT, dispatch_tenant

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    meeting = _meeting(db)
    _participant(db, meeting, user)
    _calendar_row(db, meeting, user, opted_out=True)
    db.commit()

    assert dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW) == []
    assert _bot_jobs(db) == []
    db.refresh(meeting)
    assert meeting.status == STATUS_SKIPPED
    assert meeting.status_reason == REASON_OPTED_OUT


def test_the_master_toggle_is_read_live_not_off_the_snapshot(db):
    """AC-S2-2: switching the master toggle off before the meeting really stops
    the bot. `is_opted_in` on the participant is a SNAPSHOT for later minutes
    visibility and would have said yes here."""
    from modules.meetings.services.dispatch import REASON_OPTED_OUT, dispatch_tenant

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id, enabled=False)
    meeting = _meeting(db)
    _participant(db, meeting, user, opted_in=True)
    _calendar_row(db, meeting, user)
    db.commit()

    dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    db.refresh(meeting)
    assert meeting.status == STATUS_SKIPPED
    assert meeting.status_reason == REASON_OPTED_OUT
    assert _bot_jobs(db) == []


def test_a_meeting_with_only_external_attendees_is_skipped(db):
    """Nobody in the tenant is in the room, so nobody is entitled to minutes."""
    from modules.meetings.services.dispatch import dispatch_tenant

    meeting = _meeting(db)
    db.add(
        MeetingParticipant(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            email="stranger@vendor.example",
            user_id=None,
            is_opted_in=False,
        )
    )
    db.commit()

    dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    db.refresh(meeting)
    assert meeting.status == STATUS_SKIPPED


# ── AC-S2-3: two invitees, one bot ───────────────────────────────────────────


def test_two_invitees_of_one_meeting_produce_one_run(db):
    from modules.meetings.services.dispatch import dispatch_tenant

    first = _demo_user(db)
    second = make_admin_user(db, DEFAULT_TENANT_ID, "second@example.com", name="Second")
    opt_in(db, DEFAULT_TENANT_ID, first.id)
    opt_in(db, DEFAULT_TENANT_ID, second.id)
    meeting = _meeting(db)
    _participant(db, meeting, first)
    _participant(db, meeting, second)
    # Two calendars, two mirrored rows, ONE meeting (S0's dedupe).
    _calendar_row(db, meeting, first, external_id="g1")
    _calendar_row(db, meeting, second, external_id="g2")
    db.commit()

    dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    assert len(_bot_jobs(db)) == 1
    assert db.query(CalendarEvent).count() == 2


def test_one_invitee_opting_out_does_not_cancel_the_others_capture(db):
    """AC-S2-3 + AC-S2-2 together: the meeting is still captured for the person
    who wants it. Opting out is a personal decision, not a veto."""
    from modules.meetings.services.dispatch import dispatch_tenant

    first = _demo_user(db)
    second = make_admin_user(db, DEFAULT_TENANT_ID, "second@example.com", name="Second")
    opt_in(db, DEFAULT_TENANT_ID, first.id)
    opt_in(db, DEFAULT_TENANT_ID, second.id)
    meeting = _meeting(db)
    _participant(db, meeting, first)
    _participant(db, meeting, second)
    _calendar_row(db, meeting, first, opted_out=True, external_id="g1")
    _calendar_row(db, meeting, second, opted_out=False, external_id="g2")
    db.commit()

    dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    db.refresh(meeting)
    assert meeting.status == STATUS_JOINING
    assert len(_bot_jobs(db)) == 1


# ── S2 live-run fix: eligibility matches by calendar_email too ───────────────


def test_a_participant_matched_only_by_calendar_email_still_dispatches(db):
    """The live failure: a legacy participant row (written before this fix, or
    from a shared calendar whose attendee address is not the login email) has
    `user_id` NULL. Eligibility must still find the enabled opt-in by matching
    the participant's email against that opt-in's `calendar_email`."""
    from modules.meetings.services.dispatch import dispatch_tenant

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id, calendar_email="personal.calendar@example.com")
    meeting = _meeting(db)
    db.add(
        MeetingParticipant(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            email="personal.calendar@example.com",
            user_id=None,
            is_opted_in=False,
        )
    )
    db.commit()

    dispatched = dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    assert dispatched == [meeting.id]
    db.refresh(meeting)
    assert meeting.status == STATUS_JOINING


def test_calendar_email_eligibility_matching_is_case_insensitive(db):
    from modules.meetings.services.dispatch import dispatch_tenant

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id, calendar_email="Personal.Calendar@Example.com")
    meeting = _meeting(db)
    db.add(
        MeetingParticipant(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            email="personal.calendar@EXAMPLE.com",
            user_id=None,
            is_opted_in=False,
        )
    )
    db.commit()

    assert dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW) == [meeting.id]


def test_a_calendar_email_match_never_resurrects_a_disabled_opt_in(db):
    from modules.meetings.services.dispatch import REASON_OPTED_OUT, dispatch_tenant

    user = _demo_user(db)
    opt_in(
        db,
        DEFAULT_TENANT_ID,
        user.id,
        calendar_email="personal.calendar@example.com",
        enabled=False,
    )
    meeting = _meeting(db)
    db.add(
        MeetingParticipant(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            email="personal.calendar@example.com",
            user_id=None,
            is_opted_in=False,
        )
    )
    db.commit()

    assert dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW) == []
    db.refresh(meeting)
    assert meeting.status == STATUS_SKIPPED
    assert meeting.status_reason == REASON_OPTED_OUT


def test_login_email_matching_still_dispatches_alongside_calendar_email(db):
    """The additional calendar_email match must not replace the login-email
    path a directory-delegated tenant relies on."""
    from modules.meetings.services.dispatch import dispatch_tenant

    meeting, _user = _ready_meeting(db)

    assert dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW) == [meeting.id]


# ── AC-S2-4: late and missed ─────────────────────────────────────────────────


def test_a_meeting_that_started_20_minutes_ago_is_still_dispatched_as_late(db):
    """The worker was down. Recording the rest beats recording none of it."""
    from modules.meetings.services.dispatch import dispatch_tenant

    meeting, _ = _ready_meeting(
        db,
        starts_at=NOW - timedelta(minutes=20),
        ends_at=NOW + timedelta(minutes=40),
    )

    dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    jobs = _bot_jobs(db)
    assert len(jobs) == 1
    assert jobs[0].payload_json["late"] is True
    db.refresh(meeting)
    assert meeting.status == STATUS_JOINING


def test_a_meeting_that_has_already_ended_is_skipped_as_missed(db):
    """Joining now would record an empty room and report it as a capture."""
    from modules.meetings.services.dispatch import REASON_MISSED, dispatch_tenant

    meeting, _ = _ready_meeting(
        db,
        starts_at=NOW - timedelta(hours=2),
        ends_at=NOW - timedelta(hours=1),
    )

    dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    assert _bot_jobs(db) == []
    db.refresh(meeting)
    assert meeting.status == STATUS_SKIPPED
    assert meeting.status_reason == REASON_MISSED


def test_a_meeting_five_minutes_in_is_dispatched_but_not_flagged_late(db):
    from modules.meetings.services.dispatch import dispatch_tenant

    _ready_meeting(db, starts_at=NOW - timedelta(minutes=5))

    dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    assert _bot_jobs(db)[0].payload_json["late"] is False


# ── AC-S2-9: nothing is dropped when several start at once ───────────────────


def test_five_meetings_in_one_minute_all_get_a_job(db):
    """The worker's concurrency is the cap; the QUEUE is what holds the rest, so
    the tick must never be the thing that drops one."""
    from modules.meetings.services.dispatch import dispatch_tenant

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    for index in range(5):
        meeting = _meeting(
            db,
            url=f"https://meet.google.com/aaa-bbbb-cc{index}",
            title=f"Meeting {index}",
        )
        _participant(db, meeting, user)
        _calendar_row(db, meeting, user, external_id=f"g{index}")
    db.commit()

    dispatched = dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    assert len(dispatched) == 5
    jobs = _bot_jobs(db)
    assert len(jobs) == 5
    assert {j.status for j in jobs} == {"pending"}


# ── tenancy ──────────────────────────────────────────────────────────────────


def test_a_tick_for_one_tenant_never_touches_another(db):
    from app.services.app_store_service import AppStoreService
    from modules.meetings.services.dispatch import dispatch_tenant

    _ready_meeting(db)

    make_tenant(db, OTHER_TENANT_ID, "Other Co")
    AppStoreService(db).install(OTHER_TENANT_ID, "meetings")
    other_user = make_admin_user(db, OTHER_TENANT_ID, "other@example.com")
    opt_in(db, OTHER_TENANT_ID, other_user.id)
    other_meeting = _meeting(db, tenant_id=OTHER_TENANT_ID)
    _participant(db, other_meeting, other_user)
    _calendar_row(db, other_meeting, other_user, external_id="g-other")
    db.commit()

    dispatch_tenant(db, OTHER_TENANT_ID, now=NOW)

    assert len(_bot_jobs(db, OTHER_TENANT_ID)) == 1
    assert _bot_jobs(db, DEFAULT_TENANT_ID) == []


def test_the_beat_tick_covers_every_tenant_with_the_module(db):
    from modules.meetings.services.dispatch import dispatch_due_bot_runs

    _ready_meeting(db)

    assert dispatch_due_bot_runs(db, now=NOW) == 1
    assert len(_bot_jobs(db)) == 1


# ── review round: one bad meeting must not undo the tick's earlier decisions ─


def test_a_meeting_that_blows_up_does_not_undo_an_earlier_skip(db, monkeypatch):
    """The tick used to flush every decision and commit ONCE at the end, so the
    rollback that isolates a failing meeting also threw away every `skipped`
    already decided in that pass. Those meetings went back to `scheduled` and
    the next tick re-decided them - forever, if the bad one kept failing."""
    from modules.meetings.services import dispatch as dispatch_module

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)

    # First by start time: nobody wants it, so it is skipped.
    skipped = _meeting(
        db, starts_at=NOW, url="https://meet.google.com/aaa-aaaa-aa1", title="Skip me"
    )
    _participant(db, skipped, user)
    _calendar_row(db, skipped, user, opted_out=True, external_id="g-skip")

    # Second: it will explode on the way to being dispatched.
    boom = _meeting(
        db,
        starts_at=NOW + timedelta(seconds=30),
        url="https://meet.google.com/bbb-bbbb-bb2",
        title="Boom",
    )
    _participant(db, boom, user)
    _calendar_row(db, boom, user, external_id="g-boom")
    db.commit()

    real_wants = dispatch_module.wants_capture

    def explode(db_, m):
        if m.id == boom.id:
            raise RuntimeError("the database went away mid-tick")
        return real_wants(db_, m)

    monkeypatch.setattr(dispatch_module, "wants_capture", explode)

    dispatch_module.dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    db.expire_all()
    assert db.query(Meeting).filter(Meeting.id == skipped.id).one().status == STATUS_SKIPPED


def test_a_meeting_with_no_end_time_is_not_dispatched_weeks_later(db):
    """`ends_at` is nullable (a calendar event can arrive without one), and the
    missed guard skipped the check entirely when it was NULL - so a meeting from
    three weeks ago sat `scheduled` and got dispatched `late` the moment the
    module was installed. Treat a missing end as one hour after the start."""
    from modules.meetings.services.dispatch import REASON_MISSED, dispatch_tenant

    meeting, _ = _ready_meeting(
        db, starts_at=NOW - timedelta(days=21), ends_at=None
    )

    dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    assert _bot_jobs(db) == []
    db.refresh(meeting)
    assert meeting.status == STATUS_SKIPPED
    assert meeting.status_reason == REASON_MISSED


def test_a_meeting_with_no_end_time_starting_now_is_still_dispatched(db):
    """The other side of the same guard: an open-ended meeting about to start is
    a normal meeting."""
    from modules.meetings.services.dispatch import dispatch_tenant

    meeting, _ = _ready_meeting(db, starts_at=NOW + timedelta(minutes=1), ends_at=None)

    dispatch_tenant(db, DEFAULT_TENANT_ID, now=NOW)

    assert len(_bot_jobs(db)) == 1
    db.refresh(meeting)
    assert meeting.status == STATUS_JOINING


# ── review round: the enqueue seam itself ────────────────────────────────────


def test_enqueue_bot_run_runs_the_job_inline_under_eager(db, monkeypatch, no_inline_run):
    """Every other test patches this out, so the one line that decides whether a
    bot ever runs had no coverage at all. Under eager config it must run the job
    on THIS session - the Celery eager path would open a second one that no test
    (and no dev server) can see."""
    from app.jobs.service import JobService
    from modules.meetings.jobs import BOT_RUN

    ran = []
    monkeypatch.setattr(
        "app.jobs.service.run_job", lambda session, job_id: ran.append((session, job_id))
    )

    job = JobService(db).create(type=BOT_RUN, tenant_id=DEFAULT_TENANT_ID, payload={})
    no_inline_run(db, job.id)

    assert ran == [(db, job.id)]


def test_enqueue_bot_run_publishes_to_the_bots_queue_when_not_eager(
    db, monkeypatch, no_inline_run
):
    """And with a real worker it publishes rather than running inline - onto the
    meetings app, whose default queue is `bots`, never the app server's."""
    from app.config import settings
    from modules.meetings import worker as worker_module

    published = []
    monkeypatch.setattr(settings, "celery_task_always_eager", False)
    monkeypatch.setattr(
        worker_module.run_bot_job, "delay", lambda job_id: published.append(job_id)
    )

    no_inline_run(db, "job-123")

    assert published == ["job-123"]
    assert worker_module.celery_app.conf.task_default_queue == "bots"
