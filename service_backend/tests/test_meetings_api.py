"""Meetings HTTP surface - AC-S0-6, AC-S0-7, AC-S0-8, AC-S0-9, AC-S0-13.

Everything here goes through the real routes with a real token, so what is
pinned is the contract the frontend binds to: the master toggle, the caller's
own upcoming events, the per-event opt-out, and the tenant scoping that must
hold across every one of them.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID, User
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.meetings_helpers import make_admin_user, make_tenant

OTHER_TENANT_ID = "44444444-4444-4444-4444-444444444444"
OTHER_EMAIL = "other@example.com"

# Seeded RELATIVE to now: a fixed calendar date turns the suite red the day it
# passes, and "upcoming" is the whole point of the window these rows sit in.
TOMORROW = datetime.now(timezone.utc) + timedelta(days=1)


@pytest.fixture
def meetings_client(meetings_session_factory):
    def override_get_db():
        db = meetings_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = meetings_session_factory
        yield c
    app.dependency_overrides.clear()


def _auth(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, slug=None) -> dict:
    # Login resolves the tenant from its slug, so a second tenant's user must
    # name theirs - exactly as a real subdomain sign-in does.
    body = {"email": email, "password": password}
    if slug:
        body["tenantSlug"] = slug
    res = client.post("/auth/login", json=body)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _demo_user_id(db) -> str:
    return db.query(User).filter(User.email == ACTIVE_EMAIL).one().id


def _seed_event(db, *, tenant_id: str, calendar_user_id: str, external_id: str, **kw):
    from modules.meetings.models import CalendarEvent

    row = CalendarEvent(
        tenant_id=tenant_id,
        external_id=external_id,
        calendar_user_id=calendar_user_id,
        title=kw.get("title", "Weekly product sync"),
        organiser_email=kw.get("organiser_email", "ops@example.com"),
        attendees_json=kw.get(
            "attendees_json",
            [
                {"email": "ops@example.com", "displayName": "Ops"},
                {"email": ACTIVE_EMAIL, "displayName": "Demo User"},
            ],
        ),
        conference_url=kw.get("conference_url", "https://meet.google.com/abc-defg-hij"),
        platform=kw.get("platform", "meet"),
        starts_at=kw.get("starts_at", TOMORROW),
        ends_at=kw.get("ends_at", TOMORROW + timedelta(hours=1)),
        opted_out=kw.get("opted_out", False),
    )
    db.add(row)
    db.flush()
    return row


# ── AC-S0-6 / AC-S0-9: the master toggle ─────────────────────────────────────


def test_optin_is_off_by_default(meetings_client):
    """AC-S0-6: a user who has never touched it is opted OUT."""
    from modules.meetings.models import UserOptIn

    res = meetings_client.get("/meetings/optin", headers=_auth(meetings_client))
    assert res.status_code == 200, res.text
    assert res.json() == {"enabled": False, "lastSyncedAt": None}

    # Reading is a read: never insert a row just because someone looked.
    db = meetings_client._factory()
    try:
        assert db.query(UserOptIn).count() == 0
    finally:
        db.close()


def test_optin_can_be_flipped_both_ways(meetings_client):
    """AC-S0-6 / AC-S0-9: on, then off; the read reflects the last write."""
    headers = _auth(meetings_client)
    on = meetings_client.put("/meetings/optin", headers=headers, json={"enabled": True})
    assert on.status_code == 200, on.text
    assert on.json()["enabled"] is True
    assert meetings_client.get("/meetings/optin", headers=headers).json()["enabled"] is True

    off = meetings_client.put("/meetings/optin", headers=headers, json={"enabled": False})
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False


def test_optin_off_hides_events_but_keeps_the_rows(meetings_client):
    """AC-S0-9: switching off stops the list; the mirrored rows are NOT deleted."""
    from modules.meetings.models import CalendarEvent

    headers = _auth(meetings_client)
    db = meetings_client._factory()
    try:
        user_id = _demo_user_id(db)
        _seed_event(db, tenant_id=DEFAULT_TENANT_ID, calendar_user_id=user_id, external_id="e1")
        db.commit()
    finally:
        db.close()

    meetings_client.put("/meetings/optin", headers=headers, json={"enabled": True})
    assert len(meetings_client.get("/meetings/events", headers=headers).json()["data"]) == 1

    meetings_client.put("/meetings/optin", headers=headers, json={"enabled": False})
    assert meetings_client.get("/meetings/events", headers=headers).json()["data"] == []

    db = meetings_client._factory()
    try:
        assert db.query(CalendarEvent).count() == 1
    finally:
        db.close()


# ── AC-S0-7 / AC-S0-8: the events list + the per-event opt-out ───────────────


def test_events_carry_everything_the_row_renders(meetings_client):
    """AC-S0-7: title, start, end, organiser, attendee count, platform, opt-out."""
    headers = _auth(meetings_client)
    db = meetings_client._factory()
    try:
        _seed_event(
            db,
            tenant_id=DEFAULT_TENANT_ID,
            calendar_user_id=_demo_user_id(db),
            external_id="e1",
        )
        db.commit()
    finally:
        db.close()
    meetings_client.put("/meetings/optin", headers=headers, json={"enabled": True})

    row = meetings_client.get("/meetings/events", headers=headers).json()["data"][0]
    assert row["title"] == "Weekly product sync"
    assert row["organiserEmail"] == "ops@example.com"
    assert row["attendeeCount"] == 2
    assert row["attendees"][0]["email"] == "ops@example.com"
    assert row["platform"] == "meet"
    assert row["conferenceUrl"].startswith("https://meet.google.com/")
    assert row["optedOut"] is False
    # Wire datetimes are Z-suffixed UTC (ApiModel), never a naive local string.
    assert row["startsAt"].endswith("Z")
    assert row["endsAt"].endswith("Z")


def test_events_are_scoped_to_the_calling_user(meetings_client):
    """A colleague's calendar row is not the caller's business - same tenant or not."""
    headers = _auth(meetings_client)
    db = meetings_client._factory()
    try:
        colleague = make_admin_user(db, DEFAULT_TENANT_ID, "colleague@example.com")
        _seed_event(
            db, tenant_id=DEFAULT_TENANT_ID, calendar_user_id=colleague.id, external_id="e-col"
        )
        _seed_event(
            db,
            tenant_id=DEFAULT_TENANT_ID,
            calendar_user_id=_demo_user_id(db),
            external_id="e-mine",
        )
        db.commit()
    finally:
        db.close()
    meetings_client.put("/meetings/optin", headers=headers, json={"enabled": True})

    rows = meetings_client.get("/meetings/events", headers=headers).json()["data"]
    assert len(rows) == 1
    assert rows[0]["title"] == "Weekly product sync"


def test_event_opt_out_sticks_and_the_row_stays(meetings_client):
    """AC-S0-8: the flag is written, the row is still listed, and it can be undone."""
    headers = _auth(meetings_client)
    db = meetings_client._factory()
    try:
        _seed_event(
            db,
            tenant_id=DEFAULT_TENANT_ID,
            calendar_user_id=_demo_user_id(db),
            external_id="e1",
        )
        db.commit()
    finally:
        db.close()
    meetings_client.put("/meetings/optin", headers=headers, json={"enabled": True})
    event_id = meetings_client.get("/meetings/events", headers=headers).json()["data"][0]["id"]

    out = meetings_client.put(
        f"/meetings/events/{event_id}/opt-out", headers=headers, json={"optedOut": True}
    )
    assert out.status_code == 200, out.text
    assert out.json()["optedOut"] is True

    rows = meetings_client.get("/meetings/events", headers=headers).json()["data"]
    assert len(rows) == 1 and rows[0]["optedOut"] is True

    back = meetings_client.put(
        f"/meetings/events/{event_id}/opt-out", headers=headers, json={"optedOut": False}
    )
    assert back.json()["optedOut"] is False


def test_event_opt_out_rejects_someone_elses_event(meetings_client):
    """The opt-out is a write - it must not reach another user's calendar row."""
    headers = _auth(meetings_client)
    db = meetings_client._factory()
    try:
        colleague = make_admin_user(db, DEFAULT_TENANT_ID, "colleague2@example.com")
        row = _seed_event(
            db, tenant_id=DEFAULT_TENANT_ID, calendar_user_id=colleague.id, external_id="e-col"
        )
        db.commit()
        foreign_id = row.id
    finally:
        db.close()
    meetings_client.put("/meetings/optin", headers=headers, json={"enabled": True})

    res = meetings_client.put(
        f"/meetings/events/{foreign_id}/opt-out", headers=headers, json={"optedOut": True}
    )
    assert res.status_code == 404, res.text


