"""What the two S2 surfaces actually receive — AC-S2-11, AC-S2-12, AC-S2-3.

Both are read-only, and both are tenant- and permission-scoped like everything
else in the module: My meetings is the caller's own calendar, bot runs are the
tenant admin's ops view.
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from modules.meetings.models import (
    STATUS_FAILED,
    STATUS_NOT_ADMITTED,
    STATUS_READY,
    STATUS_SCHEDULED,
    CalendarEvent,
    Meeting,
)
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.meetings_helpers import make_admin_user, opt_in, utc

MEET_URL = "https://meet.google.com/abc-defg-hij"


def soon(hours: float = 1.0):
    """A time inside the events window, RELATIVE to now.

    A fixed date would put every seeded meeting outside the 14-day window the
    events list reads the day the suite is run past it - the S0 trap, once.
    """
    from datetime import datetime, timedelta as _td, timezone

    return datetime.now(timezone.utc) + _td(hours=hours)


@pytest.fixture
def meetings_client(meetings_session_factory):
    def override_get_db():
        session = meetings_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = meetings_session_factory
        yield c
    app.dependency_overrides.clear()


def _auth(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _seed(
    session,
    *,
    status=STATUS_SCHEDULED,
    reason=None,
    starts_at=None,
    url=MEET_URL,
    duration_s=None,
):
    """One calendar row for the demo user plus the meeting behind it."""
    from app.models import User
    from modules.meetings.services.calendar_sync import dedupe_key

    starts_at = starts_at or soon()
    user = session.query(User).filter(User.email == ACTIVE_EMAIL).one()
    opt_in(session, DEFAULT_TENANT_ID, user.id)
    event = CalendarEvent(
        tenant_id=DEFAULT_TENANT_ID,
        external_id=f"g-{url[-6:]}",
        calendar_user_id=user.id,
        title="Weekly product sync",
        conference_url=url,
        platform="meet",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
    )
    meeting = Meeting(
        tenant_id=DEFAULT_TENANT_ID,
        dedupe_key=dedupe_key(url, starts_at),
        title="Weekly product sync",
        conference_url=url,
        platform="meet",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        status=status,
        status_reason=reason,
        duration_s=duration_s,
    )
    session.add_all([event, meeting])
    session.commit()
    return user, event, meeting


def _events(client, headers):
    res = client.get("/meetings/events", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["data"]


# ── AC-S2-11: status on My meetings ──────────────────────────────────────────


def test_an_event_carries_the_status_of_the_meeting_behind_it(meetings_client):
    session = meetings_client._factory()
    try:
        _seed(session, status=STATUS_READY)
    finally:
        session.close()

    row = _events(meetings_client, _auth(meetings_client))[0]
    assert row["meetingStatus"] == STATUS_READY
    assert row["statusReason"] is None


def test_a_not_admitted_row_carries_the_reason(meetings_client):
    session = meetings_client._factory()
    try:
        _seed(session, status=STATUS_NOT_ADMITTED, reason="denied")
    finally:
        session.close()

    row = _events(meetings_client, _auth(meetings_client))[0]
    assert row["meetingStatus"] == STATUS_NOT_ADMITTED
    assert row["statusReason"] == "denied"


def test_a_failed_row_carries_the_reason_too(meetings_client):
    session = meetings_client._factory()
    try:
        _seed(session, status=STATUS_FAILED, reason="error:TimeoutError:join button")
    finally:
        session.close()

    row = _events(meetings_client, _auth(meetings_client))[0]
    assert row["meetingStatus"] == STATUS_FAILED
    assert "TimeoutError" in row["statusReason"]


def test_an_event_whose_meeting_row_is_not_there_yet_reads_scheduled(meetings_client):
    """The sync writes the event and the meeting in one pass, so this is a
    transient state - it must read as "nothing has happened", never as a gap."""
    session = meetings_client._factory()
    try:
        _seed(session)
        session.query(Meeting).delete()
        session.commit()
    finally:
        session.close()

    row = _events(meetings_client, _auth(meetings_client))[0]
    assert row["meetingStatus"] == STATUS_SCHEDULED
    assert row["statusReason"] is None


def test_the_opt_out_write_answers_with_the_status_too(meetings_client):
    """The row re-renders from this response, so it has to carry everything the
    list does or the badge would blank out on a toggle."""
    session = meetings_client._factory()
    try:
        _, event, _ = _seed(session, status=STATUS_NOT_ADMITTED, reason="denied")
        event_id = event.id
    finally:
        session.close()

    res = meetings_client.put(
        f"/meetings/events/{event_id}/opt-out",
        headers=_auth(meetings_client),
        json={"optedOut": True},
    )
    assert res.status_code == 200, res.text
    assert res.json()["meetingStatus"] == STATUS_NOT_ADMITTED
    assert res.json()["statusReason"] == "denied"


def test_two_invitees_of_one_meeting_see_the_same_status(meetings_client):
    """AC-S2-3 from the user's side: one meeting, one bot, one answer."""
    session = meetings_client._factory()
    try:
        _, _, meeting = _seed(session, status=STATUS_READY)
        second = make_admin_user(session, DEFAULT_TENANT_ID, "second@example.com", name="Second")
        opt_in(session, DEFAULT_TENANT_ID, second.id)
        session.add(
            CalendarEvent(
                tenant_id=DEFAULT_TENANT_ID,
                external_id="g-second",
                calendar_user_id=second.id,
                title=meeting.title,
                conference_url=meeting.conference_url,
                platform="meet",
                starts_at=meeting.starts_at,
                ends_at=meeting.ends_at,
            )
        )
        session.commit()
    finally:
        session.close()

    mine = _events(meetings_client, _auth(meetings_client))
    theirs = _events(meetings_client, _auth(meetings_client, "second@example.com"))

    assert len(mine) == 1 and len(theirs) == 1
    assert mine[0]["id"] != theirs[0]["id"]  # two calendar rows
    assert mine[0]["meetingStatus"] == theirs[0]["meetingStatus"] == STATUS_READY


