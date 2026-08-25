"""Shared-calendar mode - the access path for a tenant with NO Workspace admin.

The tenant we are onboarding cannot grant domain-wide delegation (nobody has
Workspace admin), so the service account reads calendars that each user shared
with its own address instead. One flag on the connection, two code paths, and
three facts learned from a live probe against a real service account that the
tests below pin so they cannot be lost again:

1. A calendar shared with a service account does NOT appear in that account's
   ``calendarList`` - the list comes back empty. Reading the calendar by address
   is the only proof the share was granted, so that is what Test does.
2. ``events.list`` returns NO ``nextSyncToken`` when ``orderBy`` is set, so the
   sync must never ask for an order it does not need.
3. The calendar a user can share is often NOT their login email (a Workspace can
   block sharing outward), hence ``user_opt_ins.calendar_email``.
"""
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.meetings.calendar.base import CalendarSourceError, SyncPage
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.meetings_helpers import FakeCalendarSource, opt_in, raw_event, utc

SERVICE_ACCOUNT_JSON = (
    '{"type":"service_account","client_email":"notetaker@proj.iam.gserviceaccount.com"}'
)


@pytest.fixture
def db(meetings_session_factory):
    session = meetings_session_factory()
    yield session
    session.close()


def _demo_user(session):
    from app.models import User

    return session.query(User).filter(User.email == ACTIVE_EMAIL).one()


# ── the mode flag ────────────────────────────────────────────────────────────


def test_shared_is_the_default_and_only_an_explicit_on_impersonates():
    """A tenant that never touches the field gets the mode that needs no admin."""
    from modules.meetings.calendar.google_dwd import impersonation_enabled

    assert impersonation_enabled({}) is False
    assert impersonation_enabled({"impersonate": "off"}) is False
    assert impersonation_enabled({"impersonate": ""}) is False
    assert impersonation_enabled({"impersonate": "on"}) is True
    assert impersonation_enabled({"impersonate": "true"}) is True


def test_the_source_is_built_in_the_mode_the_connection_declares():
    from modules.meetings.providers import calendar_source_from_connection

    shared = calendar_source_from_connection({}, {"serviceAccountJson": SERVICE_ACCOUNT_JSON})
    delegated = calendar_source_from_connection(
        {"impersonate": "on"}, {"serviceAccountJson": SERVICE_ACCOUNT_JSON}
    )
    assert shared._impersonate is False
    assert delegated._impersonate is True


def test_the_service_account_email_comes_off_the_key_and_the_key_does_not():
    """The address a user shares WITH is public; the key never is."""
    from modules.meetings.calendar.google_dwd import service_account_email

    assert (
        service_account_email(SERVICE_ACCOUNT_JSON)
        == "notetaker@proj.iam.gserviceaccount.com"
    )
    assert service_account_email("not json") is None
    assert service_account_email("") is None


# ── which calendar the two modes read ────────────────────────────────────────


class _RecordingGoogle:
    """Stands in for the Google client: records how the request was shaped."""

    def __init__(self, response=None):
        self.response = response or {"items": []}
        self.calls = []
        self.subjects = []

    def events(self):
        return self

    def list(self, **params):
        self.calls.append(params)
        return self

    def execute(self):
        return self.response


def _patch_google(monkeypatch, fake):
    from modules.meetings.calendar import google_dwd

    def credentials(service_account_json, scopes, subject):
        fake.subjects.append(subject)
        return object()

    monkeypatch.setattr(google_dwd, "_service_account_credentials", credentials)
    monkeypatch.setattr(google_dwd, "_build", lambda *a, **kw: fake)
    return fake


def test_shared_mode_reads_the_named_calendar_as_itself(monkeypatch):
    """No subject (so no delegation), and the calendar is named by address."""
    from modules.meetings.calendar.google_dwd import GoogleDwdCalendarSource

    fake = _patch_google(monkeypatch, _RecordingGoogle())
    GoogleDwdCalendarSource(SERVICE_ACCOUNT_JSON, impersonate=False).list_events(
        user_email="someone@gmail.com", time_min=utc(2026, 9, 1), time_max=utc(2026, 9, 15)
    )
    assert fake.subjects == [None]
    assert fake.calls[0]["calendarId"] == "someone@gmail.com"