# ── AC-S0-13: cross-tenant isolation ─────────────────────────────────────────


def test_no_cross_tenant_events(meetings_client):
    """AC-S0-13: tenant A never sees a tenant B row, even at the same user email."""
    from app.services.app_store_service import AppStoreService

    db = meetings_client._factory()
    try:
        make_tenant(db, OTHER_TENANT_ID, "Other Co")
        AppStoreService(db).install(OTHER_TENANT_ID, "meetings")
        other_user = make_admin_user(db, OTHER_TENANT_ID, OTHER_EMAIL)
        _seed_event(
            db,
            tenant_id=OTHER_TENANT_ID,
            calendar_user_id=other_user.id,
            external_id="e-other",
            title="Other tenant standup",
        )
        _seed_event(
            db,
            tenant_id=DEFAULT_TENANT_ID,
            calendar_user_id=_demo_user_id(db),
            external_id="e-mine",
        )
        db.commit()
    finally:
        db.close()

    mine = _auth(meetings_client)
    theirs = _auth(meetings_client, email=OTHER_EMAIL, password="demo1234", slug="other-co")
    meetings_client.put("/meetings/optin", headers=mine, json={"enabled": True})
    meetings_client.put("/meetings/optin", headers=theirs, json={"enabled": True})

    my_rows = meetings_client.get("/meetings/events", headers=mine).json()["data"]
    their_rows = meetings_client.get("/meetings/events", headers=theirs).json()["data"]
    assert [r["title"] for r in my_rows] == ["Weekly product sync"]
    assert [r["title"] for r in their_rows] == ["Other tenant standup"]

    # And a cross-tenant id is a 404, never a silent write.
    res = meetings_client.put(
        f"/meetings/events/{their_rows[0]['id']}/opt-out",
        headers=mine,
        json={"optedOut": True},
    )
    assert res.status_code == 404, res.text