# ── AC-S2-12: the bot-runs list ──────────────────────────────────────────────


def _run_job(session, meeting, *, status="done", result=None, error=None, created_at=None):
    from app.models.background_job import BackgroundJob
    from modules.meetings.jobs import BOT_RUN

    job = BackgroundJob(
        tenant_id=meeting.tenant_id,
        type=BOT_RUN,
        status=status,
        payload_json={"meeting_id": meeting.id, "tenant_id": meeting.tenant_id},
        result_json=result,
        error=error,
        started_at=meeting.starts_at,
        finished_at=meeting.starts_at + timedelta(minutes=58),
    )
    session.add(job)
    session.flush()
    if created_at is not None:
        job.created_at = created_at
    session.commit()
    return job


def test_a_run_is_listed_with_everything_the_page_renders(meetings_client):
    session = meetings_client._factory()
    try:
        _, _, meeting = _seed(session, status=STATUS_READY, duration_s=3480)
        _run_job(session, meeting, result={"reason": "room_empty"})
    finally:
        session.close()

    res = meetings_client.get("/meetings/bot-runs", headers=_auth(meetings_client))
    assert res.status_code == 200, res.text
    rows = res.json()["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["meetingTitle"] == "Weekly product sync"
    assert row["exitReason"] == "room_empty"
    assert row["durationS"] == 3480
    assert row["meetingStatus"] == STATUS_READY
    assert row["startedAt"] and row["endedAt"]


def test_a_failed_run_reports_the_jobs_error_when_the_bot_gave_no_reason(meetings_client):
    session = meetings_client._factory()
    try:
        _, _, meeting = _seed(session, status=STATUS_FAILED, reason="error:boom")
        _run_job(
            session,
            meeting,
            status="failed",
            error="The bot container could not start: No such image",
        )
    finally:
        session.close()

    rows = meetings_client.get(
        "/meetings/bot-runs", headers=_auth(meetings_client)
    ).json()["data"]
    assert "No such image" in rows[0]["exitReason"]


def test_the_window_is_a_week_by_default(meetings_client):
    session = meetings_client._factory()
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        _, _, recent = _seed(session, status=STATUS_READY, starts_at=now - timedelta(days=2))
        _, _, old = _seed(
            session,
            status=STATUS_READY,
            starts_at=now - timedelta(days=30),
            url="https://meet.google.com/old-oldd-old",
        )
        _run_job(session, recent, result={"reason": "room_empty"}, created_at=now - timedelta(days=2))
        _run_job(session, old, result={"reason": "ended"}, created_at=now - timedelta(days=30))
    finally:
        session.close()

    headers = _auth(meetings_client)
    week = meetings_client.get("/meetings/bot-runs", headers=headers).json()["data"]
    assert [r["exitReason"] for r in week] == ["room_empty"]

    month = meetings_client.get(
        "/meetings/bot-runs", headers=headers, params={"days": 60}
    ).json()["data"]
    assert len(month) == 2


def test_bot_runs_need_the_settings_permission(meetings_client):
    """A user who may manage their OWN capture has no business over the
    tenant's ops data."""
    from app.models import Role, User, UserStatus
    from app.security import hash_password
    from app.repositories.permission_repository import PermissionRepository

    session = meetings_client._factory()
    try:
        role = Role(tenant_id=DEFAULT_TENANT_ID, name="Viewer", description="View only")
        role.permissions = [
            p
            for p in PermissionRepository(session).list_all()
            if p.key == "meetings.view"
        ]
        session.add(role)
        session.flush()
        user = User(
            tenant_id=DEFAULT_TENANT_ID,
            email="viewer@example.com",
            password=hash_password("demo1234"),
            name="Viewer",
            status=UserStatus.ACTIVE.value,
        )
        from sqlalchemy.sql import func

        user.email_verified_at = func.now()
        user.roles = [role]
        session.add(user)
        session.commit()
    finally:
        session.close()

    res = meetings_client.get(
        "/meetings/bot-runs", headers=_auth(meetings_client, "viewer@example.com", "demo1234")
    )
    assert res.status_code == 403, res.text


def test_bot_runs_are_scoped_to_the_calling_tenant(meetings_client):
    from app.services.app_store_service import AppStoreService
    from tests.meetings_helpers import make_tenant

    other_id = "99999999-9999-9999-9999-999999999999"
    session = meetings_client._factory()
    try:
        make_tenant(session, other_id, "Other Co")
        AppStoreService(session).install(other_id, "meetings")
        make_admin_user(session, other_id, "other@example.com")
        from modules.meetings.services.calendar_sync import dedupe_key

        starts_at = soon()
        other_meeting = Meeting(
            tenant_id=other_id,
            dedupe_key=dedupe_key(MEET_URL, starts_at),
            title="Their meeting",
            conference_url=MEET_URL,
            platform="meet",
            starts_at=starts_at,
            status=STATUS_READY,
        )
        session.add(other_meeting)
        session.flush()
        _run_job(session, other_meeting, result={"reason": "ended"})

        _, _, mine = _seed(session, status=STATUS_READY, url="https://meet.google.com/mine-mine-mi")
        _run_job(session, mine, result={"reason": "room_empty"})
    finally:
        session.close()

    rows = meetings_client.get(
        "/meetings/bot-runs", headers=_auth(meetings_client)
    ).json()["data"]
    assert [r["meetingTitle"] for r in rows] == ["Weekly product sync"]