def test_delegated_mode_impersonates_and_reads_primary(monkeypatch):
    from modules.meetings.calendar.google_dwd import GoogleDwdCalendarSource

    fake = _patch_google(monkeypatch, _RecordingGoogle())
    GoogleDwdCalendarSource(SERVICE_ACCOUNT_JSON, impersonate=True).list_events(
        user_email="user@tenant.com", time_min=utc(2026, 9, 1), time_max=utc(2026, 9, 15)
    )
    assert fake.subjects == ["user@tenant.com"]
    assert fake.calls[0]["calendarId"] == "primary"


def test_a_full_read_never_asks_google_to_order_the_events(monkeypatch):
    """Live-probe fact 2: Google drops ``nextSyncToken`` from any response that
    carries an ``orderBy``, so asking for an order we do not need would cost us
    the token and make every later read a full one."""
    from modules.meetings.calendar.google_dwd import GoogleDwdCalendarSource

    fake = _patch_google(monkeypatch, _RecordingGoogle({"items": [], "nextSyncToken": "t1"}))
    page = GoogleDwdCalendarSource(SERVICE_ACCOUNT_JSON).list_events(
        user_email="someone@gmail.com", time_min=utc(2026, 9, 1), time_max=utc(2026, 9, 15)
    )
    assert "orderBy" not in fake.calls[0]
    assert page.next_sync_token == "t1"


def test_a_tokened_read_carries_no_window(monkeypatch):
    """Google rejects timeMin/timeMax alongside a syncToken."""
    from modules.meetings.calendar.google_dwd import GoogleDwdCalendarSource

    fake = _patch_google(monkeypatch, _RecordingGoogle())
    GoogleDwdCalendarSource(SERVICE_ACCOUNT_JSON).list_events(
        user_email="someone@gmail.com", sync_token="t1"
    )
    assert fake.calls[0]["syncToken"] == "t1"
    assert "timeMin" not in fake.calls[0] and "timeMax" not in fake.calls[0]


def test_the_fake_refuses_a_token_when_an_order_was_asked_for(db):
    """The regression guard for live-probe fact 2, on the source every sync test
    drives: if a future change puts ``orderBy`` back, the sync's token tests go
    red instead of the behaviour silently degrading in production."""
    source = FakeCalendarSource({"a@x.com": [SyncPage(events=[], next_sync_token="t1")]})

    with_order = source.list_events(user_email="a@x.com", order_by="startTime")
    assert with_order.next_sync_token is None

    without_order = source.list_events(user_email="a@x.com")
    assert without_order.next_sync_token == "t1"


# ── the per-user calendar address ────────────────────────────────────────────


def test_the_calendar_address_defaults_to_the_login_email(db):
    """NULL means "my login email" - what every DWD tenant uses."""
    from modules.meetings.services.optin import calendar_address_for

    user = _demo_user(db)
    row = opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    assert calendar_address_for(row, user) == user.email

    row.calendar_email = "personal@gmail.com"
    assert calendar_address_for(row, user) == "personal@gmail.com"


def test_the_sync_reads_the_override_not_the_login_email(db):
    """The whole point: the login email is not always shareable."""
    from modules.meetings.services.calendar_sync import sync_tenant
    from modules.meetings.models import CalendarEvent

    user = _demo_user(db)
    row = opt_in(db, DEFAULT_TENANT_ID, user.id)
    row.calendar_email = "personal@gmail.com"
    db.commit()

    source = FakeCalendarSource(
        {"personal@gmail.com": [SyncPage(events=[raw_event("g1", starts_at=utc(2026, 9, 1, 2))])]}
    )
    result = sync_tenant(db, DEFAULT_TENANT_ID, source, now=utc(2026, 8, 25))

    assert [c["user_email"] for c in source.calls] == ["personal@gmail.com"]
    assert result.events_upserted == 1
    # The mirrored row still belongs to the LOGGED-IN user, not to the address.
    assert db.query(CalendarEvent).one().calendar_user_id == user.id