def test_settings_are_tenant_scoped(meetings_client):
    """AC-S0-13: one tenant's settings write never lands on another's row."""
    from app.services.app_store_service import AppStoreService

    db = meetings_client._factory()
    try:
        make_tenant(db, OTHER_TENANT_ID, "Other Co")
        AppStoreService(db).install(OTHER_TENANT_ID, "meetings")
        make_admin_user(db, OTHER_TENANT_ID, OTHER_EMAIL)
        db.commit()
    finally:
        db.close()

    mine = _auth(meetings_client)
    theirs = _auth(meetings_client, email=OTHER_EMAIL, password="demo1234", slug="other-co")

    saved = meetings_client.put(
        "/meetings/settings",
        headers=mine,
        json={"minutesLanguage": "ms", "audioRetentionDays": 0, "botDisplayName": "Scribe"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["minutesLanguage"] == "ms"
    assert saved.json()["audioRetentionDays"] == 0

    other = meetings_client.get("/meetings/settings", headers=theirs).json()
    assert other["minutesLanguage"] == "en"
    assert other["audioRetentionDays"] == 90
    assert other["botDisplayName"] is None


def test_settings_needs_the_settings_permission(meetings_client):
    """The settings surface is gated separately from the personal one."""
    from app.models.role import Role

    db = meetings_client._factory()
    try:
        viewer_role = Role(
            tenant_id=DEFAULT_TENANT_ID, name="Viewer", description="Meetings only"
        )
        from app.models.permission import Permission

        viewer_role.permissions = [
            db.query(Permission).filter(Permission.key == "meetings.view").one()
        ]
        db.add(viewer_role)
        db.flush()
        viewer = make_admin_user(db, DEFAULT_TENANT_ID, "viewer@example.com")
        viewer.roles = [viewer_role]
        db.commit()
    finally:
        db.close()

    headers = _auth(meetings_client, email="viewer@example.com", password="demo1234")
    assert meetings_client.get("/meetings/optin", headers=headers).status_code == 200
    assert meetings_client.get("/meetings/settings", headers=headers).status_code == 403