def test_changing_the_address_drops_the_sync_token(db):
    """A token belongs to the calendar that minted it; replaying it against a
    different calendar is a 400 from Google, and a full read is the recovery."""
    from modules.meetings.services.optin import OptInService

    user = _demo_user(db)
    row = opt_in(db, DEFAULT_TENANT_ID, user.id)
    row.sync_token = "tok-1"
    db.commit()

    service = OptInService(db)
    kept = service.set(DEFAULT_TENANT_ID, user.id, True)
    assert kept.sync_token == "tok-1"  # a toggle write alone never touches it

    moved = service.set(
        DEFAULT_TENANT_ID, user.id, True,
        calendar_email="personal@gmail.com", set_calendar_email=True,
    )
    assert moved.calendar_email == "personal@gmail.com"
    assert moved.sync_token is None


def test_the_api_round_trips_the_calendar_address(meetings_client):
    """AC-S0-6 path, extended: the user sets which calendar to read."""
    headers = _auth(meetings_client)

    saved = meetings_client.put(
        "/meetings/optin",
        headers=headers,
        json={"enabled": True, "calendarEmail": "personal@gmail.com"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["calendarEmail"] == "personal@gmail.com"

    # An omitted key keeps it - flipping the toggle must not silently clear it.
    kept = meetings_client.put("/meetings/optin", headers=headers, json={"enabled": False})
    assert kept.json()["calendarEmail"] == "personal@gmail.com"

    # Sent as null clears it, back to the login email.
    cleared = meetings_client.put(
        "/meetings/optin", headers=headers, json={"enabled": True, "calendarEmail": None}
    )
    assert cleared.json()["calendarEmail"] is None


def test_a_malformed_calendar_address_is_refused(meetings_client):
    res = meetings_client.put(
        "/meetings/optin",
        headers=_auth(meetings_client),
        json={"enabled": True, "calendarEmail": "not-an-email"},
    )
    assert res.status_code == 422, res.text


# ── the Test button, in both modes ───────────────────────────────────────────


def test_shared_mode_test_probes_every_opted_in_calendar(db, monkeypatch):
    """Live-probe fact 1: ``calendarList`` is empty for a shared calendar, so the
    test READS each one instead."""
    from modules.meetings import providers as providers_module

    user = _demo_user(db)
    row = opt_in(db, DEFAULT_TENANT_ID, user.id)
    row.calendar_email = "personal@gmail.com"
    db.commit()

    probed = []
    monkeypatch.setattr(
        providers_module,
        "probe_calendar",
        lambda **kw: probed.append(kw["calendar_id"]),
    )
    result = providers_module.GoogleDwdProvider().test(
        {}, {"serviceAccountJson": SERVICE_ACCOUNT_JSON},
        db=db, tenant_id=DEFAULT_TENANT_ID,
    )

    assert probed == ["personal@gmail.com"]
    assert result.ok is True
    assert "personal@gmail.com" in result.message


def test_shared_mode_test_fails_with_googles_own_words_for_an_unshared_calendar(
    db, monkeypatch
):
    """The operator has to learn WHICH calendar was never shared, and why."""
    from modules.meetings import providers as providers_module

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    def boom(**kw):
        raise CalendarSourceError("Not Found")

    monkeypatch.setattr(providers_module, "probe_calendar", boom)
    result = providers_module.GoogleDwdProvider().test(
        {}, {"serviceAccountJson": SERVICE_ACCOUNT_JSON},
        db=db, tenant_id=DEFAULT_TENANT_ID,
    )

    assert result.ok is False
    assert user.email in result.message and "Not Found" in result.message
    # And it names the address the calendar has to be shared with.
    assert "notetaker@proj.iam.gserviceaccount.com" in result.message


def test_shared_mode_test_says_what_to_do_when_nobody_has_opted_in(db, monkeypatch):
    """There is nothing to read yet, so the connection is not verified - saying
    ok here would stamp it ACTIVE on the strength of having read nothing."""
    from modules.meetings import providers as providers_module

    def never(**kw):  # pragma: no cover - must not be reached
        raise AssertionError("Google must not be called with no calendars to read")

    monkeypatch.setattr(providers_module, "probe_calendar", never)
    result = providers_module.GoogleDwdProvider().test(
        {}, {"serviceAccountJson": SERVICE_ACCOUNT_JSON},
        db=db, tenant_id=DEFAULT_TENANT_ID,
    )

    assert result.ok is False
    assert "notetaker@proj.iam.gserviceaccount.com" in result.message


def test_shared_mode_test_never_calls_the_directory_api(db, monkeypatch):
    """No admin.directory scope is granted in this mode - reaching for it would
    fail for a reason that has nothing to do with the operator's problem."""
    from modules.meetings import providers as providers_module

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    def never(**kw):  # pragma: no cover - must not be reached
        raise AssertionError("shared mode must not touch the Directory API")

    monkeypatch.setattr(providers_module, "list_directory_users", never)
    monkeypatch.setattr(providers_module, "probe_calendar", lambda **kw: None)
    assert providers_module.GoogleDwdProvider().test(
        {}, {"serviceAccountJson": SERVICE_ACCOUNT_JSON},
        db=db, tenant_id=DEFAULT_TENANT_ID,
    ).ok is True


def test_core_hands_the_session_over_only_to_a_provider_that_asks(meetings_client):
    """The provider declares ``test_needs_context``; core passes db + tenant_id.
    Without that wiring the shared-mode test could never see an opt-in row."""
    from modules.meetings.providers import GoogleDwdProvider, MeetBotProvider

    assert GoogleDwdProvider.test_needs_context is True
    assert getattr(MeetBotProvider, "test_needs_context", False) is False

    headers = _auth(meetings_client)
    created = meetings_client.post(
        "/integrations/connections",
        headers=headers,
        json={
            "provider": "google_dwd",
            "name": "Workspace calendar",
            "config": {},
            "credentials": {"serviceAccountJson": SERVICE_ACCOUNT_JSON},
        },
    )
    assert created.status_code in (200, 201), created.text

    # Nobody has opted in, so the real (unmocked) shared test short-circuits
    # BEFORE any Google call and reports the address to share with - proof the
    # tenant's rows were actually reachable from inside the provider.
    res = meetings_client.post(
        f"/integrations/connections/{created.json()['id']}/test", headers=headers, json={}
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is False
    assert "notetaker@proj.iam.gserviceaccount.com" in res.json()["message"]


# ── the settings surface names the address to share with ─────────────────────


def test_the_settings_page_shows_the_service_account_address(meetings_client):
    headers = _auth(meetings_client)
    assert (
        meetings_client.get("/meetings/settings", headers=headers)
        .json()["calendarServiceAccountEmail"]
        is None
    )

    created = meetings_client.post(
        "/integrations/connections",
        headers=headers,
        json={
            "provider": "google_dwd",
            "name": "Workspace calendar",
            "config": {},
            "credentials": {"serviceAccountJson": SERVICE_ACCOUNT_JSON},
        },
    )
    assert created.status_code in (200, 201), created.text

    settings = meetings_client.get("/meetings/settings", headers=headers)
    assert (
        settings.json()["calendarServiceAccountEmail"]
        == "notetaker@proj.iam.gserviceaccount.com"
    )
    # The key itself never leaves the server.
    assert "private_key" not in settings.text
    assert SERVICE_ACCOUNT_JSON not in settings.text

    # And the user who actually has to share a calendar sees it too.
    optin = meetings_client.get("/meetings/optin", headers=headers)
    assert optin.json()["serviceAccountEmail"] == "notetaker@proj.iam.gserviceaccount.com"


# ── fixtures shared with the connections suite ───────────────────────────────


@pytest.fixture
def meetings_client(meetings_session_factory):
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

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


def _auth(client) -> dict:
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
